/**
 * @fileoverview KAIRO VOD Analysis Pipeline — Main Analyzer
 *
 * Orchestrates the full pipeline:
 *   Video → Frame Extraction → Highlight Detection →
 *   Template Selection → Narrative Building → Enhancement →
 *   Final Clip Generation
 *
 * @module pipeline/analyzer
 */

import { execFile } from 'node:child_process';
import { mkdir, readdir, rm } from 'node:fs/promises';
import { join, basename, extname } from 'node:path';
import { promisify } from 'node:util';
import { randomUUID } from 'node:crypto';

import config from '../config.js';
import { getTemplate, listTemplateIds } from './templates.js';
import { applyEnhancements } from './enhancer.js';
import { matchTemplate, customizeEnhancements } from './persona.js';

const execFileAsync = promisify(execFile);

// ─── Types ──────────────────────────────────────────────────────────────────

/**
 * @typedef {Object} AnalyzeOptions
 * @property {number}  [fps=1]          - Frame extraction rate
 * @property {string}  [templateId]     - Force a specific template (skip auto-selection)
 * @property {import('./persona.js').StreamerPersona} [persona] - Streamer persona for customization
 * @property {number}  [maxDuration]    - Max output clip duration in seconds
 * @property {string}  [outputPath]     - Custom output file path
 * @property {boolean} [dryRun=false]   - If true, return clip plan without rendering
 * @property {boolean} [verbose]        - Enable verbose logging
 */

/**
 * @typedef {Object} FrameData
 * @property {string} path       - Path to the extracted frame image
 * @property {number} timestamp  - Timestamp in seconds within the video
 * @property {number} index      - Frame index (0-based)
 */

/**
 * @typedef {Object} Highlight
 * @property {number} timestamp  - Timestamp in seconds
 * @property {number} score      - Excitement score (0-100)
 * @property {number} frameIndex - Index of the source frame
 * @property {string} reason     - Human-readable reason for the score
 */

/**
 * @typedef {Object} ClipSegment
 * @property {number} start  - Start time in seconds
 * @property {number} end    - End time in seconds
 * @property {number} score  - Highlight score
 * @property {string} phase  - Narrative phase (intro | build | climax | outro)
 */

/**
 * @typedef {Object} ClipPlan
 * @property {string}        id             - Unique plan ID
 * @property {string}        videoPath      - Source video path
 * @property {string}        templateId     - Selected template ID
 * @property {string}        mood           - Template mood
 * @property {string}        templateTransitionStyle - Transition style from template
 * @property {ClipSegment[]} segments       - Ordered clip segments
 * @property {number}        totalDuration  - Sum of segment durations
 * @property {Object}        [enhancements] - Applied enhancements (after enhance step)
 */

/**
 * @typedef {Object} AnalyzeResult
 * @property {string}       id          - Pipeline run ID
 * @property {ClipPlan}     clipPlan    - The generated clip plan
 * @property {Highlight[]}  highlights  - All detected highlights
 * @property {string}       [outputPath] - Path to rendered clip (absent in dryRun)
 * @property {Object}       timing      - Performance timing
 * @property {number}       timing.extractMs
 * @property {number}       timing.detectMs
 * @property {number}       timing.buildMs
 * @property {number}       timing.renderMs
 * @property {number}       timing.totalMs
 */

// ─── VODAnalyzer Class ──────────────────────────────────────────────────────

/**
 * Main VOD analysis pipeline.
 *
 * @example
 * import { VODAnalyzer } from './pipeline/analyzer.js';
 *
 * const analyzer = new VODAnalyzer();
 * const result = await analyzer.analyze('/path/to/vod.mp4', {
 *   fps: 1,
 *   persona: myPersona,
 *   dryRun: false,
 * });
 * console.log(`Clip saved to: ${result.outputPath}`);
 */
export class VODAnalyzer {
  /**
   * Create a new VODAnalyzer.
   * @param {Object} [overrides] - Override default config values
   */
  constructor(overrides = {}) {
    /** @type {typeof config} */
    this.config = { ...config, ...overrides };

    /** @private */
    this._log = this.config.pipeline?.verbose ? console.log.bind(console, '[KAIRO]') : () => {};
  }

