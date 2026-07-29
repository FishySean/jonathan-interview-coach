#!/usr/bin/env python3
"""
遍历 raw_videos/，用 Whisper 转录为文字，输出到 transcripts/。

用法:
    python -m scripts.transcribe
    python -m scripts.transcribe --model medium --backend faster-whisper
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.paths import RAW_VIDEOS_DIR, TRANSCRIPTS_DIR, VIDEO_REGISTRY_FILE, setup_path
from scripts.pipeline.video_registry import VideoRegistry

setup_path()

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".m4a", ".mp3", ".wav"}


def is_transcribable_video(path: Path) -> bool:
    """只转录完整视频，跳过 yt-dlp 残留的分片/未完成文件。"""
    if not path.is_file():
        return False
    name = path.name.lower()
    if name.endswith(".part"):
        return False
    if ".f" in name and (name.endswith(".m4a") or name.endswith(".mp4")):
        # 例如 xxx.f140.m4a / xxx.f137.mp4
        stem = path.stem
        if ".f" in stem and stem.rsplit(".f", 1)[-1].isdigit():
            return False
    return path.suffix.lower() in {".mp4", ".webm", ".mkv"}


def list_videos(input_dir: Path) -> list[Path]:
    """列出目录下所有可转录的完整视频文件。"""
    return sorted(p for p in input_dir.iterdir() if is_transcribable_video(p))


def transcribe_with_faster_whisper(
    video_path: Path,
    model: Any,
    language: str | None,
) -> tuple[str, list[dict]]:
    """使用已加载的 faster-whisper 模型转录。"""
    segments, _info = model.transcribe(
        str(video_path),
        language=language,
        vad_filter=True,
    )

    segment_list: list[dict] = []
    text_parts: list[str] = []
    for seg in segments:
        segment_list.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
        })
        text_parts.append(seg.text.strip())

    full_text = " ".join(text_parts)
    return full_text, segment_list


def load_faster_whisper_model(model_size: str) -> Any:
    from faster_whisper import WhisperModel

    print("正在加载 Whisper 模型（首次运行会从 HuggingFace 下载，请耐心等待）...")
    return WhisperModel(model_size, device="auto", compute_type="auto")


def transcribe_with_whisper_loaded(
    video_path: Path,
    model: Any,
    language: str | None,
) -> tuple[str, list[dict]]:
    """使用已加载的 OpenAI Whisper 模型转录。"""
    result = model.transcribe(str(video_path), language=language)

    segment_list = [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        for s in result.get("segments", [])
    ]
    return result["text"].strip(), segment_list


def load_whisper_model(model_size: str) -> Any:
    import whisper

    print("正在加载 Whisper 模型（首次运行会下载权重，请耐心等待）...")
    return whisper.load_model(model_size)


def format_markdown(
    video_path: Path,
    full_text: str,
    segments: list[dict],
    model: str,
    backend: str,
) -> str:
    """生成 Markdown 格式 transcript。"""
    lines = [
        f"# {video_path.stem}",
        "",
        f"- **源文件**: `{video_path.name}`",
        f"- **转录时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **模型**: {model} ({backend})",
        "",
        "## 全文",
        "",
        full_text,
        "",
        "## 分段",
        "",
    ]
    for seg in segments:
        start = _format_timestamp(seg["start"])
        end = _format_timestamp(seg["end"])
        lines.append(f"**[{start} → {end}]** {seg['text']}")
        lines.append("")

    return "\n".join(lines)


def format_plain_text(full_text: str) -> str:
    """生成纯文本 transcript。"""
    return full_text + "\n"


def _format_timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def delete_local_video_files(video_path: Path) -> None:
    """删除视频及同 stem 的分片/残留文件。"""
    parent = video_path.parent
    stem = video_path.stem
    removed = False
    for candidate in parent.iterdir():
        if not candidate.is_file():
            continue
        if candidate.stem == stem or candidate.name.startswith(f"{stem}."):
            candidate.unlink()
            print(f"已删除本地视频: {candidate.name}")
            removed = True
    if not removed and video_path.exists():
        video_path.unlink()
        print(f"已删除本地视频: {video_path.name}")


def cleanup_raw_videos_dir(
    video_dir: Path = RAW_VIDEOS_DIR,
    *,
    keep_names: frozenset[str] = frozenset({".gitkeep"}),
) -> list[str]:
    """清空 raw_videos/ 下所有媒体文件（pipeline 结束时兜底）。"""
    if not video_dir.exists():
        return []
    deleted: list[str] = []
    for path in sorted(video_dir.iterdir()):
        if not path.is_file() or path.name in keep_names:
            continue
        path.unlink()
        deleted.append(path.name)
        print(f"已删除本地视频: {path.name}")
    return deleted


def transcribe_file(
    video_path: Path,
    output_dir: Path,
    model_obj: Any,
    backend: str,
    model_name: str,
    language: str | None,
    output_format: str,
    force: bool,
    index: int,
    total: int,
    *,
    registry: VideoRegistry | None = None,
    delete_after: bool = False,
) -> Path | None:
    """转录单个文件并写入 transcripts/。"""
    ext = ".md" if output_format == "md" else ".txt"
    output_path = output_dir / f"{video_path.stem}{ext}"

    if output_path.exists() and not force:
        print(f"[PROGRESS] {index}/{total} 跳过（已存在）: {output_path.name}")
        if registry:
            registry.mark_transcribed_by_stem(
                video_path.stem,
                transcript_file=output_path.name,
            )
        if delete_after:
            delete_local_video_files(video_path)
        return output_path

    print(f"[PROGRESS] {index}/{total} 转录中: {video_path.name}")

    if backend == "faster-whisper":
        full_text, segments = transcribe_with_faster_whisper(video_path, model_obj, language)
    elif backend == "whisper":
        full_text, segments = transcribe_with_whisper_loaded(video_path, model_obj, language)
    else:
        raise ValueError(f"未知 backend: {backend}")

    if output_format == "md":
        content = format_markdown(video_path, full_text, segments, model_name, backend)
    else:
        content = format_plain_text(full_text)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"已保存: {output_path.name}")
    if registry:
        registry.mark_transcribed_by_stem(
            video_path.stem,
            transcript_file=output_path.name,
        )
    if delete_after:
        delete_local_video_files(video_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Whisper 转录 raw_videos/ → transcripts/")
    parser.add_argument(
        "--input-dir", "-i",
        type=Path,
        default=RAW_VIDEOS_DIR,
        help="视频输入目录（默认 raw_videos/）",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=TRANSCRIPTS_DIR,
        help="转录输出目录（默认 transcripts/）",
    )
    parser.add_argument(
        "--model", "-m",
        default="medium",
        help="Whisper 模型大小: tiny/base/small/medium/large-v3（默认 medium）",
    )
    parser.add_argument(
        "--backend", "-b",
        choices=["faster-whisper", "whisper"],
        default="faster-whisper",
        help="转录引擎（默认 faster-whisper）",
    )
    parser.add_argument(
        "--language", "-l",
        default=None,
        help="语言代码，如 en；留空则自动检测",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["md", "txt"],
        default="md",
        help="输出格式（默认 md）",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="只转录指定文件（相对于 input-dir 或绝对路径）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的 transcript",
    )
    parser.add_argument(
        "--delete-after",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="转录后删除本地视频（默认开启，用 --no-delete-after 保留）",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="视频登记文件；用于记录 video ID 与 transcript 对应关系",
    )
    args = parser.parse_args()

    registry = VideoRegistry.load(args.registry) if args.registry else None

    input_dir: Path = args.input_dir
    if not input_dir.exists():
        print(f"错误: 输入目录不存在 — {input_dir}", file=sys.stderr)
        sys.exit(1)

    if args.file:
        video_path = args.file if args.file.is_absolute() else input_dir / args.file
        videos = [video_path] if video_path.exists() else []
    else:
        videos = list_videos(input_dir)

    if not videos:
        print(f"未找到视频文件。请将视频放入 {input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"输入: {input_dir}")
    print(f"输出: {args.output_dir}")
    print(f"模型: {args.model} ({args.backend})")
    print(f"共 {len(videos)} 个文件\n")

    if args.backend == "faster-whisper":
        model_obj = load_faster_whisper_model(args.model)
    elif args.backend == "whisper":
        model_obj = load_whisper_model(args.model)
    else:
        raise ValueError(f"未知 backend: {args.backend}")

    print("Whisper 模型已就绪，开始转录。\n")

    for i, video in enumerate(videos, start=1):
        try:
            transcribe_file(
                video,
                args.output_dir,
                model_obj,
                args.backend,
                args.model,
                args.language,
                args.format,
                args.force,
                i,
                len(videos),
                registry=registry,
                delete_after=args.delete_after,
            )
        except Exception as exc:
            print(f"失败: {video.name} — {exc}", file=sys.stderr)

    print("\n完成。请检查 transcripts/ 目录。")


if __name__ == "__main__":
    main()
