#!/usr/bin/env python3
"""兼容旧路径：请改用 python -m scripts.ingest.download_youtube"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
runpy.run_module("scripts.ingest.download_youtube", run_name="__main__")
