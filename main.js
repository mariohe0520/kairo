const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

let mainWindow;
let serverProcess = null;

const SERVER_PORT = 8420;
const SERVER_HOST = '127.0.0.1';
const API_BASE = `http://${SERVER_HOST}:${SERVER_PORT}`;

// ═══════ SERVER MANAGEMENT ═══════

function findPython() {
  // Try common Python paths in order of preference
  const candidates = ['python3', 'python'];
  for (const cmd of candidates) {
    try {
      const { execSync } = require('child_process');
      execSync(`${cmd} --version`, { stdio: 'ignore' });
      return cmd;
    } catch {
      continue;
    }
  }
  return 'python3'; // Fallback, let it fail with a clear error
}

function startServer() {
  return new Promise((resolve, reject) => {
    const pythonCmd = findPython();
    const serverScript = path.join(__dirname, 'server.py');

    console.log(`[Kairo] Starting FastAPI server: ${pythonCmd} ${serverScript}`);

    serverProcess = spawn(pythonCmd, ['-u', serverScript], {
      cwd: __dirname,
      env: {
        ...process.env,
        KAIRO_PORT: String(SERVER_PORT),
        KAIRO_HOST: SERVER_HOST,
        PYTHONUNBUFFERED: '1',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    serverProcess.stdout.on('data', (data) => {
      console.log(`[Server] ${data.toString().trim()}`);
    });

    serverProcess.stderr.on('data', (data) => {
      console.log(`[Server] ${data.toString().trim()}`);
    });

    serverProcess.on('error', (err) => {
      console.error(`[Kairo] Failed to start server: ${err.message}`);
      serverProcess = null;
      reject(err);
    });

    serverProcess.on('close', (code) => {
      console.log(`[Kairo] Server process exited with code ${code}`);
      serverProcess = null;
    });

    // Poll for health until server is ready (up to 30 seconds)
    let attempts = 0;
    const maxAttempts = 60;
    const checkInterval = setInterval(() => {
      attempts++;
      checkServerHealth()
        .then(() => {
          clearInterval(checkInterval);
          console.log(`[Kairo] Server is ready after ${attempts} attempts`);
          resolve();
        })
        .catch(() => {
          if (attempts >= maxAttempts) {
            clearInterval(checkInterval);
            console.error('[Kairo] Server failed to start within timeout');
            reject(new Error('Server startup timeout'));
          }
        });
    }, 500);
  });
}

function stopServer() {
  if (serverProcess) {
    console.log('[Kairo] Stopping server...');
    serverProcess.kill('SIGTERM');

    // Force kill after 3 seconds if still running
    setTimeout(() => {
      if (serverProcess) {
        try {
          serverProcess.kill('SIGKILL');
        } catch {
          // Already dead
        }
        serverProcess = null;
      }
    }, 3000);
  }
}

function checkServerHealth() {
  return new Promise((resolve, reject) => {
    const req = http.get(`${API_BASE}/api/health`, { timeout: 2000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          resolve(json);
        } catch {
          reject(new Error('Invalid health response'));
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Timeout')); });
  });
}

// ═══════ API CALL HELPERS ═══════

function apiGet(endpoint) {
  return new Promise((resolve, reject) => {
    const url = `${API_BASE}${endpoint}`;
    const req = http.get(url, { timeout: 30000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (res.statusCode >= 400) {
            reject({ status: res.statusCode, ...json });
          } else {
            resolve(json);
          }
        } catch {
          reject(new Error(`Invalid JSON response from ${endpoint}`));
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });
  });
}

function apiPost(endpoint, formData = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(`${API_BASE}${endpoint}`);

    // Encode as application/x-www-form-urlencoded
    const body = Object.entries(formData)
      .filter(([, v]) => v !== undefined && v !== null)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&');

    const options = {
      method: 'POST',
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      timeout: 120000,
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Content-Length': Buffer.byteLength(body),
      },
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (res.statusCode >= 400) {
            reject({ status: res.statusCode, ...json });
          } else {
            resolve(json);
          }
        } catch {
          reject(new Error(`Invalid JSON response from ${endpoint}`));
        }
      });
    });

    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });
    req.write(body);
    req.end();
  });
}

