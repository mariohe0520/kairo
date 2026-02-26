# Kairo — AI Game Clip Intelligence Agent

An autonomous AI agent that transforms gaming livestream replays into viral short videos with narrative depth, personalized to the streamer's style.

## Architecture

```
Input (Video URL/File)
       ↓
   [Ingest Pipeline]
   yt-dlp download → FFmpeg extract → Whisper ASR → Frame sampling
       ↓
   [Caption Agent] (MLX-VLM local)
   Multi-modal understanding: game events + streamer emotion + chat signals
       ↓
   [DVD Agent] (Deep Video Discovery)
   Scan full stream, score windows, find top-3 viral candidates
       ↓
   [DNA Agent] (Dynamic Narrative Architect)
   Generate frame-accurate editing scripts with anti-fluff validation
       ↓
   [Render Engine]
   FFmpeg-based intelligent editing: cuts, transitions, text overlays, BGM
       ↓
   Output (.mp4 viral short video)
```

## Key Differentiators

1. **Material First, Template Second** — Discover best clips first, then match narrative templates
2. **Tri-modal Triangulation** — Game events × Streamer emotion × Audience reaction
3. **Memory System** — Learns streamer preferences over time
4. **Local-First AI** — MLX models on Apple Silicon for privacy and speed
5. **Anti-Fluff** — Every second must justify its existence

## Tech Stack

- Python 3.14 + MLX (Apple Silicon optimized)
- MLX-VLM for video frame understanding
- Whisper for ASR transcription
- FFmpeg for video processing
- FastAPI + Web UI for interaction
- yt-dlp for video downloading
