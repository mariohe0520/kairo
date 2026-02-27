"""
Kairo FastAPI Server — Bridge between Electron frontend and Python AI backend.

Exposes all pipeline stages (ingest, analyze, generate, render) as REST endpoints
with background task execution. Long-running operations report progress via
WebSocket at /ws/progress.

Run with:
    uvicorn server:app --host 0.0.0.0 --port 8420 --reload
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

from core.ingest import ingest as run_ingest, IngestResult
from core.render import EditBeat, EditScript, RenderEngine, SubtitleSegment
from memory.streamer_memory import (
    Feedback,
    StreamerMemory,
    StreamerProfile,
    TemplateRecommendation,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kairo.server")

# ---------------------------------------------------------------------------
# Job state management
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """In-memory state for a background job."""

    job_id: str
    job_type: str  # ingest, analyze, generate, render
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0  # 0.0 - 1.0
    message: str = ""
    result: Any = None
    error: Optional[str] = None
    created_at: str = ""
    completed_at: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status.value,
            "progress": round(self.progress, 4),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


# Global job store
_jobs: dict[str, Job] = {}

# Global WebSocket connections for progress broadcasting
_ws_connections: set[WebSocket] = set()

# Shared services
_memory = StreamerMemory()
_render_engine = RenderEngine(hwaccel="auto")

# ---------------------------------------------------------------------------
# Template and persona registries (mirroring JS definitions)
# ---------------------------------------------------------------------------

TEMPLATES = {
    "comeback-king": {
        "id": "comeback-king", "name": "Comeback King",
        "description": "Highlights dramatic reversals — getting destroyed then clawing back to win.",
        "category": "Narrative", "mood": "triumphant",
        "durationRange": [45, 120],
        "enhancement_defaults": {"bgm": 80, "subtitles": 60, "effects": 75, "hook": 90, "transitions": 70},
    },
    "clutch-master": {
        "id": "clutch-master", "name": "Clutch Master",
        "description": "Showcases clutch moments — insane plays when everything is on the line.",
        "category": "FPS", "mood": "intense",
        "durationRange": [30, 90],
        "enhancement_defaults": {"bgm": 85, "subtitles": 50, "effects": 90, "hook": 95, "transitions": 60},
    },
    "rage-quit-montage": {
        "id": "rage-quit-montage", "name": "Rage Quit Montage",
        "description": "Captures tilts, fails, and rage moments — funny, chaotic, shareable.",
        "category": "Comedy", "mood": "chaotic",
        "durationRange": [30, 90],
        "enhancement_defaults": {"bgm": 70, "subtitles": 85, "effects": 95, "hook": 80, "transitions": 90},
    },
    "chill-highlights": {
        "id": "chill-highlights", "name": "Chill Highlights",
        "description": "Smooth, relaxed highlight reel — aesthetic vibes over hype.",
        "category": "Universal", "mood": "chill",
        "durationRange": [60, 180],
        "enhancement_defaults": {"bgm": 90, "subtitles": 40, "effects": 30, "hook": 45, "transitions": 85},
    },
    "kill-montage": {
        "id": "kill-montage", "name": "Kill Montage",
        "description": "Rapid-fire kill compilation — headshots, multi-kills, ace rounds.",
        "category": "FPS", "mood": "intense",
        "durationRange": [20, 60],
        "enhancement_defaults": {"bgm": 90, "subtitles": 20, "effects": 95, "hook": 85, "transitions": 50},
    },
    "session-story": {
        "id": "session-story", "name": "Session Story",
        "description": "Full session condensed into a narrative with chapters and emotional arc.",
        "category": "Narrative", "mood": "triumphant",
        "durationRange": [120, 300],
        "enhancement_defaults": {"bgm": 75, "subtitles": 70, "effects": 50, "hook": 60, "transitions": 80},
    },
    "tiktok-vertical": {
        "id": "tiktok-vertical", "name": "TikTok Vertical",
        "description": "Optimized for 9:16 vertical — fast hook, peak moment, reaction.",
        "category": "Short-Form", "mood": "intense",
        "durationRange": [15, 60],
        "enhancement_defaults": {"bgm": 85, "subtitles": 95, "effects": 80, "hook": 100, "transitions": 75},
    },
    "edu-breakdown": {
        "id": "edu-breakdown", "name": "Educational Breakdown",
        "description": "Annotated replay analysis — freeze frames, zoom callouts, step-by-step.",
        "category": "Educational", "mood": "chill",
        "durationRange": [60, 240],
        "enhancement_defaults": {"bgm": 40, "subtitles": 90, "effects": 60, "hook": 50, "transitions": 70},
    },
    "hype-montage": {
        "id": "hype-montage", "name": "Hype Montage",
        "description": "Music-synced highlight reel — beat drops align with kills.",
        "category": "Universal", "mood": "intense",
        "durationRange": [30, 90],
        "enhancement_defaults": {"bgm": 95, "subtitles": 30, "effects": 85, "hook": 90, "transitions": 80},
    },
    "squad-moments": {
        "id": "squad-moments", "name": "Squad Moments",
        "description": "Best group plays, comms highlights, and team chemistry moments.",
        "category": "Social", "mood": "triumphant",
        "durationRange": [45, 150],
        "enhancement_defaults": {"bgm": 65, "subtitles": 85, "effects": 55, "hook": 70, "transitions": 75},
    },
}

PERSONAS = {
    "hype-streamer": {
        "id": "hype-streamer", "name": "HypeAndy", "archetype": "The Hype Machine",
        "energy_level": 9, "humor_style": "loud",
        "preferred_template": "clutch-master", "edit_intensity": 8,
    },
    "chill-streamer": {
        "id": "chill-streamer", "name": "ZenVibes", "archetype": "The Zen Master",
        "energy_level": 3, "humor_style": "dry",
        "preferred_template": "chill-highlights", "edit_intensity": 3,
    },
    "chaos-gremlin": {
        "id": "chaos-gremlin", "name": "TiltLord", "archetype": "The Chaos Gremlin",
        "energy_level": 10, "humor_style": "chaotic",
        "preferred_template": "rage-quit-montage", "edit_intensity": 10,
    },
    "tactician": {
        "id": "tactician", "name": "SteadyAim", "archetype": "The Tactician",
        "energy_level": 5, "humor_style": "sarcastic",
        "preferred_template": "edu-breakdown", "edit_intensity": 5,
    },
    "squad-captain": {
        "id": "squad-captain", "name": "SquadLeader", "archetype": "The Squad Captain",
        "energy_level": 7, "humor_style": "wholesome",
        "preferred_template": "squad-moments", "edit_intensity": 6,
    },
}

# ---------------------------------------------------------------------------
# WebSocket progress broadcasting
# ---------------------------------------------------------------------------


async def _broadcast_progress(job_id: str, stage: str, progress: float, message: str) -> None:
    """Send progress update to all connected WebSocket clients."""
    payload = json.dumps({
        "type": "progress",
        "job_id": job_id,
        "stage": stage,
        "progress": round(progress, 4),
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    dead = set()
    for ws in _ws_connections:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)

    _ws_connections -= dead


def _sync_broadcast(job_id: str, stage: str, progress: float, message: str) -> None:
    """Synchronous wrapper for broadcasting progress from background threads."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_broadcast_progress(job_id, stage, progress, message))
        else:
            loop.run_until_complete(_broadcast_progress(job_id, stage, progress, message))
    except RuntimeError:
        pass  # No event loop available (pure background thread)


