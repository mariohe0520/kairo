# Changelog

All notable changes to Kairo AI Clip Editor.

---

## [2.0.0] — 2026-03-01

### Security
- **API keys moved to `.env`** — Added `config.py` that auto-loads `.env` with `python-dotenv` fallback. Keys never hardcoded.
- **`.env.example` added** — Template with all configurable variables and documentation.
- **`.env` confirmed in `.gitignore`** — API keys cannot be accidentally committed.

### Bug Fixes (P1)
- **Fixed frames directory never cleaned up** — `pipeline.py` now has a `finally` block that deletes `output/frames/<video>/` after each pipeline run. A 1-hour video creates ~500MB of frames; this was a silent disk exhaustion bug.
- **Fixed unlimited concurrent pipelines** — Added `asyncio.Semaphore` in `server.py` controlled by `KAIRO_MAX_PIPELINES` (default 2). Extra requests now queue gracefully instead of competing for CPU/RAM.

### New Features
- **`config.py`** — Centralized environment variable management. All settings (`KAIRO_PORT`, `KAIRO_HOST`, `KAIRO_WHISPER_MODEL`, `KAIRO_MAX_UPLOAD_GB`, `KAIRO_MAX_PIPELINES`, `KAIRO_CLEANUP_FRAMES`) in one place.
- **Queue status broadcast** — When pipeline is waiting for a free slot, frontend now shows "Queued – waiting for pipeline slot" with a live status update.
- **ETA display** — Progress bar now shows estimated time remaining (e.g., "23% · ETA 2m 30s"), calculated from elapsed time and current progress.
- **Friendly error messages** — Raw exception strings are now translated to human-readable messages: FFmpeg not found, URL invalid, no highlights found, file too large, timeout.
- **File size validation** — Frontend now shows file size when a file is selected and warns if it exceeds 10 GB before uploading.
- **`python-dotenv` added** to `requirements.txt` for clean `.env` parsing.

### Documentation
- **Complete `README.md`** — Quick start, system requirements, configuration guide, pipeline explanation, API reference, template catalog, troubleshooting.
- **`AGENTS.md`** — Complete technical reference for AI agents working on this codebase: tech stack, project structure, pipeline stages, API endpoints, code conventions.
- **`AUDIT_REPORT.md`** — Full audit: architecture diagram, health score (80/100), bug catalog with priorities, security analysis, feature completeness assessment, fix roadmap.

---

## [1.0.0] — 2026-02-28

### Initial Release
- 7-stage autonomous AI pipeline: Ingest → Caption → Discover → Architect → Render → Evaluate → Self-correct
- FastAPI backend with WebSocket real-time progress
- Vanilla JS SPA frontend (no framework, no build step)
- Support for YouTube, Twitch, Bilibili, TikTok URLs via yt-dlp
- Whisper ASR for speech transcription
- MLX-VLM visual frame analysis (Apple Silicon, optional)
- Ollama/mlx-lm narrative script generation (optional)
- Claude API and OpenAI API LLM highlight detection (optional)
- Heuristic fallback for all AI stages (no API keys required)
- VideoToolbox hardware acceleration on macOS
- 10 editing templates × 5 streamer personas
- Streamer memory/learning system (EMA + cosine similarity)
- Demo mode for GitHub Pages (no backend required)
- One-click `./start.sh` launcher
