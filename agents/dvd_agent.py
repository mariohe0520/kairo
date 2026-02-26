"""
Kairo DVDAgent -- Deep Video Discovery Agent.

Scans the full annotated ``CaptionTimeline`` and discovers the top viral clip
candidates using triangulation scoring across game, emotion, and audience
signals.

Three scoring strategies run in parallel and are merged:
  - **Peak-based**:     find single highest-intensity moments.
  - **Arc-based**:      find windows with a natural narrative arc
                        (setup -> climax -> resolution).
  - **Momentum-based**: find biggest score swings (comeback moments).

Anti-clustering enforces a minimum temporal gap between returned candidates
so the top-N list is always temporally diverse.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("kairo.dvd_agent")

# Try numpy for fast array operations; fall back to pure-Python if absent.
try:
    import numpy as np  # type: ignore[import-untyped]
    _HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False
    logger.info("numpy not available -- using pure-Python scoring (slower)")


# ---------------------------------------------------------------------------
# Import shared types from caption_agent
# ---------------------------------------------------------------------------

from agents.caption_agent import CaptionTimeline, SegmentAnnotation  # noqa: E402


# ---------------------------------------------------------------------------
# Structured data types
# ---------------------------------------------------------------------------

@dataclass
class WindowScore:
    """Score breakdown for a single candidate time window."""
    start: float
    end: float
    duration: float
    game_score: float = 0.0          # aggregated game intensity
    emotion_score: float = 0.0       # aggregated emotion intensity
    audience_score: float = 0.0      # aggregated audience intensity
    triangulation: float = 0.0       # game * emotion * audience (cubed root)
    peak_composite: float = 0.0      # max per-second composite in window
    mean_composite: float = 0.0      # mean per-second composite
    narrative_potential: float = 0.0  # arc shape quality 0-1
    momentum_score: float = 0.0      # biggest swing in window


@dataclass
class NarrativeArc:
    """A detected narrative arc within the timeline."""
    start: float
    end: float
    setup_end: float          # timestamp where setup transitions to rising
    climax_start: float       # timestamp where climax begins
    climax_peak: float        # timestamp of the peak moment
    resolution_start: float   # timestamp where resolution begins
    arc_quality: float = 0.0  # 0-1 how clean the arc shape is
    peak_intensity: float = 0.0


@dataclass
class ClipCandidate:
    """A discovered clip candidate ready for the DNA agent."""
    rank: int
    start: float
    end: float
    duration: float
    composite_score: float        # final blended ranking score
    window_score: WindowScore
    dominant_signal: str          # "game" | "emotion" | "audience" | "balanced"
    narrative_potential: float    # 0-1 how story-worthy this window is
    scoring_strategy: str         # "peak" | "arc" | "momentum"
    annotations: list[SegmentAnnotation] = field(default_factory=list)
    narrative_arc: Optional[NarrativeArc] = None


# ---------------------------------------------------------------------------
# DVDAgent
# ---------------------------------------------------------------------------

# Default sliding-window durations (seconds)
_DEFAULT_WINDOW_SIZES = [15, 30, 60, 90, 120]

# Minimum gap between candidates in seconds (anti-clustering)
_DEFAULT_MIN_GAP = 60.0


class DVDAgent:
    """
    Deep Video Discovery Agent.

    Scans every possible time window across multiple sizes, scores using
    triangulation, and returns temporally diverse top-N candidates.

    Parameters
    ----------
    window_sizes : list[int]
        Candidate clip durations to evaluate (seconds).
    min_gap : float
        Minimum temporal gap (seconds) between returned candidates.
    top_n : int
        Number of candidates to return.
    step_sec : float
        Sliding-window step size (seconds).  Smaller = finer grained but slower.
    """

    def __init__(
        self,
        window_sizes: Optional[list[int]] = None,
        min_gap: float = _DEFAULT_MIN_GAP,
        top_n: int = 5,
        step_sec: float = 2.0,
    ) -> None:
        self.window_sizes = window_sizes or list(_DEFAULT_WINDOW_SIZES)
        self.min_gap = min_gap
        self.top_n = top_n
        self.step_sec = step_sec

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(
        self,
        caption_timeline: CaptionTimeline,
        config: Optional[dict] = None,
    ) -> list[ClipCandidate]:
        """
        Discover the best viral clip candidates from an annotated timeline.

        Parameters
        ----------
        caption_timeline : CaptionTimeline
            Output of ``CaptionAgent.analyze()``.
        config : dict, optional
            Override defaults.  Recognised keys:
            ``window_sizes``, ``min_gap``, ``top_n``, ``step_sec``,
            ``game_weight``, ``emotion_weight``, ``audience_weight``.

        Returns
        -------
        list[ClipCandidate]
            Top-N candidates sorted descending by composite score.
        """
        cfg = config or {}
        window_sizes = cfg.get("window_sizes", self.window_sizes)
        min_gap = cfg.get("min_gap", self.min_gap)
        top_n = cfg.get("top_n", self.top_n)
        step = cfg.get("step_sec", self.step_sec)
        game_w = cfg.get("game_weight", 0.35)
        emotion_w = cfg.get("emotion_weight", 0.40)
        audience_w = cfg.get("audience_weight", 0.25)

        annotations = caption_timeline.annotations
        if not annotations:
            logger.warning("Empty timeline -- no candidates")
            return []

        duration = caption_timeline.duration_sec
        logger.info(
            "DVD scanning %.0fs timeline with window sizes %s, step=%.1fs",
            duration, window_sizes, step,
        )

        # --- Precompute signal arrays for fast window scoring ---
        game_arr, emo_arr, aud_arr, comp_arr = self._build_signal_arrays(annotations)

        # --- Score all windows across all sizes (3 strategies) ---
        all_candidates: list[ClipCandidate] = []

        # Pre-detect narrative arcs once (reused across window sizes)
        arcs = self._find_narrative_arcs(annotations)
        arc_lookup = {(a.start, a.end): a for a in arcs}

        for wsize in window_sizes:
            if wsize > duration:
                continue

            starts = self._window_start_positions(duration, wsize, step)
            for ws in starts:
                we = ws + wsize
                window_anns = caption_timeline.slice(ws, we)
                if not window_anns:
                    continue

                # Core window score
                wscore = self._score_window(
                    game_arr, emo_arr, aud_arr, comp_arr,
                    ws, we, len(annotations),
                )

                # Narrative arc overlap
                best_arc = self._best_overlapping_arc(arcs, ws, we)
                wscore.narrative_potential = best_arc.arc_quality if best_arc else 0.0

                # Momentum
                wscore.momentum_score = self._momentum_in_window(comp_arr, ws, we, len(annotations))

                # --- Strategy 1: Peak-based ---
                peak_score = (
                    wscore.peak_composite * 0.5
                    + wscore.triangulation * 0.3
                    + wscore.mean_composite * 0.2
                )
                all_candidates.append(
                    ClipCandidate(
                        rank=0,
                        start=ws,
                        end=we,
                        duration=wsize,
                        composite_score=round(peak_score, 4),
                        window_score=wscore,
                        dominant_signal=self._dominant_signal(wscore),
                        narrative_potential=wscore.narrative_potential,
                        scoring_strategy="peak",
                        annotations=window_anns,
                        narrative_arc=best_arc,
                    )
                )

                # --- Strategy 2: Arc-based ---
                if best_arc and best_arc.arc_quality > 0.3:
                    arc_score = (
                        best_arc.arc_quality * 0.45
                        + wscore.triangulation * 0.30
                        + wscore.mean_composite * 0.25
                    )
                    all_candidates.append(
                        ClipCandidate(
                            rank=0,
                            start=ws,
                            end=we,
                            duration=wsize,
                            composite_score=round(arc_score, 4),
                            window_score=wscore,
                            dominant_signal=self._dominant_signal(wscore),
                            narrative_potential=best_arc.arc_quality,
                            scoring_strategy="arc",
                            annotations=window_anns,
                            narrative_arc=best_arc,
                        )
                    )

                # --- Strategy 3: Momentum-based ---
                if wscore.momentum_score > 0.2:
                    mom_score = (
                        wscore.momentum_score * 0.50
                        + wscore.peak_composite * 0.25
                        + wscore.triangulation * 0.25
                    )
                    all_candidates.append(
                        ClipCandidate(
                            rank=0,
                            start=ws,
                            end=we,
                            duration=wsize,
                            composite_score=round(mom_score, 4),
                            window_score=wscore,
                            dominant_signal=self._dominant_signal(wscore),
                            narrative_potential=wscore.narrative_potential,
                            scoring_strategy="momentum",
                            annotations=window_anns,
                            narrative_arc=best_arc,
                        )
                    )

        logger.info("Scored %d raw candidate windows", len(all_candidates))

        # --- Anti-clustering & ranking ---
        ranked = self._anti_cluster_select(all_candidates, top_n, min_gap)

        for i, c in enumerate(ranked):
            c.rank = i + 1

        logger.info(
            "DVD result: %d candidates, best=%.4f (%s, %.0f-%.0fs)",
            len(ranked),
            ranked[0].composite_score if ranked else 0,
            ranked[0].scoring_strategy if ranked else "n/a",
            ranked[0].start if ranked else 0,
            ranked[0].end if ranked else 0,
        )
        return ranked

    # ------------------------------------------------------------------
    # Window scoring
    # ------------------------------------------------------------------

    def _score_window(
        self,
        game_arr: list[float],
        emo_arr: list[float],
        aud_arr: list[float],
        comp_arr: list[float],
        start: float,
        end: float,
        total_secs: int,
    ) -> WindowScore:
        """Score a single time window using pre-computed signal arrays."""
        lo = max(0, int(math.floor(start)))
        hi = min(total_secs, int(math.ceil(end)))
        if hi <= lo:
            return WindowScore(start=start, end=end, duration=end - start)

        g = game_arr[lo:hi]
        e = emo_arr[lo:hi]
        a = aud_arr[lo:hi]
        c = comp_arr[lo:hi]

        if _HAS_NUMPY:
            g_np = np.array(g, dtype=np.float64)
            e_np = np.array(e, dtype=np.float64)
            a_np = np.array(a, dtype=np.float64)
            c_np = np.array(c, dtype=np.float64)

            game_score = float(np.mean(g_np))
            emo_score = float(np.mean(e_np))
            aud_score = float(np.mean(a_np))
            peak = float(np.max(c_np)) if c_np.size > 0 else 0.0
            mean = float(np.mean(c_np)) if c_np.size > 0 else 0.0
        else:
            game_score = sum(g) / len(g) if g else 0.0
            emo_score = sum(e) / len(e) if e else 0.0
            aud_score = sum(a) / len(a) if a else 0.0
            peak = max(c) if c else 0.0
            mean = sum(c) / len(c) if c else 0.0

        tri = self._triangulation_score(game_score, emo_score, aud_score)

        return WindowScore(
            start=start,
            end=end,
            duration=end - start,
            game_score=round(game_score, 4),
            emotion_score=round(emo_score, 4),
            audience_score=round(aud_score, 4),
            triangulation=round(tri, 4),
            peak_composite=round(peak, 4),
            mean_composite=round(mean, 4),
        )

    def _triangulation_score(
        self,
        game_signal: float,
        emotion_signal: float,
        audience_signal: float,
    ) -> float:
        """
        Triangulation scoring: geometric mean of the three signals.

        Using the cube root of the product rewards windows where *all three*
        channels are elevated, rather than windows where only one channel
        spikes.  A small epsilon prevents a single zero channel from
        killing the score entirely.
        """
        eps = 0.01
        g = max(eps, game_signal)
        e = max(eps, emotion_signal)
        a = max(eps, audience_signal)
        return round((g * e * a) ** (1.0 / 3.0), 6)

    # ------------------------------------------------------------------
    # Narrative arc detection
    # ------------------------------------------------------------------

    def _find_narrative_arcs(
        self, annotations: list[SegmentAnnotation]
    ) -> list[NarrativeArc]:
        """
        Detect natural narrative arcs in the composite score curve.

        An arc is a contiguous region where the score rises, peaks, and falls.
        The algorithm walks through the composite series, identifies local
        valleys and peaks, and groups them into (valley -> peak -> valley)
        triplets.
        """
        if len(annotations) < 10:
            return []

        scores = [a.composite_score for a in annotations]
        n = len(scores)

        # Find local extrema using a 5-second window
        peaks: list[int] = []
        valleys: list[int] = []
        w = 5
        for i in range(w, n - w):
            window = scores[i - w : i + w + 1]
            if scores[i] == max(window):
                peaks.append(i)
            elif scores[i] == min(window):
                valleys.append(i)

        if not peaks:
            return []

        # Build arcs from valley-peak-valley triplets
        arcs: list[NarrativeArc] = []
        for peak_idx in peaks:
            # Find closest valley before and after
            prev_valleys = [v for v in valleys if v < peak_idx]
            next_valleys = [v for v in valleys if v > peak_idx]

            if not prev_valleys or not next_valleys:
                continue

            v_before = max(prev_valleys, key=lambda v: v)
            v_after = min(next_valleys, key=lambda v: v)

            arc_start = float(v_before)
            arc_end = float(v_after)
            arc_duration = arc_end - arc_start

            if arc_duration < 10 or arc_duration > 180:
                continue

            # Measure arc quality: how much does the peak stand above the valleys?
            valley_avg = (scores[v_before] + scores[v_after]) / 2.0
            peak_val = scores[peak_idx]
            contrast = peak_val - valley_avg
            if contrast < 0.05:
                continue

            # Quality: contrast * shape regularity
            # Shape regularity: is the rise roughly as long as the fall?
            rise_len = peak_idx - v_before
            fall_len = v_after - peak_idx
            symmetry = 1.0 - abs(rise_len - fall_len) / max(rise_len + fall_len, 1)
            arc_quality = min(1.0, contrast * 2.0) * (0.5 + 0.5 * symmetry)

            # Determine narrative phases within the arc
            setup_end = arc_start + arc_duration * 0.25
            climax_start = float(peak_idx) - arc_duration * 0.15
            resolution_start = float(peak_idx) + arc_duration * 0.15

            arcs.append(
                NarrativeArc(
                    start=arc_start,
                    end=arc_end,
                    setup_end=round(setup_end, 1),
                    climax_start=round(climax_start, 1),
                    climax_peak=float(peak_idx),
                    resolution_start=round(resolution_start, 1),
                    arc_quality=round(arc_quality, 4),
                    peak_intensity=round(peak_val, 4),
                )
            )

        # Deduplicate overlapping arcs: keep the higher-quality one
        arcs.sort(key=lambda a: a.arc_quality, reverse=True)
        kept: list[NarrativeArc] = []
        for arc in arcs:
            overlap = any(
                not (arc.end <= k.start or arc.start >= k.end) for k in kept
            )
            if not overlap:
                kept.append(arc)

        logger.info("Detected %d narrative arcs", len(kept))
        return kept

    # ------------------------------------------------------------------
    # Momentum scoring
    # ------------------------------------------------------------------

    def _momentum_in_window(
        self,
        comp_arr: list[float],
        start: float,
        end: float,
        total_secs: int,
    ) -> float:
        """
        Find the largest positive swing in composite score within a window.

        This captures comeback moments where the score rockets from low to
        high.  The value is normalised to 0-1.
        """
        lo = max(0, int(math.floor(start)))
        hi = min(total_secs, int(math.ceil(end)))
        segment = comp_arr[lo:hi]
        if len(segment) < 5:
            return 0.0

        # Rolling minimum (lookback 10s) vs current value
        lookback = 10
        max_swing = 0.0
        running_min = segment[0]

        for i, val in enumerate(segment):
            if i > lookback:
                running_min = min(segment[i - lookback : i])
            else:
                running_min = min(segment[: i + 1])
            swing = val - running_min
            if swing > max_swing:
                max_swing = swing

        return round(min(1.0, max_swing * 2.0), 4)  # scale up, cap at 1

    # ------------------------------------------------------------------
    # Anti-clustering selection
    # ------------------------------------------------------------------

    def _anti_cluster_select(
        self,
        candidates: list[ClipCandidate],
        top_n: int,
        min_gap: float,
    ) -> list[ClipCandidate]:
        """
        Select top-N candidates ensuring no two overlap more than allowed.

        Greedy: sort by score descending, accept a candidate only if its
        midpoint is at least ``min_gap`` seconds from every already-accepted
        candidate's midpoint.
        """
        if not candidates:
            return []

        candidates.sort(key=lambda c: c.composite_score, reverse=True)

        selected: list[ClipCandidate] = []
        selected_midpoints: list[float] = []

        for cand in candidates:
            mid = (cand.start + cand.end) / 2.0
            if all(abs(mid - sm) >= min_gap for sm in selected_midpoints):
                selected.append(cand)
                selected_midpoints.append(mid)
                if len(selected) >= top_n:
                    break

        # If we could not fill top_n due to anti-clustering, relax the gap
        if len(selected) < top_n and min_gap > 10:
            remaining = [c for c in candidates if c not in selected]
            relaxed_gap = min_gap * 0.5
            for cand in remaining:
                mid = (cand.start + cand.end) / 2.0
                if all(abs(mid - sm) >= relaxed_gap for sm in selected_midpoints):
                    selected.append(cand)
                    selected_midpoints.append(mid)
                    if len(selected) >= top_n:
                        break

        return selected

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_signal_arrays(
        self, annotations: list[SegmentAnnotation]
    ) -> tuple[list[float], list[float], list[float], list[float]]:
        """Extract parallel float lists from annotations for fast indexing."""
        game = [a.game_intensity for a in annotations]
        emo = [a.emotion_intensity for a in annotations]
        aud = [a.audience_intensity for a in annotations]
        comp = [a.composite_score for a in annotations]
        return game, emo, aud, comp

    @staticmethod
    def _window_start_positions(
        duration: float, window_size: int, step: float
    ) -> list[float]:
        """Generate sliding window start positions."""
        positions: list[float] = []
        pos = 0.0
        while pos + window_size <= duration:
            positions.append(round(pos, 1))
            pos += step
        return positions

    @staticmethod
    def _dominant_signal(ws: WindowScore) -> str:
        """Identify which signal channel dominates a window score."""
        signals = {
            "game": ws.game_score,
            "emotion": ws.emotion_score,
            "audience": ws.audience_score,
        }
        top = max(signals, key=signals.get)  # type: ignore[arg-type]
        top_val = signals[top]

        # If the top signal is not significantly above others, call it balanced
        others = [v for k, v in signals.items() if k != top]
        if top_val > 0 and all((top_val - o) / max(top_val, 0.01) < 0.25 for o in others):
            return "balanced"
        return top

    @staticmethod
    def _best_overlapping_arc(
        arcs: list[NarrativeArc], start: float, end: float
    ) -> Optional[NarrativeArc]:
        """Return the highest-quality arc that overlaps with [start, end)."""
        best: Optional[NarrativeArc] = None
        best_q = -1.0
        for arc in arcs:
            if arc.end <= start or arc.start >= end:
                continue
            # Measure overlap fraction
            overlap_start = max(arc.start, start)
            overlap_end = min(arc.end, end)
            overlap = overlap_end - overlap_start
            arc_len = arc.end - arc.start
            coverage = overlap / arc_len if arc_len > 0 else 0
            effective_quality = arc.arc_quality * coverage
            if effective_quality > best_q:
                best_q = effective_quality
                best = arc
        return best