# ---------------------------------------------------------------------------
# Background task runners
# ---------------------------------------------------------------------------


def _create_job(job_type: str) -> Job:
    """Create and register a new job."""
    job_id = f"{job_type}_{uuid.uuid4().hex[:12]}"
    job = Job(job_id=job_id, job_type=job_type)
    _jobs[job_id] = job
    return job


def _complete_job(job: Job, result: Any = None, error: Optional[str] = None) -> None:
    """Mark a job as completed or failed."""
    if error:
        job.status = JobStatus.FAILED
        job.error = error
        job.message = f"Failed: {error}"
    else:
        job.status = JobStatus.COMPLETED
        job.result = result
        job.progress = 1.0
        job.message = "Complete"
    job.completed_at = datetime.now(timezone.utc).isoformat()


async def _run_ingest_job(job: Job, source: str, language: Optional[str]) -> None:
    """Background ingest job."""
    try:
        job.status = JobStatus.RUNNING
        job.message = "Starting ingest pipeline"

        # Run the synchronous ingest in a thread pool
        loop = asyncio.get_event_loop()
        result: IngestResult = await loop.run_in_executor(
            None, lambda: run_ingest(source, language=language)
        )

        _complete_job(job, result={
            "video_path": result.video_path,
            "audio_path": result.audio_path,
            "transcript_path": result.transcript_path,
            "frames_dir": result.frames_dir,
            "duration_sec": result.duration_sec,
            "fps": result.fps,
            "resolution": list(result.resolution),
            "transcript_segments": result.transcript_segments[:50],  # Cap for response size
            "metadata": result.metadata,
        })
        logger.info("Ingest job %s completed: %s", job.job_id, result.video_path)

    except Exception as e:
        logger.exception("Ingest job %s failed", job.job_id)
        _complete_job(job, error=str(e))


