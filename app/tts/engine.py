"""
TTS Engine – offline text-to-speech backend.

Priority chain:
  1. Piper TTS  (neural, high quality – needs .onnx model in models/)
  2. pyttsx3    (system voices: espeak-ng on Linux, SAPI on Windows, nsss on macOS)
"""

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


# ── Voice definitions ──────────────────────────────────────────────────────────

PIPER_CATALOG = [
    dict(id="it_IT-paola-medium",    name="Paola",    lang="it", gender="female", quality="medium", size_mb=63),
    dict(id="it_IT-riccardo-x_low",  name="Riccardo", lang="it", gender="male",   quality="low",    size_mb=24),
    dict(id="en_US-lessac-medium",   name="Lessac",   lang="en", gender="female", quality="medium", size_mb=63),
    dict(id="en_US-ryan-high",       name="Ryan",     lang="en", gender="male",   quality="high",   size_mb=121),
    dict(id="en_GB-alan-medium",     name="Alan",     lang="en", gender="male",   quality="medium", size_mb=63),
    dict(id="de_DE-thorsten-medium", name="Thorsten", lang="de", gender="male",   quality="medium", size_mb=63),
    dict(id="fr_FR-upmc-medium",     name="UPMC",     lang="fr", gender="male",   quality="medium", size_mb=63),
    dict(id="es_ES-sharvard-medium", name="Sharvard", lang="es", gender="male",   quality="medium", size_mb=63),
]


class Voice:
    """A voice usable by the TTS engine."""

    def __init__(self, id, name, lang, gender, quality, engine, onnx_path=None, config_path=None, system_id=None):
        self.id = id
        self.name = name
        self.lang = lang
        self.gender = gender
        self.quality = quality          # "high" | "medium" | "low"
        self.engine = engine            # "piper" | "pyttsx3"
        self.onnx_path = onnx_path      # Piper only
        self.config_path = config_path  # Piper only
        self.system_id = system_id      # pyttsx3 only

    def __repr__(self):
        return f"<Voice {self.name} [{self.engine}/{self.quality}]>"


