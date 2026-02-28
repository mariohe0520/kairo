# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This App Does

AI video clip editor. Upload a long video (or paste a URL) → pipeline automatically finds the best highlight moments → renders a finished short video. Designed to run on the Mac Mini with a web UI accessible from any browser.

## Running

```bash
./start.sh                  # recommended: auto-installs deps, opens browser
# OR manually:
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8420 --reload
```

Server: `http://localhost:8420` — Swagger API docs: `http://localhost:8420/docs`

System deps (install once):
```bash
brew install ffmpeg yt-dlp
pip install openai-whisper
```

## Architecture: 7-Stage Pipeline

```
Upload/URL → Ingest → Caption → Discover → Architect → Render → Evaluate → Self-correct
```

| File | Role |
|------|------|
| `core/pipeline.py` | Orchestrates all 7 stages. `KairoPipeline.run()` is the entry point. Emits progress events via `_emit_progress()`. Self-corrects up to 3 iterations if quality fails. |
| `core/ingest.py` | Download (yt-dlp), audio extract, Whisper ASR, frame sampling |
| `core/render.py` | FFmpeg render engine. `RenderEngine.render()` takes an `EditScript` → output MP4. Handles segment cutting, xfade transitions, subtitle burning (ASS format), BGM mixing. VideoToolbox HW accel on macOS. |
| `agents/caption_agent.py` | Frame understanding. Uses VLM (Qwen2.5-VL) if locally cached, otherwise heuristics. Check `_is_vlm_cached()` before downloading — model is 3GB. |
| `agents/dvd_agent.py` | Scores clip candidates (Discover stage) |
| `agents/dna_agent.py` | Generates edit scripts from clip candidates (Architect stage) |
| `server.py` | FastAPI app. REST endpoints + WebSocket `/ws/progress` for real-time progress. Serves `web/` as static files. Job state stored in `_jobs` dict. |
| `web/` | Frontend SPA (index.html + app.js + style.css). Demo mode works without backend (GitHub Pages). |
| `docs/` | GitHub Pages copy of `web/` — must stay in sync: `cp web/* docs/` |

## Critical FFmpeg Rules

- `-accurate_seek` and `-ss` are **INPUT options** — must appear BEFORE `-i input_file`, never after
- When cutting segments: order is `ffmpeg -y [-hwaccel] -accurate_seek -ss START -i input.mp4 -t DURATION [encoding] output.mp4`
- VideoToolbox encoder: use `h264_videotoolbox` with `-q:v 65` (not `-crf` which is libx264 only)

## Critical Python Rules

- `_ws_connections` is a module-level `set` — use `_ws_connections.difference_update(dead)` for in-place removal, NOT `-=` which creates a local binding and causes `UnboundLocalError`
- Pipeline output path: `result.output_video` — empty string means render failed; check logs for FFmpeg exit codes

## Deploying Web UI

```bash
cp web/index.html docs/index.html
cp web/app.js docs/app.js
cp web/style.css docs/style.css
git add -A && git commit -m "..." && git push
```

GitHub Pages serves from `docs/` on the `main` branch.
