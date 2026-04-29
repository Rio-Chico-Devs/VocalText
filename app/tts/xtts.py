"""
XTTS v2 wrapper – TTS neurale multilingua con clonazione voce.
Richiede: pip install TTS

Il modello (~1.8 GB) DEVE essere stato pre-scaricato in ./models/xtts/
prima del primo utilizzo. L'app non scarica nulla a runtime — esegui:
    python scripts/download_models.py
"""

import os
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

LOCAL_XTTS_DIR = Path(__file__).resolve().parents[2] / "models" / "xtts"

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

BUILTIN_SPEAKERS = [
    "Claribel Dervla", "Daisy Studious", "Gracie Wise", "Tammie Ema",
    "Alison Dietlinde", "Ana Florence", "Annmarie Nele", "Asya Anara",
    "Brenda Stern", "Gitta Nikolina", "Henriette Usha", "Sofia Hellen",
    "Tammy Grit", "Tanja Adelina", "Vjollca Johnnie", "Nova Hogarth",
    "Maja Ruoho", "Uta Obando", "Lidiya Szekeres", "Chandra MacFarland",
    "Szofi Granger", "Camilla Holmström", "Lilya Stainthorpe",
    "Zofija Kendrick", "Narelle Moon", "Barbora MacLean",
    "Alexandra Hisakawa", "Alma María", "Rosemary Okafor",
    "Andrew Chipper", "Badr Odhiambo", "Dionisio Schuyler", "Royston Min",
    "Viktor Eka", "Abrahan Mack", "Adde Michal", "Baldur Sanjin",
    "Craig Gutsy", "Damien Black", "Gilberto Mathias", "Ilkin Urbano",
    "Kazuhiko Atallah", "Ludvig Milivoj", "Viktor Menelaos",
    "Zacharie Aimilios", "Luis Moray", "Marcos Rudaski",
]

RECOMMENDED_IT = [
    "Alma María", "Ana Florence", "Brenda Stern", "Gitta Nikolina",
    "Gilberto Mathias", "Damien Black", "Viktor Menelaos",
]


def _patch_torchaudio():
    """
    Sostituisce torchaudio.load con un'implementazione basata su soundfile,
    bypassando completamente torchcodec (richiede FFmpeg, non disponibile).
    """
    try:
        import soundfile as _sf
        import torch as _torch
        import torchaudio as _ta

        def _sf_load(uri, frame_offset=0, num_frames=-1,
                     normalize=True, channels_first=True,
                     format=None, backend=None):
            data, sr = _sf.read(str(uri), dtype="float32", always_2d=True)
            wav = _torch.from_numpy(data.T.copy())
            if frame_offset > 0:
                wav = wav[:, frame_offset:]
            if num_frames > 0:
                wav = wav[:, :num_frames]
            return wav, sr

        _ta.load = _sf_load
    except Exception:
        pass


def _torch_load_unsafe(*args, **kwargs):
    """torch.load con weights_only=False per i modelli Coqui (non dati da terzi)."""
    import torch
    kwargs.setdefault("weights_only", False)
    return torch._orig_load_unsafe(*args, **kwargs)  # type: ignore[attr-defined]


