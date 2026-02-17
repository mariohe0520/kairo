/**
 * @fileoverview KAIRO Enhancement Modules
 *
 * Five independent enhancement modules that post-process a clip plan
 * before final render. Each module can be dialled from 0-100 via the
 * template or persona system.
 *
 * Modules:
 *  1. BGM        — Background music selection & mixing
 *  2. Subtitles  — Speech-to-text → styled captions
 *  3. Effects    — Slow-mo, zoom, visual FX
 *  4. Hook       — First-3-second attention grabber
 *  5. Transitions — Cuts & blends between segments
 *
 * @module pipeline/enhancer
 */

import config from '../config.js';

// ─── Types ──────────────────────────────────────────────────────────────────

/**
 * @typedef {Object} EnhancementLevels
 * @property {number} bgm         - 0-100
 * @property {number} subtitles   - 0-100
 * @property {number} effects     - 0-100
 * @property {number} hook        - 0-100
 * @property {number} transitions - 0-100
 */

/**
 * @typedef {Object} ClipSegment
 * @property {number} start       - Start time in seconds
 * @property {number} end         - End time in seconds
 * @property {number} score       - Highlight score (0-100)
 * @property {string} phase       - Narrative phase (intro|build|climax|outro)
 * @property {Object} [enhancements] - Applied enhancement metadata
 */

/**
 * @typedef {Object} ClipPlan
 * @property {ClipSegment[]} segments
 * @property {string} templateId
 * @property {string} mood
 * @property {number} totalDuration
 * @property {EnhancementLevels} levels
 */

/**
 * @typedef {Object} BGMSuggestion
 * @property {string} category   - Music category / genre tag
 * @property {number} bpm        - Suggested BPM range center
 * @property {number} energy     - Energy level 0-100
 * @property {string} mood       - Mood tag
 * @property {boolean} fadeIn    - Whether to fade in at start
 * @property {boolean} fadeOut   - Whether to fade out at end
 * @property {number} mixLevel   - Volume mix level 0-100 (relative to game audio)
 */

/**
 * @typedef {Object} SubtitleEntry
 * @property {number} start   - Start time in seconds
 * @property {number} end     - End time in seconds
 * @property {string} text    - Caption text
 * @property {Object} style   - Styling metadata
 * @property {string} style.position - top | center | bottom
 * @property {string} style.size     - small | medium | large
 * @property {string} style.color    - Hex color
 * @property {boolean} style.bold
 * @property {string} style.font     - Font family
 * @property {number} style.outline  - Outline thickness (px)
 */

/**
 * @typedef {Object} EffectDirective
 * @property {string} type        - slowmo | zoom | shake | flash | vignette
 * @property {number} start       - Start time in seconds
 * @property {number} duration    - Duration in seconds
 * @property {Object} params      - Effect-specific parameters
 */

/**
 * @typedef {Object} HookDirective
 * @property {string} text         - Hook overlay text
 * @property {number} duration     - Duration in seconds (default 3)
 * @property {Object} zoom         - Zoom parameters
 * @property {number} zoom.factor  - Zoom multiplier (e.g. 1.3)
 * @property {number} zoom.x       - Zoom center x (0-1)
 * @property {number} zoom.y       - Zoom center y (0-1)
 * @property {Object} textStyle    - Text overlay styling
 */

/**
 * @typedef {Object} TransitionDirective
 * @property {string} type       - cut | crossfade | whip | glitch | zoom-through
 * @property {number} at         - Timestamp where transition occurs
 * @property {number} duration   - Transition duration in seconds
 * @property {Object} [params]   - Type-specific parameters
 */

// ─── 1. BGM Module ──────────────────────────────────────────────────────────

/**
 * Analyze clip mood and suggest a background music category.
 *
 * Maps mood strings to music categories with appropriate BPM,
 * energy, and mixing parameters. The intensity slider (0-100)
 * controls volume mix level and whether to fade in/out.
 *
 * @param {ClipPlan} clipPlan - The clip plan with mood and segments
 * @param {number}   level    - BGM intensity slider (0-100)
 * @returns {BGMSuggestion} Music suggestion metadata
 */
