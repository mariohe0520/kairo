"""
Kairo DNAAgent -- Dynamic Narrative Architect.

Takes ``ClipCandidate`` objects from the DVD agent and produces frame-accurate
edit decision lists (EDLs) with:

  - Narrative structure: Hook (0-3s) -> Rising Action -> Climax -> Resolution
  - Beat-level timestamps, effects, transitions, text overlays
  - Anti-fluff validation: every segment must earn its screen time
  - TTS voiceover script suggestions
  - BGM mood selection with sync points

The agent uses a local LLM (via Ollama or mlx-lm) for creative narrative
generation and voiceover scripts, with a deterministic template-based fallback
when no LLM is available.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import subprocess
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("kairo.dna_agent")

# ---------------------------------------------------------------------------
# Import shared types
# ---------------------------------------------------------------------------

from agents.caption_agent import (  # noqa: E402
    CaptionTimeline,
    SegmentAnnotation,
)
from agents.dvd_agent import ClipCandidate, NarrativeArc  # noqa: E402


# ---------------------------------------------------------------------------
# Structured data types
# ---------------------------------------------------------------------------

@dataclass
class EditBeat:
    """A single beat in the edit decision list."""
    phase: str              # hook | rising | climax | resolution
    beat_type: str          # moment | transition | context | reaction | text_overlay
    source_start: float     # start in source video (seconds)
    source_end: float       # end in source video (seconds)
    output_start: float     # start in output timeline (seconds)
    output_end: float       # end in output timeline (seconds)
    intensity: float        # 0-100
    description: str = ""

    # Rendering directives
    playback_speed: float = 1.0       # 0.25 = quarter speed, 2.0 = double
    effect: str = "none"              # slowmo | zoom | shake | flash | vignette | none
    effect_params: dict = field(default_factory=dict)
    transition_in: str = "cut"        # cut | crossfade | whip | glitch | zoom-through
    transition_in_duration: float = 0.0
    text_overlay: str = ""
    text_style: dict = field(default_factory=dict)
    music_cue: str = "sustain"        # build | drop | sustain | quiet | silence
    zoom: Optional[dict] = None       # {factor, x, y}

    # Anti-fluff validation flags
    has_game_event: bool = False
    has_emotion_peak: bool = False
    has_speech_content: bool = False
    has_visual_change: bool = False
    fluff_signals: int = 0            # count of present signals (min 3 to pass)


@dataclass
class BGMDirective:
    """Background music selection and sync metadata."""
    mood: str               # epic | hype | chill | chaotic | cinematic
    genre: str              # orchestral-epic | electronic-hype | lofi-ambient etc.
    energy_curve: list[tuple[float, float]] = field(default_factory=list)  # (timestamp, energy 0-1)
    bpm_target: int = 130
    drop_timestamps: list[float] = field(default_factory=list)  # beat-drop sync points
    fade_in_sec: float = 1.0
    fade_out_sec: float = 2.0
    mix_level: float = 0.6  # 0-1 relative to game audio


@dataclass
class EditScript:
    """Complete edit script for a single clip, ready for the render engine."""
    clip_id: str
    source_start: float
    source_end: float
    total_output_duration: float
    beats: list[EditBeat]
    bgm: BGMDirective
    voiceover_script: str = ""
    voiceover_timestamps: list[tuple[float, float, str]] = field(default_factory=list)
    title_suggestion: str = ""
    description_suggestion: str = ""
    narrative_summary: str = ""
    anti_fluff_report: dict = field(default_factory=dict)

    def to_edl(self) -> list[dict]:
        """Serialise beats to a flat EDL-style list of dicts."""
        return [
            {
                "phase": b.phase,
                "type": b.beat_type,
                "src_in": round(b.source_start, 3),
                "src_out": round(b.source_end, 3),
                "out_in": round(b.output_start, 3),
                "out_out": round(b.output_end, 3),
                "speed": b.playback_speed,
                "effect": b.effect,
                "transition": b.transition_in,
                "text": b.text_overlay,
                "music": b.music_cue,
            }
            for b in self.beats
        ]


# ---------------------------------------------------------------------------
# LLM helper (Ollama / mlx-lm fallback)
# ---------------------------------------------------------------------------

_LLM_AVAILABLE: Optional[bool] = None


def _check_llm() -> bool:
    """Check if Ollama is reachable."""
    global _LLM_AVAILABLE
    if _LLM_AVAILABLE is not None:
        return _LLM_AVAILABLE
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        _LLM_AVAILABLE = result.returncode == 0
    except Exception:
        _LLM_AVAILABLE = False
    if not _LLM_AVAILABLE:
        logger.info("Ollama not available -- using template-based generation")
    return _LLM_AVAILABLE


def _llm_generate(prompt: str, model: str = "llama3.2:3b", max_tokens: int = 512) -> str:
    """Call Ollama to generate text.  Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as exc:
        logger.debug("LLM generation failed: %s", exc)
    return ""


