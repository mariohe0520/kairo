# AUDIT_REPORT.md — Kairo AI 剪辑 全面审计报告

> 审计时间：2026-03-01
> 审计人：Claude Sonnet 4.6（全栈架构审计）
> 审计范围：所有源文件（server.py / core/ / agents/ / memory/ / web/）

---

## 1. 架构图

```
┌─────────────────────────────────────────────────────┐
│                   浏览器 (Web UI)                    │
│  web/index.html + app.js + style.css (Vanilla JS)   │
│  - URL 输入 / 文件拖拽上传                           │
│  - 模板选择 / 主播画像                               │
│  - 实时进度仪表盘（WebSocket）                       │
│  - 视频播放器 + 下载 + 反馈星级                      │
└────────────────┬────────────────────────────────────┘
                 │ HTTP REST + WebSocket
                 ▼
┌─────────────────────────────────────────────────────┐
│          FastAPI Server (server.py) :8420           │
│  - REST API (/api/*)                                │
│  - WebSocket (/ws/progress) 实时进度广播             │
│  - 静态文件服务 (web/ 目录)                          │
│  - 内存任务队列 (_jobs dict)                         │
│  - StreamerMemory 用户画像服务                       │
└────────────────┬────────────────────────────────────┘
                 │ BackgroundTasks 异步调度
                 ▼
┌─────────────────────────────────────────────────────┐
│              7 阶段 AI 流水线 (core/pipeline.py)    │
│                                                     │
│  [1] Ingest (core/ingest.py)                        │
│       yt-dlp 下载 → ffmpeg 音频提取 → Whisper ASR   │
│       → ffmpeg 帧采样 → 音频能量计算                 │
│                                                     │
│  [2] Caption (agents/caption_agent.py)              │
│       MLX-VLM (Qwen2.5-VL) 帧分析                  │
│       或 关键词启发式（VLM 未缓存时降级）             │
│                                                     │
│  [3] Discover (agents/dvd_agent.py)                 │
│       滑窗三角评分 × 3 策略（峰值/弧/动量）           │
│       叙事弧检测，Anti-clustering 去重               │
│                                                     │
│  [4] Architect (agents/dna_agent.py)                │
│       Ollama/mlx-lm 生成 EDL 叙事脚本               │
│       或确定性模板降级                               │
│                                                     │
│  [5] Render (core/render.py)                        │
│       FFmpeg：切段 + xfade 转场 + ASS 字幕           │
│       + BGM 混音 + VideoToolbox 硬件加速             │
│                                                     │
│  [6] Evaluate → [7] Self-correct (最多 3 次)        │
└─────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────┐
│           持久化存储                                 │
│  output/uploads/   上传的原始视频                    │
│  output/audio/     提取的 WAV 音频                   │
│  output/transcripts/  Whisper JSON 字幕              │
│  output/frames/    采样帧（pipeline 后不自动删除）    │
│  output/*.mp4      最终渲染视频                      │
│  memory/profiles/  用户画像 JSON（持久化）            │
└─────────────────────────────────────────────────────┘
```

---

## 2. 技术栈确认

| 层 | 技术 | 版本约束 |
|----|------|----------|
| 后端语言 | Python | 3.10+（使用 match/case 语法） |
| Web 框架 | FastAPI | >=0.115.0 |
| ASGI 服务器 | uvicorn[standard] | >=0.32.0 |
| 前端 | 原生 Vanilla JS | 无框架，无构建步骤 |
| 视频下载 | yt-dlp | >=2024.0.0 |
| 视频处理 | FFmpeg | 系统安装（brew） |
| 语音识别 | OpenAI Whisper | pip（命令行工具） |
| 视觉分析 | MLX-VLM / Qwen2.5-VL-3B | 本地 Apple Silicon（可选） |
| 叙事生成 | Ollama 或 mlx-lm | 本地（可选） |
| LLM 高光检测 | Claude API / OpenAI API | 外部（可选） |
| 数据持久化 | 无数据库；JSON 文件 | 用户画像只有 JSON |
| 任务管理 | 内存 dict | 无持久化，重启丢失 |
| Electron 壳 | Electron 33 | 存在 package.json，当前未使用 |

