const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('kairo', {
  // Existing
  openVodDialog: () => ipcRenderer.invoke('open-vod-dialog'),
  platform: process.platform,

  // Health check
  health: () => ipcRenderer.invoke('api-health'),

  // Pipeline API
  ingest: (source) => ipcRenderer.invoke('api-ingest', source),
  ingestStatus: (jobId) => ipcRenderer.invoke('api-ingest-status', jobId),
  analyze: (videoPath, options) => ipcRenderer.invoke('api-analyze', videoPath, options),
  generate: (videoPath, templateId, personaId) => ipcRenderer.invoke('api-generate', videoPath, templateId, personaId),
  render: (editScript) => ipcRenderer.invoke('api-render', editScript),
  renderStatus: (jobId) => ipcRenderer.invoke('api-render-status', jobId),

  // One-click autonomous pipeline
  runPipeline: (source, streamerId) => ipcRenderer.invoke('api-run-pipeline', source, streamerId),

  // Memory
  getMemory: (streamerId) => ipcRenderer.invoke('api-memory', streamerId),
  submitFeedback: (data) => ipcRenderer.invoke('api-feedback', data),

  // Templates & Personas
  getTemplates: () => ipcRenderer.invoke('api-templates'),
  getPersonas: () => ipcRenderer.invoke('api-personas'),

  // Progress events from main process
  onProgress: (callback) => {
    ipcRenderer.on('progress', (_event, data) => callback(data));
  },
});
