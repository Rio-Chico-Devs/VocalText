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

from app.tts.engine import TTSEngine, Voice, PIPER_CATALOG
from app.audio.player import AudioPlayer

ACCENT   = "#4ecca3"
ACCENT_D = "#3aaf8d"
DANGER   = "#ff6b6b"


class VocalTextApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("VocalText")
        self.geometry("1080x680")
        self.minsize(800, 560)

        self.engine  = TTSEngine()
        self.player  = AudioPlayer()

        self._voice: Voice | None = None
        self._speed   = tk.DoubleVar(value=1.0)
        self._volume  = tk.DoubleVar(value=1.0)
        self._audio_path: str | None = None
        self._seek_dragging = False

        self._build()
        self.after(120, self._load_voices)
        self.after(120, self._check_engine)
        self.after(200, self._tick)           # player position ticker
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
        sb = ctk.CTkFrame(self, width=220, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(2, weight=1)

        # Header
        hdr = ctk.CTkFrame(sb, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        ctk.CTkLabel(hdr, text="VocalText", font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=ACCENT).pack(side="left")
        self._theme_btn = ctk.CTkButton(hdr, text="☀", width=28, height=28,
                                        fg_color="transparent", hover_color=("gray80","gray30"),
                                        command=self._toggle_theme)
        self._theme_btn.pack(side="right")

        # Engine status
        self._status_lbl = ctk.CTkLabel(sb, text="● Rilevamento…",
                                        font=ctk.CTkFont(size=11), anchor="w",
                                        text_color="gray")
        self._status_lbl.grid(row=1, column=0, sticky="ew", padx=14, pady=(8, 4))

        # Voice list
        ctk.CTkLabel(sb, text="VOCE", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray", anchor="w").grid(row=3, column=0,
                     sticky="ew", padx=14, pady=(10, 2))

        self._voice_frame = ctk.CTkScrollableFrame(sb, fg_color="transparent", label_text="")
        self._voice_frame.grid(row=4, column=0, sticky="nsew", padx=8)
        sb.grid_rowconfigure(4, weight=1)

        # Parameters
        params = ctk.CTkFrame(sb, fg_color="transparent")
        params.grid(row=5, column=0, sticky="ew", padx=14, pady=(6, 14))

        ctk.CTkLabel(params, text="PARAMETRI", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray", anchor="w").pack(fill="x")

        self._speed_lbl = ctk.CTkLabel(params, text="Velocità  1.00×",
                                       font=ctk.CTkFont(size=12), anchor="w")
        self._speed_lbl.pack(fill="x", pady=(8, 0))
        ctk.CTkSlider(params, from_=0.5, to=2.0, variable=self._speed,
                      button_color=ACCENT, button_hover_color=ACCENT_D,
                      progress_color=ACCENT,
                      command=lambda v: self._speed_lbl.configure(
                          text=f"Velocità  {v:.2f}×")).pack(fill="x")

        self._vol_lbl = ctk.CTkLabel(params, text="Volume  100%",
                                     font=ctk.CTkFont(size=12), anchor="w")
        self._vol_lbl.pack(fill="x", pady=(10, 0))
        ctk.CTkSlider(params, from_=0.1, to=1.0, variable=self._volume,
                      button_color=ACCENT, button_hover_color=ACCENT_D,
                      progress_color=ACCENT,
                      command=lambda v: self._vol_lbl.configure(
                          text=f"Volume  {int(v*100)}%")).pack(fill="x")

    # ── Main area ──────────────────────────────────────────────────────────

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        # ── Editor card ──
        editor_card = ctk.CTkFrame(main)
        editor_card.grid(row=0, column=0, sticky="ew")
        editor_card.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(editor_card, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        ctk.CTkLabel(toolbar, text="TESTO", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray").pack(side="left")
        ctk.CTkButton(toolbar, text="Incolla", width=70, height=26,
                      fg_color="transparent", border_width=1,
                      command=self._paste).pack(side="right", padx=(4, 0))
        ctk.CTkButton(toolbar, text="Cancella", width=70, height=26,
                      fg_color="transparent", border_width=1,
                      command=self._clear_text).pack(side="right")

        self._textbox = ctk.CTkTextbox(editor_card, height=200, wrap="word",
                                       font=ctk.CTkFont(size=14))
        self._textbox.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 0))
        self._textbox.bind("<KeyRelease>", self._on_text_change)
        self._textbox.insert("0.0",
            "Scrivi qui il testo da convertire in voce…\n\n"
            "Premi Ctrl+Invio oppure il pulsante \"Genera Audio\" per iniziare.")
        self._textbox.bind("<FocusIn>", self._clear_placeholder)

        foot = ctk.CTkFrame(editor_card, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 10))
        self._char_lbl = ctk.CTkLabel(foot, text="0 / 5000 caratteri",
                                      font=ctk.CTkFont(size=11), text_color="gray")
        self._char_lbl.pack(side="left")
        self._word_lbl = ctk.CTkLabel(foot, text="0 parole",
                                      font=ctk.CTkFont(size=11), text_color="gray")
        self._word_lbl.pack(side="right")

        # ── Generate button ──
        self._gen_btn = ctk.CTkButton(
            main, text="▶  Genera Audio",
            height=48, font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
            command=self._generate)
        self._gen_btn.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.bind("<Control-Return>", lambda _: self._generate())

        # ── Error label ──
        self._err_lbl = ctk.CTkLabel(main, text="", text_color=DANGER,
                                     font=ctk.CTkFont(size=12), wraplength=600, anchor="w")
        self._err_lbl.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        # ── Player card ──
        self._player_card = ctk.CTkFrame(main)
        self._player_card.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self._player_card.grid_columnconfigure(0, weight=1)
        self._player_card.grid_remove()   # hidden until first generation
        self._build_player(self._player_card)

    def _build_player(self, parent):
        # Waveform canvas
        self._wave_canvas = tk.Canvas(parent, height=56, bg="#1d2335",
                                      highlightthickness=0, cursor="hand2")
        self._wave_canvas.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        self._wave_canvas.bind("<Button-1>", self._seek_click)

        # Controls row
        ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl.grid(row=1, column=0, sticky="ew", padx=10, pady=6)
        ctrl.grid_columnconfigure(2, weight=1)

        self._play_btn = ctk.CTkButton(ctrl, text="▶", width=38, height=38,
                                       fg_color=ACCENT, hover_color=ACCENT_D,
                                       text_color="#0a1810", font=ctk.CTkFont(size=16),
                                       command=self._toggle_play)
        self._play_btn.grid(row=0, column=0, padx=(0, 6))

        self._time_cur = ctk.CTkLabel(ctrl, text="0:00",
                                      font=ctk.CTkFont(size=12, family="monospace"), width=38)
        self._time_cur.grid(row=0, column=1)

        self._seek_var = tk.DoubleVar(value=0)
        self._seek_bar = ctk.CTkSlider(ctrl, from_=0, to=100, variable=self._seek_var,
                                       button_color=ACCENT, button_hover_color=ACCENT_D,
                                       progress_color=ACCENT,
                                       command=self._seek_drag)
        self._seek_bar.grid(row=0, column=2, sticky="ew", padx=6)

        self._time_tot = ctk.CTkLabel(ctrl, text="0:00",
                                      font=ctk.CTkFont(size=12, family="monospace"), width=38)
        self._time_tot.grid(row=0, column=3)

        ctk.CTkButton(ctrl, text="⟲", width=32, height=32,
                      fg_color="transparent", border_width=1,
                      command=lambda: (self.player.restart(), self.player.play())).grid(
                          row=0, column=4, padx=(6, 0))

        # Export row
        exp = ctk.CTkFrame(parent, fg_color="transparent")
        exp.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        ctk.CTkButton(exp, text="⬇  Salva WAV", width=120, height=30,
                      fg_color="transparent", border_width=1,
                      command=self._export_wav).pack(side="left")
        self._dur_lbl = ctk.CTkLabel(exp, text="", font=ctk.CTkFont(size=11),
                                     text_color="gray")
        self._dur_lbl.pack(side="right")

    # ══════════════════════════════════════════════════════════════════════
    #  Engine & voices
    # ══════════════════════════════════════════════════════════════════════

    def _check_engine(self):
        level, msg = self.engine.status()
        colors = {"ok": ACCENT, "warn": "#f4a261", "error": DANGER}
        dot = {"ok": "●", "warn": "●", "error": "●"}
        self._status_lbl.configure(text=f"{dot[level]} {msg}",
                                   text_color=colors[level])

    def _load_voices(self):
        def _fetch():
            voices = self.engine.get_all_voices()
            self.after(0, lambda: self._render_voices(voices))

        threading.Thread(target=_fetch, daemon=True).start()

    def _render_voices(self, voices: list[Voice]):
        for w in self._voice_frame.winfo_children():
            w.destroy()

        if not voices:
            ctk.CTkLabel(self._voice_frame,
                         text="Nessuna voce trovata.\nInstalla espeak-ng o\naggiungi modelli Piper.",
                         font=ctk.CTkFont(size=11), text_color="gray",
                         justify="left").pack(anchor="w", padx=4, pady=6)
            return

        # Group by engine
        piper_voices = [v for v in voices if v.engine == "piper"]
        sys_voices   = [v for v in voices if v.engine != "piper"]

        if piper_voices:
            self._section_label("Piper · Neurale")
            for v in piper_voices:
                self._voice_btn(v)

        if sys_voices:
            self._section_label("Sistema · Base")
            for v in sys_voices[:12]:   # cap at 12 system voices
                self._voice_btn(v)

        # auto-select first
        if voices and self._voice is None:
            self._select_voice(voices[0])

    def _section_label(self, text: str):
        ctk.CTkLabel(self._voice_frame, text=text,
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray", anchor="w").pack(
                         fill="x", padx=4, pady=(8, 2))

    def _voice_btn(self, voice: Voice):
        quality_colors = {"high": ACCENT, "medium": "#f4a261", "low": "gray"}
        color = quality_colors.get(voice.quality, "gray")

        row = ctk.CTkFrame(self._voice_frame, fg_color="transparent", cursor="hand2")
        row.pack(fill="x", pady=1)

        indicator = ctk.CTkLabel(row, text="●", font=ctk.CTkFont(size=10),
                                 text_color=color, width=14)
        indicator.pack(side="left", padx=(4, 2))

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        name_lbl = ctk.CTkLabel(info, text=voice.name, font=ctk.CTkFont(size=13),
                                anchor="w")
        name_lbl.pack(fill="x")
        meta_lbl = ctk.CTkLabel(info,
                                text=f"{voice.lang.upper()} · {voice.quality}",
                                font=ctk.CTkFont(size=10), text_color="gray",
                                anchor="w")
        meta_lbl.pack(fill="x")

        # Store ref for selection highlight
        row._voice = voice
        row._name_lbl = name_lbl

        for w in (row, indicator, info, name_lbl, meta_lbl):
            w.bind("<Button-1>", lambda _, v=voice, r=row: self._select_voice(v, r))

    def _select_voice(self, voice: Voice, row_widget=None):
        self._voice = voice
        # Reset all rows
        for w in self._voice_frame.winfo_children():
            if hasattr(w, "_name_lbl"):
                w._name_lbl.configure(text_color=("black", "white"))
            if isinstance(w, ctk.CTkFrame):
                w.configure(fg_color="transparent")
        # Highlight selected
        if row_widget:
            row_widget.configure(fg_color=("gray85", "#1e2d24"))
            row_widget._name_lbl.configure(text_color=ACCENT)

    # ══════════════════════════════════════════════════════════════════════
    #  Text editor helpers
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
        color = DANGER if chars > 4800 else ("#f4a261" if chars > 4000 else "gray")
        self._char_lbl.configure(text=f"{chars} / 5000 caratteri", text_color=color)
        self._word_lbl.configure(text=f"{words} parole")

    def _get_text(self) -> str:
        if self._placeholder_active:
            return ""
        return self._textbox.get("0.0", "end").strip()

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

        self._gen_btn.configure(state="disabled", text="⏳  Generazione in corso…")
        self._hide_error()

        self.engine.generate(
            text=text,
            voice=self._voice,
            speed=self._speed.get(),
            volume=self._volume.get(),
            on_done=lambda path: self.after(0, lambda: self._on_audio_ready(path)),
            on_error=lambda msg:  self.after(0, lambda: self._on_gen_error(msg)),
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
    #  Audio player
    # ══════════════════════════════════════════════════════════════════════

    def _toggle_play(self):
        if not self._audio_path:
            return
        if self.player.is_playing:
            self.player.pause()
            self._play_btn.configure(text="▶")
        else:
            self.player.play(on_end=lambda: self.after(0, self._on_play_end))
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
        pct = max(0.0, min(event.x / w, 1.0))
        secs = pct * self.player.duration
        self.player.seek(secs)
        self.player.play(on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

    def _tick(self):
        """Called every 200 ms to update position display."""
        if self.player.is_playing and self.player.duration > 0:
            pos  = self.player.position
            pct  = (pos / self.player.duration) * 100
            if not self._seek_dragging:
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
        self._wave_canvas.create_line(x, 0, x, 56, fill=ACCENT, width=2, tags="playhead")

    # ══════════════════════════════════════════════════════════════════════
    #  Waveform
    # ══════════════════════════════════════════════════════════════════════

    def _draw_waveform(self, path: str):
        self.update_idletasks()
        W = self._wave_canvas.winfo_width()
        H = 56
        if W <= 1:
            W = 700
        self._wave_canvas.delete("wave")

        try:
            with wave.open(path, "rb") as wf:
                n_frames   = wf.getnframes()
                sampwidth  = wf.getsampwidth()
                n_channels = wf.getnchannels()
                raw = wf.readframes(n_frames)

            # Decode to mono float
            fmt = {1: "b", 2: "h", 4: "i"}.get(sampwidth, "h")
            samples = struct.unpack(f"<{n_frames * n_channels}{fmt}", raw)
            # Mix to mono
            if n_channels > 1:
                samples = [samples[i] for i in range(0, len(samples), n_channels)]
            max_val = 2 ** (sampwidth * 8 - 1)
            norm = [s / max_val for s in samples]

            step = max(1, len(norm) // W)
            bars = [max(abs(s) for s in norm[i:i+step]) for i in range(0, len(norm), step)]
            bars = bars[:W]

            for x, amp in enumerate(bars):
                bh = max(2, amp * (H - 8))
                y0 = (H - bh) / 2
                y1 = y0 + bh
                alpha = int(80 + 120 * amp)
                color = f"#{int(0x4e):02x}{int(0xcc):02x}{int(0xa3):02x}"
                self._wave_canvas.create_line(x, y0, x, y1, fill=color, tags="wave")
        except Exception:
            # Fallback: random-ish bars
            import random
            random.seed(42)
            for x in range(W):
                amp = 0.2 + 0.6 * abs(math.sin(x * 0.12)) * (0.5 + 0.5 * random.random())
                bh = max(2, amp * (H - 8))
                y0 = (H - bh) / 2
                self._wave_canvas.create_line(x, y0, x, y0 + bh, fill=ACCENT, tags="wave")

    # ══════════════════════════════════════════════════════════════════════
    #  Export
    # ══════════════════════════════════════════════════════════════════════

    def _export_wav(self):
        if not self._audio_path:
            return
        dest = filedialog.asksaveasfilename(
            title="Salva traccia audio",
            defaultextension=".wav",
            filetypes=[("WAV audio", "*.wav"), ("Tutti i file", "*.*")],
            initialfile=f"VocalText_{self._voice.name if self._voice else 'output'}.wav",
        )
        if dest:
            import shutil
            shutil.copy2(self._audio_path, dest)

    # ══════════════════════════════════════════════════════════════════════
    #  Theme / helpers
    # ══════════════════════════════════════════════════════════════════════

    def _toggle_theme(self):
        current = ctk.get_appearance_mode()
        new = "Light" if current == "Dark" else "Dark"
        ctk.set_appearance_mode(new)
        self._theme_btn.configure(text="☀" if new == "Dark" else "🌙")
        self._wave_canvas.configure(bg="#1d2335" if new == "Dark" else "#e8eaf0")

    def _show_error(self, msg: str):
        self._err_lbl.configure(text=f"⚠  {msg}")

    def _hide_error(self):
        self._err_lbl.configure(text="")

    def _on_close(self):
        self.player.quit()
        self.destroy()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_time(secs: float) -> str:
    if not secs or not math.isfinite(secs):
        return "0:00"
    m = int(secs // 60)
    s = int(secs % 60)
    return f"{m}:{s:02d}"
