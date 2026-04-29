"""
Cambia velocità di riproduzione preservando l'intonazione (pitch).

Strategia di priorità:
  1. pedalboard.time_stretch (Rubberband) — qualità professionale
  2. Phase vocoder custom (numpy + scipy STFT) — fallback puro DSP

factor > 1.0 → audio più veloce (es. 1.25 = +25%, durata −20%)
factor < 1.0 → audio più lento  (es. 0.75 = −25%, durata +33%)
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


# ── API pubblica ───────────────────────────────────────────────────────────────

def change_speed(input_path: str, output_path: str | None = None,
                 factor: float = 1.0) -> bool:
    """
    Cambia velocità mantenendo il pitch.
    Ritorna True se la modifica è andata a buon fine, False altrimenti
    (in tal caso l'output contiene una copia dell'originale).
    """
    if output_path is None:
        output_path = input_path

    factor = max(0.25, min(4.0, float(factor)))
    samples, sr = _read_wav(input_path)
    if not _is_valid(samples):
        return False

    # No-op (entro 1%): copia esatta
    if abs(factor - 1.0) < 0.01:
        _write_wav(output_path, samples, sr)
        return True

    try:
        out = _stretch_pedalboard(samples, sr, factor)
        if _is_valid(out):
            _write_wav(output_path, out, sr)
            return True
    except Exception:
        pass

    try:
        out = _stretch_phase_vocoder(samples, sr, factor)
        if _is_valid(out):
            _write_wav(output_path, out, sr)
            return True
    except Exception:
        pass

    _write_wav(output_path, samples, sr)
    return False


# ── Path pedalboard (preferito) ────────────────────────────────────────────────

def _stretch_pedalboard(samples: np.ndarray, sr: int,
                        factor: float) -> np.ndarray:
    """Rubberband via pedalboard — qualità studio, pitch preservato."""
    from pedalboard import time_stretch  # pedalboard ≥ 0.7.4

    audio = samples[np.newaxis, :]
    out = time_stretch(
        audio, sr,
        stretch_factor=float(factor),
        pitch_shift_in_semitones=0.0,
    )
    return out[0].astype(np.float32)


# ── Path fallback: phase vocoder custom ───────────────────────────────────────

def _stretch_phase_vocoder(samples: np.ndarray, sr: int,
                           factor: float) -> np.ndarray:
    """
    Phase vocoder STFT classico:
      - analizza con hop_a costante
      - sintetizza con hop_s = hop_a / factor
      - propaga le fasi accumulando la differenza istantanea (= unwrapping)
    Mantiene l'intonazione modificando solo la struttura temporale.
    Qualità accettabile per voce; transitori leggermente smussati.
    """
    from scipy.signal import get_window

    n_fft  = 2048
    hop_a  = n_fft // 4              # hop di analisi
    hop_s  = max(1, int(round(hop_a / float(factor))))   # hop di sintesi
    win    = get_window("hann", n_fft).astype(np.float32)

    # Padding per coprire i bordi
    pad = n_fft
    x   = np.concatenate([np.zeros(pad, dtype=np.float32),
                          samples,
                          np.zeros(pad, dtype=np.float32)])

    n_frames = 1 + (len(x) - n_fft) // hop_a
    if n_frames < 2:
        return samples

    # STFT analisi
    spec = np.empty((n_fft // 2 + 1, n_frames), dtype=np.complex64)
    for k in range(n_frames):
        seg = x[k * hop_a : k * hop_a + n_fft] * win
        spec[:, k] = np.fft.rfft(seg)

    mag    = np.abs(spec)
    phases = np.angle(spec)

    # Frequenze "vere" via differenza fase: omega_bin + dphi
    omega = 2.0 * np.pi * np.arange(n_fft // 2 + 1) * hop_a / n_fft
    dphi  = np.diff(phases, axis=1) - omega[:, None]
    # principal value in [-pi, pi]
    dphi  = dphi - 2.0 * np.pi * np.round(dphi / (2.0 * np.pi))
    true_freq = (omega[:, None] + dphi) / hop_a   # rad/sample

    # Sintesi: accumula fase con hop_s
    out_phases = np.empty_like(phases)
    out_phases[:, 0] = phases[:, 0]
    for k in range(1, n_frames):
        out_phases[:, k] = out_phases[:, k - 1] + true_freq[:, k - 1] * hop_s

    new_spec = mag * np.exp(1j * out_phases)

    # iSTFT (overlap-add con normalizzazione del window)
    out_len = (n_frames - 1) * hop_s + n_fft
    y       = np.zeros(out_len, dtype=np.float32)
    win_sum = np.zeros(out_len, dtype=np.float32)
    for k in range(n_frames):
        frame = np.fft.irfft(new_spec[:, k]).astype(np.float32) * win
        i0 = k * hop_s
        y[i0 : i0 + n_fft]       += frame
        win_sum[i0 : i0 + n_fft] += win * win

    win_sum[win_sum < 1e-6] = 1.0
    y = y / win_sum

    # Rimuovi padding originale (proporzionale al fattore)
    cut = int(pad / float(factor))
    y = y[cut : cut + int(round(len(samples) / float(factor)))]

    # Normalizza al picco originale per evitare clipping
    peak_in  = float(np.max(np.abs(samples)))
    peak_out = float(np.max(np.abs(y)))
    if peak_out > 0 and peak_in > 0:
        y = y * (peak_in / peak_out) * 0.95
    return y.astype(np.float32)
