/**
 * @fileoverview Story Template Definitions for KAIRO
 *
 * Each template defines a narrative arc that shapes how highlights
 * are assembled into a final clip. Templates control pacing, mood,
 * music style, transitions, and default enhancement levels.
 *
 * 10 templates covering every major content style in gaming.
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
 * @property {string}              category             - Template category tag
 * @property {string}              icon                 - Emoji icon for UI
 * @property {number[]}            durationRange        - [min, max] suggested clip length in seconds
 * @property {StructureTiming}     structure            - Narrative arc timing splits
 * @property {string}              mood                 - Overall emotional tone
 * @property {string}              musicMood            - Music mood tag for BGM selection
 * @property {string}              bgm_style            - Recommended BGM genre / vibe
 * @property {string}              transition_style     - Transition approach
 * @property {EnhancementDefaults} enhancement_defaults - Default slider values for 5 modules
 * @property {Object}              scoring              - How this template weighs highlight attributes
 * @property {number}              scoring.momentum_weight     - Weight for momentum shifts (0-1)
 * @property {number}              scoring.intensity_weight    - Weight for raw intensity (0-1)
 * @property {number}              scoring.surprise_weight     - Weight for surprise factor (0-1)
 */

// ─── Template 1: Comeback King ──────────────────────────────────────────────

