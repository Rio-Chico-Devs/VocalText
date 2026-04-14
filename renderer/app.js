/* ═══════════════════════════════════════════════════════════
   VocalText – Renderer process
   ═══════════════════════════════════════════════════════════ */

'use strict';

const api = window.vocaltext;

// ── State ─────────────────────────────────────────────────────────────────

const state = {
  theme: 'dark',
  selectedVoice: null,       // { id, name, onnxPath?, configPath?, lang?, engine }
  speed: 1.0,
  pitch: 1.0,
  volume: 1.0,
  audioBlob: null,
  audioUrl: null,
  audioDuration: 0,
  isGenerating: false,
  engines: [],
  history: []                // [{ text, voiceName, audioData, timestamp }]
};

// ── DOM refs ──────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const els = {
  body:         document.body,
  textInput:    $('text-input'),
  charCount:    $('char-count'),
  wordCount:    $('word-count'),
  btnGenerate:  $('btn-generate'),
  btnLabel:     $('btn-generate-label'),
  spinner:      $('spinner'),
  audioPlayer:  $('audio-player'),
  audioEl:      $('audio-element'),
  btnPlayPause: $('btn-play-pause'),
  iconPlay:     $('icon-play'),
  iconPause:    $('icon-pause'),
  seekBar:      $('seek-bar'),
  timeCurrent:  $('time-current'),
  timeTotal:    $('time-total'),
  durationBadge:$('duration-badge'),
  playhead:     $('playhead'),
  waveformCanvas:$('waveform'),
  btnRestart:   $('btn-restart'),
  btnExportWav: $('btn-export-wav'),
  errorBox:     $('error-box'),
  errorText:    $('error-text'),
  voiceList:    $('voice-list'),
  engineStatus: $('engine-status'),
  statusDot:    $('status-dot'),
  statusText:   $('status-text'),
  piperHint:    $('piper-hint'),
  btnOpenModels:$('btn-open-models'),
  btnTheme:     $('btn-theme'),
  iconSun:      $('icon-sun'),
  iconMoon:     $('icon-moon'),
  btnClear:     $('btn-clear'),
  btnPaste:     $('btn-paste'),
  historySection:$('history-section'),
  historyList:  $('history-list'),
  modalOverlay: $('modal-overlay'),
  modalClose:   $('modal-close'),
  modalVoiceList:$('modal-voice-list'),
  modalOpenFolder:$('modal-open-folder'),
  titlebar:     $('titlebar'),
  winControls:  $('win-controls'),
  btnMinimize:  $('btn-minimize'),
  btnMaximize:  $('btn-maximize'),
  btnClose:     $('btn-close'),
  ctrlSpeed:    $('ctrl-speed'),
  ctrlPitch:    $('ctrl-pitch'),
  ctrlVolume:   $('ctrl-volume'),
  valSpeed:     $('val-speed'),
  valPitch:     $('val-pitch'),
  valVolume:    $('val-volume')
};

// ── Init ──────────────────────────────────────────────────────────────────

async function init() {
  // Platform
  if (api.platform === 'darwin') {
    els.body.dataset.platform = 'darwin';
    els.titlebar.style.display = 'none';
    document.querySelector('.layout').style.height = '100vh';
  }

  // Load saved settings
  const [theme, speed, pitch, volume, lastVoice] = await Promise.all([
    api.settings.get('theme'),
    api.settings.get('speed'),
    api.settings.get('pitch'),
    api.settings.get('volume'),
    api.settings.get('lastVoice')
  ]);

  applyTheme(theme || 'dark');
  setSlider('speed', speed ?? 1.0);
  setSlider('pitch', pitch ?? 1.0);
  setSlider('volume', volume ?? 1.0);

  // Detect engines & load voices
  await detectEngines();
  await loadVoices(lastVoice);

  // Event listeners
  bindEvents();
}

// ── Theme ─────────────────────────────────────────────────────────────────

function applyTheme(theme) {
  state.theme = theme;
  els.body.dataset.theme = theme;
  els.iconSun.style.display  = theme === 'dark'  ? 'block' : 'none';
  els.iconMoon.style.display = theme === 'light' ? 'block' : 'none';
}

function toggleTheme() {
  const next = state.theme === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  api.settings.set('theme', next);
}

// ── Engine detection ──────────────────────────────────────────────────────

