"""
Kairo Streamer Memory — Preference learning and recommendation system.

This is what makes Kairo an intelligent agent rather than a simple tool.
StreamerMemory tracks every interaction, learns editing preferences over
time, and provides personalized recommendations for templates, effects,
pacing, and enhancement levels.

Data is persisted as JSON files in the memory/profiles/ directory,
one file per streamer. No external database required.
"""

import json
import logging
import math
import os
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("kairo.memory")

WORKSPACE = Path(__file__).parent.parent
PROFILES_DIR = Path(__file__).parent / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Feedback:
    """Feedback submitted by the streamer on a generated clip."""

    rating: int = 3  # 1-5 star rating
    action: str = "approved"  # approved, rejected, modified
    modifications: dict = field(default_factory=dict)  # what was changed
    notes: str = ""

    def __post_init__(self):
        self.rating = max(1, min(5, self.rating))
        if self.action not in ("approved", "rejected", "modified"):
            self.action = "approved"


@dataclass
class EditingRecord:
    """Record of a single clip generation event and its outcome."""

    clip_id: str = ""
    template_id: str = ""
    enhancements: dict = field(default_factory=dict)  # slider values used
    feedback: str = "pending"  # approved, rejected, modified, pending
    modifications: dict = field(default_factory=dict)  # what the streamer changed
    timestamp: str = ""
    engagement_metrics: dict = field(default_factory=dict)  # views, likes, shares
    video_analysis: dict = field(default_factory=dict)  # game, genre, duration
    rating: int = 0  # 1-5 from feedback

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class StreamerProfile:
    """
    Complete profile for a streamer — preferences, history, and learned vectors.

    Persisted as JSON. Updated incrementally on every feedback event.
    """

    streamer_id: str = ""
    name: str = ""
    platform: str = "twitch"  # twitch, youtube, bilibili
    games: list = field(default_factory=list)
    editing_history: list = field(default_factory=list)  # list[EditingRecord]
    preference_vector: dict = field(default_factory=dict)  # learned preferences
    template_usage: dict = field(default_factory=dict)  # template_id -> count
    template_ratings: dict = field(default_factory=dict)  # template_id -> [ratings]
    avg_enhancement_levels: dict = field(default_factory=lambda: {
        "bgm": 70.0,
        "subtitles": 60.0,
        "effects": 65.0,
        "hook": 75.0,
        "transitions": 60.0,
    })
    effect_preferences: dict = field(default_factory=dict)  # effect_type -> affinity score
    pacing_preference: float = 1.0  # average preferred pacing
    preferred_duration_range: list = field(default_factory=lambda: [30, 90])
    content_tags: list = field(default_factory=list)  # tags learned from content
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


@dataclass
class PreferenceVector:
    """
    Learned preference vector for a streamer.

    Each dimension is a normalized float [0.0, 1.0] representing
    affinity toward that editing dimension.
    """

    template_affinities: dict = field(default_factory=dict)  # template_id -> 0-1 score
    effect_affinities: dict = field(default_factory=dict)  # effect_type -> 0-1 score
    enhancement_levels: dict = field(default_factory=dict)  # module -> preferred level
    pacing_center: float = 1.0  # preferred pacing center
    pacing_variance: float = 0.3  # how much pacing varies
    mood_preference: str = "intense"  # dominant mood
    complexity_preference: float = 0.6  # 0 = minimal, 1 = maximal
    subtitle_importance: float = 0.5  # how much they value subtitles
    music_importance: float = 0.7  # how much they value BGM


@dataclass
class TemplateRecommendation:
    """A recommended template with reasoning."""

    template_id: str
    confidence: float  # 0-1
    reason: str
    predicted_rating: float  # predicted 1-5 rating
    suggested_enhancements: dict = field(default_factory=dict)
    alternatives: list = field(default_factory=list)  # list of (template_id, confidence)


# ---------------------------------------------------------------------------
# StreamerMemory — The intelligence layer
# ---------------------------------------------------------------------------


