"""
Pipeline di post-processing audio professionale per VocalText.
Applica: high-pass, noise reduction, EQ voce, compressione, normalizzazione LUFS,
limiter, fade in/out.

Usa pedalboard (Spotify) se disponibile, altrimenti scipy come fallback.
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


# ── Pipeline ───────────────────────────────────────────────────────────────────

def polish(input_path: str, output_path: str | None = None,
           target_lufs: float = -16.0):
    """
    Rifinisce il WAV audio con una catena professionale.
    Se output_path è None sovrascrive il file sorgente.
    """
    if output_path is None:
        output_path = input_path
    samples, sr = _read_wav(input_path)
    samples = _process(samples, sr, target_lufs)
    _write_wav(output_path, samples, sr)


def _process(samples: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
    try:
        return _process_pedalboard(samples, sr, target_lufs)
    except ImportError:
        return _process_basic(samples, sr, target_lufs)


def _process_pedalboard(samples: np.ndarray, sr: int,
                         target_lufs: float) -> np.ndarray:
    from pedalboard import (Pedalboard, HighpassFilter, LowpassFilter,
                             PeakFilter, LowShelfFilter, Compressor,
                             Limiter, NoiseGate)

    audio = samples[np.newaxis, :]   # (1, N) per pedalboard

    board = Pedalboard([
        # Rimuove rumble e offset DC
        HighpassFilter(cutoff_frequency_hz=80.0),
        # Taglia ultra-high non necessario per la voce
        LowpassFilter(cutoff_frequency_hz=16000.0),
        # Noise gate leggero per eliminare artefatti in silenzio
        NoiseGate(threshold_db=-55.0, ratio=2.0,
                  attack_ms=5.0, release_ms=100.0),
        # Presenza voce (chiarezza 2–4 kHz)
        PeakFilter(cutoff_frequency_hz=3000.0, gain_db=1.5, q=0.8),
        # Calore basse frequenze voce
        LowShelfFilter(cutoff_frequency_hz=200.0, gain_db=0.8),
        # Compressione moderata – uniforma le dinamiche
        Compressor(threshold_db=-22.0, ratio=3.5,
                   attack_ms=8.0, release_ms=120.0),
        # Hard limiter – evita qualsiasi clipping
        Limiter(threshold_db=-1.0, release_ms=100.0),
    ])

    audio = board(audio, sr)
    samples = audio[0]

    # Noise reduction spettrale
    try:
        import noisereduce as nr
        samples = nr.reduce_noise(y=samples, sr=sr,
                                  stationary=True, prop_decrease=0.75)
    except ImportError:
        pass

    samples = _lufs_normalize(samples, sr, target_lufs)
    return _fade(np.clip(samples, -1.0, 1.0).astype(np.float32), sr)


def _process_basic(samples: np.ndarray, sr: int,
                    target_lufs: float) -> np.ndarray:
    """Fallback senza pedalboard – usa scipy."""
    try:
        from scipy import signal
        sos = signal.butter(4, 80.0 / (sr / 2), btype="high", output="sos")
        samples = signal.sosfilt(sos, samples).astype(np.float32)
    except ImportError:
        pass

    try:
        import noisereduce as nr
        samples = nr.reduce_noise(y=samples, sr=sr,
                                  stationary=True, prop_decrease=0.75)
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
        if loudness > -70.0:
            samples = pyln.normalize.loudness(samples, loudness, target_lufs)
        return samples
    except (ImportError, Exception):
        # Fallback: normalizzazione al picco
        peak = np.max(np.abs(samples))
        if peak > 0:
            samples = samples / peak * 0.9
        return samples


def _fade(samples: np.ndarray, sr: int, ms: int = 8) -> np.ndarray:
    n = int(ms / 1000.0 * sr)
    if len(samples) > n * 2:
        samples[:n]  *= np.linspace(0.0, 1.0, n)
        samples[-n:] *= np.linspace(1.0, 0.0, n)
    return samples
