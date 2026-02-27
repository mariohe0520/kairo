/**
 * Kairo AI — Web UI Application
 * Standalone single-page app for the Kairo video editing pipeline.
 * Connects to the local FastAPI backend at the same origin.
 */

(function () {
  'use strict';

  // ═══════════════════════════════════════════
  // Configuration
  // ═══════════════════════════════════════════

  const API_BASE = window.location.origin;
  const WS_BASE = API_BASE.replace(/^http/, 'ws');

  // Detect demo mode (GitHub Pages or file://)
  const IS_DEMO = window.location.protocol === 'file:' ||
    window.location.hostname.includes('github.io') ||
    window.location.hostname.includes('pages.dev');

  // ═══════════════════════════════════════════
  // i18n — English / Chinese
  // ═══════════════════════════════════════════

  const i18n = {
    en: {
      'hero.badge': 'AI-Powered Video Intelligence',
      'hero.title1': 'Turn Gaming VODs into',
      'hero.title2': 'Viral Clips',
      'hero.desc': 'Paste a URL. Get a TikTok-ready clip. Kairo\'s AI analyzes highlights, builds narratives, and renders polished videos automatically.',
      'hero.inputPlaceholder': 'Paste YouTube, Twitch, or Bilibili URL...',
      'hero.cta': 'Create Viral Clip',
      'hero.or': 'or',
      'hero.dropText': 'Drag & drop video file here',
      'hero.dropHint': 'MP4, MOV, MKV, WebM',
      'hero.supports': 'Supports',
      'templates.title': 'Editing Templates',
      'templates.subtitle': 'Choose a narrative style for your clip',
      'templates.all': 'All',
      'templates.narrative': 'Narrative',
      'templates.comedy': 'Comedy',
      'templates.short': 'Short',
      'templates.universal': 'Universal',
      'personas.title': 'Streamer Personas',
      'personas.subtitle': 'Select a persona to auto-tune editing style',
      'progress.title': 'Processing Your Video',
      'progress.initializing': 'Initializing pipeline...',
      'progress.cancel': 'Cancel',
      'progress.ingest': 'Ingest',
      'progress.analyze': 'Analyze',
      'progress.generate': 'Generate',
      'progress.render': 'Render',
      'progress.waiting': 'Waiting to start...',
      'result.ready': 'Your clip is ready!',
      'result.download': 'Download',
      'result.share': 'Share',
      'result.newClip': 'New Clip',
      'result.rateTitle': 'Rate this clip',
      'result.approve': 'Approve',
      'result.modify': 'Modify',
      'result.reject': 'Reject',
      'history.title': 'Job History',
      'history.subtitle': 'View past jobs and their results',
      'history.refresh': 'Refresh',
      'history.empty': 'No jobs yet. Create your first viral clip above!',
      'toast.connected': 'Connected to Kairo backend',
      'toast.disconnected': 'Backend offline — running in demo mode',
      'toast.pipelineStarted': 'Pipeline started! Processing your video...',
      'toast.pipelineComplete': 'Your viral clip is ready!',
      'toast.pipelineFailed': 'Pipeline failed. Please try again.',
      'toast.feedbackSent': 'Feedback submitted, thank you!',
      'toast.urlRequired': 'Please paste a URL or drop a video file',
      'toast.demoMode': 'Demo mode — connect to backend to use full features',
      'status.connected': 'Connected',
      'status.connecting': 'Connecting...',
      'status.offline': 'Demo Mode',
    },
    zh: {
      'hero.badge': 'AI驱动的视频智能编辑',
      'hero.title1': '将游戏录像变成',
      'hero.title2': '爆款短视频',
      'hero.desc': '粘贴链接，获得抖音级别的精彩剪辑。Kairo AI自动分析亮点、构建叙事、渲染精美视频。',
      'hero.inputPlaceholder': '粘贴 YouTube、Twitch 或 B站 链接...',
      'hero.cta': '一键生成爆款',
      'hero.or': '或者',
      'hero.dropText': '拖拽视频文件到这里',
      'hero.dropHint': 'MP4, MOV, MKV, WebM',
      'hero.supports': '支持平台',
      'templates.title': '编辑模板',
      'templates.subtitle': '选择你的剪辑叙事风格',
      'templates.all': '全部',
      'templates.narrative': '叙事',
      'templates.comedy': '搞笑',
      'templates.short': '短视频',
      'templates.universal': '通用',
      'personas.title': '主播人设',
      'personas.subtitle': '选择人设自动调整编辑风格',
      'progress.title': '正在处理你的视频',
      'progress.initializing': '初始化管线...',
      'progress.cancel': '取消',
      'progress.ingest': '导入',
      'progress.analyze': '分析',
      'progress.generate': '生成',
      'progress.render': '渲染',
      'progress.waiting': '等待开始...',
      'result.ready': '你的剪辑已完成！',
      'result.download': '下载',
      'result.share': '分享',
      'result.newClip': '新建剪辑',
      'result.rateTitle': '为这个剪辑评分',
      'result.approve': '通过',
      'result.modify': '修改',
      'result.reject': '拒绝',
      'history.title': '任务历史',
      'history.subtitle': '查看历史任务及结果',
      'history.refresh': '刷新',
      'history.empty': '暂无任务。在上方创建你的第一个爆款剪辑！',
      'toast.connected': '已连接到 Kairo 后端',
      'toast.disconnected': '后端离线 — 演示模式运行中',
      'toast.pipelineStarted': '管线已启动！正在处理视频...',
      'toast.pipelineComplete': '你的爆款剪辑已完成！',
      'toast.pipelineFailed': '管线失败，请重试。',
      'toast.feedbackSent': '反馈已提交，谢谢！',
      'toast.urlRequired': '请粘贴链接或拖入视频文件',
      'toast.demoMode': '演示模式 — 连接后端以使用完整功能',
      'status.connected': '已连接',
      'status.connecting': '连接中...',
      'status.offline': '演示模式',
    }
  };

  // ═══════════════════════════════════════════
  // State
  // ═══════════════════════════════════════════

  const state = {
    lang: 'en',
    serverOnline: false,
    ws: null,
    currentJobId: null,
    selectedTemplate: null,
    selectedPersona: null,
    uploadedFile: null,
    feedbackRating: 0,
    templates: [],
    personas: [],
    jobs: [],
  };

  // ═══════════════════════════════════════════
  // DOM Helpers
  // ═══════════════════════════════════════════

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  function el(tag, attrs = {}, children = []) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'className') e.className = v;
      else if (k === 'textContent') e.textContent = v;
      else if (k === 'innerHTML') e.innerHTML = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
      else e.setAttribute(k, v);
    }
    for (const c of children) {
      if (typeof c === 'string') e.appendChild(document.createTextNode(c));
      else if (c) e.appendChild(c);
    }
    return e;
  }

  // ═══════════════════════════════════════════
  // i18n Engine
  // ═══════════════════════════════════════════

  function t(key) {
    return (i18n[state.lang] || i18n.en)[key] || key;
  }

  function applyLanguage() {
    $$('[data-i18n]').forEach(el => {
      el.textContent = t(el.dataset.i18n);
    });
    $$('[data-i18n-placeholder]').forEach(el => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    $('#lang-label').textContent = state.lang === 'en' ? 'EN' : '中';
  }

  function toggleLanguage() {
    state.lang = state.lang === 'en' ? 'zh' : 'en';
    applyLanguage();
  }

  // ═══════════════════════════════════════════
  // Toast Notifications
  // ═══════════════════════════════════════════

  function showToast(message, type = 'info', duration = 4000) {
    const container = $('#toast-container');
    const icons = {
      success: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
      error: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
      info: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };

    const toast = el('div', { className: `toast ${type}` }, [
      el('span', { className: 'toast-icon', innerHTML: icons[type] || icons.info }),
      el('span', { textContent: message }),
    ]);

    container.appendChild(toast);

    setTimeout(() => {
      toast.classList.add('removing');
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  // ═══════════════════════════════════════════
  // API Layer
  // ═══════════════════════════════════════════

  async function api(path, opts = {}) {
    if (IS_DEMO && !state.serverOnline) {
      return null;
    }
    try {
      const resp = await fetch(`${API_BASE}${path}`, {
        ...opts,
        headers: { ...opts.headers },
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${resp.status}`);
      }
      return await resp.json();
    } catch (err) {
      console.error(`API error [${path}]:`, err);
      throw err;
    }
  }

  // ═══════════════════════════════════════════
  // Server Health Check
  // ═══════════════════════════════════════════

  async function checkServer() {
    const dot = $('#status-dot');
    const label = $('#status-label');

    try {
      const data = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(3000) });
      if (data && data.ok) {
        state.serverOnline = true;
        dot.className = 'status-dot connected';
        label.textContent = t('status.connected');
        return true;
      }
    } catch (e) {
      // Server not reachable
    }

    state.serverOnline = false;
    dot.className = 'status-dot error';
    label.textContent = t('status.offline');
    return false;
  }

  // ═══════════════════════════════════════════
  // WebSocket
  // ═══════════════════════════════════════════

  function connectWebSocket() {
    if (!state.serverOnline || IS_DEMO) return;
    if (state.ws && state.ws.readyState <= 1) return;

    try {
      state.ws = new WebSocket(`${WS_BASE}/ws/progress`);

      state.ws.onopen = () => {
        console.log('[WS] Connected');
      };

      state.ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          if (data.type === 'progress') {
            handleProgressUpdate(data);
          }
        } catch (e) {
          // ignore parse errors
        }
      };

      state.ws.onclose = () => {
        console.log('[WS] Disconnected');
        setTimeout(connectWebSocket, 5000);
      };

      state.ws.onerror = () => {
        state.ws.close();
      };
    } catch (e) {
      console.error('[WS] Connection failed:', e);
    }
  }

  // ═══════════════════════════════════════════
  // Progress Updates
  // ═══════════════════════════════════════════

  function handleProgressUpdate(data) {
    if (data.job_id !== state.currentJobId) return;

    const progress = data.progress || 0;
    const message = data.message || '';
    const stage = data.stage || '';

    // Update progress bar
    const pct = Math.round(progress * 100);
    const fill = $('#main-progress-fill');
    const glow = $('#main-progress-glow');
    const pctEl = $('#progress-percentage');

    if (fill) fill.style.width = pct + '%';
    if (glow) glow.style.width = pct + '%';
    if (pctEl) pctEl.textContent = pct + '%';

    // Update message
    const msgEl = $('#progress-message');
    if (msgEl) msgEl.textContent = message;

    // Update stage indicators
    updateStageIndicators(stage, progress);

    // Add log entry
    addLogEntry(message);

    // Check for completion
    if (data.stage === 'complete' || progress >= 1) {
      onPipelineComplete(data);
    } else if (data.stage === 'error') {
      onPipelineFailed(message);
    }
  }

  function updateStageIndicators(stage, progress) {
    const stages = ['ingest', 'analyze', 'generate', 'render'];
    const stageMap = {
      'ingest': 0, 'download': 0, 'ingesting': 0,
      'analyze': 1, 'analysis': 1, 'caption': 1, 'dvd': 1,
      'generate': 2, 'script': 2, 'dna': 2,
      'render': 3, 'rendering': 3, 'segments': 3, 'concat': 3,
      'complete': 4, 'done': 4,
      'pipeline': -1,
    };

    // Try to find stage index from the stage string
    let activeIdx = stageMap[stage] !== undefined ? stageMap[stage] : -1;

    // Fallback: estimate from progress
    if (activeIdx === -1 && progress > 0) {
      activeIdx = Math.min(3, Math.floor(progress * 4));
    }

    stages.forEach((s, i) => {
      const el = $(`#stage-${s}`);
      if (!el) return;
      el.classList.remove('active', 'completed');
      if (i < activeIdx) el.classList.add('completed');
      else if (i === activeIdx) el.classList.add('active');
    });
  }

  function addLogEntry(message) {
    if (!message) return;
    const log = $('#progress-log');
    if (!log) return;

    const now = new Date();
    const time = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

    const entry = el('div', { className: 'log-entry' }, [
      el('span', { className: 'log-time', textContent: time }),
      el('span', { className: 'log-text', textContent: message }),
    ]);

    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
  }

  // ═══════════════════════════════════════════
  // Pipeline Control
  // ═══════════════════════════════════════════

  async function startPipeline() {
    const urlInput = $('#url-input');
    const url = urlInput.value.trim();
    const goBtn = $('#btn-pipeline');

    if (!url && !state.uploadedFile) {
      showToast(t('toast.urlRequired'), 'error');
      urlInput.focus();
      return;
    }

    if (!state.serverOnline) {
      showToast(t('toast.demoMode'), 'info');
      // In demo mode, simulate a pipeline run
      simulatePipeline();
      return;
    }

    // Show loading state on button
    goBtn.classList.add('loading');

    try {
      const formData = new FormData();
      if (state.uploadedFile) {
        // Upload the actual file to the ingest endpoint first,
        // then run pipeline with the resulting path.
        // For simplicity, use /api/pipeline which also accepts file uploads.
        formData.append('file', state.uploadedFile);
      } else {
        formData.append('url', url);
      }

      if (state.selectedPersona) {
        formData.append('streamer_id', state.selectedPersona);
      }
      if (state.selectedTemplate) {
        formData.append('template_id', state.selectedTemplate);
      }

      const data = await api('/api/pipeline', {
        method: 'POST',
        body: formData,
      });

      if (data && data.job_id) {
        state.currentJobId = data.job_id;
        showProgressSection();
        showToast(t('toast.pipelineStarted'), 'success');

        // Start polling if WebSocket isn't connected
        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
          startPolling(data.job_id);
        }
      }
    } catch (err) {
      showToast(err.message || t('toast.pipelineFailed'), 'error');
    } finally {
      goBtn.classList.remove('loading');
    }
  }

  function startPolling(jobId) {
    const interval = setInterval(async () => {
      try {
        const data = await api(`/api/jobs/${jobId}`);
        if (!data) { clearInterval(interval); return; }

        // Map the pipeline's internal stage names to our UI stages
        let stage = data.job_type || 'pipeline';
        const msg = (data.message || '').toLowerCase();
        if (msg.includes('ingest') || msg.includes('download')) stage = 'ingest';
        else if (msg.includes('caption') || msg.includes('analyz')) stage = 'analyze';
        else if (msg.includes('discover') || msg.includes('architect') || msg.includes('generat') || msg.includes('script')) stage = 'generate';
        else if (msg.includes('render')) stage = 'render';
        else if (msg.includes('complete') || msg.includes('done')) stage = 'complete';

        handleProgressUpdate({
          job_id: jobId,
          stage: stage,
          progress: data.progress || 0,
          message: data.message || '',
        });

        if (data.status === 'completed') {
          clearInterval(interval);
          onPipelineComplete(data);
        } else if (data.status === 'failed') {
          clearInterval(interval);
          onPipelineFailed(data.error || 'Unknown error');
        }
      } catch (e) {
        // keep polling
      }
    }, 2000);
  }

  function onPipelineComplete(data) {
    showToast(t('toast.pipelineComplete'), 'success', 6000);
    showResultSection(data);
    refreshJobs();
  }

  function onPipelineFailed(error) {
    showToast(t('toast.pipelineFailed') + ': ' + error, 'error', 8000);
    hideProgressSection();
    refreshJobs();
  }

  // ═══════════════════════════════════════════
  // Demo / Simulation Mode
  // ═══════════════════════════════════════════

  function simulatePipeline() {
    state.currentJobId = 'demo_' + Date.now();
    showProgressSection();
    showToast(t('toast.pipelineStarted'), 'success');

    const stages = [
      { stage: 'ingest', progress: 0.05, message: 'Downloading video...', delay: 500 },
      { stage: 'ingest', progress: 0.15, message: 'Extracting audio...', delay: 1200 },
      { stage: 'ingest', progress: 0.25, message: 'Extracting frames...', delay: 1800 },
      { stage: 'analyze', progress: 0.35, message: 'Running AI analysis...', delay: 2500 },
      { stage: 'analyze', progress: 0.45, message: 'Detecting highlights...', delay: 3200 },
      { stage: 'analyze', progress: 0.55, message: 'Building emotional arc...', delay: 3900 },
      { stage: 'generate', progress: 0.65, message: 'Generating edit scripts...', delay: 4600 },
      { stage: 'generate', progress: 0.75, message: 'Selecting best candidates...', delay: 5300 },
      { stage: 'render', progress: 0.85, message: 'Rendering final video...', delay: 6000 },
      { stage: 'render', progress: 0.95, message: 'Applying effects & subtitles...', delay: 6800 },
      { stage: 'complete', progress: 1.0, message: 'Pipeline complete!', delay: 7500 },
    ];

    stages.forEach(({ stage, progress, message, delay }) => {
      setTimeout(() => {
        handleProgressUpdate({
          job_id: state.currentJobId,
          stage,
          progress,
          message,
        });
      }, delay);
    });
  }

  // ═══════════════════════════════════════════
  // Section Visibility
  // ═══════════════════════════════════════════

  function showProgressSection() {
    $('#progress').classList.remove('hidden');
    $('#result').classList.add('hidden');

    // Reset progress UI
    const fill = $('#main-progress-fill');
    const glow = $('#main-progress-glow');
    const pct = $('#progress-percentage');
    if (fill) fill.style.width = '0%';
    if (glow) glow.style.width = '0%';
    if (pct) pct.textContent = '0%';
    $('#progress-message').textContent = t('progress.initializing');

    // Clear log
    const log = $('#progress-log');
    log.innerHTML = '';
    addLogEntry(t('progress.waiting'));

    // Reset stages
    $$('.stage-step').forEach(s => s.classList.remove('active', 'completed'));

    // Scroll into view
    $('#progress').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function hideProgressSection() {
    $('#progress').classList.add('hidden');
  }

  function showResultSection(data) {
    hideProgressSection();
    const resultSection = $('#result');
    resultSection.classList.remove('hidden');

    // Set up video player if we have a result
    const video = $('#result-video');
    const overlay = $('#player-overlay');

    if (data && data.result && (data.result.output_video || data.result.output_path)) {
      video.src = `${API_BASE}/api/jobs/${state.currentJobId}/download`;
      overlay.classList.remove('hidden');
    } else {
      // Demo mode - no actual video
      overlay.classList.remove('hidden');
    }

    // Reset feedback
    state.feedbackRating = 0;
    $$('.star-btn').forEach(s => s.classList.remove('active'));

    resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ═══════════════════════════════════════════
  // Templates & Personas
  // ═══════════════════════════════════════════

  const TEMPLATE_ICONS = {
    'comeback-king': { icon: '\uD83D\uDC51', color: '#10b981' },
    'clutch-master': { icon: '\uD83C\uDFAF', color: '#ef4444' },
    'rage-quit-montage': { icon: '\uD83D\uDCA2', color: '#f59e0b' },
    'chill-highlights': { icon: '\uD83C\uDF19', color: '#06b6d4' },
    'kill-montage': { icon: '\uD83D\uDD2B', color: '#ef4444' },
    'session-story': { icon: '\uD83D\uDCDA', color: '#8b5cf6' },
    'tiktok-vertical': { icon: '\uD83D\uDCF1', color: '#ec4899' },
    'edu-breakdown': { icon: '\uD83C\uDF93', color: '#3b82f6' },
    'hype-montage': { icon: '\uD83D\uDD25', color: '#f59e0b' },
    'squad-moments': { icon: '\uD83E\uDD1D', color: '#8b5cf6' },
  };

  const PERSONA_ICONS = {
    'hype-streamer': '\uD83D\uDD25',
    'chill-streamer': '\uD83E\uDDD8',
    'chaos-gremlin': '\uD83D\uDC80',
    'tactician': '\uD83E\uDDE0',
    'squad-captain': '\uD83E\uDD1D',
  };

  // Fallback template data (for demo mode or if API is unavailable)
  const FALLBACK_TEMPLATES = [
    { id: 'comeback-king', name: 'Comeback King', description: 'Highlights dramatic reversals \u2014 getting destroyed then clawing back to win.', category: 'Narrative', mood: 'triumphant', durationRange: [45, 120] },
    { id: 'clutch-master', name: 'Clutch Master', description: 'Showcases clutch moments \u2014 insane plays when everything is on the line.', category: 'FPS', mood: 'intense', durationRange: [30, 90] },
    { id: 'rage-quit-montage', name: 'Rage Quit Montage', description: 'Captures tilts, fails, and rage moments \u2014 funny, chaotic, shareable.', category: 'Comedy', mood: 'chaotic', durationRange: [30, 90] },
    { id: 'chill-highlights', name: 'Chill Highlights', description: 'Smooth, relaxed highlight reel \u2014 aesthetic vibes over hype.', category: 'Universal', mood: 'chill', durationRange: [60, 180] },
    { id: 'kill-montage', name: 'Kill Montage', description: 'Rapid-fire kill compilation \u2014 headshots, multi-kills, ace rounds.', category: 'FPS', mood: 'intense', durationRange: [20, 60] },
    { id: 'session-story', name: 'Session Story', description: 'Full session condensed into a narrative with chapters and emotional arc.', category: 'Narrative', mood: 'triumphant', durationRange: [120, 300] },
    { id: 'tiktok-vertical', name: 'TikTok Vertical', description: 'Optimized for 9:16 vertical \u2014 fast hook, peak moment, reaction.', category: 'Short-Form', mood: 'intense', durationRange: [15, 60] },
    { id: 'edu-breakdown', name: 'Educational Breakdown', description: 'Annotated replay analysis \u2014 freeze frames, zoom callouts, step-by-step.', category: 'Educational', mood: 'chill', durationRange: [60, 240] },
    { id: 'hype-montage', name: 'Hype Montage', description: 'Music-synced highlight reel \u2014 beat drops align with kills.', category: 'Universal', mood: 'intense', durationRange: [30, 90] },
    { id: 'squad-moments', name: 'Squad Moments', description: 'Best group plays, comms highlights, and team chemistry moments.', category: 'Social', mood: 'triumphant', durationRange: [45, 150] },
  ];

  const FALLBACK_PERSONAS = [
    { id: 'hype-streamer', name: 'HypeAndy', archetype: 'The Hype Machine', energy_level: 9, humor_style: 'loud', preferred_template: 'clutch-master', edit_intensity: 8 },
    { id: 'chill-streamer', name: 'ZenVibes', archetype: 'The Zen Master', energy_level: 3, humor_style: 'dry', preferred_template: 'chill-highlights', edit_intensity: 3 },
    { id: 'chaos-gremlin', name: 'TiltLord', archetype: 'The Chaos Gremlin', energy_level: 10, humor_style: 'chaotic', preferred_template: 'rage-quit-montage', edit_intensity: 10 },
    { id: 'tactician', name: 'SteadyAim', archetype: 'The Tactician', energy_level: 5, humor_style: 'sarcastic', preferred_template: 'edu-breakdown', edit_intensity: 5 },
    { id: 'squad-captain', name: 'SquadLeader', archetype: 'The Squad Captain', energy_level: 7, humor_style: 'wholesome', preferred_template: 'squad-moments', edit_intensity: 6 },
  ];

  async function loadTemplates() {
    try {
      if (state.serverOnline) {
        const data = await api('/api/templates');
        if (data && data.templates) {
          state.templates = data.templates;
          renderTemplates(state.templates);
          return;
        }
      }
    } catch (e) {
      // Fall through to fallback
    }
    state.templates = FALLBACK_TEMPLATES;
    renderTemplates(state.templates);
  }

  async function loadPersonas() {
    try {
      if (state.serverOnline) {
        const data = await api('/api/personas');
        if (data && data.personas) {
          state.personas = data.personas;
          renderPersonas(state.personas);
          return;
        }
      }
    } catch (e) {
      // Fall through to fallback
    }
    state.personas = FALLBACK_PERSONAS;
    renderPersonas(state.personas);
  }

  function renderTemplates(templates, filter = 'all') {
    const grid = $('#template-grid');
    grid.innerHTML = '';

    const filtered = filter === 'all'
      ? templates
      : templates.filter(t => t.category === filter);

    filtered.forEach(tmpl => {
      const meta = TEMPLATE_ICONS[tmpl.id] || { icon: '\uD83C\uDFAC', color: '#8b5cf6' };
      const dur = tmpl.durationRange
        ? `${tmpl.durationRange[0]}s - ${Math.floor(tmpl.durationRange[1] / 60)}m${tmpl.durationRange[1] % 60 ? tmpl.durationRange[1] % 60 + 's' : ''}`
        : '';

      const card = el('div', {
        className: 'template-card' + (state.selectedTemplate === tmpl.id ? ' selected' : ''),
        onClick: () => selectTemplate(tmpl.id),
      }, [
        el('div', { className: 'template-card-top' }, [
          el('div', { className: 'template-icon', textContent: meta.icon }),
          el('span', { className: 'template-category', textContent: tmpl.category }),
        ]),
        el('div', { className: 'template-name', textContent: tmpl.name }),
        el('div', { className: 'template-desc', textContent: tmpl.description }),
        el('div', { className: 'template-meta' }, [
          el('span', { className: `mood-badge mood-${tmpl.mood}`, textContent: tmpl.mood }),
          el('span', { className: 'template-meta-item', innerHTML: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ${dur}` }),
        ]),
      ]);

      grid.appendChild(card);
    });
  }

  function renderPersonas(personas) {
    const grid = $('#persona-grid');
    grid.innerHTML = '';

    personas.forEach(p => {
      const emoji = PERSONA_ICONS[p.id] || '\uD83C\uDFAE';
      const energyDots = [];
      for (let i = 0; i < 10; i++) {
        energyDots.push(el('div', { className: 'energy-dot' + (i < p.energy_level ? ' active' : '') }));
      }

      const card = el('div', {
        className: 'persona-card' + (state.selectedPersona === p.id ? ' selected' : ''),
        onClick: () => selectPersona(p.id),
      }, [
        el('div', { className: 'persona-avatar', textContent: emoji }),
        el('div', { className: 'persona-name', textContent: p.name }),
        el('div', { className: 'persona-archetype', textContent: p.archetype }),
        el('div', { className: 'persona-energy' }, [
          el('span', { textContent: 'Energy ' }),
          el('div', { className: 'energy-bar' }, energyDots),
        ]),
      ]);

      grid.appendChild(card);
    });
  }

  function selectTemplate(id) {
    state.selectedTemplate = state.selectedTemplate === id ? null : id;
    renderTemplates(state.templates, getCurrentFilter());
  }

  function selectPersona(id) {
    state.selectedPersona = state.selectedPersona === id ? null : id;
    renderPersonas(state.personas);
  }

  function getCurrentFilter() {
    const active = $('.filter-pill.active');
    return active ? active.dataset.filter : 'all';
  }

  // ═══════════════════════════════════════════
  // Job History
  // ═══════════════════════════════════════════

  async function refreshJobs() {
    try {
      if (!state.serverOnline) return;
      const data = await api('/api/jobs?limit=20');
      if (data && data.jobs) {
        state.jobs = data.jobs;
        renderJobHistory(data.jobs);
      }
    } catch (e) {
      // Ignore
    }
  }

  function renderJobHistory(jobs) {
    const list = $('#history-list');
    const empty = $('#history-empty');

    if (!jobs || jobs.length === 0) {
      list.innerHTML = '';
      list.appendChild(empty);
      empty.classList.remove('hidden');
      return;
    }

    list.innerHTML = '';
    empty.classList.add('hidden');

    const statusIcons = {
      completed: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
      running: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
      failed: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
      pending: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    };

    jobs.forEach(job => {
      const time = job.created_at ? new Date(job.created_at).toLocaleString() : '';
      const progress = Math.round((job.progress || 0) * 100);

      const item = el('div', { className: 'history-item', onClick: () => viewJob(job) }, [
        el('div', {
          className: `history-icon ${job.status}`,
          innerHTML: statusIcons[job.status] || statusIcons.pending,
        }),
        el('div', { className: 'history-info' }, [
          el('div', { className: 'history-title', textContent: `${job.job_type} - ${job.job_id}` }),
          el('div', { className: 'history-meta', textContent: `${time} ${job.message ? '| ' + job.message : ''}` }),
        ]),
        job.status === 'running'
          ? el('div', { className: 'history-progress-mini' }, [
              el('div', { className: 'history-progress-mini-fill', style: `width: ${progress}%` }),
            ])
          : el('span', { className: `history-status ${job.status}`, textContent: job.status }),
      ]);

      list.appendChild(item);
    });
  }

  function viewJob(job) {
    if (job.status === 'completed' && job.result) {
      state.currentJobId = job.job_id;
      showResultSection(job);
    }
  }

  // ═══════════════════════════════════════════
  // Feedback
  // ═══════════════════════════════════════════

  function setRating(rating) {
    state.feedbackRating = rating;
    $$('.star-btn').forEach((btn, i) => {
      btn.classList.toggle('active', i < rating);
    });
  }

  async function submitFeedback(action) {
    if (!state.currentJobId) return;

    if (state.serverOnline) {
      try {
        const formData = new FormData();
        formData.append('streamer_id', state.selectedPersona || 'default');
        formData.append('clip_id', state.currentJobId);
        formData.append('rating', state.feedbackRating || 3);
        formData.append('action', action);

        await api('/api/feedback', {
          method: 'POST',
          body: formData,
        });
      } catch (e) {
        // Ignore
      }
    }

    showToast(t('toast.feedbackSent'), 'success');
  }

  // ═══════════════════════════════════════════
  // File Upload / Drag & Drop
  // ═══════════════════════════════════════════

  function setupDragDrop() {
    const dropZone = $('#drop-zone');
    const fileInput = $('#file-input');
    const inputWrapper = $('#input-wrapper');

    // Click to browse
    dropZone.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        handleFileSelected(e.target.files[0]);
      }
    });

    // Drag events on drop zone
    ['dragenter', 'dragover'].forEach(event => {
      dropZone.addEventListener(event, (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
      });
    });

    ['dragleave', 'drop'].forEach(event => {
      dropZone.addEventListener(event, (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
      });
    });

    dropZone.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        handleFileSelected(files[0]);
      }
    });

    // Also allow drag over the URL input
    ['dragenter', 'dragover'].forEach(event => {
      inputWrapper.addEventListener(event, (e) => {
        e.preventDefault();
        inputWrapper.classList.add('drag-over');
      });
    });

    ['dragleave', 'drop'].forEach(event => {
      inputWrapper.addEventListener(event, (e) => {
        e.preventDefault();
        inputWrapper.classList.remove('drag-over');
      });
    });

    inputWrapper.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        handleFileSelected(files[0]);
      }
    });
  }

  function handleFileSelected(file) {
    state.uploadedFile = file;
    const urlInput = $('#url-input');
    urlInput.value = file.name;
    showToast(`File selected: ${file.name}`, 'success');
  }

  // ═══════════════════════════════════════════
  // Navigation
  // ═══════════════════════════════════════════

  function setupNavigation() {
    $$('.nav-link').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        $$('.nav-link').forEach(l => l.classList.remove('active'));
        link.classList.add('active');

        const section = link.dataset.section;
        if (section) {
          const target = document.getElementById(section);
          if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        }
      });
    });

    // Highlight nav on scroll
    const sections = ['hero', 'templates', 'history'];
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const id = entry.target.id;
          $$('.nav-link').forEach(l => {
            l.classList.toggle('active', l.dataset.section === id);
          });
        }
      });
    }, { rootMargin: '-50% 0px', threshold: 0 });

    sections.forEach(id => {
      const section = document.getElementById(id);
      if (section) observer.observe(section);
    });
  }

  // ═══════════════════════════════════════════
  // Template Filters
  // ═══════════════════════════════════════════

  function setupTemplateFilters() {
    $$('.filter-pill').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.filter-pill').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderTemplates(state.templates, btn.dataset.filter);
      });
    });
  }

  // ═══════════════════════════════════════════
  // Event Bindings
  // ═══════════════════════════════════════════

  function bindEvents() {
    // Pipeline button
    $('#btn-pipeline').addEventListener('click', startPipeline);

    // Enter key on URL input
    $('#url-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') startPipeline();
    });

    // Language toggle
    $('#lang-toggle').addEventListener('click', toggleLanguage);

    // Cancel button
    $('#btn-cancel').addEventListener('click', () => {
      state.currentJobId = null;
      hideProgressSection();
      showToast('Pipeline cancelled', 'info');
    });

    // Result actions
    $('#btn-play-result').addEventListener('click', () => {
      const video = $('#result-video');
      const overlay = $('#player-overlay');
      video.play();
      overlay.classList.add('hidden');
    });

    $('#btn-download').addEventListener('click', () => {
      if (state.serverOnline && state.currentJobId) {
        // Try the generic job download endpoint first (works for pipeline + render jobs)
        window.open(`${API_BASE}/api/jobs/${state.currentJobId}/download`, '_blank');
      } else {
        showToast(t('toast.demoMode'), 'info');
      }
    });

    $('#btn-share').addEventListener('click', () => {
      if (navigator.share) {
        navigator.share({
          title: 'Kairo AI - My Viral Clip',
          text: 'Check out this clip I made with Kairo AI!',
          url: window.location.href,
        }).catch(() => {});
      } else {
        navigator.clipboard.writeText(window.location.href).then(() => {
          showToast('Link copied to clipboard!', 'success');
        });
      }
    });

    $('#btn-new-clip').addEventListener('click', () => {
      $('#result').classList.add('hidden');
      state.currentJobId = null;
      state.feedbackRating = 0;
      $('#url-input').value = '';
      state.uploadedFile = null;
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // Feedback stars
    $$('.star-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        setRating(parseInt(btn.dataset.rating));
      });
    });

    // Feedback actions
    $('#btn-approve').addEventListener('click', () => submitFeedback('approved'));
    $('#btn-modify').addEventListener('click', () => submitFeedback('modified'));
    $('#btn-reject').addEventListener('click', () => submitFeedback('rejected'));

    // Refresh jobs
    $('#btn-refresh-jobs').addEventListener('click', refreshJobs);
  }

  // ═══════════════════════════════════════════
  // Initialization
  // ═══════════════════════════════════════════

  async function init() {
    // Hide loading screen (faster when server is local)
    setTimeout(() => {
      $('#loading-screen').classList.add('hide');
    }, 1200);

    // Apply initial language
    applyLanguage();

    // Setup interactions
    setupNavigation();
    setupTemplateFilters();
    setupDragDrop();
    bindEvents();

    // Check server health
    const online = await checkServer();

    if (online) {
      showToast(t('toast.connected'), 'success');
      connectWebSocket();
    } else if (IS_DEMO) {
      showToast(t('toast.demoMode'), 'info', 6000);
    } else {
      showToast(t('toast.disconnected'), 'info', 5000);
    }

    // Load data
    await Promise.all([
      loadTemplates(),
      loadPersonas(),
    ]);

    // Load job history if online
    if (online) {
      refreshJobs();
    }

    // Periodic health check
    setInterval(async () => {
      const wasOnline = state.serverOnline;
      await checkServer();
      if (!wasOnline && state.serverOnline) {
        showToast(t('toast.connected'), 'success');
        connectWebSocket();
        refreshJobs();
      }
    }, 15000);
  }

  // Boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