---

## 3. 健康度评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构设计 | 88/100 | 分层清晰，7 阶段流水线设计优秀 |
| 前端完整度 | 82/100 | UI 完整，缺少视频预览前的缩略图、上传进度条 |
| 后端 API 设计 | 79/100 | RESTful 风格，缺少文件大小限制和请求频率限制 |
| AI 核心逻辑 | 85/100 | 三角评分、叙事弧检测算法扎实 |
| 错误处理 | 72/100 | 有降级机制，但部分错误信息不够友好 |
| 安全性 | 90/100 | API Key 安全，无硬编码，缺少上传类型严格校验 |
| 性能 | 65/100 | 单进程阻塞，无任务队列，大文件有风险 |
| 代码质量 | 84/100 | 注释清晰，数据类型完善，测试覆盖偏少 |
| **综合** | **80/100** | 架构扎实，可用性强，性能和健壮性需优化 |

---

## 4. Bug 清单

### P0 — 阻塞性/数据安全

> 暂无 P0 级别问题（无硬编码密钥，无明显崩溃路径）

### P1 — 高优先级功能缺陷

**[P1-001] 文件上传无大小限制**
- 位置：`server.py` 的 `POST /api/pipeline` 和 `POST /api/ingest`
- 问题：`UploadFile` 接受任意大小文件，可被 100GB+ 文件打爆内存
- 影响：服务崩溃，OOM
- 修复：在 FastAPI 中设置 `max_upload_size`（如 10GB），或在读取前检查 `content-length`

**[P1-002] frames 目录不自动清理**
- 位置：`core/ingest.py` 的 `sample_frames()`，输出到 `output/frames/<video_stem>/`
- 问题：每次 pipeline 会提取数千帧（1fps × 视频时长秒数），1 小时视频 = 3600 帧 JPEG，约 500MB
- 影响：磁盘快速耗尽
- 修复：pipeline 完成后删除帧目录，或只保留最近 N 次

**[P1-003] 并发 pipeline 任务互相干扰**
- 位置：`server.py` + `core/pipeline.py`
- 问题：多个 pipeline 任务并发时，`subprocess.run(whisper ...)` 等重 CPU 操作会互相争抢资源，无任务队列限制
- 影响：服务响应超时，任务失败
- 修复：加一个全局信号量（asyncio.Semaphore），限制同时最多 1-2 个 pipeline 任务

### P2 — 中优先级缺陷

**[P2-001] 任务状态内存存储，重启丢失**
- 位置：`server.py` 的 `_jobs: dict`
- 问题：服务重启后，所有进行中和已完成的任务状态全部丢失，前端 History 页面清空
- 修复：将 `_jobs` 持久化到 SQLite 或 JSON 文件

**[P2-002] output/ 目录无限增长**
- 位置：`output/uploads/`、`output/audio/`、`output/transcripts/`
- 问题：每次处理的中间文件（WAV、transcript JSON）和原始上传文件都不清理
- 影响：长期运行后磁盘耗尽
- 修复：保留最近 N 个任务的文件，或定期清理超过 7 天的文件

**[P2-003] 上传文件扩展名校验仅对本地路径生效**
- 位置：`core/ingest.py:198-204`
- 问题：URL 下载的视频不经过扩展名校验；上传的文件通过 `accept="video/*"` 在前端过滤，但后端未二次校验 MIME 类型
- 修复：在 server.py 上传处理后检查实际文件魔数（magic bytes）

**[P2-004] DNA Agent 的 Ollama subprocess 无超时限制**
- 位置：`agents/dna_agent.py` 中调用 Ollama 的部分
- 问题：如果本地 LLM 服务无响应，subprocess 会无限等待
- 修复：添加 `timeout=60` 到 subprocess.run

