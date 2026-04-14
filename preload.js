const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('vocaltext', {
  // Settings
  settings: {
    get: (key) => ipcRenderer.invoke('settings:get', key),
    set: (key, value) => ipcRenderer.invoke('settings:set', key, value)
  },

  // TTS
  tts: {
    generate: (params) => ipcRenderer.invoke('tts:generate', params),
    getEngines: () => ipcRenderer.invoke('tts:engines'),
    checkPiper: () => ipcRenderer.invoke('tts:check-piper')
  },

  // File system
  fs: {
    saveAudio: (params) => ipcRenderer.invoke('fs:save-audio', params),
    openModelsDir: () => ipcRenderer.invoke('fs:open-models-dir'),
    getModels: () => ipcRenderer.invoke('fs:get-models')
  },

  // Window
  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    close: () => ipcRenderer.invoke('window:close')
  },

  // Platform
  platform: process.platform
});
