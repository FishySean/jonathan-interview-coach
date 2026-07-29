#!/usr/bin/env python3
"""列出尚未蒸馏的 transcripts（有 transcript、无 by_video 对应文件）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.paths import DISTILLED_BY_VIDEO_DIR, TRANSCRIPTS_DIR, setup_path

setup_path()


def pending_transcripts() -> list[Path]:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    DISTILLED_BY_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    distilled = {p.name for p in DISTILLED_BY_VIDEO_DIR.glob("*.md")}
    pending = [
        p
        for p in sorted(TRANSCRIPTS_DIR.glob("*.md"))
        if p.name not in distilled
    ]
    return pending


def main() -> None:
    pending = pending_transcripts()
    as_json = "--json" in sys.argv
    if as_json:
        print(json.dumps({"pending": [p.name for p in pending], "count": len(pending)}))
        return
    if not pending:
        print("0 pending")
        return
    print(f"{len(pending)} pending:")
    for p in pending:
        print(p.name)


if __name__ == "__main__":
    main()