async def _run_render_job(job: Job, edit_script: EditScript) -> None:
    """Background render job."""
    try:
        job.status = JobStatus.RUNNING
        job.message = "Starting render"

        def progress_cb(stage: str, progress: float, message: str):
            job.progress = progress
            job.message = message
            _sync_broadcast(job.job_id, stage, progress, message)

        engine = RenderEngine(
            hwaccel="auto",
            progress_callback=progress_cb,
        )

        loop = asyncio.get_event_loop()
        output_path = await loop.run_in_executor(
            None, lambda: engine.render(edit_script)
        )

        _complete_job(job, result={
            "output_path": output_path,
            "file_size_bytes": os.path.getsize(output_path) if os.path.isfile(output_path) else 0,
        })
        logger.info("Render job %s completed: %s", job.job_id, output_path)

    except Exception as e:
        logger.exception("Render job %s failed", job.job_id)
        _complete_job(job, error=str(e))


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Kairo server starting up")
    logger.info("Workspace: %s", WORKSPACE)
    logger.info("Output dir: %s", WORKSPACE / "output")
    (WORKSPACE / "output").mkdir(exist_ok=True)
    yield
    logger.info("Kairo server shutting down")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Kairo",
    description="AI-powered video editing pipeline for gaming content creators",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Electron app uses file:// protocol
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_jobs": sum(1 for j in _jobs.values() if j.status == JobStatus.RUNNING),
    }


# ---------------------------------------------------------------------------
# Ingest endpoints
# ---------------------------------------------------------------------------


@app.post("/api/ingest")
async def start_ingest(
    background_tasks: BackgroundTasks,
    url: Optional[str] = Form(None),
    file_path: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    language: Optional[str] = Form(None),
):
    """
    Start video ingest pipeline. Accepts a URL, local file path, or file upload.
    Returns a job ID for progress tracking.
    """
    source = None

    if url:
        source = url
    elif file_path:
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=400, detail=f"File not found: {file_path}")
        source = file_path
    elif file:
        # Save uploaded file to temp location
        upload_dir = WORKSPACE / "output" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / f"upload_{uuid.uuid4().hex[:8]}_{file.filename}"
        with open(dest, "wb") as f_out:
            content = await file.read()
            f_out.write(content)
        source = str(dest)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'url', 'file_path', or upload a 'file'",
        )

    job = _create_job("ingest")
    background_tasks.add_task(_run_ingest_job, job, source, language)

    logger.info("Ingest job created: %s (source=%s)", job.job_id, source[:100])
    return {"job_id": job.job_id, "status": "pending", "source": source}


