"""
VocalText – finestra principale (CustomTkinter).
"""

import tkinter as tk
import customtkinter as ctk
import threading
import os
import wave
import struct
import math
from pathlib import Path
from tkinter import filedialog

from app.tts.engine import TTSEngine, Voice
from app.audio.player import AudioPlayer

ACCENT   = "#4ecca3"
ACCENT_D = "#3aaf8d"
DANGER   = "#ff6b6b"
WARN     = "#f4a261"

# Lingue supportate da XTTS v2
LANGUAGES = {
    "it": "Italiano", "en": "English", "es": "Español",
    "fr": "Français", "de": "Deutsch", "pt": "Português",
    "pl": "Polski",   "ru": "Русский", "nl": "Nederlands",
    "cs": "Čeština",  "zh-cn": "中文",  "hu": "Magyar",
    "ko": "한국어",    "ja": "日本語",   "ar": "العربية",
    "hi": "हिंदी",
}


class VocalTextApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("VocalText")
        self.geometry("1080x720")
        self.minsize(820, 580)

        self.engine = TTSEngine()
        self.player = AudioPlayer()

        self._voice: Voice | None = None
        self._speed   = tk.DoubleVar(value=1.0)
        self._volume  = tk.DoubleVar(value=1.0)
        self._lang    = tk.StringVar(value="it")
        self._polish  = tk.BooleanVar(value=True)
        self._ref_wav: str | None = None
        self._audio_path: str | None = None
        self._voice_rows: dict[str, ctk.CTkFrame] = {}

        # Selezione audio per editing
        self._sel_start: float | None = None   # secondi
        self._sel_end:   float | None = None   # secondi
        self._sel_drag_x0: int | None = None   # pixel pressione iniziale

        # Editing non-distruttivo: backup dell'originale finché non confermato
        self._audio_original: str | None = None   # path originale prima dell'edit
        self._edit_pending = False                 # c'è un edit non ancora confermato

        self._build()
        self.after(120, self._load_voices)
        self.after(120, self._check_engine)
        self.after(400, self._preload_xtts)   # avvia XTTS in background subito
        self.after(200, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ══════════════════════════════════════════════════════════════════════
    #  Layout
    # ══════════════════════════════════════════════════════════════════════

    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

    # ── Sidebar ────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=230, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(4, weight=1)

        # Header
        hdr = ctk.CTkFrame(sb, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        ctk.CTkLabel(hdr, text="VocalText",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=ACCENT).pack(side="left")
        self._theme_btn = ctk.CTkButton(
            hdr, text="☀", width=28, height=28,
            fg_color="transparent", hover_color=("gray80", "gray30"),
            command=self._toggle_theme)
        self._theme_btn.pack(side="right")

        # Engine status
        self._status_lbl = ctk.CTkLabel(
            sb, text="● Rilevamento…",
            font=ctk.CTkFont(size=11), anchor="w", text_color="gray")
        self._status_lbl.grid(row=1, column=0, sticky="ew", padx=14, pady=(8, 2))

        # Voice list label
        ctk.CTkLabel(sb, text="VOCE",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray", anchor="w").grid(
            row=3, column=0, sticky="ew", padx=14, pady=(8, 2))

        self._voice_frame = ctk.CTkScrollableFrame(
            sb, fg_color="transparent", label_text="")
        self._voice_frame.grid(row=4, column=0, sticky="nsew", padx=8)

        # ── XTTS: lingua + clonazione voce ──
        self._xtts_panel = ctk.CTkFrame(sb, fg_color="transparent")
        self._xtts_panel.grid(row=5, column=0, sticky="ew", padx=14, pady=(4, 0))
        self._xtts_panel.grid_remove()   # visibile solo con voce XTTS

        ctk.CTkLabel(self._xtts_panel, text="LINGUA",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray", anchor="w").pack(fill="x")

        lang_menu = ctk.CTkOptionMenu(
            self._xtts_panel,
            values=[f"{code}  {name}" for code, name in LANGUAGES.items()],
            command=self._on_lang_change,
            fg_color=("gray85", "gray25"),
            button_color=ACCENT, button_hover_color=ACCENT_D,
            dynamic_resizing=False, width=200)
        lang_menu.set("it  Italiano")
        lang_menu.pack(fill="x", pady=(4, 8))
        self._lang_menu = lang_menu

        ctk.CTkLabel(self._xtts_panel, text="CLONA UNA VOCE (opzionale)",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray", anchor="w").pack(fill="x")

        ctk.CTkLabel(self._xtts_panel,
                     text="Carica un file WAV di ~6 sec con la voce\nda riprodurre (tua voce, attore, ecc.)",
                     font=ctk.CTkFont(size=11), text_color="gray",
                     justify="left").pack(fill="x", pady=(2, 4))

        ref_row = ctk.CTkFrame(self._xtts_panel, fg_color="transparent")
        ref_row.pack(fill="x")
        self._ref_lbl = ctk.CTkLabel(
            ref_row, text="Nessun file selezionato",
            font=ctk.CTkFont(size=11), text_color="gray",
            anchor="w", wraplength=140)
        self._ref_lbl.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            ref_row, text="Sfoglia", width=64, height=26,
            fg_color="transparent", border_width=1,
            command=self._pick_ref_wav).pack(side="right")

        self._ref_clear_btn = ctk.CTkButton(
            self._xtts_panel, text="✕  Rimuovi voce di riferimento",
            height=26, fg_color="transparent", border_width=1,
            text_color=DANGER, hover_color=("gray85", "gray25"),
            command=self._clear_ref_wav)
        self._ref_clear_btn.pack(fill="x", pady=(4, 0))
        self._ref_clear_btn.pack_forget()

        # ── Multi-voci ──
        ctk.CTkButton(
            sb, text="🎭  Multi-voci", height=30,
            fg_color="transparent", border_width=1,
            text_color=ACCENT, hover_color=("gray85", "gray25"),
            font=ctk.CTkFont(size=12),
            command=self._open_multi_voice,
        ).grid(row=7, column=0, sticky="ew", padx=14, pady=(0, 8))

        # ── Parametri ──
        params = ctk.CTkFrame(sb, fg_color="transparent")
        params.grid(row=6, column=0, sticky="ew", padx=14, pady=(8, 4))

        ctk.CTkLabel(params, text="PARAMETRI",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray", anchor="w").pack(fill="x")

        self._speed_lbl = ctk.CTkLabel(
            params, text="Velocità  1.00×",
            font=ctk.CTkFont(size=12), anchor="w")
        self._speed_lbl.pack(fill="x", pady=(8, 0))
        ctk.CTkSlider(
            params, from_=0.5, to=2.0, variable=self._speed,
            button_color=ACCENT, button_hover_color=ACCENT_D,
            progress_color=ACCENT,
            command=lambda v: self._speed_lbl.configure(
                text=f"Velocità  {float(v):.2f}×")).pack(fill="x")

        self._vol_lbl = ctk.CTkLabel(
            params, text="Volume  100%",
            font=ctk.CTkFont(size=12), anchor="w")
        self._vol_lbl.pack(fill="x", pady=(10, 0))
        ctk.CTkSlider(
            params, from_=0.1, to=1.0, variable=self._volume,
            button_color=ACCENT, button_hover_color=ACCENT_D,
            progress_color=ACCENT,
            command=lambda v: self._vol_lbl.configure(
                text=f"Volume  {int(float(v)*100)}%")).pack(fill="x")

        # ── Rifinitura audio ──
        polish_row = ctk.CTkFrame(params, fg_color="transparent")
        polish_row.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(polish_row, text="Rifinitura audio",
                     font=ctk.CTkFont(size=12), anchor="w").pack(side="left")
        ctk.CTkSwitch(
            polish_row, text="", variable=self._polish, width=40,
            button_color=ACCENT, button_hover_color=ACCENT_D,
            progress_color=ACCENT).pack(side="right")
        ctk.CTkLabel(
            params,
            text="EQ voce · compressione · normalizzazione LUFS",
            font=ctk.CTkFont(size=10), text_color="gray",
            anchor="w", justify="left").pack(fill="x")

        # ── Pannello tag effetti ──
        ctk.CTkButton(
            params, text="📋  Tag effetti disponibili",
            height=26, fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=11),
            command=self._show_tags_help).pack(fill="x", pady=(10, 0))

    # ── Main area ──────────────────────────────────────────────────────────

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        # Editor card
        editor_card = ctk.CTkFrame(main)
        editor_card.grid(row=0, column=0, sticky="ew")
        editor_card.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(editor_card, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        ctk.CTkLabel(toolbar, text="TESTO",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray").pack(side="left")
        ctk.CTkButton(toolbar, text="Incolla", width=70, height=26,
                      fg_color="transparent", border_width=1,
                      command=self._paste).pack(side="right", padx=(4, 0))
        ctk.CTkButton(toolbar, text="Cancella", width=70, height=26,
                      fg_color="transparent", border_width=1,
                      command=self._clear_text).pack(side="right")

        self._textbox = ctk.CTkTextbox(
            editor_card, height=200, wrap="word",
            font=ctk.CTkFont(size=14))
        self._textbox.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 0))
        self._textbox.bind("<KeyRelease>", self._on_text_change)
        self._textbox.insert("0.0",
            "Scrivi qui il testo da convertire in voce…\n\n"
            "Premi Ctrl+Invio oppure il pulsante \"Genera Audio\" per iniziare.")
        self._textbox.bind("<FocusIn>", self._clear_placeholder)

        foot = ctk.CTkFrame(editor_card, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 10))
        self._char_lbl = ctk.CTkLabel(
            foot, text="0 / 5000 caratteri",
            font=ctk.CTkFont(size=11), text_color="gray")
        self._char_lbl.pack(side="left")
        self._word_lbl = ctk.CTkLabel(
            foot, text="0 parole",
            font=ctk.CTkFont(size=11), text_color="gray")
        self._word_lbl.pack(side="right")

        # Generate button
        self._gen_btn = ctk.CTkButton(
            main, text="▶  Genera Audio",
            height=48, font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
            command=self._generate)
        self._gen_btn.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.bind("<Control-Return>", lambda _: self._generate())

        # Error label
        self._err_lbl = ctk.CTkLabel(
            main, text="", text_color=DANGER,
            font=ctk.CTkFont(size=12), wraplength=600, anchor="w")
        self._err_lbl.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        # Player card
        self._player_card = ctk.CTkFrame(main)
        self._player_card.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self._player_card.grid_columnconfigure(0, weight=1)
        self._player_card.grid_remove()
        self._build_player(self._player_card)

    def _build_player(self, parent):
        # Istruzione selezione
        ctk.CTkLabel(
            parent,
            text="Trascina sulla forma d'onda per selezionare una regione",
            font=ctk.CTkFont(size=10), text_color="gray").grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 0))

        self._wave_canvas = tk.Canvas(
            parent, height=64, bg="#1d2335",
            highlightthickness=0, cursor="crosshair")
        self._wave_canvas.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 0))
        self._wave_canvas.bind("<Button-1>",        self._sel_press)
        self._wave_canvas.bind("<B1-Motion>",       self._sel_motion)
        self._wave_canvas.bind("<ButtonRelease-1>", self._sel_release)

        ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl.grid(row=2, column=0, sticky="ew", padx=10, pady=6)
        ctrl.grid_columnconfigure(2, weight=1)

        self._play_btn = ctk.CTkButton(
            ctrl, text="▶", width=38, height=38,
            fg_color=ACCENT, hover_color=ACCENT_D,
            text_color="#0a1810", font=ctk.CTkFont(size=16),
            command=self._toggle_play)
        self._play_btn.grid(row=0, column=0, padx=(0, 6))

        self._time_cur = ctk.CTkLabel(
            ctrl, text="0:00",
            font=ctk.CTkFont(size=12, family="monospace"), width=38)
        self._time_cur.grid(row=0, column=1)

        self._seek_var = tk.DoubleVar(value=0)
        ctk.CTkSlider(
            ctrl, from_=0, to=100, variable=self._seek_var,
            button_color=ACCENT, button_hover_color=ACCENT_D,
            progress_color=ACCENT,
            command=self._seek_drag).grid(
            row=0, column=2, sticky="ew", padx=6)

        self._time_tot = ctk.CTkLabel(
            ctrl, text="0:00",
            font=ctk.CTkFont(size=12, family="monospace"), width=38)
        self._time_tot.grid(row=0, column=3)

        ctk.CTkButton(
            ctrl, text="⟲", width=32, height=32,
            fg_color="transparent", border_width=1,
            command=lambda: (self.player.restart(),
                             self.player.play())).grid(
            row=0, column=4, padx=(6, 0))

        # ── Barra editing (visibile solo con selezione attiva) ──
        self._edit_bar = ctk.CTkFrame(parent, fg_color="transparent")
        self._edit_bar.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 4))
        self._edit_bar.grid_remove()

        ctk.CTkLabel(self._edit_bar, text="Selezione:",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(side="left")
        self._sel_lbl = ctk.CTkLabel(
            self._edit_bar, text="",
            font=ctk.CTkFont(size=11, family="monospace"),
            text_color=ACCENT)
        self._sel_lbl.pack(side="left", padx=(4, 12))

        ctk.CTkButton(
            self._edit_bar, text="✂  Elimina selezione",
            height=28, width=160,
            fg_color=DANGER, hover_color="#cc4444", text_color="white",
            font=ctk.CTkFont(size=11),
            command=self._edit_delete).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            self._edit_bar, text="✂  Ritaglia",
            height=28, width=100,
            fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=11),
            command=self._edit_crop).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            self._edit_bar, text="✕",
            height=28, width=32,
            fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=11),
            command=self._edit_clear_sel).pack(side="left")

        # ── Barra conferma edit (visibile dopo ogni modifica) ──
        self._confirm_bar = ctk.CTkFrame(parent, fg_color=("gray90", "#1e2a1e"),
                                         corner_radius=6)
        self._confirm_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 4))
        self._confirm_bar.grid_remove()

        ctk.CTkLabel(self._confirm_bar,
                     text="Anteprima modifica — ascolta e poi scegli:",
                     font=ctk.CTkFont(size=11), text_color=WARN).pack(
            side="left", padx=(10, 12), pady=6)

        ctk.CTkButton(
            self._confirm_bar, text="✓  Conferma",
            height=28, width=110,
            fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
            font=ctk.CTkFont(size=11),
            command=self._confirm_edit).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            self._confirm_bar, text="↩  Annulla",
            height=28, width=90,
            fg_color="transparent", border_width=1, text_color=WARN,
            font=ctk.CTkFont(size=11),
            command=self._undo_edit).pack(side="left")

        # ── Footer: pulisci voce + export + info durata ──
        exp = ctk.CTkFrame(parent, fg_color="transparent")
        exp.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 10))

        self._clean_btn = ctk.CTkButton(
            exp, text="✨ Pulisci voce", width=140, height=30,
            fg_color="transparent", border_width=1,
            text_color=ACCENT,
            font=ctk.CTkFont(size=12),
            command=self._clean_voice)
        self._clean_btn.pack(side="left", padx=(0, 6))

        self._speed_btn = ctk.CTkButton(
            exp, text="⏱ Velocità", width=110, height=30,
            fg_color="transparent", border_width=1,
            text_color=ACCENT,
            font=ctk.CTkFont(size=12),
            command=self._show_speed_dialog)
        self._speed_btn.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            exp, text="Esporta…", width=100, height=30,
            fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._show_export_dialog).pack(side="left")
        self._dur_lbl = ctk.CTkLabel(
            exp, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self._dur_lbl.pack(side="right")

    # ══════════════════════════════════════════════════════════════════════
    #  Engine & voices
    # ══════════════════════════════════════════════════════════════════════

    def _check_engine(self):
        level, msg = self.engine.status()
        colors = {"ok": ACCENT, "warn": WARN, "error": DANGER}
        self._status_lbl.configure(
            text=f"● {msg}", text_color=colors.get(level, "gray"))

    def _preload_xtts(self):
        """Carica il modello XTTS in background appena l'app si apre."""
        if not self.engine.has_xtts():
            return
        from app.tts.xtts import XTTSEngine
        if XTTSEngine.is_loaded() or XTTSEngine.is_loading():
            return
        self._status_lbl.configure(
            text="● Caricamento XTTS v2…", text_color=WARN)
        XTTSEngine.load_model(
            on_progress=lambda m: self.after(
                0, lambda: self._status_lbl.configure(
                    text="● Caricamento XTTS v2…", text_color=WARN)),
            on_done=lambda: self.after(
                0, lambda: self._status_lbl.configure(
                    text="● XTTS v2 pronto", text_color=ACCENT)),
            on_error=lambda e: self.after(
                0, lambda: self._status_lbl.configure(
                    text="● XTTS errore caricamento", text_color=DANGER)),
        )

    def _load_voices(self):
        def _fetch():
            voices = self.engine.get_all_voices()
            self.after(0, lambda: self._render_voices(voices))
        threading.Thread(target=_fetch, daemon=True).start()

    def _render_voices(self, voices: list[Voice]):
        for w in self._voice_frame.winfo_children():
            w.destroy()
        self._voice_rows.clear()

        if not voices:
            ctk.CTkLabel(
                self._voice_frame,
                text="Nessuna voce trovata.\nInstalla espeak-ng o\naggiungi modelli Piper.",
                font=ctk.CTkFont(size=11), text_color="gray",
                justify="left").pack(anchor="w", padx=4, pady=6)
            return

        xtts_voices  = [v for v in voices if v.engine == "xtts"]
        piper_voices = [v for v in voices if v.engine == "piper"]
        sys_voices   = [v for v in voices if v.engine == "pyttsx3"]

        if xtts_voices:
            self._section_label("XTTS v2 · Neurale")
            for v in xtts_voices:
                self._voice_btn(v)

        if piper_voices:
            self._section_label("Piper · Neurale")
            for v in piper_voices:
                self._voice_btn(v)

        if sys_voices:
            self._section_label("Sistema · Base")
            for v in sys_voices[:12]:
                self._voice_btn(v)

        if voices and self._voice is None:
            first = voices[0]
            self._select_voice(first, self._voice_rows.get(first.id))

    def _section_label(self, text: str):
        ctk.CTkLabel(
            self._voice_frame, text=text,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="gray", anchor="w").pack(
            fill="x", padx=4, pady=(8, 2))

    def _voice_btn(self, voice: Voice):
        colors = {"high": ACCENT, "medium": WARN, "low": "gray"}
        dot_color = colors.get(voice.quality, "gray")

        row = ctk.CTkFrame(self._voice_frame, fg_color="transparent", cursor="hand2")
        row.pack(fill="x", pady=1)

        ctk.CTkLabel(row, text="●", font=ctk.CTkFont(size=10),
                     text_color=dot_color, width=14).pack(side="left", padx=(4, 2))

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        name_lbl = ctk.CTkLabel(
            info, text=voice.name,
            font=ctk.CTkFont(size=13), anchor="w")
        name_lbl.pack(fill="x")

        lang_display = voice.lang.upper() if voice.lang != "multi" else "MULTI"
        ctk.CTkLabel(
            info, text=f"{lang_display} · {voice.quality}",
            font=ctk.CTkFont(size=10), text_color="gray",
            anchor="w").pack(fill="x")

        row._voice    = voice
        row._name_lbl = name_lbl
        self._voice_rows[voice.id] = row

        for w in (row, info, name_lbl):
            w.bind("<Button-1>",
                   lambda _, v=voice, r=row: self._select_voice(v, r))

    def _select_voice(self, voice: Voice, row_widget=None):
        self._voice = voice

        for row in self._voice_rows.values():
            row.configure(fg_color="transparent")
            row._name_lbl.configure(text_color=("gray10", "gray90"))

        if row_widget and row_widget.winfo_exists():
            row_widget.configure(fg_color=("gray85", "#1e2d24"))
            row_widget._name_lbl.configure(text_color=ACCENT)

        # Mostra/nascondi pannello XTTS
        if voice.engine == "xtts":
            self._xtts_panel.grid()
        else:
            self._xtts_panel.grid_remove()

    # ── Tag effetti ───────────────────────────────────────────────────────

    def _show_tags_help(self):
        from app.audio.effects import get_tags_help
        win = ctk.CTkToplevel(self)
        win.title("Tag effetti sonori")
        win.geometry("360x420")
        win.resizable(False, False)
        win.grab_set()

        ctk.CTkLabel(win, text="Inserisci questi tag nel testo",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(16, 4))
        ctk.CTkLabel(win,
                     text="Gli effetti vengono generati con la voce selezionata\n"
                          "e cachati offline nella cartella effects/",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(0, 10))

        frame = ctk.CTkScrollableFrame(win, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=16)

        tags = get_tags_help()
        for tag, desc in tags.items():
            row = ctk.CTkFrame(frame, fg_color=("gray90", "gray20"),
                               corner_radius=6)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=f"[{tag}]",
                         font=ctk.CTkFont(size=12, family="Courier"),
                         text_color=ACCENT, anchor="w").pack(
                side="left", padx=10, pady=6)
            ctk.CTkLabel(row, text=desc,
                         font=ctk.CTkFont(size=11), text_color="gray",
                         anchor="e").pack(side="right", padx=10)

        ctk.CTkButton(win, text="Chiudi", command=win.destroy,
                      fg_color=ACCENT, hover_color=ACCENT_D).pack(pady=12)

    # ── XTTS helpers ──────────────────────────────────────────────────────

    def _on_lang_change(self, value: str):
        code = value.split()[0]
        self._lang.set(code)

    def _pick_ref_wav(self):
        path = filedialog.askopenfilename(
            title="Seleziona audio di riferimento",
            filetypes=[("File WAV", "*.wav"), ("Tutti i file", "*.*")])
        if path:
            self._ref_wav = path
            name = os.path.basename(path)
            self._ref_lbl.configure(text=name, text_color=ACCENT)
            self._ref_clear_btn.pack(fill="x", pady=(4, 0))

    def _clear_ref_wav(self):
        self._ref_wav = None
        self._ref_lbl.configure(
            text="Nessun file selezionato", text_color="gray")
        self._ref_clear_btn.pack_forget()

    # ══════════════════════════════════════════════════════════════════════
    #  Text editor
    # ══════════════════════════════════════════════════════════════════════

    _placeholder_active = True

    def _clear_placeholder(self, _event=None):
        if self._placeholder_active:
            self._textbox.delete("0.0", "end")
            self._placeholder_active = False

    def _clear_text(self):
        self._placeholder_active = False
        self._textbox.delete("0.0", "end")
        self._on_text_change()

    def _paste(self):
        try:
            text = self.clipboard_get()
            self._clear_placeholder()
            self._textbox.delete("0.0", "end")
            self._textbox.insert("0.0", text)
            self._on_text_change()
        except Exception:
            pass

    def _on_text_change(self, _event=None):
        if self._placeholder_active:
            return
        text = self._textbox.get("0.0", "end").strip()
        chars = len(text)
        words = len(text.split()) if text else 0
        color = (DANGER if chars > 4800 else
                 WARN   if chars > 4000 else "gray")
        self._char_lbl.configure(
            text=f"{chars} / 5000 caratteri", text_color=color)
        self._word_lbl.configure(text=f"{words} parole")

    def _get_text(self) -> str:
        return "" if self._placeholder_active else \
               self._textbox.get("0.0", "end").strip()

    # ══════════════════════════════════════════════════════════════════════
    #  Generation
    # ══════════════════════════════════════════════════════════════════════

    def _generate(self):
        text = self._get_text()
        if not text:
            self._show_error("Scrivi del testo prima di generare.")
            return
        if not self._voice:
            self._show_error("Seleziona una voce dalla lista a sinistra.")
            return

        # XTTS: se ancora in caricamento mostra stato ma procede comunque
        # (il thread di generazione attende internamente fino a 5 minuti)
        if self._voice.engine == "xtts":
            from app.tts.xtts import XTTSEngine
            if not XTTSEngine.is_loaded():
                if not XTTSEngine.is_loading():
                    self._preload_xtts()
                self._status_lbl.configure(
                    text="● Caricamento XTTS v2…", text_color=WARN)

        self._gen_btn.configure(state="disabled",
                                text="⏳  Generazione in corso…")
        self._hide_error()

        from app.audio.effects import has_tags, build_audio

        if has_tags(text):
            # Pipeline con effetti inline
            build_audio(
                text=text,
                voice=self._voice,
                engine=self.engine,
                speed=self._speed.get(),
                volume=self._volume.get(),
                language=self._lang.get(),
                reference_wav=self._ref_wav,
                polish=self._polish.get(),
                on_done=lambda p: self.after(0, lambda: self._on_audio_ready(p)),
                on_error=lambda e: self.after(0, lambda: self._on_gen_error(e)),
            )
        else:
            self.engine.generate(
                text=text,
                voice=self._voice,
                speed=self._speed.get(),
                volume=self._volume.get(),
                language=self._lang.get(),
                reference_wav=self._ref_wav,
                polish=self._polish.get(),
                on_done=lambda p: self.after(0, lambda: self._on_audio_ready(p)),
                on_error=lambda e: self.after(0, lambda: self._on_gen_error(e)),
            )

    def _on_audio_ready(self, path: str):
        self._audio_path = path
        self._audio_original = None
        self._edit_pending   = False
        self._confirm_bar.grid_remove()
        self._gen_btn.configure(state="normal", text="▶  Genera Audio")
        duration = self.player.load(path)
        self._time_tot.configure(text=_fmt_time(duration))
        self._dur_lbl.configure(text=f"{_fmt_time(duration)} · WAV")
        self._draw_waveform(path)
        self._edit_clear_sel()
        self._player_card.grid()
        self.player.play(on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

    def _on_gen_error(self, msg: str):
        self._gen_btn.configure(state="normal", text="▶  Genera Audio")
        self._show_error(msg)

    # ══════════════════════════════════════════════════════════════════════
    #  Player
    # ══════════════════════════════════════════════════════════════════════

    def _toggle_play(self):
        if not self._audio_path:
            return
        if self.player.is_playing:
            self.player.pause()
            self._play_btn.configure(text="▶")
        else:
            self.player.play(
                on_end=lambda: self.after(0, self._on_play_end))
            self._play_btn.configure(text="⏸")

    def _on_play_end(self):
        self._play_btn.configure(text="▶")
        self._seek_var.set(0)
        self._time_cur.configure(text="0:00")
        self._update_playhead(0.0)

    def _seek_drag(self, value):
        if not self.player.duration:
            return
        secs = (float(value) / 100.0) * self.player.duration
        self.player.seek(secs)
        self._time_cur.configure(text=_fmt_time(secs))
        self._update_playhead(secs)

    def _seek_to_x(self, x: int):
        """Porta la riproduzione alla posizione x (pixel) sulla forma d'onda."""
        w = self._wave_canvas.winfo_width()
        if w <= 0:
            return
        pct  = max(0.0, min(x / w, 1.0))
        secs = pct * self.player.duration
        self.player.seek(secs)
        self.player.play(on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

    # ── Selezione waveform ─────────────────────────────────────────────────

    def _sel_press(self, event):
        """Inizio click: segna la posizione iniziale, cancella selezione precedente."""
        self._sel_drag_x0 = event.x
        self._sel_start = None
        self._sel_end   = None
        self._wave_canvas.delete("selection")
        self._edit_bar.grid_remove()

    def _sel_motion(self, event):
        """Trascinamento: disegna il rettangolo di selezione in tempo reale."""
        if self._sel_drag_x0 is None or not self.player.duration:
            return
        x0, x1 = self._sel_drag_x0, event.x
        xa, xb = min(x0, x1), max(x0, x1)
        if xb - xa < 3:
            return
        H = self._wave_canvas.winfo_height() or 64
        self._wave_canvas.delete("selection")
        # Rettangolo semitrasparente (stipple = tratteggio tk)
        self._wave_canvas.create_rectangle(
            xa, 0, xb, H,
            fill=ACCENT, stipple="gray25",
            outline=ACCENT, width=1, tags="selection")
        # Linee di bordo solide
        self._wave_canvas.create_line(xa, 0, xa, H,
                                      fill=ACCENT, width=2, tags="selection")
        self._wave_canvas.create_line(xb, 0, xb, H,
                                      fill=ACCENT, width=2, tags="selection")

    def _sel_release(self, event):
        """Fine click/trascinamento: decide se fare seek o finalizzare selezione."""
        if self._sel_drag_x0 is None:
            return
        dx = abs(event.x - self._sel_drag_x0)
        if dx < 6 or not self.player.duration:
            # Click semplice → seek
            self._wave_canvas.delete("selection")
            self._edit_bar.grid_remove()
            self._sel_drag_x0 = None
            self._seek_to_x(event.x)
            return

        # Trascino → selezione
        w  = self._wave_canvas.winfo_width()
        x0 = self._sel_drag_x0
        x1 = event.x
        xa, xb = min(x0, x1), max(x0, x1)
        dur = self.player.duration
        self._sel_start = max(0.0, (xa / w) * dur)
        self._sel_end   = min(dur,  (xb / w) * dur)
        self._sel_drag_x0 = None

        self._sel_lbl.configure(
            text=f"{_fmt_time(self._sel_start)} → {_fmt_time(self._sel_end)}"
                 f"  ({_fmt_time(self._sel_end - self._sel_start)})")
        self._edit_bar.grid()

    def _edit_clear_sel(self):
        """Cancella la selezione corrente."""
        self._sel_start = None
        self._sel_end   = None
        self._wave_canvas.delete("selection")
        self._edit_bar.grid_remove()

    # ── Operazioni di editing ──────────────────────────────────────────────

    def _edit_delete(self):
        """Elimina la regione selezionata dall'audio."""
        if self._sel_start is None or not self._audio_path:
            return
        self._apply_edit("delete")

    def _edit_crop(self):
        """Mantiene solo la regione selezionata."""
        if self._sel_start is None or not self._audio_path:
            return
        self._apply_edit("crop")

    def _apply_edit(self, mode: str):
        import tempfile
        path = self._audio_path
        try:
            with wave.open(path, "rb") as wf:
                n_ch = wf.getnchannels()
                sw   = wf.getsampwidth()
                sr   = wf.getframerate()
                n_fr = wf.getnframes()
                raw  = wf.readframes(n_fr)

            fmt = {1: "b", 2: "h", 4: "i"}.get(sw, "h")
            all_samples = list(struct.unpack(f"<{n_fr * n_ch}{fmt}", raw))

            s_start = int(self._sel_start * sr) * n_ch
            s_end   = int(self._sel_end   * sr) * n_ch
            s_start = max(0, min(s_start, len(all_samples)))
            s_end   = max(0, min(s_end,   len(all_samples)))

            if mode == "delete":
                result = all_samples[:s_start] + all_samples[s_end:]
            else:  # crop
                result = all_samples[s_start:s_end]

            if not result:
                self._show_error("La modifica produrrebbe un file vuoto.")
                return

            # Scrivi in un file TEMPORANEO — non tocca l'originale
            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="vt_edit_")
            os.close(fd)
            packed = struct.pack(f"<{len(result)}{fmt}", *result)
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(n_ch)
                wf.setsampwidth(sw)
                wf.setframerate(sr)
                wf.writeframes(packed)

            # Prima modifica: salva backup dell'originale
            if not self._edit_pending:
                self._audio_original = path
                self._edit_pending   = True

            # Swap a temp e riproduci subito
            self._audio_path = tmp
            self.player.stop()
            duration = self.player.load(tmp)
            self._time_tot.configure(text=_fmt_time(duration))
            label_mode = "eliminata selezione" if mode == "delete" else "ritagliato"
            self._dur_lbl.configure(
                text=f"{_fmt_time(duration)} · WAV ({label_mode})")
            self._draw_waveform(tmp)
            self._edit_clear_sel()
            self._confirm_bar.grid()
            self._hide_error()
            self.player.play(on_end=lambda: self.after(0, self._on_play_end))
            self._play_btn.configure(text="⏸")

        except Exception as exc:
            self._show_error(f"Errore editing: {exc}")

    def _confirm_edit(self):
        """Conferma la modifica: il file temp diventa il nuovo audio corrente."""
        if not self._edit_pending:
            return
        # Se l'originale era già un temp, possiamo eliminarlo
        if self._audio_original and self._audio_original != self._audio_path:
            try:
                os.unlink(self._audio_original)
            except Exception:
                pass
        self._audio_original = None
        self._edit_pending   = False
        self._confirm_bar.grid_remove()
        dur = self.player.duration or 0
        self._dur_lbl.configure(text=f"{_fmt_time(dur)} · WAV")

    def _undo_edit(self):
        """Annulla la modifica: ripristina l'audio originale."""
        if not self._edit_pending or not self._audio_original:
            self._confirm_bar.grid_remove()
            return
        # Elimina il file di edit temporaneo
        if self._audio_path and self._audio_path != self._audio_original:
            try:
                os.unlink(self._audio_path)
            except Exception:
                pass
        self._audio_path     = self._audio_original
        self._audio_original = None
        self._edit_pending   = False
        self._confirm_bar.grid_remove()
        self.player.stop()
        duration = self.player.load(self._audio_path)
        self._time_tot.configure(text=_fmt_time(duration))
        self._dur_lbl.configure(text=f"{_fmt_time(duration)} · WAV")
        self._draw_waveform(self._audio_path)
        self._edit_clear_sel()
        self.player.play(on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

    # ── Pulizia voce ───────────────────────────────────────────────────────────

    def _clean_voice(self):
        """Pulisce l'audio corrente dal rumore in background.
        Usa lo stesso workflow Conferma/Annulla degli altri edit."""
        if not self._audio_path:
            return
        import tempfile
        from app.audio.enhance import clean_voice

        src = self._audio_path
        fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="vt_clean_")
        os.close(fd)

        self._clean_btn.configure(state="disabled", text="⏳ Pulizia in corso…")
        self._show_error("Pulizia voce in corso… (può richiedere qualche secondo)",
                         color=WARN)

        def _run():
            try:
                ok = clean_voice(src, tmp)
                self.after(0, lambda: self._on_clean_done(tmp, ok))
            except Exception as exc:
                self.after(0, lambda: self._on_clean_error(str(exc), tmp))

        threading.Thread(target=_run, daemon=True).start()

    def _on_clean_done(self, tmp_path: str, ok: bool):
        self._clean_btn.configure(state="normal", text="✨ Pulisci voce")
        if not ok or not os.path.exists(tmp_path):
            self._show_error(
                "Pulizia non riuscita — l'audio originale non è stato modificato.")
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
            return

        # Prima pulizia: salva backup dell'originale
        if not self._edit_pending:
            self._audio_original = self._audio_path
            self._edit_pending   = True

        # Swap a temp pulito e riproduci subito
        self._audio_path = tmp_path
        self.player.stop()
        duration = self.player.load(tmp_path)
        self._time_tot.configure(text=_fmt_time(duration))
        self._dur_lbl.configure(text=f"{_fmt_time(duration)} · WAV (pulito)")
        self._draw_waveform(tmp_path)
        self._edit_clear_sel()
        self._confirm_bar.grid()
        self._hide_error()
        self.player.play(on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

    def _on_clean_error(self, msg: str, tmp_path: str):
        self._clean_btn.configure(state="normal", text="✨ Pulisci voce")
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass
        self._show_error(f"Errore pulizia voce: {msg}")

    # ── Cambio velocità (pitch preservato) ─────────────────────────────────────

    def _show_speed_dialog(self):
        """Dialog con slider 0.5x – 2.0x. Applica time-stretch pitch-preserving."""
        if not self._audio_path:
            return

        win = ctk.CTkToplevel(self)
        win.title("Cambia velocità")
        win.geometry("380x230")
        win.resizable(False, False)
        win.grab_set()

        ctk.CTkLabel(win, text="Cambia velocità",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 2))
        ctk.CTkLabel(win, text="L'intonazione viene preservata.",
                     font=ctk.CTkFont(size=11),
                     text_color="gray").pack(pady=(0, 10))

        speed_var = tk.DoubleVar(value=1.0)
        val_lbl = ctk.CTkLabel(
            win, text="1.00×",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=ACCENT)
        val_lbl.pack(pady=(0, 4))

        def _on_change(v):
            val_lbl.configure(text=f"{float(v):.2f}×")

        slider = ctk.CTkSlider(
            win, from_=0.50, to=2.00, number_of_steps=150,
            variable=speed_var, command=_on_change,
            progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_D)
        slider.pack(fill="x", padx=30, pady=(0, 4))

        # Marker preset cliccabili
        preset_row = ctk.CTkFrame(win, fg_color="transparent")
        preset_row.pack(fill="x", padx=30, pady=(0, 12))
        for label, val in [("0.75×", 0.75), ("1.00×", 1.00),
                           ("1.25×", 1.25), ("1.50×", 1.50)]:
            ctk.CTkButton(
                preset_row, text=label, width=60, height=24,
                fg_color="transparent", border_width=1,
                text_color=("gray20", "gray80"),
                font=ctk.CTkFont(size=10),
                command=lambda v=val: (speed_var.set(v),
                                       val_lbl.configure(text=f"{v:.2f}×"))
            ).pack(side="left", expand=True, padx=2)

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=30, pady=(0, 12))

        def _apply():
            factor = float(speed_var.get())
            win.destroy()
            self._apply_speed(factor)

        ctk.CTkButton(
            btn_row, text="Applica", height=32,
            fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=_apply).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(
            btn_row, text="Annulla", height=32,
            fg_color="transparent", border_width=1,
            command=win.destroy).pack(side="left", expand=True, fill="x", padx=(4, 0))

    def _apply_speed(self, factor: float):
        """Time-stretch in background, stesso workflow Conferma/Annulla."""
        if not self._audio_path:
            return
        if abs(factor - 1.0) < 0.01:
            return
        import tempfile
        from app.audio.speed import change_speed

        src = self._audio_path
        fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="vt_speed_")
        os.close(fd)

        self._speed_btn.configure(state="disabled", text="⏳ Elaborazione…")
        self._show_error(f"Cambio velocità a {factor:.2f}×…", color=WARN)

        def _run():
            try:
                ok = change_speed(src, tmp, factor)
                self.after(0, lambda: self._on_speed_done(tmp, ok, factor))
            except Exception as exc:
                self.after(0, lambda: self._on_speed_error(str(exc), tmp))

        threading.Thread(target=_run, daemon=True).start()

    def _on_speed_done(self, tmp_path: str, ok: bool, factor: float):
        self._speed_btn.configure(state="normal", text="⏱ Velocità")
        if not ok or not os.path.exists(tmp_path):
            self._show_error(
                "Cambio velocità non riuscito — l'audio originale non è stato modificato.")
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
            return

        if not self._edit_pending:
            self._audio_original = self._audio_path
            self._edit_pending   = True

        self._audio_path = tmp_path
        self.player.stop()
        duration = self.player.load(tmp_path)
        self._time_tot.configure(text=_fmt_time(duration))
        self._dur_lbl.configure(text=f"{_fmt_time(duration)} · WAV ({factor:.2f}×)")
        self._draw_waveform(tmp_path)
        self._edit_clear_sel()
        self._confirm_bar.grid()
        self._hide_error()
        self.player.play(on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

    def _on_speed_error(self, msg: str, tmp_path: str):
        self._speed_btn.configure(state="normal", text="⏱ Velocità")
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass
        self._show_error(f"Errore cambio velocità: {msg}")

    def _tick(self):
        if self.player.is_playing and self.player.duration > 0:
            pos = self.player.position
            pct = (pos / self.player.duration) * 100
            self._seek_var.set(pct)
            self._time_cur.configure(text=_fmt_time(pos))
            self._update_playhead(pos)
        self.after(200, self._tick)

    def _update_playhead(self, secs: float):
        if not self.player.duration:
            return
        w = self._wave_canvas.winfo_width()
        if w <= 1:
            return
        x = int((secs / self.player.duration) * w)
        self._wave_canvas.delete("playhead")
        self._wave_canvas.create_line(
            x, 0, x, 56, fill=ACCENT, width=2, tags="playhead")

    # ══════════════════════════════════════════════════════════════════════
    #  Waveform
    # ══════════════════════════════════════════════════════════════════════

    def _draw_waveform(self, path: str):
        self.update_idletasks()
        W = self._wave_canvas.winfo_width() or 700
        H = 56
        self._wave_canvas.delete("wave")
        try:
            with wave.open(path, "rb") as wf:
                n_frames   = wf.getnframes()
                sampwidth  = wf.getsampwidth()
                n_channels = wf.getnchannels()
                raw = wf.readframes(n_frames)

            fmt = {1: "b", 2: "h", 4: "i"}.get(sampwidth, "h")
            samples = struct.unpack(f"<{n_frames * n_channels}{fmt}", raw)
            if n_channels > 1:
                samples = [samples[i]
                           for i in range(0, len(samples), n_channels)]
            max_val = 2 ** (sampwidth * 8 - 1)
            norm    = [s / max_val for s in samples]

            step = max(1, len(norm) // W)
            bars = [max(abs(s) for s in norm[i:i + step])
                    for i in range(0, len(norm), step)][:W]

            for x, amp in enumerate(bars):
                bh = max(2, amp * (H - 8))
                y0 = (H - bh) / 2
                self._wave_canvas.create_line(
                    x, y0, x, y0 + bh, fill=ACCENT, tags="wave")
        except Exception:
            import random; random.seed(42)
            for x in range(W):
                amp = 0.2 + 0.6 * abs(math.sin(x * 0.12)) * (
                    0.5 + 0.5 * random.random())
                bh = max(2, amp * (H - 8))
                y0 = (H - bh) / 2
                self._wave_canvas.create_line(
                    x, y0, x, y0 + bh, fill=ACCENT, tags="wave")

    # ══════════════════════════════════════════════════════════════════════
    #  Export
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _find_ffmpeg() -> str | None:
        """Cerca FFmpeg nel PATH e nei percorsi comuni di Windows."""
        import shutil
        found = shutil.which("ffmpeg")
        if found:
            return found
        common = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
            r"C:\tools\ffmpeg\bin\ffmpeg.exe",
        ]
        for p in common:
            if os.path.exists(p):
                return p
        return None

    @staticmethod
    def _has_lameenc() -> bool:
        try:
            import lameenc  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _has_soundfile_ogg() -> bool:
        """True se soundfile è installato e supporta OGG (Vorbis o Opus)."""
        try:
            import soundfile as sf
            subtypes = sf.available_subtypes("OGG")
            return bool(subtypes)  # Vorbis è sempre presente se OGG supportato
        except Exception:
            return False

    @staticmethod
    def _soundfile_ogg_subtype() -> str:
        """Restituisce 'OPUS' se disponibile, altrimenti 'VORBIS'."""
        try:
            import soundfile as sf
            subtypes = sf.available_subtypes("OGG")
            if "OPUS" in subtypes:
                return "OPUS"
            if "VORBIS" in subtypes:
                return "VORBIS"
        except Exception:
            pass
        return "VORBIS"

    @staticmethod
    def _has_soundfile_opus() -> bool:
        """soundfile (libsndfile) supporta Opus dalla 1.0.29 / soundfile 0.12+."""
        try:
            import soundfile as sf
            return "OPUS" in sf.available_subtypes("OGG")
        except Exception:
            return False

    def _show_export_dialog(self):
        if not self._audio_path:
            return

        ffmpeg    = self._find_ffmpeg()
        has_mp3   = self._has_lameenc() or bool(ffmpeg)
        has_ogg   = self._has_soundfile_ogg() or bool(ffmpeg)

        win = ctk.CTkToplevel(self)
        win.title("Esporta audio")
        win.geometry("440x390")
        win.resizable(False, False)
        win.grab_set()

        ctk.CTkLabel(win, text="Esporta Audio",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(18, 2))

        # Riga stato dipendenze
        if self._has_lameenc():
            mp3_note = "MP3 disponibile (lameenc)"
        elif ffmpeg:
            mp3_note = "MP3 disponibile (FFmpeg)"
        else:
            mp3_note = "MP3 non disponibile — esegui: pip install lameenc"

        if self._has_soundfile_opus():
            ogg_note = "OGG/Opus disponibile (soundfile)"
        elif self._has_soundfile_ogg():
            ogg_note = "OGG/Vorbis disponibile (soundfile)"
        elif ffmpeg:
            ogg_note = "OGG/Opus disponibile (FFmpeg)"
        else:
            ogg_note = "OGG non disponibile — esegui: pip install soundfile"

        ctk.CTkLabel(win, text=f"● {mp3_note}",
                     font=ctk.CTkFont(size=11),
                     text_color=ACCENT if has_mp3 else "gray").pack(anchor="w", padx=24)
        ctk.CTkLabel(win, text=f"● {ogg_note}",
                     font=ctk.CTkFont(size=11),
                     text_color=ACCENT if has_ogg else "gray").pack(anchor="w", padx=24, pady=(0, 8))

        # ── Formato ──
        ctk.CTkLabel(win, text="FORMATO",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray").pack(anchor="w", padx=24)

        fmt_var = tk.StringVar(value="wav")
        fmt_frame = ctk.CTkFrame(win, fg_color="transparent")
        fmt_frame.pack(fill="x", padx=24, pady=(4, 10))

        formats = [
            ("WAV   – Lossless, massima fedeltà",        "wav", True),
            ("MP3   – Compresso, compatibile ovunque",    "mp3", has_mp3),
            ("OGG   – Compresso, ottimale web/voce",      "ogg", has_ogg),
        ]
        for label, val, enabled in formats:
            ctk.CTkRadioButton(
                fmt_frame, text=label, variable=fmt_var, value=val,
                state="normal" if enabled else "disabled",
                fg_color=ACCENT, hover_color=ACCENT_D,
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", pady=3)

        # ── Qualità ──
        ctk.CTkLabel(win, text="QUALITÀ  (per MP3/OGG)",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray").pack(anchor="w", padx=24)

        quality_var = tk.StringVar(value="web")
        q_frame = ctk.CTkFrame(win, fg_color="transparent")
        q_frame.pack(fill="x", padx=24, pady=(4, 14))

        for label, val in [
            ("Web ready  – voce leggera ~48 kbps, file piccolo", "web"),
            ("Alta        – bilanciato ~128 kbps",                "high"),
            ("Massima    – 320 kbps / lossless",                  "max"),
        ]:
            ctk.CTkRadioButton(
                q_frame, text=label, variable=quality_var, value=val,
                fg_color=ACCENT, hover_color=ACCENT_D,
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", pady=2)

        def do_export():
            fmt     = fmt_var.get()
            quality = quality_var.get()
            name    = self._voice.name if self._voice else "output"
            ext     = {"wav": ".wav", "mp3": ".mp3", "ogg": ".ogg"}[fmt]
            dest = filedialog.asksaveasfilename(
                title="Salva come",
                defaultextension=ext,
                filetypes=[(fmt.upper() + " audio", f"*{ext}"),
                           ("Tutti i file", "*.*")],
                initialfile=f"VocalText_{name}{ext}")
            if not dest:
                return
            win.destroy()
            self._do_export(fmt, quality, dest)

        ctk.CTkButton(
            win, text="Scegli destinazione ed Esporta",
            height=40, fg_color=ACCENT, hover_color=ACCENT_D,
            text_color="#0a1810",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=do_export).pack(fill="x", padx=24, pady=(0, 8))

        ctk.CTkButton(
            win, text="Annulla", height=30,
            fg_color="transparent", border_width=1,
            command=win.destroy).pack(fill="x", padx=24)

    def _do_export(self, fmt: str, quality: str, dest: str):
        """Esegue la conversione in thread separato."""
        import shutil, subprocess
        src = self._audio_path

        if fmt == "wav":
            try:
                shutil.copy2(src, dest)
                size_kb = os.path.getsize(dest) / 1024
                self._show_error(
                    f"Salvato: {os.path.basename(dest)}  ({size_kb:.0f} KB)",
                    color=ACCENT)
            except Exception as exc:
                self._show_error(f"Errore salvataggio: {exc}")
            return

        self._show_error("Esportazione in corso…", color=WARN)
        threading.Thread(
            target=self._export_worker,
            args=(fmt, quality, src, dest),
            daemon=True,
        ).start()

    def _export_worker(self, fmt: str, quality: str, src: str, dest: str):
        """Thread worker per conversione MP3/OGG."""
        import subprocess
        try:
            if fmt == "mp3" and self._has_lameenc():
                self._export_mp3_lameenc(src, dest, quality)
            elif fmt == "ogg" and self._has_soundfile_ogg():
                self._export_ogg_soundfile(src, dest, quality)
            else:
                ffmpeg = self._find_ffmpeg()
                if not ffmpeg:
                    msg = ("Esporta MP3: installa lameenc."
                           if fmt == "mp3"
                           else "Esporta OGG: installa soundfile (pip install soundfile).")
                    self.after(0, lambda m=msg: self._show_error(m))
                    return
                cmd = [ffmpeg, "-y", "-i", src]
                if fmt == "mp3":
                    q_map = {"max": "0", "high": "2", "web": "5"}
                    cmd += ["-codec:a", "libmp3lame", "-q:a", q_map.get(quality, "3")]
                elif fmt == "ogg":
                    br_map = {"max": "128k", "high": "64k", "web": "32k"}
                    cmd += ["-codec:a", "libopus", "-b:a",
                            br_map.get(quality, "48k"),
                            "-ac", "1", "-ar", "48000"]
                    if quality == "web":
                        cmd += ["-application", "voip"]
                cmd.append(dest)
                result = subprocess.run(cmd, capture_output=True, timeout=120)
                if result.returncode != 0:
                    err = result.stderr.decode(errors="replace")[-300:]
                    self.after(0, lambda: self._show_error(f"Errore FFmpeg: {err}"))
                    return

            if os.path.exists(dest):
                size_kb = os.path.getsize(dest) / 1024
                self.after(0, lambda: self._show_error(
                    f"Esportato: {os.path.basename(dest)}  ({size_kb:.0f} KB)",
                    color=ACCENT))
        except Exception as exc:
            self.after(0, lambda: self._show_error(f"Errore esportazione: {exc}"))

    @staticmethod
    def _export_ogg_soundfile(src: str, dest: str, quality: str):
        """
        Encoder OGG tramite libsndfile (via soundfile) — niente FFmpeg.
        Tenta Opus (richiede libsndfile ≥ 1.0.29), poi Vorbis come fallback.
        Opus richiede sample rate ∈ {8k,12k,16k,24k,48k}.
        """
        import soundfile as sf
        import numpy as np

        data, sr = sf.read(src, dtype="float32", always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)

        subtype = VocalTextApp._soundfile_ogg_subtype()

        if subtype == "OPUS":
            # Opus richiede sample rate specifico
            valid_sr = [48000, 24000, 16000, 12000, 8000]
            target_sr = 24000 if quality == "web" else 48000
            if int(sr) not in valid_sr:
                try:
                    from scipy import signal
                    from math import gcd
                    g = gcd(int(sr), target_sr)
                    data = signal.resample_poly(data, target_sr // g, int(sr) // g).astype(np.float32)
                    sr = target_sr
                except Exception:
                    sr = target_sr

        # compression_level: 0=max qualità, 1=min qualità (Opus e Vorbis)
        level_map = {"max": 0.0, "high": 0.3, "web": 0.7}
        sf.write(
            dest, data, int(sr),
            format="OGG", subtype=subtype,
            compression_level=level_map.get(quality, 0.5),
        )

    @staticmethod
    def _export_mp3_lameenc(src: str, dest: str, quality: str):
        """
        Encoder MP3 puro Python via lameenc — non richiede FFmpeg.
        Legge il WAV sorgente, converte in mono se necessario, codifica.
        """
        import lameenc

        bitrate_map = {"max": 320, "high": 128, "web": 48}
        vbr_q_map   = {"max": 2,   "high": 2,   "web": 5}
        bitrate = bitrate_map.get(quality, 64)
        vbr_q   = vbr_q_map.get(quality, 3)

        with wave.open(src, "rb") as wf:
            n_ch   = wf.getnchannels()
            sr     = wf.getframerate()
            sw     = wf.getsampwidth()
            n_fr   = wf.getnframes()
            raw    = wf.readframes(n_fr)

        # Assicura PCM 16-bit little-endian
        if sw == 2:
            pcm = raw
        elif sw == 1:
            import array as _arr
            samples8 = _arr.array("B", raw)
            samples16 = _arr.array("h", ((s - 128) << 8 for s in samples8))
            pcm = samples16.tobytes()
        else:
            # 32-bit → scala a 16-bit
            import struct as _s
            vals = _s.unpack(f"<{n_fr * n_ch}i", raw)
            import array as _arr
            s16 = _arr.array("h", (v >> 16 for v in vals))
            pcm = s16.tobytes()

        encoder = lameenc.Encoder()
        encoder.set_bit_rate(bitrate)
        encoder.set_in_sample_rate(sr)
        encoder.set_channels(n_ch)
        encoder.set_quality(vbr_q)

        mp3_data = encoder.encode(pcm) + encoder.flush()
        with open(dest, "wb") as f:
            f.write(mp3_data)

    # ══════════════════════════════════════════════════════════════════════
    #  Helpers
    # ══════════════════════════════════════════════════════════════════════

    def _toggle_theme(self):
        new = "Light" if ctk.get_appearance_mode() == "Dark" else "Dark"
        ctk.set_appearance_mode(new)
        self._theme_btn.configure(text="☀" if new == "Dark" else "🌙")
        self._wave_canvas.configure(
            bg="#1d2335" if new == "Dark" else "#e8eaf0")

    def _show_error(self, msg: str, color: str = DANGER):
        self._err_lbl.configure(text=f"⚠  {msg}", text_color=color)

    def _hide_error(self):
        self._err_lbl.configure(text="")

    def _open_multi_voice(self):
        from app.multi_voice_window import MultiVoiceWindow
        MultiVoiceWindow(self)

    def _on_close(self):
        self.player.quit()
        self.destroy()


def _fmt_time(secs: float) -> str:
    if not secs or not math.isfinite(secs):
        return "0:00"
    return f"{int(secs//60)}:{int(secs%60):02d}"