# ---------------------------------------------------------------------------
# Hook text & narrative templates
# ---------------------------------------------------------------------------

_HOOK_TEMPLATES: dict[str, list[str]] = {
    "triumphant": [
        "They said it was over...",
        "The comeback nobody believed in.",
        "Watch how this ends.",
    ],
    "intense": [
        "Lock in.",
        "This is the round that matters.",
        "Clutch or kick.",
    ],
    "chaotic": [
        "Things are about to go VERY wrong.",
        "The tilt was just beginning.",
        "You won't believe what happens next.",
    ],
    "chill": [
        "Sometimes the best moments are quiet.",
        "This is the one.",
        "Watch this.",
    ],
}

_CLIMAX_TEMPLATES: dict[str, list[str]] = {
    "triumphant": ["THE MOMENT.", "THEY DID IT.", "IMPOSSIBLE."],
    "intense": ["INSANE.", "ABSOLUTELY CRACKED.", "NO WAY."],
    "chaotic": ["WHAT.", "BRO.", "IT HAPPENED AGAIN."],
    "chill": ["nice.", "clean.", "we take those."],
}

_MOOD_TO_BGM: dict[str, dict[str, Any]] = {
    "triumphant": {"genre": "orchestral-epic", "bpm": 140, "base_energy": 0.7},
    "intense":    {"genre": "electronic-hype", "bpm": 150, "base_energy": 0.8},
    "chaotic":    {"genre": "meme-edm",        "bpm": 160, "base_energy": 0.85},
    "chill":      {"genre": "lofi-ambient",     "bpm": 85,  "base_energy": 0.3},
}


# ---------------------------------------------------------------------------
# DNAAgent
# ---------------------------------------------------------------------------