@app.get("/api/ingest/{job_id}")
async def get_ingest_status(job_id: str):
    """Check ingest job progress and result."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    if job.job_type != "ingest":
        raise HTTPException(status_code=400, detail=f"Job {job_id} is not an ingest job")
    return job.to_dict()


# ---------------------------------------------------------------------------
# Analysis endpoint
# ---------------------------------------------------------------------------


@app.post("/api/analyze")
async def analyze_video(
    background_tasks: BackgroundTasks,
    video_path: str = Form(...),
    template_id: Optional[str] = Form(None),
    persona_id: Optional[str] = Form(None),
    max_duration: Optional[int] = Form(None),
    streamer_id: Optional[str] = Form(None),
):
    """
    Run full analysis pipeline on an ingested video.

    Triggers caption + DVD analysis (when agents are available),
    highlight detection, template matching, and narrative building.
    Returns highlights and clip candidates.
    """
    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"Video file not found: {video_path}")

    job = _create_job("analyze")

    async def run_analysis():
        try:
            job.status = JobStatus.RUNNING
            job.message = "Running analysis pipeline"

            # Get streamer recommendations if available
            recommendations = None
            if streamer_id:
                try:
                    recommendations = _memory.recommend_template(
                        streamer_id,
                        {"video_path": video_path},
                    )
                except Exception as e:
                    logger.warning("Failed to get recommendations: %s", e)

            # Use recommended template if no explicit override
            effective_template = template_id
            if not effective_template and recommendations:
                effective_template = recommendations.template_id

            # Build analysis result
            # (In production, this would invoke caption_agent + dvd_agent)
            result = {
                "video_path": video_path,
                "template_id": effective_template or "chill-highlights",
                "persona_id": persona_id,
                "recommendations": asdict(recommendations) if recommendations else None,
                "status": "analysis_complete",
                "message": (
                    "Analysis pipeline ready. "
                    "Caption and DVD agents will process when available."
                ),
            }

            _complete_job(job, result=result)
            logger.info("Analysis job %s completed", job.job_id)

        except Exception as e:
            logger.exception("Analysis job %s failed", job.job_id)
            _complete_job(job, error=str(e))

    background_tasks.add_task(run_analysis)
    return {"job_id": job.job_id, "status": "pending"}


# ---------------------------------------------------------------------------
# Edit script generation
# ---------------------------------------------------------------------------


@app.post("/api/generate")
async def generate_edit_script(
    video_path: str = Form(...),
    template_id: str = Form("chill-highlights"),
    streamer_id: Optional[str] = Form(None),
    beats_json: Optional[str] = Form(None),
    enhancements_json: Optional[str] = Form(None),
):
    """
    Generate an EditScript for a specific video and template.

    If beats_json is provided, uses those beats directly.
    Otherwise generates beats based on template structure.
    (In production, the DNA agent would generate the full EditScript.)

    Returns the EditScript as JSON for preview/modification before render.
    """
    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"Video file not found: {video_path}")

    template = TEMPLATES.get(template_id)
    if not template:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown template: {template_id}. Available: {list(TEMPLATES.keys())}",
        )

    # Parse custom beats if provided
    beats = []
    if beats_json:
        try:
            raw_beats = json.loads(beats_json)
            for b in raw_beats:
                beats.append(EditBeat(**{
                    k: v for k, v in b.items()
                    if k in EditBeat.__dataclass_fields__
                }))
        except (json.JSONDecodeError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid beats_json: {e}")

    # Get enhancement recommendations
    enhancements = None
    if enhancements_json:
        try:
            enhancements = json.loads(enhancements_json)
        except json.JSONDecodeError:
            pass

    if not enhancements and streamer_id:
        enhancements = _memory.recommend_enhancements(streamer_id, template_id)

    if not enhancements:
        enhancements = template.get("enhancement_defaults", {})

    # Build output config
    output_config = {
        "resolution": "1920x1080",
        "fps": 60,
        "codec": "libx264",
        "audio_codec": "aac",
        "format": "mp4",
        "crf": "18",
    }

    # Construct EditScript
    edit_script = EditScript(
        source_video=video_path,
        beats=beats,
        bgm_config={
            "path": None,
            "mood": template.get("mood", "chill"),
            "fade_in": 2.0,
            "fade_out": 3.0,
            "volume": (enhancements.get("bgm", 70) / 100.0) * 0.5,
        },
        subtitle_segments=[],
        voiceover_script=None,
        output_config=output_config,
    )

    # Serialize for response
    script_dict = {
        "source_video": edit_script.source_video,
        "beats": [asdict(b) if hasattr(b, "__dataclass_fields__") else b for b in edit_script.beats],
        "bgm_config": edit_script.bgm_config,
        "subtitle_segments": edit_script.subtitle_segments,
        "voiceover_script": edit_script.voiceover_script,
        "output_config": edit_script.output_config,
        "template_id": template_id,
        "enhancements": enhancements,
        "total_output_duration": edit_script.total_output_duration,
    }

    return {"edit_script": script_dict}


# ---------------------------------------------------------------------------
# Render endpoints
# ---------------------------------------------------------------------------


@app.post("/api/render")
async def start_render(
    background_tasks: BackgroundTasks,
    edit_script_json: str = Form(...),
):
    """
    Render final video from an EditScript.

    Accepts the edit_script as a JSON string (from /api/generate or modified by UI).
    Returns a job ID for progress tracking via /api/render/{job_id} or WebSocket.
    """
    try:
        raw = json.loads(edit_script_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    # Reconstruct EditScript
    try:
        beats = []
        for b in raw.get("beats", []):
            beats.append(EditBeat(**{
                k: v for k, v in b.items()
                if k in EditBeat.__dataclass_fields__
            }))

        edit_script = EditScript(
            source_video=raw["source_video"],
            beats=beats,
            bgm_config=raw.get("bgm_config", {}),
            subtitle_segments=raw.get("subtitle_segments", []),
            voiceover_script=raw.get("voiceover_script"),
            output_config=raw.get("output_config", {}),
        )
    except (KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid edit_script structure: {e}")

    if not os.path.isfile(edit_script.source_video):
        raise HTTPException(status_code=400, detail=f"Source video not found: {edit_script.source_video}")

    job = _create_job("render")
    background_tasks.add_task(_run_render_job, job, edit_script)

    logger.info(
        "Render job created: %s (%d beats)",
        job.job_id, len(edit_script.beats),
    )
    return {"job_id": job.job_id, "status": "pending"}


@app.get("/api/render/{job_id}")
async def get_render_status(job_id: str):
    """Check render job progress and result."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    if job.job_type != "render":
        raise HTTPException(status_code=400, detail=f"Job {job_id} is not a render job")
    return job.to_dict()


