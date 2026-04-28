#!/usr/bin/env python3
"""
VocalText – app desktop offline text-to-speech.
Avvio: python main.py
"""

# ─────────────────────────────────────────────────────────────────────────────
# Modalità OFFLINE forzata: queste variabili impediscono a HuggingFace Hub,
# Transformers, Datasets e Coqui TTS di tentare qualsiasi connessione di rete.
# Se un modello locale manca, l'app dà un errore esplicito invece di scaricarlo.
# DEVONO essere impostate PRIMA di qualsiasi import che possa caricare ML libs.
# ─────────────────────────────────────────────────────────────────────────────
import os
os.environ.setdefault("HF_HUB_OFFLINE",       "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE",  "1")
os.environ.setdefault("TTS_TOS_AGREED",       "1")  # evita prompt EULA online

import customtkinter as ctk
from app.window import VocalTextApp

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

if __name__ == "__main__":
    app = VocalTextApp()
    app.mainloop()