class TTSEngine:
    """Offline TTS engine. Thread-safe: generate() runs in background threads."""

    def __init__(self, models_dir: Path | None = None):
        self.models_dir = models_dir or (Path(__file__).parent.parent.parent / "models")
        self.models_dir.mkdir(parents=True, exist_ok=True)

        self._piper_bin: str | None = self._find_piper()
        self._pyttsx3_available = self._check_pyttsx3()
        self._system_voices: list[Voice] = []
        self._voices_loaded = False

    # ── Engine detection ───────────────────────────────────────────────────────

    def _find_piper(self) -> str | None:
        # 1. Local bin/ directory (bundled)
        local = Path(__file__).parent.parent.parent / "bin" / "piper"
        if local.exists():
            return str(local)
        # 2. System PATH
        return shutil.which("piper")

    def _check_pyttsx3(self) -> bool:
        try:
            import pyttsx3  # noqa: F401
            return True
        except ImportError:
            return False

    def has_piper(self) -> bool:
        return self._piper_bin is not None

    def has_pyttsx3(self) -> bool:
        return self._pyttsx3_available

    def is_ready(self) -> bool:
        return self.has_piper() or self.has_pyttsx3()

    def status(self) -> tuple[str, str]:
        """Returns (level, message) where level is 'ok'|'warn'|'error'."""
        if self.has_piper() and self.get_piper_voices():
            return "ok", "Piper TTS – qualità neurale"
        if self.has_pyttsx3():
            return "warn", "pyttsx3 – voci di sistema"
        return "error", "Nessun motore TTS trovato"

    # ── Voice listing ──────────────────────────────────────────────────────────

    def get_all_voices(self) -> list[Voice]:
        voices: list[Voice] = []
        voices.extend(self.get_piper_voices())
        voices.extend(self.get_system_voices())
        return voices

    def get_piper_voices(self) -> list[Voice]:
        """Scan models/ for installed Piper .onnx models."""
        found: list[Voice] = []
        for entry in sorted(self.models_dir.iterdir()) if self.models_dir.exists() else []:
            if not entry.is_dir():
                continue
            for onnx in sorted(entry.glob("*.onnx")):
                config = onnx.with_suffix(".onnx.json")
                if not config.exists():
                    continue
                # Try to match with catalog metadata
                meta = next((v for v in PIPER_CATALOG if v["id"] == entry.name), None)
                name = meta["name"] if meta else _format_model_name(entry.name)
                lang = meta["lang"] if meta else entry.name.split("_")[0]
                gender = meta.get("gender", "neutral") if meta else "neutral"
                quality = meta.get("quality", "medium") if meta else "medium"
                found.append(Voice(
                    id=f"piper:{entry.name}",
                    name=name,
                    lang=lang,
                    gender=gender,
                    quality=quality,
                    engine="piper",
                    onnx_path=str(onnx),
                    config_path=str(config),
                ))
        return found

    def get_system_voices(self) -> list[Voice]:
        """Fetch voices from pyttsx3 (espeak / SAPI / nsss)."""
        if not self._pyttsx3_available:
            return []
        if self._voices_loaded:
            return self._system_voices

        try:
            import pyttsx3
            engine = pyttsx3.init()
            raw = engine.getProperty("voices") or []
            engine.stop()
            del engine

            result: list[Voice] = []
            for v in raw:
                lang = _lang_from_pyttsx3(v)
                result.append(Voice(
                    id=f"sys:{v.id}",
                    name=_clean_voice_name(v.name),
                    lang=lang,
                    gender=_gender_from_pyttsx3(v),
                    quality="low",
                    engine="pyttsx3",
                    system_id=v.id,
                ))
            self._system_voices = result
        except Exception:
            self._system_voices = []

        self._voices_loaded = True
        return self._system_voices

    # ── Generation ─────────────────────────────────────────────────────────────

    def generate(
        self,
        text: str,
        voice: Voice,
        speed: float = 1.0,
        volume: float = 1.0,
        output_path: str | None = None,
        on_done=None,
        on_error=None,
    ):
        """Generate audio asynchronously. Calls on_done(path) or on_error(msg)."""
        if not output_path:
            fd, output_path = tempfile.mkstemp(suffix=".wav", prefix="vocaltext_")
            os.close(fd)

        def _run():
            try:
                if voice.engine == "piper":
                    self._generate_piper(text, voice, speed, output_path)
                else:
                    self._generate_pyttsx3(text, voice, speed, volume, output_path)
                if on_done:
                    on_done(output_path)
            except Exception as exc:
                if on_error:
                    on_error(str(exc))

        threading.Thread(target=_run, daemon=True).start()

    def _generate_piper(self, text: str, voice: Voice, speed: float, output_path: str):
        if not self._piper_bin:
            raise RuntimeError("Piper non trovato nel sistema")
        if not voice.onnx_path or not os.path.exists(voice.onnx_path):
            raise RuntimeError(f"Modello Piper non trovato: {voice.onnx_path}")

        length_scale = str(round(1.0 / max(speed, 0.1), 3))
        cmd = [
            self._piper_bin,
            "--model",       voice.onnx_path,
            "--config",      voice.config_path,
            "--output_file", output_path,
            "--length_scale", length_scale,
        ]
        proc = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Piper error: {proc.stderr.decode(errors='replace')}")
        if not os.path.exists(output_path):
            raise RuntimeError("Piper non ha prodotto il file audio")

    def _generate_pyttsx3(self, text: str, voice: Voice, speed: float, volume: float, output_path: str):
        import pyttsx3
        engine = pyttsx3.init()
        try:
            if voice.system_id:
                engine.setProperty("voice", voice.system_id)
            engine.setProperty("rate", int(200 * speed))
            engine.setProperty("volume", max(0.0, min(1.0, volume)))
            engine.save_to_file(text, output_path)
            engine.runAndWait()
        finally:
            engine.stop()

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("pyttsx3 non ha prodotto il file audio.\n"
                               "Verifica che espeak-ng sia installato (Linux: sudo apt install espeak-ng)")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_model_name(dir_name: str) -> str:
    parts = dir_name.split("-")
    if len(parts) >= 2:
        return parts[1].capitalize()
    return dir_name

def _clean_voice_name(raw: str) -> str:
    for prefix in ("Microsoft ", "Apple ", "IVONA ", "eSpeak "):
        raw = raw.replace(prefix, "")
    return raw.strip()

def _lang_from_pyttsx3(v) -> str:
    langs = getattr(v, "languages", []) or []
    for lang in langs:
        if isinstance(lang, bytes):
            lang = lang.decode("utf-8", errors="ignore")
        if lang:
            return lang[:2].lower()
    name = (v.name or "").lower()
    for code in ("it", "en", "de", "fr", "es", "pt"):
        if code in name:
            return code
    return "??"

def _gender_from_pyttsx3(v) -> str:
    g = str(getattr(v, "gender", "") or "").lower()
    if "female" in g or "woman" in g:
        return "female"
    if "male" in g or "man" in g:
        return "male"
    return "neutral"
