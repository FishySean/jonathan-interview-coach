#!/usr/bin/env python3
"""
从 YouTube Shorts URL 列表下载视频到 raw_videos/。

支持断点续跑：本地已有完整 .mp4 时跳过下载；archive 命中但缺文件时自动重下。
默认读取本机浏览器 Cookie + node JS runtime，减轻 YouTube 429 / bot 验证。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
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


def _resolve_cookies_from_browser() -> tuple[str, ...] | None:
    """
    让 yt-dlp 读取本机浏览器登录态，缓解 YouTube bot / 429。
    环境变量 JONATHAN_COACH_COOKIES_FROM_BROWSER:
      - 未设置: 自动尝试 chrome → safari → edge
      - chrome / safari / …: 指定浏览器
      - off / 0 / none: 禁用
    """
    raw = os.environ.get("JONATHAN_COACH_COOKIES_FROM_BROWSER", "").strip()
    if raw.lower() in {"0", "off", "none", "false", "no"}:
        return None
    if raw:
        return (raw,)

    home = Path.home()
    candidates = [
        (
            "chrome",
            home / "Library/Application Support/Google/Chrome/Default/Cookies",
        ),
        (
            "safari",
            home / "Library/Cookies/Cookies.binarycookies",
        ),
        (
            "edge",
            home / "Library/Application Support/Microsoft Edge/Default/Cookies",
        ),
    ]
    for name, path in candidates:
        if path.exists():
            return (name,)
    return None


def _resolve_node_runtime() -> dict | None:
    """yt-dlp 需要 JS runtime 解析部分 YouTube 页面；优先用本机 node。"""
    node = shutil.which("node")
    if not node:
        return None
    return {"node": {"path": node}}


def _is_rate_or_bot_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    needles = (
        "429",
        "too many requests",
        "sign in to confirm",
        "not a bot",
        "cookiesfrombrowser",
        "could not copy",
        "database is locked",
    )
    return any(n in msg for n in needles)


def _base_ydl_opts(outtmpl: str, ffmpeg: Path) -> dict:
    opts: dict = {
        "outtmpl": outtmpl,
        "restrictfilenames": True,
        # 转录够用即可；避免默认拉到 1080p 大文件
        "format": (
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=720][ext=mp4]/"
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "best[ext=mp4]/best"
        ),
        "merge_output_format": "mp4",
        "ignoreerrors": False,
        "noplaylist": True,
        "quiet": False,
        "ffmpeg_location": str(ffmpeg.parent),
        "sleep_interval_requests": 1.5,
        "extractor_retries": 3,
        "retries": 5,
        "fragment_retries": 5,
        # YouTube 需 EJS challenge solver；无 yt-dlp-ejs 包时从 GitHub 拉取
        "remote_components": {"ejs:github"},
    }
    if os.environ.get("JONATHAN_COACH_NO_OVERWRITES") == "1":
        opts["overwrites"] = False

    js = _resolve_node_runtime()
    if js:
        opts["js_runtimes"] = js

    cookies = _resolve_cookies_from_browser()
    if cookies:
        opts["cookiesfrombrowser"] = cookies

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

    ydl_opts = _base_ydl_opts(outtmpl, ffmpeg)
    if archive_file:
        ydl_opts["download_archive"] = str(archive_file)

    cookies = ydl_opts.get("cookiesfrombrowser")
    js = ydl_opts.get("js_runtimes")
    print(f"输出目录: {output_dir}")
    print(f"ffmpeg: {ffmpeg}")
    print(f"cookies: {cookies[0] if cookies else '未启用（易触发 YouTube bot/429）'}")
    print(f"js_runtime: {'node' if js else '无（建议安装 node）'}")
    print(f"待处理: {len(pending_urls)} 个视频")
    print(f"本地已有完整视频: {len(_list_complete_videos(output_dir))} 个\n")

    ok = 0
    skipped = skipped_transcribed
    failed = 0
    bot_hits = 0
    max_attempts = 3

    # 单个 YoutubeDL：只读一次浏览器 Cookie，避免双开解密失败
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for i, url in enumerate(pending_urls, start=1):
            print(f"[{i}/{len(pending_urls)}] {url}")
            video_id = extract_video_id(url) or ""
            last_exc: BaseException | None = None
            succeeded = False

            for attempt in range(1, max_attempts + 1):
                try:
                    info = ydl.extract_info(url, download=False)
                    if not isinstance(info, dict):
                        raise RuntimeError("无法解析视频信息（extract_info 返回空）")

                    video_id = str(info.get("id") or video_id)
                    if registry and video_id and registry.is_transcribed(video_id):
                        print(f"  跳过（已转录）: {video_id}")
                        skipped += 1
                        succeeded = True
                        break

                    stem = _stem_from_info(ydl, info, outtmpl)

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
                        succeeded = True
                        break

                    if registry and video_id:
                        entry = registry._videos.get(video_id, {})
                        alt_stem = entry.get("filename_stem") or entry.get("slug")
                        if alt_stem:
                            existing = _find_complete_video(output_dir, str(alt_stem))
                            if existing:
                                print(
                                    f"  续跑：本地已有（registry stem）→ {existing.name}"
                                )
                                registry.mark_downloaded(
                                    video_id,
                                    url=url,
                                    title=str(info.get("title") or ""),
                                    filename_stem=str(alt_stem),
                                )
                                ok += 1
                                succeeded = True
                                break

                    if archive_file and video_id and _archive_has(archive_file, video_id):
                        print(f"  archive 命中但缺完整文件，重新下载: {video_id}")
                        _remove_from_archive(archive_file, video_id)

                    ydl.download([url])
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
                    succeeded = True
                    break
                except Exception as exc:
                    last_exc = exc
                    if _is_rate_or_bot_error(exc) and attempt < max_attempts:
                        wait = 8 * attempt
                        print(
                            f"  触发限流/bot 验证，{wait}s 后重试 "
                            f"({attempt}/{max_attempts})…",
                            file=sys.stderr,
                        )
                        time.sleep(wait)
                        continue
                    break

            if not succeeded:
                failed += 1
                if last_exc is not None and _is_rate_or_bot_error(last_exc):
                    bot_hits += 1
                print(f"  下载失败: {last_exc}", file=sys.stderr)

            if i < len(pending_urls):
                time.sleep(2.5)

    local_n = len(_list_complete_videos(output_dir))
    print(
        f"\n完成。成功/续跑 {ok}，跳过 {skipped}，失败 {failed}；"
        f"本地完整视频 {local_n} 个。"
    )
    if failed > 0 and bot_hits > 0 and ok == 0:
        print(
            "\n提示: YouTube 判定为 bot / 触发 429。可尝试：\n"
            "  1) 用已登录 YouTube 的 Chrome 打开一次 youtube.com\n"
            "  2) 关闭 Chrome 后再跑（macOS 读 Cookie 更稳）\n"
            "  3) export JONATHAN_COACH_COOKIES_FROM_BROWSER=chrome\n"
            "  4) 稍等 10–30 分钟再重试，或把数量上限调小（如 3）\n"
            "  5) pip install -U 'yt-dlp[default]'",
            file=sys.stderr,
        )
    elif failed > 0 and ok == 0:
        print(
            "\n提示: 下载失败常见原因还包括 YouTube JS challenge 未解出。\n"
            "  请确认已安装: pip install -U 'yt-dlp[default]'\n"
            "  以及本机有 Node ≥ 20（当前脚本会自动启用 ejs:github）。",
            file=sys.stderr,
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
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        help="从浏览器读取 Cookie（chrome/safari/edge）。默认自动检测。",
    )
    args = parser.parse_args()

    urls: list[str] = list(args.urls)
    if args.file:
        if not args.file.exists():
            print(f"错误: 文件不存在 — {args.file}", file=sys.stderr)
            sys.exit(1)
        urls.extend(load_urls_from_file(args.file))

    if not urls:
        if args.file is not None:
            print(f"URL 列表为空（{args.file}），无需下载。")
            sys.exit(0)
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

    if args.cookies_from_browser:
        os.environ["JONATHAN_COACH_COOKIES_FROM_BROWSER"] = args.cookies_from_browser

    registry = VideoRegistry.load(args.registry) if args.registry else None

    try:
        result = download_videos(urls, registry=registry)
    except RuntimeError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(2)

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
