/**
 * @fileoverview KAIRO Story Engine — The Differentiator
 *
 * KAIRO doesn't just clip highlights — it creates STORIES from gameplay.
 * This module transforms raw highlight data into narrative arcs with:
 *
 *   Opening Hook → Rising Action → Climax → Outro
 *
 * Each story is personalized to the streamer's style and the template's
 * narrative structure. The story engine understands gameplay context
 * (kills, deaths, objectives, momentum shifts) and weaves them into
 * compelling content that feels authored, not auto-generated.
 *
 * @module pipeline/story-engine
 */

// ─── Types ──────────────────────────────────────────────────────────────────

/**
 * @typedef {Object} StoryBeat
 * @property {string} phase       - Narrative phase: hook | rising | climax | falling | outro
 * @property {string} type        - Beat type: moment | transition | context | reaction
 * @property {number} start       - Start timestamp in source video (seconds)
 * @property {number} end         - End timestamp in source video (seconds)
 * @property {number} intensity   - Emotional intensity 0-100
 * @property {string} description - Human-readable description of what happens
 * @property {Object} metadata    - Additional metadata for rendering
 * @property {string} [metadata.overlayText]   - Text overlay suggestion
 * @property {string} [metadata.effectHint]    - Suggested visual effect
 * @property {string} [metadata.musicCue]      - Music intensity cue (build | drop | quiet | sustain)
 * @property {number} [metadata.pacing]        - Playback speed suggestion (0.25 = quarter, 1 = normal, 2 = fast)
 */

/**
 * @typedef {Object} StoryArc
 * @property {string}      id           - Unique story ID
 * @property {string}      title        - Auto-generated story title
 * @property {string}      logline      - One-sentence summary (like a movie logline)
 * @property {StoryBeat[]} beats        - Ordered sequence of story beats
 * @property {Object}      structure    - Arc metadata
 * @property {number}      structure.hookEnd       - Timestamp where hook ends
 * @property {number}      structure.risingEnd     - Timestamp where rising action ends
 * @property {number}      structure.climaxEnd     - Timestamp where climax ends
 * @property {number}      structure.totalDuration - Total story duration
 * @property {Object}      emotionCurve - Emotion intensity at key points
 * @property {number}      emotionCurve.opening    - 0-100
 * @property {number}      emotionCurve.midpoint   - 0-100
 * @property {number}      emotionCurve.peak       - 0-100
 * @property {number}      emotionCurve.closing    - 0-100
 */

/**
 * @typedef {Object} GameplayMoment
 * @property {number} timestamp    - When it happened (seconds)
 * @property {string} type         - kill | death | objective | clutch | fail | reaction | combo
 * @property {number} score        - Excitement score 0-100
 * @property {string} description  - What happened
 * @property {number} [killCount]  - Number of kills in this moment
 * @property {boolean} [isMultiKill] - Whether it's a multi-kill
 * @property {boolean} [isClutch]  - Whether it's a clutch situation
 * @property {number} [teamScore]  - Team score at this point (if applicable)
 * @property {number} [enemyScore] - Enemy score at this point
 */

// ─── Story Engine ───────────────────────────────────────────────────────────

/**
 * The KAIRO Story Engine.
 *
 * Transforms gameplay highlights into narrative arcs. This is what makes
 * KAIRO different from every other clip tool — it doesn't just find cool
 * moments, it tells a STORY.
 *
 * @example
 * const engine = new StoryEngine();
 * const arc = engine.buildStoryArc(moments, template, persona);
 * console.log(arc.title);    // "The Impossible Comeback"
 * console.log(arc.logline);  // "Down 0-5, one player refuses to lose..."
 */
