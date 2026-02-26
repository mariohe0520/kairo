"""
Kairo Core — Video processing, rendering, and autonomous pipeline.

Modules:
    ingest: Downloads video, extracts audio, runs Whisper ASR, samples frames.
    render: FFmpeg-based intelligent render engine with effects and transitions.
    pipeline: Autonomous end-to-end pipeline controller (the brain).
    meta_template: Reusable editing pattern extraction and matching.
"""

from core.ingest import (
    IngestResult,
    compute_audio_energy,
    download_video,
    extract_audio,
    get_video_info,
    ingest,
    sample_frames,
    transcribe_audio,
)
from core.render import (
    EditBeat,
    EditScript,
    RenderEngine,
    SubtitleSegment,
)
from core.pipeline import (
    KairoPipeline,
    PipelineResult,
    QualityReport,
    CandidateResult,
    run_pipeline,
)
from core.meta_template import (
    MetaTemplateEngine,
    MetaTemplate,
    get_default_template,
)

__all__ = [
    # ingest
    "IngestResult",
    "ingest",
    "download_video",
    "extract_audio",
    "transcribe_audio",
    "sample_frames",
    "get_video_info",
    "compute_audio_energy",
    # render
    "EditBeat",
    "EditScript",
    "SubtitleSegment",
    "RenderEngine",
    # pipeline
    "KairoPipeline",
    "PipelineResult",
    "QualityReport",
    "CandidateResult",
    "run_pipeline",
    # meta_template
    "MetaTemplateEngine",
    "MetaTemplate",
    "get_default_template",
]