// Poll a job until it completes, sending progress events to renderer
function pollJob(jobId, endpoint, intervalMs = 1000) {
  return new Promise((resolve, reject) => {
    const poll = setInterval(async () => {
      try {
        const status = await apiGet(`${endpoint}/${jobId}`);

        // Send progress to renderer
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('progress', {
            job_id: jobId,
            status: status.status,
            progress: status.progress,
            message: status.message,
          });
        }

        if (status.status === 'completed') {
          clearInterval(poll);
          resolve(status);
        } else if (status.status === 'failed') {
          clearInterval(poll);
          reject(new Error(status.error || 'Job failed'));
        }
      } catch (err) {
        clearInterval(poll);
        reject(err);
      }
    }, intervalMs);
  });
}

// ═══════ WINDOW CREATION ═══════

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 16 },
    backgroundColor: '#0a0a0f',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ═══════ APP LIFECYCLE ═══════

app.whenReady().then(async () => {
  createWindow();

  // Start the Python backend server
  try {
    await startServer();
    console.log('[Kairo] Backend server started successfully');
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('progress', {
        type: 'server-status',
        status: 'connected',
        message: 'Backend server ready',
      });
    }
  } catch (err) {
    console.error('[Kairo] Failed to start backend server:', err.message);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('progress', {
        type: 'server-status',
        status: 'error',
        message: `Server startup failed: ${err.message}`,
      });
    }
  }
});

app.on('window-all-closed', () => {
  stopServer();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  stopServer();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// ═══════ IPC: FILE DIALOG ═══════

ipcMain.handle('open-vod-dialog', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Select Gaming VOD',
    filters: [
      { name: 'Video Files', extensions: ['mp4', 'mov', 'mkv', 'webm', 'avi'] }
    ],
    properties: ['openFile']
  });
  return result;
});

// ═══════ IPC: HEALTH CHECK ═══════

ipcMain.handle('api-health', async () => {
  try {
    return await checkServerHealth();
  } catch (err) {
    return { status: 'error', message: err.message };
  }
});

// ═══════ IPC: INGEST ═══════

ipcMain.handle('api-ingest', async (_event, source) => {
  try {
    const isUrl = source.startsWith('http://') || source.startsWith('https://');
    const formData = isUrl ? { url: source } : { file_path: source };
    const result = await apiPost('/api/ingest', formData);

    // Start polling for status in background
    if (result.job_id) {
      pollJob(result.job_id, '/api/ingest').catch((err) => {
        console.error('[Kairo] Ingest poll error:', err.message);
      });
    }

    return result;
  } catch (err) {
    return { error: err.message || String(err) };
  }
});

ipcMain.handle('api-ingest-status', async (_event, jobId) => {
  try {
    return await apiGet(`/api/ingest/${jobId}`);
  } catch (err) {
    return { error: err.message || String(err) };
  }
});

// ═══════ IPC: ANALYZE ═══════

ipcMain.handle('api-analyze', async (_event, videoPath, options = {}) => {
  try {
    const formData = {
      video_path: videoPath,
      template_id: options.templateId || undefined,
      persona_id: options.personaId || undefined,
      streamer_id: options.streamerId || undefined,
    };
    const result = await apiPost('/api/analyze', formData);

    if (result.job_id) {
      pollJob(result.job_id, '/api/jobs').catch((err) => {
        console.error('[Kairo] Analyze poll error:', err.message);
      });
    }

    return result;
  } catch (err) {
    return { error: err.message || String(err) };
  }
});

// ═══════ IPC: GENERATE EDIT SCRIPT ═══════

ipcMain.handle('api-generate', async (_event, videoPath, templateId, personaId) => {
  try {
    const formData = {
      video_path: videoPath,
      template_id: templateId || 'chill-highlights',
      streamer_id: personaId || undefined,
    };
    return await apiPost('/api/generate', formData);
  } catch (err) {
    return { error: err.message || String(err) };
  }
});

// ═══════ IPC: RENDER ═══════

ipcMain.handle('api-render', async (_event, editScript) => {
  try {
    const formData = {
      edit_script_json: typeof editScript === 'string' ? editScript : JSON.stringify(editScript),
    };
    const result = await apiPost('/api/render', formData);

    if (result.job_id) {
      pollJob(result.job_id, '/api/render', 500).catch((err) => {
        console.error('[Kairo] Render poll error:', err.message);
      });
    }

    return result;
  } catch (err) {
    return { error: err.message || String(err) };
  }
});

ipcMain.handle('api-render-status', async (_event, jobId) => {
  try {
    return await apiGet(`/api/render/${jobId}`);
  } catch (err) {
    return { error: err.message || String(err) };
  }
});

// ═══════ IPC: ONE-CLICK PIPELINE ═══════

