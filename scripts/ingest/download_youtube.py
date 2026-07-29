#!/usr/bin/env python3
"""
从 YouTube Shorts URL 列表下载视频到 raw_videos/。

支持断点续跑：本地已有完整 .mp4 时跳过下载；archive 命中但缺文件时自动重下。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yt_dlp

from scripts.paths import (
    RAW_VIDEOS_DIR,
    ensure_env_bin_on_path,
    resolve_ffmpeg,
    setup_path,
)
from scripts.pipeline.video_registry import VideoRegistry, extract_video_id
from scripts.tools.merge_raw_fragments import merge_orphaned_fragments
from scripts.transcribe.transcribe import is_transcribable_video

setup_path()
ensure_env_bin_on_path()


def load_urls_from_file(path: Path) -> list[str]:
    """从文本文件读取 URL，每行一个，忽略空行和 # 注释。"""
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def _archive_has(archive_path: Path, video_id: str) -> bool:
    if not archive_path.exists():
        return False
    return any(
        video_id in line.split()
        for line in archive_path.read_text(encoding="utf-8").splitlines()
    )


def _remove_from_archive(archive_path: Path, video_id: str) -> None:
    if not archive_path.exists():
        return
    lines = [
        line
        for line in archive_path.read_text(encoding="utf-8").splitlines()
        if video_id not in line.split()
    ]
    archive_path.write_text(
        "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )


def _find_complete_video(output_dir: Path, stem: str) -> Path | None:
    """查找可转录的完整视频（优先 stem.mp4）。"""
    for ext in (".mp4", ".webm", ".mkv"):
        path = output_dir / f"{stem}{ext}"
        if path.exists() and is_transcribable_video(path):
            return path
    for path in output_dir.iterdir():
        if path.is_file() and path.stem == stem and is_transcribable_video(path):
            return path
    return None


def _list_complete_videos(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    return sorted(p for p in output_dir.iterdir() if is_transcribable_video(p))


def _stem_from_info(ydl: yt_dlp.YoutubeDL, info: dict, outtmpl: str) -> str:
    prepared = Path(ydl.prepare_filename(info, outtmpl=outtmpl))
    return prepared.stem


def _base_ydl_opts(outtmpl: str, ffmpeg: Path) -> dict:
    opts: dict = {
        "outtmpl": outtmpl,
        "restrictfilenames": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "ignoreerrors": False,
        "noplaylist": True,
        "quiet": False,
        "ffmpeg_location": str(ffmpeg.parent),
    }
    if os.environ.get("JONATHAN_COACH_NO_OVERWRITES") == "1":
        opts["overwrites"] = False
    return opts


def download_videos(
    urls: list[str],
    output_dir: Path = RAW_VIDEOS_DIR,
    *,
    registry: VideoRegistry | None = None,
) -> dict[str, int]:
    """下载视频；本地已有完整文件时记为成功（断点续跑）。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    ensure_env_bin_on_path()

    ffmpeg = resolve_ffmpeg()
    if ffmpeg is None:
        raise RuntimeError(
            "找不到 ffmpeg。分离音视频无法合并成可转录的 .mp4。\n"
            "请运行: conda install -n jonathan-coach -y ffmpeg"
        )

    # 先合并上次失败留下的分片
    try:
        merged, _, merge_failed = merge_orphaned_fragments(output_dir)
        if merged:
            print(f"续跑：先合并了 {merged} 组未完成分片")
        if merge_failed:
            print(f"警告: {merge_failed} 组分片合并失败", file=sys.stderr)
    except RuntimeError as exc:
        print(f"警告: {exc}", file=sys.stderr)

    pending_urls: list[str] = []
    skipped_transcribed = 0
    for url in urls:
        video_id = extract_video_id(url)
        if registry and video_id and registry.is_transcribed(video_id):
            print(f"跳过（已转录，registry）: {video_id}")
            skipped_transcribed += 1
            continue
        pending_urls.append(url)

    if not pending_urls:
        local_n = len(_list_complete_videos(output_dir))
        print(f"没有需要下载的新视频（本地完整视频 {local_n} 个）。")
        return {"ok": 0, "skipped": skipped_transcribed, "failed": 0, "local": local_n}

    archive_env = os.environ.get("JONATHAN_COACH_DOWNLOAD_ARCHIVE")
    archive_file = Path(archive_env) if archive_env else None
    outtmpl = str(output_dir / "%(title)s.%(ext)s")

    # 关键：元数据查询绝不能带 download_archive，否则已登记 ID 会返回 None
    meta_opts = _base_ydl_opts(outtmpl, ffmpeg)
    download_opts = _base_ydl_opts(outtmpl, ffmpeg)
    if archive_file:
        download_opts["download_archive"] = str(archive_file)

    print(f"输出目录: {output_dir}")
    print(f"ffmpeg: {ffmpeg}")
    print(f"待处理: {len(pending_urls)} 个视频")
    print(f"本地已有完整视频: {len(_list_complete_videos(output_dir))} 个\n")

    ok = 0
    skipped = skipped_transcribed
    failed = 0

    with yt_dlp.YoutubeDL(meta_opts) as ydl_meta, yt_dlp.YoutubeDL(download_opts) as ydl_dl:
        for i, url in enumerate(pending_urls, start=1):
            print(f"[{i}/{len(pending_urls)}] {url}")
            video_id = extract_video_id(url) or ""
            try:
                # 1) 仅取元数据（无视 archive）
                info = ydl_meta.extract_info(url, download=False)
                if not isinstance(info, dict):
                    raise RuntimeError("无法解析视频信息（extract_info 返回空）")

                video_id = str(info.get("id") or video_id)
                if registry and video_id and registry.is_transcribed(video_id):
                    print(f"  跳过（已转录）: {video_id}")
                    skipped += 1
                    continue

                stem = _stem_from_info(ydl_meta, info, outtmpl)

                # 2) 断点续跑：本地已有完整文件 → 成功
                existing = _find_complete_video(output_dir, stem)
                if existing:
                    print(f"  续跑：本地已有 → {existing.name}")
                    if registry and video_id:
                        registry.mark_downloaded(
                            video_id,
                            url=url,
                            title=str(info.get("title") or ""),
                            filename_stem=stem,
                        )
                    ok += 1
                    continue

                # 3) registry 里记过 stem，再查一次
                if registry and video_id:
                    entry = registry._videos.get(video_id, {})
                    alt_stem = entry.get("filename_stem") or entry.get("slug")
                    if alt_stem:
                        existing = _find_complete_video(output_dir, str(alt_stem))
                        if existing:
                            print(f"  续跑：本地已有（registry stem）→ {existing.name}")
                            registry.mark_downloaded(
                                video_id,
                                url=url,
                                title=str(info.get("title") or ""),
                                filename_stem=str(alt_stem),
                            )
                            ok += 1
                            continue

                # 4) archive 命中但本地没有 → 剔除后重下
                if archive_file and video_id and _archive_has(archive_file, video_id):
                    print(f"  archive 命中但缺完整文件，重新下载: {video_id}")
                    _remove_from_archive(archive_file, video_id)

                ydl_dl.download([url])
                merge_orphaned_fragments(output_dir)
                complete = _find_complete_video(output_dir, stem)
                if complete is None:
                    raise RuntimeError(
                        f"下载后未找到完整视频（stem={stem}）。"
                        "请检查 ffmpeg 合并是否成功。"
                    )

                if registry and video_id:
                    registry.mark_downloaded(
                        video_id,
                        url=url,
                        title=str(info.get("title") or ""),
                        filename_stem=stem,
                    )
                print(f"  成功: {complete.name}")
                ok += 1
            except Exception as exc:
                failed += 1
                print(f"  下载失败: {exc}", file=sys.stderr)

    local_n = len(_list_complete_videos(output_dir))
    print(
        f"\n完成。成功/续跑 {ok}，跳过 {skipped}，失败 {failed}；"
        f"本地完整视频 {local_n} 个。"
    )
    return {"ok": ok, "skipped": skipped, "failed": failed, "local": local_n}


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
        print(
            "  python -m scripts.ingest.download_youtube https://youtube.com/shorts/xxx",
            file=sys.stderr,
        )
        print(
            "  python -m scripts.ingest.download_youtube --file urls.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.download_archive:
        os.environ["JONATHAN_COACH_DOWNLOAD_ARCHIVE"] = str(args.download_archive)

    if args.no_overwrites:
        os.environ["JONATHAN_COACH_NO_OVERWRITES"] = "1"

    registry = VideoRegistry.load(args.registry) if args.registry else None

    try:
        result = download_videos(urls, registry=registry)
    except RuntimeError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(2)

    # 断点续跑：只要本地有可转录视频，或本轮有成功，就不因部分失败整批失败
    if result["failed"] > 0 and result["ok"] == 0 and result.get("local", 0) == 0:
        sys.exit(1)
    if result["failed"] > 0 and result["ok"] == 0 and result.get("local", 0) > 0:
        print(
            f"有 {result['failed']} 个 URL 处理失败，但本地已有 "
            f"{result['local']} 个完整视频，将继续后续步骤。",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