@app.get("/api/render/{job_id}/download")
async def download_rendered_video(job_id: str):
    """Download the rendered video file."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"Job not yet completed (status: {job.status.value})")

    output_path = (job.result or {}).get("output_path")
    if not output_path or not os.path.isfile(output_path):
        raise HTTPException(status_code=404, detail="Rendered file not found")

    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=os.path.basename(output_path),
    )


# ---------------------------------------------------------------------------
# Generic download — works for any completed job with an output video
# ---------------------------------------------------------------------------


@app.get("/api/jobs/{job_id}/download")
async def download_job_output(job_id: str):
    """Download the output video from any completed job (pipeline or render)."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"Job not yet completed (status: {job.status.value})")

    result = job.result or {}
    # Try various result keys for the output path
    output_path = (
        result.get("output_video")
        or result.get("output_path")
        or result.get("video_path")
    )

    if not output_path or not os.path.isfile(output_path):
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=os.path.basename(output_path),
    )


# ---------------------------------------------------------------------------
# LLM-based highlight detection endpoint
# ---------------------------------------------------------------------------


@app.post("/api/highlights")
async def detect_highlights(
    transcript_json: str = Form(...),
    template_id: Optional[str] = Form(None),
    max_highlights: int = Form(5),
):
    """
    Use an LLM (Claude or OpenAI) to detect the best viral moments from
    a Whisper transcript. This is the AI-powered highlight detection that
    competitors like Opus Clip use.

    Sends the transcript to an LLM and asks it to identify the most
    engaging, emotional, or dramatic moments for short-form video clips.

    Returns a list of highlight segments with timestamps and reasoning.
    """
    try:
        segments = json.loads(transcript_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid transcript JSON: {e}")

    if not segments:
        return {"highlights": [], "message": "No transcript segments provided"}

    # Build a condensed transcript for the LLM
    transcript_text = ""
    for seg in segments[:500]:  # Cap to avoid token limits
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        text = seg.get("text", "").strip()
        if text:
            transcript_text += f"[{start:.1f}s - {end:.1f}s] {text}\n"

    if not transcript_text.strip():
        return {"highlights": [], "message": "Transcript is empty"}

    template_context = ""
    if template_id and template_id in TEMPLATES:
        tmpl = TEMPLATES[template_id]
        template_context = (
            f"\nTarget template: {tmpl['name']} - {tmpl['description']}\n"
            f"Target mood: {tmpl['mood']}, Duration: {tmpl['durationRange'][0]}-{tmpl['durationRange'][1]}s\n"
        )

    system_prompt = (
        "You are an expert viral video editor. Analyze this gaming/streaming "
        "transcript and identify the best moments for short-form clips "
        "(TikTok, YouTube Shorts, Reels).\n\n"
        "For each highlight, identify:\n"
        "1. Start and end timestamps (in seconds)\n"
        "2. Why this moment is engaging (emotion, action, humor, surprise)\n"
        "3. A suggested hook/title\n"
        "4. Virality score (1-10)\n\n"
        f"Find up to {max_highlights} highlights.{template_context}\n\n"
        "Return JSON array with format:\n"
        '[{"start": 0.0, "end": 30.0, "reason": "...", "hook": "...", "virality": 8}]'
    )

    highlights = []

    # Try Claude first, then OpenAI, then fall back to heuristic
    llm_used = "none"
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": f"Transcript:\n{transcript_text}"}],
            )
            raw = response.content[0].text
            # Extract JSON from response
            import re
            json_match = re.search(r'\[.*\]', raw, re.DOTALL)
            if json_match:
                highlights = json.loads(json_match.group())
                llm_used = "claude"
        except Exception as e:
            logger.warning("Claude highlight detection failed: %s", e)

    if not highlights and openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Transcript:\n{transcript_text}"},
                ],
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                highlights = parsed
            elif isinstance(parsed, dict) and "highlights" in parsed:
                highlights = parsed["highlights"]
            llm_used = "openai"
        except Exception as e:
            logger.warning("OpenAI highlight detection failed: %s", e)

    if not highlights:
        # Heuristic fallback: find segments with high energy words
        highlights = _heuristic_highlights(segments, max_highlights)
        llm_used = "heuristic"

    return {
        "highlights": highlights[:max_highlights],
        "llm_used": llm_used,
        "total_segments": len(segments),
    }


