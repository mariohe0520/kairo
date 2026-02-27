# Kairo AI Clip Editor -- Quick Start

## One-Click Launch

```bash
cd /Users/mario/.openclaw/workspace/apps/kairo
./start.sh
```

This will:
1. Install Python dependencies
2. Check for ffmpeg, yt-dlp, whisper
3. Start the server on http://localhost:8420
4. Open your browser automatically

## Manual Launch

```bash
pip install -r requirements.txt
python3 -m uvicorn server:app --host 127.0.0.1 --port 8420 --reload
```

Then open http://localhost:8420

## How to Use

1. **Open** http://localhost:8420 in your browser
2. **Paste** a YouTube, Twitch, or Bilibili URL into the input bar
   - Or **drag and drop** a local video file (MP4, MOV, MKV, WebM)
3. **Choose a template** (optional) -- scroll down to pick a style like "Clutch Master" or "TikTok Vertical"
4. **Click "Create Viral Clip"**
5. **Watch** the AI pipeline process your video with real-time progress
6. **Download** your finished clip when it's ready

## System Requirements

- **Python 3.10+** (tested with 3.12+)
- **ffmpeg** -- `brew install ffmpeg` (required for video processing)
- **yt-dlp** -- `brew install yt-dlp` (required for URL downloads)
- **whisper** -- `pip install openai-whisper` (required for speech-to-text)

## Optional: AI-Powered Highlight Detection

Set one of these environment variables for LLM-based highlight detection:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # Claude API
export OPENAI_API_KEY=sk-...           # OpenAI API
```

Without an API key, the system uses heuristic-based highlight detection
(still works, just less intelligent).

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/health` | GET | Health check |
| `/api/pipeline` | POST | One-click: URL/file -> viral clip |
| `/api/ingest` | POST | Download + transcribe a video |
| `/api/analyze` | POST | Analyze a video for highlights |
| `/api/generate` | POST | Generate an edit script |
| `/api/render` | POST | Render a video from edit script |
| `/api/highlights` | POST | LLM-based highlight detection |
| `/api/templates` | GET | List editing templates |
| `/api/personas` | GET | List streamer personas |
| `/api/jobs` | GET | List all jobs |
| `/api/jobs/{id}` | GET | Get job status |
| `/api/jobs/{id}/download` | GET | Download job output |
| `/ws/progress` | WebSocket | Real-time progress updates |
| `/docs` | GET | Interactive API documentation |

## Architecture

```
User (Browser at localhost:8420)
       |
       v
  [FastAPI Server]  (server.py)
       |
       +-- /api/pipeline  (one-click autonomous pipeline)
       |     |
       |     +-- Ingest:    yt-dlp download, ffmpeg audio extract, Whisper ASR
       |     +-- Caption:   Frame analysis (VLM + heuristics)
       |     +-- Discover:  Triangulation-scored clip candidate ranking
       |     +-- Architect: Narrative edit script generation
       |     +-- Render:    FFmpeg-based intelligent video assembly
       |     +-- Evaluate:  Quality scoring (5 criteria)
       |     +-- Select:    Best candidate selection
       |
       +-- /ws/progress  (WebSocket for real-time updates)
       +-- /web  (Static web UI files)
```

## Troubleshooting

**Server won't start:**
- Check if port 8420 is already in use: `lsof -i :8420`
- Try a different port: `KAIRO_PORT=8421 ./start.sh`

**Video download fails:**
- Make sure yt-dlp is installed: `yt-dlp --version`
- Update yt-dlp: `pip install -U yt-dlp`

**Transcription is slow:**
- Whisper's `base` model is used by default (good balance of speed/accuracy)
- For faster transcription: install with GPU support

**No highlights detected:**
- Set ANTHROPIC_API_KEY or OPENAI_API_KEY for LLM-powered detection
- Without an API key, the heuristic fallback still works for most content
