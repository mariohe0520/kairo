"""
Kairo CaptionAgent -- Multi-modal Frame Understanding Agent.

Analyzes sampled video frames using a local Vision-Language Model (MLX-VLM on
Apple Silicon) combined with ASR transcript segments and audio energy data to
produce a structured, per-second annotated timeline.

Tri-modal signal extraction:
  - Game signals:     kills, deaths, objectives, ability usage, score changes
  - Emotion signals:  excitement, frustration, surprise, calm
  - Audience signals: chat density, emote spikes (when chat overlay is visible)

The agent falls back to heuristic analysis when the VLM is unavailable so the
pipeline never hard-fails on a missing model dependency.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("kairo.caption_agent")

# ---------------------------------------------------------------------------
# Structured data types
# ---------------------------------------------------------------------------

@dataclass
class GameSignal:
    """Detected game-state change at a point in time."""
    event_type: str          # kill, death, objective, ability, score_change, ui_event
    confidence: float        # 0.0 - 1.0
    details: str = ""        # free-text description from VLM
    kill_count: int = 0
    is_multi_kill: bool = False
    is_clutch: bool = False
    score_delta: tuple[int, int] = (0, 0)   # (team, enemy) change


@dataclass
class EmotionSignal:
    """Emotion state inferred from facecam + voice energy + speech content."""
    dominant: str            # excitement, frustration, surprise, calm, neutral
    intensity: float         # 0.0 - 1.0
    voice_energy: float = 0.0
    facecam_expression: str = "unknown"
    speech_sentiment: str = "neutral"


@dataclass
class AudienceSignal:
    """Audience engagement inferred from visible chat overlay / emote density."""
    chat_density: float = 0.0    # 0.0 - 1.0 (normalized messages per second)
    emote_spike: bool = False
    emote_types: list[str] = field(default_factory=list)
    engagement_score: float = 0.0


@dataclass
class FrameAnalysis:
    """Result of analyzing a single sampled frame."""
    timestamp: float
    frame_path: str
    game_signals: list[GameSignal] = field(default_factory=list)
    emotion: EmotionSignal = field(default_factory=lambda: EmotionSignal("neutral", 0.0))
    audience: AudienceSignal = field(default_factory=AudienceSignal)
    visual_intensity: float = 0.0   # 0.0 - 1.0
    raw_vlm_output: str = ""        # raw text from VLM for debugging
    used_vlm: bool = False


@dataclass
class SegmentAnnotation:
    """Merged, smoothed annotation for a time segment (typically 1 second)."""
    start: float
    end: float
    game_intensity: float = 0.0       # 0.0 - 1.0
    emotion_intensity: float = 0.0    # 0.0 - 1.0
    audience_intensity: float = 0.0   # 0.0 - 1.0
    composite_score: float = 0.0      # 0.0 - 1.0
    dominant_emotion: str = "neutral"
    game_events: list[str] = field(default_factory=list)
    speech_text: str = ""
    has_game_event: bool = False
    has_emotion_peak: bool = False
    has_audience_spike: bool = False


@dataclass
class CaptionTimeline:
    """Full annotated timeline produced by CaptionAgent."""
    duration_sec: float
    annotations: list[SegmentAnnotation]
    frame_analyses: list[FrameAnalysis]
    summary: dict = field(default_factory=dict)

    # ------ convenience accessors ------

    def at(self, t: float) -> Optional[SegmentAnnotation]:
        """Return the annotation covering timestamp *t* (seconds)."""
        for ann in self.annotations:
            if ann.start <= t < ann.end:
                return ann
        return None

    def slice(self, start: float, end: float) -> list[SegmentAnnotation]:
        """Return annotations that overlap the [start, end) window."""
        return [a for a in self.annotations if a.end > start and a.start < end]

    def peak_moments(self, top_n: int = 10) -> list[SegmentAnnotation]:
        """Return the *top_n* highest composite-score annotations."""
        return sorted(self.annotations, key=lambda a: a.composite_score, reverse=True)[:top_n]


# ---------------------------------------------------------------------------
# VLM prompt template
# ---------------------------------------------------------------------------

_VLM_PROMPT = """You are a gaming video analyst. Analyze this frame from a gaming livestream.