def _heuristic_highlights(segments: list, max_highlights: int) -> list:
    """Fallback: detect highlights based on speech energy keywords."""
    energy_words = {
        "oh", "omg", "no", "yes", "let's go", "clutch", "insane",
        "what", "kill", "headshot", "ace", "win", "lose", "gg",
        "holy", "dude", "bro", "sick", "crazy", "nice", "nooo",
        "come on", "how", "why", "haha", "lol", "rage", "tilt",
    }
    scored = []
    for seg in segments:
        text = (seg.get("text", "") or "").lower()
        words = text.split()
        energy = sum(1 for w in words if any(ew in w for ew in energy_words))
        word_count = max(len(words), 1)
        # More words in short time = more energy
        duration = max(seg.get("end", 0) - seg.get("start", 0), 0.1)
        density = word_count / duration
        score = energy * 2 + density * 0.5
        if score > 0:
            scored.append({
                "start": seg.get("start", 0),
                "end": min(seg.get("end", 0) + 15, seg.get("start", 0) + 30),
                "reason": f"High energy speech detected ({energy} trigger words)",
                "hook": text[:60].strip() + "..." if len(text) > 60 else text.strip(),
                "virality": min(10, int(score * 2)),
            })
    scored.sort(key=lambda x: x["virality"], reverse=True)
    return scored[:max_highlights]


# ---------------------------------------------------------------------------
# Feedback endpoint
# ---------------------------------------------------------------------------


@app.post("/api/feedback")
async def submit_feedback(
    streamer_id: str = Form(...),
    clip_id: str = Form(...),
    rating: int = Form(3),
    action: str = Form("approved"),
    modifications_json: Optional[str] = Form(None),
    notes: Optional[str] = Form(""),
    template_id: Optional[str] = Form(None),
    enhancements_json: Optional[str] = Form(None),
    video_analysis_json: Optional[str] = Form(None),
):
    """
    Submit feedback on a generated clip. This feeds the learning system.

    The streamer's profile is updated with the feedback, and future
    recommendations will reflect their preferences.
    """
    modifications = {}
    if modifications_json:
        try:
            modifications = json.loads(modifications_json)
        except json.JSONDecodeError:
            pass

    enhancements = {}
    if enhancements_json:
        try:
            enhancements = json.loads(enhancements_json)
        except json.JSONDecodeError:
            pass

    video_analysis = {}
    if video_analysis_json:
        try:
            video_analysis = json.loads(video_analysis_json)
        except json.JSONDecodeError:
            pass

    feedback = Feedback(
        rating=rating,
        action=action,
        modifications=modifications,
        notes=notes or "",
    )

    _memory.record_feedback(
        streamer_id=streamer_id,
        clip_id=clip_id,
        feedback=feedback,
        template_id=template_id or "",
        enhancements=enhancements,
        video_analysis=video_analysis,
    )

    logger.info(
        "Feedback recorded: streamer=%s, clip=%s, action=%s, rating=%d",
        streamer_id, clip_id, action, rating,
    )

    return {
        "status": "recorded",
        "streamer_id": streamer_id,
        "clip_id": clip_id,
        "action": action,
        "rating": rating,
    }


