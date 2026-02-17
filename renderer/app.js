/**
 * KAIRO — Renderer Process (Desktop App)
 * Full UI state management, template rendering, mock analysis, and interactions.
 */

document.addEventListener('DOMContentLoaded', () => {

  // ═══════ STATE ═══════
  const state = {
    currentSection: 'dashboard',
    selectedTemplate: null,
    selectedPersona: 'hypeStreamer',
    vodLoaded: false,
    vodName: null,
    analysisRun: false,
    projects: [
      { id: 'demo-1', name: 'Valorant Session #12', clips: 3, time: '2m ago', color: '#8b5cf6' },
      { id: 'demo-2', name: 'CS2 Ranked Grind', clips: 7, time: '1h ago', color: '#3b82f6' },
      { id: 'demo-3', name: 'Apex Legends w/ Squad', clips: 5, time: 'Yesterday', color: '#06b6d4' },
    ],
    sliders: { bgm: 65, subtitles: 80, effects: 45, hook: 70, transitions: 55 },
  };

  // ═══════ TEMPLATE DATA ═══════
  const templates = [
    { id: 'comeback-king', name: 'Comeback King', icon: '👑', category: 'Narrative', description: 'Dramatic reversals — deficit to victory.', duration: '45s–2m', mood: 'triumphant' },
    { id: 'clutch-master', name: 'Clutch Master', icon: '🎯', category: 'FPS', description: 'Clutch plays under pressure. Pure skill showcase.', duration: '30s–90s', mood: 'intense' },
    { id: 'rage-quit-montage', name: 'Rage Quit Montage', icon: '💀', category: 'Comedy', description: 'Tilts, fails, rage — funny and shareable.', duration: '30s–90s', mood: 'chaotic' },
    { id: 'chill-highlights', name: 'Chill Highlights', icon: '✨', category: 'Universal', description: 'Smooth vibes. Aesthetic over hype.', duration: '1m–3m', mood: 'chill' },
    { id: 'kill-montage', name: 'Kill Montage', icon: '🔫', category: 'FPS', description: 'Rapid-fire kills. Headshots, multi-kills, aces.', duration: '20s–60s', mood: 'intense' },
    { id: 'session-story', name: 'Session Story', icon: '📖', category: 'Narrative', description: 'Full session → narrative arc with chapters.', duration: '2m–5m', mood: 'triumphant' },
    { id: 'tiktok-vertical', name: 'TikTok Vertical', icon: '📱', category: 'Short-Form', description: 'Optimized for 9:16 vertical. Under 60s.', duration: '15s–60s', mood: 'intense' },
    { id: 'edu-breakdown', name: 'Educational Breakdown', icon: '🎓', category: 'Educational', description: 'Annotated replay analysis with callouts.', duration: '1m–4m', mood: 'chill' },
    { id: 'hype-montage', name: 'Hype Montage', icon: '🔥', category: 'Universal', description: 'Music-synced highlights. Beat drops = kills.', duration: '30s–90s', mood: 'intense' },
    { id: 'squad-moments', name: 'Squad Moments', icon: '🤝', category: 'Social', description: 'Best group plays, comms, team chemistry.', duration: '45s–2.5m', mood: 'triumphant' },
  ];

  // ═══════ MOCK HIGHLIGHTS DATA ═══════
  const mockHighlights = [
    { time: '0:12', type: 'emotion', score: 30, desc: 'Caught off-guard — pistol round death' },
    { time: '0:45', type: 'kill', score: 55, desc: 'First blood — a spark of hope' },
    { time: '1:20', type: 'clutch', score: 72, desc: '1v2 clutch to save the round' },
    { time: '2:10', type: 'kill', score: 65, desc: 'Eco round ace — 5K spray transfer' },
    { time: '3:00', type: 'objective', score: 60, desc: 'Score tied 5-5 — momentum shift' },
    { time: '3:55', type: 'clutch', score: 92, desc: '1v3 clutch with 5HP — the play' },
    { time: '4:40', type: 'kill', score: 88, desc: 'Triple kill to close out the half' },
    { time: '5:50', type: 'clutch', score: 96, desc: 'Match point 1v4 — the impossible ace' },
    { time: '6:18', type: 'emotion', score: 85, desc: 'Pure celebration — GG WP' },
  ];

  // ═══════ RENDER TEMPLATES ═══════
  function renderTemplates(filter = 'all') {
    const grid = document.getElementById('template-grid');
    if (!grid) return;

    const filtered = filter === 'all' ? templates : templates.filter(t => t.category === filter);

    grid.innerHTML = filtered.map((t, i) => `
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

  // ═══════ UPDATE STORY ARC VISUALIZATION ═══════
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
      triumphant: '"Down 0-5, one player refuses to lose — and what happens next is legendary."',
      intense: '"When the aim is on and the reads are perfect, this is what happens."',
      chaotic: '"It started as a normal game. It did not stay that way."',
      chill: '"Just a good session, captured in the best way possible."',
    };

    const loglineEl = document.getElementById('story-logline');
    if (loglineEl) loglineEl.textContent = loglines[mood] || loglines.chill;
  }

  // ═══════ ENHANCEMENT SLIDERS ═══════
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

  // ═══════ UPLOAD ZONE ═══════
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
      if (e.dataTransfer.files.length > 0) handleFileSelected(e.dataTransfer.files[0]);
    });
    uploadZone.addEventListener('click', openFileDialog);
  }

  if (btnUpload) btnUpload.addEventListener('click', openFileDialog);

  async function openFileDialog() {
    if (window.kairo && window.kairo.openVodDialog) {
      const result = await window.kairo.openVodDialog();
      if (!result.canceled && result.filePaths.length > 0) {
        handleFileSelected({ name: result.filePaths[0].split('/').pop(), path: result.filePaths[0] });
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
    state.vodLoaded = true;
    state.vodName = name;

    if (uploadZone) {
      uploadZone.innerHTML = `
        <div class="vod-loaded-display">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color: var(--accent-green);">
            <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>
            <polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
          <h3 style="color: var(--accent-green);">📂 ${name}</h3>
          <p>VOD loaded — select a template and analyze</p>
        </div>
      `;
      uploadZone.style.borderColor = 'rgba(16, 185, 129, 0.4)';
    }

    if (btnAnalyze) btnAnalyze.disabled = false;

    // Show video controls
    const vc = document.getElementById('video-controls');
    if (vc) vc.classList.remove('hidden');
  }

  if (btnImportUrl) {
    btnImportUrl.addEventListener('click', () => {
      const url = prompt('Paste Twitch or YouTube VOD URL:');
      if (url && url.trim()) handleFileSelected({ name: url.trim() });
    });
  }

  // ═══════ MOCK ANALYSIS ═══════
  if (btnAnalyze) {
    btnAnalyze.addEventListener('click', () => {
      runMockAnalysis();
    });
  }

  function runMockAnalysis() {
    const statusBadge = document.getElementById('analysis-status');
    const content = document.getElementById('analysis-content');
    const statusDot = document.querySelector('.status-dot');
    const statusText = document.querySelector('.status-text');

    if (statusBadge) { statusBadge.textContent = 'Analyzing...'; statusBadge.classList.add('active'); }
    if (statusDot) { statusDot.className = 'status-dot processing'; }
    if (statusText) { statusText.textContent = 'Analyzing VOD...'; }
    if (btnAnalyze) { btnAnalyze.disabled = true; btnAnalyze.innerHTML = '<span class="spinner"></span> Analyzing...'; }

    // Simulate analysis time
    setTimeout(() => {
      state.analysisRun = true;

      if (statusBadge) { statusBadge.textContent = `${mockHighlights.length} Highlights`; }
      if (statusDot) { statusDot.className = 'status-dot online'; }
      if (statusText) { statusText.textContent = 'Analysis Complete'; }
      if (btnAnalyze) { btnAnalyze.disabled = false; btnAnalyze.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26z"/></svg>
        Re-Analyze
      `; }

      // Render highlights
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

      // Auto-select best template if none selected
      if (!state.selectedTemplate) {
        state.selectedTemplate = 'comeback-king';
        renderTemplates();
        updateStoryArc('triumphant');
        document.getElementById('story-title').innerHTML = '<span class="story-label">👑 Comeback King</span>';
      }
    }, 2000);
  }

  // ═══════ SIDEBAR NAVIGATION ═══════
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

  // ═══════ TEMPLATE FILTERS ═══════
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderTemplates(btn.dataset.filter);
    });
  });

  // ═══════ RIGHT PANEL TABS ═══════
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

  // ═══════ PERSONA SELECTOR ═══════
  document.querySelectorAll('.persona-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.persona-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      state.selectedPersona = chip.dataset.persona;

      // Adjust sliders based on persona
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

  // ═══════ PROJECT LIST ═══════
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
              <span class="project-meta">${newProject.clips} clips • ${newProject.time}</span>
            </div>
          `;
          list.querySelectorAll('.project-item').forEach(p => p.classList.remove('active'));
          list.prepend(el);
        }
      }
    });
  }

  // ═══════ EXPORT MOCK ═══════
  const btnExport = document.getElementById('btn-export');
  const btnPreview = document.getElementById('btn-preview-export');

  if (btnExport) {
    btnExport.addEventListener('click', () => {
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
          if (progressText) progressText.textContent = 'Export Complete! ✓';
          setTimeout(() => {
            if (progressContainer) progressContainer.classList.add('hidden');
            if (progressFill) progressFill.style.width = '0%';
          }, 2000);
        }
        if (progressFill) progressFill.style.width = `${pct}%`;
        if (progressText && pct < 100) progressText.textContent = `Rendering... ${Math.round(pct)}%`;
      }, 200);
    });
  }

  // ═══════ TIMELINE PLAYHEAD ANIMATION ═══════
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

  // Timeline play button
  const tlPlay = document.getElementById('tl-play');
  if (tlPlay) {
    tlPlay.addEventListener('click', () => {
      playheadActive = !playheadActive;
      tlPlay.textContent = playheadActive ? '⏸' : '▶';
    });
  }

  // ═══════ KEYBOARD SHORTCUTS ═══════
  document.addEventListener('keydown', e => {
    if (e.code === 'Space' && e.target === document.body) {
      e.preventDefault();
      playheadActive = !playheadActive;
      if (tlPlay) tlPlay.textContent = playheadActive ? '⏸' : '▶';
    }
  });

  // ═══════ INIT ═══════
  renderTemplates();

  // Console branding
  console.log(
    '%cKAIRO%c v0.2.0 — AI Story-Driven Gaming Clips',
    'background: linear-gradient(135deg, #8b5cf6, #3b82f6); color: white; padding: 8px 16px; border-radius: 4px; font-weight: bold; font-size: 14px;',
    'color: #8888a0; padding: 8px; font-size: 12px;'
  );
});
