/**
 * @fileoverview Streamer Persona Matching for KAIRO
 *
 * Maps a streamer's personality profile to the optimal template
 * and enhancement settings. The persona system ensures that a
 * chill lo-fi streamer doesn't get an MLG-edit treatment and
 * vice versa.
 *
 * 5 detailed persona profiles with rich customization.
 *
 * @module pipeline/persona
 */

import { TEMPLATES, getTemplate } from './templates.js';

// ─── Types ──────────────────────────────────────────────────────────────────

/**
 * @typedef {Object} PersonaConfig
 * @property {string}   name               - Streamer display name
 * @property {string}   archetype          - Persona archetype label
 * @property {string}   bio                - Short bio / description
 * @property {string}   avatar             - Emoji avatar for UI
 * @property {number}   energy_level       - Energy level 1-10 (1 = zen, 10 = caffeine IV)
 * @property {string}   humor_style        - Humor style: dry | sarcastic | loud | wholesome | chaotic
 * @property {string[]} catchphrases       - Signature phrases the streamer uses
 * @property {string[]} games              - Preferred game genres
 * @property {string}   preferred_template - Template id preference (can be overridden)
 * @property {number}   edit_intensity     - How intense edits should be 1-10
 * @property {Object}   style_prefs        - Additional style preferences
 * @property {string}   style_prefs.captionStyle - minimal | standard | expressive | meme
 * @property {string}   style_prefs.colorScheme  - neon | pastel | monochrome | warm | cool
 * @property {boolean}  style_prefs.facecamFocus  - Whether to prioritize facecam reactions
 * @property {string}   style_prefs.musicTaste    - Music taste hint for BGM
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
 *   archetype: 'Chaos Gremlin',
 *   bio: 'Maximum chaos, zero chill',
 *   avatar: '💀',
 *   energy_level: 10,
 *   humor_style: 'chaotic',
 *   catchphrases: ['WHAT WAS THAT', 'düd'],
 *   games: ['FPS', 'Variety'],
 *   preferred_template: 'rage-quit-montage',
 *   edit_intensity: 9,
 *   style_prefs: { captionStyle: 'meme', colorScheme: 'neon', facecamFocus: true, musicTaste: 'edm' },
 * });
 */
export class StreamerPersona {
  /**
   * @param {PersonaConfig} config - Persona configuration
   */
  constructor(config) {
    this.name = config.name;
    this.archetype = config.archetype || 'Custom';
    this.bio = config.bio || '';
    this.avatar = config.avatar || '🎮';
    this.energy_level = Math.max(1, Math.min(10, config.energy_level));
    this.humor_style = config.humor_style || 'wholesome';
    this.catchphrases = config.catchphrases || [];
    this.games = config.games || [];
    this.preferred_template = config.preferred_template || '';
    this.edit_intensity = Math.max(1, Math.min(10, config.edit_intensity));
    this.style_prefs = {
      captionStyle: config.style_prefs?.captionStyle || 'standard',
      colorScheme: config.style_prefs?.colorScheme || 'cool',
      facecamFocus: config.style_prefs?.facecamFocus ?? false,
      musicTaste: config.style_prefs?.musicTaste || 'any',
    };
  }

  /**
   * Serialize persona to a plain object.
   * @returns {PersonaConfig}
   */
  toJSON() {
    return {
      name: this.name,
      archetype: this.archetype,
      bio: this.bio,
      avatar: this.avatar,
      energy_level: this.energy_level,
      humor_style: this.humor_style,
      catchphrases: this.catchphrases,
      games: this.games,
      preferred_template: this.preferred_template,
      edit_intensity: this.edit_intensity,
      style_prefs: { ...this.style_prefs },
    };
  }
}

// ─── Template Matching ──────────────────────────────────────────────────────

/**
 * Score how well a template fits a persona + highlight summary.
 * @private
 */
