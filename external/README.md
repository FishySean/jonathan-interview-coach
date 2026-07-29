# external/

存放**第三方开源代码与工具**，与本项目自研脚本分离。

## 重要：我们不是「每次从 GitHub 云端调用」

当前 pipeline 的运行时依赖来自 **pip 安装到 `.venv/`**，不是每次运行都去 GitHub 拉代码。

```
pip install -r requirements.txt   ← 只在安装时联网一次
         ↓
.venv/lib/python3.x/site-packages/
  ├── yt_dlp/          ← 下载脚本 import 的是这里
  └── faster_whisper/  ← 转录脚本 import 的是这里
```

`scripts/*.py` 里的 `import yt_dlp` / `from faster_whisper import ...` 读的是**本机已安装的 Python 包**，和 `external/` 目录**目前没有直接关系**。

### 什么时候会发网络请求？

| 操作 | 是否联网 | 频率 | 说明 |
|------|----------|------|------|
| `pip install` | ✅ | 安装时一次 | 从 PyPI 下载 wheel |
| 下载 YouTube 视频 | ✅ | 每个新视频 | 从 YouTube CDN 拉流，无法避免 |
| Whisper 模型权重 | ✅ | **首次**转录时 | 之后走本地缓存 |
| 转录（faster-whisper） | ❌ | — | 模型加载后纯本地 CPU/GPU |
| 抓取 Shorts URL 列表 | ✅ | 每次跑 fetch | 访问 YouTube 页面解析 |
| 从 GitHub clone 到 external/ | ✅ | 你手动执行时 | **不会**被 pipeline 自动调用 |

### clone 到 external/ 能更快吗？

**对日常跑 pipeline 来说，一般不会更快。**

- `git clone` 只是把**源码**拷到本地，方便你阅读、对比版本、打补丁
- 真正执行时，Python 仍然需要 `import` 已编译/安装好的包；光 clone 源码不会自动被脚本用到
- 想从 `external/` 直接跑，需要额外配置（如 `pip install -e external/yt-dlp` 或改 `PYTHONPATH`），复杂度更高，MVP 阶段不推荐

**clone 到 external/ 的真正价值：**

1. **看得清楚**用了哪些开源项目、什么版本
2. **读源码**理解 yt-dlp / faster-whisper 的行为
3. **锁版本**（记录 commit hash），避免 pip 自动升级导致行为变化

### 想减少重复网络请求，应该怎么做？

| 目标 | 做法 |
|------|------|
| 不重复下载视频 | 已有 `download_archive.txt`（yt-dlp archive） |
| 不重复转录 | `transcribe.py` 默认跳过已存在的 transcript |
| 模型只下过一次 | 把缓存放到 `external/hf_cache/`（见下方） |
| 看清用了啥工具 | clone 源码到 external/ + 看本文档 |

## 放什么

| 类型 | 示例 | 说明 |
|------|------|------|
| Git 子模块 / clone | `yt-dlp/`、`whisper/` | 需要读源码、打补丁或 pin 版本时 |
| 独立工具 | 一次性脚本、实验性 fork | 不放进 `scripts/` 的临时代码 |
| 模型权重 | Whisper 模型缓存（可选） | 大文件建议用环境变量指向，见下方 |

## 不放什么

- 项目自己的 pipeline 脚本 → `scripts/`
- 下载的视频、转录文本、蒸馏结果 → `raw_videos/`、`transcripts/`、`distilled/`
- Python 依赖（pip 包）→ 用 `requirements.txt` + 虚拟环境

## 常用操作

```bash
# 克隆 yt-dlp 源码（可选，一般 pip install 即可）
git clone https://github.com/yt-dlp/yt-dlp.git external/yt-dlp

# 克隆 faster-whisper
git clone https://github.com/SYSTRAN/faster-whisper.git external/faster-whisper
```

克隆进本目录的内容默认**不提交到 git**（见根目录 `.gitignore`）。若需版本锁定，可用 git submodule 或在此 README 记录 commit hash。

## 模型缓存（可选）

Whisper 模型默认下载到用户缓存目录。若希望统一到项目内：

```bash
export HF_HOME="$PWD/external/hf_cache"
```

或在 `transcribe.py` 运行时指定 faster-whisper 的 `download_root`。