export class StoryEngine {
  constructor() {
    this.titleGenerators = {
      triumphant: [
        'The Impossible Comeback',
        'Against All Odds',
        'When Everything Clicked',
        'The Redemption Arc',
        'Never Count Them Out',
      ],
      intense: [
        'Built Different',
        'One Player Army',
        'The Carry Job',
        'Mechanical Perfection',
        'Absolutely Unreal',
      ],
      chaotic: [
        'How Did We Get Here',
        'The Tilt Saga',
        'Actual Madness',
        'From Bad to Worse to LOL',
        'The Ragequit Chronicles',
      ],
      chill: [
        'Good Vibes Only',
        'A Cozy Session',
        'The Highlights, Unfiltered',
        'Best Bits, No Stress',
        'Peak Comfort Gaming',
      ],
    };

    this.loglineTemplates = {
      triumphant: [
        'Down {deficit}, one player refuses to lose — and what happens next is legendary.',
        'It looked like an easy loss until the clutch gene activated.',
        'Sometimes the best stories start from the worst positions.',
      ],
      intense: [
        'When the aim is on and the reads are perfect, this is what happens.',
        '{kills} kills. {clutches} clutch rounds. Zero mercy.',
        'A mechanical masterclass that left everyone speechless.',
      ],
      chaotic: [
        'It started as a normal game. It did not stay that way.',
        'The tilt was real, the rage was real, and somehow it was all content.',
        'Warning: desk safety not guaranteed.',
      ],
      chill: [
        'Just a good session, captured in the best way possible.',
        'No drama, no rage — just pure gaming moments worth remembering.',
        'The kind of session you want to bottle up and keep forever.',
      ],
    };
  }

  /**
   * Build a complete narrative arc from gameplay moments.
   *
   * The algorithm:
   * 1. Identify the emotional contour of the session
   * 2. Find the natural climax point (highest score cluster)
   * 3. Work backwards to find the rising action
   * 4. Select a hook moment (either the climax teaser or a strong opener)
   * 5. Build the outro from post-climax moments
   * 6. Fill gaps with context beats and transitions
   *
   * @param {GameplayMoment[]} moments  - Detected gameplay moments
   * @param {import('./templates.js').StoryTemplate} template - Story template
   * @param {import('./persona.js').StreamerPersona} [persona] - Optional persona
   * @returns {StoryArc} Complete story arc
   */
  buildStoryArc(moments, template, persona = null) {
    if (!moments || moments.length === 0) {
      return this._emptyArc(template);
    }

    // Sort by timestamp
    const sorted = [...moments].sort((a, b) => a.timestamp - b.timestamp);

    // Find the climax — highest scoring cluster of moments
    const climaxCenter = this._findClimaxCenter(sorted);

    // Partition moments into narrative phases
    const phases = this._partitionIntoPhases(sorted, climaxCenter, template.structure);

    // Build story beats from phase assignments
    const beats = this._buildBeats(phases, template, persona);

    // Generate title and logline
    const mood = template.mood;
    const title = this._generateTitle(mood, moments);
    const logline = this._generateLogline(mood, moments);

    // Calculate emotion curve
    const emotionCurve = this._calculateEmotionCurve(beats);

    // Calculate structure timestamps
    const hookEnd = beats.filter(b => b.phase === 'hook').reduce((max, b) => Math.max(max, b.end), 0);
    const risingEnd = beats.filter(b => b.phase === 'rising').reduce((max, b) => Math.max(max, b.end), hookEnd);
    const climaxEnd = beats.filter(b => b.phase === 'climax').reduce((max, b) => Math.max(max, b.end), risingEnd);
    const totalDuration = beats.reduce((sum, b) => sum + (b.end - b.start), 0);

    return {
      id: `story_${Date.now().toString(36)}`,
      title,
      logline,
      beats,
      structure: { hookEnd, risingEnd, climaxEnd, totalDuration },
      emotionCurve,
    };
  }

