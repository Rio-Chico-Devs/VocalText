const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');

// Store configuration
let store;
async function getStore() {
  if (!store) {
    const { default: Store } = await import('electron-store');
    store = new Store({
      defaults: {
        theme: 'dark',
        lastVoice: null,
        outputDir: app.getPath('documents'),
        speed: 1.0,
        pitch: 1.0,
        volume: 1.0,
        windowBounds: { width: 1100, height: 720 }
      }
    });
  }
  return store;
}

let mainWindow;

async function createWindow() {
  const s = await getStore();
  const bounds = s.get('windowBounds');

  mainWindow = new BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    minWidth: 800,
    minHeight: 560,
    backgroundColor: '#0f1117',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    frame: process.platform !== 'darwin',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    },
    icon: path.join(__dirname, 'assets', 'icon.png'),
    show: false
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (process.argv.includes('--dev')) {
      mainWindow.webContents.openDevTools();
    }
  });

  mainWindow.on('resize', async () => {
    const [width, height] = mainWindow.getSize();
    const s = await getStore();
    s.set('windowBounds', { width, height });
  });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

// ── IPC: Settings ──────────────────────────────────────────────────────────

ipcMain.handle('settings:get', async (_, key) => {
  const s = await getStore();
  return s.get(key);
});

ipcMain.handle('settings:set', async (_, key, value) => {
  const s = await getStore();
  s.set(key, value);
});

// ── IPC: TTS ───────────────────────────────────────────────────────────────

ipcMain.handle('tts:generate', async (_, { text, voice, speed, pitch, volume }) => {
  const { TTSEngine } = require('./tts/engine');
  const engine = new TTSEngine();

  const outputPath = path.join(os.tmpdir(), `vocaltext_${Date.now()}.wav`);

  try {
    await engine.generate({ text, voice, speed, pitch, volume, outputPath });
    const buffer = fs.readFileSync(outputPath);
    return { success: true, audioData: buffer.toString('base64'), outputPath };
  } catch (err) {
    return { success: false, error: err.message };
  }
});

ipcMain.handle('tts:engines', async () => {
  const { TTSEngine } = require('./tts/engine');
  const engine = new TTSEngine();
  return engine.getAvailableEngines();
});

ipcMain.handle('tts:check-piper', async () => {
  const { TTSEngine } = require('./tts/engine');
  const engine = new TTSEngine();
  return engine.checkPiper();
});

// ── IPC: File system ────────────────────────────────────────────────────────

ipcMain.handle('fs:save-audio', async (_, { audioData, defaultName }) => {
  const s = await getStore();
  const { filePath } = await dialog.showSaveDialog(mainWindow, {
    title: 'Salva traccia audio',
    defaultPath: path.join(s.get('outputDir'), defaultName || 'vocaltext_output.wav'),
    filters: [
      { name: 'Audio WAV', extensions: ['wav'] },
      { name: 'Tutti i file', extensions: ['*'] }
    ]
  });

  if (!filePath) return { success: false, cancelled: true };

  const buffer = Buffer.from(audioData, 'base64');
  fs.writeFileSync(filePath, buffer);
  s.set('outputDir', path.dirname(filePath));
  return { success: true, filePath };
});

ipcMain.handle('fs:open-models-dir', async () => {
  const modelsDir = path.join(app.getPath('userData'), 'models');
  if (!fs.existsSync(modelsDir)) fs.mkdirSync(modelsDir, { recursive: true });
  shell.openPath(modelsDir);
});

ipcMain.handle('fs:get-models', async () => {
  const { TTSEngine } = require('./tts/engine');
  const engine = new TTSEngine();
  return engine.getInstalledModels();
});

// ── IPC: Window controls ────────────────────────────────────────────────────

ipcMain.handle('window:minimize', () => mainWindow.minimize());
ipcMain.handle('window:maximize', () => {
  if (mainWindow.isMaximized()) mainWindow.unmaximize();
  else mainWindow.maximize();
});
ipcMain.handle('window:close', () => mainWindow.close());