export const comebackKing = {
  id: 'comeback-king',
  name: 'Comeback King',
  description: 'Highlights dramatic reversals — getting destroyed then clawing back to win.',
  category: 'Narrative',
  icon: '👑',
  durationRange: [45, 120],
  structure: {
    intro: 0.10,
    build: 0.35,
    climax: 0.40,
    outro: 0.15,
  },
  mood: 'triumphant',
  musicMood: 'epic-orchestral',
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

// ─── Template 2: Clutch Master ──────────────────────────────────────────────

export const clutchMaster = {
  id: 'clutch-master',
  name: 'Clutch Master',
  description: 'Showcases clutch moments — insane plays when everything is on the line.',
  category: 'FPS',
  icon: '🎯',
  durationRange: [30, 90],
  structure: {
    intro: 0.08,
    build: 0.25,
    climax: 0.55,
    outro: 0.12,
  },
  mood: 'intense',
  musicMood: 'electronic-hype',
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

// ─── Template 3: Rage Quit Montage ──────────────────────────────────────────

export const rageQuitMontage = {
  id: 'rage-quit-montage',
  name: 'Rage Quit Montage',
  description: 'Captures tilts, fails, and rage moments — funny, chaotic, shareable.',
  category: 'Comedy',
  icon: '💀',
  durationRange: [30, 90],
  structure: {
    intro: 0.05,
    build: 0.40,
    climax: 0.35,
    outro: 0.20,
  },
  mood: 'chaotic',
  musicMood: 'meme-chaos',
  bgm_style: 'meme-edm',
  transition_style: 'glitch-whip',
  enhancement_defaults: {
    bgm: 70,
    subtitles: 85,
    effects: 95,
    hook: 80,
    transitions: 90,
  },
  scoring: {
    momentum_weight: 0.15,
    intensity_weight: 0.35,
    surprise_weight: 0.5,
  },
};

// ─── Template 4: Chill Highlights ───────────────────────────────────────────

export const chillHighlights = {
  id: 'chill-highlights',
  name: 'Chill Highlights',
  description: 'Smooth, relaxed highlight reel — aesthetic vibes over hype.',
  category: 'Universal',
  icon: '✨',
  durationRange: [60, 180],
  structure: {
    intro: 0.15,
    build: 0.30,
    climax: 0.30,
    outro: 0.25,
  },
  mood: 'chill',
  musicMood: 'lofi-chill',
  bgm_style: 'lofi-ambient',
  transition_style: 'crossfade',
  enhancement_defaults: {
    bgm: 90,
    subtitles: 40,
    effects: 30,
    hook: 45,
    transitions: 85,
  },
  scoring: {
    momentum_weight: 0.3,
    intensity_weight: 0.3,
    surprise_weight: 0.4,
  },
};

// ─── Template 5: Kill Montage ───────────────────────────────────────────────

export const killMontage = {
  id: 'kill-montage',
  name: 'Kill Montage',
  description: 'Rapid-fire kill compilation — headshots, multi-kills, ace rounds. Pure mechanical skill.',
  category: 'FPS',
  icon: '🔫',
  durationRange: [20, 60],
  structure: {
    intro: 0.05,
    build: 0.15,
    climax: 0.70,
    outro: 0.10,
  },
  mood: 'intense',
  musicMood: 'bass-heavy-electronic',
  bgm_style: 'dubstep-trap',
  transition_style: 'hard-cut',
  enhancement_defaults: {
    bgm: 90,
    subtitles: 20,
    effects: 95,
    hook: 85,
    transitions: 50,
  },
  scoring: {
    momentum_weight: 0.1,
    intensity_weight: 0.7,
    surprise_weight: 0.2,
  },
};

// ─── Template 6: Session Story ──────────────────────────────────────────────

export const sessionStory = {
  id: 'session-story',
  name: 'Session Story',
  description: 'Full session condensed into a 3-5 minute narrative with chapters, context, and emotional arc.',
  category: 'Narrative',
  icon: '📖',
  durationRange: [120, 300],
  structure: {
    intro: 0.12,
    build: 0.38,
    climax: 0.30,
    outro: 0.20,
  },
  mood: 'triumphant',
  musicMood: 'cinematic-journey',
  bgm_style: 'cinematic-ambient',
  transition_style: 'crossfade',
  enhancement_defaults: {
    bgm: 75,
    subtitles: 70,
    effects: 50,
    hook: 60,
    transitions: 80,
  },
  scoring: {
    momentum_weight: 0.45,
    intensity_weight: 0.25,
    surprise_weight: 0.30,
  },
};

// ─── Template 7: TikTok Vertical ────────────────────────────────────────────

export const tiktokVertical = {
  id: 'tiktok-vertical',
  name: 'TikTok Vertical',
  description: 'Optimized for 9:16 vertical — fast hook, peak moment, reaction. Under 60 seconds.',
  category: 'Short-Form',
  icon: '📱',
  durationRange: [15, 60],
  structure: {
    intro: 0.08,
    build: 0.20,
    climax: 0.55,
    outro: 0.17,
  },
  mood: 'intense',
  musicMood: 'trending-viral',
  bgm_style: 'trending-pop',
  transition_style: 'glitch-whip',
  enhancement_defaults: {
    bgm: 85,
    subtitles: 95,
    effects: 80,
    hook: 100,
    transitions: 75,
  },
  scoring: {
    momentum_weight: 0.15,
    intensity_weight: 0.45,
    surprise_weight: 0.40,
  },
};

// ─── Template 8: Educational Breakdown ──────────────────────────────────────

export const eduBreakdown = {
  id: 'edu-breakdown',
  name: 'Educational Breakdown',
  description: 'Annotated replay analysis — freeze frames, zoom callouts, step-by-step narration.',
  category: 'Educational',
  icon: '🎓',
  durationRange: [60, 240],
  structure: {
    intro: 0.10,
    build: 0.45,
    climax: 0.30,
    outro: 0.15,
  },
  mood: 'chill',
  musicMood: 'focused-ambient',
  bgm_style: 'study-ambient',
  transition_style: 'crossfade',
  enhancement_defaults: {
    bgm: 40,
    subtitles: 90,
    effects: 60,
    hook: 50,
    transitions: 70,
  },
  scoring: {
    momentum_weight: 0.40,
    intensity_weight: 0.30,
    surprise_weight: 0.30,
  },
};

// ─── Template 9: Hype Montage ───────────────────────────────────────────────

export const hypeMontage = {
  id: 'hype-montage',
  name: 'Hype Montage',
  description: 'Music-synced highlight reel — beat drops align with kills, cuts match the rhythm.',
  category: 'Universal',
  icon: '🔥',
  durationRange: [30, 90],
  structure: {
    intro: 0.07,
    build: 0.30,
    climax: 0.48,
    outro: 0.15,
  },
  mood: 'intense',
  musicMood: 'high-energy-edm',
  bgm_style: 'edm-festival',
  transition_style: 'hard-cut',
  enhancement_defaults: {
    bgm: 95,
    subtitles: 30,
    effects: 85,
    hook: 90,
    transitions: 80,
  },
  scoring: {
    momentum_weight: 0.20,
    intensity_weight: 0.50,
    surprise_weight: 0.30,
  },
};

// ─── Template 10: Duo / Squad Moments ───────────────────────────────────────

export const squadMoments = {
  id: 'squad-moments',
  name: 'Squad Moments',
  description: 'Best group plays, comms highlights, and team chemistry moments from duo/squad sessions.',
  category: 'Social',
  icon: '🤝',
  durationRange: [45, 150],
  structure: {
    intro: 0.12,
    build: 0.33,
    climax: 0.35,
    outro: 0.20,
  },
  mood: 'triumphant',
  musicMood: 'feel-good-upbeat',
  bgm_style: 'indie-pop',
  transition_style: 'crossfade',
  enhancement_defaults: {
    bgm: 65,
    subtitles: 85,
    effects: 55,
    hook: 70,
    transitions: 75,
  },
  scoring: {
    momentum_weight: 0.35,
    intensity_weight: 0.30,
    surprise_weight: 0.35,
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
  [killMontage.id, killMontage],
  [sessionStory.id, sessionStory],
  [tiktokVertical.id, tiktokVertical],
  [eduBreakdown.id, eduBreakdown],
  [hypeMontage.id, hypeMontage],
  [squadMoments.id, squadMoments],
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

/**
 * Get all templates as an array (useful for UI rendering).
 * @returns {StoryTemplate[]}
 */
export function getAllTemplates() {
  return [...TEMPLATES.values()];
}

/**
 * Get templates filtered by category.
 * @param {string} category
 * @returns {StoryTemplate[]}
 */
export function getTemplatesByCategory(category) {
  return [...TEMPLATES.values()].filter(t => t.category === category);
}

export default TEMPLATES;
