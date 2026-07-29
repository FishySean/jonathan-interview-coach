#!/usr/bin/env python3
"""
LLM 蒸馏：transcript → distilled/by_video/ → 合并 skill/

可在代码中调用 run_distill()（pipeline / app 自动触发），也可 CLI 单独运行。

后端（代码里可调用，非 Cursor Agent）：
  - ollama   本地免费，推荐：brew install ollama && ollama pull qwen2.5:14b
  - openai   需 OPENAI_API_KEY
  - anthropic 需 ANTHROPIC_API_KEY

.env 示例见 .env.example

用法:
    python -m scripts.distill --limit 1
    python -m scripts.distill --merge-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.paths import (
    DISTILL_INDEX_FILE,
    DISTILLED_BY_VIDEO_DIR,
    PROJECT_ROOT,
    PROMPTS_DIR,
    SKILL_DIR,
    SKILL_FILE,
    TRANSCRIPTS_DIR,
    setup_path,
)
from scripts.pipeline.video_registry import VideoRegistry

setup_path()

PROMPT_FILE = PROMPTS_DIR / "distill_system.txt"

LogFn = Callable[[str], None]


@dataclass
class DistillConfig:
    backend: str = "auto"  # auto | ollama | openai | anthropic
    model: str | None = None
    limit: int = 0  # 0 = 处理所有待蒸馏
    force: bool = False
    merge: bool = True
    ollama_host: str = "http://127.0.0.1:11434"


@dataclass
class DistillResult:
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    skill_path: Path | None = None
    backend: str = ""
    model: str = ""


def load_env_file() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def load_index() -> dict:
    if DISTILL_INDEX_FILE.exists():
        return json.loads(DISTILL_INDEX_FILE.read_text(encoding="utf-8"))
    return {"completed": {}}


def save_index(index: dict) -> None:
    DISTILL_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    DISTILL_INDEX_FILE.write_text(json.dumps(index, indent=2), encoding="utf-8")


def extract_transcript_body(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    if "## 全文" in text:
        part = text.split("## 全文", 1)[1]
        if "## 分段" in part:
            part = part.split("## 分段", 1)[0]
        return part.strip()
    return text.strip()


def list_pending_transcripts(index: dict, force: bool) -> list[Path]:
    pending: list[Path] = []
    for path in sorted(TRANSCRIPTS_DIR.glob("*.md")):
        slug = path.stem
        if slug.endswith(".f140") or slug.endswith(".f137"):
            continue
        if force or slug not in index.get("completed", {}):
            pending.append(path)
    return pending


def ollama_available(host: str) -> bool:
    try:
        req = urllib.request.Request(f"{host.rstrip('/')}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def resolve_backend_and_model(config: DistillConfig) -> tuple[str, str]:
    load_env_file()
    backend = config.backend
    if backend == "auto":
        if ollama_available(config.ollama_host):
            backend = "ollama"
        elif os.environ.get("OPENAI_API_KEY"):
            backend = "openai"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            backend = "anthropic"
        else:
            raise RuntimeError(
                "未找到可用 LLM：请安装 Ollama（ollama pull qwen2.5:14b）"
                "或在 .env 配置 OPENAI_API_KEY"
            )

    defaults = {
        "ollama": config.model or os.environ.get("OLLAMA_MODEL", "qwen2.5:14b"),
        "openai": config.model or os.environ.get("OPENAI_MODEL", "gpt-4o"),
        "anthropic": config.model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
    }
    if backend not in defaults:
        raise ValueError(f"未知 backend: {backend}")

    if backend == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("需要 OPENAI_API_KEY（写入 .env）")
    if backend == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("需要 ANTHROPIC_API_KEY")
    if backend == "ollama" and not ollama_available(config.ollama_host):
        raise RuntimeError(
            f"Ollama 未运行（{config.ollama_host}）。"
            "安装: brew install ollama && ollama serve && ollama pull qwen2.5:14b"
        )

    return backend, defaults[backend]


def call_openai(system: str, user: str, model: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


def call_anthropic(system: str, user: str, model: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=0.3,
    )
    parts = [b.text for b in msg.content if hasattr(b, "text")]
    return "\n".join(parts)


def call_ollama(system: str, user: str, model: str, host: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.3},
    }
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("message", {}).get("content", "")


def distill_one(
    transcript_path: Path,
    *,
    backend: str,
    model: str,
    system_prompt: str,
    ollama_host: str,
) -> str:
    body = extract_transcript_body(transcript_path)
    user_msg = f"# Source transcript\n\nFile: `{transcript_path.name}`\n\n{body}"
    if backend == "openai":
        return call_openai(system_prompt, user_msg, model)
    if backend == "anthropic":
        return call_anthropic(system_prompt, user_msg, model)
    if backend == "ollama":
        return call_ollama(system_prompt, user_msg, model, ollama_host)
    raise ValueError(f"未知 backend: {backend}")


def merge_skill() -> Path:
    parts_dir = DISTILLED_BY_VIDEO_DIR
    files = sorted(parts_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"没有蒸馏文件: {parts_dir}")

    video_blocks: list[str] = []
    for f in files:
        title = f.stem.replace("_", " ")
        body = f.read_text(encoding="utf-8")
        body = re.sub(r"^<!--.*?-->\n*", "", body, flags=re.MULTILINE)
        video_blocks.append(f"### {title}\n\n{body.strip()}")

    skill = f"""# Jonathan Interview Coach

