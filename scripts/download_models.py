#!/usr/bin/env python3
"""
download_models.py — Scarica TUTTI i modelli neurali in models/ una volta sola.

Da quel momento VocalText funziona 100% offline senza connessione internet.
È l'unico script dell'app che si collega a internet — il main.py imposta
flag globali che impediscono ai vari motori ML di scaricare nulla a runtime.

Uso:
    python scripts/download_models.py                # tutto (~2.3 GB)
    python scripts/download_models.py --skip-piper   # solo XTTS+DFN (~1.85 GB)
    python scripts/download_models.py --skip-xtts    # niente XTTS (~350 MB)
    python scripts/download_models.py --piper-only   # solo Piper (~300 MB)

Tempi indicativi (connessione 50 Mbit/s):
    XTTS v2          ~1.8 GB     ≈ 5-8 min
    DeepFilterNet3   ~50  MB     ≈ 10-20 sec
    Piper voices     ~300 MB     ≈ 1-2 min  (10 voci)
"""
from __future__ import annotations
import argparse
import os
import sys
import urllib.request
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"

# Voci Piper preinstallate (lingue principali coperte da XTTS)
PIPER_VOICES = [
    "it_IT-paola-medium",
    "en_US-lessac-medium",
    "en_GB-alba-medium",
    "es_ES-davefx-medium",
    "fr_FR-siwis-medium",
    "de_DE-thorsten-medium",
    "pt_PT-tugão-medium",
    "pl_PL-mc_speech-medium",
    "ru_RU-irina-medium",
    "nl_NL-mls-medium",
]


def _hf_snapshot(repo_id: str, target: Path, label: str, size_hint: str) -> bool:
    target.mkdir(parents=True, exist_ok=True)
    if (target / ".complete").exists():
        print(f"✓ {label} già presente in {target} (skip)")
        return True
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("✗ Manca huggingface_hub. Installalo con:")
        print("    pip install huggingface_hub")
        return False
    print(f"→ Scarico {label} ({size_hint}) in {target}…")
    try:
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(target),
            local_dir_use_symlinks=False,
        )
    except Exception as exc:
        print(f"✗ Download fallito: {exc}")
        return False
    (target / ".complete").touch()
    print(f"✓ {label} pronto.")
    return True


def download_xtts() -> bool:
    return _hf_snapshot("coqui/XTTS-v2", MODELS / "xtts", "XTTS v2", "~1.8 GB")


def download_dfn() -> bool:
    return _hf_snapshot("Rikorose/DeepFilterNet3",
                        MODELS / "dfn", "DeepFilterNet3", "~50 MB")


def download_piper_voice(voice_id: str) -> bool:
    parts = voice_id.split("-")
    if len(parts) < 3:
        print(f"  ✗ ID voce non valido: {voice_id}")
        return False
    lang_full, speaker, quality = parts[0], parts[1], "-".join(parts[2:])
    lang_prefix = lang_full[:2]

    voice_dir = MODELS / voice_id
    voice_dir.mkdir(parents=True, exist_ok=True)

    base = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"{lang_prefix}/{lang_full}/{speaker}/{quality}")
    files = [f"{voice_id}.onnx", f"{voice_id}.onnx.json"]

    if all((voice_dir / f).exists() for f in files):
        print(f"  ✓ {voice_id} (già presente)")
        return True

    for fname in files:
        target = voice_dir / fname
        if target.exists():
            continue
        url = f"{base}/{fname}"
        print(f"  → {voice_id}/{fname}")
        try:
            urllib.request.urlretrieve(url, target)
        except Exception as exc:
            print(f"  ✗ Errore su {fname}: {exc}")
            return False
    print(f"  ✓ {voice_id}")
    return True


def download_all_piper() -> bool:
    print(f"→ Scarico voci Piper ({len(PIPER_VOICES)} voci, ~{30*len(PIPER_VOICES)} MB)")
    ok = True
    for vid in PIPER_VOICES:
        if not download_piper_voice(vid):
            ok = False
    return ok


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-piper", action="store_true",
                        help="Salta le voci Piper")
    parser.add_argument("--skip-xtts", action="store_true",
                        help="Salta XTTS v2")
    parser.add_argument("--skip-dfn", action="store_true",
                        help="Salta DeepFilterNet")
    parser.add_argument("--piper-only", action="store_true",
                        help="Solo voci Piper")
    args = parser.parse_args()

    # Sicurezza: lo script DEVE poter andare online — rimuovi flag offline
    for v in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ.pop(v, None)

    print("=" * 60)
    print("VocalText — download modelli (one-time setup)")
    print("=" * 60)
    print(f"Destinazione: {MODELS}")
    print()

    results = []
    if args.piper_only:
        results.append(("Piper voices", download_all_piper()))
    else:
        if not args.skip_xtts:
            results.append(("XTTS v2", download_xtts()))
            print()
        if not args.skip_dfn:
            results.append(("DeepFilterNet3", download_dfn()))
            print()
        if not args.skip_piper:
            results.append(("Piper voices", download_all_piper()))
            print()

    print("=" * 60)
    failed = [name for name, ok in results if not ok]
    if failed:
        print(f"✗ Setup INCOMPLETO. Falliti: {', '.join(failed)}")
        print("  Riesegui lo script per completare i mancanti.")
        sys.exit(1)
    print("✓ Setup completato. L'app può ora funzionare senza internet.")
    print("=" * 60)


if __name__ == "__main__":
    main()
