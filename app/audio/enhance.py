"""
Pulizia voce — rimuove rumore di fondo preservando il timbro originale.

Strategia di priorità:
  1. DeepFilterNet (neurale) se installato → migliore qualità in assoluto
  2. Pipeline DSP custom (sempre disponibile) — basata su numpy/scipy/
     noisereduce/pedalboard, già nelle nostre dipendenze

Filosofia: NIENTE EQ tonali (niente boost/cut di frequenze) per non
alterare la caratteristica della voce. Solo riduzione di ciò che voce
NON è: rumore di fondo, hiss, sibilanti eccessive, rumble.

Per evitare l'effetto "tubo metallico" (musical noise da gating
spettrale aggressivo) il segnale finale è un wet/dry blend: 82% di
pulito + 18% di originale. La piccola quota di "dry" preserva
l'ambienza naturale e maschera gli artefatti di gating spettrale.

Catena DSP (in ordine):
  1. DC remove
  2. HP 80Hz (rumble e DC residuo)
  3. Snapshot del segnale post-HP come "dry reference"
  4. Spectral gating moderato (noisereduce, prop_decrease 0.70)
  5. NoiseGate residuo dolce (pedalboard, ratio 3.5)
  6. De-esser leggerissimo
  7. Wet/dry blend con la dry reference
  8. LUFS normalize a -16 dB
  9. Fade in/out
"""

from __future__ import annotations
import wave
from pathlib import Path
import numpy as np

# Path del modello DeepFilterNet pre-scaricato (popolato dallo script
# scripts/download_models.py). Se assente, la pipeline DSP fa da fallback.
LOCAL_DFN_DIR = Path(__file__).resolve().parents[2] / "models" / "dfn"


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

def clean_voice(input_path: str, output_path: str | None = None, *,
                denoise_strength: float = 0.70,
                dry_mix: float = 0.18,
                gate: str = "normal") -> bool:
    """
    Pulisce l'audio rimuovendo rumore di fondo. Preserva il timbro.
    Se output_path è None sovrascrive il file sorgente.
    Ritorna True se la pulizia è andata a buon fine.

    denoise_strength : 0.30–0.92  (percentuale di rumore rimosso)
    dry_mix          : 0.00–0.40  (quota di segnale originale nel blend)
    gate             : "off" | "gentle" | "normal" | "strong"
    """
    if output_path is None:
        output_path = input_path

    samples, sr = _read_wav(input_path)
    if not _is_valid(samples):
        return False

    try:
        cleaned = _clean(samples.copy(), sr,
                         denoise_strength=denoise_strength,
                         dry_mix=dry_mix, gate=gate)
        if _is_valid(cleaned):
            _write_wav(output_path, cleaned, sr)
            return True
        _write_wav(output_path, samples, sr)
        return False
    except Exception:
        _write_wav(output_path, samples, sr)
        return False


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def _clean(samples: np.ndarray, sr: int, *,
           denoise_strength: float, dry_mix: float, gate: str) -> np.ndarray:
    """Tenta neurale, poi fallback DSP."""
    try:
        result = _clean_neural(samples, sr)
        if _is_valid(result):
            # DFN è già naturale: usiamo metà del dry_mix richiesto
            return _post_process(result, samples, sr, mix=dry_mix * 0.55)
    except (ImportError, Exception):
        pass
    return _clean_dsp(samples, sr,
                      denoise_strength=denoise_strength,
                      dry_mix=dry_mix, gate=gate)


def _post_process(wet: np.ndarray, dry: np.ndarray, sr: int,
                  mix: float) -> np.ndarray:
    """Blend wet/dry, normalizza loudness, applica fade in/out."""
    out = _blend_with_dry(wet, dry, mix=mix)
    out = _lufs_normalize(out, sr, target=-16.0)
    return _fade(np.clip(out, -1.0, 1.0).astype(np.float32), sr)


def _blend_with_dry(wet: np.ndarray, dry: np.ndarray,
                    mix: float = 0.18) -> np.ndarray:
    """
    Mescola una piccola quota di segnale originale (dry) con il pulito (wet).
    Il dry "ridà" l'ambienza naturale e maschera gli artefatti di gating
    spettrale (effetto "tubo metallico" / musical noise).
    """
    n = min(len(wet), len(dry))
    if n == 0 or mix <= 0:
        return wet.astype(np.float32)
    return ((1.0 - mix) * wet[:n] + mix * dry[:n]).astype(np.float32)


