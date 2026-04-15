"""
XTTS v2 wrapper – TTS neurale multilingua con clonazione voce.
Richiede: pip install TTS
Il modello (~1.8 GB) viene scaricato automaticamente al primo avvio.
"""

import os
import threading

XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

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
                    # torchaudio 2.x: force soundfile backend (avoids torchcodec dependency)
                    try:
                        import torchaudio as _ta
                        _ta.set_audio_backend("soundfile")
                    except Exception:
                        pass
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

        kwargs: dict = {
            "text": text,
            "language": language,
            "file_path": output_path,
        }

        if reference_wav and os.path.exists(reference_wav):
            kwargs["speaker_wav"] = reference_wav
        else:
            kwargs["speaker"] = speaker_name or BUILTIN_SPEAKERS[0]

        cls._tts.tts_to_file(**kwargs)

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("XTTS v2 non ha prodotto il file audio")

    # ── Speaker list ───────────────────────────────────────────────────────────

    @classmethod
    def get_speakers(cls) -> list[str]:
        if cls._tts is not None and cls._tts.speakers:
            return cls._tts.speakers
        return BUILTIN_SPEAKERS
