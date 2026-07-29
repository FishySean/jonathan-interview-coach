const startBtn = document.getElementById("startBtn");
const shutdownBtn = document.getElementById("shutdownBtn");
const shutdownOverlay = document.getElementById("shutdownOverlay");
const clearLogBtn = document.getElementById("clearLog");
const logFeed = document.getElementById("logFeed");
const phaseLabel = document.getElementById("phaseLabel");
const phaseBadge = document.getElementById("phaseBadge");
const progressBar = document.getElementById("progressBar");

const statUrls = document.getElementById("statUrls");
const statVideos = document.getElementById("statVideos");
const statTranscripts = document.getElementById("statTranscripts");
const statDistilled = document.getElementById("statDistilled");

const pathUrls = document.getElementById("pathUrls");
const pathVideos = document.getElementById("pathVideos");
const pathTranscripts = document.getElementById("pathTranscripts");
const pathSkill = document.getElementById("pathSkill");

const PHASE_LABELS = {
  idle: "待命",
  starting: "准备中",
  install: "安装依赖",
  fetch: "抓取 Shorts 链接",
  download: "下载视频",
  transcribe: "语音转文字",
  distill: "LLM 蒸馏",
  cleanup: "清理本地视频",
  done: "完成",
  error: "出错",
};

const PHASE_PROGRESS = {
  idle: 0,
  starting: 8,
  install: 12,
  fetch: 30,
  download: 60,
  transcribe: 85,
  distill: 95,
  cleanup: 98,
  done: 100,
  error: 100,
};

let running = false;
let serverOffline = false;

function formatTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString();
}

function addLog(kind, message, timestamp = Date.now() / 1000) {
  const item = document.createElement("div");
  item.className = `log-item ${kind}`;
  item.innerHTML = `<span class="log-time">${formatTime(timestamp)}</span>${message}`;
  logFeed.prepend(item);
}

function updateStats(stats, extras = {}) {
  if (!stats) return;
  // 只更新明确给出的字段，避免 phase-only 事件把累计数字刷成 0
  if (stats.urls_found != null) statUrls.textContent = stats.urls_found;
  if (stats.videos_total != null) statVideos.textContent = stats.videos_total;
  if (stats.transcripts_total != null) {
    statTranscripts.textContent = stats.transcripts_total;
  }
  if (stats.distilled_total != null) {
    statDistilled.textContent = stats.distilled_total;
  }

  if (stats.output_paths) {
    pathUrls.textContent = stats.output_paths.urls;
    pathVideos.textContent = stats.output_paths.videos;
    pathTranscripts.textContent = stats.output_paths.transcripts;
    if (stats.output_paths.skill) pathSkill.textContent = stats.output_paths.skill;
  }

  const phase = extras.phase || stats.phase || "idle";
  phaseLabel.textContent = PHASE_LABELS[phase] || phase;
  phaseBadge.textContent = phase.toUpperCase();
  phaseBadge.className = `phase-badge ${phase}`;

  const pct = extras.progress_percent ?? PHASE_PROGRESS[phase] ?? 0;
  progressBar.style.width = `${pct}%`;
  progressBar.classList.toggle(
    "indeterminate",
    (phase === "transcribe" || phase === "distill") && !extras.progress_percent,
  );

  document.querySelectorAll(".stat-card").forEach((card) => {
    card.classList.toggle("active", card.dataset.phase === phase);
  });
}

function setServerOffline(value) {
  serverOffline = value;
  startBtn.disabled = value || running;
  shutdownBtn.disabled = value;
  if (value) {
    shutdownOverlay.classList.remove("hidden");
    phaseLabel.textContent = "已关机";
    phaseBadge.textContent = "OFF";
    phaseBadge.className = "phase-badge idle";
  }
}

function setRunning(value) {
  running = value;
  startBtn.disabled = value || serverOffline;
  shutdownBtn.disabled = value || serverOffline;
  startBtn.classList.toggle("running", value);
  startBtn.querySelector(".btn-label").textContent = value ? "运行中…" : "开始运行";
}

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) throw new Error(`status ${res.status}`);
    const data = await res.json();
    updateStats(data);
    setRunning(Boolean(data.running));
  } catch {
    // 启动瞬间或服务重启时可能短暂失败，不打断页面
  }
}

function connectEvents() {
  const source = new EventSource("/api/events");
  source.onmessage = (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    if (payload.kind === "ping") return;

    if (payload.stats) {
      updateStats(payload.stats, {
        phase: payload.phase,
        progress_percent: payload.progress_percent,
      });
    } else if (payload.phase) {
      updateStats({ phase: payload.phase }, {
        phase: payload.phase,
        progress_percent: payload.progress_percent,
      });
    }
    if (payload.message) {
      const kind = ["phase", "progress", "done", "error"].includes(payload.kind)
        ? payload.kind
        : "log";
      addLog(kind, payload.message, payload.timestamp);
    }

    if (payload.kind === "done") setRunning(false);
    if (payload.kind === "error") setRunning(false);
  };

  source.onerror = () => {
    setTimeout(connectEvents, 2000);
    source.close();
  };
}

startBtn.addEventListener("click", async () => {
  if (running) return;

  const body = {
    channel: document.getElementById("channel").value.trim(),
    max_videos: Number(document.getElementById("maxVideos").value || 10),
    model: document.getElementById("model").value,
    auto_distill: document.getElementById("autoDistill").checked,
    distill_backend: document.getElementById("distillBackend").value,
    auto_install_requirements: false,
  };

  setRunning(true);
  addLog("phase", "已发送启动指令，准备开始…");

  try {
    const res = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    if (!res.ok) {
      setRunning(false);
      addLog("error", data.error || "启动失败");
    }
  } catch (err) {
    setRunning(false);
    addLog("error", "无法连接本地服务，请确认 python app.py 仍在运行");
  }
});

clearLogBtn.addEventListener("click", () => {
  logFeed.innerHTML = "";
});

shutdownBtn.addEventListener("click", async () => {
  if (serverOffline) return;
  if (running) {
    addLog("error", "Pipeline 运行中，请等完成后再关机");
    return;
  }
  if (!window.confirm("确定关闭 Jonathan Coach 本地服务？")) return;

  shutdownBtn.disabled = true;
  shutdownBtn.querySelector("span").textContent = "…";
  addLog("phase", "正在发送关机指令…");

  try {
    const res = await fetch("/api/shutdown", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      shutdownBtn.disabled = false;
      shutdownBtn.querySelector("span").textContent = "关机";
      addLog("error", data.error || "关机失败");
      return;
    }
    addLog("done", data.message || "服务已关闭");
    setServerOffline(true);
  } catch {
    addLog("done", "服务已关闭（连接已断开）");
    setServerOffline(true);
  }
});

refreshStatus();
connectEvents();
