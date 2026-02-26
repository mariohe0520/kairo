/**
 * KAIRO -- Renderer Process (Desktop App)
 * Full UI state management, real API integration via window.kairo bridge,
 * autonomous pipeline support, and graceful server-not-ready handling.
 */

document.addEventListener('DOMContentLoaded', () => {

  // ======= STATE =======
  const state = {
    currentSection: 'dashboard',
    selectedTemplate: null,
    selectedPersona: 'hypeStreamer',
    vodLoaded: false,
    vodName: null,
    vodPath: null,       // Actual file path after ingest
    vodSource: null,     // Original source (file path or URL)
    analysisRun: false,
    analysisResult: null,
    serverReady: false,
    pipelineRunning: false,
    clipCandidates: [],
    currentIngestJobId: null,
    projects: [
      { id: 'demo-1', name: 'Valorant Session #12', clips: 3, time: '2m ago', color: '#8b5cf6' },
      { id: 'demo-2', name: 'CS2 Ranked Grind', clips: 7, time: '1h ago', color: '#3b82f6' },
      { id: 'demo-3', name: 'Apex Legends w/ Squad', clips: 5, time: 'Yesterday', color: '#06b6d4' },
    ],
    sliders: { bgm: 65, subtitles: 80, effects: 45, hook: 70, transitions: 55 },
  };

  // ======= TEMPLATE DATA (local fallback) =======
  const templates = [
    { id: 'comeback-king', name: 'Comeback King', icon: '\uD83D\uDC51', category: 'Narrative', description: 'Dramatic reversals -- deficit to victory.', duration: '45s-2m', mood: 'triumphant' },
    { id: 'clutch-master', name: 'Clutch Master', icon: '\uD83C\uDFAF', category: 'FPS', description: 'Clutch plays under pressure. Pure skill showcase.', duration: '30s-90s', mood: 'intense' },
    { id: 'rage-quit-montage', name: 'Rage Quit Montage', icon: '\uD83D\uDC80', category: 'Comedy', description: 'Tilts, fails, rage -- funny and shareable.', duration: '30s-90s', mood: 'chaotic' },
    { id: 'chill-highlights', name: 'Chill Highlights', icon: '\u2728', category: 'Universal', description: 'Smooth vibes. Aesthetic over hype.', duration: '1m-3m', mood: 'chill' },
    { id: 'kill-montage', name: 'Kill Montage', icon: '\uD83D\uDD2B', category: 'FPS', description: 'Rapid-fire kills. Headshots, multi-kills, aces.', duration: '20s-60s', mood: 'intense' },
    { id: 'session-story', name: 'Session Story', icon: '\uD83D\uDCD6', category: 'Narrative', description: 'Full session -> narrative arc with chapters.', duration: '2m-5m', mood: 'triumphant' },
    { id: 'tiktok-vertical', name: 'TikTok Vertical', icon: '\uD83D\uDCF1', category: 'Short-Form', description: 'Optimized for 9:16 vertical. Under 60s.', duration: '15s-60s', mood: 'intense' },
    { id: 'edu-breakdown', name: 'Educational Breakdown', icon: '\uD83C\uDF93', category: 'Educational', description: 'Annotated replay analysis with callouts.', duration: '1m-4m', mood: 'chill' },
    { id: 'hype-montage', name: 'Hype Montage', icon: '\uD83D\uDD25', category: 'Universal', description: 'Music-synced highlights. Beat drops = kills.', duration: '30s-90s', mood: 'intense' },
    { id: 'squad-moments', name: 'Squad Moments', icon: '\uD83E\uDD1D', category: 'Social', description: 'Best group plays, comms, team chemistry.', duration: '45s-2.5m', mood: 'triumphant' },
  ];

  // ======= SERVER STATUS & HEALTH =======
  const serverDot = document.getElementById('server-dot');
  const serverStatusText = document.getElementById('server-status-text');

  function setServerStatus(status, message) {
    state.serverReady = (status === 'online');
    if (serverDot) {
      serverDot.className = `status-dot ${status}`;
    }
    if (serverStatusText) {
      serverStatusText.textContent = message;
    }
  }

  async function checkServerHealth() {
    if (!window.kairo || !window.kairo.health) {
      setServerStatus('error', 'Bridge not available');
      return false;
    }
    try {
      const result = await window.kairo.health();
      if (result && result.status === 'ok') {
        setServerStatus('online', 'Backend ready');
        return true;
      }
      setServerStatus('connecting', 'Waiting for backend...');
      return false;
    } catch {
      setServerStatus('connecting', 'Waiting for backend...');
      return false;
    }
  }

  // Poll server health on startup
  let healthPollCount = 0;
  const healthPollMax = 120; // 2 minutes
  const healthPollInterval = setInterval(async () => {
    healthPollCount++;
    const ready = await checkServerHealth();
    if (ready) {
      clearInterval(healthPollInterval);
    } else if (healthPollCount >= healthPollMax) {
      clearInterval(healthPollInterval);
      setServerStatus('error', 'Backend timeout');
    }
  }, 1000);

  // Also check immediately
  checkServerHealth();

  // ======= PROGRESS EVENTS FROM MAIN PROCESS =======
  if (window.kairo && window.kairo.onProgress) {
    window.kairo.onProgress((data) => {
      if (data.type === 'server-status') {
        if (data.status === 'connected') {
          setServerStatus('online', 'Backend ready');
          clearInterval(healthPollInterval);
        } else if (data.status === 'error') {
          setServerStatus('error', data.message || 'Backend error');
        }
      }

      if (data.type === 'pipeline') {
        updatePipelineOverlay(data);
      }

      // Generic job progress
      if (data.job_id && data.progress !== undefined) {
        updateJobProgress(data);
      }
    });
  }

  function updateJobProgress(data) {
    // Update bottom bar progress if exporting
    const progressContainer = document.getElementById('export-progress');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');

    if (data.job_id && data.job_id.startsWith('render_')) {
      if (progressContainer) progressContainer.classList.remove('hidden');
      if (progressFill) progressFill.style.width = `${Math.round(data.progress * 100)}%`;
      if (progressText) progressText.textContent = data.message || `Rendering... ${Math.round(data.progress * 100)}%`;

      if (data.status === 'completed') {
        if (progressText) progressText.textContent = 'Export Complete!';
        setTimeout(() => {
          if (progressContainer) progressContainer.classList.add('hidden');
          if (progressFill) progressFill.style.width = '0%';
        }, 3000);
      }
    }
  }

  // ======= PIPELINE OVERLAY =======
  const pipelineOverlay = document.getElementById('pipeline-overlay');
  const pipelineMessage = document.getElementById('pipeline-message');
  const pipelineProgressFill = document.getElementById('pipeline-progress-fill');
  const btnPipelineCancel = document.getElementById('btn-pipeline-cancel');

  function showPipelineOverlay() {
    if (pipelineOverlay) pipelineOverlay.classList.remove('hidden');
    state.pipelineRunning = true;
    // Reset all stages
    ['stage-ingest', 'stage-analyze', 'stage-generate', 'stage-complete'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.className = 'pipeline-stage';
    });
    if (pipelineProgressFill) pipelineProgressFill.style.width = '0%';
    if (pipelineMessage) pipelineMessage.textContent = 'Initializing...';
  }

  function hidePipelineOverlay() {
    if (pipelineOverlay) pipelineOverlay.classList.add('hidden');
    state.pipelineRunning = false;
  }

  function updatePipelineOverlay(data) {
    if (pipelineMessage) pipelineMessage.textContent = data.message || '';
    if (pipelineProgressFill) pipelineProgressFill.style.width = `${Math.round((data.progress || 0) * 100)}%`;

    const stageMap = {
      'ingest': 'stage-ingest',
      'analyze': 'stage-analyze',
      'generate': 'stage-generate',
      'complete': 'stage-complete',
    };

    const stageOrder = ['ingest', 'analyze', 'generate', 'complete'];
    const currentIdx = stageOrder.indexOf(data.stage);

    stageOrder.forEach((stage, i) => {
      const el = document.getElementById(stageMap[stage]);
      if (!el) return;
      if (i < currentIdx) {
        el.className = 'pipeline-stage completed';
      } else if (i === currentIdx) {
        el.className = data.stage === 'error' ? 'pipeline-stage error' : 'pipeline-stage active';
      } else {
        el.className = 'pipeline-stage';
      }
    });

    if (data.stage === 'complete') {
      // Mark all as completed
      stageOrder.forEach(stage => {
        const el = document.getElementById(stageMap[stage]);
        if (el) el.className = 'pipeline-stage completed';
      });
    }

    if (data.stage === 'error') {
      if (pipelineMessage) pipelineMessage.textContent = data.message || 'Pipeline error';
    }
  }

  if (btnPipelineCancel) {
    btnPipelineCancel.addEventListener('click', () => {
      hidePipelineOverlay();
    });
  }

  // ======= RENDER TEMPLATES =======
  function renderTemplates(filter = 'all') {
    const grid = document.getElementById('template-grid');
    if (!grid) return;

    const filtered = filter === 'all' ? templates : templates.filter(t => t.category === filter);

    grid.innerHTML = filtered.map((t) => `
      <div class="template-card ${state.selectedTemplate === t.id ? 'selected' : ''}" data-template="${t.id}">
        <div class="template-preview tpl-bg-${templates.indexOf(t)}">
          <div class="template-overlay">
            <span class="template-tag">${t.category}</span>
          </div>
          <span class="template-icon-display">${t.icon}</span>
          <span class="template-duration">${t.duration}</span>
        </div>
        <div class="template-info">
          <h4>${t.name}</h4>
          <p>${t.description}</p>
        </div>
      </div>
    `).join('');

    // Bind click events
    grid.querySelectorAll('.template-card').forEach(card => {
      card.addEventListener('click', () => {
        state.selectedTemplate = card.dataset.template;
        grid.querySelectorAll('.template-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');

        const t = templates.find(t => t.id === state.selectedTemplate);
        if (t) {
          document.getElementById('story-title').innerHTML = `<span class="story-label">${t.icon} ${t.name}</span>`;
          updateStoryArc(t.mood);
        }
      });
    });
  }

  // ======= UPDATE STORY ARC VISUALIZATION =======
  function updateStoryArc(mood) {
    const profiles = {
      triumphant: [60, 45, 55, 70, 95, 85, 50, 35],
      intense: [80, 60, 70, 75, 98, 90, 55, 40],
      chaotic: [70, 40, 65, 50, 90, 95, 60, 30],
      chill: [40, 35, 45, 50, 65, 60, 45, 30],
    };

    const heights = profiles[mood] || profiles.chill;
    const phases = document.querySelectorAll('.story-phase .phase-bar');
    phases.forEach((bar, i) => {
      if (heights[i] !== undefined) {
        bar.style.height = `${heights[i]}%`;
      }
    });

    const loglines = {
      triumphant: '"Down 0-5, one player refuses to lose -- and what happens next is legendary."',
      intense: '"When the aim is on and the reads are perfect, this is what happens."',
      chaotic: '"It started as a normal game. It did not stay that way."',
      chill: '"Just a good session, captured in the best way possible."',
    };

    const loglineEl = document.getElementById('story-logline');
    if (loglineEl) loglineEl.textContent = loglines[mood] || loglines.chill;
  }

  // ======= ENHANCEMENT SLIDERS =======
  const sliders = document.querySelectorAll('.enhance-slider');
  sliders.forEach(slider => {
    const moduleId = slider.id.replace('slider-', '');
    const valueDisplay = document.getElementById(`val-${moduleId}`);

    const updateSlider = () => {
      const val = slider.value;
      state.sliders[moduleId] = parseInt(val);
      if (valueDisplay) valueDisplay.textContent = `${val}%`;

      const pct = val / 100;
      const purple = `rgba(139, 92, 246, ${0.3 + pct * 0.7})`;
      const blue = `rgba(59, 130, 246, ${0.3 + pct * 0.7})`;
      slider.style.background = `linear-gradient(90deg, ${purple} 0%, ${blue} ${val}%, var(--bg-elevated) ${val}%)`;
    };

    slider.addEventListener('input', updateSlider);
    updateSlider();
  });

  // ======= UPLOAD ZONE =======
  const uploadZone = document.getElementById('upload-zone');
  const btnUpload = document.getElementById('btn-upload-vod');
  const btnImportUrl = document.getElementById('btn-import-url');
  const btnAnalyze = document.getElementById('btn-analyze');

  if (uploadZone) {
    ['dragenter', 'dragover'].forEach(evt => {
      uploadZone.addEventListener(evt, e => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
    });
    ['dragleave', 'drop'].forEach(evt => {
      uploadZone.addEventListener(evt, e => { e.preventDefault(); uploadZone.classList.remove('drag-over'); });
    });
    uploadZone.addEventListener('drop', e => {
      if (e.dataTransfer.files.length > 0) {
        const file = e.dataTransfer.files[0];
        handleFileSelected({ name: file.name, path: file.path });
      }
    });
    uploadZone.addEventListener('click', openFileDialog);
  }

  if (btnUpload) btnUpload.addEventListener('click', openFileDialog);

  async function openFileDialog() {
    if (window.kairo && window.kairo.openVodDialog) {
      const result = await window.kairo.openVodDialog();
      if (!result.canceled && result.filePaths.length > 0) {
        const filePath = result.filePaths[0];
        handleFileSelected({ name: filePath.split('/').pop(), path: filePath });
      }
    } else {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'video/*';
      input.onchange = () => { if (input.files.length > 0) handleFileSelected(input.files[0]); };
      input.click();
    }
  }

  function handleFileSelected(file) {
    const name = file.name || file;
    const filePath = file.path || null;
    state.vodLoaded = true;
    state.vodName = name;
    state.vodSource = filePath || name;

    if (uploadZone) {
      uploadZone.innerHTML = `
        <div class="vod-loaded-display">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color: var(--accent-green);">
            <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>
            <polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
          <h3 style="color: var(--accent-green);">${name}</h3>
          <p>VOD loaded -- select a template and analyze</p>
        </div>
      `;
      uploadZone.style.borderColor = 'rgba(16, 185, 129, 0.4)';
    }

    if (btnAnalyze) btnAnalyze.disabled = false;

    // Update URL input with file path
    const urlInput = document.getElementById('url-input');
    if (urlInput && filePath) {
      urlInput.value = filePath;
    }

    // Show video controls
    const vc = document.getElementById('video-controls');
    if (vc) vc.classList.remove('hidden');

    // If server is ready, start ingesting immediately
    if (state.serverReady && filePath) {
      startIngest(filePath);
    }
  }

  // URL import via header button (legacy)
  if (btnImportUrl) {
    btnImportUrl.addEventListener('click', () => {
      const url = prompt('Paste Twitch or YouTube VOD URL:');
      if (url && url.trim()) {
        const urlInput = document.getElementById('url-input');
        if (urlInput) urlInput.value = url.trim();
        handleUrlInput(url.trim());
      }
    });
  }

  // ======= URL INPUT BAR =======
  const urlInput = document.getElementById('url-input');
  const btnAutoEdit = document.getElementById('btn-auto-edit');

  if (urlInput) {
    urlInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const val = urlInput.value.trim();
        if (val) {
          handleUrlInput(val);
        }
      }
    });

    // Support pasting
    urlInput.addEventListener('paste', () => {
      setTimeout(() => {
        const val = urlInput.value.trim();
        if (val && (val.startsWith('http://') || val.startsWith('https://'))) {
          // Auto-fill the source
          state.vodSource = val;
          state.vodName = val;
          state.vodLoaded = true;
          if (btnAnalyze) btnAnalyze.disabled = false;
        }
      }, 50);
    });
  }

  function handleUrlInput(url) {
    state.vodSource = url;
    state.vodName = url;
    state.vodLoaded = true;

    if (uploadZone) {
      uploadZone.innerHTML = `
        <div class="vod-loaded-display">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color: var(--accent-cyan);">
            <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/>
            <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/>
          </svg>
          <h3 style="color: var(--accent-cyan);">URL Loaded</h3>
          <p style="word-break: break-all; max-width: 400px;">${url}</p>
        </div>
      `;
      uploadZone.style.borderColor = 'rgba(6, 182, 212, 0.4)';
    }

    if (btnAnalyze) btnAnalyze.disabled = false;

    const vc = document.getElementById('video-controls');
    if (vc) vc.classList.remove('hidden');
  }

  // ======= AUTO EDIT (ONE-CLICK PIPELINE) =======
  if (btnAutoEdit) {
    btnAutoEdit.addEventListener('click', async () => {
      const source = (urlInput && urlInput.value.trim()) || state.vodSource;
      if (!source) {
        alert('Please paste a URL or select a video file first.');
        return;
      }

      if (!state.serverReady) {
        alert('Backend server is not ready yet. Please wait a moment and try again.');
        return;
      }

      await runFullPipeline(source);
    });
  }

  async function runFullPipeline(source) {
    showPipelineOverlay();
    btnAutoEdit.disabled = true;
    btnAutoEdit.classList.add('running');
    btnAutoEdit.innerHTML = '<span class="spinner"></span> Running...';

    try {
      const result = await window.kairo.runPipeline(source, state.selectedPersona || 'default');

      hidePipelineOverlay();

      if (result.error) {
        alert(`Pipeline failed: ${result.error}`);
      } else {
        // Store results
        state.vodPath = result.video_path;
        state.analysisResult = result.analysis;
        state.clipCandidates = result.clips || [];
        state.analysisRun = true;

        // Update UI with analysis results
        updateAnalysisUI(result.analysis);

        // Show clip candidates
        if (state.clipCandidates.length > 0) {
          showResultsPanel(state.clipCandidates);
        }

        // Auto-select template from analysis
        if (result.analysis && result.analysis.template_id) {
          state.selectedTemplate = result.analysis.template_id;
          renderTemplates();
          const tpl = templates.find(t => t.id === state.selectedTemplate);
          if (tpl) {
            document.getElementById('story-title').innerHTML = `<span class="story-label">${tpl.icon} ${tpl.name}</span>`;
            updateStoryArc(tpl.mood);
          }
        }
      }
    } catch (err) {
      hidePipelineOverlay();
      alert(`Pipeline error: ${err.message || err}`);
    }

    btnAutoEdit.disabled = false;
    btnAutoEdit.classList.remove('running');
    btnAutoEdit.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
      Auto Edit
    `;
  }

  // ======= INGEST =======
  async function startIngest(source) {
    if (!window.kairo || !window.kairo.ingest) return;
    if (!state.serverReady) return;

    const statusBadge = document.getElementById('analysis-status');
    if (statusBadge) { statusBadge.textContent = 'Ingesting...'; }

    try {
      const result = await window.kairo.ingest(source);
      if (result.error) {
        console.error('Ingest failed:', result.error);
        if (statusBadge) statusBadge.textContent = 'Ingest Failed';
        return;
      }
      state.currentIngestJobId = result.job_id;
      if (statusBadge) statusBadge.textContent = 'Ingesting...';

      // Poll for completion
      pollIngestStatus(result.job_id);
    } catch (err) {
      console.error('Ingest error:', err);
      if (statusBadge) statusBadge.textContent = 'Ingest Error';
    }
  }

  async function pollIngestStatus(jobId) {
    const statusBadge = document.getElementById('analysis-status');
    const poll = setInterval(async () => {
      try {
        const status = await window.kairo.ingestStatus(jobId);
        if (status.status === 'completed') {
          clearInterval(poll);
          state.vodPath = status.result?.video_path;
          if (statusBadge) statusBadge.textContent = 'Ready to Analyze';
        } else if (status.status === 'failed') {
          clearInterval(poll);
          if (statusBadge) statusBadge.textContent = 'Ingest Failed';
        }
      } catch {
        clearInterval(poll);
      }
    }, 2000);
  }

  // ======= ANALYSIS =======
  if (btnAnalyze) {
    btnAnalyze.addEventListener('click', () => {
      runAnalysis();
    });
  }

  async function runAnalysis() {
    const statusBadge = document.getElementById('analysis-status');
    const content = document.getElementById('analysis-content');
    const statusDot = document.querySelector('#server-dot');
    const statusText = document.querySelector('#server-status-text');

    if (statusBadge) { statusBadge.textContent = 'Analyzing...'; statusBadge.classList.add('active'); }
    if (btnAnalyze) { btnAnalyze.disabled = true; btnAnalyze.innerHTML = '<span class="spinner"></span> Analyzing...'; }

    // Determine video path: use ingested path if available, otherwise source
    const videoPath = state.vodPath || state.vodSource;

    if (!videoPath) {
      if (statusBadge) statusBadge.textContent = 'No video loaded';
      if (btnAnalyze) { btnAnalyze.disabled = false; btnAnalyze.innerHTML = 'Analyze VOD'; }
      return;
    }

    // If server is ready, use real API
    if (state.serverReady && window.kairo && window.kairo.analyze) {
      try {
        const result = await window.kairo.analyze(videoPath, {
          templateId: state.selectedTemplate,
          personaId: state.selectedPersona,
        });

        if (result.error) {
          console.error('Analysis failed:', result.error);
          // Fall back to mock
          runMockAnalysis();
          return;
        }

        // Poll for analysis completion
        if (result.job_id) {
          pollAnalysisStatus(result.job_id);
        }
      } catch (err) {
        console.error('Analysis error:', err);
        runMockAnalysis();
      }
    } else {
      // Server not ready, use mock analysis
      runMockAnalysis();
    }
  }

  async function pollAnalysisStatus(jobId) {
    const statusBadge = document.getElementById('analysis-status');
    const poll = setInterval(async () => {
      try {
        const status = await window.kairo.ingestStatus(jobId); // uses generic job endpoint
        if (!status || status.error) {
          // Try the generic endpoint
          clearInterval(poll);
          onAnalysisComplete(null);
          return;
        }
        if (status.status === 'completed') {
          clearInterval(poll);
          state.analysisResult = status.result;
          state.analysisRun = true;
          onAnalysisComplete(status.result);
        } else if (status.status === 'failed') {
          clearInterval(poll);
          if (statusBadge) statusBadge.textContent = 'Analysis Failed';
          resetAnalyzeButton();
          // Fall back to mock
          runMockAnalysis();
        }
      } catch {
        clearInterval(poll);
        runMockAnalysis();
      }
    }, 1500);
  }

  function onAnalysisComplete(result) {
    const statusBadge = document.getElementById('analysis-status');

    state.analysisRun = true;
    updateAnalysisUI(result);
    resetAnalyzeButton();

    // Auto-select template
    if (result && result.template_id && !state.selectedTemplate) {
      state.selectedTemplate = result.template_id;
      renderTemplates();
      const tpl = templates.find(t => t.id === state.selectedTemplate);
      if (tpl) {
        document.getElementById('story-title').innerHTML = `<span class="story-label">${tpl.icon} ${tpl.name}</span>`;
        updateStoryArc(tpl.mood);
      }
    }
  }

  function updateAnalysisUI(result) {
    const statusBadge = document.getElementById('analysis-status');
    const content = document.getElementById('analysis-content');

    if (result && result.status === 'analysis_complete') {
      if (statusBadge) statusBadge.textContent = 'Analysis Complete';

      if (content) {
        const info = `
          <div class="highlight-item">
            <span class="highlight-score high">OK</span>
            <div class="highlight-info">
              <span class="highlight-type objective">STATUS</span>
              <span class="highlight-desc">${result.message || 'Analysis pipeline ready'}</span>
            </div>
          </div>
        `;

        let templateInfo = '';
        if (result.template_id) {
          const tpl = templates.find(t => t.id === result.template_id);
          templateInfo = `
            <div class="highlight-item">
              <span class="highlight-score medium">${tpl ? tpl.icon : '?'}</span>
              <div class="highlight-info">
                <span class="highlight-type clutch">TEMPLATE</span>
                <span class="highlight-desc">${tpl ? tpl.name : result.template_id}</span>
              </div>
            </div>
          `;
        }

        let recInfo = '';
        if (result.recommendations) {
          recInfo = `
            <div class="highlight-item">
              <span class="highlight-score high">${Math.round((result.recommendations.confidence || 0) * 100)}</span>
              <div class="highlight-info">
                <span class="highlight-type emotion">CONFIDENCE</span>
                <span class="highlight-desc">${result.recommendations.reasoning || 'AI recommendation'}</span>
              </div>
            </div>
          `;
        }

        content.innerHTML = info + templateInfo + recInfo;
      }
    } else {
      // No real analysis result, show completed status
      if (statusBadge) statusBadge.textContent = 'Ready';
    }
  }

  function resetAnalyzeButton() {
    if (btnAnalyze) {
      btnAnalyze.disabled = false;
      btnAnalyze.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26z"/></svg>
        Re-Analyze
      `;
    }
  }

  // ======= MOCK ANALYSIS (fallback when server unavailable) =======
  const mockHighlights = [
    { time: '0:12', type: 'emotion', score: 30, desc: 'Caught off-guard -- pistol round death' },
    { time: '0:45', type: 'kill', score: 55, desc: 'First blood -- a spark of hope' },
    { time: '1:20', type: 'clutch', score: 72, desc: '1v2 clutch to save the round' },
    { time: '2:10', type: 'kill', score: 65, desc: 'Eco round ace -- 5K spray transfer' },
    { time: '3:00', type: 'objective', score: 60, desc: 'Score tied 5-5 -- momentum shift' },
    { time: '3:55', type: 'clutch', score: 92, desc: '1v3 clutch with 5HP -- the play' },
    { time: '4:40', type: 'kill', score: 88, desc: 'Triple kill to close out the half' },
    { time: '5:50', type: 'clutch', score: 96, desc: 'Match point 1v4 -- the impossible ace' },
    { time: '6:18', type: 'emotion', score: 85, desc: 'Pure celebration -- GG WP' },
  ];

  function runMockAnalysis() {
    const statusBadge = document.getElementById('analysis-status');
    const content = document.getElementById('analysis-content');

    if (statusBadge) { statusBadge.textContent = 'Analyzing...'; statusBadge.classList.add('active'); }
    if (btnAnalyze) { btnAnalyze.disabled = true; btnAnalyze.innerHTML = '<span class="spinner"></span> Analyzing...'; }

    setTimeout(() => {
      state.analysisRun = true;

      if (statusBadge) { statusBadge.textContent = `${mockHighlights.length} Highlights`; }
      resetAnalyzeButton();

      if (content) {
        content.innerHTML = mockHighlights.map(h => {
          const scoreClass = h.score >= 80 ? 'high' : h.score >= 60 ? 'medium' : 'low';
          return `
            <div class="highlight-item">
              <span class="highlight-score ${scoreClass}">${h.score}</span>
              <div class="highlight-info">
                <span class="highlight-type ${h.type}">${h.type}</span>
                <span class="highlight-desc">${h.desc}</span>
              </div>
              <span class="highlight-time">${h.time}</span>
            </div>
          `;
        }).join('');
      }

      if (!state.selectedTemplate) {
        state.selectedTemplate = 'comeback-king';
        renderTemplates();
        updateStoryArc('triumphant');
        document.getElementById('story-title').innerHTML = '<span class="story-label">\uD83D\uDC51 Comeback King</span>';
      }
    }, 2000);
  }

  // ======= RESULTS PANEL =======
  const resultsPanel = document.getElementById('results-panel');
  const resultsGrid = document.getElementById('results-grid');
  const btnCloseResults = document.getElementById('btn-close-results');
  const btnDismissResults = document.getElementById('btn-results-dismiss');
  const btnExportApproved = document.getElementById('btn-export-approved');

  function showResultsPanel(clips) {
    if (!resultsPanel || !resultsGrid) return;

    resultsGrid.innerHTML = clips.map((clip, i) => {
      const tpl = templates.find(t => t.id === clip.template_id);
      const scoreClass = clip.quality_score >= 80 ? 'high' : clip.quality_score >= 60 ? 'medium' : 'low';
      const gradientClass = `g${(i % 3) + 1}`;

      return `
        <div class="result-card" data-clip-index="${i}" id="result-card-${i}">
          <div class="result-card-header">
            <span class="result-template-name">${tpl ? `${tpl.icon} ${tpl.name}` : clip.template_id}</span>
            <span class="result-score ${scoreClass}">${clip.quality_score}</span>
          </div>
          <div class="result-card-body">
            <p class="result-meta">
              ${tpl ? tpl.description : 'Generated clip'}
              ${clip.edit_script ? `<br>Duration: ${clip.edit_script.total_output_duration || 'N/A'}s` : ''}
            </p>
          </div>
          <div class="result-card-actions">
            <button class="btn-tiny btn-approve" onclick="approveClip(${i})">Approve</button>
            <button class="btn-tiny btn-reject" onclick="rejectClip(${i})">Reject</button>
          </div>
        </div>
      `;
    }).join('');

    resultsPanel.classList.remove('hidden');
  }

  function hideResultsPanel() {
    if (resultsPanel) resultsPanel.classList.add('hidden');
  }

  // Global functions for inline onclick handlers
  window.approveClip = function(index) {
    const card = document.getElementById(`result-card-${index}`);
    if (card) {
      card.classList.remove('rejected');
      card.classList.add('approved');
    }
    if (state.clipCandidates[index]) {
      state.clipCandidates[index].approved = true;
      state.clipCandidates[index].rejected = false;

      // Submit positive feedback
      if (window.kairo && window.kairo.submitFeedback) {
        window.kairo.submitFeedback({
          clipId: state.clipCandidates[index].id,
          action: 'approved',
          rating: 4,
          templateId: state.clipCandidates[index].template_id,
          enhancements: state.sliders,
        });
      }
    }
  };

  window.rejectClip = function(index) {
    const card = document.getElementById(`result-card-${index}`);
    if (card) {
      card.classList.remove('approved');
      card.classList.add('rejected');
    }
    if (state.clipCandidates[index]) {
      state.clipCandidates[index].approved = false;
      state.clipCandidates[index].rejected = true;

      // Submit negative feedback
      if (window.kairo && window.kairo.submitFeedback) {
        window.kairo.submitFeedback({
          clipId: state.clipCandidates[index].id,
          action: 'rejected',
          rating: 2,
          templateId: state.clipCandidates[index].template_id,
        });
      }
    }
  };

  if (btnCloseResults) btnCloseResults.addEventListener('click', hideResultsPanel);
  if (btnDismissResults) btnDismissResults.addEventListener('click', hideResultsPanel);

  // ======= EXPORT APPROVED CLIPS =======
  if (btnExportApproved) {
    btnExportApproved.addEventListener('click', async () => {
      const approved = state.clipCandidates.filter(c => c.approved);
      if (approved.length === 0) {
        alert('No clips approved. Approve at least one clip to export.');
        return;
      }

      if (!state.serverReady) {
        alert('Backend server is not ready. Cannot export.');
        return;
      }

      // Render each approved clip
      for (const clip of approved) {
        if (clip.edit_script) {
          try {
            const result = await window.kairo.render(clip.edit_script);
            if (result.error) {
              console.error(`Render failed for ${clip.id}:`, result.error);
            }
          } catch (err) {
            console.error(`Render error for ${clip.id}:`, err);
          }
        }
      }

      hideResultsPanel();
    });
  }

  // ======= EXPORT BUTTON (bottom bar) =======
  const btnExport = document.getElementById('btn-export');
  const btnPreview = document.getElementById('btn-preview-export');

  if (btnExport) {
    btnExport.addEventListener('click', async () => {
      if (state.serverReady && window.kairo && window.kairo.generate && state.vodPath) {
        // Real export: generate then render
        const progressContainer = document.getElementById('export-progress');
        const progressFill = document.getElementById('progress-fill');
        const progressText = document.getElementById('progress-text');

        if (progressContainer) progressContainer.classList.remove('hidden');
        if (progressText) progressText.textContent = 'Generating edit script...';

        try {
          const genResult = await window.kairo.generate(
            state.vodPath,
            state.selectedTemplate || 'chill-highlights',
            state.selectedPersona || undefined
          );

          if (genResult.error) {
            if (progressText) progressText.textContent = `Error: ${genResult.error}`;
            setTimeout(() => { if (progressContainer) progressContainer.classList.add('hidden'); }, 3000);
            return;
          }

          if (genResult.edit_script) {
            if (progressText) progressText.textContent = 'Starting render...';

            const renderResult = await window.kairo.render(genResult.edit_script);
            if (renderResult.error) {
              if (progressText) progressText.textContent = `Render error: ${renderResult.error}`;
              setTimeout(() => { if (progressContainer) progressContainer.classList.add('hidden'); }, 3000);
            }
            // Progress updates come via the onProgress listener
          }
        } catch (err) {
          if (progressText) progressText.textContent = `Error: ${err.message}`;
          setTimeout(() => { if (progressContainer) progressContainer.classList.add('hidden'); }, 3000);
        }
      } else {
        // Mock export
        runMockExport();
      }
    });
  }

  function runMockExport() {
    const progressContainer = document.getElementById('export-progress');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');

    if (progressContainer) progressContainer.classList.remove('hidden');

    let pct = 0;
    const interval = setInterval(() => {
      pct += Math.random() * 8 + 2;
      if (pct >= 100) {
        pct = 100;
        clearInterval(interval);
        if (progressText) progressText.textContent = 'Export Complete!';
        setTimeout(() => {
          if (progressContainer) progressContainer.classList.add('hidden');
          if (progressFill) progressFill.style.width = '0%';
        }, 2000);
      }
      if (progressFill) progressFill.style.width = `${pct}%`;
      if (progressText && pct < 100) progressText.textContent = `Rendering... ${Math.round(pct)}%`;
    }, 200);
  }

  // ======= SIDEBAR NAVIGATION =======
  const navItems = document.querySelectorAll('.nav-item');
  navItems.forEach(item => {
    item.addEventListener('click', e => {
      e.preventDefault();
      navItems.forEach(n => n.classList.remove('active'));
      item.classList.add('active');

      const section = item.dataset.section;
      state.currentSection = section;

      const titleEl = document.getElementById('page-title');
      const subtitleEl = document.getElementById('page-subtitle');
      if (titleEl) titleEl.textContent = section.charAt(0).toUpperCase() + section.slice(1);

      const subtitles = {
        dashboard: 'Create story-driven clips from your gaming VODs',
        projects: 'Manage your clip projects',
        templates: 'Choose your narrative template',
        personas: 'Select and customize streamer personas',
        enhance: 'Fine-tune your enhancement settings',
        export: 'Export your finished clips',
      };
      if (subtitleEl) subtitleEl.textContent = subtitles[section] || '';
    });
  });

  // ======= TEMPLATE FILTERS =======
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderTemplates(btn.dataset.filter);
    });
  });

  // ======= RIGHT PANEL TABS =======
  document.querySelectorAll('.rpanel-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.rpanel-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      const tabId = tab.dataset.tab;
      document.querySelectorAll('.rpanel-content').forEach(c => c.classList.add('hidden'));
      const content = document.getElementById(`tab-${tabId}`);
      if (content) content.classList.remove('hidden');
    });
  });

  // ======= PERSONA SELECTOR =======
  document.querySelectorAll('.persona-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.persona-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      state.selectedPersona = chip.dataset.persona;

      const presets = {
        hypeStreamer: { bgm: 75, subtitles: 60, effects: 85, hook: 95, transitions: 65 },
        chillStreamer: { bgm: 90, subtitles: 40, effects: 25, hook: 40, transitions: 85 },
        chaosGremlin: { bgm: 65, subtitles: 90, effects: 100, hook: 85, transitions: 95 },
        tactician: { bgm: 40, subtitles: 85, effects: 50, hook: 50, transitions: 70 },
        squadCaptain: { bgm: 65, subtitles: 80, effects: 55, hook: 70, transitions: 75 },
      };

      const preset = presets[state.selectedPersona];
      if (preset) {
        Object.entries(preset).forEach(([key, val]) => {
          const slider = document.getElementById(`slider-${key}`);
          if (slider) {
            slider.value = val;
            slider.dispatchEvent(new Event('input'));
          }
        });
      }
    });
  });

  // ======= PROJECT LIST =======
  document.querySelectorAll('.project-item').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.project-item').forEach(p => p.classList.remove('active'));
      item.classList.add('active');
    });
  });

  const btnNewProject = document.getElementById('btn-new-project');
  if (btnNewProject) {
    btnNewProject.addEventListener('click', () => {
      const name = prompt('Project name:');
      if (name && name.trim()) {
        const colors = ['#8b5cf6', '#3b82f6', '#06b6d4', '#10b981', '#f59e0b', '#ec4899'];
        const newProject = {
          id: `proj-${Date.now()}`,
          name: name.trim(),
          clips: 0,
          time: 'Just now',
          color: colors[Math.floor(Math.random() * colors.length)],
        };
        state.projects.unshift(newProject);

        const list = document.getElementById('project-list');
        if (list) {
          const el = document.createElement('div');
          el.className = 'project-item active';
          el.dataset.id = newProject.id;
          el.innerHTML = `
            <div class="project-color" style="background: ${newProject.color};"></div>
            <div class="project-info">
              <span class="project-name">${newProject.name}</span>
              <span class="project-meta">${newProject.clips} clips - ${newProject.time}</span>
            </div>
          `;
          list.querySelectorAll('.project-item').forEach(p => p.classList.remove('active'));
          list.prepend(el);
        }
      }
    });
  }

  // ======= TIMELINE PLAYHEAD ANIMATION =======
  const playhead = document.getElementById('playhead');
  let playheadPos = 70;
  let playheadDirection = 1;
  let playheadActive = true;

  function animatePlayhead() {
    const container = document.getElementById('timeline-container');
    if (!container || !playheadActive) { requestAnimationFrame(animatePlayhead); return; }

    const maxLeft = container.offsetWidth - 16;
    playheadPos += playheadDirection * 0.4;
    if (playheadPos >= maxLeft) playheadDirection = -1;
    if (playheadPos <= 70) playheadDirection = 1;

    if (playhead) playhead.style.left = `${playheadPos}px`;
    requestAnimationFrame(animatePlayhead);
  }

  animatePlayhead();

  const tlPlay = document.getElementById('tl-play');
  if (tlPlay) {
    tlPlay.addEventListener('click', () => {
      playheadActive = !playheadActive;
      tlPlay.textContent = playheadActive ? '\u23F8' : '\u25B6';
    });
  }

  // ======= KEYBOARD SHORTCUTS =======
  document.addEventListener('keydown', e => {
    if (e.code === 'Space' && e.target === document.body) {
      e.preventDefault();
      playheadActive = !playheadActive;
      if (tlPlay) tlPlay.textContent = playheadActive ? '\u23F8' : '\u25B6';
    }
  });

  // ======= INIT =======
  renderTemplates();

  // Console branding
  console.log(
    '%cKAIRO%c v0.3.0 -- AI Story-Driven Gaming Clips (Connected)',
    'background: linear-gradient(135deg, #8b5cf6, #3b82f6); color: white; padding: 8px 16px; border-radius: 4px; font-weight: bold; font-size: 14px;',
    'color: #8888a0; padding: 8px; font-size: 12px;'
  );
});