> Merged from **{len(files)}** Jonathan Career Shorts distillations.
> **Use this file** as Claude Project Knowledge or a Claude Code skill.
> Enable only for mock interviews — not for everyday chat.

## Role

You are a Jonathan-style interview coach.

Your goal: help candidates improve through rigorous questioning — not by giving easy answers, but by exposing weak spots and teaching them how interviewers actually think.

**Activation:** Only adopt this persona when the user explicitly asks for interview coaching, mock interviews, or says **「Jonathan 模式」**.

## How to use this knowledge

- Synthesize patterns across videos below; do not quote transcripts verbatim.
- When coaching, apply: principles → evaluation → follow-up questions → answer frameworks.
- Be rigorous. Push for specifics, ownership, and measurable impact.

## Video Insights（按 Short 蒸馏，随 pipeline 增量追加）

"""
    skill += "\n\n".join(video_blocks)
    skill += "\n\n## Source index\n\n"
    for f in files:
        skill += f"- `{f.stem}`\n"
    skill += f"\n---\n\n*Last merged: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | {len(files)} videos*\n"

    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    SKILL_FILE.write_text(skill, encoding="utf-8")
    return SKILL_FILE


def run_distill(
    config: DistillConfig | None = None,
    on_log: LogFn | None = None,
) -> DistillResult:
    """供 pipeline / app 调用的蒸馏入口（非 Cursor Agent）。"""
    config = config or DistillConfig()
    load_env_file()

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)
        else:
            print(msg)

    backend, model = resolve_backend_and_model(config)
    result = DistillResult(backend=backend, model=model)

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    index = load_index()
    pending = list_pending_transcripts(index, config.force)
    if config.limit > 0:
        pending = pending[: config.limit]

    if not pending:
        log("没有待蒸馏的 transcript，尝试合并已有 Skill…")
        if config.merge and list(DISTILLED_BY_VIDEO_DIR.glob("*.md")):
            result.skill_path = merge_skill()
            log(f"Skill 已更新 → {result.skill_path}")
        return result

    DISTILLED_BY_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    log(f"蒸馏后端: {backend} | 模型: {model} | 待处理: {len(pending)} 个")

    for i, path in enumerate(pending, start=1):
        slug = path.stem
        log(f"[PROGRESS] {i}/{len(pending)} 蒸馏: {slug}")
        try:
            content = distill_one(
                path,
                backend=backend,
                model=model,
                system_prompt=system_prompt,
                ollama_host=config.ollama_host,
            )
            out_path = DISTILLED_BY_VIDEO_DIR / f"{slug}.md"
            out_path.write_text(
                f"<!-- source: {path.name} | model: {model} ({backend}) -->\n\n{content.strip()}\n",
                encoding="utf-8",
            )
            index.setdefault("completed", {})[slug] = {
                "transcript": path.name,
                "distilled": out_path.name,
                "model": model,
                "backend": backend,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            save_index(index)
            result.processed += 1
            log(f"已保存: {out_path.name}")
            VideoRegistry.load().mark_distilled_by_slug(slug)
        except Exception as exc:
            result.failed += 1
            log(f"失败: {slug} — {exc}")
        time.sleep(0.3)

    if config.merge and (
        result.processed > 0 or list(DISTILLED_BY_VIDEO_DIR.glob("*.md"))
    ):
        try:
            result.skill_path = merge_skill()
            log(f"Skill 已更新 → {result.skill_path}")
        except FileNotFoundError:
            pass

    return result


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="LLM 蒸馏 transcripts → skill")
    parser.add_argument("--limit", type=int, default=0, help="本次最多处理几个（0=全部）")
    parser.add_argument("--backend", choices=["auto", "ollama", "openai", "anthropic"], default="auto")
    parser.add_argument("--model", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--merge-only", action="store_true")
    parser.add_argument("--no-merge", action="store_true")
    args = parser.parse_args()

    if args.merge_only:
        out = merge_skill()
        print(f"已合并 → {out}")
        return

    cfg = DistillConfig(
        backend=args.backend,
        model=args.model,
        limit=args.limit,
        force=args.force,
        merge=not args.no_merge,
    )
    result = run_distill(cfg)
    print(f"\n完成: 成功 {result.processed}, 失败 {result.failed}, 后端 {result.backend}/{result.model}")


if __name__ == "__main__":
    main()
