#!/usr/bin/env python3
"""CLI：频道 Shorts → raw_videos → transcripts"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.paths import setup_path

setup_path()

from scripts.paths import PROJECT_ROOT
from scripts.pipeline import PipelineConfig, run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="频道 Shorts → raw_videos → transcripts")
    parser.add_argument("--channel", default="@MrJonathanCareer")
    parser.add_argument("--channel-url", default=None)
    parser.add_argument("--urls-out", type=Path, default=PROJECT_ROOT / "shorts_urls.txt")
    parser.add_argument("--download-archive", type=Path, default=PROJECT_ROOT / "download_archive.txt")
    parser.add_argument("--max-videos", type=int, default=0)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-transcribe", action="store_true")
    parser.add_argument("--language", default="en")
    parser.add_argument("--model", default="medium")
    parser.add_argument("--backend", default="faster-whisper", choices=["faster-whisper", "whisper"])
    parser.add_argument("--format", default="md", choices=["md", "txt"])
    args = parser.parse_args()

    config = PipelineConfig(
        channel=args.channel,
        channel_url=args.channel_url or "",
        max_videos=args.max_videos,
        language=args.language,
        model=args.model,
        backend=args.backend,
        output_format=args.format,
        skip_download=args.skip_download,
        skip_transcribe=args.skip_transcribe,
        urls_out=args.urls_out,
        download_archive=args.download_archive,
    )

    def on_event(kind: str, payload: dict) -> None:
        message = payload.get("message")
        if message:
            print(f"[{kind}] {message}")

    run_pipeline(config, on_event=on_event)


if __name__ == "__main__":
    main()
