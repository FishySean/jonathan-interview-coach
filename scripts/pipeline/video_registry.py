"""YouTube 视频处理登记：用 video ID 追踪进度，不依赖本地视频文件是否存在。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.paths import (
    DISTILL_INDEX_FILE,
    DOWNLOAD_ARCHIVE_FILE,
    TRANSCRIPTS_DIR,
    VIDEO_REGISTRY_FILE,
)

VIDEO_ID_RE = re.compile(
    r"(?:shorts/|[?&]v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def extract_video_id(url: str) -> str | None:
    match = VIDEO_ID_RE.search(url.strip())
    return match.group(1) if match else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VideoRegistry:
    """持久化登记：key = YouTube video ID。"""

    def __init__(self, path: Path = VIDEO_REGISTRY_FILE) -> None:
        self.path = path
        self._videos: dict[str, dict[str, Any]] = {}

    @classmethod
    def load(cls, path: Path = VIDEO_REGISTRY_FILE) -> VideoRegistry:
        reg = cls(path)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            reg._videos = data.get("videos", {})
        else:
            reg.bootstrap_from_existing()
            reg.save()
        return reg

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"videos": self._videos}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def is_transcribed(self, video_id: str) -> bool:
        entry = self._videos.get(video_id)
        if not entry:
            return False
        return entry.get("status") in {"transcribed", "distilled"}

    def is_distilled(self, video_id: str) -> bool:
        return self._videos.get(video_id, {}).get("status") == "distilled"

    def processed_ids(self) -> set[str]:
        return {
            vid
            for vid, e in self._videos.items()
            if not vid.startswith("slug:")
            and e.get("status") in {"transcribed", "distilled"}
        }

    def get_id_by_stem(self, stem: str) -> str | None:
        for vid, entry in self._videos.items():
            if entry.get("slug") == stem or entry.get("filename_stem") == stem:
                return vid
        return None

    def mark_downloaded(
        self,
        video_id: str,
        *,
        url: str,
        title: str | None = None,
        filename_stem: str | None = None,
    ) -> None:
        entry = self._videos.setdefault(video_id, {})
        entry.update({
            "url": url,
            "title": title or entry.get("title"),
            "filename_stem": filename_stem or entry.get("filename_stem"),
            "status": "downloaded",
            "downloaded_at": _now_iso(),
        })
        self.save()

    def mark_transcribed(
        self,
        video_id: str,
        *,
        slug: str,
        transcript_file: str | None = None,
    ) -> None:
        entry = self._videos.setdefault(video_id, {})
        entry.update({
            "slug": slug,
            "transcript_file": transcript_file or f"{slug}.md",
            "status": "transcribed",
            "transcribed_at": _now_iso(),
        })
        self.save()

    def mark_transcribed_by_stem(self, stem: str, *, transcript_file: str | None = None) -> None:
        video_id = self.get_id_by_stem(stem)
        if video_id:
            self.mark_transcribed(video_id, slug=stem, transcript_file=transcript_file)
        else:
            # 无 video id 时仍按 slug 登记，便于蒸馏索引对齐
            pseudo_id = f"slug:{stem}"
            self.mark_transcribed(pseudo_id, slug=stem, transcript_file=transcript_file)

    def mark_distilled(self, video_id: str) -> None:
        entry = self._videos.setdefault(video_id, {})
        entry["status"] = "distilled"
        entry["distilled_at"] = _now_iso()
        self.save()

    def mark_distilled_by_slug(self, slug: str) -> None:
        video_id = self.get_id_by_stem(slug)
        if video_id:
            self.mark_distilled(video_id)

    def bootstrap_from_existing(self) -> None:
        """首次运行：从 download_archive、transcripts、distill 索引回填。"""
        # 1) yt-dlp archive → 视为已转录（历史 pipeline 产物）
        if DOWNLOAD_ARCHIVE_FILE.exists():
            for line in DOWNLOAD_ARCHIVE_FILE.read_text(encoding="utf-8").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0] == "youtube":
                    vid = parts[1]
                    entry = self._videos.setdefault(vid, {})
                    if entry.get("status") not in {"transcribed", "distilled"}:
                        entry["status"] = "transcribed"
                        entry["bootstrapped_from"] = "download_archive"
                        entry["transcribed_at"] = entry.get("transcribed_at") or _now_iso()

        # 2) 已有 transcript → 补全 slug（仅合并到已有 video ID 条目）
        if TRANSCRIPTS_DIR.exists():
            for path in sorted(TRANSCRIPTS_DIR.glob("*.md")):
                slug = path.stem
                if slug.endswith(".f140") or slug.endswith(".f137"):
                    continue
                for entry in self._videos.values():
                    if entry.get("slug") == slug:
                        break
                    if entry.get("filename_stem") == slug:
                        entry.setdefault("slug", slug)
                        entry.setdefault("transcript_file", path.name)
                        if entry.get("status") == "downloaded":
                            entry["status"] = "transcribed"
                        break

        # 3) 蒸馏索引 → 标记 distilled
        if DISTILL_INDEX_FILE.exists():
            index = json.loads(DISTILL_INDEX_FILE.read_text(encoding="utf-8"))
            for slug in index.get("completed", {}):
                self.mark_distilled_by_slug(slug)