  // ── Main Entry Point ────────────────────────────────────────────────────

  /**
   * Run the full analysis pipeline on a video file.
   *
   * @param {string}         videoPath - Path to the source VOD file
   * @param {AnalyzeOptions} [options={}] - Pipeline options
   * @returns {Promise<AnalyzeResult>} Analysis result with clip plan and output path
   */
  async analyze(videoPath, options = {}) {
    const runId = randomUUID().slice(0, 8);
    const verbose = options.verbose ?? this.config.pipeline?.verbose;
    const log = verbose ? console.log.bind(console, `[KAIRO:${runId}]`) : () => {};

    log(`Starting analysis of: ${videoPath}`);
    const t0 = Date.now();

    // Step 1: Extract frames
    const t1 = Date.now();
    const fps = options.fps ?? this.config.extraction?.defaultFps ?? 1;
    const frames = await this.extractFrames(videoPath, fps);
    const extractMs = Date.now() - t1;
    log(`Extracted ${frames.length} frames in ${extractMs}ms`);

    // Step 2: Detect highlights
    const t2 = Date.now();
    const highlights = await this.detectHighlights(frames);
    const detectMs = Date.now() - t2;
    log(`Detected ${highlights.length} highlights in ${detectMs}ms`);

    // Step 3: Select template
    let template;
    if (options.templateId) {
      template = getTemplate(options.templateId);
      if (!template) {
        throw new Error(
          `Unknown template "${options.templateId}". Available: ${listTemplateIds().join(', ')}`
        );
      }
    } else if (options.persona) {
      const summary = this._summarizeHighlights(highlights);
      const match = matchTemplate(options.persona, summary);
      template = match.template;
      log(`Auto-selected template: ${template.name} (score: ${match.score})`);
    } else {
      // Default to "Chill Highlights" when no persona or template specified
      template = getTemplate('chill-highlights');
    }

    // Step 4: Build narrative
    const t3 = Date.now();
    const maxDuration = options.maxDuration ?? this.config.pipeline?.maxOutputDuration ?? 600;
    let clipPlan = this.buildNarrative(highlights, template, maxDuration);
    clipPlan.videoPath = videoPath;
    clipPlan.id = runId;
    const buildMs = Date.now() - t3;
    log(`Built narrative with ${clipPlan.segments.length} segments in ${buildMs}ms`);

    // Step 5: Apply enhancements
    let enhancementLevels = { ...template.enhancement_defaults };
    if (options.persona) {
      enhancementLevels = customizeEnhancements(options.persona, enhancementLevels);
      log('Customized enhancements for persona:', enhancementLevels);
    }
    clipPlan = applyEnhancements(clipPlan, enhancementLevels);

    // Step 6: Render (or dry run)
    let outputPath = null;
    let renderMs = 0;
    if (!options.dryRun) {
      const t4 = Date.now();
      outputPath = await this.generateClip(videoPath, clipPlan, options.outputPath);
      renderMs = Date.now() - t4;
      log(`Rendered clip in ${renderMs}ms → ${outputPath}`);
    } else {
      log('Dry run — skipping render');
    }

    const totalMs = Date.now() - t0;
    log(`Pipeline complete in ${totalMs}ms`);

    // Cleanup temp frames
    await this._cleanupFrames(frames).catch(() => {});

    return {
      id: runId,
      clipPlan,
      highlights,
      outputPath,
      timing: { extractMs, detectMs, buildMs, renderMs, totalMs },
    };
  }

  // ── Frame Extraction ────────────────────────────────────────────────────

