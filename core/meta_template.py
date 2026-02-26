"""
Kairo Meta-Template Engine -- Reusable editing pattern extraction and matching.

A meta-template encodes the *winning formula* of a successful edit as two
orthogonal components:

  - **Process**: HOW to edit -- pacing curve, transition patterns, effect
    placement rules, phase proportions, music sync strategy.
  - **Tags**: WHAT to select -- content signal thresholds, game event
    priorities, emotion weights, audience engagement filters.

When a streamer's video performs well (high views, high engagement), the
system extracts its editing pattern as a meta-template.  Future videos
of similar content are then edited using that template, preserving the
*structure* that worked while adapting to new *content*.

Lifecycle:
    1. Streamer publishes a clip that gets great engagement.
    2. ``extract_template()`` distills its EditScript into a MetaTemplate.
    3. Next time similar content arrives, ``match_template()`` finds it.
    4. ``adapt_template()`` applies the template to the new CaptionTimeline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("kairo.meta_template")

WORKSPACE = Path(__file__).parent.parent
TEMPLATES_DIR = WORKSPACE / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Import shared types
# ---------------------------------------------------------------------------

from agents.caption_agent import CaptionTimeline, SegmentAnnotation  # noqa: E402
from agents.dna_agent import EditBeat, EditScript, BGMDirective      # noqa: E402


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PacingCurve:
    """Normalized pacing curve across the edit's output timeline.

    Each entry is ``(normalized_position, speed)`` where
    *normalized_position* is in [0.0, 1.0] (start to end of edit) and
    *speed* is the playback speed at that point.
    """
    points: list[tuple[float, float]] = field(default_factory=list)

    def speed_at(self, t_norm: float) -> float:
        """Interpolate speed at normalized position *t_norm*."""
        if not self.points:
            return 1.0
        if t_norm <= self.points[0][0]:
            return self.points[0][1]
        if t_norm >= self.points[-1][0]:
            return self.points[-1][1]
        for i in range(len(self.points) - 1):
            t0, s0 = self.points[i]
            t1, s1 = self.points[i + 1]
            if t0 <= t_norm <= t1:
                alpha = (t_norm - t0) / max(t1 - t0, 1e-9)
                return s0 + alpha * (s1 - s0)
        return 1.0


@dataclass
class TransitionPattern:
    """Describes a recurring transition placement rule."""
    from_phase: str          # phase before transition
    to_phase: str            # phase after transition
    transition_type: str     # cut | crossfade | whip | glitch | zoom-through
    duration: float = 0.0
    frequency: float = 0.0   # how often this pattern appears (0-1)


@dataclass
class EffectPlacementRule:
    """When and how to place a specific effect."""
    effect_type: str         # slowmo | zoom | shake | flash | vignette
    trigger: str             # on_peak | on_game_event | on_emotion_peak | always
    phase: str               # hook | rising | climax | resolution | any
    min_intensity: float     # minimum beat intensity (0-100) to trigger
    params: dict = field(default_factory=dict)


@dataclass
class ContentFilter:
    """Thresholds for content selection (the Tags component)."""
    game_event_priority: dict = field(default_factory=lambda: {
        "kill": 1.0, "death": 0.6, "objective": 0.8,
        "ability": 0.4, "score_change": 0.5,
    })
    min_composite_score: float = 0.25
    min_emotion_intensity: float = 0.3
    min_game_intensity: float = 0.2
    audience_weight: float = 0.25
    emotion_weight: float = 0.40
    game_weight: float = 0.35
    prefer_narrative_arcs: bool = True
    arc_quality_threshold: float = 0.3


@dataclass
class MetaTemplate:
    """
    A complete reusable editing pattern extracted from a successful video.

    Combines Process (structural) and Tags (selection) components.
    """
    template_id: str
    name: str = ""
    source_clip_id: str = ""
    created_from_engagement: dict = field(default_factory=dict)

    # --- Process: HOW to edit ---
    phase_proportions: dict = field(default_factory=lambda: {
        "hook": 0.08, "rising": 0.30, "climax": 0.42, "resolution": 0.20,
    })
    pacing_curve: PacingCurve = field(default_factory=PacingCurve)
    transition_patterns: list[TransitionPattern] = field(default_factory=list)
    effect_rules: list[EffectPlacementRule] = field(default_factory=list)
    bgm_mood: str = "intense"
    bgm_genre: str = "electronic-hype"
    bgm_energy_profile: list[tuple[float, float]] = field(default_factory=list)
    target_duration_range: tuple[float, float] = (30.0, 90.0)
    beats_per_minute_target: int = 130
    hook_strategy: str = "flash_forward"  # flash_forward | cold_open | text_tease
    anti_fluff_min_signals: int = 2

    # --- Tags: WHAT to select ---
    content_filter: ContentFilter = field(default_factory=ContentFilter)

    # --- Metadata ---
    mood: str = "intense"
    content_tags: list[str] = field(default_factory=list)
    win_rate: float = 0.0      # fraction of times this template led to good results
    usage_count: int = 0
    avg_rating: float = 0.0
    created_at: str = ""

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return _deep_serialize(asdict(self))

    @classmethod
    def from_dict(cls, data: dict) -> "MetaTemplate":
        """Reconstruct from a serialized dict."""
        # Reconstruct nested dataclasses
        pacing_data = data.pop("pacing_curve", {})
        pacing = PacingCurve(
            points=[tuple(p) for p in pacing_data.get("points", [])]
        )

        tp_data = data.pop("transition_patterns", [])
        transition_patterns = [
            TransitionPattern(**{k: v for k, v in tp.items()
                                 if k in TransitionPattern.__dataclass_fields__})
            for tp in tp_data
        ]

        er_data = data.pop("effect_rules", [])
        effect_rules = [
            EffectPlacementRule(**{k: v for k, v in er.items()
                                  if k in EffectPlacementRule.__dataclass_fields__})
            for er in er_data
        ]

        cf_data = data.pop("content_filter", {})
        content_filter = ContentFilter(**{
            k: v for k, v in cf_data.items()
            if k in ContentFilter.__dataclass_fields__
        })

        # Convert target_duration_range from list to tuple if needed
        tdr = data.get("target_duration_range", [30.0, 90.0])
        if isinstance(tdr, list):
            data["target_duration_range"] = tuple(tdr)

        # Convert bgm_energy_profile entries to tuples
        bep = data.get("bgm_energy_profile", [])
        data["bgm_energy_profile"] = [tuple(p) for p in bep]

        return cls(
            pacing_curve=pacing,
            transition_patterns=transition_patterns,
            effect_rules=effect_rules,
            content_filter=content_filter,
            **{k: v for k, v in data.items() if k in cls.__dataclass_fields__
               and k not in ("pacing_curve", "transition_patterns",
                             "effect_rules", "content_filter")},
        )


# ---------------------------------------------------------------------------
# MetaTemplateEngine
# ---------------------------------------------------------------------------

class MetaTemplateEngine:
    """
    Extracts reusable editing patterns from high-VV (high view count) videos.

    Usage::

        engine = MetaTemplateEngine()

        # After a video performs well:
        meta = engine.extract_template(edit_script, {"views": 500000, "likes": 25000})

        # For new content:
        best = engine.match_template(caption_timeline, engine.list_templates())

        # Apply it:
        new_script = engine.adapt_template(best, caption_timeline)
    """

    def __init__(self, templates_dir: Optional[str] = None) -> None:
        self._templates_dir = Path(templates_dir) if templates_dir else TEMPLATES_DIR
        self._templates_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, MetaTemplate] = {}

    # ------------------------------------------------------------------
    # Extract: distill a successful edit into a reusable template
    # ------------------------------------------------------------------

    def extract_template(
        self,
        edit_script: EditScript,
        engagement_metrics: dict,
    ) -> MetaTemplate:
        """
        Extract a reusable ``MetaTemplate`` from a successful edit.

        Analyzes the structure of *edit_script* -- phase proportions, pacing
        curve, transition and effect patterns -- and encodes them as rules
        that can be re-applied to new content.

        Parameters
        ----------
        edit_script : EditScript
            The edit script from a successful video.
        engagement_metrics : dict
            Engagement data: ``views``, ``likes``, ``shares``, ``comments``,
            ``avg_watch_time``, ``completion_rate``.

        Returns
        -------
        MetaTemplate
        """
        beats = edit_script.beats
        if not beats:
            logger.warning("Cannot extract template from empty EditScript")
            return MetaTemplate(template_id=_generate_id("empty"))

        total_duration = edit_script.total_output_duration or sum(
            b.output_end - b.output_start for b in beats
        )
        if total_duration <= 0:
            total_duration = sum(
                (b.source_end - b.source_start) / max(b.playback_speed, 0.1)
                for b in beats
            )

        template_id = _generate_id(edit_script.clip_id)
        logger.info(
            "Extracting meta-template from clip %s (%.1fs, %d beats)",
            edit_script.clip_id, total_duration, len(beats),
        )

        # --- Phase proportions ---
        phase_durations: dict[str, float] = {}
        for beat in beats:
            dur = beat.output_end - beat.output_start
            if dur <= 0:
                dur = (beat.source_end - beat.source_start) / max(beat.playback_speed, 0.1)
            phase_durations[beat.phase] = phase_durations.get(beat.phase, 0.0) + dur

        phase_proportions = {}
        for phase, dur in phase_durations.items():
            phase_proportions[phase] = round(dur / max(total_duration, 1e-6), 4)

        # Ensure all standard phases exist
        for phase in ("hook", "rising", "climax", "resolution"):
            phase_proportions.setdefault(phase, 0.0)

        # --- Pacing curve ---
        pacing_points: list[tuple[float, float]] = []
        cursor = 0.0
        for beat in beats:
            t_norm = cursor / max(total_duration, 1e-6)
            pacing_points.append((round(t_norm, 4), beat.playback_speed))
            dur = beat.output_end - beat.output_start
            if dur <= 0:
                dur = (beat.source_end - beat.source_start) / max(beat.playback_speed, 0.1)
            cursor += dur
        pacing_curve = PacingCurve(points=pacing_points)

        # --- Transition patterns ---
        transition_counts: dict[tuple[str, str, str], int] = {}
        for i in range(len(beats) - 1):
            key = (beats[i].phase, beats[i + 1].phase, beats[i + 1].transition_in)
            transition_counts[key] = transition_counts.get(key, 0) + 1

        total_transitions = max(sum(transition_counts.values()), 1)
        transition_patterns = []
        for (from_p, to_p, tr_type), count in transition_counts.items():
            transition_patterns.append(TransitionPattern(
                from_phase=from_p,
                to_phase=to_p,
                transition_type=tr_type,
                frequency=round(count / total_transitions, 4),
            ))

        # --- Effect placement rules ---
        effect_rules: list[EffectPlacementRule] = []
        seen_effects: set[tuple[str, str, str]] = set()

        for beat in beats:
            if beat.effect == "none":
                continue
            # Determine trigger heuristic
            trigger = "always"
            if beat.has_game_event:
                trigger = "on_game_event"
            elif beat.has_emotion_peak:
                trigger = "on_emotion_peak"
            elif beat.intensity >= 70:
                trigger = "on_peak"

            key = (beat.effect, trigger, beat.phase)
            if key not in seen_effects:
                seen_effects.add(key)
                effect_rules.append(EffectPlacementRule(
                    effect_type=beat.effect,
                    trigger=trigger,
                    phase=beat.phase,
                    min_intensity=beat.intensity,
                    params=beat.effect_params or {},
                ))

        # --- BGM profile ---
        bgm = edit_script.bgm
        bgm_mood = bgm.mood if bgm else "intense"
        bgm_genre = bgm.genre if bgm else "electronic-hype"
        bgm_energy_profile: list[tuple[float, float]] = []
        if bgm and bgm.energy_curve:
            for t, e in bgm.energy_curve:
                t_norm = t / max(total_duration, 1e-6)
                bgm_energy_profile.append((round(t_norm, 4), round(e, 4)))

        # --- Hook strategy detection ---
        hook_beats = [b for b in beats if b.phase == "hook"]
        hook_strategy = "flash_forward"
        if hook_beats:
            first_hook = hook_beats[0]
            if first_hook.text_overlay and not first_hook.has_game_event:
                hook_strategy = "text_tease"
            elif first_hook.beat_type == "moment" and first_hook.effect == "zoom":
                hook_strategy = "flash_forward"
            else:
                hook_strategy = "cold_open"

        # --- Content filter from anti-fluff report ---
        afr = edit_script.anti_fluff_report or {}
        anti_fluff_min = afr.get("min_signals_required", 2)

        # --- Duration range ---
        dur_min = max(15.0, total_duration * 0.75)
        dur_max = total_duration * 1.25

        # --- Engagement-based naming ---
        views = engagement_metrics.get("views", 0)
        name = f"meta_{edit_script.clip_id[:8]}"
        if views >= 1_000_000:
            name = f"viral_{name}"
        elif views >= 100_000:
            name = f"hit_{name}"

        template = MetaTemplate(
            template_id=template_id,
            name=name,
            source_clip_id=edit_script.clip_id,
            created_from_engagement=engagement_metrics,
            phase_proportions=phase_proportions,
            pacing_curve=pacing_curve,
            transition_patterns=transition_patterns,
            effect_rules=effect_rules,
            bgm_mood=bgm_mood,
            bgm_genre=bgm_genre,
            bgm_energy_profile=bgm_energy_profile,
            target_duration_range=(dur_min, dur_max),
            beats_per_minute_target=bgm.bpm_target if bgm else 130,
            hook_strategy=hook_strategy,
            anti_fluff_min_signals=anti_fluff_min,
            content_filter=ContentFilter(),
            mood=bgm_mood,
            content_tags=[],
            win_rate=1.0,
            usage_count=1,
            avg_rating=5.0,
        )

        self._save_template(template)
        logger.info(
            "Extracted meta-template %s: phases=%s, %d transition patterns, %d effect rules",
            template_id, phase_proportions, len(transition_patterns), len(effect_rules),
        )
        return template

    # ------------------------------------------------------------------
    # Match: find the best template for new content
    # ------------------------------------------------------------------

    def match_template(
        self,
        caption_timeline: CaptionTimeline,
        available_templates: list[MetaTemplate],
    ) -> Optional[MetaTemplate]:
        """
        Find the best matching meta-template for new content.

        Scoring considers:
        - Content similarity (mood, intensity profile, event density)
        - Duration compatibility
        - Template success rate (win_rate, avg_rating)

        Parameters
        ----------
        caption_timeline : CaptionTimeline
            The annotated timeline of the new video.
        available_templates : list[MetaTemplate]
            Pool of candidate templates.

        Returns
        -------
        MetaTemplate or None
            The best matching template, or None if no templates are available.
        """
        if not available_templates:
            logger.info("No templates available for matching")
            return None

        annotations = caption_timeline.annotations
        if not annotations:
            logger.warning("Empty timeline -- returning first available template")
            return available_templates[0]

        # Analyze content characteristics
        content_profile = self._analyze_content_profile(annotations)
        logger.info(
            "Content profile: mood=%s, intensity=%.2f, event_density=%.2f",
            content_profile["dominant_mood"],
            content_profile["mean_intensity"],
            content_profile["event_density"],
        )

        best_template: Optional[MetaTemplate] = None
        best_score = -1.0

        for template in available_templates:
            score = self._compute_match_score(template, content_profile, caption_timeline)
            if score > best_score:
                best_score = score
                best_template = template

        if best_template:
            logger.info(
                "Best matching template: %s (score=%.3f)",
                best_template.template_id, best_score,
            )

        return best_template

    # ------------------------------------------------------------------
    # Adapt: apply a template to new content
    # ------------------------------------------------------------------

    def adapt_template(
        self,
        template: MetaTemplate,
        new_content: CaptionTimeline,
        candidate_start: float = 0.0,
        candidate_end: Optional[float] = None,
    ) -> dict:
        """
        Adapt a meta-template to new content while preserving its winning patterns.

        Returns a configuration dict that the DNAAgent can use as its
        ``template`` parameter -- containing mood, structure (phase
        proportions), transition style, BGM preferences, and content
        selection thresholds.

        Parameters
        ----------
        template : MetaTemplate
            The meta-template to adapt.
        new_content : CaptionTimeline
            The annotated timeline for the new video.
        candidate_start : float
            Start time of the clip window in the source video.
        candidate_end : float or None
            End time of the clip window.  Defaults to timeline duration.

        Returns
        -------
        dict
            Template configuration dict compatible with ``DNAAgent.architect(template=...)``.
        """
        if candidate_end is None:
            candidate_end = new_content.duration_sec

        clip_duration = candidate_end - candidate_start
        target_min, target_max = template.target_duration_range
        target_duration = max(target_min, min(target_max, clip_duration))

        # Determine the dominant transition style from patterns
        transition_style = "crossfade"
        if template.transition_patterns:
            # Pick the most frequent non-cut transition
            non_cuts = [tp for tp in template.transition_patterns
                        if tp.transition_type != "cut"]
            if non_cuts:
                best_tp = max(non_cuts, key=lambda tp: tp.frequency)
                transition_style = best_tp.transition_type
            else:
                transition_style = "dramatic-cut"

        # Map transition types to the format DNA agent expects
        transition_map = {
            "crossfade": "crossfade",
            "whip": "glitch-whip",
            "glitch": "glitch-whip",
            "zoom-through": "zoom-through",
            "cut": "dramatic-cut",
        }
        transition_style = transition_map.get(transition_style, transition_style)

        # Build the adapted configuration
        adapted_config = {
            "mood": template.mood,
            "structure": dict(template.phase_proportions),
            "transition_style": transition_style,
            "musicMood": template.bgm_mood,
            "bgm_style": template.bgm_genre,
            "hook_strategy": template.hook_strategy,
            "target_duration": target_duration,
            "anti_fluff_min_signals": template.anti_fluff_min_signals,
            "content_filter": {
                "min_composite_score": template.content_filter.min_composite_score,
                "min_emotion_intensity": template.content_filter.min_emotion_intensity,
                "min_game_intensity": template.content_filter.min_game_intensity,
                "game_weight": template.content_filter.game_weight,
                "emotion_weight": template.content_filter.emotion_weight,
                "audience_weight": template.content_filter.audience_weight,
            },
            "pacing_guidance": self._generate_pacing_guidance(
                template.pacing_curve, target_duration
            ),
            "effect_guidance": [
                {
                    "effect": rule.effect_type,
                    "trigger": rule.trigger,
                    "phase": rule.phase,
                    "min_intensity": rule.min_intensity,
                    "params": rule.params,
                }
                for rule in template.effect_rules
            ],
            # Metadata for tracking
            "_meta_template_id": template.template_id,
            "_meta_template_name": template.name,
        }

        logger.info(
            "Adapted template %s for %.1fs clip: mood=%s, transition=%s",
            template.template_id, target_duration, template.mood, transition_style,
        )
        return adapted_config

    # ------------------------------------------------------------------
    # Template persistence
    # ------------------------------------------------------------------

    def list_templates(self) -> list[MetaTemplate]:
        """Load and return all saved meta-templates."""
        templates: list[MetaTemplate] = []
        for path in sorted(self._templates_dir.glob("meta_*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                template = MetaTemplate.from_dict(data)
                self._cache[template.template_id] = template
                templates.append(template)
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning("Failed to load template from %s: %s", path, e)
        return templates

    def get_template(self, template_id: str) -> Optional[MetaTemplate]:
        """Load a specific template by ID."""
        if template_id in self._cache:
            return self._cache[template_id]
        path = self._templates_dir / f"meta_{template_id}.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                template = MetaTemplate.from_dict(data)
                self._cache[template_id] = template
                return template
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning("Failed to load template %s: %s", template_id, e)
        return None

    def _save_template(self, template: MetaTemplate) -> None:
        """Persist a meta-template to disk."""
        self._cache[template.template_id] = template
        path = self._templates_dir / f"meta_{template.template_id}.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(template.to_dict(), f, indent=2, ensure_ascii=False)
            logger.debug("Saved meta-template %s to %s", template.template_id, path)
        except OSError as e:
            logger.error("Failed to save meta-template: %s", e)

    def update_template_stats(
        self,
        template_id: str,
        rating: float,
        engagement: Optional[dict] = None,
    ) -> None:
        """Update a template's success statistics after usage."""
        template = self.get_template(template_id)
        if not template:
            logger.warning("Template %s not found for stats update", template_id)
            return

        # Update running averages
        old_count = template.usage_count
        template.usage_count = old_count + 1
        template.avg_rating = (
            (template.avg_rating * old_count + rating) / template.usage_count
        )

        # Win rate: rating >= 4 counts as a win
        wins = template.win_rate * old_count
        if rating >= 4.0:
            wins += 1
        template.win_rate = wins / template.usage_count

        self._save_template(template)

    # ------------------------------------------------------------------
    # Content analysis helpers
    # ------------------------------------------------------------------

    def _analyze_content_profile(
        self,
        annotations: list[SegmentAnnotation],
    ) -> dict:
        """Analyze content characteristics from timeline annotations."""
        composites = [a.composite_score for a in annotations]
        game_intensities = [a.game_intensity for a in annotations]
        emotion_intensities = [a.emotion_intensity for a in annotations]

        n = len(annotations)
        n_game_events = sum(1 for a in annotations if a.has_game_event)
        n_emotion_peaks = sum(1 for a in annotations if a.has_emotion_peak)
        n_audience_spikes = sum(1 for a in annotations if a.has_audience_spike)

        # Determine dominant mood from emotion distribution
        emotion_counts: dict[str, int] = {}
        for a in annotations:
            emotion_counts[a.dominant_emotion] = emotion_counts.get(
                a.dominant_emotion, 0
            ) + 1
        dominant_mood = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral"

        # Map emotions to template moods
        mood_map = {
            "excitement": "intense",
            "frustration": "chaotic",
            "surprise": "intense",
            "calm": "chill",
            "neutral": "chill",
        }
        template_mood = mood_map.get(dominant_mood, "intense")

        return {
            "dominant_mood": template_mood,
            "dominant_emotion": dominant_mood,
            "mean_intensity": statistics.mean(composites) if composites else 0.0,
            "peak_intensity": max(composites) if composites else 0.0,
            "intensity_std": statistics.stdev(composites) if len(composites) > 1 else 0.0,
            "event_density": n_game_events / max(n, 1),
            "emotion_peak_density": n_emotion_peaks / max(n, 1),
            "audience_spike_density": n_audience_spikes / max(n, 1),
            "game_dominant": statistics.mean(game_intensities) > statistics.mean(emotion_intensities)
            if game_intensities and emotion_intensities else False,
            "total_seconds": n,
        }

    def _compute_match_score(
        self,
        template: MetaTemplate,
        content_profile: dict,
        timeline: CaptionTimeline,
    ) -> float:
        """Score how well a template matches content characteristics."""
        score = 0.0

        # 1. Mood match (30% weight)
        if template.mood == content_profile["dominant_mood"]:
            score += 0.30
        elif (template.mood in ("intense", "chaotic") and
              content_profile["dominant_mood"] in ("intense", "chaotic")):
            score += 0.15  # Close enough
        else:
            score += 0.05  # Mood mismatch

        # 2. Duration compatibility (20% weight)
        content_duration = content_profile["total_seconds"]
        target_min, target_max = template.target_duration_range
        if target_min <= content_duration <= target_max:
            score += 0.20
        elif content_duration > target_max * 0.5:
            # Content is long enough to clip from
            score += 0.15
        else:
            score += 0.05

        # 3. Intensity profile match (25% weight)
        mean_int = content_profile["mean_intensity"]
        # Higher intensity content matches higher-energy templates
        if template.mood in ("intense", "chaotic") and mean_int > 0.3:
            score += 0.25
        elif template.mood == "chill" and mean_int < 0.3:
            score += 0.25
        elif template.mood == "triumphant" and content_profile["intensity_std"] > 0.1:
            score += 0.20  # Varied intensity suits narrative
        else:
            score += 0.10

        # 4. Template success rate (25% weight)
        if template.usage_count > 0:
            success_score = (
                template.win_rate * 0.5
                + (template.avg_rating / 5.0) * 0.5
            )
            score += success_score * 0.25
        else:
            score += 0.125  # Neutral for untested templates

        return round(score, 4)

    def _generate_pacing_guidance(
        self,
        pacing_curve: PacingCurve,
        target_duration: float,
    ) -> list[dict]:
        """Convert pacing curve to timestamped guidance points."""
        if not pacing_curve.points:
            return [
                {"time": 0.0, "speed": 1.0},
                {"time": target_duration * 0.4, "speed": 1.0},
                {"time": target_duration * 0.6, "speed": 0.75},
                {"time": target_duration * 0.8, "speed": 1.0},
                {"time": target_duration, "speed": 1.0},
            ]

        guidance = []
        for t_norm, speed in pacing_curve.points:
            guidance.append({
                "time": round(t_norm * target_duration, 2),
                "speed": round(speed, 3),
            })
        return guidance


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _generate_id(seed: str) -> str:
    """Generate a deterministic short ID from a seed string."""
    return hashlib.md5(seed.encode()).hexdigest()[:12]


