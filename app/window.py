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

        # ── Parametri ──
        params = ctk.CTkFrame(sb, fg_color="transparent")
        params.grid(row=6, column=0, sticky="ew", padx=14, pady=(8, 14))

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
        self._wave_canvas = tk.Canvas(
            parent, height=56, bg="#1d2335",
            highlightthickness=0, cursor="hand2")
        self._wave_canvas.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        self._wave_canvas.bind("<Button-1>", self._seek_click)

        ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl.grid(row=1, column=0, sticky="ew", padx=10, pady=6)
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

        exp = ctk.CTkFrame(parent, fg_color="transparent")
        exp.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        ctk.CTkButton(
            exp, text="⬇  Salva WAV", width=120, height=30,
            fg_color="transparent", border_width=1,
            command=self._export_wav).pack(side="left")
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
        self._gen_btn.configure(state="normal", text="▶  Genera Audio")
        duration = self.player.load(path)
        self._time_tot.configure(text=_fmt_time(duration))
        self._dur_lbl.configure(text=f"{_fmt_time(duration)} · WAV")
        self._draw_waveform(path)
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

    def _seek_click(self, event):
        w = self._wave_canvas.winfo_width()
        if w <= 0:
            return
        pct  = max(0.0, min(event.x / w, 1.0))
        secs = pct * self.player.duration
        self.player.seek(secs)
        self.player.play(
            on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

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

    def _export_wav(self):
        if not self._audio_path:
            return
        name = self._voice.name if self._voice else "output"
        dest = filedialog.asksaveasfilename(
            title="Salva traccia audio",
            defaultextension=".wav",
            filetypes=[("WAV audio", "*.wav"), ("Tutti i file", "*.*")],
            initialfile=f"VocalText_{name}.wav")
        if dest:
            import shutil
            shutil.copy2(self._audio_path, dest)

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

    def _on_close(self):
        self.player.quit()
        self.destroy()


def _fmt_time(secs: float) -> str:
    if not secs or not math.isfinite(secs):
        return "0:00"
    return f"{int(secs//60)}:{int(secs%60):02d}"
