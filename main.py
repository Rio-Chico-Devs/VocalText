#!/usr/bin/env python3
"""
VocalText – app desktop offline text-to-speech.
Avvio: python main.py
"""

import customtkinter as ctk
from app.window import VocalTextApp

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

if __name__ == "__main__":
    app = VocalTextApp()
    app.mainloop()