async function detectEngines() {
  try {
    const engines = await api.tts.getEngines();
    state.engines = engines;

    if (engines.length === 0) {
      setStatus('error', 'Nessun motore TTS trovato');
      return;
    }

    const best = engines[0];
    if (best.id === 'piper') {
      setStatus('ok', `Piper TTS · neurale`);
    } else if (best.id === 'espeak') {
      setStatus('warn', `eSpeak-NG · qualità base`);
    } else {
      setStatus('ok', `${best.name}`);
    }
  } catch (e) {
    setStatus('error', 'Errore rilevamento motore');
  }
}

function setStatus(type, text) {
  els.statusDot.className = `status-dot ${type}`;
  els.statusText.textContent = text;
}

// ── Voice loading ─────────────────────────────────────────────────────────

async function loadVoices(savedVoiceId) {
  els.voiceList.innerHTML = '';

  // Piper installed models
  const installedModels = await api.fs.getModels();

  // eSpeak voices
  const hasEspeak = state.engines.find(e => e.id === 'espeak');

  // macOS Say voices
  const hasSay = state.engines.find(e => e.id === 'say');

  const allVoices = [];

  if (installedModels.length > 0) {
    const piperGroup = makeGroupLabel('Piper · Neurale');
    els.voiceList.appendChild(piperGroup);

    for (const model of installedModels) {
      const voice = {
        id: model.id,
        name: model.name,
        onnxPath: model.onnxPath,
        configPath: model.configPath,
        engine: 'piper',
        quality: 'high',
        lang: model.dir.split('-')[0],
        gender: 'neutral'
      };
      allVoices.push(voice);
      els.voiceList.appendChild(makeVoiceItem(voice));
    }
  } else {
    els.piperHint.style.display = 'flex';
  }

  if (hasEspeak) {
    const espeakGroup = makeGroupLabel('eSpeak-NG · Base');
    els.voiceList.appendChild(espeakGroup);

    const espeakVoices = [
      { id: 'espeak-it', name: 'Italiano', lang: 'it', gender: 'neutral', engine: 'espeak', quality: 'low' },
      { id: 'espeak-en', name: 'English',  lang: 'en', gender: 'neutral', engine: 'espeak', quality: 'low' },
      { id: 'espeak-de', name: 'Deutsch',  lang: 'de', gender: 'neutral', engine: 'espeak', quality: 'low' },
      { id: 'espeak-fr', name: 'Français', lang: 'fr', gender: 'neutral', engine: 'espeak', quality: 'low' },
      { id: 'espeak-es', name: 'Español',  lang: 'es', gender: 'neutral', engine: 'espeak', quality: 'low' }
    ];
    for (const v of espeakVoices) {
      allVoices.push(v);
      els.voiceList.appendChild(makeVoiceItem(v));
    }
  }

  if (hasSay) {
    const sayGroup = makeGroupLabel('macOS · Sistema');
    els.voiceList.appendChild(sayGroup);
    const sayVoices = [
      { id: 'macos-alice',    name: 'Alice',    systemName: 'Alice',    lang: 'it', gender: 'female', engine: 'say', quality: 'medium' },
      { id: 'macos-luca',     name: 'Luca',     systemName: 'Luca',     lang: 'it', gender: 'male',   engine: 'say', quality: 'medium' },
      { id: 'macos-samantha', name: 'Samantha', systemName: 'Samantha', lang: 'en', gender: 'female', engine: 'say', quality: 'medium' }
    ];
    for (const v of sayVoices) {
      allVoices.push(v);
      els.voiceList.appendChild(makeVoiceItem(v));
    }
  }

  // Select first voice or saved
  if (allVoices.length > 0) {
    const target = allVoices.find(v => v.id === savedVoiceId) || allVoices[0];
    selectVoice(target);
  }
}

function makeGroupLabel(text) {
  const el = document.createElement('div');
  el.className = 'voice-group-label';
  el.textContent = text;
  return el;
}

function makeVoiceItem(voice) {
  const item = document.createElement('div');
  item.className = 'voice-item';
  item.dataset.id = voice.id;

  const initial = voice.name.charAt(0).toUpperCase();
  item.innerHTML = `
    <div class="voice-avatar ${voice.gender}">${initial}</div>
    <div class="voice-info">
      <div class="voice-name">${voice.name}</div>
      <div class="voice-meta">
        <span>${langLabel(voice.lang)}</span>
        <span class="quality-badge ${voice.quality}">${voice.quality}</span>
      </div>
    </div>
  `;

  item.addEventListener('click', () => selectVoice(voice));
  return item;
}

