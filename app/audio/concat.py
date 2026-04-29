"""
Concatenazione audio intelligente per chunk TTS.

Features:
  - Trim del silenzio ai bordi di ogni chunk (evita "dead air")
  - Crossfade equal-power tra chunk adiacenti (curve sin/cos)
  - Pause adattive tra chunk in base alla punteggiatura
  - DC offset removal per-chunk (elimina "pop" alle giunzioni)
  - Loudness matching leggero (chunk-to-chunk, non globale)

L'equal-power crossfade usa (sin², cos²) invece del lineare:
la somma dell'energia resta costante → niente "buco" percepito
al punto di giunzione.
"""

from __future__ import annotations
import numpy as np


# ── API pubblica ───────────────────────────────────────────────────────────────

def concat_chunks(chunks: list[np.ndarray], sr: int,
                  pauses_ms: list[int],
                  crossfade_ms: int = 18,
                  trim_silence: bool = True,
                  match_loudness: bool = True) -> np.ndarray:
    """
    Concatena N chunk audio. Tra chunk i e i+1 viene applicata:
      - silenzio lungo pauses_ms[i]   (se > soglia crossfade)
      - oppure crossfade equal-power  (se pausa breve)

    Args:
        chunks: lista di array float32 mono
        sr: sample rate comune
        pauses_ms: len(chunks)-1 oppure len(chunks) (ultimo ignorato)
        crossfade_ms: durata crossfade quando la pausa è breve
        trim_silence: rimuove silenzio ai bordi di ogni chunk
        match_loudness: normalizza RMS per-chunk (chunk più uniformi)
    """
    if not chunks:
        return np.zeros(0, dtype=np.float32)

    # Normalizza ingresso
    chunks = [np.asarray(c, dtype=np.float32) for c in chunks if c is not None and len(c) > 0]
    if not chunks:
        return np.zeros(0, dtype=np.float32)

    # Per-chunk cleanup
    if trim_silence:
        chunks = [_trim_silence(c, sr) for c in chunks]
        chunks = [c for c in chunks if len(c) > 0]
        if not chunks:
            return np.zeros(0, dtype=np.float32)

    chunks = [_remove_dc(c) for c in chunks]

    if match_loudness and len(chunks) > 1:
        chunks = _match_loudness(chunks)

    if len(chunks) == 1:
        return chunks[0]

    # Pad pauses_ms al numero di giunzioni (len(chunks)-1)
    junctions = len(chunks) - 1
    if len(pauses_ms) < junctions:
        pauses_ms = list(pauses_ms) + [80] * (junctions - len(pauses_ms))

    cf_samples = int(crossfade_ms / 1000.0 * sr)
    result = chunks[0].copy()

    for i in range(junctions):
        nxt = chunks[i + 1]
        pause_ms = pauses_ms[i]
        pause_samples = int(pause_ms / 1000.0 * sr)

        if pause_samples > cf_samples:
            # Pausa "vera" → silenzio + micro fade sui bordi per evitare click
            result = _fade_out(result, sr, ms=6)
            result = np.concatenate([
                result,
                np.zeros(pause_samples, dtype=np.float32),
                _fade_in(nxt, sr, ms=6),
            ])
        else:
            # Niente pausa percepita → crossfade equal-power
            result = _crossfade(result, nxt, cf_samples)

    return result.astype(np.float32)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _trim_silence(samples: np.ndarray, sr: int,
                  threshold: float = 0.003,
                  keep_ms: int = 25) -> np.ndarray:
    """
    Rimuove il silenzio iniziale/finale sotto soglia RMS, lasciando
    keep_ms di "aria" per non troncare sbuffi/consonanti deboli.
    """
    if len(samples) == 0:
        return samples

    abs_s = np.abs(samples)
    # Finestra di analisi ~10ms
    win = max(1, int(0.010 * sr))
    if len(abs_s) <= win:
        return samples

    # Indici dove il livello supera la soglia (analisi a finestra scorrevole)
    # Usiamo cumsum per media mobile efficiente
    csum = np.cumsum(np.concatenate([[0.0], abs_s]))
    mean = (csum[win:] - csum[:-win]) / win
    above = np.where(mean > threshold)[0]
    if len(above) == 0:
        return samples   # tutto sotto soglia → lo lasciamo come è

    keep = int(keep_ms / 1000.0 * sr)
    start = max(0, above[0] - keep)
    end   = min(len(samples), above[-1] + win + keep)
    return samples[start:end]


def _remove_dc(samples: np.ndarray) -> np.ndarray:
    """Rimuove offset DC — previene 'pop' alle giunzioni."""
    if len(samples) == 0:
        return samples
    return samples - float(np.mean(samples))


def _match_loudness(chunks: list[np.ndarray]) -> list[np.ndarray]:
    """
    Allinea l'RMS dei chunk al valore mediano.
    Evita scalini di volume tra frasi generate separatamente.
    Applica gain max ±6dB per sicurezza.
    """
    rms = np.array([_rms(c) for c in chunks])
    # Considera solo chunk con segnale vero
    valid = rms > 1e-4
    if valid.sum() < 2:
        return chunks
    target = float(np.median(rms[valid]))
    if target <= 0:
        return chunks

    out: list[np.ndarray] = []
    for c, r in zip(chunks, rms):
        if r <= 1e-4:
            out.append(c)
            continue
        gain = target / r
        # Clamp ±6dB
        gain = float(np.clip(gain, 0.5, 2.0))
        out.append((c * gain).astype(np.float32))
    return out


def _rms(samples: np.ndarray) -> float:
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def _crossfade(a: np.ndarray, b: np.ndarray, n: int) -> np.ndarray:
    """
    Crossfade equal-power: out = a*cos(t) + b*sin(t) con t: 0→π/2.
    Se uno dei due è più corto di n, limita.
    """
    n = min(n, len(a), len(b))
    if n <= 0:
        return np.concatenate([a, b])

    t = np.linspace(0.0, np.pi / 2.0, n, dtype=np.float32)
    fade_out = np.cos(t)
    fade_in  = np.sin(t)

    head  = a[:-n]
    tail  = a[-n:] * fade_out + b[:n] * fade_in
    rest  = b[n:]
    return np.concatenate([head, tail, rest])


def _fade_in(samples: np.ndarray, sr: int, ms: int = 6) -> np.ndarray:
    n = min(int(ms / 1000.0 * sr), len(samples))
    if n <= 0:
        return samples
    out = samples.copy()
    out[:n] *= np.linspace(0.0, 1.0, n, dtype=np.float32)
    return out


def _fade_out(samples: np.ndarray, sr: int, ms: int = 6) -> np.ndarray:
    n = min(int(ms / 1000.0 * sr), len(samples))
    if n <= 0:
        return samples
    out = samples.copy()
    out[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    return out
