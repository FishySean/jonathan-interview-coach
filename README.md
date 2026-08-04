# Jonathan Interview Coach

[![GitHub](https://img.shields.io/badge/GitHub-FishySean%2Fjonathan--interview--coach-blue)](https://github.com/FishySean/jonathan-interview-coach)

把 YouTube Shorts 上 [Jonathan Career](https://www.youtube.com/@MrJonathanCareer) 的面试技巧，提炼成 Claude 可加载的 **Interview Coach Skill**。

- **工具仓库（本 repo）**：`jonathan-interview-coach` — pipeline、可视化界面、蒸馏脚本  
- **可分享产物**：[`data/skill/`](data/skill/) — Agent Skills 布局（瘦身 `SKILL.md` + `references/`）

> 作者：[FishySean](https://github.com/FishySean)（Sean Fan）

## 快速链接

| 你想… | 看这个 |
|--------|--------|
| 只用 Skill，不要跑代码 | [`data/skill/README.md`](data/skill/README.md) |
| 跑 pipeline 抓视频 → 转录 | 下方「安装」+ `python app.py` |
| Skill 更新记录 | [`data/skill/CHANGELOG.md`](data/skill/CHANGELOG.md) |

## Pipeline

```
YouTube Shorts
      ↓
视频下载 (yt-dlp)
      ↓
Transcript 文本库 (Whisper)
      ↓
LLM 知识蒸馏
      ↓
Jonathan Interview OS
      ↓
Claude Skill / Project Knowledge
      ↓
你的私人 AI 面试教练
```

## 目录结构

```
jonathan-interview-coach/
├── app.py               # 主入口（可视化界面）
├── data/                # 本地加工产物
│   ├── raw_videos/      # L1 视频（转录后自动删除）
│   ├── transcripts/     # L2 转录文本
│   ├── distilled/       # L3 按视频蒸馏（by_video/）
│   ├── skill/           # L4 ★ Skill（瘦身 SKILL.md + references/）
│   ├── shorts_urls.txt      # 运行时 URL 列表（gitignore）
│   └── download_archive.txt # 运行时下载记录（gitignore）
├── scripts/             # 自动化脚本（按功能分子目录）
│   ├── paths.py         # 共享路径常量
│   ├── ingest/          # L1 抓取 + 下载
│   ├── transcribe/      # L2 Whisper 转录
│   ├── distill/         # L3 LLM 蒸馏 + 合并 skill
│   ├── pipeline/        # 全流程编排（app / CLI 共用）
│   ├── cli/             # 命令行入口
│   └── tools/           # 维护工具
├── prompts/             # LLM 蒸馏 prompt
├── external/            # 第三方开源 clone
├── requirements.txt
└── README.md
```

## 命名说明

| 文件 | 本项目用途 |
|------|------------|
| `app.py` | **主入口**：启动可视化界面 |
| `./run` | Shell 启动器（自动激活 conda 环境） |
| `python -m scripts.cli.run_channel_shorts_to_transcripts` | CLI 全流程 |

## 当前进度（MVP）

| 阶段 | 状态 | 说明 |
|------|------|------|
| 目录与脚本骨架 | ✅ 完成 | 下载 + 转录 pipeline 可跑 |
| 可视化界面 | ✅ 完成 | `app.py` + 实时广播面板 |
| YouTube 下载 | ✅ 完成 | 支持 URL 列表 / `urls.txt` |
| 频道批量抓取 | ✅ 完成 | 自动抓取 `@MrJonathanCareer` Shorts |
| Whisper 转录 | ✅ 完成 | faster-whisper / 原版 whisper，输出 `.md` |
| LLM 蒸馏 | ✅ 脚本 | `python -m scripts.distill` + 合并 skill |
| 合并 Skill | ✅ 增量 | 每蒸馏 1 个 transcript → skill 更完善 |

目标频道：[MrJonathanCareer](https://www.youtube.com/@MrJonathanCareer)

## 安装（Anaconda，推荐）

需要 **Anaconda / Miniconda**。

```bash
cd ~/Desktop/jonathan-coach

# 一键创建环境（含 Python、ffmpeg、yt-dlp、faster-whisper、flask）
./setup_env.sh

# 激活环境
conda activate jonathan-coach

# 启动应用
python app.py
```

环境名：`jonathan-coach`  
Python 路径：`/opt/anaconda3/envs/jonathan-coach/bin/python`

> **注意**：不要用系统自带的 `/usr/local/bin/python3` 直接跑 `app.py`，它没有装项目依赖。  
> 在 Cursor 里运行前，请先 `conda activate jonathan-coach`，或执行 `./run`。

### 备选：pip + venv（不用 conda 时）

```bash
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 使用方式

### 可视化界面（推荐，自动贩卖机模式）

```bash
python3 app.py
```

或执行 `./run`。

页面功能：
- 点 **开始运行** 一键执行全流程
- 实时广播：当前阶段、日志、已处理数量
- 展示产物路径：`data/shorts_urls.txt`、`data/raw_videos/`、`data/transcripts/`

首次运行会自动安装依赖。

### 高级：纯命令行（可选）

```bash
python -m scripts.cli.run_channel_shorts_to_transcripts --max-videos 10
```

先跑 3~10 个 Shorts 验证质量：

```bash
python -m scripts.cli.run_channel_shorts_to_transcripts \
  --channel "@MrJonathanCareer" \
  --max-videos 10 \
  --language en \
  --model small
```

想全量跑（`--max-videos 0` 不限制）：

```bash
python -m scripts.cli.run_channel_shorts_to_transcripts \
  --channel "@MrJonathanCareer" \
  --max-videos 0 \
  --language en \
  --model medium
```

脚本会依次完成：
- 抓取 Shorts URL → 写入 `data/shorts_urls.txt`
- 下载 → `data/raw_videos/`（通过 `data/download_archive.txt` 避免重复）
- 转录 → `transcripts/`

### 可选：分步执行

### Step 1：抓取频道 Shorts URL

```bash
python -m scripts.ingest.fetch_channel_shorts \
  --channel "@MrJonathanCareer" \
  --output urls.txt \
  --max-videos 10
```

### Step 2：下载视频

```bash
python -m scripts.ingest.download_youtube \
  --file urls.txt \
  --download-archive data/download_archive.txt
```

### Step 3：转录为文字

```bash
python -m scripts.transcribe --model medium --language en
```

输出保存到 `transcripts/`，与视频同名（`.md` 或 `.txt`）。

- 下载 → `data/raw_videos/`
- 转录 → `data/transcripts/`

### Step 4：LLM 蒸馏（自动化）

在 `.env` 配置（OpenAI 通常比 Claude API 更容易获取）：

```bash
OPENAI_API_KEY=sk-...
```

```bash
# 先试 1 个，检查质量
python -m scripts.distill --limit 1 --model gpt-4o

# 满意后跑剩余
python -m scripts.distill --limit 9 --model gpt-4o
```

每蒸馏 **1 个 transcript**：
- 写入 `data/distilled/by_video/{视频名}.md`
- 自动 **重新合并** skill 包：瘦身 [`SKILL.md`](data/skill/SKILL.md) + 同步 [`references/by_video/`](data/skill/references/by_video/)

**最终产物**：`data/skill/` — 按 Agent Skills progressive disclosure 组织（入口短、细节按需加载）。

### 修复损坏视频

若某个视频下载不完整（如 HTTP 500 只留下 `.f140.m4a`）：

```bash
python -m scripts.tools.fix_broken_video
```

### Step 5：装进 Claude（按需切换人格）

**Claude Code / Cursor skill（推荐）**

```bash
mkdir -p .claude/skills/jonathan-interview-coach
cp -R data/skill/SKILL.md data/skill/references \
  .claude/skills/jonathan-interview-coach/
```

**Claude Project**

上传 `SKILL.md` + `references/frameworks.md`；按需再加个别 `references/by_video/*.md`。详见 [`data/skill/README.md`](data/skill/README.md)。

## 后续扩展

| 阶段 | 目录 | 说明 |
|------|------|------|
| 蒸馏 | `distilled/by_video/` | 每条 Short 的完整蒸馏（源） |
| Skill | `skill/` | 瘦身入口 + `references/` 按需加载 |
| API | `scripts/distill/` | Ollama / OpenAI / Anthropic 批量蒸馏 |

蒸馏目标**不是简单总结**，而是提取：

- 面试原则（Principles）
- 面试官判断标准（Evaluation Criteria）
- 常见候选人错误（Mistakes）
- Jonathan 风格追问方式（Follow-up Questions）
- 优秀回答结构（Answer Framework）

## 发布到 GitHub

```bash
# 在 GitHub 新建仓库：jonathan-interview-coach
# https://github.com/new  → Owner: FishySean

cd jonathan-interview-coach
git init
git add .
git commit -m "Initial commit: pipeline + skill v0.2 (2 videos)"
git branch -M main
git remote add origin https://github.com/FishySean/jonathan-interview-coach.git
git push -u origin main
```

**建议提交的内容：**

- ✅ `data/skill/`（`SKILL.md`、`references/`、`README.md`、`CHANGELOG.md`）
- ✅ `app.py`、`scripts/`、`prompts/`、`ui/`、`README.md`
- ❌ `data/transcripts/`、`data/raw_videos/`、`data/distilled/`、`.env`（已在 `.gitignore`）

别人 clone 后只想用 Skill → 读 [`data/skill/README.md`](data/skill/README.md)，拷贝整个 `data/skill/` 目录即可。

## 环境变量（后续 API 阶段）

```bash
# .env（不要提交到 git）
ANTHROPIC_API_KEY=sk-ant-...
```

## 常见问题

**下载失败？** 确认依赖完整：`pip install -U 'yt-dlp[default]'`（含 JS challenge 求解器）。Chrome 登录 YouTube 后关掉浏览器再跑；可用 `JONATHAN_COACH_COOKIES_FROM_BROWSER=chrome`。

**转录很慢？** 先用 `--model small` 或 `--model base` 快速验证 pipeline；有 NVIDIA GPU 时 faster-whisper 会自动加速。

**文件名乱码？** 脚本使用 `restrictfilenames`，特殊字符会被替换为安全字符。

## License

Private use — 视频内容版权归原博主所有，本项目仅用于个人学习。
