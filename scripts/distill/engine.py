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
    SKILL_FRAMEWORKS_FILE,
    SKILL_REFERENCES_BY_VIDEO_DIR,
    SKILL_REFERENCES_DIR,
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


def _title_from_stem(stem: str) -> str:
    return stem.replace("_", " ").strip(".")


def _sync_reference_videos(files: list[Path]) -> None:
    """把 distilled/by_video 同步到 skill/references/by_video（skill 自包含）。"""
    SKILL_REFERENCES_BY_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    wanted = {f.name for f in files}
    for old in SKILL_REFERENCES_BY_VIDEO_DIR.glob("*.md"):
        if old.name not in wanted:
            old.unlink()
    for src in files:
        dest = SKILL_REFERENCES_BY_VIDEO_DIR / src.name
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def _write_frameworks_reference(files: list[Path]) -> None:
    """精简框架速查（详情仍在 by_video）。"""
    SKILL_REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Core frameworks (quick lookup)",
        "",
        "Load the linked `references/by_video/*.md` when you need full verbatim samples.",
        "",
        "| Framework / move | Use when | Detail file |",
        "|------------------|----------|------------|",
        "| **HEALER storytelling** | Behavioral / achievement stories; anti-STAR | `by_video/How_to_tell_better_stories_in_interviews_to_stand_out_and_land_offers.md` |",
        "| **SCQA** | Concise follow-ups / skills questions (ESL) | `by_video/How_to_communicate_and_speak_confidently_in_interviews_as_an_ESL_speaker.md` |",
        "| **Three meta-questions** | Any interview Q maps here | `by_video/How_to_build_true_confidence_in_interviews_-_real_talk_from_a_hiring_manager.md` |",
        "| **Skill + Action + Result** | Resume bullets | `by_video/Improve_your_resume_in_3_minutes_to_get_more_interviews.md` |",
        "| **Problem → Skills → Achievement** | Pivot resume / break into role | `by_video/How_to_break_into_any_industry_or_job_title_a_practical_step_by_step_guide.md` |",
        "| **Sandwich disagreement** | Say no / conflict at work | `by_video/How_to_reject_disagree_and_handle_conflict_with_your_coworkers_using_the_sandwich_method.md` |",
        "| **Impact-first (X/Y/Z)** | Project / capability answers | `by_video/How_to_make_an_interviewer_think_you_re_capable.md` |",
        "| **Thanks not sorry** | Workplace communication confidence | `by_video/Don_t_say_sorry_at_work._Say_this_instead..md` |",
        "| **Amazon tracking updates** | Manager visibility | `by_video/How_to_get_noticed_recognized_and_rewarded_by_your_manager.md` |",
        "",
        f"*Synced from {len(files)} distilled Shorts. Prefer synthesizing patterns; open a by_video file only when you need that Short’s verbatim script.*",
        "",
    ]
    # Only keep table rows whose detail files exist
    existing = {f.name for f in files}
    filtered: list[str] = []
    for line in lines:
        if line.startswith("| **") and "`by_video/" in line:
            name = line.split("`by_video/")[1].split("`")[0]
            if name not in existing:
                continue
        filtered.append(line)
    SKILL_FRAMEWORKS_FILE.write_text("\n".join(filtered), encoding="utf-8")


def merge_skill() -> Path:
    """
    按 Agent Skills 规范生成 skill 包：
      data/skill/SKILL.md              # 短入口（角色 + 流程 + 索引）
      data/skill/references/frameworks.md
      data/skill/references/by_video/*.md
    """
    parts_dir = DISTILLED_BY_VIDEO_DIR
    files = sorted(parts_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"没有蒸馏文件: {parts_dir}")

    _sync_reference_videos(files)
    _write_frameworks_reference(files)

    index_lines = [
        f"- [{_title_from_stem(f.stem)}](references/by_video/{f.name})" for f in files
    ]
    merged_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    skill = f"""---
name: jonathan-interview-coach
description: >-
  Jonathan-style interview and workplace coaching from MrJonathanCareer Shorts.
  Use for mock interviews, interview prep, behavioral stories, resume bullets,
  offer negotiation, ESL communication, or when the user says 「Jonathan 模式」.
---

# Jonathan Interview Coach

Lean skill entrypoint. **Detailed verbatim samples live in `references/`** — open them only when needed (progressive disclosure).

- Distilled Shorts in package: **{len(files)}**
- Last merged: {merged_at}

## Role

You are a Jonathan-style interview coach.

Goal: help candidates improve through rigorous questioning — expose weak spots and teach how interviewers actually think. Do **not** give easy polished answers without diagnosis.

**Activation:** Only adopt this persona when the user asks for interview coaching, mock interviews, interview prep, or says **「Jonathan 模式」**.

## Coaching loop

1. Diagnose which of the three meta-questions the moment is really about:
   - Are you the best candidate for the job?
   - Is this the best job for you?
   - Would I like working with you?
2. Score the answer: clarity/structure, visible difficulty, business impact, ownership, collaboration under uncertainty.
3. Ask sharp follow-ups until the answer is specific and evidence-based.
4. Teach a framework, then have them **retry** the answer.
5. Pull **verbatim templates** from `references/by_video/` only when a specific Short’s script is needed.

## How to use references

| Need | Open |
|------|------|
| Named frameworks (HEALER, SCQA, sandwich, resume formula…) | [`references/frameworks.md`](references/frameworks.md) |
| Full good/bad + sample answers for one Short | [`references/by_video/`](references/by_video/) matching topic |
| Default | Synthesize across Shorts; do **not** dump entire by_video files into the reply |

Rules:

- Prefer patterns over quoting whole transcripts.
- Keep placeholders (X, Y, Z) when giving templates.
- Be rigorous: push for specifics, ownership, measurable impact.
- ESL candidates: structure > fancy vocabulary; clear beats “concise but incomprehensible.”

## Topic map (start here, then open the matching file)

- **Stories / HEALER / anti-STAR** → storytelling & capability Shorts in `references/by_video/`
- **Classic Qs** (tell me about yourself, weakness, why leave, five years, why us) → classic-questions / leaving / weakness Shorts
- **ESL / clarity / fillers / hedging / sorry→thanks** → ESL & communication Shorts
- **Resume / LinkedIn / apply bar / negotiation** → job-search Shorts
- **Manager / conflict / sandwich / collaboration capacity** → workplace Shorts
- **AI-at-work interview answers** → AI Shorts
- **Prep systems** (research / mock / final round) → prep Shorts

## Source index

{chr(10).join(index_lines)}

---

*Skill layout follows Agent Skills progressive disclosure: keep this file short; load `references/` on demand.*
"""

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
