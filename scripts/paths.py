"""项目路径常量，供各脚本共享。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent

# 逐层精加工的四层产物，统一放在 data/ 下
DATA_DIR = PROJECT_ROOT / "data"
RAW_VIDEOS_DIR = DATA_DIR / "raw_videos"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
DISTILLED_DIR = DATA_DIR / "distilled"
SKILL_DIR = DATA_DIR / "skill"

SKILL_FILE = SKILL_DIR / "SKILL.md"
SKILL_README = SKILL_DIR / "README.md"
SKILL_CHANGELOG = SKILL_DIR / "CHANGELOG.md"
SKILL_REFERENCES_DIR = SKILL_DIR / "references"
SKILL_REFERENCES_BY_VIDEO_DIR = SKILL_REFERENCES_DIR / "by_video"
SKILL_FRAMEWORKS_FILE = SKILL_REFERENCES_DIR / "frameworks.md"

DISTILLED_BY_VIDEO_DIR = DISTILLED_DIR / "by_video"
EXTERNAL_DIR = PROJECT_ROOT / "external"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

SHORTS_URLS_FILE = DATA_DIR / "shorts_urls.txt"
DOWNLOAD_ARCHIVE_FILE = DATA_DIR / "download_archive.txt"
DISTILL_INDEX_FILE = DISTILLED_DIR / ".distill_index.json"
VIDEO_REGISTRY_FILE = DATA_DIR / ".video_registry.json"


def setup_path() -> Path:
    """直接运行子目录脚本时，把项目根加入 sys.path。"""
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return PROJECT_ROOT


def python_env_bin() -> Path:
    """当前解释器所在 bin 目录（conda/venv 的 ffmpeg 通常也在这里）。"""
    return Path(sys.executable).resolve().parent


def ensure_env_bin_on_path() -> str:
    """把当前 Python 环境的 bin 放到 PATH 最前，避免未 activate 时找不到 ffmpeg。"""
    env_bin = str(python_env_bin())
    path = os.environ.get("PATH", "")
    parts = path.split(os.pathsep) if path else []
    if env_bin not in parts:
        os.environ["PATH"] = env_bin + (os.pathsep + path if path else "")
    return os.environ["PATH"]


def resolve_ffmpeg() -> Path | None:
    """定位 ffmpeg：优先 PATH，其次与当前 Python 同目录。"""
    ensure_env_bin_on_path()
    which = shutil.which("ffmpeg")
    if which:
        return Path(which)
    sibling = python_env_bin() / "ffmpeg"
    if sibling.exists():
        return sibling
    return None
