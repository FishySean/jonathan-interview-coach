#!/usr/bin/env python3
"""
修复下载不完整或转录错误的单个视频。

默认修复：A_quick_and_simple_way_to_reduce_your_career_anxiety
（原下载 HTTP 500，只留下了 .f140.m4a 分片）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.paths import DOWNLOAD_ARCHIVE_FILE, RAW_VIDEOS_DIR, TRANSCRIPTS_DIR, ensure_env_bin_on_path, setup_path

setup_path()
ensure_env_bin_on_path()

from scripts.ingest.download_youtube import download_videos
from scripts.transcribe.transcribe import load_faster_whisper_model, transcribe_file

DEFAULT_URL = "https://www.youtube.com/shorts/qqOGnMsaDfA"
BAD_STEM = "A_quick_and_simple_way_to_reduce_your_career_anxiety"


def cleanup_partial_files(stem: str) -> None:
    patterns = [
        f"{stem}.*",
        f"{stem}.f*.*",
    ]
    for path in RAW_VIDEOS_DIR.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if name.startswith(stem):
            print(f"删除不完整文件: {name}")
            path.unlink()

    for path in TRANSCRIPTS_DIR.glob(f"{stem}*"):
        print(f"删除错误 transcript: {path.name}")
        path.unlink()


def remove_from_download_archive(video_id: str) -> None:
  """允许 yt-dlp 重新下载（从 archive 移除该条目）。"""
  if not DOWNLOAD_ARCHIVE_FILE.exists():
    return
  lines = [
    line for line in DOWNLOAD_ARCHIVE_FILE.read_text(encoding="utf-8").splitlines()
    if video_id not in line
  ]
  DOWNLOAD_ARCHIVE_FILE.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="重新下载并转录损坏的视频")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--stem", default=BAD_STEM)
    parser.add_argument("--model", default="small", help="转录模型（small 更快）")
    args = parser.parse_args()

    cleanup_partial_files(args.stem)

    # 从 URL 提取 video id（shorts/XXXX）
    vid = args.url.rstrip("/").split("/")[-1]
    remove_from_download_archive(vid)

    print(f"\n重新下载: {args.url}")
    download_videos([args.url], output_dir=RAW_VIDEOS_DIR)

    # 找到新下载的 mp4（标题可能与 stem 略有不同）
    videos = sorted(RAW_VIDEOS_DIR.glob("A_quick_and_simple*.mp4"))
    if not videos:
        print("错误: 未找到重新下载的 mp4", file=sys.stderr)
        sys.exit(1)

    video = videos[0]
    print(f"\n转录: {video.name}")
    model = load_faster_whisper_model(args.model)
    transcribe_file(
        video,
        TRANSCRIPTS_DIR,
        model,
        "faster-whisper",
        args.model,
        "en",
        "md",
        force=True,
        index=1,
        total=1,
    )
    print("\n修复完成。")


if __name__ == "__main__":
    main()
