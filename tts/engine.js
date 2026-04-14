/**
 * VocalText TTS Engine
 *
 * Priority chain:
 *  1. Piper TTS  – neural, offline, high quality  (requires piper binary + .onnx model)
 *  2. eSpeak-NG  – lightweight, offline, robotic  (usually pre-installed on Linux)
 *  3. macOS say  – offline, system voices
 *  4. Windows SAPI via PowerShell
 */

const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { app } = require('electron');

const PIPER_VOICES_CATALOG_URL =
  'https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json';

class TTSEngine {
  constructor() {
    this.platform = os.platform();
    this.appDataDir = app ? app.getPath('userData') : path.join(os.homedir(), '.vocaltext');
    this.modelsDir = path.join(this.appDataDir, 'models');
    this.binDir = this._getBinDir();

    if (!fs.existsSync(this.modelsDir)) {
      fs.mkdirSync(this.modelsDir, { recursive: true });
    }
  }

  _getBinDir() {
    // During dev: look in project root bin/<platform>
    // After packaging: look in process.resourcesPath/bin
    const devBin = path.join(__dirname, '..', 'bin', this.platform);
    if (fs.existsSync(devBin)) return devBin;
    if (process.resourcesPath) {
      const prodBin = path.join(process.resourcesPath, 'bin');
      if (fs.existsSync(prodBin)) return prodBin;
    }
    return null;
  }

  // ── Engine detection ──────────────────────────────────────────────────────

  checkPiper() {
    const piperBin = this._getPiperBin();
    return {
      available: !!piperBin,
      path: piperBin,
      installedModels: this.getInstalledModels()
    };
  }

  _getPiperBin() {
    // 1. Bundled binary
    if (this.binDir) {
      const binName = this.platform === 'win32' ? 'piper.exe' : 'piper';
      const bundled = path.join(this.binDir, binName);
      if (fs.existsSync(bundled)) return bundled;
    }

    // 2. System-wide
    try {
      const result = execSync('which piper 2>/dev/null || where piper 2>nul', {
        stdio: ['pipe', 'pipe', 'ignore']
      }).toString().trim();
      if (result) return result;
    } catch {}

    return null;
  }

  _getEspeakBin() {
    try {
      execSync('espeak-ng --version', { stdio: 'ignore' });
      return 'espeak-ng';
    } catch {}
    try {
      execSync('espeak --version', { stdio: 'ignore' });
      return 'espeak';
    } catch {}
    return null;
  }

  getAvailableEngines() {
    const engines = [];

    const piper = this._getPiperBin();
    if (piper) {
      engines.push({ id: 'piper', name: 'Piper TTS (neural)', quality: 'high', path: piper });
    }

    const espeak = this._getEspeakBin();
    if (espeak) {
      engines.push({ id: 'espeak', name: 'eSpeak-NG', quality: 'low', path: espeak });
    }

    if (this.platform === 'darwin') {
      engines.push({ id: 'say', name: 'macOS Say', quality: 'medium', path: 'say' });
    }

    if (this.platform === 'win32') {
      engines.push({ id: 'sapi', name: 'Windows SAPI', quality: 'medium', path: 'powershell' });
    }

    return engines;
  }

  // ── Installed models ──────────────────────────────────────────────────────

  getInstalledModels() {
    if (!fs.existsSync(this.modelsDir)) return [];

    const models = [];
    const entries = fs.readdirSync(this.modelsDir, { withFileTypes: true });

    for (const entry of entries) {
      if (entry.isDirectory()) {
        const modelDir = path.join(this.modelsDir, entry.name);
        const onnxFiles = fs.readdirSync(modelDir).filter(f => f.endsWith('.onnx'));
        const configFiles = fs.readdirSync(modelDir).filter(f => f.endsWith('.onnx.json'));

        for (const onnx of onnxFiles) {
          const config = onnx + '.json';
          if (configFiles.includes(config)) {
            models.push({
              id: entry.name + '/' + onnx.replace('.onnx', ''),
              name: this._formatModelName(entry.name),
              onnxPath: path.join(modelDir, onnx),
              configPath: path.join(modelDir, config),
              dir: entry.name
            });
          }
        }
      }
    }

    return models;
  }

  _formatModelName(dirName) {
    // e.g. "en_US-lessac-medium" → "English (US) – Lessac [Medium]"
    const parts = dirName.split('-');
    if (parts.length >= 3) {
      const [lang, speaker, quality] = parts;
      const [langCode, region] = lang.split('_');
      const langNames = {
        en: 'English', it: 'Italian', de: 'German', fr: 'French',
        es: 'Spanish', pt: 'Portuguese', nl: 'Dutch', ru: 'Russian',
        zh: 'Chinese', ja: 'Japanese', ko: 'Korean', pl: 'Polish'
      };
      const langLabel = langNames[langCode] || langCode.toUpperCase();
      const regionLabel = region ? ` (${region})` : '';
      const speakerLabel = speaker.charAt(0).toUpperCase() + speaker.slice(1);
      const qualityLabel = quality ? ` [${quality}]` : '';
      return `${langLabel}${regionLabel} – ${speakerLabel}${qualityLabel}`;
    }
    return dirName;
  }

  // ── Audio generation ──────────────────────────────────────────────────────