  /**
   * Extract frames from a video at the specified FPS using ffmpeg.
   *
   * Creates a temporary directory and writes JPEG frames as
   * `frame_000001.jpg`, `frame_000002.jpg`, etc.
   *
   * @param {string} videoPath - Path to the source video
   * @param {number} [fps=1]   - Frames per second to extract
   * @returns {Promise<FrameData[]>} Array of extracted frame metadata
   */
  async extractFrames(videoPath, fps = 1) {
    const tempDir = join(
      this.config.extraction?.tempDir || '/tmp/kairo-frames',
      randomUUID().slice(0, 8)
    );
    await mkdir(tempDir, { recursive: true });

    const framePattern = join(tempDir, 'frame_%06d.jpg');
    const ffmpegBin = this.config.ffmpeg?.bin || 'ffmpeg';

    const args = [
      '-i', videoPath,
      '-vf', `fps=${fps}`,
      '-q:v', String(this.config.extraction?.frameQuality ?? 2),
      '-threads', String(this.config.ffmpeg?.threads ?? 0),
      framePattern,
      '-y',       // Overwrite
      '-loglevel', 'warning',
    ];

    this._log(`ffmpeg ${args.join(' ')}`);

    try {
      await execFileAsync(ffmpegBin, args, { timeout: 300_000 });
    } catch (err) {
      throw new Error(`Frame extraction failed: ${err.message}`);
    }

    // Read extracted frames and build metadata
    const files = (await readdir(tempDir))
      .filter((f) => f.startsWith('frame_') && f.endsWith('.jpg'))
      .sort();

    return files.map((file, index) => ({
      path: join(tempDir, file),
      timestamp: index / fps,
      index,
    }));
  }

  // ── Highlight Detection ─────────────────────────────────────────────────

  /**
   * Score each frame for "excitement" (0-100).
   *
   * **Current implementation: enhanced mock with realistic patterns.**
   * In production, this will call Gemini Flash or TwelveLabs to
   * analyze frame content (kills, deaths, clutch situations, chat
   * spam spikes, audio peaks, etc.).
   *
   * The mock generates realistic highlight distributions with:
   * - Kill moments with multi-kill detection
   * - Clutch situations (1vX)
   * - Emotion peaks (rage, celebration, surprise)
   * - Objective plays (plants, defuses, captures)
   * - Momentum shifts
   *
   * @param {FrameData[]} frames - Extracted frame data
   * @returns {Promise<Highlight[]>} Scored highlights (only frames above threshold)
   */
  async detectHighlights(frames) {
    const threshold = this.config.highlights?.minScore ?? 60;
    const minGap = this.config.highlights?.minGapSeconds ?? 5;
    const maxHighlights = this.config.highlights?.maxHighlights ?? 20;

    // Generate realistic gameplay events across the timeline
    const totalFrames = frames.length;
    const events = this._generateMockGameplayEvents(totalFrames);

    const allScored = frames.map((frame, i) => {
      // Base activity level with natural variance
      const noise = Math.abs(Math.sin(i * 0.7) * 15 + Math.cos(i * 1.3) * 15);
      const tension = (i / totalFrames) * 20;
      const jitter = Math.random() * 8;

      // Check if this frame aligns with a gameplay event
      const event = events.find(e => Math.abs(e.frameIndex - i) < 3);
      const eventBonus = event ? event.score : 0;
      const eventType = event ? event.type : null;

      const score = Math.min(100, Math.round(noise + tension + jitter + eventBonus));
      const reasons = [];
      const metadata = {};

      if (event) {
        reasons.push(event.reason);
        metadata.eventType = event.type;
        metadata.killCount = event.killCount || 0;
        metadata.isClutch = event.isClutch || false;
        metadata.isMultiKill = event.isMultiKill || false;
        metadata.emotionType = event.emotionType || null;
      }
      if (tension > 15) reasons.push('late-game tension');
      if (score > 85) reasons.push('high excitement composite');

      return {
        timestamp: frame.timestamp,
        score,
        frameIndex: frame.index,
        reason: reasons.length > 0 ? reasons.join(', ') : 'baseline activity',
        type: eventType || 'ambient',
        metadata,
      };
    });

    // Filter above threshold
    let highlights = allScored.filter((h) => h.score >= threshold);

    // Enforce minimum gap
    highlights = this._deduplicateHighlights(highlights, minGap);

    // Cap at max
    highlights = highlights
      .sort((a, b) => b.score - a.score)
      .slice(0, maxHighlights)
      .sort((a, b) => a.timestamp - b.timestamp);

    return highlights;
  }