**[P2-005] WebSocket 进度广播在服务关闭时未清理**
- 位置：`server.py` 的 `_ws_connections`
- 问题：服务端关闭时，已连接的 WebSocket 客户端没有收到关闭通知
- 修复：在 `lifespan` 的 shutdown 阶段发送 close 帧给所有连接

**[P2-006] yt-dlp 下载超时 3600 秒（1小时）可能不足**
- 位置：`core/ingest.py:52`
- 问题：超长直播录像（6小时+）下载可能超时
- 修复：增加 timeout 或改用流式下载

### P3 — 低优先级/体验问题

**[P3-001] Electron 相关代码存在但未使用**
- 位置：`package.json`、`main.js`、`preload.js`
- 问题：有 Electron 依赖但 `./start.sh` 不使用它，造成混乱
- 建议：删除 Electron 相关文件，或单独维护 Electron 启动模式

**[P3-002] 进度百分比在前端可能停顿**
- 位置：`web/app.js` WebSocket 处理
- 问题：Caption 阶段（帧分析）耗时最长，但进度更新粒度取决于 batch_size，可能出现长时间卡在某个百分比
- 修复：在 caption_agent 中增加 per-frame 进度回调

**[P3-003] History 页面没有分页**
- 位置：`web/app.js` + `GET /api/jobs`
- 问题：所有任务一次性返回，任务多时性能差
- 修复：增加分页参数

**[P3-004] Share 按钮功能未实现**
- 位置：`web/index.html:252`
- 问题：Share 按钮存在但点击无任何效果（或仅复制链接）
- 修复：实现分享到剪贴板或系统分享 API

**[P3-005] 音频能量解析不够鲁棒**
- 位置：`core/ingest.py:152-172` 的 `compute_audio_energy()`
- 问题：通过解析 ffmpeg stderr 的文本输出提取 RMS，ffmpeg 版本更新可能导致格式变化破坏解析
- 修复：改用 `ffprobe` + JSON 格式输出，或引入 `librosa`

---

## 5. API Key 安全报告

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 硬编码 API Key | ✅ 安全 | 全项目无任何硬编码密钥 |
| 环境变量读取 | ✅ 安全 | `os.environ.get("ANTHROPIC_API_KEY")` 等 |
| .gitignore 排除 .env | ✅ 安全 | `.gitignore` 已包含 `.env` |
| 前端代码暴露密钥 | ✅ 安全 | 前端仅连接同源 API，无直接 API 调用 |
| 敏感文件提交 Git | ✅ 安全 | 未发现 .env 文件被提交 |
| memory/profiles 排除 | ✅ 安全 | `.gitignore` 已排除 `memory/profiles/` |
| output 目录排除 | ✅ 安全 | `.gitignore` 已排除 `output/` |
| CORS 配置 | ⚠️ 需确认 | server.py 配置了 CORS，需确认是否限制了允许的 Origin |
| 文件路径穿越 | ⚠️ 低风险 | 下载接口通过 job_id 索引文件，但需确认 job.result 路径未被用户篡改 |

**结论**：API Key 安全性良好。主要风险点是 CORS 配置和文件下载路径校验，需二次确认。

---

## 6. 功能完成度

### MVP 功能（已实现）
- ✅ 本地文件上传并处理
- ✅ URL 粘贴下载（YouTube/Bilibili/Twitch via yt-dlp）
- ✅ 7 阶段 AI 流水线自动运行
- ✅ WebSocket 实时进度推送
- ✅ 视频下载接口
- ✅ 10 个编辑模板
- ✅ 5 个主播画像
- ✅ 用户反馈（星级评分 + approve/reject）
- ✅ 偏好学习（StreamerMemory EMA + 余弦相似度）
- ✅ 模板推荐 API
- ✅ 中英双语 UI
- ✅ 健壮的降级机制（无 VLM/LLM 时自动启发式）