Context (ASR transcript near this frame):
\"\"\"{transcript_context}\"\"\"

Audio energy at this moment: {audio_energy:.2f} (0=silent, 1=loud)

Respond ONLY with valid JSON (no markdown fences) matching this schema:
{{
  "game_events": [
    {{
      "type": "kill|death|objective|ability|score_change|ui_event|none",
      "confidence": 0.0-1.0,
      "details": "short description",
      "kill_count": 0,
      "is_multi_kill": false,
      "is_clutch": false
    }}
  ],
  "emotion": {{
    "dominant": "excitement|frustration|surprise|calm|neutral",
    "intensity": 0.0-1.0,
    "facecam_expression": "description of face if visible"
  }},
  "audience": {{
    "chat_density": 0.0-1.0,
    "emote_spike": false,
    "emote_types": []
  }},
  "visual_intensity": 0.0-1.0
}}"""

# ---------------------------------------------------------------------------
# CaptionAgent
# ---------------------------------------------------------------------------

# Lazy import guard so the module loads even without mlx_vlm installed.
_mlx_vlm = None
_vlm_model = None
_vlm_processor = None
_VLM_AVAILABLE: Optional[bool] = None

def _ensure_vlm_loaded(model_id: str = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit") -> bool:
    """Attempt to load MLX-VLM once.  Returns True if the model is ready."""
    global _mlx_vlm, _vlm_model, _vlm_processor, _VLM_AVAILABLE

    if _VLM_AVAILABLE is not None:
        return _VLM_AVAILABLE

    try:
        import mlx_vlm                           # type: ignore[import-untyped]
        from mlx_vlm import load as vlm_load     # type: ignore[import-untyped]
        _mlx_vlm = mlx_vlm
        logger.info("Loading VLM model: %s", model_id)
        _vlm_model, _vlm_processor = vlm_load(model_id)
        _VLM_AVAILABLE = True
        logger.info("VLM loaded successfully")
    except Exception as exc:
        logger.warning("VLM unavailable, falling back to heuristics: %s", exc)
        _VLM_AVAILABLE = False

    return _VLM_AVAILABLE


class CaptionAgent:
    """
    Multi-modal frame understanding agent.

    Analyses sampled frames (from ``IngestResult.frames_dir``) together with
    ASR transcript segments and audio energy to produce a richly annotated
    ``CaptionTimeline``.

    Parameters
    ----------
    vlm_model_id : str
        HuggingFace model ID for MLX-VLM.  Defaults to a quantised Qwen2.5-VL.
    batch_size : int
        How many frames to process before yielding (for progress reporting).
    smoothing_window : int
        Number of seconds for the sliding-window signal smoother.
    max_tokens : int
        Maximum VLM generation tokens per frame.
    """

    def __init__(
        self,
        vlm_model_id: str = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit",
        batch_size: int = 8,
        smoothing_window: int = 5,
        max_tokens: int = 512,
    ) -> None:
        self.vlm_model_id = vlm_model_id
        self.batch_size = batch_size
        self.smoothing_window = smoothing_window
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, ingest_result: Any) -> CaptionTimeline:
        """
        Run the full caption pipeline on an ``IngestResult``.

        Steps
        -----
        1. Load sampled frames from ``ingest_result.frames_dir``.
        2. Analyse each frame (VLM or heuristic).
        3. Merge frame analyses with ASR transcript segments and audio energy
           into per-second ``SegmentAnnotation`` objects.
        4. Apply sliding-window smoothing.
        5. Compute summary statistics.

        Returns
        -------
        CaptionTimeline
        """
        frames_dir = ingest_result.frames_dir
        transcript_segments = ingest_result.transcript_segments or []
        audio_energy: list[float] = ingest_result.metadata.get("audio_energy", [])
        duration_sec: float = ingest_result.duration_sec

        # --- gather frame paths ---
        frame_paths = sorted(
            str(p) for p in Path(frames_dir).glob("frame_*.jpg")
        )
        if not frame_paths:
            frame_paths = sorted(
                str(p) for p in Path(frames_dir).glob("frame_*.png")
            )
        if not frame_paths:
            logger.warning("No frames found in %s", frames_dir)
            return CaptionTimeline(duration_sec=duration_sec, annotations=[], frame_analyses=[])

        logger.info("Analyzing %d frames from %s", len(frame_paths), frames_dir)

        # --- analyse frames in batches ---
        frame_analyses: list[FrameAnalysis] = []
        for batch_start in range(0, len(frame_paths), self.batch_size):
            batch = frame_paths[batch_start : batch_start + self.batch_size]
            for idx, fpath in enumerate(batch):
                global_idx = batch_start + idx
                timestamp = float(global_idx)  # 1 fps assumption from ingest

                context = self._build_frame_context(
                    timestamp, transcript_segments, audio_energy
                )
                analysis = self._analyze_frame(fpath, context)
                analysis.timestamp = timestamp
                frame_analyses.append(analysis)

            if (batch_start + self.batch_size) % (self.batch_size * 4) == 0:
                logger.info(
                    "  progress: %d / %d frames",
                    min(batch_start + self.batch_size, len(frame_paths)),
                    len(frame_paths),
                )

        # --- merge into per-second annotations ---
        annotations = self._merge_signals(
            frame_analyses, transcript_segments, audio_energy, duration_sec
        )

        # --- smooth ---
        annotations = self._smooth_annotations(annotations)

        # --- summary ---
        summary = self._compute_summary(annotations, frame_analyses)

        timeline = CaptionTimeline(
            duration_sec=duration_sec,
            annotations=annotations,
            frame_analyses=frame_analyses,
            summary=summary,
        )
        logger.info(
            "CaptionTimeline: %d annotations, %.0fs duration, peak=%.2f",
            len(annotations),
            duration_sec,
            summary.get("peak_composite", 0),
        )
        return timeline

    # ------------------------------------------------------------------
    # Frame analysis (VLM or heuristic)
    # ------------------------------------------------------------------

    def _analyze_frame(self, frame_path: str, context: dict) -> FrameAnalysis:
        """
        Analyze a single frame.

        Attempts VLM first; falls back to heuristic if unavailable or on error.
        """
        analysis = FrameAnalysis(timestamp=0.0, frame_path=frame_path)

        if _ensure_vlm_loaded(self.vlm_model_id):
            try:
                analysis = self._analyze_frame_vlm(frame_path, context)
                return analysis
            except Exception as exc:
                logger.debug("VLM analysis failed for %s: %s", frame_path, exc)

        # Heuristic fallback
        analysis = self._analyze_frame_heuristic(frame_path, context)
        return analysis

    def _analyze_frame_vlm(self, frame_path: str, context: dict) -> FrameAnalysis:
        """Run MLX-VLM on a single frame and parse the structured JSON output."""
        assert _mlx_vlm is not None and _vlm_model is not None

        prompt = _VLM_PROMPT.format(
            transcript_context=context.get("transcript_text", ""),
            audio_energy=context.get("audio_energy", 0.0),
        )

        # mlx_vlm.generate accepts image path + text prompt
        raw_output: str = _mlx_vlm.generate(
            _vlm_model,
            _vlm_processor,
            prompt,
            image=frame_path,
            max_tokens=self.max_tokens,
            verbose=False,
        )

        parsed = self._parse_vlm_json(raw_output)

        game_signals: list[GameSignal] = []
        for ge in parsed.get("game_events", []):
            if ge.get("type", "none") == "none":
                continue
            game_signals.append(
                GameSignal(
                    event_type=ge["type"],
                    confidence=float(ge.get("confidence", 0.5)),
                    details=ge.get("details", ""),
                    kill_count=int(ge.get("kill_count", 0)),
                    is_multi_kill=bool(ge.get("is_multi_kill", False)),
                    is_clutch=bool(ge.get("is_clutch", False)),
                )
            )

        emo_data = parsed.get("emotion", {})
        emotion = EmotionSignal(
            dominant=emo_data.get("dominant", "neutral"),
            intensity=float(emo_data.get("intensity", 0.0)),
            voice_energy=context.get("audio_energy", 0.0),
            facecam_expression=emo_data.get("facecam_expression", "unknown"),
            speech_sentiment=context.get("speech_sentiment", "neutral"),
        )

        aud_data = parsed.get("audience", {})
        audience = AudienceSignal(
            chat_density=float(aud_data.get("chat_density", 0.0)),
            emote_spike=bool(aud_data.get("emote_spike", False)),
            emote_types=list(aud_data.get("emote_types", [])),
            engagement_score=float(aud_data.get("chat_density", 0.0)),
        )

        return FrameAnalysis(
            timestamp=0.0,
            frame_path=frame_path,
            game_signals=game_signals,
            emotion=emotion,
            audience=audience,
            visual_intensity=float(parsed.get("visual_intensity", 0.0)),
            raw_vlm_output=raw_output,
            used_vlm=True,
        )

    def _analyze_frame_heuristic(self, frame_path: str, context: dict) -> FrameAnalysis:
        """
        Heuristic fallback when VLM is unavailable.

        Uses audio energy, transcript keywords, and frame filename index to
        produce rough estimates.  This is deliberately conservative so the
        downstream DVD agent is not misled by fabricated high-confidence data.
        """
        audio_e = context.get("audio_energy", 0.0)
        transcript = context.get("transcript_text", "").lower()

        # ---- game signal heuristics from speech keywords ----
        game_signals: list[GameSignal] = []
        kill_keywords = {"kill", "headshot", "frag", "ace", "multi", "triple", "quad", "penta", "wipe"}
        death_keywords = {"died", "dead", "rip", "gg", "unlucky", "bruh"}
        objective_keywords = {"plant", "defuse", "capture", "objective", "push", "ult", "ulted"}

        matched_kill = any(kw in transcript for kw in kill_keywords)
        matched_death = any(kw in transcript for kw in death_keywords)
        matched_obj = any(kw in transcript for kw in objective_keywords)

        if matched_kill:
            game_signals.append(
                GameSignal(event_type="kill", confidence=0.4, details="keyword-heuristic")
            )
        if matched_death:
            game_signals.append(
                GameSignal(event_type="death", confidence=0.35, details="keyword-heuristic")
            )
        if matched_obj:
            game_signals.append(
                GameSignal(event_type="objective", confidence=0.35, details="keyword-heuristic")
            )

        # ---- emotion heuristics from audio energy + speech ----
        excitement_keywords = {"nice", "let's go", "insane", "crazy", "oh my god", "clutch", "no way", "wow"}
        frustration_keywords = {"what", "no", "how", "broken", "bs", "cheat", "hack", "tilt", "rage"}

        excited = any(kw in transcript for kw in excitement_keywords)
        frustrated = any(kw in transcript for kw in frustration_keywords)

        if excited and audio_e > 0.6:
            dominant_emo = "excitement"
            emo_intensity = min(1.0, audio_e * 1.2)
        elif frustrated and audio_e > 0.5:
            dominant_emo = "frustration"
            emo_intensity = min(1.0, audio_e * 1.1)
        elif audio_e > 0.7:
            dominant_emo = "surprise"
            emo_intensity = audio_e
        elif audio_e < 0.2:
            dominant_emo = "calm"
            emo_intensity = 0.1
        else:
            dominant_emo = "neutral"
            emo_intensity = audio_e * 0.5

        emotion = EmotionSignal(
            dominant=dominant_emo,
            intensity=emo_intensity,
            voice_energy=audio_e,
            facecam_expression="unknown (heuristic)",
            speech_sentiment="positive" if excited else ("negative" if frustrated else "neutral"),
        )

        # ---- visual intensity from audio energy (rough proxy) ----
        visual_intensity = min(1.0, audio_e * 0.8 + (0.2 if game_signals else 0.0))

        return FrameAnalysis(
            timestamp=0.0,
            frame_path=frame_path,
            game_signals=game_signals,
            emotion=emotion,
            audience=AudienceSignal(engagement_score=audio_e * 0.3),
            visual_intensity=visual_intensity,
            raw_vlm_output="",
            used_vlm=False,
        )

    # ------------------------------------------------------------------
    # Merge signals into per-second annotations
    # ------------------------------------------------------------------

    def _merge_signals(
        self,
        frame_analyses: list[FrameAnalysis],
        transcript_segments: list[dict],
        audio_energy: list[float],
        duration_sec: float,
    ) -> list[SegmentAnnotation]:
        """
        Combine frame analyses, transcript segments and audio energy into
        one ``SegmentAnnotation`` per second of the video.
        """
        n_seconds = max(1, int(math.ceil(duration_sec)))
        annotations: list[SegmentAnnotation] = []

        # Index transcript segments by second for fast lookup
        transcript_by_sec: dict[int, list[dict]] = {}
        for seg in transcript_segments:
            seg_start = int(seg.get("start", 0))
            seg_end = int(math.ceil(seg.get("end", seg_start + 1)))
            for s in range(seg_start, seg_end + 1):
                transcript_by_sec.setdefault(s, []).append(seg)

        # Index frame analyses by rounded timestamp
        frame_by_sec: dict[int, FrameAnalysis] = {}
        for fa in frame_analyses:
            sec = int(round(fa.timestamp))
            frame_by_sec[sec] = fa

        for sec in range(n_seconds):
            fa = frame_by_sec.get(sec)
            ae = audio_energy[sec] if sec < len(audio_energy) else 0.0
            segs = transcript_by_sec.get(sec, [])
            speech_text = " ".join(s.get("text", "") for s in segs).strip()

            # --- game intensity ---
            game_intensity = 0.0
            game_events: list[str] = []
            if fa and fa.game_signals:
                for gs in fa.game_signals:
                    game_intensity = max(game_intensity, gs.confidence)
                    game_events.append(gs.event_type)

            # --- emotion intensity (combine voice energy + VLM/heuristic) ---
            emotion_intensity = 0.0
            dominant_emotion = "neutral"
            if fa:
                # Weighted blend: 40% VLM emotion, 40% voice energy, 20% visual
                emotion_intensity = (
                    fa.emotion.intensity * 0.4
                    + ae * 0.4
                    + fa.visual_intensity * 0.2
                )
                dominant_emotion = fa.emotion.dominant

            # --- audience intensity ---
            audience_intensity = 0.0
            if fa:
                audience_intensity = fa.audience.engagement_score

            # --- composite ---
            composite = (
                game_intensity * 0.35
                + emotion_intensity * 0.40
                + audience_intensity * 0.25
            )

            annotations.append(
                SegmentAnnotation(
                    start=float(sec),
                    end=float(sec + 1),
                    game_intensity=round(game_intensity, 4),
                    emotion_intensity=round(emotion_intensity, 4),
                    audience_intensity=round(audience_intensity, 4),
                    composite_score=round(composite, 4),
                    dominant_emotion=dominant_emotion,
                    game_events=game_events,
                    speech_text=speech_text,
                    has_game_event=bool(game_events),
                    has_emotion_peak=emotion_intensity > 0.65,
                    has_audience_spike=audience_intensity > 0.5,
                )
            )

        return annotations

    # ------------------------------------------------------------------
    # Signal smoothing
    # ------------------------------------------------------------------

    def _smooth_annotations(
        self, annotations: list[SegmentAnnotation]
    ) -> list[SegmentAnnotation]:
        """
        Apply a centred sliding-window average over the three intensity
        signals and the composite score.  This removes per-frame noise while
        preserving genuine peaks.
        """
        n = len(annotations)
        if n <= 1:
            return annotations

        half_w = self.smoothing_window // 2

        def _smoothed(values: list[float]) -> list[float]:
            out: list[float] = []
            for i in range(n):
                lo = max(0, i - half_w)
                hi = min(n, i + half_w + 1)
                window = values[lo:hi]
                # Weighted: centre value gets double weight to preserve peaks
                weight_sum = len(window) + 1
                val = (sum(window) + values[i]) / weight_sum
                out.append(round(val, 4))
            return out

        game_vals = _smoothed([a.game_intensity for a in annotations])
        emo_vals = _smoothed([a.emotion_intensity for a in annotations])
        aud_vals = _smoothed([a.audience_intensity for a in annotations])
        comp_vals = _smoothed([a.composite_score for a in annotations])

        for i, ann in enumerate(annotations):
            ann.game_intensity = game_vals[i]
            ann.emotion_intensity = emo_vals[i]
            ann.audience_intensity = aud_vals[i]
            ann.composite_score = comp_vals[i]

        return annotations

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_frame_context(
        self,
        timestamp: float,
        transcript_segments: list[dict],
        audio_energy: list[float],
    ) -> dict:
        """
        Build context dict for a frame at *timestamp*: nearby transcript text,
        audio energy, and speech sentiment keywords.
        """
        # Gather transcript text within +/- 3 seconds
        window = 3.0
        nearby: list[str] = []
        for seg in transcript_segments:
            seg_start = seg.get("start", 0.0)
            seg_end = seg.get("end", seg_start + 1.0)
            if seg_end >= timestamp - window and seg_start <= timestamp + window:
                nearby.append(seg.get("text", ""))

        transcript_text = " ".join(nearby).strip()

        sec_idx = int(round(timestamp))
        ae = audio_energy[sec_idx] if sec_idx < len(audio_energy) else 0.0

        return {
            "transcript_text": transcript_text,
            "audio_energy": ae,
            "speech_sentiment": "neutral",  # upgraded by VLM when available
        }

    @staticmethod
    def _parse_vlm_json(raw: str) -> dict:
        """
        Best-effort parse of JSON from VLM output.

        VLMs sometimes wrap JSON in markdown fences or include preamble text.
        This method strips that away and returns the parsed dict, or an empty
        dict on failure.
        """
        # Strip markdown code fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw)
        cleaned = cleaned.strip().rstrip("`").strip()

        # Try direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try extracting the first JSON object
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        logger.debug("Failed to parse VLM JSON: %s", raw[:200])
        return {}

    @staticmethod
    def _compute_summary(
        annotations: list[SegmentAnnotation],
        frame_analyses: list[FrameAnalysis],
    ) -> dict:
        """Compute aggregate statistics for the timeline."""
        if not annotations:
            return {}

        composites = [a.composite_score for a in annotations]
        game_vals = [a.game_intensity for a in annotations]
        emo_vals = [a.emotion_intensity for a in annotations]

        n_game_events = sum(1 for a in annotations if a.has_game_event)
        n_emotion_peaks = sum(1 for a in annotations if a.has_emotion_peak)
        n_audience_spikes = sum(1 for a in annotations if a.has_audience_spike)
        vlm_used = sum(1 for fa in frame_analyses if fa.used_vlm)

        return {
            "total_seconds": len(annotations),
            "peak_composite": max(composites) if composites else 0.0,
            "mean_composite": round(sum(composites) / len(composites), 4),
            "peak_game_intensity": max(game_vals) if game_vals else 0.0,
            "peak_emotion_intensity": max(emo_vals) if emo_vals else 0.0,
            "game_event_seconds": n_game_events,
            "emotion_peak_seconds": n_emotion_peaks,
            "audience_spike_seconds": n_audience_spikes,
            "vlm_frames_analyzed": vlm_used,
            "heuristic_frames_analyzed": len(frame_analyses) - vlm_used,
        }
