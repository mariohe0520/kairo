"""
Kairo Pipeline Controller -- The Brain.

This is the autonomous end-to-end pipeline that transforms a single URL or
file path into a finished, quality-checked viral short video.  It is what
makes Kairo an *intelligent agent* rather than a collection of tools.

Pipeline stages:
    1. **Ingest**       -- download, extract audio, ASR, frame sampling
    2. **Caption**      -- multi-modal frame understanding (VLM + heuristics)
    3. **Discover**     -- triangulation-scored clip candidate ranking
    4. **Architect**    -- narrative edit script generation per candidate
    5. **Render**       -- FFmpeg-based video assembly
    6. **Evaluate**     -- quality scoring with 5 criteria
    7. **Self-correct** -- parameter adjustment & re-generation loop (max 3)

The controller orchestrates all six agents and modules, manages streamer
memory for personalization, supports meta-template matching, and emits
structured progress events for WebSocket forwarding.

Usage::

    pipeline = KairoPipeline()
    result = pipeline.run("https://www.bilibili.com/video/BV1xxx")
    print(result.output_video)   # /path/to/rendered.mp4
    print(result.quality_score)  # 0-100
    print(result.report)         # human-readable quality report card
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("kairo.pipeline")

WORKSPACE = Path(__file__).parent.parent
OUTPUT_DIR = WORKSPACE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Import pipeline components
# ---------------------------------------------------------------------------

from core.ingest import IngestResult, ingest                          # noqa: E402
from agents.caption_agent import (                                    # noqa: E402
    CaptionAgent,
    CaptionTimeline,
    SegmentAnnotation,
)
from agents.dvd_agent import DVDAgent, ClipCandidate, WindowScore     # noqa: E402
from agents.dna_agent import (                                        # noqa: E402
    DNAAgent,
    EditScript as DNAEditScript,
    EditBeat as DNAEditBeat,
    BGMDirective,
)
from core.render import (                                             # noqa: E402
    RenderEngine,
    EditScript as RenderEditScript,
    EditBeat as RenderEditBeat,
    SubtitleSegment,
)
from core.meta_template import (                                      # noqa: E402
    MetaTemplateEngine,
    MetaTemplate,
    get_default_template,
)
from memory.streamer_memory import (                                  # noqa: E402
    StreamerMemory,
    StreamerProfile,
    TemplateRecommendation,
)


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[str, float, str], None]
"""Signature: callback(stage: str, progress: float 0-1, message: str)"""


def _null_progress(stage: str, progress: float, message: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QualityReport:
    """Quality evaluation of a generated edit script / rendered video."""

    # The five quality criteria (each 0-100)
    information_density: float = 0.0
    pacing_variation: float = 0.0
    hook_strength: float = 0.0
    duration_fitness: float = 0.0
    anti_fluff_score: float = 0.0

    # Composite
    overall_score: float = 0.0

    # Pass/fail for each criterion
    passes_density: bool = False
    passes_pacing: bool = False
    passes_hook: bool = False
    passes_duration: bool = False
    passes_anti_fluff: bool = False

    # Diagnostics
    details: dict = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True if the edit passes all five quality gates."""
        return (
            self.passes_density
            and self.passes_pacing
            and self.passes_hook
            and self.passes_duration
            and self.passes_anti_fluff
        )

    @property
    def failures(self) -> list[str]:
        """List of failed criterion names."""
        fails = []
        if not self.passes_density:
            fails.append("information_density")
        if not self.passes_pacing:
            fails.append("pacing_variation")
        if not self.passes_hook:
            fails.append("hook_strength")
        if not self.passes_duration:
            fails.append("duration_fitness")
        if not self.passes_anti_fluff:
            fails.append("anti_fluff")
        return fails

    def to_report_card(self) -> str:
        """Generate a human-readable quality report card."""
        def _bar(score: float, passed: bool) -> str:
            blocks = int(score / 10)
            bar = "+" * blocks + "-" * (10 - blocks)
            status = "PASS" if passed else "FAIL"
            return f"[{bar}] {score:5.1f}/100 {status}"

        lines = [
            "=" * 60,
            "  KAIRO QUALITY REPORT CARD",
            "=" * 60,
            "",
            f"  Overall Score:        {self.overall_score:.1f} / 100",
            f"  Status:               {'APPROVED' if self.passed else 'NEEDS IMPROVEMENT'}",
            "",
            f"  Information Density:  {_bar(self.information_density, self.passes_density)}",
            f"  Pacing Variation:     {_bar(self.pacing_variation, self.passes_pacing)}",
            f"  Hook Strength:        {_bar(self.hook_strength, self.passes_hook)}",
            f"  Duration Fitness:     {_bar(self.duration_fitness, self.passes_duration)}",
            f"  Anti-Fluff:           {_bar(self.anti_fluff_score, self.passes_anti_fluff)}",
            "",
        ]

        if self.suggestions:
            lines.append("  Suggestions:")
            for s in self.suggestions:
                lines.append(f"    - {s}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)


@dataclass
class CandidateResult:
    """Result from processing a single clip candidate."""
    rank: int
    candidate: ClipCandidate
    edit_script: DNAEditScript
    quality_report: QualityReport
    output_video: Optional[str] = None
    render_time_sec: float = 0.0


@dataclass
class PipelineResult:
    """Final output of the autonomous pipeline."""

    # Primary outputs
    output_video: str = ""            # path to best rendered video
    quality_score: float = 0.0        # 0-100 composite quality score
    report: str = ""                  # human-readable quality report

    # All generated candidates
    candidates: list[CandidateResult] = field(default_factory=list)
    best_candidate_rank: int = 0

    # Metadata
    source: str = ""
    streamer_id: str = ""
    template_used: str = ""
    persona_used: str = ""
    iterations: int = 0               # how many quality loop iterations
    total_time_sec: float = 0.0
    ingest_result: Optional[IngestResult] = None
    caption_timeline: Optional[CaptionTimeline] = None

    # Quality reports for all rendered candidates
    quality_reports: list[QualityReport] = field(default_factory=list)

    def summary(self) -> str:
        """Short summary of the pipeline result."""
        return (
            f"Kairo Pipeline Result\n"
            f"  Source: {self.source}\n"
            f"  Output: {self.output_video}\n"
            f"  Quality: {self.quality_score:.1f}/100\n"
            f"  Candidates evaluated: {len(self.candidates)}\n"
            f"  Quality iterations: {self.iterations}\n"
            f"  Total time: {self.total_time_sec:.1f}s\n"
            f"  Template: {self.template_used}\n"
        )


# ---------------------------------------------------------------------------
# Template & persona defaults (mirroring server.py TEMPLATES)
# ---------------------------------------------------------------------------

_TEMPLATE_REGISTRY: dict[str, dict] = {
    "comeback-king": {
        "id": "comeback-king", "mood": "triumphant",
        "durationRange": [45, 120],
        "structure": {"intro": 0.10, "build": 0.35, "climax": 0.35, "outro": 0.20},
        "transition_style": "crossfade", "musicMood": "triumphant",
        "bgm_style": "orchestral-epic",
    },
    "clutch-master": {
        "id": "clutch-master", "mood": "intense",
        "durationRange": [30, 90],
        "structure": {"intro": 0.08, "build": 0.30, "climax": 0.45, "outro": 0.17},
        "transition_style": "glitch-whip", "musicMood": "intense",
        "bgm_style": "electronic-hype",
    },
    "rage-quit-montage": {
        "id": "rage-quit-montage", "mood": "chaotic",
        "durationRange": [30, 90],
        "structure": {"intro": 0.12, "build": 0.25, "climax": 0.45, "outro": 0.18},
        "transition_style": "glitch-whip", "musicMood": "chaotic",
        "bgm_style": "meme-edm",
    },
    "chill-highlights": {
        "id": "chill-highlights", "mood": "chill",
        "durationRange": [60, 180],
        "structure": {"intro": 0.06, "build": 0.35, "climax": 0.30, "outro": 0.29},
        "transition_style": "crossfade", "musicMood": "chill",
        "bgm_style": "lofi-ambient",
    },
    "kill-montage": {
        "id": "kill-montage", "mood": "intense",
        "durationRange": [20, 60],
        "structure": {"intro": 0.10, "build": 0.20, "climax": 0.55, "outro": 0.15},
        "transition_style": "dramatic-cut", "musicMood": "intense",
        "bgm_style": "electronic-hype",
    },
    "session-story": {
        "id": "session-story", "mood": "triumphant",
        "durationRange": [120, 300],
        "structure": {"intro": 0.08, "build": 0.40, "climax": 0.30, "outro": 0.22},
        "transition_style": "crossfade", "musicMood": "triumphant",
        "bgm_style": "orchestral-epic",
    },
    "tiktok-vertical": {
        "id": "tiktok-vertical", "mood": "intense",
        "durationRange": [15, 60],
        "structure": {"intro": 0.15, "build": 0.20, "climax": 0.50, "outro": 0.15},
        "transition_style": "glitch-whip", "musicMood": "intense",
        "bgm_style": "electronic-hype",
    },
    "hype-montage": {
        "id": "hype-montage", "mood": "intense",
        "durationRange": [30, 90],
        "structure": {"intro": 0.10, "build": 0.25, "climax": 0.50, "outro": 0.15},
        "transition_style": "dramatic-cut", "musicMood": "intense",
        "bgm_style": "electronic-hype",
    },
}

_MOOD_FROM_CONTENT: dict[str, str] = {
    "excitement": "intense",
    "frustration": "chaotic",
    "surprise": "intense",
    "calm": "chill",
    "neutral": "chill",
}

_PERSONA_REGISTRY: dict[str, dict[str, Any]] = {
    "hype-streamer": {
        "id": "hype-streamer",
        "name": "HypeAndy",
        "energy_level": 9,
        "humor_style": "loud",
        "catchphrases": ["lock in", "this is free", "send him home"],
        "style_prefs": {"effects": 85, "hook": 90, "transitions": 75, "subtitles": 55, "bgm": 85},
    },
    "chill-streamer": {
        "id": "chill-streamer",
        "name": "ZenVibes",
        "energy_level": 3,
        "humor_style": "dry",
        "catchphrases": ["clean", "nice and easy", "we take those"],
        "style_prefs": {"effects": 35, "hook": 55, "transitions": 70, "subtitles": 60, "bgm": 70},
    },
    "chaos-gremlin": {
        "id": "chaos-gremlin",
        "name": "TiltLord",
        "energy_level": 10,
        "humor_style": "chaotic",
        "catchphrases": ["nahhh", "that is criminal", "what is this lobby"],
        "style_prefs": {"effects": 95, "hook": 85, "transitions": 90, "subtitles": 80, "bgm": 80},
    },
    "tactician": {
        "id": "tactician",
        "name": "SteadyAim",
        "energy_level": 5,
        "humor_style": "sarcastic",
        "catchphrases": ["read that", "angle won", "macro diff"],
        "style_prefs": {"effects": 50, "hook": 70, "transitions": 65, "subtitles": 85, "bgm": 45},
    },
    "squad-captain": {
        "id": "squad-captain",
        "name": "SquadLeader",
        "energy_level": 7,
        "humor_style": "wholesome",
        "catchphrases": ["good comms", "play together", "team diff"],
        "style_prefs": {"effects": 60, "hook": 72, "transitions": 70, "subtitles": 85, "bgm": 65},
    },
}

_INTENT_TEMPLATE_KEYWORDS: list[tuple[str, str]] = [
    ("teaching", "edu-breakdown"),
    ("tutorial", "edu-breakdown"),
    ("analysis", "edu-breakdown"),
    ("讲解", "edu-breakdown"),
    ("教学", "edu-breakdown"),
    ("clutch", "clutch-master"),
    ("ace", "kill-montage"),
    ("headshot", "kill-montage"),
    ("highlights", "kill-montage"),
    ("击杀", "kill-montage"),
    ("反杀", "comeback-king"),
    ("comeback", "comeback-king"),
    ("逆风翻盘", "comeback-king"),
    ("rage", "rage-quit-montage"),
    ("funny", "rage-quit-montage"),
    ("搞笑", "rage-quit-montage"),
    ("meme", "rage-quit-montage"),
    ("story", "session-story"),
    ("剧情", "session-story"),
    ("squad", "squad-moments"),
    ("duo", "squad-moments"),
    ("组队", "squad-moments"),
    ("douyin", "tiktok-vertical"),
    ("tiktok", "tiktok-vertical"),
    ("shorts", "tiktok-vertical"),
    ("reels", "tiktok-vertical"),
    ("抖音", "tiktok-vertical"),
    ("短视频", "tiktok-vertical"),
]


# ---------------------------------------------------------------------------
# Quality thresholds
# ---------------------------------------------------------------------------

# Information density: seconds with content events / total duration
_DENSITY_THRESHOLD = 0.7
# Pacing variation: std dev of beat intensities
_PACING_STD_THRESHOLD = 15.0
# Hook strength: first 3 seconds composite score
_HOOK_SCORE_THRESHOLD = 70.0
# Anti-fluff: max removal rate
_ANTI_FLUFF_MAX_REMOVAL = 0.20
# Max quality loop iterations
_MAX_QUALITY_ITERATIONS = 3
# Number of candidates to generate and compare
_NUM_CANDIDATES = 3


# ---------------------------------------------------------------------------
# KairoPipeline
# ---------------------------------------------------------------------------

class KairoPipeline:
    """
    Autonomous end-to-end pipeline: URL -> viral short video.

    This is the brain of Kairo.  It orchestrates all agents, applies
    streamer-specific personalization, evaluates quality, and self-corrects
    when the output doesn't meet standards.

    Usage::

        pipeline = KairoPipeline()
        result = pipeline.run("https://www.bilibili.com/video/BV1xxx")
        print(result.output_video)    # path to rendered video
        print(result.quality_score)   # 0-100
        print(result.report)          # human-readable quality report

    Parameters
    ----------
    streamer_id : str, optional
        Streamer identifier for personalized editing.  If provided, the
        pipeline loads their preference profile and uses learned templates.
    config : dict, optional
        Override defaults.  Recognised keys:
        ``template_id``, ``persona_id``, ``language``, ``num_candidates``,
        ``max_iterations``, ``render_all``, ``output_dir``.
    progress_callback : callable, optional
        ``callback(stage, progress, message)`` for real-time progress.
    """

    def __init__(
        self,
        streamer_id: Optional[str] = None,
        config: Optional[dict] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        self.streamer_id = streamer_id or ""
        self.config = config or {}
        self._progress = progress_callback or _null_progress

        # Sub-components (lazily configured per-run)
        self._memory = StreamerMemory()
        self._caption_agent = CaptionAgent()
        self._dvd_agent = DVDAgent(top_n=self.config.get("num_candidates", _NUM_CANDIDATES))
        self._dna_agent = DNAAgent()
        self._render_engine = RenderEngine(
            hwaccel="auto",
            progress_callback=self._render_progress_adapter,
        )
        self._meta_engine = MetaTemplateEngine()

        # Runtime state
        self._current_stage = ""
        self._stage_base_progress = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        source: str,
        language: Optional[str] = None,
    ) -> PipelineResult:
        """
        Full autonomous pipeline: URL/path -> rendered viral short video.

        Parameters
        ----------
        source : str
            Video URL (Bilibili, YouTube, Twitch, etc.) or local file path.
        language : str, optional
            Language hint for ASR transcription.

        Returns
        -------
        PipelineResult
            Contains the output video path, quality score, report card,
            and metadata for all evaluated candidates.
        """
        t_start = time.time()
        language = language or self.config.get("language")
        num_candidates = self.config.get("num_candidates", _NUM_CANDIDATES)
        max_iterations = self.config.get("max_iterations", _MAX_QUALITY_ITERATIONS)
        render_all = self.config.get("render_all", True)
        output_dir = self.config.get("output_dir", str(OUTPUT_DIR))

        result = PipelineResult(source=source, streamer_id=self.streamer_id)
        ingest_result = None  # 提前声明，供 finally 块清理帧文件

        logger.info(
            "Pipeline starting: source=%s, streamer=%s, candidates=%d",
            source[:100], self.streamer_id or "(anonymous)", num_candidates,
        )

        try:
            # ---- Stage 1: Ingest ----
            self._emit_progress("ingest", 0.0, "Starting ingest pipeline")
            ingest_result = self._run_ingest(source, language)
            result.ingest_result = ingest_result
            self._emit_progress("ingest", 1.0, f"Ingest complete: {ingest_result.duration_sec:.0f}s video")

            # ---- Stage 2: Caption (frame understanding) ----
            self._emit_progress("caption", 0.0, "Analyzing video frames")
            caption_timeline = self._run_caption(ingest_result)
            result.caption_timeline = caption_timeline
            self._emit_progress("caption", 1.0, f"Caption complete: {len(caption_timeline.annotations)} annotations")

            # ---- Stage 3: Template & persona selection ----
            self._emit_progress("template", 0.0, "Selecting template and persona")
            template = self._select_template(caption_timeline, self.streamer_id)
            persona = self._build_persona(self.streamer_id, caption_timeline)
            result.template_used = template.get("id", template.get("mood", "auto"))
            result.persona_used = persona.get("name", "auto")
            self._emit_progress("template", 1.0, f"Template: {result.template_used}, Persona: {result.persona_used}")

            # ---- Stage 4: Discover clip candidates ----
            self._emit_progress("discover", 0.0, "Discovering viral clip candidates")
            dvd_config = self._build_dvd_config(template)
            candidates = self._dvd_agent.discover(caption_timeline, config=dvd_config)

            if not candidates:
                logger.warning("No clip candidates found -- using full video as fallback")
                candidates = self._fallback_candidate(caption_timeline)

            # Take top-N
            candidates = candidates[:num_candidates]
            self._emit_progress(
                "discover", 1.0,
                f"Found {len(candidates)} candidates (best: {candidates[0].composite_score:.3f})"
            )

            # ---- Stage 5: Architect + Render + Quality loop ----
            self._emit_progress("architect", 0.0, "Generating edit scripts and rendering")
            candidate_results = self._process_candidates(
                candidates, caption_timeline, template, persona,
                ingest_result, max_iterations, render_all, output_dir,
            )
            result.candidates = candidate_results

            # ---- Stage 6: Select best ----
            self._emit_progress("select", 0.0, "Selecting best output")
            best = self._select_best_candidate(candidate_results)

            if best:
                result.output_video = best.output_video or ""
                result.quality_score = best.quality_report.overall_score
                result.report = best.quality_report.to_report_card()
                result.best_candidate_rank = best.rank
                result.quality_reports = [cr.quality_report for cr in candidate_results]
                result.iterations = max(
                    1, max(
                        (getattr(cr, "_iterations", 1) for cr in candidate_results),
                        default=1,
                    )
                )
            else:
                result.report = "No candidates could be processed."
                logger.error("Pipeline produced no viable output")

            self._emit_progress("select", 1.0, f"Best candidate: rank {result.best_candidate_rank}, score {result.quality_score:.1f}")

        except Exception as e:
            logger.exception("Pipeline failed: %s", e)
            result.report = f"Pipeline error: {e}"
            self._emit_progress("error", 0.0, f"Pipeline failed: {e}")

        finally:
            # 自动清理帧文件（1小时视频约 500MB，默认开启）
            _auto_cleanup = os.environ.get("KAIRO_CLEANUP_FRAMES", "1") != "0"
            if _auto_cleanup and ingest_result and getattr(ingest_result, "frames_dir", None):
                _frames = Path(ingest_result.frames_dir)
                if _frames.exists():
                    shutil.rmtree(_frames, ignore_errors=True)
                    logger.info("已清理帧目录: %s", _frames)

        result.total_time_sec = time.time() - t_start
        self._emit_progress(
            "done", 1.0,
            f"Pipeline complete in {result.total_time_sec:.1f}s -- score: {result.quality_score:.1f}/100"
        )

        logger.info(
            "Pipeline complete: score=%.1f, output=%s, time=%.1fs",
            result.quality_score, result.output_video, result.total_time_sec,
        )
        return result

    # ------------------------------------------------------------------
    # Stage runners
    # ------------------------------------------------------------------

    def _run_ingest(self, source: str, language: Optional[str]) -> IngestResult:
        """Run the ingest pipeline (download + audio + ASR + frames)."""
        logger.info("Ingest: processing %s", source[:100])
        return ingest(source, language=language)

    def _run_caption(self, ingest_result: IngestResult) -> CaptionTimeline:
        """Run the caption agent for multi-modal frame understanding."""
        logger.info("Caption: analyzing %d frames", len(
            list(Path(ingest_result.frames_dir).glob("frame_*")) if ingest_result.frames_dir else []
        ))
        return self._caption_agent.analyze(ingest_result)

    # ------------------------------------------------------------------
    # Template & persona selection
    # ------------------------------------------------------------------

    def _select_template(
        self,
        caption_timeline: CaptionTimeline,
        streamer_id: str,
    ) -> dict:
        """
        Auto-select the best template based on content + streamer preferences.

        Decision tree:
        1. If config explicitly specifies a template_id, use that.
        2. If streamer has a profile with learned preferences, use memory recommendation.
        3. If learned meta-templates exist, match against content.
        4. Otherwise, analyze content mood and pick the best built-in template.
        """
        # 1. Explicit override
        explicit_id = self.config.get("template_id")
        if explicit_id and explicit_id in _TEMPLATE_REGISTRY:
            logger.info("Using explicitly requested template: %s", explicit_id)
            return dict(_TEMPLATE_REGISTRY[explicit_id])

        # 1.5 Intent-aware selection from creator brief / target platform
        intent_template = self._template_from_intent()
        if intent_template and intent_template in _TEMPLATE_REGISTRY:
            logger.info("Using intent-selected template: %s", intent_template)
            return dict(_TEMPLATE_REGISTRY[intent_template])

        # 2. Streamer memory recommendation
        if streamer_id:
            profile = self._memory.load_profile(streamer_id)
            if profile.editing_history:
                rec = self._memory.recommend_template(
                    streamer_id,
                    video_analysis=self._build_video_analysis(caption_timeline),
                )
                if rec.confidence >= 0.4 and rec.template_id in _TEMPLATE_REGISTRY:
                    logger.info(
                        "Memory-recommended template: %s (confidence=%.2f, reason=%s)",
                        rec.template_id, rec.confidence, rec.reason,
                    )
                    template = dict(_TEMPLATE_REGISTRY[rec.template_id])
                    # Apply learned enhancement levels
                    enhancements = self._memory.recommend_enhancements(
                        streamer_id, rec.template_id,
                    )
                    template["_learned_enhancements"] = enhancements
                    return template

        # 3. Meta-template matching
        meta_templates = self._meta_engine.list_templates()
        if meta_templates:
            best_meta = self._meta_engine.match_template(caption_timeline, meta_templates)
            if best_meta:
                adapted = self._meta_engine.adapt_template(
                    best_meta, caption_timeline,
                )
                logger.info(
                    "Using meta-template: %s (%s)",
                    best_meta.template_id, best_meta.name,
                )
                return adapted

        # 4. Content-based auto-selection
        return self._auto_select_from_content(caption_timeline)

    def _auto_select_from_content(self, caption_timeline: CaptionTimeline) -> dict:
        """Analyze content to auto-select the best built-in template."""
        annotations = caption_timeline.annotations
        if not annotations:
            logger.info("No annotations -- defaulting to chill-highlights")
            return dict(_TEMPLATE_REGISTRY["chill-highlights"])

        # Analyze dominant mood
        emotion_counts: dict[str, int] = {}
        for a in annotations:
            emotion_counts[a.dominant_emotion] = emotion_counts.get(
                a.dominant_emotion, 0
            ) + 1
        dominant_emotion = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral"
        mood = _MOOD_FROM_CONTENT.get(dominant_emotion, "intense")

        # Analyze content intensity
        composites = [a.composite_score for a in annotations]
        mean_intensity = statistics.mean(composites) if composites else 0.0
        has_game_events = any(a.has_game_event for a in annotations)
        game_event_density = sum(1 for a in annotations if a.has_game_event) / max(len(annotations), 1)

        # Analyze variance (for narrative potential)
        intensity_std = statistics.stdev(composites) if len(composites) > 1 else 0.0

        # Decision logic
        if mood == "chaotic" and mean_intensity > 0.3:
            template_id = "rage-quit-montage"
        elif has_game_events and game_event_density > 0.15 and mood == "intense":
            # Lots of kills/events -> kill montage
            if caption_timeline.duration_sec < 1200:
                template_id = "kill-montage"
            else:
                template_id = "hype-montage"
        elif intensity_std > 0.15 and mood in ("intense", "triumphant"):
            # High variance suggests a comeback or clutch narrative
            template_id = "comeback-king" if mood == "triumphant" else "clutch-master"
        elif caption_timeline.duration_sec > 3600 and mood == "triumphant":
            template_id = "session-story"
        elif mood == "chill":
            template_id = "chill-highlights"
        elif mean_intensity > 0.4:
            template_id = "hype-montage"
        else:
            template_id = "chill-highlights"

        logger.info(
            "Auto-selected template: %s (mood=%s, intensity=%.2f, game_events=%.1f%%)",
            template_id, mood, mean_intensity, game_event_density * 100,
        )
        return dict(_TEMPLATE_REGISTRY[template_id])

    def _build_persona(
        self,
        streamer_id: str,
        caption_timeline: CaptionTimeline,
    ) -> dict:
        """
        Build or load a persona dict for the streamer.

        If a streamer profile exists with preferences, builds a persona from
        those.  Otherwise, infers a persona from content characteristics.
        """
        # Explicit override
        explicit_persona = self.config.get("persona_id")
        if explicit_persona:
            base = dict(_PERSONA_REGISTRY.get(
                explicit_persona,
                {"id": explicit_persona, "name": explicit_persona, "energy_level": 6, "humor_style": "neutral", "catchphrases": []},
            ))
            return self._augment_persona_with_creator_brief(base)

        # Legacy mode: streamer_id may be a preset persona id.
        if streamer_id in _PERSONA_REGISTRY:
            return self._augment_persona_with_creator_brief(dict(_PERSONA_REGISTRY[streamer_id]))

        # Load from memory
        if streamer_id:
            profile = self._memory.load_profile(streamer_id)
            if profile.name or profile.editing_history:
                pref = self._memory.learn_preferences(streamer_id)
                return self._augment_persona_with_creator_brief({
                    "name": profile.name or streamer_id,
                    "energy_level": self._energy_from_mood(pref.mood_preference),
                    "humor_style": "neutral",
                    "catchphrases": [],
                    "style_prefs": dict(pref.enhancement_levels),
                })

        # Infer from content
        return self._augment_persona_with_creator_brief(
            self._infer_persona_from_content(caption_timeline)
        )

    def _infer_persona_from_content(self, caption_timeline: CaptionTimeline) -> dict:
        """Infer a persona from video content characteristics."""
        annotations = caption_timeline.annotations
        if not annotations:
            return {"name": "auto", "energy_level": 5, "humor_style": "neutral", "catchphrases": []}

        # Estimate energy from average emotion intensity
        emotion_vals = [a.emotion_intensity for a in annotations]
        avg_emotion = statistics.mean(emotion_vals) if emotion_vals else 0.0

        energy = max(1, min(10, int(avg_emotion * 12)))

        # Detect humor style from dominant emotions
        emotion_counts: dict[str, int] = {}
        for a in annotations:
            emotion_counts[a.dominant_emotion] = emotion_counts.get(
                a.dominant_emotion, 0
            ) + 1
        dominant = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral"

        humor_map = {
            "excitement": "loud",
            "frustration": "chaotic",
            "surprise": "reactive",
            "calm": "dry",
            "neutral": "neutral",
        }

        return {
            "name": "auto",
            "energy_level": energy,
            "humor_style": humor_map.get(dominant, "neutral"),
            "catchphrases": [],
        }

    # ------------------------------------------------------------------
    # Candidate processing (architect + render + quality loop)
    # ------------------------------------------------------------------

    def _process_candidates(
        self,
        candidates: list[ClipCandidate],
        caption_timeline: CaptionTimeline,
        template: dict,
        persona: dict,
        ingest_result: IngestResult,
        max_iterations: int,
        render_all: bool,
        output_dir: str,
    ) -> list[CandidateResult]:
        """
        For each candidate: generate edit script, render, evaluate quality.
        If quality fails, adjust parameters and re-generate (up to max_iterations).
        """
        results: list[CandidateResult] = []
        total = len(candidates)

        for idx, candidate in enumerate(candidates):
            base_progress = idx / max(total, 1)
            self._emit_progress(
                "architect", base_progress,
                f"Processing candidate {idx + 1}/{total} "
                f"(rank {candidate.rank}, {candidate.start:.0f}-{candidate.end:.0f}s)",
            )

            cr = self._process_single_candidate(
                candidate=candidate,
                caption_timeline=caption_timeline,
                template=dict(template),
                persona=dict(persona),
                ingest_result=ingest_result,
                max_iterations=max_iterations,
                render=render_all,
                output_dir=output_dir,
                candidate_index=idx,
                total_candidates=total,
            )
            results.append(cr)

        return results

    def _process_single_candidate(
        self,
        candidate: ClipCandidate,
        caption_timeline: CaptionTimeline,
        template: dict,
        persona: dict,
        ingest_result: IngestResult,
        max_iterations: int,
        render: bool,
        output_dir: str,
        candidate_index: int,
        total_candidates: int,
    ) -> CandidateResult:
        """Process a single candidate through architect -> render -> quality loop."""
        iteration = 0
        current_template = dict(template)
        current_enhancements = template.get("_learned_enhancements", {})
        best_script: Optional[DNAEditScript] = None
        best_report: Optional[QualityReport] = None
        best_video: Optional[str] = None
        current_candidate = candidate

        while iteration < max_iterations:
            iteration += 1
            logger.info(
                "Candidate rank %d, iteration %d/%d",
                candidate.rank, iteration, max_iterations,
            )

            # ---- Architect ----
            persona_for_iteration = self._blend_persona_with_enhancements(
                persona, current_enhancements
            )

            edit_script = self._dna_agent.architect(
                clip_candidate=current_candidate,
                caption_timeline=caption_timeline,
                template=current_template,
                persona=persona_for_iteration,
            )

            # ---- Evaluate quality (pre-render) ----
            quality_report = self._evaluate_quality(edit_script, caption_timeline, current_template)

            logger.info(
                "Quality eval (iteration %d): overall=%.1f, passed=%s, failures=%s",
                iteration, quality_report.overall_score,
                quality_report.passed, quality_report.failures,
            )

            # Keep best so far
            if best_report is None or quality_report.overall_score > best_report.overall_score:
                best_script = edit_script
                best_report = quality_report

            if quality_report.passed:
                logger.info("Quality passed on iteration %d", iteration)
                break

            # ---- Self-correct ----
            if iteration < max_iterations:
                current_template, current_enhancements = self._auto_adjust(
                    quality_report, current_template, current_enhancements,
                )

                if "duration_fitness" in quality_report.failures:
                    current_candidate = self._retime_candidate_for_duration(
                        current_candidate, quality_report, caption_timeline
                    )
                logger.info(
                    "Auto-adjusted parameters for iteration %d: %s",
                    iteration + 1, quality_report.suggestions,
                )

        # ---- Render (using best script) ----
        output_video = None
        render_time = 0.0
        if render and best_script:
            t_render_start = time.time()
            try:
                render_edit_script = self._bridge_to_render_script(
                    best_script, ingest_result.video_path, output_dir,
                )
                output_video = self._render_engine.render(render_edit_script)
                render_time = time.time() - t_render_start
                logger.info(
                    "Rendered candidate rank %d in %.1fs: %s",
                    candidate.rank, render_time, output_video,
                )
            except Exception as e:
                logger.error("Render failed for candidate rank %d: %s", candidate.rank, e)
                render_time = time.time() - t_render_start

        cr = CandidateResult(
            rank=current_candidate.rank,
            candidate=current_candidate,
            edit_script=best_script or edit_script,
            quality_report=best_report or quality_report,
            output_video=output_video,
            render_time_sec=render_time,
        )
        # Store iteration count as ad-hoc attribute for reporting
        cr._iterations = iteration  # type: ignore[attr-defined]
        return cr

    # ------------------------------------------------------------------
    # Quality evaluation
    # ------------------------------------------------------------------

    def _evaluate_quality(
        self,
        edit_script: DNAEditScript,
        caption_timeline: CaptionTimeline,
        template: dict,
    ) -> QualityReport:
        """
        Score an edit script against five quality criteria.

        Criteria
        --------
        1. **Information density**: seconds with content events / total > 0.7
        2. **Pacing variation**: std dev of beat intensities > 15
        3. **Hook strength**: first 3 seconds must have score > 70
        4. **Duration fitness**: within template's recommended range
        5. **Anti-fluff score**: < 20% of beats removed
        """
        beats = edit_script.beats
        if not beats:
            return QualityReport(suggestions=["No beats in edit script"])

        report = QualityReport()
        report.details = {}

        # ---- 1. Information density ----
        total_output_dur = edit_script.total_output_duration
        if total_output_dur <= 0:
            total_output_dur = sum(
                (b.output_end - b.output_start) for b in beats
            )

        content_beats = [
            b for b in beats
            if b.beat_type != "transition" and (
                b.has_game_event or b.has_emotion_peak or b.has_speech_content
            )
        ]
        content_duration = sum(
            b.output_end - b.output_start for b in content_beats
        )
        density_ratio = content_duration / max(total_output_dur, 0.1)

        # Score: 0-100 based on how close we are to the 0.7 threshold
        report.information_density = min(100, (density_ratio / _DENSITY_THRESHOLD) * 100)
        report.passes_density = density_ratio >= _DENSITY_THRESHOLD
        report.details["density_ratio"] = round(density_ratio, 4)
        report.details["content_beats"] = len(content_beats)
        report.details["total_beats"] = len(beats)

        # ---- 2. Pacing variation ----
        intensities = [b.intensity for b in beats if b.beat_type != "transition"]
        if len(intensities) >= 2:
            pacing_std = statistics.stdev(intensities)
        else:
            pacing_std = 0.0

        report.pacing_variation = min(100, (pacing_std / _PACING_STD_THRESHOLD) * 100)
        report.passes_pacing = pacing_std >= _PACING_STD_THRESHOLD
        report.details["pacing_std"] = round(pacing_std, 2)

        # ---- 3. Hook strength ----
        hook_beats = [b for b in beats if b.phase == "hook"]
        if hook_beats:
            hook_intensities = [b.intensity for b in hook_beats]
            max_hook_intensity = max(hook_intensities)
            avg_hook_intensity = statistics.mean(hook_intensities)
            # Weight: 60% max, 40% average
            hook_score = max_hook_intensity * 0.6 + avg_hook_intensity * 0.4
        else:
            hook_score = 0.0

        report.hook_strength = min(100, hook_score)
        report.passes_hook = hook_score >= _HOOK_SCORE_THRESHOLD
        report.details["hook_score"] = round(hook_score, 2)
        report.details["hook_beats"] = len(hook_beats)

        # ---- 4. Duration fitness ----
        duration_range = template.get("durationRange", [30, 90])
        if isinstance(duration_range, dict):
            dur_min = duration_range.get("min", 30)
            dur_max = duration_range.get("max", 90)
        else:
            dur_min, dur_max = duration_range[0], duration_range[-1]

        source_window_dur = max(0.0, float(edit_script.source_end) - float(edit_script.source_start))
        # Short-source adaptive mode:
        # if the candidate window itself is not long enough, relax duration expectations.
        if source_window_dur > 0 and source_window_dur < dur_min * 1.8:
            effective_min = max(12.0, min(dur_min, source_window_dur * 0.55))
            effective_max = max(dur_max, source_window_dur * 1.25)
        else:
            effective_min = float(dur_min)
            effective_max = float(dur_max)

        if effective_min <= total_output_dur <= effective_max:
            duration_score = 100.0
        else:
            # Score decreases linearly as we move away from the range
            if total_output_dur < effective_min:
                distance = effective_min - total_output_dur
                range_size = effective_min
            else:
                distance = total_output_dur - effective_max
                range_size = effective_max
            duration_score = max(0, 100 - (distance / max(range_size, 1)) * 100)

        report.duration_fitness = round(duration_score, 1)
        report.passes_duration = effective_min * 0.8 <= total_output_dur <= effective_max * 1.2
        report.details["output_duration"] = round(total_output_dur, 2)
        report.details["target_range"] = [dur_min, dur_max]
        report.details["effective_target_range"] = [round(effective_min, 2), round(effective_max, 2)]
        report.details["source_window_duration"] = round(source_window_dur, 2)

        # ---- 5. Anti-fluff score ----
        afr = edit_script.anti_fluff_report or {}
        total_raw = afr.get("total_beats_raw", len(beats))
        beats_removed = afr.get("beats_removed", 0)
        removal_rate = beats_removed / max(total_raw, 1)

        if source_window_dur > 0 and source_window_dur < dur_min * 1.8:
            anti_fluff_max = max(_ANTI_FLUFF_MAX_REMOVAL, 0.55)
        else:
            anti_fluff_max = _ANTI_FLUFF_MAX_REMOVAL

        # Score: 100 when 0% removed, 0 when >= 40% removed
        anti_fluff_score = max(0, 100 - (removal_rate / 0.4) * 100)
        report.anti_fluff_score = round(anti_fluff_score, 1)
        report.passes_anti_fluff = removal_rate <= anti_fluff_max
        report.details["removal_rate"] = round(removal_rate, 4)
        report.details["beats_removed"] = beats_removed
        report.details["anti_fluff_max_removal"] = round(anti_fluff_max, 3)

        # ---- Overall score ----
        # Weighted average: hook > density > pacing > anti-fluff > duration
        report.overall_score = round(
            report.information_density * 0.25
            + report.pacing_variation * 0.20
            + report.hook_strength * 0.25
            + report.duration_fitness * 0.15
            + report.anti_fluff_score * 0.15,
            1,
        )

        # ---- Suggestions ----
        if not report.passes_density:
            report.suggestions.append(
                f"Low information density ({density_ratio:.0%}). "
                f"Try lowering the content selection threshold to include more events."
            )
        if not report.passes_pacing:
            report.suggestions.append(
                f"Pacing is too flat (std={pacing_std:.1f}). "
                f"Increase contrast between calm and intense moments."
            )
        if not report.passes_hook:
            report.suggestions.append(
                f"Hook is weak (score={hook_score:.0f}). "
                f"Use a higher-intensity moment for the flash-forward teaser."
            )
        if not report.passes_duration:
            report.suggestions.append(
                f"Duration ({total_output_dur:.0f}s) outside target range "
                f"({dur_min}-{dur_max}s). Adjust clip window or beat count."
            )
        if not report.passes_anti_fluff:
            report.suggestions.append(
                f"Too much fluff removed ({removal_rate:.0%}). "
                f"Lower the anti-fluff threshold or select a more content-rich window."
            )

        return report

    # ------------------------------------------------------------------
    # Self-correction: auto-adjust parameters
    # ------------------------------------------------------------------

    def _auto_adjust(
        self,
        quality_report: QualityReport,
        template: dict,
        enhancements: dict,
    ) -> tuple[dict, dict]:
        """
        Adjust template and enhancement parameters based on quality report
        to improve the next iteration.

        Each failed criterion has a specific adjustment strategy.

        Returns
        -------
        tuple[dict, dict]
            Updated (template, enhancements).
        """
        template = dict(template)
        enhancements = dict(enhancements)

        for failure in quality_report.failures:
            if failure == "information_density":
                # Lower the content selection threshold -- let more moments through
                structure = template.get("structure", {})
                # Increase climax proportion (most content-dense phase)
                if "climax" in structure:
                    structure["climax"] = min(0.60, structure["climax"] + 0.05)
                    # Steal from rising
                    if "build" in structure:
                        structure["build"] = max(0.15, structure["build"] - 0.05)
                template["structure"] = structure
                # Also reduce anti-fluff strictness
                template["_anti_fluff_min_signals"] = max(
                    0, template.get("_anti_fluff_min_signals", 2) - 1
                )

            elif failure == "pacing_variation":
                # Increase contrast: make slow parts slower, fast parts faster
                structure = template.get("structure", {})
                # More pronounced phase transitions help pacing
                if "intro" in structure:
                    structure["intro"] = min(0.15, structure.get("intro", 0.10) + 0.02)
                template["structure"] = structure
                # Suggest more speed variation via effects
                enhancements["effects"] = min(100, enhancements.get("effects", 65) + 15)

            elif failure == "hook_strength":
                # Strengthen the hook
                enhancements["hook"] = min(100, enhancements.get("hook", 75) + 15)
                # Ensure hook uses the flash-forward strategy
                template["hook_strategy"] = "flash_forward"

            elif failure == "duration_fitness":
                # Adjust window sizes for DVD agent
                duration_range = template.get("durationRange", [30, 90])
                details = quality_report.details
                output_dur = details.get("output_duration", 0)
                if output_dur < duration_range[0]:
                    # Too short: expand window sizes
                    template["_window_size_boost"] = 1.5
                else:
                    # Too long: shrink window sizes
                    template["_window_size_boost"] = 0.75

            elif failure == "anti_fluff":
                # Too aggressive fluff removal -- relax thresholds
                template["_anti_fluff_min_signals"] = max(
                    0, template.get("_anti_fluff_min_signals", 2) - 1
                )

        return template, enhancements

    # ------------------------------------------------------------------
    # Best candidate selection
    # ------------------------------------------------------------------

    def _select_best_candidate(
        self,
        candidate_results: list[CandidateResult],
    ) -> Optional[CandidateResult]:
        """
        Select the best candidate from all processed results.

        Scoring prioritizes:
        1. Quality report overall score (60%)
        2. Original DVD composite score (25%)
        3. Whether rendering succeeded (15% bonus)
        """
        if not candidate_results:
            return None

        best: Optional[CandidateResult] = None
        best_score = -1.0

        for cr in candidate_results:
            q_score = cr.quality_report.overall_score / 100.0
            dvd_score = cr.candidate.composite_score
            render_bonus = 0.15 if cr.output_video else 0.0

            combined = q_score * 0.60 + dvd_score * 0.25 + render_bonus
            if combined > best_score:
                best_score = combined
                best = cr

        return best

    # ------------------------------------------------------------------
    # Bridge: DNA EditScript -> Render EditScript
    # ------------------------------------------------------------------

    def _bridge_to_render_script(
        self,
        dna_script: DNAEditScript,
        source_video: str,
        output_dir: str,
    ) -> RenderEditScript:
        """
        Convert a DNA agent EditScript to the render engine's EditScript format.

        The DNA agent and render engine use different EditBeat/EditScript
        dataclasses.  This method bridges between the two representations.
        """
        render_beats: list[RenderEditBeat] = []

        for dna_beat in dna_script.beats:
            # Build effects list for render engine
            effects: list = []
            if dna_beat.effect != "none":
                effects.append({
                    "type": dna_beat.effect,
                    **(dna_beat.effect_params or {}),
                })
            if dna_beat.zoom:
                effects.append({
                    "type": "zoom",
                    "factor": dna_beat.zoom.get("factor", 1.3),
                    "center_x": dna_beat.zoom.get("x", 0.5),
                    "center_y": dna_beat.zoom.get("y", 0.4),
                })

            render_beat = RenderEditBeat(
                phase=dna_beat.phase,
                start=dna_beat.source_start,
                end=dna_beat.source_end,
                effects=effects,
                transition_in=dna_beat.transition_in,
                text_overlay=dna_beat.text_overlay or None,
                text_style=dna_beat.text_style or {},
                pacing=dna_beat.playback_speed,
                music_cue=dna_beat.music_cue,
            )
            render_beats.append(render_beat)

        # Build subtitle segments from voiceover timestamps
        subtitle_segments: list = []
        if dna_script.voiceover_timestamps:
            for start, end, text in dna_script.voiceover_timestamps:
                subtitle_segments.append({
                    "start": start,
                    "end": end,
                    "text": text,
                    "style": {},
                })

        # Fallback: if no timed voiceover/subtitle segments are available,
        # derive readable captions from beat overlays so output is never "silent text-wise".
        if not subtitle_segments:
            for b in render_beats:
                txt = (b.text_overlay or "").strip()
                dur = max(0.0, float(b.end) - float(b.start))
                if not txt or dur < 0.6:
                    continue
                seg_end = min(float(b.end), float(b.start) + max(1.2, min(4.0, dur)))
                subtitle_segments.append({
                    "start": float(b.start),
                    "end": seg_end,
                    "text": txt,
                    "style": {"bold": True},
                })

        # BGM config
        bgm_config = {
            "path": None,  # No pre-selected BGM file
            "mood": dna_script.bgm.mood if dna_script.bgm else "chill",
            "fade_in": dna_script.bgm.fade_in_sec if dna_script.bgm else 2.0,
            "fade_out": dna_script.bgm.fade_out_sec if dna_script.bgm else 3.0,
            "volume": dna_script.bgm.mix_level if dna_script.bgm else 0.3,
        }

        render_script = RenderEditScript(
            source_video=source_video,
            beats=render_beats,
            bgm_config=bgm_config,
            subtitle_segments=subtitle_segments,
            voiceover_script=dna_script.voiceover_script or None,
            output_config={
                "resolution": "1920x1080",
                "fps": 60,
                "codec": "libx264",
                "audio_codec": "aac",
                "format": "mp4",
                "crf": "18",
            },
        )
        return render_script

    # ------------------------------------------------------------------
    # Helper: build DVD agent config from template
    # ------------------------------------------------------------------

    def _build_dvd_config(self, template: dict) -> dict:
        """Build a config dict for DVDAgent.discover() from the template."""
        duration_range = template.get("durationRange", [30, 90])
        if isinstance(duration_range, dict):
            dur_min = duration_range.get("min", 30)
            dur_max = duration_range.get("max", 90)
        else:
            dur_min, dur_max = duration_range[0], duration_range[-1]

        # Generate window sizes that cover the template's duration range
        window_sizes = []
        size = dur_min
        while size <= dur_max:
            window_sizes.append(int(size))
            size += max(15, int((dur_max - dur_min) / 4))
        if dur_max not in window_sizes:
            window_sizes.append(int(dur_max))

        # Apply boost from auto-adjust if present
        boost = template.get("_window_size_boost", 1.0)
        window_sizes = [max(10, int(w * boost)) for w in window_sizes]

        # Content filter weights
        content_filter = template.get("content_filter", {})
        game_w = content_filter.get("game_weight", 0.35)
        emotion_w = content_filter.get("emotion_weight", 0.40)
        audience_w = content_filter.get("audience_weight", 0.25)

        return {
            "window_sizes": sorted(set(window_sizes)),
            "min_gap": max(30, dur_min * 0.8),
            "top_n": self.config.get("num_candidates", _NUM_CANDIDATES),
            "step_sec": 2.0,
            "game_weight": game_w,
            "emotion_weight": emotion_w,
            "audience_weight": audience_w,
        }

    # ------------------------------------------------------------------
    # Helper: build video analysis dict for memory system
    # ------------------------------------------------------------------

    def _build_video_analysis(self, caption_timeline: CaptionTimeline) -> dict:
        """Build a video analysis dict for the memory recommendation system."""
        annotations = caption_timeline.annotations
        if not annotations:
            return {"duration": caption_timeline.duration_sec}

        composites = [a.composite_score for a in annotations]
        game_events = sum(1 for a in annotations if a.has_game_event)

        emotion_counts: dict[str, int] = {}
        for a in annotations:
            emotion_counts[a.dominant_emotion] = emotion_counts.get(
                a.dominant_emotion, 0
            ) + 1
        dominant = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral"
        mood = _MOOD_FROM_CONTENT.get(dominant, "intense")

        return {
            "duration": caption_timeline.duration_sec,
            "intensity": int(statistics.mean(composites) * 100) if composites else 50,
            "mood": mood,
            "game_events": game_events,
            "tags": [mood, dominant],
        }

    # ------------------------------------------------------------------
    # Helper: fallback candidate when DVD finds nothing
    # ------------------------------------------------------------------

    def _fallback_candidate(self, caption_timeline: CaptionTimeline) -> list[ClipCandidate]:
        """Create a fallback candidate from the full timeline when DVD finds nothing."""
        duration = caption_timeline.duration_sec
        # Use up to 90 seconds from the most interesting part
        target = min(90, duration)

        # Find the peak region
        annotations = caption_timeline.annotations
        if annotations:
            peak = max(annotations, key=lambda a: a.composite_score)
            center = peak.start
            start = max(0, center - target / 2)
            end = min(duration, start + target)
            start = max(0, end - target)  # Ensure we get full target duration
        else:
            start = 0
            end = min(target, duration)

        window_anns = caption_timeline.slice(start, end)

        return [ClipCandidate(
            rank=1,
            start=start,
            end=end,
            duration=end - start,
            composite_score=0.3,
            window_score=WindowScore(start=start, end=end, duration=end - start),
            dominant_signal="balanced",
            narrative_potential=0.3,
            scoring_strategy="fallback",
            annotations=window_anns,
            narrative_arc=None,
        )]

    def _retime_candidate_for_duration(
        self,
        candidate: ClipCandidate,
        quality_report: QualityReport,
        caption_timeline: CaptionTimeline,
    ) -> ClipCandidate:
        """Expand/shrink candidate window when duration fitness fails."""
        details = quality_report.details or {}
        out_dur = float(details.get("output_duration", candidate.duration))
        tr = details.get("target_range", [30, 90])
        if isinstance(tr, list) and len(tr) >= 2:
            target_min = float(tr[0])
            target_max = float(tr[-1])
        else:
            target_min, target_max = 30.0, 90.0

        if target_min <= 0:
            target_min = 10.0
        if target_max < target_min:
            target_max = target_min + 30.0

        desired = candidate.duration
        if out_dur < target_min:
            grow_ratio = min(2.2, target_min / max(out_dur, 0.5))
            desired = min(target_max * 1.1, candidate.duration * grow_ratio)
        elif out_dur > target_max:
            shrink_ratio = max(0.55, target_max / max(out_dur, 1.0))
            desired = max(target_min * 0.85, candidate.duration * shrink_ratio)
        else:
            return candidate

        duration = caption_timeline.duration_sec
        desired = max(8.0, min(desired, duration))

        center = (candidate.start + candidate.end) / 2.0
        new_start = max(0.0, center - desired / 2.0)
        new_end = min(duration, new_start + desired)
        new_start = max(0.0, new_end - desired)

        if abs(new_start - candidate.start) < 0.5 and abs(new_end - candidate.end) < 0.5:
            return candidate

        anns = caption_timeline.slice(new_start, new_end) or candidate.annotations
        ws = WindowScore(
            start=new_start,
            end=new_end,
            duration=new_end - new_start,
            game_score=candidate.window_score.game_score,
            emotion_score=candidate.window_score.emotion_score,
            audience_score=candidate.window_score.audience_score,
            triangulation=candidate.window_score.triangulation,
            peak_composite=candidate.window_score.peak_composite,
            mean_composite=candidate.window_score.mean_composite,
            narrative_potential=candidate.window_score.narrative_potential,
            momentum_score=candidate.window_score.momentum_score,
        )
        logger.info(
            "Retimed candidate rank %d: %.1f-%.1fs -> %.1f-%.1fs for duration recovery",
            candidate.rank,
            candidate.start,
            candidate.end,
            new_start,
            new_end,
        )
        return ClipCandidate(
            rank=candidate.rank,
            start=new_start,
            end=new_end,
            duration=new_end - new_start,
            composite_score=candidate.composite_score,
            window_score=ws,
            dominant_signal=candidate.dominant_signal,
            narrative_potential=candidate.narrative_potential,
            scoring_strategy=candidate.scoring_strategy,
            annotations=anns,
            narrative_arc=candidate.narrative_arc,
        )

    def _template_from_intent(self) -> Optional[str]:
        """Infer preferred template from creator brief and target platform."""
        brief = str(self.config.get("creator_brief") or "").strip().lower()
        platform = str(self.config.get("target_platform") or "").strip().lower()

        if platform in {"tiktok", "douyin", "shorts", "reels"} and not brief:
            return "tiktok-vertical"

        combined = f"{platform} {brief}".strip()
        if not combined:
            return None

        for keyword, template_id in _INTENT_TEMPLATE_KEYWORDS:
            if keyword in combined:
                return template_id
        return None

    def _augment_persona_with_creator_brief(self, persona: dict) -> dict:
        """Merge creator brief keywords into persona style signals."""
        persona = dict(persona or {})
        brief = str(self.config.get("creator_brief") or "").strip()
        if not brief:
            return persona

        lower = brief.lower()
        style = dict(persona.get("style_prefs") or {})

        if any(k in lower for k in ("fast", "aggressive", "炸", "节奏快", "高能")):
            style["effects"] = max(float(style.get("effects", 65)), 82.0)
            style["hook"] = max(float(style.get("hook", 70)), 85.0)
            persona["energy_level"] = max(int(persona.get("energy_level", 6)), 8)
        if any(k in lower for k in ("clean", "calm", "慢", "沉浸", "低调")):
            style["effects"] = min(float(style.get("effects", 65)), 45.0)
            style["transitions"] = max(float(style.get("transitions", 65)), 75.0)
            persona["energy_level"] = min(int(persona.get("energy_level", 6)), 5)
        if any(k in lower for k in ("subtitle", "caption", "字幕", "台词", "解说")):
            style["subtitles"] = max(float(style.get("subtitles", 60)), 82.0)
        if any(k in lower for k in ("music", "bgm", "配乐")):
            style["bgm"] = max(float(style.get("bgm", 65)), 78.0)

        persona["style_prefs"] = style
        persona["creator_brief"] = brief
        return persona

    @staticmethod
    def _blend_persona_with_enhancements(persona: dict, enhancements: dict) -> dict:
        """Inject learned enhancement levels into persona for DNA decisions."""
        p = dict(persona or {})
        style = dict(p.get("style_prefs") or {})
        enh = enhancements or {}
        for key in ("bgm", "subtitles", "effects", "hook", "transitions"):
            val = enh.get(key)
            if isinstance(val, (int, float)):
                old_val = float(style.get(key, val))
                style[key] = round(old_val * 0.4 + float(val) * 0.6, 2)

        energy = int(p.get("energy_level", 6))
        effects_lvl = float(style.get("effects", 65))
        hook_lvl = float(style.get("hook", 70))
        boosted = int(round(energy * 0.6 + ((effects_lvl + hook_lvl) / 2.0) / 10.0 * 0.4))
        p["energy_level"] = max(1, min(10, boosted))
        p["style_prefs"] = style
        return p

    # ------------------------------------------------------------------
    # Progress helpers
    # ------------------------------------------------------------------

    def _emit_progress(self, stage: str, progress: float, message: str) -> None:
        """Emit a progress event through the callback."""
        self._current_stage = stage
        self._stage_base_progress = progress
        self._progress(stage, progress, message)
        logger.info("[%s %.0f%%] %s", stage, progress * 100, message)

    def _render_progress_adapter(self, stage: str, progress: float, message: str) -> None:
        """Adapter that forwards render engine progress events to our callback."""
        self._progress(f"render:{stage}", progress, message)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _energy_from_mood(mood: str) -> int:
        """Map mood preference to energy level (1-10)."""
        return {
            "intense": 8,
            "chaotic": 9,
            "triumphant": 7,
            "chill": 3,
        }.get(mood, 5)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def run_pipeline(
    source: str,
    streamer_id: Optional[str] = None,
    language: Optional[str] = None,
    config: Optional[dict] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> PipelineResult:
    """
    One-call convenience function for the full pipeline.

    Parameters
    ----------
    source : str
        Video URL or local file path.
    streamer_id : str, optional
        Streamer identifier for personalization.
    language : str, optional
        Language hint for ASR.
    config : dict, optional
        Pipeline configuration overrides.
    progress_callback : callable, optional
        Progress event callback.

    Returns
    -------
    PipelineResult
    """
    pipeline = KairoPipeline(
        streamer_id=streamer_id,
        config=config or {},
        progress_callback=progress_callback,
    )
    return pipeline.run(source, language=language)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <url_or_path> [streamer_id] [language]")
        print("")
        print("Examples:")
        print("  python pipeline.py https://www.bilibili.com/video/BV1xxx")
        print("  python pipeline.py /path/to/video.mp4 my_streamer zh")
        print("  python pipeline.py https://youtu.be/xxx streamer_123 en")
        sys.exit(1)

    source = sys.argv[1]
    streamer_id = sys.argv[2] if len(sys.argv) > 2 else None
    language = sys.argv[3] if len(sys.argv) > 3 else None

    def on_progress(stage: str, progress: float, message: str) -> None:
        print(f"  [{stage}] {progress * 100:.0f}% -- {message}")

    print("=" * 60)
    print("  KAIRO AUTONOMOUS PIPELINE")
    print("=" * 60)
    print(f"  Source:    {source}")
    print(f"  Streamer:  {streamer_id or '(anonymous)'}")
    print(f"  Language:  {language or '(auto)'}")
    print("=" * 60)
    print()

    result = run_pipeline(
        source=source,
        streamer_id=streamer_id,
        language=language,
        progress_callback=on_progress,
    )

    print()
    print(result.summary())
    if result.report:
        print(result.report)

    if result.output_video:
        print(f"\nOutput video: {result.output_video}")
    else:
        print("\nNo video was rendered.")

    sys.exit(0 if result.quality_score >= 50 else 1)
