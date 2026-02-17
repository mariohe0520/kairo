/**
 * @fileoverview Streamer Persona Matching for KAIRO
 *
 * Maps a streamer's personality profile to the optimal template
 * and enhancement settings. The persona system ensures that a
 * chill lo-fi streamer doesn't get an MLG-edit treatment and
 * vice versa.
 *
 * @module pipeline/persona
 */

import { TEMPLATES, getTemplate } from './templates.js';

// ─── Types ──────────────────────────────────────────────────────────────────

/**
 * @typedef {Object} PersonaConfig
 * @property {string}   name               - Streamer display name
 * @property {number}   energy_level       - Energy level 1-10 (1 = zen, 10 = caffeine IV)
 * @property {string}   humor_style        - Humor style: dry | sarcastic | loud | wholesome | chaotic
 * @property {string[]} catchphrases       - Signature phrases the streamer uses
 * @property {string}   preferred_template - Template id preference (can be overridden)
 * @property {number}   edit_intensity     - How intense edits should be 1-10
 */

/**
 * @typedef {Object} HighlightSummary
 * @property {number} avgScore        - Average highlight score (0-100)
 * @property {number} maxScore        - Peak highlight score
 * @property {number} count           - Total number of highlights
 * @property {number} momentumSwings  - Number of big score changes
 * @property {number} clutchCount     - Number of clutch moments (score > 90)
 * @property {number} rageIndicators  - Number of probable rage moments
 */

// ─── StreamerPersona Class ──────────────────────────────────────────────────

/**
 * Represents a streamer's personality and editing preferences.
 *
 * @example
 * const persona = new StreamerPersona({
 *   name: 'xQc',
 *   energy_level: 10,
 *   humor_style: 'chaotic',
 *   catchphrases: ['WHAT WAS THAT', 'düd'],
 *   preferred_template: 'rage-quit-montage',
 *   edit_intensity: 9,
 * });
 */
export class StreamerPersona {
  /**
   * @param {PersonaConfig} config - Persona configuration
   */
  constructor(config) {
    /** @type {string} */
    this.name = config.name;

    /** @type {number} Energy level 1-10 */
    this.energy_level = Math.max(1, Math.min(10, config.energy_level));

    /** @type {string} */
    this.humor_style = config.humor_style || 'wholesome';

    /** @type {string[]} */
    this.catchphrases = config.catchphrases || [];

    /** @type {string} */
    this.preferred_template = config.preferred_template || '';

    /** @type {number} Edit intensity 1-10 */
    this.edit_intensity = Math.max(1, Math.min(10, config.edit_intensity));
  }

  /**
   * Serialize persona to a plain object.
   * @returns {PersonaConfig}
   */
  toJSON() {
    return {
      name: this.name,
      energy_level: this.energy_level,
      humor_style: this.humor_style,
      catchphrases: this.catchphrases,
      preferred_template: this.preferred_template,
      edit_intensity: this.edit_intensity,
    };
  }
}

// ─── Template Matching ──────────────────────────────────────────────────────

/**
 * Score how well a template fits a persona + highlight summary.
 *
 * Scoring factors:
 *  - Persona preference match (hard bonus)
 *  - Energy level alignment with template mood
 *  - Highlight characteristics (comebacks, clutches, rage)
 *  - Humor style compatibility
 *
 * @param {StreamerPersona}  persona    - The streamer persona
 * @param {HighlightSummary} highlights - Summary of detected highlights
 * @param {import('./templates.js').StoryTemplate} template - Template to score
 * @returns {number} Compatibility score (0-100)
 * @private
 */
function scoreTemplateMatch(persona, highlights, template) {
  let score = 50; // Baseline

  // ── Hard preference bonus ──
  if (persona.preferred_template === template.id) {
    score += 20;
  }

  // ── Energy alignment ──
  const energyMap = {
    'comeback-king':      7,
    'clutch-master':      8,
    'rage-quit-montage':  9,
    'chill-highlights':   3,
  };
  const templateEnergy = energyMap[template.id] || 5;
  const energyDiff = Math.abs(persona.energy_level - templateEnergy);
  score -= energyDiff * 3; // Penalty for mismatch

  // ── Highlight characteristics ──
  if (template.id === 'comeback-king' && highlights.momentumSwings > 3) {
    score += 15;
  }
  if (template.id === 'clutch-master' && highlights.clutchCount > 2) {
    score += 15;
  }
  if (template.id === 'rage-quit-montage' && highlights.rageIndicators > 2) {
    score += 15;
  }
  if (template.id === 'chill-highlights' && highlights.avgScore < 50) {
    score += 10; // Lower average = more chill session
  }

  // ── Humor style compatibility ──
  const humorBonus = {
    'chaotic':   { 'rage-quit-montage': 10, 'clutch-master': 5 },
    'loud':      { 'clutch-master': 10, 'comeback-king': 8 },
    'sarcastic': { 'rage-quit-montage': 8, 'chill-highlights': 5 },
    'dry':       { 'chill-highlights': 10, 'comeback-king': 5 },
    'wholesome': { 'chill-highlights': 10, 'comeback-king': 8 },
  };
  const bonus = humorBonus[persona.humor_style]?.[template.id] || 0;
  score += bonus;

  return Math.max(0, Math.min(100, score));
}