### 空壳 / 部分实现
- ⚠️ **Share 功能**：按钮存在，但功能未实现
- ⚠️ **视频预览**：结果页有播放器，但上传后的原视频预览缺失
- ⚠️ **BGM 混音**：render.py 中有 BGM 相关代码，但 BGM 文件来源未确认（是否有内置音乐库？）
- ⚠️ **字幕样式**：支持 ASS 格式字幕，但样式配置入口不明显
- ⚠️ **Electron 桌面版**：package.json 存在，main.js/preload.js 存在，但 start.sh 不使用

### 计划中 / 未实现
- ❌ 垂直视频（9:16）自动裁剪（tiktok-vertical 模板提到但 render.py 中未见裁剪逻辑）
- ❌ 真正的队列系统（当前 BackgroundTasks 无队列保证）
- ❌ 任务历史持久化（重启丢失）
- ❌ 多用户隔离（单机个人使用，无身份认证）
- ❌ 云存储/CDN 输出（纯本地）

---

## 7. 性能瓶颈分析

| 瓶颈 | 严重程度 | 说明 |
|------|----------|------|
| Whisper 转录 | ⭐⭐⭐⭐ | 最慢阶段。1 小时视频约需 10-30 分钟（base 模型，CPU）。Apple Silicon 有优化 |
| 帧采样 + VLM 分析 | ⭐⭐⭐⭐ | 若使用 VLM，每帧约 0.5-2 秒，1 小时视频 = 3600 帧，极慢 |
| FFmpeg 渲染 | ⭐⭐⭐ | VideoToolbox 硬件加速可缓解，通常数十秒内完成 |
| subprocess.run 阻塞事件循环 | ⭐⭐⭐ | BackgroundTasks 在主线程执行，但 subprocess 会阻塞，多任务并发时响应变慢 |
| 内存占用（大视频） | ⭐⭐⭐ | 上传文件写入磁盘后释放，但帧目录可能同时存多个任务的数千帧 |
| 无 CDN，视频在本地服务 | ⭐⭐ | 下载接口通过 FastAPI 的 FileResponse 传输，大文件会占用 uvicorn 线程 |

**最慢路径**：Whisper ASR → VLM 帧分析（如果 Qwen2.5-VL 已缓存）
**实际体验**：对于典型 30 分钟游戏录像，全流水线约需 **5-15 分钟**（无 VLM，heuristic 模式）

---

## 8. 修复优先级

### 本周必修（影响可用性）

| 优先级 | Bug | 工作量 |
|--------|-----|--------|
| P1-001 | 文件上传无大小限制 | 小（加 middleware 或 header check） |
| P1-002 | frames 目录不清理 | 小（pipeline 完成后 shutil.rmtree） |
| P1-003 | 并发 pipeline 无限制 | 小（asyncio.Semaphore(1)） |

### 近期优化（影响体验）

| 优先级 | Bug | 工作量 |
|--------|-----|--------|
| P2-001 | 任务状态不持久化 | 中（JSON 文件存储） |
| P2-002 | output 目录不清理 | 小（定时清理脚本） |
| P2-004 | DNA Agent 无超时 | 极小（加 timeout 参数） |

### 长期改进

| 优先级 | Bug | 工作量 |
|--------|-----|--------|
| P3-001 | 清理 Electron 相关文件 | 极小 |
| P3-002 | Caption 阶段进度粒度 | 中 |
| P3-004 | Share 功能实现 | 小 |

---

## 总结

Kairo 的**架构设计非常扎实**：7 阶段流水线、三角评分算法、叙事弧检测、自纠正机制、偏好学习系统，代码质量远超原型级别。

**最需要解决的 3 个问题**：
1. 上传大小限制（防止 OOM 崩溃）
2. frames 目录清理（防止磁盘耗尽）
3. 并发限制（防止资源争抢）

这 3 个修复合计不超过 20 行代码，却能大幅提升稳定性。其余功能已达到可正常使用的质量水平。