  /**
   * Generate mock gameplay events for realistic analysis output.
   * Creates a believable distribution of kills, clutches, objectives,
   * and emotion peaks across a video timeline.
   *
   * @param {number} totalFrames - Total number of frames
   * @returns {Array<Object>} Mock gameplay events
   * @private
   */
  _generateMockGameplayEvents(totalFrames) {
    const events = [];

    // Kill moments — scattered throughout with clusters
    const killTimings = [0.08, 0.15, 0.22, 0.35, 0.42, 0.55, 0.63, 0.72, 0.78, 0.85, 0.92];
    for (const t of killTimings) {
      const isMulti = Math.random() > 0.7;
      const killCount = isMulti ? Math.floor(Math.random() * 3) + 2 : 1;
      events.push({
        frameIndex: Math.floor(t * totalFrames),
        type: 'kill',
        score: isMulti ? 55 + killCount * 10 : 35 + Math.random() * 20,
        reason: isMulti ? `multi-kill (${killCount}K)` : 'kill confirmed',
        killCount,
        isMultiKill: isMulti,
      });
    }

    // Clutch moments — rare, high-value
    const clutchTimings = [0.45, 0.75, 0.88];
    for (const t of clutchTimings) {
      const vsCount = Math.floor(Math.random() * 3) + 2;
      events.push({
        frameIndex: Math.floor(t * totalFrames),
        type: 'clutch',
        score: 75 + Math.random() * 25,
        reason: `1v${vsCount} clutch situation`,
        isClutch: true,
        killCount: vsCount,
      });
    }

    // Emotion peaks — reactions
    const emotionTimings = [0.12, 0.48, 0.65, 0.90];
    const emotionTypes = ['celebration', 'surprise', 'frustration', 'celebration'];
    for (let i = 0; i < emotionTimings.length; i++) {
      events.push({
        frameIndex: Math.floor(emotionTimings[i] * totalFrames),
        type: 'emotion',
        score: 40 + Math.random() * 35,
        reason: `emotion peak: ${emotionTypes[i]}`,
        emotionType: emotionTypes[i],
      });
    }

    // Objective plays
    const objTimings = [0.30, 0.60, 0.82];
    const objTypes = ['bomb plant', 'objective captured', 'round-winning defuse'];
    for (let i = 0; i < objTimings.length; i++) {
      events.push({
        frameIndex: Math.floor(objTimings[i] * totalFrames),
        type: 'objective',
        score: 45 + Math.random() * 30,
        reason: objTypes[i],
      });
    }

    return events;
  }

  // ── Narrative Building ──────────────────────────────────────────────────