/**
 * Pick the best template for a given persona and highlight set.
 *
 * Scores every registered template against the persona and
 * highlight summary, then returns the highest-scoring one.
 * Falls back to the persona's preferred template if scores are tied.
 *
 * @param {StreamerPersona}  persona    - The streamer persona
 * @param {HighlightSummary} highlights - Summary stats from highlight detection
 * @returns {{ template: import('./templates.js').StoryTemplate, score: number, allScores: Object.<string, number> }}
 *
 * @example
 * const result = matchTemplate(persona, {
 *   avgScore: 72, maxScore: 98, count: 15,
 *   momentumSwings: 5, clutchCount: 3, rageIndicators: 1,
 * });
 * console.log(result.template.name); // "Clutch Master"
 */
export function matchTemplate(persona, highlights) {
  const allScores = {};
  let bestId = null;
  let bestScore = -1;

  for (const [id, template] of TEMPLATES) {
    const s = scoreTemplateMatch(persona, highlights, template);
    allScores[id] = s;

    if (s > bestScore) {
      bestScore = s;
      bestId = id;
    }
  }

  // Tie-break: prefer persona's preferred template
  if (persona.preferred_template && allScores[persona.preferred_template] === bestScore) {
    bestId = persona.preferred_template;
  }

  return {
    template: getTemplate(bestId),
    score: bestScore,
    allScores,
  };
}

// ─── Enhancement Customization ──────────────────────────────────────────────

/**
 * Adjust the 5 enhancement sliders based on streamer persona.
 *
 * Takes the template's default enhancement levels and modifies them
 * to match the persona's energy and style. High-energy personas get
 * boosted effects/hooks; chill personas get boosted BGM and toned-down FX.
 *
 * @param {StreamerPersona}  persona  - The streamer persona
 * @param {import('./templates.js').EnhancementDefaults} defaults - Template default levels
 * @returns {import('./templates.js').EnhancementDefaults} Adjusted enhancement levels
 *
 * @example
 * const adjusted = customizeEnhancements(persona, {
 *   bgm: 80, subtitles: 60, effects: 75, hook: 90, transitions: 70,
 * });
 * // High-energy persona → effects bumped, hook maxed, bgm slightly lowered
 */
export function customizeEnhancements(persona, defaults) {
  const e = persona.energy_level;        // 1-10
  const i = persona.edit_intensity;      // 1-10
  const energyFactor = e / 10;           // 0.1 - 1.0
  const intensityFactor = i / 10;        // 0.1 - 1.0

  /**
   * Clamp a value to 0-100.
   * @param {number} v
   * @returns {number}
   */
  const clamp = (v) => Math.max(0, Math.min(100, Math.round(v)));

  // BGM: high-energy personas slightly lower BGM (game audio matters more),
  //       chill personas boost BGM (music is the vibe)
  const bgm = clamp(defaults.bgm + (1 - energyFactor) * 15 - energyFactor * 10);

  // Subtitles: chaotic / loud humor styles need more captions for comedy
  const subtitleBonus = ['chaotic', 'loud', 'sarcastic'].includes(persona.humor_style) ? 20 : 0;
  const subtitles = clamp(defaults.subtitles + subtitleBonus * intensityFactor);

  // Effects: scales directly with energy and edit intensity
  const effects = clamp(defaults.effects * (0.5 + intensityFactor * 0.5) + energyFactor * 10);

  // Hook: high-energy personas get aggressive hooks
  const hook = clamp(defaults.hook * (0.6 + energyFactor * 0.4) + intensityFactor * 5);

  // Transitions: high edit intensity = more complex transitions
  const transitions = clamp(defaults.transitions * (0.5 + intensityFactor * 0.5) + energyFactor * 5);

  return { bgm, subtitles, effects, hook, transitions };
}

// ─── Preset Personas (Examples) ─────────────────────────────────────────────

/**
 * Pre-built persona examples for testing.
 * @type {Object.<string, StreamerPersona>}
 */
export const PRESET_PERSONAS = {
  hypeStreamer: new StreamerPersona({
    name: 'HypeAndy',
    energy_level: 9,
    humor_style: 'loud',
    catchphrases: ['LET\'S GOOO', 'NO WAY', 'ABSOLUTELY INSANE'],
    preferred_template: 'clutch-master',
    edit_intensity: 8,
  }),

  chillStreamer: new StreamerPersona({
    name: 'ZenVibes',
    energy_level: 3,
    humor_style: 'dry',
    catchphrases: ['that was neat', 'oh well', 'nice'],
    preferred_template: 'chill-highlights',
    edit_intensity: 3,
  }),

  chaosGremlin: new StreamerPersona({
    name: 'TiltLord',
    energy_level: 10,
    humor_style: 'chaotic',
    catchphrases: ['WHAT', 'I\'M DONE', 'THIS GAME IS BROKEN'],
    preferred_template: 'rage-quit-montage',
    edit_intensity: 10,
  }),

  consistentPro: new StreamerPersona({
    name: 'SteadyAim',
    energy_level: 6,
    humor_style: 'sarcastic',
    catchphrases: ['calculated', 'ez', 'all skill no luck'],
    preferred_template: 'comeback-king',
    edit_intensity: 6,
  }),
};

export default {
  StreamerPersona,
  matchTemplate,
  customizeEnhancements,
  PRESET_PERSONAS,
};