  /**
   * Generate a mock story arc for demo/preview purposes.
   * @param {string} templateId - Template to base the mock on
   * @returns {StoryArc}
   */
  generateMockArc(templateId = 'comeback-king') {
    const mockMoments = [
      { timestamp: 12, type: 'death', score: 30, description: 'Caught off-guard in pistol round', killCount: 0 },
      { timestamp: 45, type: 'death', score: 25, description: 'Team down 0-3, morale crumbling', teamScore: 0, enemyScore: 3 },
      { timestamp: 78, type: 'kill', score: 55, description: 'First blood — a spark of hope', killCount: 1 },
      { timestamp: 120, type: 'clutch', score: 72, description: '1v2 clutch to save the round', killCount: 2, isClutch: true },
      { timestamp: 180, type: 'combo', score: 65, description: 'Eco round ace, the crowd goes wild', killCount: 5, isMultiKill: true },
      { timestamp: 240, type: 'objective', score: 60, description: 'Score tied up 5-5, momentum shift', teamScore: 5, enemyScore: 5 },
      { timestamp: 310, type: 'kill', score: 78, description: 'Opening pick on their best player', killCount: 1 },
      { timestamp: 355, type: 'clutch', score: 92, description: '1v3 clutch with 5 HP — the crowd erupts', killCount: 3, isClutch: true },
      { timestamp: 400, type: 'combo', score: 88, description: 'Triple kill to close out the half', killCount: 3, isMultiKill: true },
      { timestamp: 450, type: 'clutch', score: 96, description: 'Match point 1v4 — the impossible ace', killCount: 4, isClutch: true },
      { timestamp: 478, type: 'reaction', score: 85, description: 'Pure celebration — the comeback is complete' },
    ];

    const { getTemplate } = require('./templates.js');
    const template = getTemplate(templateId) || getTemplate('comeback-king');
    return this.buildStoryArc(mockMoments, template);
  }

  // ─── Private Methods ────────────────────────────────────────────────────

  /**
   * Find the center timestamp of the climax cluster.
   * @private
   */
  _findClimaxCenter(sortedMoments) {
    if (sortedMoments.length <= 2) {
      return sortedMoments[sortedMoments.length - 1].timestamp;
    }

    // Sliding window to find highest-scoring cluster
    const windowSize = Math.max(3, Math.floor(sortedMoments.length * 0.3));
    let bestScore = 0;
    let bestCenter = 0;

    for (let i = 0; i <= sortedMoments.length - windowSize; i++) {
      const window = sortedMoments.slice(i, i + windowSize);
      const totalScore = window.reduce((s, m) => s + m.score, 0);
      if (totalScore > bestScore) {
        bestScore = totalScore;
        const midIdx = i + Math.floor(windowSize / 2);
        bestCenter = sortedMoments[midIdx].timestamp;
      }
    }

    return bestCenter;
  }

  /**
   * Partition moments into narrative phases based on climax position.
   * @private
   */
  _partitionIntoPhases(sortedMoments, climaxCenter, structure) {
    const totalSpan = sortedMoments[sortedMoments.length - 1].timestamp - sortedMoments[0].timestamp;
    const hookBudget = totalSpan * structure.intro;
    const risingBudget = totalSpan * structure.build;
    const climaxBudget = totalSpan * structure.climax;

    const phases = { hook: [], rising: [], climax: [], falling: [], outro: [] };

    for (const moment of sortedMoments) {
      const relTime = moment.timestamp - sortedMoments[0].timestamp;
      const distFromClimax = Math.abs(moment.timestamp - climaxCenter);

      if (distFromClimax < climaxBudget / 2 && moment.score >= 70) {
        phases.climax.push(moment);
      } else if (moment.timestamp < climaxCenter - climaxBudget / 2) {
        if (relTime < hookBudget) {
          phases.hook.push(moment);
        } else {
          phases.rising.push(moment);
        }
      } else {
        phases.outro.push(moment);
      }
    }

    // Ensure climax has at least the top moment
    if (phases.climax.length === 0) {
      const best = sortedMoments.reduce((a, b) => a.score > b.score ? a : b);
      phases.climax.push(best);
    }

    return phases;
  }

