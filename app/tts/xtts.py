"""
XTTS v2 wrapper – TTS neurale multilingua con clonazione voce.
Richiede: pip install TTS
Il modello (~1.8 GB) viene scaricato automaticamente al primo avvio.
"""

import os
import tempfile
import threading
import wave

import numpy as np

XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

# Soglia sopra la quale attiviamo il chunking automatico.
# XTTS v2 inizia a degradare (ripetizioni, glitch, troncamenti) oltre i
# ~250 caratteri per frase. Teniamo margine.
CHUNK_THRESHOLD_CHARS = 200

LANGUAGES = {
    "it": "Italiano",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "pt": "Português",
    "pl": "Polski",
    "ru": "Русский",
    "nl": "Nederlands",
    "cs": "Čeština",
    "zh-cn": "中文",
    "hu": "Magyar",
    "ko": "한국어",
    "ja": "日本語",
    "ar": "العربية",
    "hi": "हिंदी",
}

# Voci built-in del modello XTTS v2
BUILTIN_SPEAKERS = [
    # Femminile
    "Claribel Dervla", "Daisy Studious", "Gracie Wise", "Tammie Ema",
    "Alison Dietlinde", "Ana Florence", "Annmarie Nele", "Asya Anara",
    "Brenda Stern", "Gitta Nikolina", "Henriette Usha", "Sofia Hellen",
    "Tammy Grit", "Tanja Adelina", "Vjollca Johnnie", "Nova Hogarth",
    "Maja Ruoho", "Uta Obando", "Lidiya Szekeres", "Chandra MacFarland",
    "Szofi Granger", "Camilla Holmström", "Lilya Stainthorpe",
    "Zofija Kendrick", "Narelle Moon", "Barbora MacLean",
    "Alexandra Hisakawa", "Alma María", "Rosemary Okafor",
    # Maschile
    "Andrew Chipper", "Badr Odhiambo", "Dionisio Schuyler", "Royston Min",
    "Viktor Eka", "Abrahan Mack", "Adde Michal", "Baldur Sanjin",
    "Craig Gutsy", "Damien Black", "Gilberto Mathias", "Ilkin Urbano",
    "Kazuhiko Atallah", "Ludvig Milivoj", "Viktor Menelaos",
    "Zacharie Aimilios", "Luis Moray", "Marcos Rudaski",
]

# Voci consigliate per l'italiano (suonano meglio con lingua it)
RECOMMENDED_IT = [
    "Alma María", "Ana Florence", "Brenda Stern", "Gitta Nikolina",
    "Gilberto Mathias", "Damien Black", "Viktor Menelaos",
]


def _patch_torchaudio():
    """
    Sostituisce torchaudio.load con un'implementazione basata su soundfile,
    bypassando completamente torchcodec (richiede FFmpeg, non disponibile).
    Compatibile con torchaudio 2.x che ha rimosso set_audio_backend().
    """
    try:
        import soundfile as _sf
        import torch as _torch
        import torchaudio as _ta

        def _sf_load(uri, frame_offset=0, num_frames=-1,
                     normalize=True, channels_first=True,
                     format=None, backend=None):
            data, sr = _sf.read(str(uri), dtype="float32", always_2d=True)
            # soundfile → (frames, channels); torchaudio → (channels, frames)
            wav = _torch.from_numpy(data.T.copy())
            if frame_offset > 0:
                wav = wav[:, frame_offset:]
            if num_frames > 0:
                wav = wav[:, :num_frames]
            return wav, sr

        _ta.load = _sf_load
    except Exception:
        pass  # soundfile non installato: fallback al comportamento originale