function scoreTemplateMatch(persona, highlights, template) {
  let score = 50;

  // Hard preference bonus
  if (persona.preferred_template === template.id) {
    score += 20;
  }

  // Energy alignment
  const energyMap = {
    'comeback-king': 7,
    'clutch-master': 8,
    'rage-quit-montage': 9,
    'chill-highlights': 3,
    'kill-montage': 8,
    'session-story': 5,
    'tiktok-vertical': 8,
    'edu-breakdown': 4,
    'hype-montage': 9,
    'squad-moments': 6,
  };
  const templateEnergy = energyMap[template.id] || 5;
  const energyDiff = Math.abs(persona.energy_level - templateEnergy);
  score -= energyDiff * 3;

  // Highlight characteristics
  if (template.id === 'comeback-king' && highlights.momentumSwings > 3) score += 15;
  if (template.id === 'clutch-master' && highlights.clutchCount > 2) score += 15;
  if (template.id === 'rage-quit-montage' && highlights.rageIndicators > 2) score += 15;
  if (template.id === 'chill-highlights' && highlights.avgScore < 50) score += 10;
  if (template.id === 'kill-montage' && highlights.maxScore >= 95) score += 15;
  if (template.id === 'session-story' && highlights.count > 10) score += 12;
  if (template.id === 'tiktok-vertical' && highlights.maxScore >= 85) score += 10;
  if (template.id === 'hype-montage' && highlights.avgScore > 70) score += 12;

  // Humor style compatibility
  const humorBonus = {
    'chaotic':   { 'rage-quit-montage': 10, 'clutch-master': 5, 'tiktok-vertical': 7 },
    'loud':      { 'clutch-master': 10, 'comeback-king': 8, 'hype-montage': 8 },
    'sarcastic': { 'rage-quit-montage': 8, 'chill-highlights': 5, 'edu-breakdown': 7 },
    'dry':       { 'chill-highlights': 10, 'comeback-king': 5, 'session-story': 7 },
    'wholesome': { 'chill-highlights': 10, 'comeback-king': 8, 'squad-moments': 10 },
  };
  const bonus = humorBonus[persona.humor_style]?.[template.id] || 0;
  score += bonus;

  return Math.max(0, Math.min(100, score));
}

/**
 * Pick the best template for a given persona and highlight set.
 *
 * @param {StreamerPersona}  persona    - The streamer persona
 * @param {HighlightSummary} highlights - Summary stats from highlight detection
 * @returns {{ template: StoryTemplate, score: number, allScores: Object.<string, number> }}
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
 * @param {StreamerPersona}  persona  - The streamer persona
 * @param {EnhancementDefaults} defaults - Template default levels
 * @returns {EnhancementDefaults} Adjusted enhancement levels
 */
export function customizeEnhancements(persona, defaults) {
  const e = persona.energy_level;
  const i = persona.edit_intensity;
  const energyFactor = e / 10;
  const intensityFactor = i / 10;

  const clamp = (v) => Math.max(0, Math.min(100, Math.round(v)));

  const bgm = clamp(defaults.bgm + (1 - energyFactor) * 15 - energyFactor * 10);
  const subtitleBonus = ['chaotic', 'loud', 'sarcastic'].includes(persona.humor_style) ? 20 : 0;
  const subtitles = clamp(defaults.subtitles + subtitleBonus * intensityFactor);
  const effects = clamp(defaults.effects * (0.5 + intensityFactor * 0.5) + energyFactor * 10);
  const hook = clamp(defaults.hook * (0.6 + energyFactor * 0.4) + intensityFactor * 5);
  const transitions = clamp(defaults.transitions * (0.5 + intensityFactor * 0.5) + energyFactor * 5);

  return { bgm, subtitles, effects, hook, transitions };
}

// ─── 5 Preset Persona Profiles ──────────────────────────────────────────────

/**
 * Pre-built persona profiles covering major streamer archetypes.
 * @type {Object.<string, StreamerPersona>}
 */
