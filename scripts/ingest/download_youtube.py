#!/usr/bin/env python3
"""
从 YouTube Shorts URL 列表下载视频到 raw_videos/。

用法:
    python -m scripts.ingest.download_youtube URL1 URL2 ...
    python -m scripts.ingest.download_youtube --file urls.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yt_dlp

from scripts.paths import RAW_VIDEOS_DIR, VIDEO_REGISTRY_FILE, setup_path
from scripts.pipeline.video_registry import VideoRegistry, extract_video_id

setup_path()


def load_urls_from_file(path: Path) -> list[str]:
    """从文本文件读取 URL，每行一个，忽略空行和 # 注释。"""
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def download_videos(
    urls: list[str],
    output_dir: Path = RAW_VIDEOS_DIR,
    *,
    registry: VideoRegistry | None = None,
) -> None:
    """下载视频，文件名使用视频标题。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    import os

    pending_urls: list[str] = []
    for url in urls:
        video_id = extract_video_id(url)
        if registry and video_id and registry.is_transcribed(video_id):
            print(f"跳过（已转录，registry）: {video_id} — {url}")
            continue
        pending_urls.append(url)

    if not pending_urls:
        print("没有需要下载的新视频。")
        return

    ydl_opts = {
        # %(title)s 保留原标题；restrictfilenames 避免特殊字符导致路径问题
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "restrictfilenames": True,
        # Shorts 通常较短，优先 mp4
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "ignoreerrors": True,
        "noplaylist": True,
        "quiet": False,
    }

    # 可选：用于自动化“只下载一次”
    download_archive = os.environ.get("JONATHAN_COACH_DOWNLOAD_ARCHIVE")
    if download_archive:
        ydl_opts["download_archive"] = download_archive

    # 可选：避免覆盖同名文件（相同 title 时仍建议优先 download-archive）
    if os.environ.get("JONATHAN_COACH_NO_OVERWRITES") == "1":
        ydl_opts["overwrites"] = False

    print(f"输出目录: {output_dir}")
    print(f"待下载: {len(pending_urls)} 个视频\n")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for i, url in enumerate(pending_urls, start=1):
            print(f"[{i}/{len(pending_urls)}] {url}")
            try:
                info = ydl.extract_info(url, download=False)
                video_id = info.get("id") if isinstance(info, dict) else extract_video_id(url)
                if registry and video_id and registry.is_transcribed(str(video_id)):
                    print(f"  跳过（已转录）: {video_id}")
                    continue
                ydl.download([url])
                if registry and video_id:
                    title = info.get("title") if isinstance(info, dict) else None
                    # yt-dlp restrictfilenames 后的 stem 与标题近似
                    stem = ydl.prepare_filename(info, outtmpl=ydl_opts["outtmpl"])
                    filename_stem = Path(stem).stem
                    registry.mark_downloaded(
                        str(video_id),
                        url=url,
                        title=str(title) if title else None,
                        filename_stem=filename_stem,
                    )
            except Exception as exc:
                print(f"  下载失败: {exc}")

    print("\n完成。请检查 raw_videos/ 目录。")


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 YouTube Shorts 到 raw_videos/")
    parser.add_argument("urls", nargs="*", help="YouTube URL（可多个）")
    parser.add_argument(
        "--file", "-f",
        type=Path,
        help="包含 URL 列表的文本文件（每行一个）",
    )
    parser.add_argument(
        "--download-archive",
        type=Path,
        default=None,
        help="yt-dlp 的 download archive 文件（用于避免重复下载）。",
    )
    parser.add_argument(
        "--no-overwrites",
        action="store_true",
        help="不覆盖已存在的文件（如果同名文件已存在）。",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="视频登记文件；提供则跳过已转录的 URL",
    )
    args = parser.parse_args()

    urls: list[str] = list(args.urls)
    if args.file:
        if not args.file.exists():
            print(f"错误: 文件不存在 — {args.file}", file=sys.stderr)
            sys.exit(1)
        urls.extend(load_urls_from_file(args.file))

    if not urls:
        print("用法示例:", file=sys.stderr)
        print("  python -m scripts.ingest.download_youtube https://youtube.com/shorts/xxx", file=sys.stderr)
        print("  python -m scripts.ingest.download_youtube --file urls.txt", file=sys.stderr)
        sys.exit(1)

    # 需要把下载选项透传到 yt-dlp，这里用一个轻量方式：直接修改 ydl_opts 的相关键
    # 为了保持脚本结构不大改，我们在 download_videos 内部保持 ydl_opts 固定，
    # 这里只把 archive/no-overwrites 变成“下载前行为”。
    #
    # 实现方式：如果提供 download-archive，则把它写到环境变量里，供 download_videos 读取。
    if args.download_archive:
        os_env_key = "JONATHAN_COACH_DOWNLOAD_ARCHIVE"
        import os

        os.environ[os_env_key] = str(args.download_archive)

    if args.no_overwrites:
        os_env_key = "JONATHAN_COACH_NO_OVERWRITES"
        import os

        os.environ[os_env_key] = "1"

    registry = VideoRegistry.load(args.registry) if args.registry else None

    # 调用下载
    download_videos(urls, registry=registry)


if __name__ == "__main__":
    main()
