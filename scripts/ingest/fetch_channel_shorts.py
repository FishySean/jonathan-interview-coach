#!/usr/bin/env python3
"""
从 YouTube 频道的 Shorts 页面提取所有 Shorts 视频的 URL。

输出：写入 urls 文本文件（每行一个 URL），供 download_youtube.py 使用。

说明：
- YouTube 对“频道 Shorts 页面”的结构可能随时间变化；本脚本依赖 yt-dlp 的页面解析能力。
- 若出现抓取到的视频数量不完整，可在下一步加分页/继续解析逻辑（后续优化点）。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yt_dlp

from scripts.paths import PROJECT_ROOT, SHORTS_URLS_FILE, VIDEO_REGISTRY_FILE, setup_path
from scripts.pipeline.video_registry import VideoRegistry, extract_video_id

setup_path()


def normalize_shorts_url(channel: str | None, channel_url: str | None) -> str:
    if channel_url:
        return channel_url
    if not channel:
        raise ValueError("缺少 --channel 或 --channel-url")

    channel = channel.strip()
    if channel.startswith("http://") or channel.startswith("https://"):
        # 若用户传的是频道主页但非 shorts 页面，则尽量追加 /shorts
        if "/shorts" in channel:
            return channel
        return channel.rstrip("/") + "/shorts"

    if channel.startswith("@"):
        return f"https://www.youtube.com/{channel}/shorts"

    # 允许用户直接传 MrJonathanCareer
    return f"https://www.youtube.com/@{channel}/shorts"


def _entry_to_url(entry: dict[str, Any]) -> str | None:
    for key in ("url", "webpage_url"):
        v = entry.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v

    vid = entry.get("id")
    if isinstance(vid, str) and vid:
        # 用 watch?v 兜底（yt-dlp 下游仍会定位到正确资源）
        return f"https://www.youtube.com/watch?v={vid}"

    return None


def extract_shorts_urls(
    shorts_page_url: str,
    *,
    strict_shorts: bool,
    max_videos: int,
    skip_processed_ids: set[str] | None = None,
) -> list[str]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        # 重点：尽量“扁平化”拿到条目列表，避免下载
        "extract_flat": True,
        "skip_download": True,
        # 防止把条目当成单条内容处理
        "noplaylist": False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(shorts_page_url, download=False)
        except TypeError:
            # 不同版本 yt-dlp 的签名可能有差异
            info = ydl.extract_info(shorts_page_url)

    entries = []
    if isinstance(info, dict):
        entries = info.get("entries") or []

    urls: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        url = _entry_to_url(entry)
        if not url:
            continue

        video_id = entry.get("id") if isinstance(entry.get("id"), str) else extract_video_id(url)
        if skip_processed_ids and video_id and video_id in skip_processed_ids:
            continue

        if strict_shorts:
            u = url.lower()
            title = str(entry.get("title", "")).lower()
            if ("/shorts/" not in u) and ("shorts" not in title):
                continue

        if url not in seen:
            seen.add(url)
            urls.append(url)

        if max_videos > 0 and len(urls) >= max_videos:
            break

    return urls


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 YouTube 频道 Shorts 的全部视频 URL")
    parser.add_argument(
        "--channel",
        default="@MrJonathanCareer",
        help="频道 handle（如 @MrJonathanCareer）",
    )
    parser.add_argument(
        "--channel-url",
        default=None,
        help="如果你已经有 Shorts 页面 URL，可直接传这里（优先级更高）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SHORTS_URLS_FILE,
        help="输出 urls 文件（每行一个 URL）",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=0,
        help="最多抓取多少个 Shorts（0 表示不限制）",
    )
    parser.add_argument(
        "--strict-shorts",
        action="store_true",
        help="只保留 URL/标题明显包含 shorts 的条目（默认：宽松）",
    )
    parser.add_argument(
        "--skip-processed",
        action="store_true",
        help="跳过已在 video registry 中标记为已转录的视频（不依赖本地视频文件）",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=VIDEO_REGISTRY_FILE,
        help="视频登记文件（默认 data/.video_registry.json）",
    )
    args = parser.parse_args()

    skip_ids: set[str] | None = None
    if args.skip_processed:
        registry = VideoRegistry.load(args.registry)
        skip_ids = registry.processed_ids()
        if skip_ids:
            print(f"已登记为处理完成: {len(skip_ids)} 个 video ID，抓取时将跳过")

    shorts_page_url = normalize_shorts_url(args.channel, args.channel_url)
    print(f"Shorts 页面: {shorts_page_url}")

    urls = extract_shorts_urls(
        shorts_page_url,
        strict_shorts=args.strict_shorts,
        max_videos=args.max_videos,
        skip_processed_ids=skip_ids,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")

    if args.skip_processed and args.max_videos > 0 and len(urls) < args.max_videos:
        print(
            f"已写入 {len(urls)} 个**新** Shorts URL（目标 {args.max_videos}，"
            f"频道里未处理的不足 {args.max_videos} 个）→ {args.output}"
        )
    else:
        print(f"已写入 {len(urls)} 个 Shorts URL → {args.output}")


if __name__ == "__main__":
    main()