function langLabel(lang) {
  const map = { it: '🇮🇹 IT', en: '🇺🇸 EN', 'en-gb': '🇬🇧 EN',
                de: '🇩🇪 DE', fr: '🇫🇷 FR', es: '🇪🇸 ES', pt: '🇵🇹 PT' };
  return map[lang] || lang?.toUpperCase() || '?';
}

function selectVoice(voice) {
  state.selectedVoice = voice;
  api.settings.set('lastVoice', voice.id);

  // Update UI
  document.querySelectorAll('.voice-item').forEach(el => {
    el.classList.toggle('selected', el.dataset.id === voice.id);
  });
}

// ── Text input ────────────────────────────────────────────────────────────

function updateCounts() {
  const text = els.textInput.value;
  const chars = text.length;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  els.charCount.textContent = chars;
  els.wordCount.textContent = words;

  // Color when near limit
  els.charCount.style.color = chars > 4500 ? 'var(--danger)' :
                               chars > 4000 ? '#f4a261' : 'var(--text-2)';
}

// ── Sliders ───────────────────────────────────────────────────────────────

function setSlider(name, value) {
  state[name] = value;
  const el = els[`ctrl${name.charAt(0).toUpperCase() + name.slice(1)}`];
  if (el) el.value = value;
  updateSliderLabel(name, value);
}

function updateSliderLabel(name, value) {
  const el = els[`val${name.charAt(0).toUpperCase() + name.slice(1)}`];
  if (!el) return;
  if (name === 'volume') {
    el.textContent = `${Math.round(value * 100)}%`;
  } else {
    el.textContent = `${parseFloat(value).toFixed(2)}×`;
  }
}

// ── Generate audio ────────────────────────────────────────────────────────

async function generateAudio() {
  const text = els.textInput.value.trim();
  if (!text) {
    showError('Scrivi del testo prima di generare!');
    els.textInput.focus();
    return;
  }

  if (!state.selectedVoice) {
    showError('Seleziona una voce dalla lista a sinistra.');
    return;
  }

  setGenerating(true);
  hideError();

  try {
    const result = await api.tts.generate({
      text,
      voice: state.selectedVoice,
      speed: state.speed,
      pitch: state.pitch,
      volume: state.volume
    });

    if (!result.success) {
      throw new Error(result.error || 'Errore sconosciuto');
    }

    // Load audio
    const audioBlob = base64ToBlob(result.audioData, 'audio/wav');
    state.audioBlob = audioBlob;
    state.audioUrl = URL.createObjectURL(audioBlob);
    state.lastAudioData = result.audioData;

    els.audioEl.src = state.audioUrl;
    await loadAudioMetadata();

    drawWaveform(result.audioData);
    showPlayer();

    // Add to history
    addToHistory({ text, voice: state.selectedVoice, audioData: result.audioData });

  } catch (err) {
    showError(err.message || 'Errore durante la generazione audio');
  } finally {
    setGenerating(false);
  }
}

function setGenerating(v) {
  state.isGenerating = v;
  els.btnGenerate.disabled = v;
  els.btnLabel.textContent = v ? 'Generazione in corso…' : 'Genera Audio';
  els.spinner.style.display = v ? 'flex' : 'none';
  document.querySelector('.btn-generate-icon').style.display = v ? 'none' : 'flex';
}

// ── Audio player ──────────────────────────────────────────────────────────

function loadAudioMetadata() {
  return new Promise((resolve) => {
    els.audioEl.onloadedmetadata = () => {
      state.audioDuration = els.audioEl.duration;
      els.timeTotal.textContent = formatTime(state.audioDuration);
      els.durationBadge.textContent = `${formatTime(state.audioDuration)} · WAV`;
      resolve();
    };
    if (els.audioEl.readyState >= 1) {
      state.audioDuration = els.audioEl.duration;
      els.timeTotal.textContent = formatTime(state.audioDuration);
      els.durationBadge.textContent = `${formatTime(state.audioDuration)} · WAV`;
      resolve();
    }
  });
}