export function enhanceBGM(clipPlan, level) {
  const moodMap = {
    triumphant:  { category: 'orchestral-epic',    bpm: 140, energy: 85 },
    intense:     { category: 'electronic-hype',     bpm: 150, energy: 90 },
    chaotic:     { category: 'meme-edm',            bpm: 160, energy: 95 },
    chill:       { category: 'lofi-ambient',         bpm: 85,  energy: 30 },
  };

  const base = moodMap[clipPlan.mood] || moodMap.chill;

  return {
    category: base.category,
    bpm: base.bpm,
    energy: Math.round(base.energy * (level / 100)),
    mood: clipPlan.mood,
    fadeIn: level > 30,
    fadeOut: true,
    mixLevel: Math.round(level * 0.7), // BGM never louder than 70% of slider
  };
}

// ─── 2. Subtitles Module ────────────────────────────────────────────────────

/**
 * Generate styled caption entries for a clip plan.
 *
 * Currently a placeholder that creates timed subtitle slots
 * matching each segment. In production this would call a
 * speech-to-text API (Whisper, Deepgram, etc.) and align
 * the transcription to the video timeline.
 *
 * @param {ClipPlan} clipPlan - The clip plan
 * @param {number}   level    - Subtitle prominence slider (0-100)
 * @returns {SubtitleEntry[]} Array of caption entries
 */
export function enhanceSubtitles(clipPlan, level) {
  if (level === 0) return [];

  const sizeMap = (l) => {
    if (l > 75) return 'large';
    if (l > 40) return 'medium';
    return 'small';
  };

  return clipPlan.segments.map((seg, i) => ({
    start: seg.start,
    end: seg.end,
    text: `[Segment ${i + 1} — awaiting STT transcription]`,
    style: {
      position: 'bottom',
      size: sizeMap(level),
      color: clipPlan.mood === 'chaotic' ? '#FF4444' : '#FFFFFF',
      bold: level > 60,
      font: clipPlan.mood === 'chill' ? 'Inter' : 'Montserrat',
      outline: level > 50 ? 3 : 1,
    },
  }));
}

// ─── 3. Effects Module ──────────────────────────────────────────────────────

/**
 * Generate visual effect directives for highlight segments.
 *
 * Rules:
 * - High-score segments (≥80) in climax phase → slow-mo
 * - Clutch moments (score ≥ 90) → zoom to center
 * - Kill moments → brief slow-mo
 * - Chaotic mood → add screen shake
 *
 * The level slider scales effect intensity and frequency.
 *
 * @param {ClipPlan} clipPlan - The clip plan
 * @param {number}   level    - Effects intensity slider (0-100)
 * @returns {EffectDirective[]} Array of effect directives
 */
export function enhanceEffects(clipPlan, level) {
  if (level === 0) return [];

  const effects = [];
  const scoreThreshold = 100 - level; // Higher level = lower threshold

  for (const seg of clipPlan.segments) {
    if (seg.score < scoreThreshold) continue;

    // Slow-mo on high-score climax moments
    if (seg.phase === 'climax' && seg.score >= 80) {
      effects.push({
        type: 'slowmo',
        start: seg.start,
        duration: Math.min(seg.end - seg.start, 3),
        params: {
          factor: level > 70 ? 0.25 : 0.5, // Quarter-speed or half-speed
          rampIn: true,
          rampOut: true,
        },
      });
    }

    // Zoom on clutch moments
    if (seg.score >= 90) {
      effects.push({
        type: 'zoom',
        start: seg.start + 0.5,
        duration: 1.5,
        params: {
          factor: 1.2 + (level / 200), // 1.2x to 1.7x
          centerX: 0.5,
          centerY: 0.4, // Slightly above center (crosshair area)
          easing: 'easeInOutCubic',
        },
      });
    }

    // Screen shake for chaotic mood
    if (clipPlan.mood === 'chaotic' && level > 50) {
      effects.push({
        type: 'shake',
        start: seg.start,
        duration: 0.5,
        params: {
          intensity: level / 100,
          frequency: 15,
        },
      });
    }
  }

  return effects;
}

// ─── 4. Hook Module ─────────────────────────────────────────────────────────

/**
 * Generate a 3-second hook for the start of the clip.
 *
 * The hook is designed to stop the scroll on platforms like
 * TikTok / YouTube Shorts. It combines a text overlay with
 * a zoom into the most exciting moment.
 *
 * @param {ClipPlan} clipPlan - The clip plan
 * @param {number}   level    - Hook aggressiveness slider (0-100)
 * @returns {HookDirective} Hook configuration
 */
