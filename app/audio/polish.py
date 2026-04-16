"""
Pipeline di post-processing audio professionale per VocalText.
Applica: high-pass, noise reduction, EQ voce, compressione, normalizzazione LUFS,
limiter, fade in/out.

Usa pedalboard (Spotify) se disponibile, altrimenti scipy come fallback.
Se il processing produce output vuoto/silenzioso, usa l'audio originale.
"""

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
    """Verifica che l'audio non sia vuoto o completamente silenzioso."""
    return len(samples) > 0 and float(np.max(np.abs(samples))) > 0.001


# ── Pipeline ───────────────────────────────────────────────────────────────────

def polish(input_path: str, output_path: str | None = None,
           target_lufs: float = -16.0):
    """
    Rifinisce il WAV audio con una catena professionale.
    Se output_path è None sovrascrive il file sorgente.
    Se il processing fallisce o produce silenzio, mantiene l'originale.
    """
    if output_path is None:
        output_path = input_path

    original, sr = _read_wav(input_path)

    if not _is_valid(original):
        return  # file originale già vuoto, niente da fare

    try:
        processed = _process(original.copy(), sr, target_lufs)
        if _is_valid(processed):
            _write_wav(output_path, processed, sr)
        else:
            # Il processing ha prodotto silenzio — usa l'originale
            _write_wav(output_path, original, sr)
    except Exception:
        # Qualsiasi errore → scrivi comunque l'originale
        _write_wav(output_path, original, sr)


def _process(samples: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
    try:
        result = _process_pedalboard(samples, sr, target_lufs)
        if _is_valid(result):
            return result
        # pedalboard ha restituito silenzio → prova il fallback
        return _process_basic(samples, sr, target_lufs)
    except ImportError:
        return _process_basic(samples, sr, target_lufs)
    except Exception:
        return _process_basic(samples, sr, target_lufs)


def _process_pedalboard(samples: np.ndarray, sr: int,
                         target_lufs: float) -> np.ndarray:
    from pedalboard import (Pedalboard, HighpassFilter,
                             PeakFilter, LowShelfFilter,
                             Compressor, Limiter)

    audio = samples[np.newaxis, :]   # (1, N) per pedalboard

    board = Pedalboard([
        # Rimuove rumble e offset DC
        HighpassFilter(cutoff_frequency_hz=80.0),
        # Presenza voce (chiarezza 2-4 kHz)
        PeakFilter(cutoff_frequency_hz=3000.0, gain_db=1.5, q=0.8),
        # Calore basse frequenze voce
        LowShelfFilter(cutoff_frequency_hz=200.0, gain_db=0.8),
        # Compressione leggera – uniforma le dinamiche
        Compressor(threshold_db=-20.0, ratio=3.0,
                   attack_ms=10.0, release_ms=150.0),
        # Hard limiter – evita clipping
        Limiter(threshold_db=-1.0, release_ms=100.0),
    ])

    out = board(audio, sr)
    samples = out[0]

    # Noise reduction opzionale
    try:
        import noisereduce as nr
        samples = nr.reduce_noise(y=samples, sr=sr,
                                  stationary=True, prop_decrease=0.6)
    except ImportError:
        pass

    samples = _lufs_normalize(samples, sr, target_lufs)
    return _fade(np.clip(samples, -1.0, 1.0).astype(np.float32), sr)


def _process_basic(samples: np.ndarray, sr: int,
                    target_lufs: float) -> np.ndarray:
    """Fallback senza pedalboard – usa solo numpy + librerie opzionali."""
    try:
        from scipy import signal
        sos = signal.butter(4, 80.0 / (sr / 2), btype="high", output="sos")
        samples = signal.sosfilt(sos, samples).astype(np.float32)
    except ImportError:
        pass

    try:
        import noisereduce as nr
        samples = nr.reduce_noise(y=samples, sr=sr,
                                  stationary=True, prop_decrease=0.6)
    except ImportError:
        pass

    samples = _lufs_normalize(samples, sr, target_lufs)
    return _fade(np.clip(samples, -1.0, 1.0).astype(np.float32), sr)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _lufs_normalize(samples: np.ndarray, sr: int,
                     target_lufs: float) -> np.ndarray:
    try:
        import pyloudnorm as pyln
        meter    = pyln.Meter(sr)
        loudness = meter.integrated_loudness(samples)
        if loudness > -70.0 and np.isfinite(loudness):
            normalized = pyln.normalize.loudness(samples, loudness, target_lufs)
            # Sanity check: la normalizzazione non deve azzerare l'audio
            if _is_valid(normalized):
                return normalized
    except (ImportError, Exception):
        pass

    # Fallback: normalizzazione al picco
    peak = float(np.max(np.abs(samples)))
    if peak > 0:
        samples = samples / peak * 0.9
    return samples


def _fade(samples: np.ndarray, sr: int, ms: int = 8) -> np.ndarray:
    n = int(ms / 1000.0 * sr)
    if len(samples) > n * 2:
        samples[:n]  *= np.linspace(0.0, 1.0, n)
        samples[-n:] *= np.linspace(1.0, 0.0, n)
    return samples