function showPlayer() {
  els.audioPlayer.style.display = 'flex';
  els.audioPlayer.style.flexDirection = 'column';
  els.audioPlayer.style.gap = '12px';
  resetPlayhead();
}

function resetPlayhead() {
  els.seekBar.value = 0;
  els.timeCurrent.textContent = '0:00';
  els.playhead.style.left = '0px';
  els.iconPlay.style.display = 'block';
  els.iconPause.style.display = 'none';
}

function togglePlayPause() {
  if (els.audioEl.paused) {
    els.audioEl.play();
    els.iconPlay.style.display = 'none';
    els.iconPause.style.display = 'block';
  } else {
    els.audioEl.pause();
    els.iconPlay.style.display = 'block';
    els.iconPause.style.display = 'none';
  }
}

function onAudioTimeUpdate() {
  const pct = (els.audioEl.currentTime / els.audioEl.duration) * 100 || 0;
  els.seekBar.value = pct;
  els.timeCurrent.textContent = formatTime(els.audioEl.currentTime);

  // Move playhead
  const canvas = els.waveformCanvas;
  const x = (pct / 100) * canvas.offsetWidth;
  els.playhead.style.left = `${x}px`;
}

function onAudioEnded() {
  els.iconPlay.style.display = 'block';
  els.iconPause.style.display = 'none';
}

function onSeekChange() {
  const pct = parseFloat(els.seekBar.value);
  els.audioEl.currentTime = (pct / 100) * els.audioEl.duration;
}

// ── Waveform drawing ──────────────────────────────────────────────────────

function drawWaveform(base64Data) {
  const canvas = els.waveformCanvas;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  canvas.width  = canvas.offsetWidth  * dpr;
  canvas.height = canvas.offsetHeight * dpr;
  ctx.scale(dpr, dpr);

  const W = canvas.offsetWidth;
  const H = canvas.offsetHeight;

  ctx.clearRect(0, 0, W, H);

  // Parse WAV PCM to amplitude data
  try {
    const bytes = base64ToUint8(base64Data);
    const view = new DataView(bytes.buffer);

    // Skip WAV header (44 bytes) and read 16-bit PCM
    const numSamples = Math.floor((bytes.length - 44) / 2);
    const step = Math.max(1, Math.floor(numSamples / W));
    const bars = W;

    ctx.fillStyle = 'transparent';

    const accentColor = getComputedStyle(document.body).getPropertyValue('--accent').trim() || '#4ecca3';
    const accentDim   = getComputedStyle(document.body).getPropertyValue('--surface-3').trim() || '#242a3e';

    for (let i = 0; i < bars; i++) {
      let max = 0;
      const offset = 44 + i * step * 2;
      for (let j = 0; j < step; j++) {
        const byteOffset = offset + j * 2;
        if (byteOffset + 2 > bytes.length) break;
        const sample = Math.abs(view.getInt16(byteOffset, true));
        if (sample > max) max = sample;
      }
      const norm = max / 32768;
      const barH = Math.max(2, norm * (H - 8));
      const x = i;
      const y = (H - barH) / 2;

      // Gradient: accent → dim
      const grad = ctx.createLinearGradient(0, y, 0, y + barH);
      grad.addColorStop(0, accentColor + 'cc');
      grad.addColorStop(1, accentColor + '44');
      ctx.fillStyle = grad;
      ctx.fillRect(x, y, 1, barH);
    }
  } catch {
    // Fallback: fake waveform
    drawFakeWaveform(ctx, canvas.offsetWidth, canvas.offsetHeight);
  }
}

function drawFakeWaveform(ctx, W, H) {
  const accentColor = getComputedStyle(document.body).getPropertyValue('--accent').trim() || '#4ecca3';
  for (let i = 0; i < W; i++) {
    const norm = 0.3 + 0.5 * Math.abs(Math.sin(i * 0.15)) * Math.random();
    const barH = Math.max(2, norm * (H - 8));
    const y = (H - barH) / 2;
    ctx.fillStyle = accentColor + '88';
    ctx.fillRect(i, y, 1, barH);
  }
}

// ── Export ────────────────────────────────────────────────────────────────

async function exportWav() {
  if (!state.lastAudioData) return;
  const voice = state.selectedVoice?.name || 'output';
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const result = await api.fs.saveAudio({
    audioData: state.lastAudioData,
    defaultName: `VocalText_${voice}_${ts}.wav`
  });
  if (result.success) {
    flash(els.btnExportWav, 'Salvato!');
  }
}

