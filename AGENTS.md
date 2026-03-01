# AGENTS.md — Kairo AI 剪辑

## 项目概述
- AI 驱动的游戏直播视频剪辑工具
- 目标：将游戏直播（本地文件或 URL）自动剪辑为高光短视频
- 本地 Mac 运行，有 Web 前端界面 + Python 后端服务

## 技术栈

### 后端
- **语言**：Python 3.10+
- **框架**：FastAPI + uvicorn（ASGI）
- **核心依赖**：见 `requirements.txt`
  - `fastapi>=0.115.0`、`uvicorn[standard]>=0.32.0`
  - `python-multipart`（文件上传）、`websockets`（进度推送）、`numpy`

### 前端
- **原生 Vanilla JS**（无框架，无构建步骤，无 npm 依赖）
- 单页应用（SPA）：`web/index.html` + `web/app.js` + `web/style.css`
- 支持中英双语（内置 i18n）
- GitHub Pages Demo 模式（无后端也能预览）

### AI 模型
| 功能 | 模型/工具 | 运行方式 |
|------|-----------|----------|
| 视频下载 | yt-dlp | 本地命令行 |
| 语音转文字 | OpenAI Whisper (base/tiny) | 本地命令行 |
| 帧视觉分析 | Qwen2.5-VL-3B-Instruct-4bit (MLX-VLM) | 本地 Apple Silicon，需预先缓存 |
| 高光检测 LLM | Claude API 或 OpenAI API | 外部 API，可选（无 key 自动降级为启发式） |
| 叙事脚本生成 | Ollama / mlx-lm | 本地，可选（无则用模板降级） |

### 视频处理
- **FFmpeg**（brew install ffmpeg）：音频提取、帧采样、视频拼接、字幕烧录、VideoToolbox 硬件加速
- **格式支持**：mp4/mkv/avi/mov/webm/flv/wmv/m4v/ts

### 数据存储
- **无数据库**
- 任务状态：内存 dict（`_jobs`，重启丢失）
- 用户画像：JSON 文件（`memory/profiles/<streamer_id>.json`，持久化）
- 输出文件：`output/uploads/`、`output/audio/`、`output/transcripts/`、`output/frames/`

## 项目结构

```
kairo/
├── server.py               # FastAPI 主服务，所有 REST + WebSocket 端点
├── start.sh                # 一键启动脚本
├── requirements.txt        # Python 依赖
├── core/
│   ├── ingest.py           # 阶段1：下载→音频提取→ASR→帧采样
│   ├── pipeline.py         # 全流水线编排（7 阶段 + 自纠正）
│   ├── render.py           # FFmpeg 渲染引擎
│   └── meta_template.py    # 元模板系统
├── agents/
│   ├── caption_agent.py    # 阶段2：多模态帧理解（VLM + 启发式）
│   ├── dvd_agent.py        # 阶段3：高光候选发现（滑窗评分）
│   └── dna_agent.py        # 阶段4：叙事剪辑脚本生成
├── memory/
│   ├── streamer_memory.py  # 用户偏好学习系统（EMA + 余弦相似度）
│   └── profiles/           # 用户画像 JSON 文件（.gitignore 排除）
├── web/                    # 前端（与 docs/ 保持同步）
│   ├── index.html
│   ├── app.js
│   └── style.css
└── docs/                   # GitHub Pages 部署副本（cp web/* docs/）
```

## 7 阶段 AI 流水线

```
上传/URL → Ingest → Caption → Discover(DVD) → Architect(DNA) → Render → Evaluate → Self-correct
```

| 阶段 | 模块 | 说明 |
|------|------|------|
| 1. Ingest | `core/ingest.py` | 下载、音频提取、Whisper ASR、帧采样（1fps） |
| 2. Caption | `agents/caption_agent.py` | 逐帧分析：游戏事件、情绪、观众信号 |
| 3. Discover | `agents/dvd_agent.py` | 三角评分（游戏×情绪×观众），叙事弧检测 |
| 4. Architect | `agents/dna_agent.py` | 生成 EDL 脚本：Hook→Rising→Climax→Resolution |
| 5. Render | `core/render.py` | FFmpeg 合成：切段、转场、字幕、BGM 混音 |
| 6. Evaluate | `core/pipeline.py` | 质量评分（5 维度，0-100） |
| 7. Self-correct | `core/pipeline.py` | 质量不达标时自动调参重渲，最多 3 次迭代 |

## 启动方式

```bash
cd /Users/mario/.openclaw/workspace/apps/kairo
./start.sh              # 推荐：自动安装依赖，启动服务，打开浏览器
```

手动启动：
```bash
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8420 --reload
```

访问：
- 前端：http://localhost:8420
- API 文档：http://localhost:8420/docs
- 健康检查：http://localhost:8420/api/health

## API 端点概览

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | /api/health | 服务健康检查 |
| POST | /api/ingest | 上传文件或提交 URL，触发下载+ASR |
| POST | /api/pipeline | 全流水线（上传/URL → 成品视频） |
| GET | /api/jobs/{job_id} | 查询任务状态 |
| GET | /api/jobs | 列出所有任务 |
| GET | /api/download/{job_id} | 下载输出视频 |
| GET | /api/templates | 获取编辑模板列表 |
| GET | /api/personas | 获取主播画像列表 |
| POST | /api/feedback | 提交用户反馈（驱动学习） |
| WebSocket | /ws/progress | 实时进度推送 |

## 测试方式

```bash
# 基础健康检查（服务启动后）
curl http://localhost:8420/api/health

# 跳过流水线的快速测试（模块单测）
python3 test_pipeline.py --skip-pipeline

# 完整端到端测试（会下载真实视频，耗时较长）
python3 test_pipeline.py
```

手动验收流程：
1. 打开 http://localhost:8420
2. 拖入一段游戏视频或粘贴 Bilibili/YouTube URL
3. 选择模板，点击「Create Viral Clip」
4. 观察进度仪表盘的 4 个阶段指示器
5. 下载输出视频，检查质量

## 环境变量

| 变量 | 说明 | 必填 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Claude API（高光 LLM 检测） | 否（降级为启发式） |
| `OPENAI_API_KEY` | OpenAI API（备选 LLM） | 否（降级为启发式） |
| `KAIRO_PORT` | 服务端口（默认 8420） | 否 |
| `KAIRO_HOST` | 绑定 IP（默认 127.0.0.1） | 否 |

## 系统依赖（brew 安装一次）

```bash
brew install ffmpeg yt-dlp
pip install openai-whisper
```

## 代码规范

- **中文注释**优先（面向中文用户的项目）
- 不删除现有功能，只扩展
- API Key 仅通过环境变量读取，严禁硬编码
- 新增 API 端点遵循 `/api/*` 前缀规范
- 视频处理改动必须兼容工具缺失场景（给清晰报错，不崩溃）
- 不随意修改输出目录结构或 Job 数据结构（破坏下载接口）
- FFmpeg 命令：`-accurate_seek -ss` 必须放在 `-i` **之前**（输入选项）
- VideoToolbox 编码器使用 `-q:v 65`，不用 `-crf`（libx264 专属）
- `_ws_connections` 去重用 `.difference_update(dead)`，不用 `-=`

## 部署 Web UI 到 GitHub Pages

```bash
cp web/index.html docs/index.html
cp web/app.js docs/app.js
cp web/style.css docs/style.css
git add -A && git commit -m "sync web UI to docs/" && git push
```