# ── Path neurale (DeepFilterNet, opzionale) ───────────────────────────────────

def _patch_torchaudio_for_dfn() -> None:
    """Inject torchaudio.backend stub so deepfilternet imports under torchaudio>=2.1."""
    import sys, types
    if "torchaudio.backend" in sys.modules:
        return
    try:
        import torchaudio  # noqa: F401
    except ImportError:
        return
    stub = types.ModuleType("torchaudio.backend")
    stub.get_audio_backend   = lambda: "soundfile"   # type: ignore[attr-defined]
    stub.set_audio_backend   = lambda _b: None        # type: ignore[attr-defined]
    stub.list_audio_backends = lambda: ["soundfile"]  # type: ignore[attr-defined]
    utils_stub = types.ModuleType("torchaudio.backend.utils")
    utils_stub.get_audio_backend   = stub.get_audio_backend    # type: ignore[attr-defined]
    utils_stub.set_audio_backend   = stub.set_audio_backend    # type: ignore[attr-defined]
    utils_stub.list_audio_backends = stub.list_audio_backends  # type: ignore[attr-defined]
    stub.utils = utils_stub  # type: ignore[attr-defined]
    sys.modules["torchaudio.backend"]       = stub
    sys.modules["torchaudio.backend.utils"] = utils_stub
    try:
        torchaudio.backend = stub  # type: ignore[attr-defined]
    except AttributeError:
        pass


def _clean_neural(samples: np.ndarray, sr: int) -> np.ndarray:
    """
    Usa DeepFilterNet se installato (pip install deepfilternet).
    Modello ~50MB, gira su CPU, qualità professionale.
    Lavora a 48kHz internamente — resampla in/out.
    """
    _patch_torchaudio_for_dfn()
    from df.enhance import enhance, init_df  # type: ignore
    import torch as _torch

    if not LOCAL_DFN_DIR.exists():
        raise RuntimeError(
            f"DeepFilterNet non trovato in {LOCAL_DFN_DIR}. "
            "Scarica con: python scripts/download_models.py")

    target_sr = 48000
    audio = samples.copy()
    if sr != target_sr:
        audio = _resample(audio, sr, target_sr)

    model, df_state, _ = init_df(model_base_dir=str(LOCAL_DFN_DIR))
    tensor = _torch.from_numpy(audio).unsqueeze(0)
    enhanced = enhance(model, df_state, tensor)
    out = enhanced.squeeze(0).cpu().numpy().astype(np.float32)

    if sr != target_sr:
        out = _resample(out, target_sr, sr)
    return out


# ── Path DSP custom (sempre disponibile) ──────────────────────────────────────

def _clean_dsp(samples: np.ndarray, sr: int, *,
               denoise_strength: float, dry_mix: float, gate: str) -> np.ndarray:
    samples = _dc_remove(samples)
    samples = _highpass_80(samples, sr)
    dry = samples.copy()
    samples = _spectral_denoise_aggressive(samples, sr, prop_decrease=denoise_strength)
    if gate != "off":
        samples = _noise_gate(samples, sr, preset=gate)
    samples = _light_deesser(samples, sr)
    return _post_process(samples, dry, sr, mix=dry_mix)


def _dc_remove(samples: np.ndarray) -> np.ndarray:
    if len(samples) == 0:
        return samples
    return (samples - float(np.mean(samples))).astype(np.float32)


def _highpass_80(samples: np.ndarray, sr: int) -> np.ndarray:
    try:
        from scipy import signal
        sos = signal.butter(6, 80.0 / (sr / 2), btype="high", output="sos")
        return signal.sosfilt(sos, samples).astype(np.float32)
    except ImportError:
        return samples