  /**
   * Convert phased moments into story beats.
   * @private
   */
  _buildBeats(phases, template, persona) {
    const beats = [];
    const contextPadding = 2; // seconds before/after each moment

    // HOOK: Tease the climax or use a strong opener
    if (phases.hook.length > 0) {
      for (const moment of phases.hook) {
        beats.push({
          phase: 'hook',
          type: 'moment',
          start: Math.max(0, moment.timestamp - contextPadding),
          end: moment.timestamp + contextPadding,
          intensity: Math.min(80, moment.score + 20), // Hook is always high-energy
          description: moment.description,
          metadata: {
            overlayText: this._hookText(moment, template.mood),
            effectHint: 'zoom-pulse',
            musicCue: 'build',
            pacing: 1.0,
          },
        });
      }
    } else {
      // If no hook moments, create a flash-forward from climax
      const peakMoment = phases.climax[0];
      if (peakMoment) {
        beats.push({
          phase: 'hook',
          type: 'context',
          start: Math.max(0, peakMoment.timestamp - 1),
          end: peakMoment.timestamp + 1,
          intensity: 90,
          description: 'Flash-forward: preview of the climax',
          metadata: {
            overlayText: 'What you\'re about to see...',
            effectHint: 'flash-white',
            musicCue: 'drop',
            pacing: 0.5,
          },
        });
      }
    }

    // RISING ACTION
    for (const moment of phases.rising) {
      beats.push({
        phase: 'rising',
        type: 'moment',
        start: Math.max(0, moment.timestamp - contextPadding),
        end: moment.timestamp + contextPadding,
        intensity: moment.score,
        description: moment.description,
        metadata: {
          effectHint: moment.score > 70 ? 'slight-zoom' : 'none',
          musicCue: 'build',
          pacing: 1.0,
        },
      });

      // Add tension-building transitions between rising beats
      if (moment !== phases.rising[phases.rising.length - 1]) {
        beats.push({
          phase: 'rising',
          type: 'transition',
          start: moment.timestamp + contextPadding,
          end: moment.timestamp + contextPadding + 0.5,
          intensity: Math.floor(moment.score * 0.6),
          description: 'Tension transition',
          metadata: {
            effectHint: 'whip-pan',
            musicCue: 'sustain',
            pacing: 1.5,
          },
        });
      }
    }

    // CLIMAX — the peak of the story
    for (const moment of phases.climax) {
      const isThePeak = moment === phases.climax.reduce((a, b) => a.score > b.score ? a : b);

      beats.push({
        phase: 'climax',
        type: 'moment',
        start: Math.max(0, moment.timestamp - (isThePeak ? 3 : contextPadding)),
        end: moment.timestamp + (isThePeak ? 3 : contextPadding),
        intensity: moment.score,
        description: moment.description,
        metadata: {
          overlayText: isThePeak ? this._climaxText(moment, template.mood) : undefined,
          effectHint: isThePeak ? 'slowmo-zoom' : 'zoom',
          musicCue: isThePeak ? 'drop' : 'sustain',
          pacing: isThePeak ? 0.5 : 0.75, // Slow-mo for the peak moment
        },
      });

      // Add reaction beat after the peak
      if (isThePeak) {
        beats.push({
          phase: 'climax',
          type: 'reaction',
          start: moment.timestamp + 3,
          end: moment.timestamp + 5,
          intensity: 85,
          description: 'Player/streamer reaction to the peak moment',
          metadata: {
            effectHint: 'facecam-zoom',
            musicCue: 'sustain',
            pacing: 1.0,
          },
        });
      }
    }

    // OUTRO — resolution, celebration, or contemplation
    for (const moment of phases.outro) {
      beats.push({
        phase: 'outro',
        type: moment.type === 'reaction' ? 'reaction' : 'moment',
        start: Math.max(0, moment.timestamp - contextPadding),
        end: moment.timestamp + contextPadding,
        intensity: Math.max(30, moment.score - 20), // Outro winds down
        description: moment.description,
        metadata: {
          effectHint: 'none',
          musicCue: 'quiet',
          pacing: 1.0,
        },
      });
    }

    // Sort beats by start time
    beats.sort((a, b) => a.start - b.start);

    return beats;
  }

