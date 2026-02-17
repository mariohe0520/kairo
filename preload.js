const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('kairo', {
  openVodDialog: () => ipcRenderer.invoke('open-vod-dialog'),
  platform: process.platform
});
