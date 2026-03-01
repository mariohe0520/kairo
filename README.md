# Kairo AI Clip Editor

> AI-powered game highlight extraction and short video generator.
> Upload a long gaming VOD → get a TikTok-ready clip in minutes.

---

## What It Does

Kairo watches your game recordings and automatically:

1. **Detects highlight moments** — kills, comebacks, emotional peaks, audience reactions
2. **Builds a narrative arc** — Hook → Rising → Climax → Resolution
3. **Renders a polished short video** — transitions, subtitles, BGM, optimized for TikTok / Shorts

No coding needed. Runs entirely on your Mac.

---

## Quick Start

```bash
cd /Users/mario/.openclaw/workspace/apps/kairo
./start.sh
```

Opens `http://localhost:8420` automatically.

### Manual Start

```bash
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8420 --reload
```

---

## System Requirements

| Tool | Install | Required |
|------|---------|---------|
| Python 3.10+ | `brew install python3` | Yes |
| FFmpeg | `brew install ffmpeg` | Yes (video processing) |
| yt-dlp | `brew install yt-dlp` | Yes (URL downloads) |
| Whisper | `pip install openai-whisper` | Yes (speech-to-text) |
| MLX-VLM | auto-loaded from cache | No (visual AI, Apple Silicon) |
| Ollama | `brew install ollama` | No (local LLM scripts) |

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

**.env file:**
```bash
# LLM API Keys (optional — enables AI-powered highlight detection)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Server (optional, defaults shown)
# KAIRO_PORT=8420
# KAIRO_HOST=127.0.0.1

# Processing (optional, defaults shown)
# KAIRO_WHISPER_MODEL=base
# KAIRO_MAX_UPLOAD_GB=10
# KAIRO_MAX_PIPELINES=2
# KAIRO_CLEANUP_FRAMES=1
```

**Without API keys:** Kairo still works using heuristic highlight detection (pattern matching + audio energy analysis). LLM keys improve accuracy but aren't required.

---

## How to Use

1. Open **http://localhost:8420**
2. **Paste a URL** (YouTube, Twitch, Bilibili, Douyin) or **drag-drop a video file**
3. Pick an editing **template** (e.g., "Comeback King", "Kill Montage")
4. Pick a **streamer persona** (optional — tunes the editing style)
5. Click **「Create Viral Clip」**
6. Watch the 4-stage progress indicator (with live ETA)
7. **Download** your finished clip

---

## Supported Formats

**Input files:** MP4, MKV, AVI, MOV, WebM, FLV, WMV, M4V, TS (up to 10 GB)
**Input URLs:** YouTube, Twitch, Bilibili, Douyin, TikTok, and 1000+ sites via yt-dlp
**Output:** Web-compatible H.264 MP4, optimized for mobile viewing

---

## AI Pipeline (7 Stages)

```
Upload/URL → Ingest → Caption → Discover → Architect → Render → Evaluate → Self-correct
```

| Stage | What Happens |
|-------|-------------|
| 1. Ingest | Download video, extract audio, Whisper transcription, frame sampling at 1fps |
| 2. Caption | Analyze each frame: game events, emotion, audience signals (VLM or heuristics) |
| 3. Discover | Score clip candidates using geometric mean (game × emotion × audience) |
| 4. Architect | Generate edit script: Hook → Rising → Climax → Resolution |
| 5. Render | FFmpeg: cut segments, xfade transitions, burn subtitles, mix BGM |
| 6. Evaluate | Quality scoring across 5 dimensions (0–100) |
| 7. Self-correct | If score < threshold, adjust parameters and re-render (up to 3x) |

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/pipeline` | Start full pipeline (file upload or URL) |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/{id}` | Get job status and result |
| GET | `/api/jobs/{id}/stream` | Stream video for browser playback |
| GET | `/api/jobs/{id}/download` | Download output video |
| GET | `/api/templates` | Available editing templates |
| GET | `/api/personas` | Available streamer personas |
| POST | `/api/feedback` | Submit clip rating (drives learning) |
| WS | `/ws/progress` | Real-time progress updates |

Full Swagger docs: **http://localhost:8420/docs**

---

## Editing Templates

| Template | Style | Duration |
|----------|-------|----------|
| Comeback King | Dramatic reversals | 45–120s |
| Clutch Master | Insane clutch plays | 30–90s |
| Kill Montage | Rapid-fire kills | 20–60s |
| Rage Quit Montage | Tilt and fail moments | 30–90s |
| Chill Highlights | Aesthetic vibes | 60–180s |
| Session Story | Full session narrative | 2–5m |
| TikTok Vertical | 9:16 vertical format | 15–60s |
| Hype Montage | Beat-synced highlights | 30–90s |
| Squad Moments | Team plays | 45–150s |
| Educational Breakdown | Annotated analysis | 60–240s |

---

## Security

- `.env` is in `.gitignore` — API keys are never committed to Git
- All LLM keys read from environment variables only
- No external data sent except to the configured LLM provider
- Server listens on `127.0.0.1` (local only) by default

---

## Deploy Web UI to GitHub Pages

```bash
cp web/index.html docs/index.html
cp web/app.js docs/app.js
cp web/style.css docs/style.css
git add -A && git commit -m "sync web UI to docs/" && git push
```

Demo mode (no backend) loads on GitHub Pages automatically.

---

## Troubleshooting

**FFmpeg not found:**
```bash
brew install ffmpeg
```

**No highlights found:**
- Try a longer video (10+ minutes works best)
- Switch to a different template
- Add `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` to `.env` for AI detection

**Queue full:**
- Default limit is 2 concurrent pipelines
- Set `KAIRO_MAX_PIPELINES=4` in `.env` to increase
- Or wait for current jobs to finish

**Disk filling up:**
- Frame files auto-cleanup after each pipeline by default
- Set `KAIRO_CLEANUP_FRAMES=0` to disable

**Video won't play in browser:**
- Server auto-repairs non-web-compatible videos on download
- Try refreshing or use the Download button

**Server won't start:**
```bash
pip install -r requirements.txt
lsof -i :8420  # Check if port is in use
```
