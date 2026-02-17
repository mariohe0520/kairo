/**
 * @fileoverview Story Template Definitions for KAIRO
 *
 * Each template defines a narrative arc that shapes how highlights
 * are assembled into a final clip. Templates control pacing, mood,
 * music style, transitions, and default enhancement levels.
 *
 * @module pipeline/templates
 */

/**
 * @typedef {Object} StructureTiming
 * @property {number} intro   - Fraction of total duration for intro (0-1)
 * @property {number} build   - Fraction of total duration for build-up (0-1)
 * @property {number} climax  - Fraction of total duration for climax (0-1)
 * @property {number} outro   - Fraction of total duration for outro (0-1)
 */

/**
 * @typedef {Object} EnhancementDefaults
 * @property {number} bgm         - Background music intensity (0-100)
 * @property {number} subtitles   - Subtitle prominence (0-100)
 * @property {number} effects     - Visual effects intensity (0-100)
 * @property {number} hook        - Hook aggressiveness (0-100)
 * @property {number} transitions - Transition complexity (0-100)
 */

/**
 * @typedef {Object} StoryTemplate
 * @property {string}              id                   - Unique template identifier
 * @property {string}              name                 - Human-readable name
 * @property {string}              description          - What this template is best for
 * @property {StructureTiming}     structure            - Narrative arc timing splits
 * @property {string}              mood                 - Overall emotional tone
 * @property {string}              bgm_style            - Recommended BGM genre / vibe
 * @property {string}              transition_style     - Transition approach
 * @property {EnhancementDefaults} enhancement_defaults - Default slider values for 5 modules
 * @property {Object}              scoring              - How this template weighs highlight attributes
 * @property {number}              scoring.momentum_weight     - Weight for momentum shifts (0-1)
 * @property {number}              scoring.intensity_weight    - Weight for raw intensity (0-1)
 * @property {number}              scoring.surprise_weight     - Weight for surprise factor (0-1)
 */

/**
 * "Comeback King" — From behind to victory.
 * Prioritises momentum shifts: low points followed by high points.
 * The intro sets up the deficit, the build shows the grind,
 * the climax is the turning point, and the outro is the celebration.
 *
 * @type {StoryTemplate}
 */
export const comebackKing = {
  id: 'comeback-king',
  name: 'Comeback King',
  description: 'Highlights dramatic reversals — getting destroyed then clawing back to win.',
  structure: {
    intro: 0.10,   // Brief scene-set: show the deficit
    build: 0.35,   // Extended struggle, tension rising
    climax: 0.40,  // The turn + the pop-off
    outro: 0.15,   // Victory lap / reaction
  },
  mood: 'triumphant',
  bgm_style: 'orchestral-epic',
  transition_style: 'dramatic-cut',
  enhancement_defaults: {
    bgm: 80,
    subtitles: 60,
    effects: 75,
    hook: 90,
    transitions: 70,
  },
  scoring: {
    momentum_weight: 0.6,
    intensity_weight: 0.25,
    surprise_weight: 0.15,
  },
};

/**
 * "Clutch Master" — Impossible plays under pressure.
 * Focuses on high-intensity singular moments: 1vX, last-second defuses,
 * buzzer-beaters. Structure front-loads context then hits hard.
 *
 * @type {StoryTemplate}
 */
export const clutchMaster = {
  id: 'clutch-master',
  name: 'Clutch Master',
  description: 'Showcases clutch moments — insane plays when everything is on the line.',
  structure: {
    intro: 0.08,
    build: 0.25,
    climax: 0.55,   // Heavy climax — multiple clutch moments back-to-back
    outro: 0.12,
  },
  mood: 'intense',
  bgm_style: 'electronic-hype',
  transition_style: 'hard-cut',
  enhancement_defaults: {
    bgm: 85,
    subtitles: 50,
    effects: 90,
    hook: 95,
    transitions: 60,
  },
  scoring: {
    momentum_weight: 0.2,
    intensity_weight: 0.5,
    surprise_weight: 0.3,
  },
};

/**
 * "Rage Quit Montage" — Chaos, tilts, and meltdowns.
 * Comedic / chaotic energy. Uses rapid cuts, exaggerated effects,
 * and meme-worthy moments. The "climax" is the biggest rage.
 *
 * @type {StoryTemplate}
 */
export const rageQuitMontage = {
  id: 'rage-quit-montage',
  name: 'Rage Quit Montage',
  description: 'Captures tilts, fails, and rage moments — funny, chaotic, shareable.',
  structure: {
    intro: 0.05,   // Jump right in
    build: 0.40,   // Escalating frustration
    climax: 0.35,  // Peak rage / the final straw
    outro: 0.20,   // Aftermath / "I'm done" moment
  },
  mood: 'chaotic',
  bgm_style: 'meme-edm',
  transition_style: 'glitch-whip',
  enhancement_defaults: {
    bgm: 70,
    subtitles: 85,    // Captions are key for comedy
    effects: 95,       // Maximum chaos
    hook: 80,
    transitions: 90,   // Rapid, jarring cuts
  },
  scoring: {
    momentum_weight: 0.15,
    intensity_weight: 0.35,
    surprise_weight: 0.5,   // Unexpected = funny
  },
};

/**
 * "Chill Highlights" — Relaxed, aesthetic recap.
 * Low intensity, smooth transitions, lo-fi vibes.
 * Good for long-form recaps or "best of the week" compilations.
 *
 * @type {StoryTemplate}
 */
export const chillHighlights = {
  id: 'chill-highlights',
  name: 'Chill Highlights',
  description: 'Smooth, relaxed highlight reel — aesthetic vibes over hype.',
  structure: {
    intro: 0.15,   // Slow, mood-setting opener
    build: 0.30,   // Gentle escalation
    climax: 0.30,  // Best moments, but no jarring spike
    outro: 0.25,   // Extended outro, let it breathe
  },
  mood: 'chill',
  bgm_style: 'lofi-ambient',
  transition_style: 'crossfade',
  enhancement_defaults: {
    bgm: 90,        // Music is the star
    subtitles: 40,
    effects: 30,     // Subtle
    hook: 45,        // Soft hook, not aggressive
    transitions: 85, // Smooth is key
  },
  scoring: {
    momentum_weight: 0.3,
    intensity_weight: 0.3,
    surprise_weight: 0.4,
  },
};

// ─── Registry ───────────────────────────────────────────────────────────────

/**
 * All available templates indexed by id.
 * @type {Map<string, StoryTemplate>}
 */
export const TEMPLATES = new Map([
  [comebackKing.id, comebackKing],
  [clutchMaster.id, clutchMaster],
  [rageQuitMontage.id, rageQuitMontage],
  [chillHighlights.id, chillHighlights],
]);

/**
 * Get a template by id.
 * @param {string} id - Template identifier
 * @returns {StoryTemplate|undefined}
 */
export function getTemplate(id) {
  return TEMPLATES.get(id);
}

/**
 * List all template ids.
 * @returns {string[]}
 */
export function listTemplateIds() {
  return [...TEMPLATES.keys()];
}

export default TEMPLATES;
