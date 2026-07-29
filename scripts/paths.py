"""项目路径常量，供各脚本共享。"""

from __future__ import annotations

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

DISTILLED_BY_VIDEO_DIR = DISTILLED_DIR / "by_video"
EXTERNAL_DIR = PROJECT_ROOT / "external"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

SHORTS_URLS_FILE = PROJECT_ROOT / "shorts_urls.txt"
DOWNLOAD_ARCHIVE_FILE = PROJECT_ROOT / "download_archive.txt"
DISTILL_INDEX_FILE = DISTILLED_DIR / ".distill_index.json"
VIDEO_REGISTRY_FILE = DATA_DIR / ".video_registry.json"


def setup_path() -> Path:
    """直接运行子目录脚本时，把项目根加入 sys.path。"""
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return PROJECT_ROOT