function flash(btn, msg) {
  const orig = btn.innerHTML;
  btn.textContent = msg;
  setTimeout(() => { btn.innerHTML = orig; }, 2000);
}

// ── History ───────────────────────────────────────────────────────────────

function addToHistory({ text, voice, audioData }) {
  const entry = {
    id: Date.now(),
    text: text.length > 80 ? text.slice(0, 80) + '…' : text,
    voiceName: voice.name,
    engine: voice.engine,
    audioData,
    timestamp: new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
  };

  state.history.unshift(entry);
  if (state.history.length > 8) state.history.pop();

  renderHistory();
}

function renderHistory() {
  if (state.history.length === 0) {
    els.historySection.style.display = 'none';
    return;
  }

  els.historySection.style.display = 'block';
  els.historyList.innerHTML = '';

  for (const entry of state.history) {
    const item = document.createElement('div');
    item.className = 'history-item';
    item.innerHTML = `
      <div class="history-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
        </svg>
      </div>
      <div class="history-meta">
        <div class="history-text">${escapeHtml(entry.text)}</div>
        <div class="history-sub">${entry.voiceName} · ${entry.timestamp}</div>
      </div>
      <button class="history-play" title="Riproduci">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      </button>
    `;

    item.querySelector('.history-play').addEventListener('click', (e) => {
      e.stopPropagation();
      playHistoryEntry(entry);
    });

    els.historyList.appendChild(item);
  }
}

function playHistoryEntry(entry) {
  const blob = base64ToBlob(entry.audioData, 'audio/wav');
  state.audioBlob = blob;
  state.audioUrl = URL.createObjectURL(blob);
  state.lastAudioData = entry.audioData;
  els.audioEl.src = state.audioUrl;
  loadAudioMetadata().then(() => {
    drawWaveform(entry.audioData);
    showPlayer();
    els.audioEl.play();
    els.iconPlay.style.display = 'none';
    els.iconPause.style.display = 'block';
  });
}

// ── Modal ─────────────────────────────────────────────────────────────────

function openModal() {
  const voices = getVoicesCatalog();
  els.modalVoiceList.innerHTML = '';

  for (const v of voices) {
    const item = document.createElement('div');
    item.className = 'modal-voice-item';
    item.innerHTML = `
      <div class="voice-avatar ${v.gender}">${v.name.charAt(0)}</div>
      <div class="modal-voice-info">
        <div class="modal-voice-name">${v.name}</div>
        <div class="modal-voice-meta">${v.language} · ${v.quality} · ${v.size_mb} MB</div>
      </div>
      <a class="btn-dl" href="${buildDownloadUrl(v)}" target="_blank">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Scarica
      </a>
    `;
    els.modalVoiceList.appendChild(item);
  }

  els.modalOverlay.style.display = 'flex';
}

function closeModal() {
  els.modalOverlay.style.display = 'none';
}

function getVoicesCatalog() {
  // These are the voices from voices.json (hardcoded here for the renderer)
  return [
    { name: 'Riccardo', language: 'Italiano',      lang_code: 'it_IT', gender: 'male',   quality: 'low',    size_mb: 24,  files: ['it/it_IT/riccardo/x_low/it_IT-riccardo-x_low.onnx', 'it/it_IT/riccardo/x_low/it_IT-riccardo-x_low.onnx.json'] },
    { name: 'Paola',    language: 'Italiano',      lang_code: 'it_IT', gender: 'female', quality: 'medium', size_mb: 63,  files: ['it/it_IT/paola/medium/it_IT-paola-medium.onnx', 'it/it_IT/paola/medium/it_IT-paola-medium.onnx.json'] },
    { name: 'Lessac',   language: 'English (US)',  lang_code: 'en_US', gender: 'female', quality: 'medium', size_mb: 63,  files: ['en/en_US/lessac/medium/en_US-lessac-medium.onnx', 'en/en_US/lessac/medium/en_US-lessac-medium.onnx.json'] },
    { name: 'Ryan',     language: 'English (US)',  lang_code: 'en_US', gender: 'male',   quality: 'high',   size_mb: 121, files: ['en/en_US/ryan/high/en_US-ryan-high.onnx', 'en/en_US/ryan/high/en_US-ryan-high.onnx.json'] },
    { name: 'Alan',     language: 'English (GB)',  lang_code: 'en_GB', gender: 'male',   quality: 'medium', size_mb: 63,  files: ['en/en_GB/alan/medium/en_GB-alan-medium.onnx', 'en/en_GB/alan/medium/en_GB-alan-medium.onnx.json'] },
    { name: 'Thorsten', language: 'Deutsch',       lang_code: 'de_DE', gender: 'male',   quality: 'medium', size_mb: 63,  files: ['de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx', 'de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json'] },
    { name: 'UPMC',     language: 'Français',      lang_code: 'fr_FR', gender: 'male',   quality: 'medium', size_mb: 63,  files: ['fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx', 'fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx.json'] }
  ];
}

