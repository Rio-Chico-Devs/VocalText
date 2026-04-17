"""
Effetti sonori inline per VocalText.

Tag nel testo come [risata], [pausa], [sospiro] vengono intercettati,
sostituiti con WAV audio generati dal motore TTS locale e cachati in effects/.
Tutto funziona offline – nessun download esterno.

Esempio:
    "Ciao! [risata] Come stai? [pausa] Benissimo!"
"""

import os
import re
import wave
import tempfile
import threading
import numpy as np
from pathlib import Path


# ── Catalogo tag ───────────────────────────────────────────────────────────────

EFFECTS: dict[str, tuple[str, str | None]] = {
    # tag: (descrizione UI, testo da sintetizzare  oppure None=silenzio)
    "pausa":        ("Pausa breve 0.5s",    None),
    "pausa_lunga":  ("Pausa lunga 1.5s",    None),
    "risata":       ("Risata leggera",      "heh heh heh"),
    "risata_forte": ("Risata forte",        "ha ha ha ha ha"),
    "risatina":     ("Risatina",            "hi hi hi hi"),
    "sospiro":      ("Sospiro",             "aaahh"),
    "respiro":      ("Respiro",             "mm-hmm"),
    "esitazione":   ("Uhm…",               "uhm"),
    "sorpresa":     ("Oh!",                 "oh!"),
    "tosse":        ("Colpo di tosse",      "ehm ehm"),
}

PAUSE_DURATIONS = {"pausa": 0.5, "pausa_lunga": 1.5}

TAG_RE = re.compile(
    r"\[(" + "|".join(re.escape(k) for k in EFFECTS) + r")\]",
    re.IGNORECASE,
)

CACHE_DIR = Path(__file__).parent.parent.parent / "effects"


# ── API pubblica ───────────────────────────────────────────────────────────────

def has_tags(text: str) -> bool:
    return bool(TAG_RE.search(text))


def get_tags_help() -> dict[str, str]:
    """Ritorna {tag: descrizione} per il pannello UI."""
    return {k: v[0] for k, v in EFFECTS.items()}


def build_audio(
    text: str,
    voice,
    engine,
    speed: float = 1.0,
    volume: float = 1.0,
    language: str = "it",
    reference_wav: str | None = None,
    output_path: str | None = None,
    polish: bool = True,
    on_done=None,
    on_error=None,
):
    """
    Parsa il testo, genera TTS per le parti testuali, inserisce gli effetti,
    concatena tutto e chiama on_done(path) o on_error(msg).
    Gira in un thread separato.
    """
    def _run():
        try:
            result = _build(
                text, voice, engine, speed, volume,
                language, reference_wav, output_path, polish,
            )
            if on_done:
                on_done(result)
        except Exception as exc:
            if on_error:
                on_error(str(exc))

    threading.Thread(target=_run, daemon=True).start()


# ── Internals ──────────────────────────────────────────────────────────────────

def _build(text, voice, engine, speed, volume, language,
           reference_wav, output_path, polish) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    segments = _parse(text)
    parts: list[np.ndarray] = []
    sr = 22050

    for kind, content in segments:
        if kind == "text" and content.strip():
            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="vt_seg_")
            os.close(fd)
            try:
                _generate_sync(engine, content, voice, speed, volume,
                                language, reference_wav, tmp)
                chunk, sr = _read_wav(tmp)
                parts.append(chunk)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)

        elif kind == "effect":
            tag = content.lower()
            gen_text = EFFECTS.get(tag, (None, None))[1]

            if gen_text is None:
                # Silenzio
                dur = PAUSE_DURATIONS.get(tag, 0.5)
                parts.append(np.zeros(int(dur * sr), dtype=np.float32))
            else:
                cache_file = CACHE_DIR / f"{tag}.wav"
                if not cache_file.exists():
                    _generate_effect_wav(engine, voice, language,
                                         gen_text, str(cache_file))
                if cache_file.exists():
                    chunk, _ = _read_wav(str(cache_file))
                    pad = np.zeros(int(0.08 * sr), dtype=np.float32)
                    parts.extend([pad, chunk, pad])

    if not parts:
        raise RuntimeError("Nessun audio generato dai segmenti.")

    combined = np.concatenate(parts)

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".wav", prefix="vocaltext_")
        os.close(fd)

    _write_wav(output_path, combined, sr)

    if polish:
        try:
            from app.audio.polish import polish as _polish
            _polish(output_path)
        except Exception:
            pass

    return output_path


def _parse(text: str) -> list[tuple[str, str]]:
    """Ritorna lista di ('text', contenuto) o ('effect', tag)."""
    result = []
    last = 0
    for m in TAG_RE.finditer(text):
        before = text[last:m.start()]
        if before:
            result.append(("text", before))
        result.append(("effect", m.group(1)))
        last = m.end()
    if text[last:]:
        result.append(("text", text[last:]))
    return result


def _generate_sync(engine, text, voice, speed, volume,
                    language, reference_wav, output_path):
    """Genera TTS in modo sincrono (blocca il thread corrente)."""
    done  = threading.Event()
    error = []

    engine.generate(
        text=text, voice=voice, speed=speed, volume=volume,
        language=language, reference_wav=reference_wav,
        output_path=output_path,
        on_done=lambda _: done.set(),
        on_error=lambda e: (error.append(e), done.set()),
    )
    done.wait(timeout=300)
    if error:
        raise RuntimeError(error[0])


def _generate_effect_wav(engine, voice, language, text, output_path):
    """Genera l'effetto e lo salva nella cache. Ignora errori silenziosamente."""
    try:
        _generate_sync(engine, text, voice, 1.0, 1.0, language, None, output_path)
    except Exception:
        pass


# ── WAV I/O ────────────────────────────────────────────────────────────────────

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