export function enhanceHook(clipPlan, level) {
  // Find the best moment to tease
  const bestSegment = clipPlan.segments.reduce(
    (best, seg) => (seg.score > best.score ? seg : best),
    { score: 0, start: 0 }
  );

  const hookTexts = {
    triumphant: 'THE COMEBACK NOBODY EXPECTED 🔥',
    intense:    'WATCH THIS CLUTCH 😤',
    chaotic:    'HE ACTUALLY RAGE QUIT 💀',
    chill:      'vibes were immaculate ✨',
  };

  const hookDuration = level > 70 ? 3 : level > 40 ? 2.5 : 2;

  return {
    text: hookTexts[clipPlan.mood] || 'WAIT FOR IT...',
    duration: hookDuration,
    zoom: {
      factor: 1 + (level / 200),  // 1.0x to 1.5x
      x: 0.5,
      y: 0.5,
    },
    textStyle: {
      font: clipPlan.mood === 'chill' ? 'Inter' : 'Bebas Neue',
      size: level > 60 ? 72 : 48,
      color: '#FFFFFF',
      stroke: '#000000',
      strokeWidth: level > 50 ? 4 : 2,
      position: 'center',
      animation: level > 70 ? 'slam' : 'fadeIn',
    },
    // Preview frame from best moment
    previewTimestamp: bestSegment.start,
  };
}

// ─── 5. Transitions Module ──────────────────────────────────────────────────

/**
 * Generate transition directives between clip segments.
 *
 * Transition type is determined by template style and the
 * level slider controls duration and complexity.
 *
 * @param {ClipPlan} clipPlan - The clip plan
 * @param {number}   level    - Transition complexity slider (0-100)
 * @returns {TransitionDirective[]} Array of transition directives
 */
export function enhanceTransitions(clipPlan, level) {
  if (level === 0 || clipPlan.segments.length < 2) return [];

  const styleMap = {
    'dramatic-cut': 'cut',
    'hard-cut':     'cut',
    'glitch-whip':  'glitch',
    'crossfade':    'crossfade',
  };

  // Resolve base transition type from template style or default
  const baseType = styleMap[clipPlan.templateTransitionStyle] || 'crossfade';

  const transitions = [];

  for (let i = 0; i < clipPlan.segments.length - 1; i++) {
    const current = clipPlan.segments[i];
    const next = clipPlan.segments[i + 1];

    // Phase change → more dramatic transition
    const phaseChange = current.phase !== next.phase;
    let type = baseType;

    if (phaseChange && level > 50) {
      // Upgrade transition on phase changes
      type = baseType === 'crossfade' ? 'zoom-through' : 'whip';
    }

    const baseDuration = type === 'cut' ? 0 : 0.3;
    const duration = baseDuration + (level / 400); // 0 to 0.55s extra

    transitions.push({
      type,
      at: current.end,
      duration: Math.round(duration * 100) / 100,
      params: {
        phaseChange,
        fromPhase: current.phase,
        toPhase: next.phase,
        // Glitch-specific
        ...(type === 'glitch' && {
          slices: Math.floor(level / 10),
          rgbShift: level > 60,
        }),
        // Crossfade-specific
        ...(type === 'crossfade' && {
          curve: 'easeInOut',
        }),
      },
    });
  }

  return transitions;
}

// ─── Orchestrator ───────────────────────────────────────────────────────────

/**
 * Apply all five enhancement modules to a clip plan.
 *
 * @param {ClipPlan}         clipPlan - The clip plan to enhance
 * @param {EnhancementLevels} levels  - Slider values for each module (0-100)
 * @returns {Object} Enhanced clip plan with all directives attached
 *
 * @example
 * const enhanced = applyEnhancements(clipPlan, {
 *   bgm: 80, subtitles: 60, effects: 75, hook: 90, transitions: 70,
 * });
 */
export function applyEnhancements(clipPlan, levels) {
  const planWithLevels = { ...clipPlan, levels };

  const bgm         = enhanceBGM(planWithLevels, levels.bgm);
  const subtitles   = enhanceSubtitles(planWithLevels, levels.subtitles);
  const effects     = enhanceEffects(planWithLevels, levels.effects);
  const hook        = enhanceHook(planWithLevels, levels.hook);
  const transitions = enhanceTransitions(planWithLevels, levels.transitions);

  return {
    ...planWithLevels,
    enhancements: {
      bgm,
      subtitles,
      effects,
      hook,
      transitions,
    },
  };
}

export default {
  enhanceBGM,
  enhanceSubtitles,
  enhanceEffects,
  enhanceHook,
  enhanceTransitions,
  applyEnhancements,
};