# ---------------------------------------------------------------------------
# Templates and personas
# ---------------------------------------------------------------------------


@app.get("/api/templates")
async def list_templates(category: Optional[str] = Query(None)):
    """List available editing templates, optionally filtered by category."""
    if category:
        filtered = {
            k: v for k, v in TEMPLATES.items()
            if v.get("category", "").lower() == category.lower()
        }
        return {"templates": list(filtered.values())}
    return {"templates": list(TEMPLATES.values())}


@app.get("/api/templates/{template_id}")
async def get_template(template_id: str):
    """Get a specific template by ID."""
    template = TEMPLATES.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")
    return template


@app.get("/api/personas")
async def list_personas():
    """List available streamer persona presets."""
    return {"personas": list(PERSONAS.values())}


@app.get("/api/personas/{persona_id}")
async def get_persona(persona_id: str):
    """Get a specific persona preset by ID."""
    persona = PERSONAS.get(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona not found: {persona_id}")
    return persona


# ---------------------------------------------------------------------------
# Memory / streamer profile endpoints
# ---------------------------------------------------------------------------


@app.get("/api/memory/{streamer_id}")
async def get_streamer_memory(streamer_id: str):
    """
    Get streamer profile, preferences, and recommendations.

    Returns the full profile with editing history, learned preferences,
    and template recommendations.
    """
    profile = _memory.load_profile(streamer_id)
    pref = _memory.learn_preferences(streamer_id)
    rec = _memory.recommend_template(streamer_id)
    enhancements = _memory.recommend_enhancements(streamer_id)
    similar = _memory.find_similar_streamers(streamer_id, top_k=3)

    return {
        "profile": {
            "streamer_id": profile.streamer_id,
            "name": profile.name,
            "platform": profile.platform,
            "games": profile.games,
            "history_count": len(profile.editing_history),
            "template_usage": profile.template_usage,
            "avg_enhancement_levels": profile.avg_enhancement_levels,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        },
        "preferences": asdict(pref),
        "recommendation": asdict(rec),
        "suggested_enhancements": enhancements,
        "similar_streamers": similar,
    }


@app.put("/api/memory/{streamer_id}")
async def update_streamer_profile(
    streamer_id: str,
    name: Optional[str] = Form(None),
    platform: Optional[str] = Form(None),
    games_json: Optional[str] = Form(None),
):
    """Update basic streamer profile information."""
    profile = _memory.load_profile(streamer_id)

    if name is not None:
        profile.name = name
    if platform is not None:
        profile.platform = platform
    if games_json is not None:
        try:
            profile.games = json.loads(games_json)
        except json.JSONDecodeError:
            pass

    _memory.save_profile(profile)
    return {"status": "updated", "streamer_id": streamer_id}


@app.get("/api/memory")
async def list_streamer_profiles():
    """List all stored streamer profile IDs."""
    profiles = _memory.list_profiles()
    return {"streamer_ids": profiles, "count": len(profiles)}


# ---------------------------------------------------------------------------
# One-click autonomous pipeline
# ---------------------------------------------------------------------------


@app.post("/api/pipeline")
async def run_full_pipeline(
    background_tasks: BackgroundTasks,
    url: Optional[str] = Form(None),
    file_path: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    streamer_id: Optional[str] = Form(None),
    template_id: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
):
    """
    One-click autonomous pipeline: URL/file → viral short video.

    This is the crown jewel of Kairo. Takes a single input (URL, file path,
    or file upload), runs the full intelligent pipeline
    (ingest → caption → DVD → DNA → render), evaluates quality,
    self-corrects, and returns the best clip.

    The pipeline generates top-3 clip candidates, scores them, and selects
    the highest quality one. It also records the result for future learning.
    """
    source = url or file_path

    # Handle file upload
    if not source and file:
        upload_dir = WORKSPACE / "output" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / f"upload_{uuid.uuid4().hex[:8]}_{file.filename}"
        with open(dest, "wb") as f_out:
            content = await file.read()
            f_out.write(content)
        source = str(dest)

    if not source:
        raise HTTPException(status_code=400, detail="Provide 'url', 'file_path', or upload a 'file'")

    job_id = str(uuid.uuid4())[:12]
    job = Job(job_id=job_id, job_type="pipeline")
    _jobs[job_id] = job

    def _run_pipeline():
        try:
            job.status = JobStatus.RUNNING
            job.message = "Starting autonomous pipeline"
            _sync_broadcast(job_id, "pipeline", 0.0, job.message)

            from core.pipeline import KairoPipeline

            def progress_cb(stage, progress, message):
                job.progress = progress
                job.message = message
                _sync_broadcast(job_id, stage, progress, message)

            pipeline = KairoPipeline(
                streamer_id=streamer_id or "default",
                progress_callback=progress_cb,
            )

            result = pipeline.run(source, language=language)

            job.status = JobStatus.COMPLETED
            job.progress = 1.0
            job.message = "Pipeline complete"
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.result = {
                "output_video": result.output_video,
                "output_path": result.output_video,  # alias for generic download
                "quality_score": result.quality_score,
                "report": result.report,
                "candidates": [
                    {
                        "rank": c.rank if hasattr(c, "rank") else i + 1,
                        "quality_score": c.quality_report.overall_score
                        if hasattr(c, "quality_report") and c.quality_report
                        else 0,
                        "output_path": c.output_video
                        if hasattr(c, "output_video")
                        else None,
                    }
                    for i, c in enumerate(
                        result.candidates if hasattr(result, "candidates") else []
                    )
                ],
                "total_time_sec": result.total_time_sec
                if hasattr(result, "total_time_sec") else 0,
            }
            _sync_broadcast(job_id, "complete", 1.0, "Pipeline complete")

        except Exception as e:
            logger.exception("Pipeline failed: %s", e)
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc).isoformat()
            _sync_broadcast(job_id, "error", 0.0, str(e))

    background_tasks.add_task(_run_pipeline)

    logger.info(
        "Pipeline started: job=%s, source=%s, streamer=%s",
        job_id,
        source[:80],
        streamer_id or "default",
    )

    return {"job_id": job_id, "status": "started", "source": source}


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------