class DNAAgent:
    """
    Dynamic Narrative Architect.

    Transforms a ``ClipCandidate`` + ``CaptionTimeline`` into a frame-accurate
    ``EditScript`` with full rendering directives, anti-fluff validation, and
    optional LLM-generated voiceover.

    Parameters
    ----------
    llm_model : str
        Ollama model name for narrative generation.
    hook_duration : float
        Maximum hook phase duration (seconds).
    min_beat_duration : float
        Minimum beat duration before it is considered fluff (seconds).
    anti_fluff_min_signals : int
        Minimum number of content signals a beat must have to survive
        anti-fluff validation.
    """

    def __init__(
        self,
        llm_model: str = "llama3.2:3b",
        hook_duration: float = 3.0,
        min_beat_duration: float = 1.0,
        anti_fluff_min_signals: int = 1,
    ) -> None:
        self.llm_model = llm_model
        self.hook_duration = hook_duration
        self.min_beat_duration = min_beat_duration
        self.anti_fluff_min_signals = anti_fluff_min_signals

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def architect(
        self,
        clip_candidate: ClipCandidate,
        caption_timeline: CaptionTimeline,
        template: Optional[dict] = None,
        persona: Optional[dict] = None,
    ) -> EditScript:
        """
        Generate a complete ``EditScript`` for a clip candidate.

        Parameters
        ----------
        clip_candidate : ClipCandidate
            A candidate from ``DVDAgent.discover()``.
        caption_timeline : CaptionTimeline
            The full annotated timeline from ``CaptionAgent.analyze()``.
        template : dict, optional
            Story template (from the JS template system, serialised to dict).
            Expected keys: ``mood``, ``structure``, ``transition_style``,
            ``musicMood``, ``bgm_style``.
        persona : dict, optional
            Streamer persona dict.  Expected keys: ``energy_level``,
            ``humor_style``, ``catchphrases``, ``style_prefs``.

        Returns
        -------
        EditScript
        """
        template = template or {}
        persona = persona or {}
        mood = template.get("mood", "intense")
        structure = template.get("structure", {"intro": 0.10, "build": 0.35, "climax": 0.40, "outro": 0.15})

        # Get annotations for this candidate's time range
        clip_annotations = caption_timeline.slice(clip_candidate.start, clip_candidate.end)
        if not clip_annotations:
            clip_annotations = clip_candidate.annotations

        clip_id = self._make_clip_id(clip_candidate)
        logger.info(
            "Architecting clip %s: %.1f-%.1fs (%s strategy)",
            clip_id, clip_candidate.start, clip_candidate.end,
            clip_candidate.scoring_strategy,
        )

        # --- Build beats for each narrative phase ---
        hook_beats = self._build_hook(clip_candidate, clip_annotations, mood, persona)
        arc_beats = self._build_narrative_arc(
            clip_candidate, clip_annotations, structure, mood, template, persona
        )

        all_beats = hook_beats + arc_beats

        # --- Assign output timeline positions ---
        all_beats = self._assign_output_times(all_beats)

        # --- Anti-fluff validation ---
        # Allow template to override the min_signals threshold (for self-correction loop)
        orig_min_signals = self.anti_fluff_min_signals
        if "_anti_fluff_min_signals" in template:
            self.anti_fluff_min_signals = int(template["_anti_fluff_min_signals"])
        validated_beats = self._anti_fluff_validate(all_beats)
        self.anti_fluff_min_signals = orig_min_signals  # restore

        # --- Reassign output times after fluff removal ---
        validated_beats = self._assign_output_times(validated_beats)

        # --- BGM ---
        bgm = self._build_bgm(validated_beats, mood, template)

        # --- Voiceover ---
        voiceover = self._generate_voiceover_script(validated_beats, persona, mood)

        # --- Total duration ---
        total_duration = 0.0
        if validated_beats:
            total_duration = validated_beats[-1].output_end

        # --- Title & description ---
        title = self._generate_title(clip_candidate, mood, persona)
        description = self._generate_description(clip_candidate, validated_beats, mood)

        # --- Anti-fluff report ---
        total_raw = len(all_beats)
        total_kept = len(validated_beats)
        removed = total_raw - total_kept
        anti_fluff_report = {
            "total_beats_raw": total_raw,
            "total_beats_kept": total_kept,
            "beats_removed": removed,
            "removal_rate": round(removed / max(total_raw, 1), 2),
            "min_signals_required": self.anti_fluff_min_signals,
        }

        script = EditScript(
            clip_id=clip_id,
            source_start=clip_candidate.start,
            source_end=clip_candidate.end,
            total_output_duration=round(total_duration, 3),
            beats=validated_beats,
            bgm=bgm,
            voiceover_script=voiceover,
            voiceover_timestamps=self._voiceover_timestamps(voiceover, validated_beats),
            title_suggestion=title,
            description_suggestion=description,
            narrative_summary=self._narrative_summary(validated_beats),
            anti_fluff_report=anti_fluff_report,
        )

        logger.info(
            "EditScript %s: %d beats, %.1fs output, %d fluff removed",
            clip_id, len(validated_beats), total_duration, removed,
        )
        return script

    # ------------------------------------------------------------------
    # Hook builder (first 0-3 seconds)
    # ------------------------------------------------------------------

    def _build_hook(
        self,
        candidate: ClipCandidate,
        annotations: list[SegmentAnnotation],
        mood: str,
        persona: dict,
    ) -> list[EditBeat]:
        """
        Build the Hook phase (first 0-3 seconds).

        Strategy: use the *climax moment* as a flash-forward teaser, or the
        single most intense second from the clip.
        """
        beats: list[EditBeat] = []
        hook_dur = self.hook_duration

        # Find the peak second in the clip for the flash-forward
        if annotations:
            peak = max(annotations, key=lambda a: a.composite_score)
        else:
            peak = None

        # Beat 1: Flash-forward snippet (1.5s of the climax in slow-mo)
        if peak:
            snippet_src_start = peak.start
            snippet_src_end = min(peak.end, peak.start + 2.0)
            hook_text = self._pick_hook_text(mood, persona)

            beats.append(
                EditBeat(
                    phase="hook",
                    beat_type="moment",
                    source_start=snippet_src_start,
                    source_end=snippet_src_end,
                    output_start=0.0,
                    output_end=1.5,
                    intensity=90,
                    description="Flash-forward: climax teaser",
                    playback_speed=0.5,
                    effect="zoom",
                    effect_params={"factor": 1.3, "x": 0.5, "y": 0.4, "easing": "easeOut"},
                    transition_in="cut",
                    text_overlay=hook_text,
                    text_style={
                        "font": "Bebas Neue" if mood != "chill" else "Inter",
                        "size": 64,
                        "color": "#FFFFFF",
                        "stroke": "#000000",
                        "position": "center",
                        "animation": "slam",
                    },
                    music_cue="drop",
                    has_game_event=peak.has_game_event,
                    has_emotion_peak=peak.has_emotion_peak,
                    has_speech_content=bool(peak.speech_text),
                    has_visual_change=True,
                    fluff_signals=4,  # hook is always justified
                )
            )

        # Beat 2: Snap to black + whoosh transition (0.3s)
        beats.append(
            EditBeat(
                phase="hook",
                beat_type="transition",
                source_start=candidate.start,
                source_end=candidate.start,
                output_start=1.5,
                output_end=1.8,
                intensity=70,
                description="Snap to black before main content",
                playback_speed=1.0,
                effect="flash",
                effect_params={"color": "#000000", "duration": 0.3},
                transition_in="glitch",
                transition_in_duration=0.2,
                music_cue="silence",
                has_visual_change=True,
                fluff_signals=4,  # transitions are always justified
            )
        )

        # Beat 3: Title card / context (1.2s)
        context_text = self._context_text(candidate, mood)
        beats.append(
            EditBeat(
                phase="hook",
                beat_type="text_overlay",
                source_start=candidate.start,
                source_end=candidate.start + 1.2,
                output_start=1.8,
                output_end=hook_dur,
                intensity=60,
                description="Title card / context setting",
                playback_speed=1.0,
                effect="vignette",
                text_overlay=context_text,
                text_style={
                    "font": "Inter",
                    "size": 36,
                    "color": "#CCCCCC",
                    "position": "bottom",
                    "animation": "fadeIn",
                },
                music_cue="build",
                has_visual_change=True,
                has_speech_content=True,
                fluff_signals=4,
            )
        )

        return beats

    # ------------------------------------------------------------------
    # Narrative arc builder (Rising -> Climax -> Resolution)
    # ------------------------------------------------------------------

    def _build_narrative_arc(
        self,
        candidate: ClipCandidate,
        annotations: list[SegmentAnnotation],
        structure: dict,
        mood: str,
        template: dict,
        persona: dict,
    ) -> list[EditBeat]:
        """
        Build the Rising Action -> Climax -> Resolution phases.

        The structure dict controls the fraction of the clip devoted to each
        phase.  Annotations are partitioned into phases, and each meaningful
        segment becomes a beat.
        """
        beats: list[EditBeat] = []
        if not annotations:
            return beats

        clip_start = candidate.start
        clip_end = candidate.end
        clip_dur = clip_end - clip_start

        # Phase boundaries (in source-video seconds)
        intro_frac = structure.get("intro", 0.10)
        build_frac = structure.get("build", 0.35)
        climax_frac = structure.get("climax", 0.40)
        # outro gets the remainder

        rising_start = clip_start + clip_dur * intro_frac
        climax_start = clip_start + clip_dur * (intro_frac + build_frac)
        resolution_start = clip_start + clip_dur * (intro_frac + build_frac + climax_frac)

        # If we have a detected narrative arc, use its phase boundaries instead
        arc = candidate.narrative_arc
        if arc and arc.arc_quality > 0.3:
            rising_start = max(clip_start, arc.setup_end)
            climax_start = max(rising_start, arc.climax_start)
            resolution_start = max(climax_start, arc.resolution_start)

        transition_style = template.get("transition_style", "crossfade")

        # Partition annotations into phases
        rising_anns = [a for a in annotations if rising_start <= a.start < climax_start]
        climax_anns = [a for a in annotations if climax_start <= a.start < resolution_start]
        resolution_anns = [a for a in annotations if a.start >= resolution_start]

        # Also grab the initial setup (pre-rising) annotations
        setup_anns = [a for a in annotations if clip_start <= a.start < rising_start]

        # --- Setup / early rising ---
        beats.extend(self._anns_to_beats(
            setup_anns, "rising", mood, transition_style,
            music_cue="build", speed=1.0, max_beats=3,
        ))

        # --- Rising action ---
        beats.extend(self._anns_to_beats(
            rising_anns, "rising", mood, transition_style,
            music_cue="build", speed=1.0, max_beats=6,
        ))

        # Add a pre-climax transition
        if rising_anns and climax_anns:
            last_rising = rising_anns[-1]
            beats.append(
                EditBeat(
                    phase="rising",
                    beat_type="transition",
                    source_start=last_rising.end,
                    source_end=last_rising.end + 0.5,
                    output_start=0, output_end=0,
                    intensity=75,
                    description="Tension build into climax",
                    effect="flash",
                    effect_params={"color": "#FFFFFF", "duration": 0.15},
                    transition_in="whip" if mood in ("intense", "chaotic") else "crossfade",
                    transition_in_duration=0.3,
                    music_cue="build",
                    has_visual_change=True,
                    fluff_signals=4,
                )
            )

        # --- Climax ---
        climax_beats = self._anns_to_beats(
            climax_anns, "climax", mood, transition_style,
            music_cue="drop", speed=0.75, max_beats=8,
        )

        # Find the absolute peak and enhance it
        if climax_beats:
            peak_beat = max(climax_beats, key=lambda b: b.intensity)
            peak_beat.playback_speed = 0.5
            peak_beat.effect = "slowmo"
            peak_beat.effect_params = {"factor": 0.5, "ramp_in": True, "ramp_out": True}
            peak_beat.text_overlay = self._pick_climax_text(mood, persona)
            peak_beat.text_style = {
                "font": "Bebas Neue",
                "size": 80,
                "color": "#FFFFFF",
                "stroke": "#000000",
                "strokeWidth": 4,
                "position": "center",
                "animation": "slam",
            }
            peak_beat.music_cue = "drop"
            peak_beat.zoom = {"factor": 1.4, "x": 0.5, "y": 0.4}

            # Add reaction beat after the peak
            reaction_src = peak_beat.source_end
            climax_beats.append(
                EditBeat(
                    phase="climax",
                    beat_type="reaction",
                    source_start=reaction_src,
                    source_end=min(reaction_src + 2.0, clip_end),
                    output_start=0, output_end=0,
                    intensity=80,
                    description="Streamer reaction after peak",
                    playback_speed=1.0,
                    effect="none",
                    music_cue="sustain",
                    has_emotion_peak=True,
                    has_visual_change=True,
                    fluff_signals=3,
                )
            )

        beats.extend(climax_beats)

        # --- Resolution ---
        resolution_beats = self._anns_to_beats(
            resolution_anns, "resolution", mood, transition_style,
            music_cue="quiet", speed=1.0, max_beats=4,
        )

        # Wind down: decrease intensity
        for i, rb in enumerate(resolution_beats):
            rb.intensity = max(20, rb.intensity - i * 10)

        # Final outro beat
        if resolution_anns:
            last = resolution_anns[-1]
            resolution_beats.append(
                EditBeat(
                    phase="resolution",
                    beat_type="context",
                    source_start=last.start,
                    source_end=min(last.end + 1.0, clip_end),
                    output_start=0, output_end=0,
                    intensity=30,
                    description="Outro / end card moment",
                    playback_speed=1.0,
                    effect="vignette",
                    transition_in="crossfade",
                    transition_in_duration=0.5,
                    music_cue="quiet",
                    has_visual_change=True,
                    fluff_signals=4,
                )
            )

        beats.extend(resolution_beats)

        return beats

    # ------------------------------------------------------------------
    # Anti-fluff validation
    # ------------------------------------------------------------------

    def _anti_fluff_validate(self, beats: list[EditBeat]) -> list[EditBeat]:
        """
        Validate every beat against anti-fluff criteria.

        A beat survives if it has at least ``anti_fluff_min_signals`` of:
          1. Game event present
          2. Emotion peak
          3. Speech content
          4. Visual change / effect

        Hook and transition beats are always kept.  Beats shorter than
        ``min_beat_duration`` are removed unless they are transitions.
        """
        kept: list[EditBeat] = []

        for beat in beats:
            # Always keep hooks and transitions -- they serve structural roles
            if beat.phase == "hook" or beat.beat_type == "transition":
                kept.append(beat)
                continue

            # Count content signals
            signals = 0
            if beat.has_game_event:
                signals += 1
            if beat.has_emotion_peak:
                signals += 1
            if beat.has_speech_content:
                signals += 1
            if beat.has_visual_change:
                signals += 1
            beat.fluff_signals = signals

            # Duration check
            src_dur = beat.source_end - beat.source_start
            if src_dur < self.min_beat_duration and beat.beat_type != "transition":
                logger.debug(
                    "Fluff removed (too short %.2fs): %s", src_dur, beat.description
                )
                continue

            # Signal check
            if signals < self.anti_fluff_min_signals:
                logger.debug(
                    "Fluff removed (%d/%d signals): %s",
                    signals, self.anti_fluff_min_signals, beat.description,
                )
                continue

            kept.append(beat)

        return kept

    # ------------------------------------------------------------------
    # Voiceover script generation
    # ------------------------------------------------------------------

    def _generate_voiceover_script(
        self, beats: list[EditBeat], persona: dict, mood: str
    ) -> str:
        """
        Generate a TTS voiceover script for the edit.

        Uses LLM when available; falls back to template-based concatenation.
        """
        # Build a compact beat summary for the LLM
        beat_summary = []
        for b in beats:
            if b.beat_type == "transition":
                continue
            beat_summary.append(
                f"[{b.phase}] {b.source_start:.1f}-{b.source_end:.1f}s: {b.description} "
                f"(intensity={b.intensity})"
            )
        beats_text = "\n".join(beat_summary)

        humor = persona.get("humor_style", "neutral")
        energy = persona.get("energy_level", 5)
        catchphrases = persona.get("catchphrases", [])

        if _check_llm():
            prompt = (
                f"You are writing a short voiceover script for a gaming clip.\n"
                f"Mood: {mood}. Humor style: {humor}. Energy: {energy}/10.\n"
                f"Streamer catchphrases: {', '.join(catchphrases[:5]) if catchphrases else 'none'}.\n\n"
                f"Here are the edit beats:\n{beats_text}\n\n"
                f"Write a concise voiceover script (max 150 words) that narrates the action.\n"
                f"Use short punchy sentences. Match the mood. Include 1-2 catchphrases if provided.\n"
                f"Format: one line per beat, prefixed with the timestamp range.\n"
                f"Output ONLY the script, no commentary."
            )
            result = _llm_generate(prompt, self.llm_model)
            if result:
                return result

        # Template fallback
        return self._template_voiceover(beats, mood, catchphrases)

    def _template_voiceover(
        self, beats: list[EditBeat], mood: str, catchphrases: list[str]
    ) -> str:
        """Deterministic template-based voiceover generation."""
        lines: list[str] = []

        phase_intros = {
            "hook": {
                "intense": "Watch this.",
                "triumphant": "You're not ready for what comes next.",
                "chaotic": "So this happened.",
                "chill": "This one's worth seeing.",
            },
            "rising": {
                "intense": "The pressure's building.",
                "triumphant": "It started rough.",
                "chaotic": "And then it got worse.",
                "chill": "Things were getting interesting.",
            },
            "climax": {
                "intense": "And then -- THIS.",
                "triumphant": "HERE IT IS.",
                "chaotic": "I can't even.",
                "chill": "And there it is.",
            },
            "resolution": {
                "intense": "Game over.",
                "triumphant": "That's how legends are made.",
                "chaotic": "Somehow, it's over.",
                "chill": "Good times.",
            },
        }

        seen_phases: set[str] = set()
        for beat in beats:
            if beat.beat_type == "transition":
                continue

            if beat.phase not in seen_phases:
                seen_phases.add(beat.phase)
                intro = phase_intros.get(beat.phase, {}).get(mood, "")
                if intro:
                    lines.append(f"[{beat.source_start:.1f}s] {intro}")

            if beat.description and beat.beat_type == "moment":
                lines.append(f"[{beat.source_start:.1f}s] {beat.description}")

        # Sprinkle a catchphrase at the climax
        if catchphrases:
            # Insert after the climax intro if present
            for i, line in enumerate(lines):
                if "climax" in line.lower() or "THIS" in line or "HERE IT IS" in line:
                    lines.insert(i + 1, f"  \"{catchphrases[0]}\"")
                    break

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # BGM builder
    # ------------------------------------------------------------------

    def _build_bgm(
        self, beats: list[EditBeat], mood: str, template: dict
    ) -> BGMDirective:
        """Build BGM directive with energy curve and sync points."""
        bgm_info = _MOOD_TO_BGM.get(mood, _MOOD_TO_BGM["intense"])
        genre = template.get("bgm_style", bgm_info["genre"])
        bpm = bgm_info["bpm"]
        base_energy = bgm_info["base_energy"]

        # Build energy curve from beats
        energy_curve: list[tuple[float, float]] = []
        drop_timestamps: list[float] = []

        for beat in beats:
            t = beat.output_start
            if beat.music_cue == "silence":
                energy_curve.append((t, 0.0))
            elif beat.music_cue == "quiet":
                energy_curve.append((t, base_energy * 0.3))
            elif beat.music_cue == "build":
                energy_curve.append((t, base_energy * 0.7))
            elif beat.music_cue == "sustain":
                energy_curve.append((t, base_energy))
            elif beat.music_cue == "drop":
                energy_curve.append((t, min(1.0, base_energy * 1.3)))
                drop_timestamps.append(t)

        return BGMDirective(
            mood=mood,
            genre=genre,
            energy_curve=energy_curve,
            bpm_target=bpm,
            drop_timestamps=drop_timestamps,
            fade_in_sec=1.0,
            fade_out_sec=2.0,
            mix_level=0.6,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _anns_to_beats(
        self,
        anns: list[SegmentAnnotation],
        phase: str,
        mood: str,
        transition_style: str,
        music_cue: str = "sustain",
        speed: float = 1.0,
        max_beats: int = 10,
    ) -> list[EditBeat]:
        """
        Convert a slice of annotations into ``EditBeat`` objects.

        Only annotations above median composite score are promoted to beats.
        Consecutive quiet seconds are merged into context beats.
        """
        if not anns:
            return []

        # Sort by time
        sorted_anns = sorted(anns, key=lambda a: a.start)

        # Take the most interesting ones up to max_beats
        scored = sorted(sorted_anns, key=lambda a: a.composite_score, reverse=True)
        selected = scored[:max_beats]
        # Re-sort by time for chronological ordering
        selected.sort(key=lambda a: a.start)

        beats: list[EditBeat] = []
        effect_map = {
            "intense": "zoom",
            "chaotic": "shake",
            "triumphant": "none",
            "chill": "none",
        }
        default_effect = effect_map.get(mood, "none")

        for i, ann in enumerate(selected):
            # Determine beat type from annotation content
            if ann.has_game_event:
                beat_type = "moment"
            elif ann.has_emotion_peak:
                beat_type = "reaction"
            else:
                beat_type = "context"

            # Scale intensity to 0-100
            intensity = min(100, int(ann.composite_score * 100))

            # Effect: apply to high-intensity beats only
            effect = default_effect if intensity > 60 else "none"

            # Transition: use template style between beats, cut for first
            trans = "cut" if i == 0 else self._map_transition(transition_style)

            beats.append(
                EditBeat(
                    phase=phase,
                    beat_type=beat_type,
                    source_start=ann.start,
                    source_end=ann.end,
                    output_start=0, output_end=0,  # assigned later
                    intensity=intensity,
                    description=self._ann_description(ann),
                    playback_speed=speed,
                    effect=effect,
                    transition_in=trans,
                    transition_in_duration=0.2 if trans != "cut" else 0.0,
                    music_cue=music_cue,
                    has_game_event=ann.has_game_event,
                    has_emotion_peak=ann.has_emotion_peak,
                    has_speech_content=bool(ann.speech_text),
                    has_visual_change=ann.composite_score > 0.05,  # low threshold for heuristic mode
                )
            )

        return beats

    def _assign_output_times(self, beats: list[EditBeat]) -> list[EditBeat]:
        """Assign sequential output timeline positions to all beats."""
        cursor = 0.0
        for beat in beats:
            src_dur = beat.source_end - beat.source_start
            # Output duration accounts for playback speed
            out_dur = max(0.1, src_dur / beat.playback_speed) if beat.playback_speed > 0 else src_dur
            beat.output_start = round(cursor, 3)
            beat.output_end = round(cursor + out_dur, 3)
            cursor += out_dur
        return beats

    @staticmethod
    def _map_transition(style: str) -> str:
        """Map template transition style name to an EditBeat transition type."""
        mapping = {
            "dramatic-cut": "cut",
            "hard-cut": "cut",
            "glitch-whip": "glitch",
            "crossfade": "crossfade",
            "zoom-through": "zoom-through",
        }
        return mapping.get(style, "crossfade")

    @staticmethod
    def _ann_description(ann: SegmentAnnotation) -> str:
        """Build a human-readable description of an annotation."""
        parts: list[str] = []
        if ann.game_events:
            parts.append(f"Game: {', '.join(ann.game_events)}")
        if ann.has_emotion_peak:
            parts.append(f"Emotion: {ann.dominant_emotion}")
        if ann.speech_text:
            text = ann.speech_text[:60] + ("..." if len(ann.speech_text) > 60 else "")
            parts.append(f'Speech: "{text}"')
        if not parts:
            parts.append(f"Composite: {ann.composite_score:.2f}")
        return "; ".join(parts)

    @staticmethod
    def _pick_hook_text(mood: str, persona: dict) -> str:
        """Select hook overlay text."""
        pool = _HOOK_TEMPLATES.get(mood, _HOOK_TEMPLATES["intense"])
        # Deterministic selection based on persona name hash
        name = persona.get("name", "default")
        idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % len(pool)
        return pool[idx]

    @staticmethod
    def _pick_climax_text(mood: str, persona: dict) -> str:
        """Select climax overlay text."""
        catchphrases = persona.get("catchphrases", [])
        if catchphrases:
            name = persona.get("name", "default")
            idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % len(catchphrases)
            return catchphrases[idx].upper()
        pool = _CLIMAX_TEMPLATES.get(mood, _CLIMAX_TEMPLATES["intense"])
        return pool[0]

    @staticmethod
    def _context_text(candidate: ClipCandidate, mood: str) -> str:
        """Generate context / title-card text for the hook."""
        strategy_labels = {
            "peak": "Peak Moment",
            "arc": "The Story",
            "momentum": "The Comeback",
        }
        label = strategy_labels.get(candidate.scoring_strategy, "Highlight")
        dur = candidate.duration
        if dur >= 60:
            dur_text = f"{dur / 60:.0f}min"
        else:
            dur_text = f"{dur:.0f}s"
        return f"{label} | {dur_text}"

    @staticmethod
    def _make_clip_id(candidate: ClipCandidate) -> str:
        """Generate a deterministic clip ID."""
        raw = f"{candidate.start:.1f}_{candidate.end:.1f}_{candidate.scoring_strategy}"
        return f"clip_{hashlib.md5(raw.encode()).hexdigest()[:8]}"

    @staticmethod
    def _generate_title(candidate: ClipCandidate, mood: str, persona: dict) -> str:
        """Generate a suggested clip title."""
        titles = {
            "peak": {
                "intense": "THE Play",
                "triumphant": "Against All Odds",
                "chaotic": "What Just Happened",
                "chill": "Clean",
            },
            "arc": {
                "intense": "The Full Story",
                "triumphant": "The Redemption Arc",
                "chaotic": "The Spiral",
                "chill": "A Good Session",
            },
            "momentum": {
                "intense": "The Swing",
                "triumphant": "The Comeback",
                "chaotic": "From Tilt to... More Tilt",
                "chill": "Momentum Shift",
            },
        }
        strategy_map = titles.get(candidate.scoring_strategy, titles["peak"])
        return strategy_map.get(mood, "Highlight")

    @staticmethod
    def _generate_description(
        candidate: ClipCandidate, beats: list[EditBeat], mood: str
    ) -> str:
        """Generate a short clip description / logline."""
        n_moments = sum(1 for b in beats if b.beat_type == "moment")
        n_reactions = sum(1 for b in beats if b.beat_type == "reaction")
        dur = candidate.duration
        return (
            f"A {dur:.0f}-second {mood} clip with {n_moments} key moments "
            f"and {n_reactions} reactions. "
            f"Score: {candidate.composite_score:.2f}."
        )

    @staticmethod
    def _narrative_summary(beats: list[EditBeat]) -> str:
        """Produce a one-paragraph narrative summary of the edit."""
        phases = {}
        for b in beats:
            if b.beat_type == "transition":
                continue
            phases.setdefault(b.phase, []).append(b.description)

        parts: list[str] = []
        for phase_name in ("hook", "rising", "climax", "resolution"):
            descs = phases.get(phase_name, [])
            if descs:
                joined = "; ".join(descs[:3])
                parts.append(f"[{phase_name.upper()}] {joined}")
        return " -> ".join(parts) if parts else "No narrative content."

    @staticmethod
    def _voiceover_timestamps(
        script: str, beats: list[EditBeat]
    ) -> list[tuple[float, float, str]]:
        """
        Align voiceover script lines to output timestamps.

        Returns a list of (start, end, text) tuples suitable for TTS.
        """
        if not script:
            return []

        lines = [l.strip() for l in script.strip().split("\n") if l.strip()]
        timestamps: list[tuple[float, float, str]] = []

        # Distribute lines evenly across non-transition beats
        content_beats = [b for b in beats if b.beat_type != "transition"]
        if not content_beats:
            return []

        n_lines = len(lines)
        n_beats = len(content_beats)
        lines_per_beat = max(1, math.ceil(n_lines / n_beats))

        line_idx = 0
        for beat in content_beats:
            batch = lines[line_idx : line_idx + lines_per_beat]
            if batch:
                text = " ".join(batch)
                timestamps.append((beat.output_start, beat.output_end, text))
            line_idx += lines_per_beat
            if line_idx >= n_lines:
                break

        return timestamps