  /**
   * Build a clip plan by distributing highlights across a narrative arc.
   *
   * The template's structure defines what fraction of the clip is
   * intro, build, climax, and outro. Highlights are sorted by score
   * and assigned to phases — the best moments go to climax, medium
   * ones to build, and scene-setters to intro/outro.
   *
   * @param {Highlight[]} highlights - Detected highlights (chronological)
   * @param {import('./templates.js').StoryTemplate} template - Story template
   * @param {number} [maxDuration=600] - Maximum clip duration in seconds
   * @returns {ClipPlan} The clip plan ready for enhancement + render
   */
  buildNarrative(highlights, template, maxDuration = 600) {
    if (highlights.length === 0) {
      return {
        id: '',
        videoPath: '',
        templateId: template.id,
        mood: template.mood,
        templateTransitionStyle: template.transition_style,
        segments: [],
        totalDuration: 0,
      };
    }

    const padding = this.config.highlights?.contextPadding ?? 2;
    const structure = template.structure;

    // Sort highlights by score (descending) for phase assignment
    const ranked = [...highlights].sort((a, b) => b.score - a.score);

    // Calculate how many highlights go in each phase
    const total = ranked.length;
    const allocation = {
      climax: Math.max(1, Math.ceil(total * structure.climax)),
      build:  Math.max(1, Math.ceil(total * structure.build)),
      intro:  Math.max(1, Math.ceil(total * structure.intro)),
      outro:  Math.max(0, total), // Remainder
    };

    // Assign phases (best → climax, next → build, etc.)
    const phaseAssignments = new Map();
    let assigned = 0;

    for (let i = 0; i < ranked.length; i++) {
      const key = ranked[i].timestamp;
      if (assigned < allocation.climax) {
        phaseAssignments.set(key, 'climax');
      } else if (assigned < allocation.climax + allocation.build) {
        phaseAssignments.set(key, 'build');
      } else if (assigned < allocation.climax + allocation.build + allocation.intro) {
        phaseAssignments.set(key, 'intro');
      } else {
        phaseAssignments.set(key, 'outro');
      }
      assigned++;
    }

    // Build segments in chronological order with padding
    const segments = highlights.map((h) => ({
      start: Math.max(0, h.timestamp - padding),
      end: h.timestamp + padding,
      score: h.score,
      phase: phaseAssignments.get(h.timestamp) || 'build',
    }));

    // Merge overlapping segments
    const merged = this._mergeOverlappingSegments(segments);

    // Trim to max duration
    let totalDuration = merged.reduce((sum, s) => sum + (s.end - s.start), 0);
    const trimmed = [];
    let accumulated = 0;

    for (const seg of merged) {
      const segDur = seg.end - seg.start;
      if (accumulated + segDur > maxDuration) {
        // Trim this segment to fit
        trimmed.push({ ...seg, end: seg.start + (maxDuration - accumulated) });
        accumulated = maxDuration;
        break;
      }
      trimmed.push(seg);
      accumulated += segDur;
    }

    totalDuration = trimmed.reduce((sum, s) => sum + (s.end - s.start), 0);

    return {
      id: '',
      videoPath: '',
      templateId: template.id,
      mood: template.mood,
      templateTransitionStyle: template.transition_style,
      segments: trimmed,
      totalDuration: Math.round(totalDuration * 100) / 100,
    };
  }

  // ── Clip Generation ─────────────────────────────────────────────────────

  /**
   * Render the final clip by cutting and concatenating video segments.
   *
   * Uses ffmpeg's concat demuxer:
   *  1. Cut each segment into a temp file
   *  2. Create a concat list
   *  3. Concatenate into the final output
   *
   * @param {string}   videoPath   - Source video path
   * @param {ClipPlan} clipPlan    - The clip plan with segments
   * @param {string}   [outputPath] - Custom output path (auto-generated if omitted)
   * @returns {Promise<string>} Path to the rendered output file
   */
  async generateClip(videoPath, clipPlan, outputPath) {
    if (clipPlan.segments.length === 0) {
      throw new Error('Cannot generate clip: no segments in clip plan');
    }

    const ffmpegBin = this.config.ffmpeg?.bin || 'ffmpeg';
    const outputDir = this.config.output?.dir || './output';
    await mkdir(outputDir, { recursive: true });

    const ext = this.config.output?.format || 'mp4';
    const finalPath = outputPath ||
      join(outputDir, `kairo_${clipPlan.id || 'clip'}_${Date.now()}.${ext}`);

    const tempDir = join(
      this.config.extraction?.tempDir || '/tmp/kairo-frames',
      `render_${randomUUID().slice(0, 8)}`
    );
    await mkdir(tempDir, { recursive: true });

    // Step 1: Cut each segment
    const segmentFiles = [];
    for (let i = 0; i < clipPlan.segments.length; i++) {
      const seg = clipPlan.segments[i];
      const segFile = join(tempDir, `seg_${String(i).padStart(4, '0')}.${ext}`);
      const duration = seg.end - seg.start;

      const args = [
        '-ss', String(seg.start),
        '-i', videoPath,
        '-t', String(duration),
        '-c:v', this.config.output?.codec || 'libx264',
        '-c:a', this.config.output?.audioCodec || 'aac',
        '-crf', this.config.output?.quality || '18',
        '-y',
        '-loglevel', 'warning',
        segFile,
      ];

      await execFileAsync(ffmpegBin, args, { timeout: 120_000 });
      segmentFiles.push(segFile);
    }

    // Step 2: Build concat file
    const { writeFile } = await import('node:fs/promises');
    const concatList = join(tempDir, 'concat.txt');
    const concatContent = segmentFiles
      .map((f) => `file '${f}'`)
      .join('\n');
    await writeFile(concatList, concatContent, 'utf-8');

    // Step 3: Concatenate
    const concatArgs = [
      '-f', 'concat',
      '-safe', '0',
      '-i', concatList,
      '-c', 'copy',
      '-y',
      '-loglevel', 'warning',
      finalPath,
    ];

    await execFileAsync(ffmpegBin, concatArgs, { timeout: 120_000 });

    // Cleanup temp segment files
    await rm(tempDir, { recursive: true, force: true }).catch(() => {});

    return finalPath;
  }

