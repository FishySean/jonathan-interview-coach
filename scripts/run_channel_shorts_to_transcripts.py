#!/usr/bin/env python3
"""兼容旧路径：请改用 python -m scripts.cli.run_channel_shorts_to_transcripts"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
runpy.run_module("scripts.cli.run_channel_shorts_to_transcripts", run_name="__main__")