export const PRESET_PERSONAS = {
  /**
   * The Hype Machine — high-energy competitive player who pops off on kills.
   * Think: Sinatraa, TenZ, Tarik
   */
  hypeStreamer: new StreamerPersona({
    name: 'HypeAndy',
    archetype: 'The Hype Machine',
    bio: 'Lives for the pop-off moment. Every kill deserves a scream. Maximum hype, zero modesty.',
    avatar: '🔥',
    energy_level: 9,
    humor_style: 'loud',
    catchphrases: ['LET\'S GOOO', 'NO WAY', 'ABSOLUTELY INSANE', 'HE\'S CRACKED'],
    games: ['FPS', 'Battle Royale', 'Fighting'],
    preferred_template: 'clutch-master',
    edit_intensity: 8,
    style_prefs: {
      captionStyle: 'expressive',
      colorScheme: 'neon',
      facecamFocus: true,
      musicTaste: 'edm',
    },
  }),

  /**
   * The Zen Master — calm, analytical, vibes-focused.
   * Think: Lirik, Northernlion, CohhCarnage
   */
  chillStreamer: new StreamerPersona({
    name: 'ZenVibes',
    archetype: 'The Zen Master',
    bio: 'Unshakeable calm. Even a 1v5 ace gets a casual "that was pretty good." Peak cozy content.',
    avatar: '🧘',
    energy_level: 3,
    humor_style: 'dry',
    catchphrases: ['that was neat', 'oh well', 'nice', 'we take those'],
    games: ['RPG', 'Strategy', 'Simulation', 'Indie'],
    preferred_template: 'chill-highlights',
    edit_intensity: 3,
    style_prefs: {
      captionStyle: 'minimal',
      colorScheme: 'pastel',
      facecamFocus: false,
      musicTaste: 'lofi',
    },
  }),

  /**
   * The Chaos Gremlin — tilts hard, rage quits, but it's content gold.
   * Think: xQc, Tyler1, IShowSpeed
   */
  chaosGremlin: new StreamerPersona({
    name: 'TiltLord',
    archetype: 'The Chaos Gremlin',
    bio: 'The desk has been replaced three times. Chat has a rage counter. Peak entertainment.',
    avatar: '💀',
    energy_level: 10,
    humor_style: 'chaotic',
    catchphrases: ['WHAT', 'I\'M DONE', 'THIS GAME IS BROKEN', 'ACTUAL AIMBOT', 'GG GO NEXT'],
    games: ['FPS', 'MOBA', 'Competitive'],
    preferred_template: 'rage-quit-montage',
    edit_intensity: 10,
    style_prefs: {
      captionStyle: 'meme',
      colorScheme: 'neon',
      facecamFocus: true,
      musicTaste: 'meme-music',
    },
  }),

  /**
   * The Tactician — calculated, educational, strategy-first.
   * Think: WarOwl, Viper, Bwipo
   */
  tactician: new StreamerPersona({
    name: 'SteadyAim',
    archetype: 'The Tactician',
    bio: 'Every play is calculated. Watches replays for fun. Could coach your team but prefers streaming.',
    avatar: '🧠',
    energy_level: 5,
    humor_style: 'sarcastic',
    catchphrases: ['calculated', 'ez', 'all skill no luck', 'as expected', 'textbook play'],
    games: ['FPS', 'Strategy', 'MOBA'],
    preferred_template: 'edu-breakdown',
    edit_intensity: 5,
    style_prefs: {
      captionStyle: 'standard',
      colorScheme: 'cool',
      facecamFocus: false,
      musicTaste: 'ambient',
    },
  }),

  /**
   * The Squad Captain — group dynamics, callouts, wholesome team energy.
   * Think: Valkyrae, Pokimane (squad streams), Sykkuno
   */
  squadCaptain: new StreamerPersona({
    name: 'SquadLeader',
    archetype: 'The Squad Captain',
    bio: 'The glue of every friend group stream. Best moments come from team chaos and accidental comedy.',
    avatar: '🤝',
    energy_level: 7,
    humor_style: 'wholesome',
    catchphrases: ['NICE ONE', 'WE GOT THIS', 'OH NO THEY\'RE COMING', 'REVIVE ME BRO', 'TEAM DIFF'],
    games: ['Battle Royale', 'Co-op', 'Party Games'],
    preferred_template: 'squad-moments',
    edit_intensity: 6,
    style_prefs: {
      captionStyle: 'expressive',
      colorScheme: 'warm',
      facecamFocus: true,
      musicTaste: 'indie-pop',
    },
  }),
};

/**
 * Get all preset personas as an array for UI rendering.
 * @returns {Array<{key: string, persona: StreamerPersona}>}
 */
export function getAllPersonas() {
  return Object.entries(PRESET_PERSONAS).map(([key, persona]) => ({ key, persona }));
}

export default {
  StreamerPersona,
  matchTemplate,
  customizeEnhancements,
  PRESET_PERSONAS,
  getAllPersonas,
};
