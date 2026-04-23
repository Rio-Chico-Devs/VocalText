"""
Pipeline di post-processing audio professionale per VocalText.

Catena completa (pedalboard disponibile):
  HP 80Hz → De-esser custom → Presence EQ → Low-shelf calore
  → Compressor → Noise reduction leggera → Limiter → LUFS → Fade

Fallback (solo numpy/scipy):
  HP 80Hz → De-esser → Presence pre-emphasis → LUFS → Fade

Note:
  - `noisereduce` su voci TTS può creare artefatti metallici se troppo
    aggressivo. Usiamo prop_decrease basso (0.25) e solo se il rumore
    stimato è sopra soglia.
  - Il de-esser è custom (multi-band compression sulla banda 5-8kHz),
    più efficace del generico PeakFilter per le sibilanti XTTS.
  - Se il processing produce silenzio/errore → mantiene l'originale.
"""

from __future__ import annotations
import wave
import numpy as np


# ── I/O WAV ────────────────────────────────────────────────────────────────────

def _read_wav(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as wf:
        n_ch = wf.getnchannels()
        sw   = wf.getsampwidth()
        sr   = wf.getframerate()
        raw  = wf.readframes(wf.getnframes())
    if sw == 2:
        s = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        s = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        s = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0
    if n_ch > 1:
        s = s.reshape(-1, n_ch).mean(axis=1)
    return s.astype(np.float32), sr


def _write_wav(path: str, samples: np.ndarray, sr: int):
    data = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(data.tobytes())


def _is_valid(samples: np.ndarray) -> bool:
    return len(samples) > 0 and float(np.max(np.abs(samples))) > 0.001


# ── Pipeline principale ────────────────────────────────────────────────────────

def polish(input_path: str, output_path: str | None = None,
           target_lufs: float = -16.0):
    """
    Rifinisce il WAV. Se output_path è None sovrascrive il sorgente.
    Se il processing fallisce o produce silenzio, mantiene l'originale.
    """
    if output_path is None:
        output_path = input_path

    original, sr = _read_wav(input_path)
    if not _is_valid(original):
        return

    try:
        processed = _process(original.copy(), sr, target_lufs)
        if _is_valid(processed):
            _write_wav(output_path, processed, sr)
        else:
            _write_wav(output_path, original, sr)
    except Exception:
        _write_wav(output_path, original, sr)


def _process(samples: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
    try:
        result = _process_pedalboard(samples, sr, target_lufs)
        if _is_valid(result):
            return result
        return _process_basic(samples, sr, target_lufs)
    except ImportError:
        return _process_basic(samples, sr, target_lufs)
    except Exception:
        return _process_basic(samples, sr, target_lufs)


# ── Pedalboard path ────────────────────────────────────────────────────────────

def _process_pedalboard(samples: np.ndarray, sr: int,
                         target_lufs: float) -> np.ndarray:
    from pedalboard import (Pedalboard, PeakFilter, LowShelfFilter,
                             Compressor, Limiter)

    # Pre-FX: HP + de-esser + DC remove — prima della catena pedalboard
    samples = _highpass_80(samples, sr)
    samples = _deesser(samples, sr)
    samples = _dc_remove(samples)

    audio = samples[np.newaxis, :]

    board = Pedalboard([
        # Presenza voce – boost chiarezza 2-4 kHz
        PeakFilter(cutoff_frequency_hz=3000.0, gain_db=1.8, q=0.9),
        # Calore basse frequenze voce
        LowShelfFilter(cutoff_frequency_hz=200.0, gain_db=0.8),
        # Compressione leggera
        Compressor(threshold_db=-20.0, ratio=3.0,
                   attack_ms=10.0, release_ms=150.0),
        # Hard limiter
        Limiter(threshold_db=-1.0, release_ms=100.0),
    ])
    samples = board(audio, sr)[0]

    # Noise reduction leggera SOLO se c'è rumore stimato
    samples = _gentle_denoise(samples, sr)

    samples = _lufs_normalize(samples, sr, target_lufs)
    return _fade(np.clip(samples, -1.0, 1.0).astype(np.float32), sr)


# ── Fallback path (solo numpy/scipy) ──────────────────────────────────────────

def _process_basic(samples: np.ndarray, sr: int,
                    target_lufs: float) -> np.ndarray:
    samples = _highpass_80(samples, sr)
    samples = _deesser(samples, sr)
    samples = _dc_remove(samples)
    samples = _presence_boost(samples, sr)
    samples = _soft_compress(samples)
    samples = _gentle_denoise(samples, sr)
    samples = _lufs_normalize(samples, sr, target_lufs)
    return _fade(np.clip(samples, -1.0, 1.0).astype(np.float32), sr)


# ── Building blocks custom ────────────────────────────────────────────────────

def _highpass_80(samples: np.ndarray, sr: int) -> np.ndarray:
    """High-pass Butterworth 80Hz — rimuove rumble/DC."""
    try:
        from scipy import signal
        sos = signal.butter(4, 80.0 / (sr / 2), btype="high", output="sos")
        return signal.sosfilt(sos, samples).astype(np.float32)
    except ImportError:
        return samples


def _deesser(samples: np.ndarray, sr: int,
             freq_low: float = 5000.0, freq_high: float = 8500.0,
             threshold: float = 0.35, ratio: float = 3.0) -> np.ndarray:
    """
    De-esser custom: isola la banda sibilante con un band-pass,
    misura l'inviluppo, e quando supera la soglia attenua SOLO quella
    banda (non l'intero segnale). Molto efficace sui "S" striduli di XTTS.
    """
    try:
        from scipy import signal
    except ImportError:
        return samples

    nyq = sr / 2.0
    if freq_high >= nyq:
        freq_high = nyq * 0.95
    if freq_low >= freq_high:
        return samples

    sos = signal.butter(4, [freq_low / nyq, freq_high / nyq],
                        btype="band", output="sos")
    sibilance = signal.sosfilt(sos, samples).astype(np.float32)

    # Inviluppo (RMS scorrevole ~5ms)
    win = max(1, int(0.005 * sr))
    env = np.sqrt(_moving_avg(sibilance ** 2, win) + 1e-12)

    gr = np.ones_like(env, dtype=np.float32)
    over = env > threshold
    if np.any(over):
        excess_db = 20.0 * np.log10(env[over] / threshold)
        reduction_db = excess_db * (1.0 - 1.0 / ratio)
        gr[over] = (10.0 ** (-reduction_db / 20.0)).astype(np.float32)

    # Smooth del gain per evitare distorsione
    gr = _moving_avg(gr, win)

    # Sottrai la porzione sibilante attenuata dal segnale originale
    attenuation = sibilance * (1.0 - gr)
    return (samples - attenuation).astype(np.float32)


def _presence_boost(samples: np.ndarray, sr: int,
                    gain_db: float = 1.5) -> np.ndarray:
    """Peak EQ 3 kHz Q=0.9 (RBJ biquad) — chiarezza voce."""
    try:
        from scipy import signal
    except ImportError:
        return samples
    f0 = 3000.0
    Q  = 0.9
    A  = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2 * Q)

    b0 = 1 + alpha * A
    b1 = -2 * np.cos(w0)
    b2 = 1 - alpha * A
    a0 = 1 + alpha / A
    a1 = -2 * np.cos(w0)
    a2 = 1 - alpha / A
    b = np.array([b0, b1, b2]) / a0
    a = np.array([1.0, a1 / a0, a2 / a0])
    return signal.lfilter(b, a, samples).astype(np.float32)


def _soft_compress(samples: np.ndarray,
                   threshold: float = 0.25, ratio: float = 2.5) -> np.ndarray:
    """Compressione soft istantanea – uniforma i picchi."""
    abs_s = np.abs(samples)
    over = abs_s > threshold
    gain = np.ones_like(samples)
    if np.any(over):
        excess = abs_s[over] / threshold
        compressed = threshold * (excess ** (1.0 / ratio))
        gain[over] = compressed / abs_s[over]
    return (samples * gain).astype(np.float32)


def _dc_remove(samples: np.ndarray) -> np.ndarray:
    if len(samples) == 0:
        return samples
    return (samples - float(np.mean(samples))).astype(np.float32)


def _gentle_denoise(samples: np.ndarray, sr: int) -> np.ndarray:
    """
    Noise reduction CONSERVATIVA.
    Attiva solo se il noise floor stimato è sopra -45 dBFS.
    prop_decrease basso per minimizzare artefatti "metallici".
    """
    try:
        import noisereduce as nr
    except ImportError:
        return samples

    win = max(1, int(0.020 * sr))
    env = np.sqrt(_moving_avg(samples ** 2, win) + 1e-12)
    noise_floor = float(np.percentile(env, 10))

    # -45 dBFS soglia: voci TTS pulite passano intatte
    if noise_floor < 0.0056:
        return samples

    try:
        return nr.reduce_noise(
            y=samples, sr=sr,
            stationary=True,
            prop_decrease=0.25,
        ).astype(np.float32)
    except Exception:
        return samples


def _moving_avg(x: np.ndarray, win: int) -> np.ndarray:
    """Media mobile centrata, stessa lunghezza dell'input (O(N))."""
    if win <= 1 or len(x) == 0:
        return x.astype(np.float32)
    csum = np.cumsum(np.concatenate([[0.0], x.astype(np.float64)]))
    n = len(x)
    half = win // 2
    lo = np.clip(np.arange(n) - half, 0, n)
    hi = np.clip(np.arange(n) + half + 1, 0, n)
    counts = (hi - lo).astype(np.float64)
    counts[counts == 0] = 1.0
    return ((csum[hi] - csum[lo]) / counts).astype(np.float32)


def _lufs_normalize(samples: np.ndarray, sr: int,
                     target_lufs: float) -> np.ndarray:
    try:
        import pyloudnorm as pyln
        meter    = pyln.Meter(sr)
        loudness = meter.integrated_loudness(samples)
        if loudness > -70.0 and np.isfinite(loudness):
            normalized = pyln.normalize.loudness(samples, loudness, target_lufs)
            if _is_valid(normalized):
                return normalized.astype(np.float32)
    except (ImportError, Exception):
        pass
    peak = float(np.max(np.abs(samples)))
    if peak > 0:
        samples = samples / peak * 0.9
    return samples.astype(np.float32)


def _fade(samples: np.ndarray, sr: int, ms: int = 8) -> np.ndarray:
    n = int(ms / 1000.0 * sr)
    if len(samples) > n * 2:
        samples[:n]  *= np.linspace(0.0, 1.0, n, dtype=np.float32)
        samples[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    return samples
