/**
 * @fileoverview KAIRO Configuration
 * Central configuration for the VOD analysis pipeline.
 * All secrets are loaded from environment variables.
 * @module config
 */

/**
 * @typedef {Object} ModelEndpoint
 * @property {string} url - API endpoint URL
 * @property {string} apiKey - API key (from env)
 * @property {string} model - Model identifier
 * @property {number} maxTokens - Max tokens per request
 */

/**
 * @typedef {Object} OutputSettings
 * @property {string} format - Output video format (mp4, webm)
 * @property {string} codec - Video codec
 * @property {string} audioCodec - Audio codec
 * @property {string} resolution - Target resolution
 * @property {number} fps - Target frame rate
 * @property {string} quality - CRF quality value (lower = better)
 */

/** @type {Object} Pipeline configuration */
const config = {
  /**
   * AI model endpoints for video understanding and generation
   */
  models: {
    /** Google Gemini Flash — fast multimodal analysis */
    geminiFlash: {
      url: process.env.GEMINI_API_URL || 'https://generativelanguage.googleapis.com/v1beta',
      apiKey: process.env.GEMINI_API_KEY || '',
      model: process.env.GEMINI_MODEL || 'gemini-2.0-flash',
      maxTokens: 8192,
    },
    /** TwelveLabs — video understanding API */
    twelveLabs: {
      url: process.env.TWELVELABS_API_URL || 'https://api.twelvelabs.io/v1.2',
      apiKey: process.env.TWELVELABS_API_KEY || '',
      model: process.env.TWELVELABS_MODEL || 'marengo-retrieval-2.6',
      maxTokens: 4096,
    },
  },

  /**
   * FFmpeg configuration
   */
  ffmpeg: {
    /** Path to ffmpeg binary */
    bin: process.env.FFMPEG_PATH || 'ffmpeg',
    /** Path to ffprobe binary */
    probeBin: process.env.FFPROBE_PATH || 'ffprobe',
    /** Number of threads (0 = auto) */
    threads: parseInt(process.env.FFMPEG_THREADS || '0', 10),
    /** Hardware acceleration (none | videotoolbox | cuda | vaapi) */
    hwaccel: process.env.FFMPEG_HWACCEL || 'none',
  },

  /**
   * Frame extraction settings
   */
  extraction: {
    /** Default FPS for frame extraction */
    defaultFps: 1,
    /** Output format for extracted frames */
    frameFormat: 'jpg',
    /** JPEG quality (2-31, lower = better) */
    frameQuality: 2,
    /** Temp directory for extracted frames */
    tempDir: process.env.KAIRO_TEMP_DIR || '/tmp/kairo-frames',
  },

  /**
   * Output video settings
   * @type {OutputSettings}
   */
  output: {
    format: 'mp4',
    codec: 'libx264',
    audioCodec: 'aac',
    resolution: '1920x1080',
    fps: 60,
    quality: '18',
    /** Output directory */
    dir: process.env.KAIRO_OUTPUT_DIR || './output',
  },

  /**
   * Highlight detection thresholds
   */
  highlights: {
    /** Minimum score (0-100) to qualify as a highlight */
    minScore: 60,
    /** Minimum gap in seconds between highlights to avoid clustering */
    minGapSeconds: 5,
    /** Maximum number of highlights to include in a clip */
    maxHighlights: 20,
    /** Context padding in seconds around each highlight */
    contextPadding: 2,
  },

  /**
   * Pipeline defaults
   */
  pipeline: {
    /** Maximum input video duration in seconds (2 hours) */
    maxInputDuration: 7200,
    /** Maximum output clip duration in seconds (10 min) */
    maxOutputDuration: 600,
    /** Enable progress logging */
    verbose: process.env.KAIRO_VERBOSE === 'true',
  },
};

export default config;
