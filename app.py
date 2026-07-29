#!/usr/bin/env python3
"""
Jonathan Interview Coach — 可视化主入口（app）

运行后自动打开本地页面，点击按钮即可执行完整 pipeline。
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _ensure_project_python() -> None:
    """若用错了解释器（如系统 Python），自动切换到 conda 环境。"""
    try:
        import flask  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    project_root = Path(__file__).resolve().parent
    candidates = [
        Path("/opt/anaconda3/envs/jonathan-coach/bin/python"),
        Path.home() / "anaconda3/envs/jonathan-coach/bin/python",
        Path.home() / "miniconda3/envs/jonathan-coach/bin/python",
        project_root / ".venv" / "bin" / "python",
    ]

    current = Path(sys.executable).resolve()
    for candidate in candidates:
        if candidate.exists() and candidate.resolve() != current:
            print(f"检测到当前 Python 缺少依赖: {current}")
            print(f"正在切换到: {candidate}")
            os.execv(str(candidate), [str(candidate), *sys.argv])

    print("错误: 未安装项目依赖（缺少 flask）。")
    print(f"当前 Python: {sys.executable}")
    print("请先运行: ./setup_env.sh")
    print("然后执行: conda activate jonathan-coach && python app.py")
    sys.exit(1)


_ensure_project_python()

from flask import Flask, Response, jsonify, request, send_from_directory

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.pipeline import PipelineConfig, PipelineStats, run_pipeline

UI_DIR = PROJECT_ROOT / "ui"

app = Flask(__name__, static_folder=str(UI_DIR), static_url_path="")

_event_queue: queue.Queue[dict] = queue.Queue()
_stats = PipelineStats()
_running = False
_server = None
_shutting_down = False
_lock = threading.Lock()


def _broadcast(kind: str, payload: dict) -> None:
    global _stats
    if "stats" in payload:
        data = payload["stats"]
        _stats = PipelineStats(
            urls_found=data.get("urls_found", 0),
            videos_total=data.get("videos_total", 0),
            transcripts_total=data.get("transcripts_total", 0),
            distilled_total=data.get("distilled_total", 0),
            phase=data.get("phase", "idle"),
            running=data.get("running", True),
            error=data.get("error", ""),
        )
    elif payload.get("phase"):
        _stats.phase = str(payload["phase"])
        _stats.running = True
    if payload.get("transcribe_current") and payload.get("transcribe_total"):
        _stats.transcripts_total = max(
            _stats.transcripts_total,
            int(payload["transcribe_current"]) - 1,
        )
    _event_queue.put({
        "kind": kind,
        "timestamp": time.time(),
        **payload,
    })


def _pipeline_worker(config: PipelineConfig) -> None:
    global _running
    try:
        run_pipeline(config, on_event=_broadcast)
    except Exception:
        pass
    finally:
        with _lock:
            _running = False


@app.route("/")
def index() -> Response:
    return send_from_directory(UI_DIR, "index.html")


@app.route("/assets/<path:filename>")
def assets(filename: str) -> Response:
    return send_from_directory(UI_DIR, filename)


@app.get("/api/status")
def status() -> Response:
    return jsonify(_stats.to_dict() | {"running": _running})


@app.post("/api/start")
def start() -> Response:
    global _running
    with _lock:
        if _running:
            return jsonify({"ok": False, "error": "已有任务在运行中"}), 409
        _running = True

    body = request.get_json(silent=True) or {}
    config = PipelineConfig(
        channel=body.get("channel", "@MrJonathanCareer"),
        channel_url=body.get("channel_url", ""),
        max_videos=int(body.get("max_videos", 10)),
        language=body.get("language", "en"),
        model=body.get("model", "small"),
        backend=body.get("backend", "faster-whisper"),
        output_format=body.get("format", "md"),
        skip_download=bool(body.get("skip_download", False)),
        skip_transcribe=bool(body.get("skip_transcribe", False)),
        auto_distill=bool(body.get("auto_distill", False)),
        skip_distill=bool(body.get("skip_distill", False)),
        distill_backend=body.get("distill_backend", "auto"),
        distill_model=body.get("distill_model") or None,
        distill_limit=int(body.get("distill_limit", 0)),
        auto_install_requirements=bool(body.get("auto_install_requirements", True)),
    )

    _broadcast("status", {"message": "任务已启动", "stats": PipelineStats(running=True, phase="starting").to_dict()})
    thread = threading.Thread(target=_pipeline_worker, args=(config,), daemon=True)
    thread.start()
    return jsonify({"ok": True})


@app.post("/api/shutdown")
def shutdown() -> Response:
    """停止本地 Flask 服务（仅 127.0.0.1）。"""
    global _shutting_down
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"ok": False, "error": "仅允许本机关机"}), 403
    with _lock:
        if _running:
            return jsonify({"ok": False, "error": "Pipeline 运行中，请等完成后再关机"}), 409
        if _shutting_down:
            return jsonify({"ok": True, "message": "服务正在关闭…"})
        _shutting_down = True

    _broadcast("log", {"message": "收到关机指令，服务即将停止…"})

    def _stop() -> None:
        time.sleep(0.4)
        if _server is not None:
            _server.shutdown()
        else:
            os._exit(0)

    threading.Thread(target=_stop, daemon=True).start()
    return jsonify({"ok": True, "message": "服务正在关闭…"})


@app.get("/api/events")
def events() -> Response:
    def stream():
        while True:
            try:
                event = _event_queue.get(timeout=20)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'kind': 'ping'})}\n\n"

    return Response(stream(), mimetype="text/event-stream")


def main() -> None:
    global _server
    from werkzeug.serving import make_server

    url = "http://127.0.0.1:8765"
    print("Jonathan Interview Coach")
    print(f"打开页面: {url}")
    print("网页内可点「关机」停止服务，或终端 Ctrl+C\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    _server = make_server("127.0.0.1", 8765, app, threaded=True)
    _server.serve_forever()


if __name__ == "__main__":
    main()