class XTTSEngine:
    """
    Singleton per XTTS v2. Il modello viene caricato una sola volta
    in un thread di background e poi riutilizzato.
    """

    _lock = threading.Lock()
    _tts = None
    _loading = False
    _load_error: str | None = None

    # ── Disponibilità ─────────────────────────────────────────────────────────

    @classmethod
    def is_available(cls) -> bool:
        """Verifica se il pacchetto TTS è installato SENZA importarlo."""
        import importlib.util
        return importlib.util.find_spec("TTS") is not None

    @classmethod
    def is_loaded(cls) -> bool:
        return cls._tts is not None

    @classmethod
    def is_loading(cls) -> bool:
        return cls._loading

    @classmethod
    def load_error(cls) -> str | None:
        return cls._load_error

    # ── Caricamento modello ────────────────────────────────────────────────────

    @classmethod
    def load_model(cls, on_progress=None, on_done=None, on_error=None):
        """
        Carica il modello XTTS v2 in background.
        Se già caricato chiama subito on_done.
        """
        if cls._tts is not None:
            if on_done:
                on_done()
            return
        if cls._loading:
            return

        def _run():
            with cls._lock:
                if cls._tts is not None:
                    if on_done:
                        on_done()
                    return
                cls._loading = True
                cls._load_error = None
                try:
                    if on_progress:
                        on_progress("Caricamento modello XTTS v2… (può richiedere 1-2 min)")
                    # Patch torchaudio.load → soundfile (evita torchcodec/FFmpeg)
                    _patch_torchaudio()
                    # PyTorch 2.6+ fix: weights_only default changed to True,
                    # breaking Coqui TTS model loading. Restore False for trusted local files.
                    import torch as _torch
                    _orig_load = _torch.load
                    _torch.load = lambda *a, **kw: _orig_load(*a, **{**kw, "weights_only": False})
                    try:
                        from TTS.api import TTS
                        cls._tts = TTS(XTTS_MODEL)
                    finally:
                        _torch.load = _orig_load
                    if on_done:
                        on_done()
                except Exception as exc:
                    cls._load_error = str(exc)
                    if on_error:
                        on_error(str(exc))
                finally:
                    cls._loading = False

        threading.Thread(target=_run, daemon=True).start()

    # ── Generazione ────────────────────────────────────────────────────────────

    @classmethod
    def generate(
        cls,
        text: str,
        language: str,
        output_path: str,
        speaker_name: str | None = None,
        reference_wav: str | None = None,
    ):
        """
        Genera audio con XTTS v2.
        - reference_wav: path a un file WAV di ~6 sec per clonare la voce
        - speaker_name: una delle BUILTIN_SPEAKERS se non si clona
        """
        if cls._tts is None:
            raise RuntimeError(
                "Modello XTTS v2 non caricato. Premi 'Genera Audio' per avviare il caricamento."
            )

        # Assicura che torchaudio usi soundfile anche durante la generazione
        _patch_torchaudio()

        speaker_kwargs: dict = {}
        if reference_wav and os.path.exists(reference_wav):
            speaker_kwargs["speaker_wav"] = reference_wav
        else:
            speaker_kwargs["speaker"] = speaker_name or BUILTIN_SPEAKERS[0]

        # Chunking automatico per testi lunghi.
        # Per testi brevi il percorso è identico al comportamento originale.
        if len(text) <= CHUNK_THRESHOLD_CHARS:
            cls._tts.tts_to_file(
                text=text, language=language,
                file_path=output_path, **speaker_kwargs,
            )
        else:
            cls._generate_chunked(
                text=text, language=language,
                output_path=output_path, speaker_kwargs=speaker_kwargs,
            )

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("XTTS v2 non ha prodotto il file audio")

    # ── Generazione chunked ────────────────────────────────────────────────────

    @classmethod
    def _generate_chunked(cls, text: str, language: str,
                          output_path: str, speaker_kwargs: dict):
        """
        Genera testi lunghi chunk-by-chunk e concatena con pause adattive
        + crossfade equal-power. Vedi app/tts/chunker.py e app/audio/concat.py.
        """
        from app.tts.chunker import chunk_text
        from app.audio.concat import concat_chunks

        chunks = chunk_text(text)
        if not chunks:
            raise RuntimeError("Chunking ha prodotto zero segmenti.")

        wav_parts: list[np.ndarray] = []
        pauses_ms: list[int] = []
        sr_ref: int | None = None

        for i, chunk in enumerate(chunks):
            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix=f"xtts_chunk{i}_")
            os.close(fd)
            try:
                cls._tts.tts_to_file(
                    text=chunk["text"], language=language,
                    file_path=tmp, **speaker_kwargs,
                )
                samples, sr = _read_wav_mono(tmp)
                if sr_ref is None:
                    sr_ref = sr
                wav_parts.append(samples)
                if i < len(chunks) - 1:
                    pauses_ms.append(chunk["pause_ms"])
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)

        if not wav_parts or sr_ref is None:
            raise RuntimeError("Nessun chunk generato con successo.")

        combined = concat_chunks(
            wav_parts, sr=sr_ref, pauses_ms=pauses_ms,
            crossfade_ms=18, trim_silence=True, match_loudness=True,
        )
        _write_wav_mono(output_path, combined, sr_ref)

    # ── Speaker list ───────────────────────────────────────────────────────────

    @classmethod
    def get_speakers(cls) -> list[str]:
        if cls._tts is not None and cls._tts.speakers:
            return cls._tts.speakers
        return BUILTIN_SPEAKERS


# ── I/O WAV mono (usato dal chunking) ─────────────────────────────────────────

def _read_wav_mono(path: str) -> tuple[np.ndarray, int]:
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


def _write_wav_mono(path: str, samples: np.ndarray, sr: int):
    data = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(data.tobytes())