  // ── Private Helpers ─────────────────────────────────────────────────────

  /**
   * Remove clustered highlights, keeping the highest score in each window.
   * @param {Highlight[]} highlights - Sorted by timestamp
   * @param {number} minGap - Minimum seconds between highlights
   * @returns {Highlight[]}
   * @private
   */
  _deduplicateHighlights(highlights, minGap) {
    if (highlights.length === 0) return [];

    const sorted = [...highlights].sort((a, b) => a.timestamp - b.timestamp);
    const result = [sorted[0]];

    for (let i = 1; i < sorted.length; i++) {
      const last = result[result.length - 1];
      if (sorted[i].timestamp - last.timestamp < minGap) {
        // Keep the higher-scoring one
        if (sorted[i].score > last.score) {
          result[result.length - 1] = sorted[i];
        }
      } else {
        result.push(sorted[i]);
      }
    }

    return result;
  }

  /**
   * Merge overlapping or adjacent segments.
   * @param {ClipSegment[]} segments - Sorted by start time
   * @returns {ClipSegment[]}
   * @private
   */
  _mergeOverlappingSegments(segments) {
    if (segments.length === 0) return [];

    const sorted = [...segments].sort((a, b) => a.start - b.start);
    const merged = [{ ...sorted[0] }];

    for (let i = 1; i < sorted.length; i++) {
      const last = merged[merged.length - 1];
      if (sorted[i].start <= last.end) {
        // Merge: extend end, keep higher score, prefer more important phase
        last.end = Math.max(last.end, sorted[i].end);
        if (sorted[i].score > last.score) {
          last.score = sorted[i].score;
          last.phase = sorted[i].phase;
        }
      } else {
        merged.push({ ...sorted[i] });
      }
    }

    return merged;
  }

  /**
   * Summarize highlights into stats for template matching.
   * @param {Highlight[]} highlights
   * @returns {import('./persona.js').HighlightSummary}
   * @private
   */
  _summarizeHighlights(highlights) {
    if (highlights.length === 0) {
      return { avgScore: 0, maxScore: 0, count: 0, momentumSwings: 0, clutchCount: 0, rageIndicators: 0 };
    }

    const scores = highlights.map((h) => h.score);
    const avgScore = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length);
    const maxScore = Math.max(...scores);

    // Count momentum swings (score changes > 30 between consecutive highlights)
    let momentumSwings = 0;
    for (let i = 1; i < highlights.length; i++) {
      if (Math.abs(highlights[i].score - highlights[i - 1].score) > 30) {
        momentumSwings++;
      }
    }

    const clutchCount = highlights.filter((h) => h.score >= 90).length;
    // Placeholder: rage indicators could be detected by audio analysis, chat sentiment, etc.
    const rageIndicators = highlights.filter((h) => h.reason.includes('spike') && h.score > 70).length;

    return { avgScore, maxScore, count: highlights.length, momentumSwings, clutchCount, rageIndicators };
  }

  /**
   * Clean up temporary frame files.
   * @param {FrameData[]} frames
   * @private
   */
  async _cleanupFrames(frames) {
    if (frames.length === 0) return;
    const dir = join(frames[0].path, '..');
    await rm(dir, { recursive: true, force: true });
  }
}

export default VODAnalyzer;