  /**
   * Generate hook overlay text based on mood.
   * @private
   */
  _hookText(moment, mood) {
    const templates = {
      triumphant: ['It wasn\'t looking good...', 'Down bad, but watch this:', 'The comeback starts HERE'],
      intense: ['Ready?', 'Lock in.', 'This is the round.'],
      chaotic: ['Things are about to go wrong.', 'The tilt begins.', 'Oh no.'],
      chill: ['Let me show you something cool.', 'This one\'s special.', 'Watch this.'],
    };
    const pool = templates[mood] || templates.chill;
    return pool[Math.floor(Math.random() * pool.length)];
  }

  /**
   * Generate climax overlay text.
   * @private
   */
  _climaxText(moment, mood) {
    if (moment.isClutch) return 'THE CLUTCH.';
    if (moment.isMultiKill) return `${moment.killCount}K.`;
    const texts = {
      triumphant: 'THE MOMENT.',
      intense: 'INSANE.',
      chaotic: 'WHAT.',
      chill: '✨',
    };
    return texts[mood] || 'THE PLAY.';
  }

  /**
   * Generate a story title.
   * @private
   */
  _generateTitle(mood, moments) {
    const pool = this.titleGenerators[mood] || this.titleGenerators.chill;
    return pool[Math.floor(Math.random() * pool.length)];
  }

  /**
   * Generate a logline.
   * @private
   */
  _generateLogline(mood, moments) {
    const pool = this.loglineTemplates[mood] || this.loglineTemplates.chill;
    let logline = pool[Math.floor(Math.random() * pool.length)];

    const kills = moments.filter(m => m.type === 'kill' || m.type === 'combo')
      .reduce((s, m) => s + (m.killCount || 1), 0);
    const clutches = moments.filter(m => m.isClutch).length;

    logline = logline.replace('{kills}', kills.toString());
    logline = logline.replace('{clutches}', clutches.toString());
    logline = logline.replace('{deficit}', '0-5');

    return logline;
  }

  /**
   * Calculate the emotion curve across the story.
   * @private
   */
  _calculateEmotionCurve(beats) {
    if (beats.length === 0) {
      return { opening: 0, midpoint: 0, peak: 0, closing: 0 };
    }

    const hookBeats = beats.filter(b => b.phase === 'hook');
    const risingBeats = beats.filter(b => b.phase === 'rising');
    const climaxBeats = beats.filter(b => b.phase === 'climax');
    const outroBeats = beats.filter(b => b.phase === 'outro');

    const avg = (arr) => arr.length > 0
      ? Math.round(arr.reduce((s, b) => s + b.intensity, 0) / arr.length)
      : 0;

    return {
      opening: avg(hookBeats) || 60,
      midpoint: avg(risingBeats) || 50,
      peak: Math.max(...climaxBeats.map(b => b.intensity), 0) || 95,
      closing: avg(outroBeats) || 40,
    };
  }

  /**
   * Return an empty arc for when there's no content.
   * @private
   */
  _emptyArc(template) {
    return {
      id: `story_empty_${Date.now().toString(36)}`,
      title: 'No Story Yet',
      logline: 'Upload a VOD to generate your story.',
      beats: [],
      structure: { hookEnd: 0, risingEnd: 0, climaxEnd: 0, totalDuration: 0 },
      emotionCurve: { opening: 0, midpoint: 0, peak: 0, closing: 0 },
    };
  }
}

export default StoryEngine;