  async generate({ text, voice, speed = 1.0, pitch = 1.0, volume = 1.0, outputPath }) {
    const engines = this.getAvailableEngines();

    if (!text || !text.trim()) {
      throw new Error('Il testo non può essere vuoto');
    }

    // Try Piper first if a model path is provided
    if (voice && voice.onnxPath && engines.find(e => e.id === 'piper')) {
      return this._generatePiper({ text, voice, speed, outputPath });
    }

    // Fallback chain
    if (engines.find(e => e.id === 'piper')) {
      const models = this.getInstalledModels();
      if (models.length > 0) {
        const model = models.find(m => m.id === voice?.id) || models[0];
        return this._generatePiper({ text, voice: model, speed, outputPath });
      }
    }

    if (engines.find(e => e.id === 'espeak')) {
      return this._generateEspeak({ text, voice, speed, pitch, outputPath });
    }

    if (engines.find(e => e.id === 'say')) {
      return this._generateSay({ text, voice, speed, outputPath });
    }

    if (engines.find(e => e.id === 'sapi')) {
      return this._generateSAPI({ text, voice, speed, outputPath });
    }

    throw new Error('Nessun motore TTS disponibile. Installa eSpeak-NG o scarica un modello Piper.');
  }

  // ── Piper TTS ─────────────────────────────────────────────────────────────

  _generatePiper({ text, voice, speed, outputPath }) {
    return new Promise((resolve, reject) => {
      const piperBin = this._getPiperBin();
      if (!piperBin) return reject(new Error('Piper non trovato'));

      const onnxPath = voice.onnxPath;
      const configPath = voice.configPath;

      if (!fs.existsSync(onnxPath)) {
        return reject(new Error(`Modello non trovato: ${onnxPath}`));
      }

      const args = [
        '--model', onnxPath,
        '--config', configPath,
        '--output_file', outputPath,
        '--length_scale', String(1.0 / speed)   // length_scale is inverse of speed
      ];

      const proc = spawn(piperBin, args, { stdio: ['pipe', 'pipe', 'pipe'] });

      let stderr = '';
      proc.stderr.on('data', d => { stderr += d.toString(); });

      proc.stdin.write(text);
      proc.stdin.end();

      proc.on('close', (code) => {
        if (code === 0 && fs.existsSync(outputPath)) {
          resolve(outputPath);
        } else {
          reject(new Error(`Piper fallito (code ${code}): ${stderr}`));
        }
      });

      proc.on('error', reject);
    });
  }

  // ── eSpeak-NG ─────────────────────────────────────────────────────────────

  _generateEspeak({ text, voice, speed, pitch, outputPath }) {
    return new Promise((resolve, reject) => {
      const bin = this._getEspeakBin();
      if (!bin) return reject(new Error('eSpeak-NG non trovato'));

      const lang = voice?.lang || 'it';
      const speedWpm = Math.round(175 * speed);
      const pitchVal = Math.round(50 * pitch);

      const args = [
        '-v', lang,
        '-s', String(speedWpm),
        '-p', String(pitchVal),
        '-w', outputPath,
        text
      ];

      const proc = spawn(bin, args);
      let stderr = '';
      proc.stderr.on('data', d => { stderr += d.toString(); });

      proc.on('close', (code) => {
        if (code === 0 && fs.existsSync(outputPath)) {
          resolve(outputPath);
        } else {
          reject(new Error(`eSpeak fallito (code ${code}): ${stderr}`));
        }
      });

      proc.on('error', reject);
    });
  }

  // ── macOS say ─────────────────────────────────────────────────────────────

  _generateSay({ text, voice, speed, outputPath }) {
    return new Promise((resolve, reject) => {
      const aiffPath = outputPath.replace('.wav', '.aiff');
      const args = ['-o', aiffPath];
      if (voice?.systemName) args.push('-v', voice.systemName);
      if (speed !== 1.0) args.push('-r', String(Math.round(200 * speed)));
      args.push('--', text);

      const proc = spawn('say', args);
      let stderr = '';
      proc.stderr.on('data', d => { stderr += d.toString(); });

      proc.on('close', (code) => {
        if (code === 0 && fs.existsSync(aiffPath)) {
          // Convert AIFF → WAV using afconvert
          const conv = spawn('afconvert', ['-f', 'WAVE', '-d', 'LEI16', aiffPath, outputPath]);
          conv.on('close', (c) => {
            fs.unlinkSync(aiffPath);
            if (c === 0) resolve(outputPath);
            else reject(new Error('Conversione AIFF→WAV fallita'));
          });
          conv.on('error', () => {
            // If afconvert not available, return aiff renamed
            fs.renameSync(aiffPath, outputPath);
            resolve(outputPath);
          });
        } else {
          reject(new Error(`say fallito (code ${code}): ${stderr}`));
        }
      });

      proc.on('error', reject);
    });
  }

  // ── Windows SAPI ──────────────────────────────────────────────────────────

  _generateSAPI({ text, voice, speed, outputPath }) {
    return new Promise((resolve, reject) => {
      const rate = Math.round((speed - 1) * 5); // SAPI rate: -10 to +10
      const voiceName = voice?.systemName || '';

      const psScript = `
        Add-Type -AssemblyName System.Speech
        $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
        $synth.Rate = ${rate}
        ${voiceName ? `$synth.SelectVoice('${voiceName.replace(/'/g, "''")}')` : ''}
        $synth.SetOutputToWaveFile('${outputPath.replace(/\\/g, '\\\\')}')
        $synth.Speak('${text.replace(/'/g, "''")}')
        $synth.Dispose()
      `.trim();

      const proc = spawn('powershell', ['-Command', psScript]);
      let stderr = '';
      proc.stderr.on('data', d => { stderr += d.toString(); });

      proc.on('close', (code) => {
        if (code === 0 && fs.existsSync(outputPath)) {
          resolve(outputPath);
        } else {
          reject(new Error(`SAPI fallito (code ${code}): ${stderr}`));
        }
      });

      proc.on('error', reject);
    });
  }
}

module.exports = { TTSEngine };