function buildDownloadUrl(voice) {
  const base = 'https://huggingface.co/rhasspy/piper-voices/resolve/main';
  return `${base}/${voice.files[0]}`;
}

// ── Errors ────────────────────────────────────────────────────────────────

function showError(msg) {
  els.errorText.textContent = msg;
  els.errorBox.style.display = 'flex';
}

function hideError() {
  els.errorBox.style.display = 'none';
}

// ── Helpers ───────────────────────────────────────────────────────────────

function formatTime(sec) {
  if (!isFinite(sec)) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function base64ToBlob(b64, mime) {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type: mime });
}

function base64ToUint8(b64) {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return arr;
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Event bindings ────────────────────────────────────────────────────────

function bindEvents() {
  // Text editor
  els.textInput.addEventListener('input', updateCounts);
  els.btnClear.addEventListener('click', () => {
    els.textInput.value = '';
    updateCounts();
    els.textInput.focus();
  });
  els.btnPaste.addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      els.textInput.value = text;
      updateCounts();
    } catch {}
  });

  // Generate
  els.btnGenerate.addEventListener('click', generateAudio);
  els.textInput.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') generateAudio();
  });

  // Audio controls
  els.btnPlayPause.addEventListener('click', togglePlayPause);
  els.audioEl.addEventListener('timeupdate', onAudioTimeUpdate);
  els.audioEl.addEventListener('ended', onAudioEnded);
  els.seekBar.addEventListener('input', onSeekChange);
  els.btnRestart.addEventListener('click', () => {
    els.audioEl.currentTime = 0;
    els.audioEl.play();
    els.iconPlay.style.display = 'none';
    els.iconPause.style.display = 'block';
  });

  // Waveform click to seek
  els.waveformCanvas.addEventListener('click', (e) => {
    const rect = els.waveformCanvas.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    els.audioEl.currentTime = pct * els.audioEl.duration;
  });

  // Export
  els.btnExportWav.addEventListener('click', exportWav);

  // Sliders
  ['speed', 'pitch', 'volume'].forEach(name => {
    const el = els[`ctrl${name.charAt(0).toUpperCase() + name.slice(1)}`];
    el.addEventListener('input', () => {
      const v = parseFloat(el.value);
      state[name] = v;
      updateSliderLabel(name, v);
      api.settings.set(name, v);
    });
  });

  // Theme
  els.btnTheme.addEventListener('click', toggleTheme);

  // Piper hint
  els.btnOpenModels.addEventListener('click', () => {
    openModal();
  });

  // Window controls
  if (els.btnMinimize) els.btnMinimize.addEventListener('click', () => api.window.minimize());
  if (els.btnMaximize) els.btnMaximize.addEventListener('click', () => api.window.maximize());
  if (els.btnClose)    els.btnClose.addEventListener('click',    () => api.window.close());

  // Modal
  els.modalClose.addEventListener('click', closeModal);
  els.modalOpenFolder.addEventListener('click', () => { api.fs.openModelsDir(); closeModal(); });
  els.modalOverlay.addEventListener('click', (e) => {
    if (e.target === els.modalOverlay) closeModal();
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
    if (e.key === ' ' && document.activeElement !== els.textInput) {
      e.preventDefault();
      if (state.audioUrl) togglePlayPause();
    }
  });

  // Resize waveform on window resize
  window.addEventListener('resize', () => {
    if (state.lastAudioData) drawWaveform(state.lastAudioData);
  });
}

// ── Boot ──────────────────────────────────────────────────────────────────
init().catch(console.error);