def _deep_serialize(obj: Any) -> Any:
    """Recursively convert dataclass dicts to JSON-serializable form."""
    if isinstance(obj, dict):
        return {k: _deep_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        serialized = [_deep_serialize(v) for v in obj]
        return serialized
    elif isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    else:
        return str(obj)


# ---------------------------------------------------------------------------
# Built-in default templates (used when no learned templates exist)
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATES: dict[str, dict] = {
    "default-intense": {
        "template_id": "default-intense",
        "name": "Default Intense",
        "mood": "intense",
        "phase_proportions": {"hook": 0.08, "rising": 0.30, "climax": 0.42, "resolution": 0.20},
        "target_duration_range": [30, 90],
        "hook_strategy": "flash_forward",
        "bgm_mood": "intense",
        "bgm_genre": "electronic-hype",
        "beats_per_minute_target": 150,
        "anti_fluff_min_signals": 2,
    },
    "default-triumphant": {
        "template_id": "default-triumphant",
        "name": "Default Triumphant",
        "mood": "triumphant",
        "phase_proportions": {"hook": 0.10, "rising": 0.35, "climax": 0.35, "resolution": 0.20},
        "target_duration_range": [45, 120],
        "hook_strategy": "cold_open",
        "bgm_mood": "triumphant",
        "bgm_genre": "orchestral-epic",
        "beats_per_minute_target": 140,
        "anti_fluff_min_signals": 2,
    },
    "default-chaotic": {
        "template_id": "default-chaotic",
        "name": "Default Chaotic",
        "mood": "chaotic",
        "phase_proportions": {"hook": 0.12, "rising": 0.25, "climax": 0.45, "resolution": 0.18},
        "target_duration_range": [20, 60],
        "hook_strategy": "flash_forward",
        "bgm_mood": "chaotic",
        "bgm_genre": "meme-edm",
        "beats_per_minute_target": 160,
        "anti_fluff_min_signals": 1,
    },
    "default-chill": {
        "template_id": "default-chill",
        "name": "Default Chill",
        "mood": "chill",
        "phase_proportions": {"hook": 0.06, "rising": 0.35, "climax": 0.30, "resolution": 0.29},
        "target_duration_range": [60, 180],
        "hook_strategy": "text_tease",
        "bgm_mood": "chill",
        "bgm_genre": "lofi-ambient",
        "beats_per_minute_target": 85,
        "anti_fluff_min_signals": 2,
    },
}


def get_default_template(mood: str) -> MetaTemplate:
    """Return a built-in default template for the given mood."""
    key = f"default-{mood}"
    if key not in DEFAULT_TEMPLATES:
        key = "default-intense"
    data = dict(DEFAULT_TEMPLATES[key])

    # Build a minimal MetaTemplate from the default dict
    tdr = data.get("target_duration_range", [30, 90])
    return MetaTemplate(
        template_id=data["template_id"],
        name=data["name"],
        mood=data["mood"],
        phase_proportions=data.get("phase_proportions", {}),
        target_duration_range=tuple(tdr),
        hook_strategy=data.get("hook_strategy", "flash_forward"),
        bgm_mood=data.get("bgm_mood", mood),
        bgm_genre=data.get("bgm_genre", "electronic-hype"),
        beats_per_minute_target=data.get("beats_per_minute_target", 130),
        anti_fluff_min_signals=data.get("anti_fluff_min_signals", 2),
    )