@app.get("/api/jobs")
async def list_jobs(
    status: Optional[str] = Query(None),
    job_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List all jobs, optionally filtered by status or type."""
    jobs = list(_jobs.values())

    if status:
        jobs = [j for j in jobs if j.status.value == status]
    if job_type:
        jobs = [j for j in jobs if j.job_type == job_type]

    # Sort by creation time descending
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    jobs = jobs[:limit]

    return {"jobs": [j.to_dict() for j in jobs]}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get status of any job by ID."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job.to_dict()


# ---------------------------------------------------------------------------
# WebSocket for real-time progress
# ---------------------------------------------------------------------------


@app.websocket("/ws/progress")
async def websocket_progress(websocket: WebSocket):
    """
    WebSocket endpoint for real-time progress updates.

    Clients receive JSON messages with structure:
    {
        "type": "progress",
        "job_id": "...",
        "stage": "segments|concat|audio|subtitles|done",
        "progress": 0.0-1.0,
        "message": "Human-readable status",
        "timestamp": "ISO 8601"
    }
    """
    await websocket.accept()
    _ws_connections.add(websocket)
    logger.info("WebSocket client connected (total: %d)", len(_ws_connections))

    try:
        # Send initial state of all running jobs
        running = [j for j in _jobs.values() if j.status == JobStatus.RUNNING]
        for job in running:
            await websocket.send_text(json.dumps({
                "type": "progress",
                "job_id": job.job_id,
                "stage": "running",
                "progress": job.progress,
                "message": job.message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))

        # Keep connection alive, listen for client messages
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Handle client pings
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_text(json.dumps({"type": "keepalive"}))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
    finally:
        _ws_connections.discard(websocket)
        logger.info("WebSocket client disconnected (total: %d)", len(_ws_connections))


# ---------------------------------------------------------------------------
# Web UI — serve static files from /web directory
# ---------------------------------------------------------------------------

WEB_DIR = WORKSPACE / "web"

if WEB_DIR.is_dir():
    @app.get("/")
    async def serve_index():
        """Serve the web UI index page."""
        index_path = WEB_DIR / "index.html"
        if index_path.is_file():
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>Kairo</h1><p>Web UI not found.</p>", status_code=404)

    # Mount static files (CSS, JS, images) — must come after all API routes
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web-static")

    logger.info("Web UI mounted from %s", WEB_DIR)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("KAIRO_PORT", "8420"))
    host = os.environ.get("KAIRO_HOST", "0.0.0.0")

    logger.info("Starting Kairo server on %s:%d", host, port)
    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )
