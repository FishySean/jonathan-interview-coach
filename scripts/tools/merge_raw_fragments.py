#!/usr/bin/env python3
"""合并 raw_videos/ 里 yt-dlp 未合并的音视频分片（*.f137.mp4 + *.f140.m4a → *.mp4）。"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from scripts.paths import RAW_VIDEOS_DIR, ensure_env_bin_on_path, resolve_ffmpeg, setup_path

setup_path()

FRAGMENT_RE = re.compile(r"^(?P<stem>.+)\.f(?P<code>\d+)$", re.IGNORECASE)


def find_fragment_groups(directory: Path) -> dict[str, dict[str, Path]]:
    """按标题 stem 分组：{'Title': {'137': path, '140': path}}。"""
    groups: dict[str, dict[str, Path]] = defaultdict(dict)
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = FRAGMENT_RE.match(path.stem)
        if not match:
            continue
        groups[match.group("stem")][match.group("code")] = path
    return groups


def merge_pair(video: Path, audio: Path, output: Path, ffmpeg: Path) -> None:
    env = {**os.environ, "PATH": ensure_env_bin_on_path()}
    cmd = [
        str(ffmpeg),
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-c",
        "copy",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)


def merge_orphaned_fragments(directory: Path | None = None) -> tuple[int, int, int]:
    """
    合并目录中的分片。

    Returns:
        (merged, skipped, failed)
    """
    directory = directory or RAW_VIDEOS_DIR
    if not directory.exists():
        return (0, 0, 0)

    ffmpeg = resolve_ffmpeg()
    if ffmpeg is None:
        groups = find_fragment_groups(directory)
        if groups:
            raise RuntimeError(
                f"发现 {len(groups)} 组未合并分片，但找不到 ffmpeg。"
                "请: conda install -n jonathan-coach ffmpeg"
            )
        return (0, 0, 0)

    groups = find_fragment_groups(directory)
    if not groups:
        return (0, 0, 0)

    merged = 0
    skipped = 0
    failed = 0

    for stem, parts in sorted(groups.items()):
        video = next(
            (parts[k] for k in sorted(parts) if parts[k].suffix.lower() == ".mp4"),
            None,
        )
        audio = next(
            (
                parts[k]
                for k in sorted(parts)
                if parts[k].suffix.lower() in {".m4a", ".webm", ".mp3"}
            ),
            None,
        )
        if video is None or audio is None:
            print(f"跳过（缺少视频或音频）: {stem} → {list(parts)}")
            skipped += 1
            continue

        output = directory / f"{stem}.mp4"
        if output.exists() and output.stat().st_size > 0:
            print(f"已有完整文件，清理分片: {output.name}")
            video.unlink(missing_ok=True)
            audio.unlink(missing_ok=True)
            skipped += 1
            continue

        print(f"合并: {video.name} + {audio.name} → {output.name}")
        try:
            merge_pair(video, audio, output, ffmpeg)
            video.unlink(missing_ok=True)
            audio.unlink(missing_ok=True)
            merged += 1
        except subprocess.CalledProcessError as exc:
            failed += 1
            print(f"  失败: {exc.stderr or exc}", file=sys.stderr)

    return merged, skipped, failed


def main() -> None:
    ensure_env_bin_on_path()
    directory = RAW_VIDEOS_DIR
    if not directory.exists():
        print(f"目录不存在: {directory}", file=sys.stderr)
        sys.exit(1)

    try:
        merged, skipped, failed = merge_orphaned_fragments(directory)
    except RuntimeError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)

    if merged == 0 and skipped == 0 and failed == 0:
        print("没有发现未合并分片。")
    else:
        print(f"\n完成: 合并 {merged}，跳过 {skipped}，失败 {failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