def _spectral_denoise_aggressive(samples: np.ndarray, sr: int,
                                  prop_decrease: float = 0.70) -> np.ndarray:
    """
    Riduzione rumore "soave": efficace ma musicalmente rispettosa.
    - Non-stazionaria → si adatta a rumori variabili
    - prop_decrease 0.70 → lascia ~30% di floor residuo che nasconde
      gli artefatti tonali ("musical noise") tipici del gating spettrale
    - n_fft 2048 + win 1024 → risoluzione frequenziale doppia rispetto
      a prima = meno modulazione delle armoniche vocali
    - Smoothing freq/tempo più ampio → mascheramento naturale, niente
      effetto "tubo metallico"
    """
    try:
        import noisereduce as nr
    except ImportError:
        return samples

    try:
        return nr.reduce_noise(
            y=samples,
            sr=sr,
            stationary=False,
            prop_decrease=float(prop_decrease),
            n_fft=2048,
            win_length=1024,
            freq_mask_smooth_hz=800,
            time_mask_smooth_ms=100,
        ).astype(np.float32)
    except Exception:
        # Fallback stazionario se non-stazionario fallisce
        try:
            return nr.reduce_noise(
                y=samples, sr=sr,
                stationary=True,
                prop_decrease=0.65,
            ).astype(np.float32)
        except Exception:
            return samples


_GATE_PRESETS: dict[str, dict] = {
    "gentle": dict(ratio=2.0, attack_ms=8.0, release_ms=300.0, floor_offset=10),
    "normal": dict(ratio=3.5, attack_ms=5.0, release_ms=200.0, floor_offset=8),
    "strong": dict(ratio=6.0, attack_ms=3.0, release_ms=120.0, floor_offset=5),
}


def _noise_gate(samples: np.ndarray, sr: int, preset: str = "normal") -> np.ndarray:
    """Gate sui residui di hiss con intensità configurabile."""
    try:
        from pedalboard import Pedalboard, NoiseGate
    except ImportError:
        return samples

    p = _GATE_PRESETS.get(preset, _GATE_PRESETS["normal"])
    abs_s = np.abs(samples)
    if len(abs_s) < sr:
        return samples
    win  = max(1, int(0.020 * sr))
    env  = _moving_avg(abs_s ** 2, win)
    floor_lin = float(np.percentile(np.sqrt(env + 1e-12), 12))
    floor_db  = 20 * np.log10(max(floor_lin, 1e-6))
    threshold_db = max(-60.0, min(-30.0, floor_db + p["floor_offset"]))

    board = Pedalboard([
        NoiseGate(threshold_db=threshold_db, ratio=p["ratio"],
                  attack_ms=p["attack_ms"], release_ms=p["release_ms"])
    ])
    audio = samples[np.newaxis, :]
    return board(audio, sr)[0].astype(np.float32)


def _light_deesser(samples: np.ndarray, sr: int,
                   threshold: float = 0.42, ratio: float = 2.5) -> np.ndarray:
    """De-esser leggero — rimuove le sibilanti accentuate dal denoise."""
    try:
        from scipy import signal
    except ImportError:
        return samples

    nyq = sr / 2.0
    f_lo, f_hi = 5500.0, min(9000.0, nyq * 0.95)
    if f_lo >= f_hi:
        return samples

    sos = signal.butter(4, [f_lo / nyq, f_hi / nyq],
                        btype="band", output="sos")
    sib = signal.sosfilt(sos, samples).astype(np.float32)

    win = max(1, int(0.005 * sr))
    env = np.sqrt(_moving_avg(sib ** 2, win) + 1e-12)

    gr = np.ones_like(env, dtype=np.float32)
    over = env > threshold
    if np.any(over):
        excess_db = 20.0 * np.log10(env[over] / threshold)
        red_db = excess_db * (1.0 - 1.0 / ratio)
        gr[over] = (10.0 ** (-red_db / 20.0)).astype(np.float32)
    gr = _moving_avg(gr, win)

    attenuation = sib * (1.0 - gr)
    return (samples - attenuation).astype(np.float32)


def _lufs_normalize(samples: np.ndarray, sr: int,
                    target: float = -16.0) -> np.ndarray:
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(sr)
        loudness = meter.integrated_loudness(samples)
        if loudness > -70.0 and np.isfinite(loudness):
            out = pyln.normalize.loudness(samples, loudness, target)
            if _is_valid(out):
                return out.astype(np.float32)
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _moving_avg(x: np.ndarray, win: int) -> np.ndarray:
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


def _resample(samples: np.ndarray, src_sr: int, tgt_sr: int) -> np.ndarray:
    """Resample alta qualità con scipy.signal.resample_poly."""
    if src_sr == tgt_sr:
        return samples
    from scipy import signal
    from math import gcd
    g = gcd(src_sr, tgt_sr)
    up   = tgt_sr // g
    down = src_sr // g
    return signal.resample_poly(samples, up, down).astype(np.float32)
