/**
 * KAIRO — Renderer Process
 * UI interactions for the prototype landing page
 */

document.addEventListener('DOMContentLoaded', () => {

  // ─── Enhancement Sliders ───────────────────────────────────
  const sliders = document.querySelectorAll('.enhance-slider');
  sliders.forEach(slider => {
    const moduleId = slider.id.replace('slider-', '');
    const valueDisplay = document.getElementById(`val-${moduleId}`);

    // Update value display and track fill
    const updateSlider = () => {
      const val = slider.value;
      valueDisplay.textContent = `${val}%`;

      // CSS gradient fill for the track
      const pct = val / 100;
      const purple = `rgba(139, 92, 246, ${0.3 + pct * 0.7})`;
      const blue = `rgba(59, 130, 246, ${0.3 + pct * 0.7})`;
      slider.style.background = `linear-gradient(90deg, ${purple} 0%, ${blue} ${val}%, var(--bg-elevated) ${val}%)`;
    };

    slider.addEventListener('input', updateSlider);
    updateSlider(); // Initialize
  });

  // ─── Upload Zone ───────────────────────────────────────────
  const uploadZone = document.getElementById('upload-zone');
  const btnUpload = document.getElementById('btn-upload-vod');
  const btnImportUrl = document.getElementById('btn-import-url');

  // Drag & Drop
  ['dragenter', 'dragover'].forEach(evt => {
    uploadZone.addEventListener(evt, (e) => {
      e.preventDefault();
      uploadZone.classList.add('drag-over');
    });
  });

  ['dragleave', 'drop'].forEach(evt => {
    uploadZone.addEventListener(evt, (e) => {
      e.preventDefault();
      uploadZone.classList.remove('drag-over');
    });
  });

  uploadZone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFileSelected(files[0]);
    }
  });

  // Click to upload
  uploadZone.addEventListener('click', openFileDialog);
  btnUpload.addEventListener('click', openFileDialog);

  async function openFileDialog() {
    if (window.kairo && window.kairo.openVodDialog) {
      const result = await window.kairo.openVodDialog();
      if (!result.canceled && result.filePaths.length > 0) {
        handleFileSelected({ name: result.filePaths[0].split('/').pop(), path: result.filePaths[0] });
      }
    } else {
      // Fallback for browser preview
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'video/*';
      input.onchange = () => {
        if (input.files.length > 0) {
          handleFileSelected(input.files[0]);
        }
      };
      input.click();
    }
  }

  function handleFileSelected(file) {
    const name = file.name || file;
    uploadZone.querySelector('h3').textContent = `📂 ${name}`;
    uploadZone.querySelector('p').textContent = 'VOD loaded — select a template to begin';
    uploadZone.style.borderColor = 'rgba(139, 92, 246, 0.5)';
    uploadZone.style.background = 'rgba(139, 92, 246, 0.04)';
  }

  // URL Import
  btnImportUrl.addEventListener('click', () => {
    const url = prompt('Paste Twitch or YouTube VOD URL:');
    if (url && url.trim()) {
      handleFileSelected({ name: url.trim() });
    }
  });

  // ─── Sidebar Navigation ────────────────────────────────────
  const navItems = document.querySelectorAll('.nav-item');
  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      navItems.forEach(n => n.classList.remove('active'));
      item.classList.add('active');

      const section = item.dataset.section;
      document.querySelector('.page-title').textContent =
        section.charAt(0).toUpperCase() + section.slice(1);
    });
  });

  // ─── Template Cards ────────────────────────────────────────
  const templateCards = document.querySelectorAll('.template-card');
  templateCards.forEach(card => {
    card.addEventListener('click', () => {
      // Remove active from all
      templateCards.forEach(c => c.style.borderColor = '');
      // Set active
      card.style.borderColor = 'rgba(139, 92, 246, 0.6)';

      const template = card.dataset.template;
      const name = card.querySelector('h4').textContent;
      console.log(`[KAIRO] Template selected: ${template} — "${name}"`);
    });
  });

  // ─── Timeline Playhead Animation ───────────────────────────
  const playhead = document.getElementById('playhead');
  let playheadPos = 90;
  let playheadDirection = 1;

  function animatePlayhead() {
    const container = document.querySelector('.timeline-container');
    if (!container) return;

    const maxLeft = container.offsetWidth - 20;

    playheadPos += playheadDirection * 0.5;
    if (playheadPos >= maxLeft) playheadDirection = -1;
    if (playheadPos <= 90) playheadDirection = 1;

    playhead.style.left = `${playheadPos}px`;
    requestAnimationFrame(animatePlayhead);
  }

  animatePlayhead();

  // ─── Keyboard Shortcuts ────────────────────────────────────
  document.addEventListener('keydown', (e) => {
    // Space: pause/resume playhead (mock)
    if (e.code === 'Space' && e.target === document.body) {
      e.preventDefault();
      playheadDirection = playheadDirection === 0 ? 1 : 0;
    }
  });

  // ─── Console Branding ──────────────────────────────────────
  console.log(
    '%cKAIRO%c v0.1.0 — AI Story-Driven Gaming Clips',
    'background: linear-gradient(135deg, #8b5cf6, #3b82f6); color: white; padding: 8px 16px; border-radius: 4px; font-weight: bold; font-size: 14px;',
    'color: #8888a0; padding: 8px; font-size: 12px;'
  );

});