class StreamerMemory:
    """
    Persistent memory system that learns streamer preferences.

    Stores profiles as JSON files. Learns from feedback to improve
    template selection, enhancement levels, and effect choices over time.

    Usage:
        memory = StreamerMemory()
        profile = memory.load_profile("streamer_123")
        memory.record_feedback("streamer_123", "clip_abc", feedback)
        rec = memory.recommend_template("streamer_123", video_analysis)
    """

    def __init__(self, profiles_dir: Optional[str] = None):
        self._profiles_dir = Path(profiles_dir) if profiles_dir else PROFILES_DIR
        self._profiles_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, StreamerProfile] = {}
        # Exponential decay weight for learning — recent feedback matters more
        self._recency_halflife = 20  # records until weight halves

    # ------------------------------------------------------------------
    # Profile CRUD
    # ------------------------------------------------------------------

    def load_profile(self, streamer_id: str) -> StreamerProfile:
        """
        Load a streamer profile from disk, or create a new one.

        Profiles are cached in memory for the lifetime of the StreamerMemory
        instance. Disk reads happen only on first access.
        """
        if streamer_id in self._cache:
            return self._cache[streamer_id]

        profile_path = self._profile_path(streamer_id)
        if profile_path.exists():
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Reconstruct EditingRecord objects
                records = []
                for rec in data.get("editing_history", []):
                    records.append(EditingRecord(**{
                        k: v for k, v in rec.items()
                        if k in EditingRecord.__dataclass_fields__
                    }))
                data["editing_history"] = records
                profile = StreamerProfile(**{
                    k: v for k, v in data.items()
                    if k in StreamerProfile.__dataclass_fields__
                })
                logger.info("Loaded profile for %s (%d records)", streamer_id, len(records))
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.error("Corrupted profile for %s, creating fresh: %s", streamer_id, e)
                profile = StreamerProfile(streamer_id=streamer_id)
        else:
            profile = StreamerProfile(streamer_id=streamer_id)
            logger.info("Created new profile for %s", streamer_id)

        self._cache[streamer_id] = profile
        return profile

    def save_profile(self, profile: StreamerProfile) -> None:
        """Persist a streamer profile to disk as JSON."""
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        self._cache[profile.streamer_id] = profile

        profile_path = self._profile_path(profile.streamer_id)
        data = self._profile_to_dict(profile)

        # Atomic write via temp file
        tmp_path = profile_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            tmp_path.replace(profile_path)
            logger.debug("Saved profile for %s", profile.streamer_id)
        except OSError as e:
            logger.error("Failed to save profile for %s: %s", profile.streamer_id, e)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def delete_profile(self, streamer_id: str) -> bool:
        """Remove a streamer profile from disk and cache."""
        self._cache.pop(streamer_id, None)
        path = self._profile_path(streamer_id)
        if path.exists():
            path.unlink()
            logger.info("Deleted profile for %s", streamer_id)
            return True
        return False

    def list_profiles(self) -> list[str]:
        """List all stored streamer IDs."""
        return [
            p.stem for p in self._profiles_dir.glob("*.json")
            if not p.stem.startswith("_")
        ]

    # ------------------------------------------------------------------
    # Feedback recording
    # ------------------------------------------------------------------

    def record_feedback(
        self,
        streamer_id: str,
        clip_id: str,
        feedback: Feedback,
        template_id: str = "",
        enhancements: Optional[dict] = None,
        video_analysis: Optional[dict] = None,
    ) -> None:
        """
        Record feedback on a generated clip and update the streamer's profile.

        This is the primary learning signal. Each feedback event:
        1. Appends to editing_history
        2. Updates template_usage and template_ratings
        3. Adjusts avg_enhancement_levels via exponential moving average
        4. Triggers preference vector recalculation
        """
        profile = self.load_profile(streamer_id)

        record = EditingRecord(
            clip_id=clip_id,
            template_id=template_id,
            enhancements=enhancements or {},
            feedback=feedback.action,
            modifications=feedback.modifications,
            rating=feedback.rating,
            video_analysis=video_analysis or {},
        )

        profile.editing_history.append(record)

        # Update template usage counts
        if template_id:
            profile.template_usage[template_id] = profile.template_usage.get(template_id, 0) + 1
            if template_id not in profile.template_ratings:
                profile.template_ratings[template_id] = []
            profile.template_ratings[template_id].append(feedback.rating)

        # Update enhancement levels via EMA
        if enhancements and feedback.action in ("approved", "modified"):
            self._update_enhancement_ema(profile, enhancements, feedback)

        # Track effect preferences from modifications
        if feedback.modifications:
            self._update_effect_preferences(profile, feedback.modifications)

        # Update content tags from video analysis
        if video_analysis:
            game = video_analysis.get("game")
            if game and game not in profile.games:
                profile.games.append(game)
            tags = video_analysis.get("tags", [])
            for tag in tags:
                if tag not in profile.content_tags:
                    profile.content_tags.append(tag)

        # Recalculate preference vector
        profile.preference_vector = asdict(self.learn_preferences(streamer_id))

        self.save_profile(profile)
        logger.info(
            "Recorded feedback for %s: clip=%s, action=%s, rating=%d",
            streamer_id, clip_id, feedback.action, feedback.rating,
        )

    # ------------------------------------------------------------------
    # Preference learning
    # ------------------------------------------------------------------

    def learn_preferences(self, streamer_id: str) -> PreferenceVector:
        """
        Compute a preference vector from the streamer's editing history.

        Uses recency-weighted aggregation: recent feedback has exponentially
        more weight than old feedback. This allows the system to adapt as
        the streamer's taste evolves.

        Returns a PreferenceVector with normalized affinities for each
        editing dimension.
        """
        profile = self.load_profile(streamer_id)
        history = profile.editing_history

        if not history:
            return PreferenceVector(
                enhancement_levels=dict(profile.avg_enhancement_levels),
            )

        # Compute recency weights (most recent record has weight 1.0)
        n = len(history)
        weights = []
        for i in range(n):
            age = n - 1 - i  # 0 for most recent
            weight = math.pow(0.5, age / self._recency_halflife)
            weights.append(weight)
        total_weight = sum(weights)
        if total_weight == 0:
            total_weight = 1.0

        # --- Template affinities ---
        template_scores: dict[str, float] = defaultdict(float)
        template_weights: dict[str, float] = defaultdict(float)

        for i, rec in enumerate(history):
            if not rec.template_id:
                continue
            # Convert rating (1-5) to affinity (0-1)
            affinity = (rec.rating - 1) / 4.0 if rec.rating > 0 else 0.5
            # Approved clips get a bonus
            if rec.feedback == "approved":
                affinity = min(1.0, affinity + 0.1)
            elif rec.feedback == "rejected":
                affinity = max(0.0, affinity - 0.2)

            template_scores[rec.template_id] += affinity * weights[i]
            template_weights[rec.template_id] += weights[i]

        template_affinities = {}
        for tid, score in template_scores.items():
            tw = template_weights[tid]
            template_affinities[tid] = round(score / tw, 4) if tw > 0 else 0.5

        # --- Effect affinities ---
        effect_scores: dict[str, float] = defaultdict(float)
        effect_counts: dict[str, float] = defaultdict(float)

        for i, rec in enumerate(history):
            enhancements = rec.enhancements or {}
            rating_signal = (rec.rating - 1) / 4.0 if rec.rating > 0 else 0.5

            # Effects used in approved/high-rated clips get positive signal
            for key, val in enhancements.items():
                if isinstance(val, (int, float)):
                    normalized = val / 100.0
                    effect_scores[key] += normalized * rating_signal * weights[i]
                    effect_counts[key] += weights[i]

        effect_affinities = {}
        for eff, score in effect_scores.items():
            ec = effect_counts[eff]
            effect_affinities[eff] = round(score / ec, 4) if ec > 0 else 0.5

        # --- Enhancement levels (weighted average of approved clips) ---
        enh_sums: dict[str, float] = defaultdict(float)
        enh_weights: dict[str, float] = defaultdict(float)

        for i, rec in enumerate(history):
            if rec.feedback == "rejected":
                continue  # Skip rejected clips for level learning
            enhancements = rec.enhancements or {}
            # Use modifications if available (streamer's actual preference)
            mods = rec.modifications or {}
            merged = {**enhancements, **mods}

            for key in ("bgm", "subtitles", "effects", "hook", "transitions"):
                val = merged.get(key)
                if val is not None and isinstance(val, (int, float)):
                    enh_sums[key] += val * weights[i]
                    enh_weights[key] += weights[i]

        enhancement_levels = {}
        for key in ("bgm", "subtitles", "effects", "hook", "transitions"):
            ew = enh_weights.get(key, 0)
            if ew > 0:
                enhancement_levels[key] = round(enh_sums[key] / ew, 2)
            else:
                enhancement_levels[key] = profile.avg_enhancement_levels.get(key, 60.0)

        # --- Pacing preference ---
        pacing_values = []
        pacing_w = []
        for i, rec in enumerate(history):
            p = (rec.enhancements or {}).get("pacing")
            if p is not None:
                pacing_values.append(p * weights[i])
                pacing_w.append(weights[i])

        pacing_center = (
            sum(pacing_values) / sum(pacing_w)
            if pacing_w
            else profile.pacing_preference
        )
        pacing_variance = 0.3  # Default; could be computed from history

        # --- Mood preference ---
        mood_counts: dict[str, float] = defaultdict(float)
        for i, rec in enumerate(history):
            mood = (rec.video_analysis or {}).get("mood")
            if mood and rec.feedback != "rejected":
                mood_counts[mood] += weights[i] * ((rec.rating or 3) / 5.0)

        mood_preference = max(mood_counts, key=mood_counts.get) if mood_counts else "intense"

        # --- Complexity preference (derived from effects + transitions levels) ---
        eff_level = enhancement_levels.get("effects", 65)
        trans_level = enhancement_levels.get("transitions", 60)
        complexity = (eff_level + trans_level) / 200.0

        # --- Subtitle and music importance ---
        sub_level = enhancement_levels.get("subtitles", 60)
        bgm_level = enhancement_levels.get("bgm", 70)

        return PreferenceVector(
            template_affinities=template_affinities,
            effect_affinities=effect_affinities,
            enhancement_levels=enhancement_levels,
            pacing_center=round(pacing_center, 3),
            pacing_variance=pacing_variance,
            mood_preference=mood_preference,
            complexity_preference=round(complexity, 3),
            subtitle_importance=round(sub_level / 100.0, 3),
            music_importance=round(bgm_level / 100.0, 3),
        )

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def recommend_template(
        self,
        streamer_id: str,
        video_analysis: Optional[dict] = None,
    ) -> TemplateRecommendation:
        """
        Recommend the best template for this streamer based on their history.

        Combines:
        1. Template affinity from preference vector (50% weight)
        2. Template success rate (average rating) (30% weight)
        3. Content match from video_analysis (20% weight)

        For cold-start (no history), falls back to similar-streamer
        recommendations or sensible defaults.
        """
        profile = self.load_profile(streamer_id)
        pref = self.learn_preferences(streamer_id)

        # Available templates (matching the JS template registry)
        all_templates = [
            "comeback-king", "clutch-master", "rage-quit-montage",
            "chill-highlights", "kill-montage", "session-story",
            "tiktok-vertical", "edu-breakdown", "hype-montage", "squad-moments",
        ]

        # Cold start
        if not profile.editing_history:
            return self._cold_start_recommendation(streamer_id, video_analysis, all_templates)

        scores: dict[str, float] = {}
        for tid in all_templates:
            # 1. Affinity from preference vector
            affinity = pref.template_affinities.get(tid, 0.5)

            # 2. Average rating for this template
            ratings = profile.template_ratings.get(tid, [])
            avg_rating = sum(ratings) / len(ratings) if ratings else 3.0
            rating_score = (avg_rating - 1) / 4.0  # normalize to 0-1

            # 3. Content match
            content_score = self._content_match_score(tid, video_analysis or {})

            # Weighted combination
            combined = (affinity * 0.50) + (rating_score * 0.30) + (content_score * 0.20)
            scores[tid] = combined

        # Sort by score descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_id, best_score = ranked[0]

        # Predict rating (linear map from score to 1-5 range)
        predicted_rating = round(1 + best_score * 4, 1)

        # Reason generation
        reason = self._generate_recommendation_reason(
            best_id, profile, pref, video_analysis
        )

        # Top-3 alternatives
        alternatives = [(tid, round(sc, 3)) for tid, sc in ranked[1:4]]

        return TemplateRecommendation(
            template_id=best_id,
            confidence=round(best_score, 3),
            reason=reason,
            predicted_rating=predicted_rating,
            suggested_enhancements=dict(pref.enhancement_levels),
            alternatives=alternatives,
        )

    def recommend_enhancements(
        self,
        streamer_id: str,
        template_id: str = "",
    ) -> dict:
        """
        Recommend enhancement slider levels for a streamer.

        Returns a dict of {module: level} where level is 0-100.
        Combines learned preferences with template-specific adjustments.
        """
        profile = self.load_profile(streamer_id)
        pref = self.learn_preferences(streamer_id)

        base_levels = dict(pref.enhancement_levels)

        # Template-specific adjustments from history
        if template_id and template_id in profile.template_ratings:
            # Find approved clips with this template and average their enhancements
            template_records = [
                r for r in profile.editing_history
                if r.template_id == template_id and r.feedback != "rejected"
            ]
            if template_records:
                for key in ("bgm", "subtitles", "effects", "hook", "transitions"):
                    vals = [
                        (r.enhancements or {}).get(key)
                        for r in template_records
                        if (r.enhancements or {}).get(key) is not None
                    ]
                    if vals:
                        # Blend learned value with base (70% template-specific, 30% overall)
                        template_avg = sum(vals) / len(vals)
                        base_levels[key] = round(
                            template_avg * 0.7 + base_levels.get(key, 60) * 0.3, 1
                        )

        # Clamp to valid range
        return {k: max(0, min(100, v)) for k, v in base_levels.items()}

    # ------------------------------------------------------------------
    # Similar streamer discovery
    # ------------------------------------------------------------------

    def find_similar_streamers(self, streamer_id: str, top_k: int = 5) -> list[str]:
        """
        Find streamers with similar editing preferences.

        Uses cosine similarity on preference vectors. Useful for:
        1. Cold-start recommendations (use similar streamer's preferences)
        2. Community features (streamer archetypes)
        3. Template popularity within a cluster
        """
        target_profile = self.load_profile(streamer_id)
        target_vec = self._profile_to_vector(target_profile)

        if not target_vec:
            return []

        similarities = []
        for sid in self.list_profiles():
            if sid == streamer_id:
                continue
            other_profile = self.load_profile(sid)
            other_vec = self._profile_to_vector(other_profile)
            if not other_vec:
                continue
            sim = self._cosine_similarity(target_vec, other_vec)
            similarities.append((sid, sim))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return [sid for sid, _ in similarities[:top_k]]

    # ------------------------------------------------------------------
    # Private helpers — learning
    # ------------------------------------------------------------------

    def _update_enhancement_ema(
        self,
        profile: StreamerProfile,
        enhancements: dict,
        feedback: Feedback,
    ) -> None:
        """Update average enhancement levels via exponential moving average."""
        alpha = 0.2  # EMA smoothing factor

        # If modified, use the modified values as the signal
        target = {**enhancements}
        if feedback.action == "modified" and feedback.modifications:
            target.update(feedback.modifications)

        for key in ("bgm", "subtitles", "effects", "hook", "transitions"):
            new_val = target.get(key)
            if new_val is not None and isinstance(new_val, (int, float)):
                old_val = profile.avg_enhancement_levels.get(key, 60.0)
                profile.avg_enhancement_levels[key] = round(
                    old_val * (1 - alpha) + new_val * alpha, 2
                )

    def _update_effect_preferences(self, profile: StreamerProfile, modifications: dict) -> None:
        """Track which effects the streamer adjusts and in which direction."""
        for key, val in modifications.items():
            if isinstance(val, (int, float)):
                current = profile.effect_preferences.get(key, 50.0)
                # Move toward the modified value
                profile.effect_preferences[key] = round((current + val) / 2, 2)

    # ------------------------------------------------------------------
    # Private helpers — recommendations
    # ------------------------------------------------------------------

    def _cold_start_recommendation(
        self,
        streamer_id: str,
        video_analysis: Optional[dict],
        all_templates: list,
    ) -> TemplateRecommendation:
        """
        Recommendation for a streamer with no history.

        Strategy:
        1. Check similar streamers (if any profiles exist)
        2. Fall back to content-based matching
        3. Default to 'chill-highlights'
        """
        # Try similar streamers
        similar = self.find_similar_streamers(streamer_id, top_k=3)
        if similar:
            # Aggregate template preferences from similar streamers
            template_votes: dict[str, float] = defaultdict(float)
            for sid in similar:
                other = self.load_profile(sid)
                for tid, count in other.template_usage.items():
                    ratings = other.template_ratings.get(tid, [3])
                    avg_r = sum(ratings) / len(ratings) if ratings else 3
                    template_votes[tid] += count * (avg_r / 5.0)

            if template_votes:
                best = max(template_votes, key=template_votes.get)
                return TemplateRecommendation(
                    template_id=best,
                    confidence=0.4,
                    reason=(
                        f"Based on similar streamers' preferences. "
                        f"Streamers like you tend to prefer '{best}'."
                    ),
                    predicted_rating=3.5,
                    suggested_enhancements={
                        "bgm": 70, "subtitles": 60, "effects": 65,
                        "hook": 75, "transitions": 60,
                    },
                )

        # Content-based fallback
        if video_analysis:
            best_tid = None
            best_score = -1
            for tid in all_templates:
                score = self._content_match_score(tid, video_analysis)
                if score > best_score:
                    best_score = score
                    best_tid = tid

            if best_tid:
                return TemplateRecommendation(
                    template_id=best_tid,
                    confidence=round(best_score * 0.6, 3),
                    reason=f"Selected based on your content characteristics.",
                    predicted_rating=3.0,
                    suggested_enhancements={
                        "bgm": 70, "subtitles": 60, "effects": 65,
                        "hook": 75, "transitions": 60,
                    },
                )

        # Ultimate fallback
        return TemplateRecommendation(
            template_id="chill-highlights",
            confidence=0.3,
            reason="Default recommendation for new users. Generate a clip and we'll learn your preferences!",
            predicted_rating=3.0,
            suggested_enhancements={
                "bgm": 70, "subtitles": 60, "effects": 50,
                "hook": 60, "transitions": 65,
            },
        )

    @staticmethod
    def _content_match_score(template_id: str, video_analysis: dict) -> float:
        """
        Score how well a template matches the content characteristics.

        Considers game genre, video duration, detected intensity,
        and content tags.
        """
        score = 0.5  # Neutral baseline

        genre = video_analysis.get("genre", "").lower()
        game = video_analysis.get("game", "").lower()
        duration = video_analysis.get("duration", 0)
        intensity = video_analysis.get("intensity", 50)
        tags = [t.lower() for t in video_analysis.get("tags", [])]

        # Genre / game matching
        fps_keywords = {"fps", "shooter", "valorant", "cs2", "csgo", "apex", "overwatch", "cod"}
        moba_keywords = {"moba", "league", "dota", "lol"}
        br_keywords = {"battle royale", "fortnite", "pubg", "warzone", "apex"}

        genre_tags = {genre, game} | set(tags)

        if template_id in ("clutch-master", "kill-montage") and genre_tags & fps_keywords:
            score += 0.25
        if template_id == "squad-moments" and ("squad" in tags or genre_tags & br_keywords):
            score += 0.2
        if template_id == "comeback-king" and "comeback" in tags:
            score += 0.3
        if template_id == "rage-quit-montage" and "rage" in tags:
            score += 0.25
        if template_id == "edu-breakdown" and ("educational" in tags or "tutorial" in tags):
            score += 0.3
        if template_id == "tiktok-vertical" and duration < 120:
            score += 0.15
        if template_id == "session-story" and duration > 1800:
            score += 0.2
        if template_id == "chill-highlights" and intensity < 40:
            score += 0.15
        if template_id in ("hype-montage", "kill-montage") and intensity > 70:
            score += 0.15

        return min(1.0, score)

    def _generate_recommendation_reason(
        self,
        template_id: str,
        profile: StreamerProfile,
        pref: PreferenceVector,
        video_analysis: Optional[dict],
    ) -> str:
        """Generate a human-readable reason for the template recommendation."""
        reasons = []

        # Check if it's the most-used template
        if profile.template_usage:
            most_used = max(profile.template_usage, key=profile.template_usage.get)
            if template_id == most_used:
                count = profile.template_usage[template_id]
                reasons.append(f"Your most-used template ({count} clips)")

        # Check rating history
        ratings = profile.template_ratings.get(template_id, [])
        if ratings:
            avg = sum(ratings) / len(ratings)
            if avg >= 4.0:
                reasons.append(f"You've rated it {avg:.1f}/5 on average")

        # Mood match
        if pref.mood_preference:
            mood_template_map = {
                "triumphant": ["comeback-king", "session-story", "squad-moments"],
                "intense": ["clutch-master", "kill-montage", "hype-montage", "tiktok-vertical"],
                "chaotic": ["rage-quit-montage"],
                "chill": ["chill-highlights", "edu-breakdown"],
            }
            matching = mood_template_map.get(pref.mood_preference, [])
            if template_id in matching:
                reasons.append(f"Matches your preferred mood: {pref.mood_preference}")

        # Content match
        if video_analysis:
            game = video_analysis.get("game", "")
            if game:
                reasons.append(f"Optimized for {game} content")

        if not reasons:
            reasons.append("Based on your editing history and preferences")

        return ". ".join(reasons) + "."

    # ------------------------------------------------------------------
    # Private helpers — vector operations
    # ------------------------------------------------------------------

    def _profile_to_vector(self, profile: StreamerProfile) -> list[float]:
        """
        Convert a profile to a numerical vector for similarity comparison.

        Dimensions:
        - 5 enhancement levels (normalized 0-1)
        - Template usage distribution (10 dimensions)
        - Pacing preference
        - Number of approved vs rejected ratio
        """
        vec = []

        # Enhancement levels
        for key in ("bgm", "subtitles", "effects", "hook", "transitions"):
            val = profile.avg_enhancement_levels.get(key, 60.0)
            vec.append(val / 100.0)

        # Template usage (normalized distribution)
        all_templates = [
            "comeback-king", "clutch-master", "rage-quit-montage",
            "chill-highlights", "kill-montage", "session-story",
            "tiktok-vertical", "edu-breakdown", "hype-montage", "squad-moments",
        ]
        total_usage = sum(profile.template_usage.values()) or 1
        for tid in all_templates:
            vec.append(profile.template_usage.get(tid, 0) / total_usage)

        # Pacing
        vec.append(profile.pacing_preference)

        # Approval ratio
        total_records = len(profile.editing_history) or 1
        approved = sum(1 for r in profile.editing_history if r.feedback == "approved")
        vec.append(approved / total_records)

        return vec

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b) or not a:
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))

        if mag_a == 0 or mag_b == 0:
            return 0.0

        return dot / (mag_a * mag_b)

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def _profile_path(self, streamer_id: str) -> Path:
        """Get the filesystem path for a streamer's profile JSON."""
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in streamer_id)
        return self._profiles_dir / f"{safe_id}.json"

    @staticmethod
    def _profile_to_dict(profile: StreamerProfile) -> dict:
        """Convert a StreamerProfile to a JSON-serializable dict."""
        data = {}
        for k, v in profile.__dict__.items():
            if k == "editing_history":
                data[k] = [asdict(rec) if hasattr(rec, "__dataclass_fields__") else rec for rec in v]
            elif hasattr(v, "__dataclass_fields__"):
                data[k] = asdict(v)
            else:
                data[k] = v
        return data


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    memory = StreamerMemory()

    # Demo: create a profile and simulate feedback
    sid = "demo_streamer"
    profile = memory.load_profile(sid)
    profile.name = "DemoAndy"
    profile.platform = "twitch"
    profile.games = ["Valorant", "CS2"]
    memory.save_profile(profile)

    # Simulate some feedback
    templates = ["clutch-master", "clutch-master", "kill-montage", "hype-montage", "clutch-master"]
    ratings = [5, 4, 3, 4, 5]

    for i, (tid, rating) in enumerate(zip(templates, ratings)):
        fb = Feedback(
            rating=rating,
            action="approved" if rating >= 4 else "modified",
            modifications={"effects": 85} if rating < 4 else {},
        )
        memory.record_feedback(
            sid, f"clip_{i:03d}", fb,
            template_id=tid,
            enhancements={"bgm": 80, "subtitles": 50, "effects": 75, "hook": 90, "transitions": 65},
            video_analysis={"game": "Valorant", "genre": "fps", "intensity": 80, "mood": "intense"},
        )

    # Get recommendation
    rec = memory.recommend_template(sid, {"game": "Valorant", "genre": "fps"})
    print(f"\nRecommendation for {sid}:")
    print(f"  Template: {rec.template_id}")
    print(f"  Confidence: {rec.confidence:.2f}")
    print(f"  Predicted rating: {rec.predicted_rating:.1f}")
    print(f"  Reason: {rec.reason}")
    print(f"  Suggested enhancements: {rec.suggested_enhancements}")
    print(f"  Alternatives: {rec.alternatives}")

    # Preference vector
    pref = memory.learn_preferences(sid)
    print(f"\nPreference Vector:")
    print(f"  Template affinities: {pref.template_affinities}")
    print(f"  Mood: {pref.mood_preference}")
    print(f"  Complexity: {pref.complexity_preference}")
    print(f"  Pacing: {pref.pacing_center}")

    # Cleanup
    memory.delete_profile(sid)
    print("\nDemo complete.")