class XTTSEngine:
    """
    Singleton per XTTS v2 caricato via API diretta Xtts/XttsConfig.
    Garantisce corretta inizializzazione del speaker encoder per la clonazione.
    """

    _lock     = threading.Lock()
    _model    = None   # Xtts instance
    _config   = None   # XttsConfig instance
    _sr       = 24000  # sample rate output XTTS v2
    _loading  = False
    _load_error: str | None = None

    # ── Disponibilità ─────────────────────────────────────────────────────────

    @classmethod
    def is_available(cls) -> bool:
        import importlib.util
        return importlib.util.find_spec("TTS") is not None

    @classmethod
    def is_loaded(cls) -> bool:
        return cls._model is not None

    @classmethod
    def is_loading(cls) -> bool:
        return cls._loading

    @classmethod
    def load_error(cls) -> str | None:
        return cls._load_error

    # ── Caricamento modello ────────────────────────────────────────────────────

    @classmethod
    def load_model(cls, on_progress=None, on_done=None, on_error=None):
        if cls._model is not None:
            if on_done:
                on_done()
            return
        if cls._loading:
            return

        def _run():
            with cls._lock:
                if cls._model is not None:
                    if on_done:
                        on_done()
                    return
                cls._loading = True
                cls._load_error = None
                try:
                    if on_progress:
                        on_progress("Caricamento modello XTTS v2… (può richiedere 1-2 min)")

                    _patch_torchaudio()

                    cfg_path = LOCAL_XTTS_DIR / "config.json"
                    if not cfg_path.exists():
                        raise RuntimeError(
                            "Modello XTTS v2 non trovato in "
                            f"{LOCAL_XTTS_DIR}.\n"
                            "Esegui una sola volta:\n"
                            "    python scripts/download_models.py")

                    import torch as _torch
                    _orig_load = _torch.load
                    _torch.load = lambda *a, **kw: _orig_load(
                        *a, **{**kw, "weights_only": False})
                    try:
                        from TTS.tts.configs.xtts_config import XttsConfig
                        from TTS.tts.models.xtts import Xtts

                        config = XttsConfig()
                        config.load_json(str(cfg_path))

                        model = Xtts.init_from_config(config)
                        model.load_checkpoint(
                            config,
                            checkpoint_dir=str(LOCAL_XTTS_DIR),
                            eval=True,
                        )
                        model.eval()

                        cls._model  = model
                        cls._config = config
                        try:
                            cls._sr = config.audio.output_sample_rate
                        except AttributeError:
                            cls._sr = 24000
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
        if cls._model is None:
            raise RuntimeError(
                "Modello XTTS v2 non caricato. Premi 'Genera Audio' per avviare il caricamento.")

        _patch_torchaudio()

        gpt_cond, spk_emb = cls._get_conditioning(reference_wav, speaker_name)

        if len(text) <= CHUNK_THRESHOLD_CHARS:
            wav = cls._infer(text, language, gpt_cond, spk_emb)
            _write_wav_mono(output_path, wav, cls._sr)
        else:
            cls._generate_chunked(text, language, output_path, gpt_cond, spk_emb)

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("XTTS v2 non ha prodotto il file audio")

    # ── Conditioning ───────────────────────────────────────────────────────────

    @classmethod
    def _get_conditioning(cls, reference_wav, speaker_name):
        """Restituisce (gpt_cond_latent, speaker_embedding) da ref audio o speaker built-in."""
        import torch
        if reference_wav and os.path.exists(reference_wav):
            with torch.no_grad():
                gpt_cond, spk_emb = cls._model.get_conditioning_latents(
                    audio_path=[reference_wav])
            return gpt_cond, spk_emb

        # Voce built-in → legge embeddings pre-calcolati da speakers_xtts.pth
        speakers_path = LOCAL_XTTS_DIR / "speakers_xtts.pth"
        if speakers_path.exists():
            speakers = torch.load(str(speakers_path), weights_only=False)
            name = speaker_name or BUILTIN_SPEAKERS[0]
            if name in speakers:
                spk = speakers[name]
                return spk["gpt_cond_latent"], spk["speaker_embedding"]

        raise RuntimeError(
            f"Speaker '{speaker_name}' non trovato. "
            "Seleziona un audio di riferimento oppure scegli una voce built-in.")

    # ── Inference ──────────────────────────────────────────────────────────────

    @classmethod
    def _infer(cls, text: str, language: str,
               gpt_cond, spk_emb) -> np.ndarray:
        import torch
        with torch.no_grad():
            out = cls._model.inference(
                text=text,
                language=language,
                gpt_cond_latent=gpt_cond,
                speaker_embedding=spk_emb,
            )
        wav = out["wav"]
        if isinstance(wav, torch.Tensor):
            wav = wav.squeeze().cpu().numpy()
        return np.asarray(wav, dtype=np.float32)

    # ── Chunked generation ─────────────────────────────────────────────────────

    @classmethod
    def _generate_chunked(cls, text: str, language: str, output_path: str,
                          gpt_cond, spk_emb):
        from app.tts.chunker import chunk_text
        from app.audio.concat import concat_chunks

        chunks = chunk_text(text)
        if not chunks:
            raise RuntimeError("Chunking ha prodotto zero segmenti.")

        wav_parts: list[np.ndarray] = []
        pauses_ms: list[int] = []

        for i, chunk in enumerate(chunks):
            wav = cls._infer(chunk["text"], language, gpt_cond, spk_emb)
            wav_parts.append(wav)
            if i < len(chunks) - 1:
                pauses_ms.append(chunk["pause_ms"])

        if not wav_parts:
            raise RuntimeError("Nessun chunk generato con successo.")

        combined = concat_chunks(
            wav_parts, sr=cls._sr, pauses_ms=pauses_ms,
            crossfade_ms=18, trim_silence=True, match_loudness=True,
        )
        _write_wav_mono(output_path, combined, cls._sr)

    # ── Speaker list ───────────────────────────────────────────────────────────

    @classmethod
    def get_speakers(cls) -> list[str]:
        if cls._model is not None:
            speakers_path = LOCAL_XTTS_DIR / "speakers_xtts.pth"
            if speakers_path.exists():
                try:
                    import torch
                    speakers = torch.load(str(speakers_path), weights_only=False)
                    return list(speakers.keys())
                except Exception:
                    pass
        return BUILTIN_SPEAKERS


# ── I/O WAV mono ───────────────────────────────────────────────────────────────

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
