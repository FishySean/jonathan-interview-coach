"""Jonathan Coach 共享 pipeline：CLI 与可视化界面共用。"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from scripts.paths import (
    DISTILLED_BY_VIDEO_DIR,
    DOWNLOAD_ARCHIVE_FILE,
    PROJECT_ROOT,
    RAW_VIDEOS_DIR,
    SHORTS_URLS_FILE,
    SKILL_FILE,
    TRANSCRIPTS_DIR,
    VIDEO_REGISTRY_FILE,
    ensure_env_bin_on_path,
)

EventHandler = Callable[[str, dict[str, Any]], None]

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".m4a", ".mp3", ".wav"}
TRANSCRIPT_EXTENSIONS = {".md", ".txt"}


@dataclass
class PipelineConfig:
    channel: str = "@MrJonathanCareer"
    channel_url: str = ""
    max_videos: int = 10
    language: str = "en"
    model: str = "small"
    backend: str = "faster-whisper"
    output_format: str = "md"
    skip_download: bool = False
    skip_transcribe: bool = False
    auto_distill: bool = False
    skip_distill: bool = False
    distill_backend: str = "auto"
    distill_model: str | None = None
    distill_limit: int = 0
    skip_processed_videos: bool = True
    delete_video_after_transcribe: bool = True
    auto_install_requirements: bool = False
    urls_out: Path = field(default_factory=lambda: SHORTS_URLS_FILE)
    download_archive: Path = field(default_factory=lambda: DOWNLOAD_ARCHIVE_FILE)


@dataclass
class PipelineStats:
    urls_found: int = 0
    videos_total: int = 0
    transcripts_total: int = 0
    distilled_total: int = 0
    phase: str = "idle"
    running: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "output_paths": {
                "urls": str(SHORTS_URLS_FILE),
                "videos": str(RAW_VIDEOS_DIR),
                "transcripts": str(TRANSCRIPTS_DIR),
                "distilled": str(DISTILLED_BY_VIDEO_DIR),
                "skill": str(SKILL_FILE),
            },
        }


def count_videos(directory: Path) -> int:
    if not directory.exists():
        return 0
    from scripts.transcribe.transcribe import is_transcribable_video

    return sum(1 for p in directory.iterdir() if is_transcribable_video(p))


def count_transcripts(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(
        1 for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in TRANSCRIPT_EXTENSIONS
    )


def count_distilled() -> int:
    if not DISTILLED_BY_VIDEO_DIR.exists():
        return 0
    return sum(1 for p in DISTILLED_BY_VIDEO_DIR.glob("*.md") if p.is_file())


def count_urls_file(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1 for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


def count_archive(path: Path | None = None) -> int:
    """yt-dlp download archive 行数 = 历史上成功下载过的视频数。"""
    archive = path or DOWNLOAD_ARCHIVE_FILE
    if not archive.exists():
        return 0
    return sum(1 for line in archive.read_text(encoding="utf-8").splitlines() if line.strip())


def collect_disk_stats(
    *,
    phase: str = "idle",
    running: bool = False,
    error: str = "",
) -> PipelineStats:
    """
    从磁盘汇总累计进度（刷新页面 / 重启 app 后仍保留）。
    - 链接：shorts_urls ∪ download_archive 去重
    - 视频：archive 与 raw_videos 取较大（转录后会删 raw，靠 archive 记住）
    - 转录 / 蒸馏：目录内文件数
    """
    try:
        from scripts.pipeline.video_registry import extract_video_id

        known_ids: set[str] = set()
        if DOWNLOAD_ARCHIVE_FILE.exists():
            for line in DOWNLOAD_ARCHIVE_FILE.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                parts = line.split()
                if parts:
                    known_ids.add(parts[-1])
        archive_n = len(known_ids)

        if SHORTS_URLS_FILE.exists():
            for line in SHORTS_URLS_FILE.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                vid = extract_video_id(text)
                if vid:
                    known_ids.add(vid)

        raw_n = count_videos(RAW_VIDEOS_DIR)
        return PipelineStats(
            urls_found=len(known_ids),
            videos_total=max(archive_n, raw_n),
            transcripts_total=count_transcripts(TRANSCRIPTS_DIR),
            distilled_total=count_distilled(),
            phase=phase,
            running=running,
            error=error,
        )
    except Exception as exc:
        # 绝不能让 /api/status 因磁盘读失败而 500
        return PipelineStats(
            urls_found=count_urls_file(SHORTS_URLS_FILE),
            videos_total=max(count_archive(), count_videos(RAW_VIDEOS_DIR)),
            transcripts_total=count_transcripts(TRANSCRIPTS_DIR),
            distilled_total=count_distilled(),
            phase=phase,
            running=running,
            error=error or f"disk stats partial: {exc}",
        )


def _emit(handler: EventHandler | None, kind: str, message: str, **data: Any) -> None:
    if handler:
        handler(kind, {"message": message, **data})


def _emit_phase(
    handler: EventHandler | None,
    stats: PipelineStats,
    phase: str,
    message: str,
) -> None:
    stats.phase = phase
    _emit(handler, "phase", message, phase=phase, stats=stats.to_dict())


def _apply_disk_floor(stats: PipelineStats) -> None:
    """把磁盘累计进度抬到 stats 上（页面刷新 / 清理 raw 后仍显示历史数）。"""
    disk = collect_disk_stats()
    stats.urls_found = max(stats.urls_found, disk.urls_found)
    stats.videos_total = max(stats.videos_total, disk.videos_total)
    stats.transcripts_total = max(stats.transcripts_total, disk.transcripts_total)
    stats.distilled_total = max(stats.distilled_total, disk.distilled_total)


def _parse_progress_line(line: str) -> tuple[int, int] | None:
    """解析 [PROGRESS] 2/9 格式（转录 / 蒸馏共用）。"""
    marker = "[PROGRESS]"
    if marker not in line:
        return None
    try:
        chunk = line.split(marker, 1)[1].strip()
        part = chunk.split()[0]
        current, total = part.split("/", 1)
        return int(current), int(total)
    except (ValueError, IndexError):
        return None


def _run_streaming(
    cmd: list[str],
    *,
    cwd: Path,
    on_line: Callable[[str], None] | None = None,
) -> None:
    # 保证子进程能找到与当前 Python 同环境的 ffmpeg（未 activate 时也可用）
    env = {**__import__("os").environ, "PATH": ensure_env_bin_on_path()}
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert process.stdout is not None
    for line in process.stdout:
        text = line.rstrip()
        if on_line and text:
            on_line(text)
    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, cmd)


def maybe_install_requirements(config: PipelineConfig, on_event: EventHandler | None = None) -> None:
    if not config.auto_install_requirements:
        return
    req = PROJECT_ROOT / "requirements.txt"
    if not req.exists():
        raise FileNotFoundError("缺少 requirements.txt")
    _emit(on_event, "log", "正在安装依赖…", phase="install")
    _run_streaming(
        [sys.executable, "-m", "pip", "install", "-r", str(req)],
        cwd=PROJECT_ROOT,
        on_line=lambda line: _emit(on_event, "log", line),
    )


def run_pipeline(
    config: PipelineConfig,
    on_event: EventHandler | None = None,
) -> PipelineStats:
    stats = PipelineStats(running=True, phase="starting")
    _emit(on_event, "status", "流程启动", stats=stats.to_dict())

    try:
        did_transcribe = False
        maybe_install_requirements(config, on_event)

        # 1) 抓取 Shorts URL
        stats.phase = "fetch"
        _emit_phase(on_event, stats, "fetch", "正在抓取频道 Shorts 链接…")
        fetch_cmd = [
            sys.executable,
            "-m",
            "scripts.ingest.fetch_channel_shorts",
            "--channel",
            config.channel,
            "--output",
            str(config.urls_out),
        ]
        if config.channel_url.strip():
            fetch_cmd.extend(["--channel-url", config.channel_url.strip()])
        if config.max_videos > 0:
            fetch_cmd.extend(["--max-videos", str(config.max_videos)])
        if config.skip_processed_videos:
            fetch_cmd.extend([
                "--skip-processed",
                "--registry",
                str(VIDEO_REGISTRY_FILE),
            ])

        _run_streaming(
            fetch_cmd,
            cwd=PROJECT_ROOT,
            on_line=lambda line: _emit(on_event, "log", line, phase="fetch"),
        )
        pending_urls = count_urls_file(config.urls_out)
        stats.urls_found = pending_urls
        _apply_disk_floor(stats)
        _emit(
            on_event,
            "progress",
            f"待处理 Shorts 链接: {pending_urls} 个（累计已知 {stats.urls_found}）",
            phase="fetch",
            stats=stats.to_dict(),
        )

        # 必须以「本轮抓取到的待处理链接」为准；勿用累计 disk floor 误判为还要下载
        if pending_urls == 0:
            _emit(
                on_event,
                "log",
                "没有新的视频需要处理（频道最新列表均已在 registry 中登记）。",
                phase="fetch",
            )
            config.skip_download = True
            config.skip_transcribe = True

        # 2) 下载（失败时若本地已有完整视频，继续转录 —— 断点续跑）
        if not config.skip_download:
            stats.phase = "download"
            _emit_phase(on_event, stats, "download", "正在下载视频…")
            download_cmd = [
                sys.executable,
                "-m",
                "scripts.ingest.download_youtube",
                "--file",
                str(config.urls_out),
                "--download-archive",
                str(config.download_archive),
                "--registry",
                str(VIDEO_REGISTRY_FILE),
            ]
            try:
                _run_streaming(
                    download_cmd,
                    cwd=PROJECT_ROOT,
                    on_line=lambda line: _emit(on_event, "log", line, phase="download"),
                )
            except subprocess.CalledProcessError:
                stats.videos_total = count_videos(RAW_VIDEOS_DIR)
                if stats.videos_total > 0:
                    _emit(
                        on_event,
                        "log",
                        f"下载步骤有错误，但 raw_videos/ 已有 {stats.videos_total} 个完整视频，继续转录（断点续跑）",
                        phase="download",
                    )
                else:
                    raise RuntimeError(
                        "下载全部失败（常见原因：YouTube 429 / bot 验证 / JS challenge）。\n"
                        "处理建议：\n"
                        "1) Chrome 登录 youtube.com 后先关掉 Chrome\n"
                        "2) 终端执行: export JONATHAN_COACH_COOKIES_FROM_BROWSER=chrome\n"
                        "3) pip install -U 'yt-dlp[default]'（含 yt-dlp-ejs）\n"
                        "4) 数量上限先改成 1～3，等 10～30 分钟再跑"
                    ) from None
            stats.videos_total = count_videos(RAW_VIDEOS_DIR)
            _emit(
                on_event,
                "progress",
                f"raw_videos/ 现有 {stats.videos_total} 个视频文件",
                phase="download",
                stats=stats.to_dict(),
            )
        else:
            stats.videos_total = count_videos(RAW_VIDEOS_DIR)
            _emit(on_event, "log", "已跳过下载步骤", phase="download")

        # 2.5) 下载后若有未合并分片，先合并再转录
        if not config.skip_transcribe:
            from scripts.tools.merge_raw_fragments import merge_orphaned_fragments

            try:
                merged, _skipped, merge_failed = merge_orphaned_fragments(RAW_VIDEOS_DIR)
                if merged:
                    _emit(
                        on_event,
                        "log",
                        f"已合并 {merged} 组未完成的音视频分片",
                        phase="download",
                    )
                if merge_failed:
                    raise RuntimeError(f"{merge_failed} 组分片合并失败，无法继续转录")
            except RuntimeError as exc:
                raise RuntimeError(str(exc)) from exc

            stats.videos_total = count_videos(RAW_VIDEOS_DIR)
            if stats.videos_total == 0 and stats.urls_found > 0:
                raise RuntimeError(
                    "下载步骤后 raw_videos/ 仍无可转录的完整视频。"
                    "常见原因：ffmpeg 未找到，只留下了 *.f137.mp4 / *.f140.m4a 分片。"
                )

        # 3) 转录
        if not config.skip_transcribe:
            stats.phase = "transcribe"
            _emit_phase(
                on_event,
                stats,
                "transcribe",
                "正在转录为文字…（首次会下载 Whisper 模型，CPU 上每个视频约 1~3 分钟）",
            )

            def on_transcribe_line(line: str) -> None:
                _emit(on_event, "log", line, phase="transcribe")
                if "正在加载 Whisper 模型" in line:
                    _emit(
                        on_event,
                        "phase",
                        "正在下载/加载 Whisper 模型，请耐心等待…",
                        phase="transcribe",
                        stats=stats.to_dict(),
                        progress_hint="model_loading",
                    )
                progress = _parse_progress_line(line)
                if progress:
                    current, total = progress
                    stats.transcripts_total = count_transcripts(TRANSCRIPTS_DIR)
                    pct = 65 + int((current / max(total, 1)) * 25)
                    _emit(
                        on_event,
                        "progress",
                        f"转录进度 {current}/{total}",
                        phase="transcribe",
                        stats=stats.to_dict(),
                        progress_percent=pct,
                        transcribe_current=current,
                        transcribe_total=total,
                    )
                if line.strip().startswith("已保存:"):
                    stats.transcripts_total = count_transcripts(TRANSCRIPTS_DIR)
                    _emit(
                        on_event,
                        "progress",
                        line.strip(),
                        phase="transcribe",
                        stats=stats.to_dict(),
                    )
            transcribe_cmd = [
                sys.executable,
                "-m",
                "scripts.transcribe",
                "--input-dir",
                str(RAW_VIDEOS_DIR),
                "--output-dir",
                str(TRANSCRIPTS_DIR),
                "--model",
                config.model,
                "--backend",
                config.backend,
                "--format",
                config.output_format,
            ]
            if config.language.strip():
                transcribe_cmd.extend(["--language", config.language.strip()])
            transcribe_cmd.extend([
                "--registry",
                str(VIDEO_REGISTRY_FILE),
            ])
            if config.delete_video_after_transcribe:
                transcribe_cmd.append("--delete-after")

            _run_streaming(
                transcribe_cmd,
                cwd=PROJECT_ROOT,
                on_line=on_transcribe_line,
            )
            did_transcribe = True
            stats.transcripts_total = count_transcripts(TRANSCRIPTS_DIR)
            _emit(
                on_event,
                "progress",
                f"transcripts/ 现有 {stats.transcripts_total} 份转录",
                phase="transcribe",
                stats=stats.to_dict(),
            )
        else:
            stats.transcripts_total = count_transcripts(TRANSCRIPTS_DIR)
            _emit(on_event, "log", "已跳过转录步骤", phase="transcribe")

        # 4) LLM 蒸馏（转录后自动继续；调用 OpenAI / Ollama 等，非 Cursor Agent）
        stats.distilled_total = count_distilled()
        if config.auto_distill and not config.skip_distill:
            from scripts.distill import DistillConfig, load_env_file, run_distill

            load_env_file()
            stats.phase = "distill"
            _emit_phase(
                on_event,
                stats,
                "distill",
                "转录完成，正在 LLM 蒸馏方法论…（需 Ollama 或 API Key，见 .env.example）",
            )

            def on_distill_line(line: str) -> None:
                _emit(on_event, "log", line, phase="distill")
                progress = _parse_progress_line(line)
                if progress:
                    current, total = progress
                    stats.distilled_total = count_distilled()
                    pct = 92 + int((current / max(total, 1)) * 7)
                    _emit(
                        on_event,
                        "progress",
                        f"蒸馏进度 {current}/{total}",
                        phase="distill",
                        stats=stats.to_dict(),
                        progress_percent=pct,
                        distill_current=current,
                        distill_total=total,
                    )
                if line.strip().startswith("已保存:"):
                    stats.distilled_total = count_distilled()
                    _emit(
                        on_event,
                        "progress",
                        line.strip(),
                        phase="distill",
                        stats=stats.to_dict(),
                    )

            try:
                distill_cfg = DistillConfig(
                    backend=config.distill_backend,
                    model=config.distill_model,
                    limit=config.distill_limit,
                    merge=True,
                )
                result = run_distill(distill_cfg, on_log=on_distill_line)
                stats.distilled_total = count_distilled()
                _emit(
                    on_event,
                    "progress",
                    f"蒸馏完成：成功 {result.processed}，失败 {result.failed}（{result.backend}/{result.model}）",
                    phase="distill",
                    stats=stats.to_dict(),
                    progress_percent=99,
                )
            except RuntimeError as exc:
                _emit(
                    on_event,
                    "log",
                    f"跳过蒸馏: {exc}",
                    phase="distill",
                )
                _emit(
                    on_event,
                    "log",
                    "提示: 安装 Ollama 或配置 OPENAI_API_KEY 后可自动蒸馏。",
                    phase="distill",
                )
        else:
            _emit(on_event, "log", "已跳过蒸馏步骤", phase="distill")

        # 5) 仅在实际跑过转录后清理 raw_videos（避免「无新 URL」时误删待转录文件）
        if config.delete_video_after_transcribe and did_transcribe:
            from scripts.transcribe.transcribe import cleanup_raw_videos_dir

            stats.phase = "cleanup"
            _emit_phase(on_event, stats, "cleanup", "正在清理本地视频文件…")
            deleted = cleanup_raw_videos_dir(RAW_VIDEOS_DIR)
            _apply_disk_floor(stats)
            if deleted:
                _emit(
                    on_event,
                    "progress",
                    f"已清理 {len(deleted)} 个本地视频（transcript 已保留；已下载累计 {stats.videos_total}）",
                    phase="cleanup",
                    stats=stats.to_dict(),
                )
            else:
                _emit(
                    on_event,
                    "log",
                    "raw_videos/ 无残留视频文件",
                    phase="cleanup",
                )
        elif config.delete_video_after_transcribe and not did_transcribe:
            _emit(
                on_event,
                "log",
                "未执行转录，跳过清理 raw_videos/（保留本地视频）",
                phase="cleanup",
            )

        stats.phase = "done"
        stats.running = False
        _apply_disk_floor(stats)
        _emit(
            on_event,
            "done",
            "全部完成！产物已写入 data/（含 transcripts、distilled、skill）。",
            stats=stats.to_dict(),
        )
        return stats

    except Exception as exc:
        stats.running = False
        stats.phase = "error"
        stats.error = str(exc)
        _apply_disk_floor(stats)
        _emit(on_event, "error", f"流程失败: {exc}", stats=stats.to_dict())
        raise