ipcMain.handle('api-run-pipeline', async (_event, source, streamerId) => {
  try {
    // Step 1: Ingest
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('progress', {
        type: 'pipeline',
        stage: 'ingest',
        progress: 0,
        message: 'Starting download and ingest...',
      });
    }

    const isUrl = source.startsWith('http://') || source.startsWith('https://');
    const ingestResult = await apiPost('/api/ingest', isUrl ? { url: source } : { file_path: source });

    if (ingestResult.error) {
      return { error: `Ingest failed: ${ingestResult.error}` };
    }

    // Poll ingest to completion
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('progress', {
        type: 'pipeline',
        stage: 'ingest',
        progress: 0.1,
        message: 'Downloading and processing video...',
      });
    }

    const ingestStatus = await pollJob(ingestResult.job_id, '/api/ingest');
    const videoPath = ingestStatus.result?.video_path;

    if (!videoPath) {
      return { error: 'Ingest completed but no video path returned' };
    }

    // Step 2: Analyze
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('progress', {
        type: 'pipeline',
        stage: 'analyze',
        progress: 0.3,
        message: 'Analyzing gameplay for highlights...',
      });
    }

    const analyzeResult = await apiPost('/api/analyze', {
      video_path: videoPath,
      streamer_id: streamerId || undefined,
    });

    if (analyzeResult.error) {
      return { error: `Analysis failed: ${analyzeResult.error}` };
    }

    const analyzeStatus = await pollJob(analyzeResult.job_id, '/api/jobs');

    // Step 3: Generate edit scripts for multiple templates
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('progress', {
        type: 'pipeline',
        stage: 'generate',
        progress: 0.6,
        message: 'Generating clip scripts...',
      });
    }

    // Generate 3 clip candidates with different templates
    const templateIds = ['clutch-master', 'comeback-king', 'hype-montage'];
    const clipCandidates = [];

    for (let i = 0; i < templateIds.length; i++) {
      try {
        const genResult = await apiPost('/api/generate', {
          video_path: videoPath,
          template_id: templateIds[i],
          streamer_id: streamerId || undefined,
        });

        if (genResult.edit_script) {
          clipCandidates.push({
            id: `clip_${i + 1}`,
            template_id: templateIds[i],
            edit_script: genResult.edit_script,
            quality_score: Math.round(70 + Math.random() * 25), // Will be replaced by real scoring
          });
        }

        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('progress', {
            type: 'pipeline',
            stage: 'generate',
            progress: 0.6 + ((i + 1) / templateIds.length) * 0.2,
            message: `Generated clip ${i + 1} of ${templateIds.length}...`,
          });
        }
      } catch (err) {
        console.error(`[Kairo] Failed to generate clip with template ${templateIds[i]}:`, err.message);
      }
    }

    // Step 4: Done
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('progress', {
        type: 'pipeline',
        stage: 'complete',
        progress: 1.0,
        message: 'Pipeline complete!',
      });
    }

    return {
      status: 'complete',
      video_path: videoPath,
      ingest: ingestStatus.result,
      analysis: analyzeStatus.result,
      clips: clipCandidates,
    };
  } catch (err) {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('progress', {
        type: 'pipeline',
        stage: 'error',
        progress: 0,
        message: `Pipeline error: ${err.message}`,
      });
    }
    return { error: err.message || String(err) };
  }
});

// ═══════ IPC: MEMORY ═══════

ipcMain.handle('api-memory', async (_event, streamerId) => {
  try {
    return await apiGet(`/api/memory/${encodeURIComponent(streamerId)}`);
  } catch (err) {
    return { error: err.message || String(err) };
  }
});

// ═══════ IPC: FEEDBACK ═══════

ipcMain.handle('api-feedback', async (_event, data) => {
  try {
    return await apiPost('/api/feedback', {
      streamer_id: data.streamerId || 'default',
      clip_id: data.clipId || `clip_${Date.now()}`,
      rating: data.rating || 3,
      action: data.action || 'approved',
      notes: data.notes || '',
      template_id: data.templateId || '',
      enhancements_json: data.enhancements ? JSON.stringify(data.enhancements) : undefined,
    });
  } catch (err) {
    return { error: err.message || String(err) };
  }
});

// ═══════ IPC: TEMPLATES & PERSONAS ═══════

ipcMain.handle('api-templates', async () => {
  try {
    return await apiGet('/api/templates');
  } catch (err) {
    return { error: err.message || String(err) };
  }
});

ipcMain.handle('api-personas', async () => {
  try {
    return await apiGet('/api/personas');
  } catch (err) {
    return { error: err.message || String(err) };
  }
});
