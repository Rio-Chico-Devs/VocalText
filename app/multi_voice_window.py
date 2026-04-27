"""
Multi-Voice Window – generazione batch di voci multiple.
Finestra separata (CTkToplevel); non modifica window.py.
"""
from __future__ import annotations
import os
import math
import wave
import struct
import threading
import tempfile
import tkinter as tk
import customtkinter as ctk
from dataclasses import dataclass, field
from tkinter import filedialog

from app.audio.player import AudioPlayer

ACCENT   = "#4ecca3"
ACCENT_D = "#3aaf8d"
DANGER   = "#ff6b6b"
WARN     = "#f4a261"

LANGUAGES = {
    "it": "Italiano", "en": "English", "es": "Español",
    "fr": "Français", "de": "Deutsch", "pt": "Português",
    "pl": "Polski",   "ru": "Русский", "nl": "Nederlands",
    "cs": "Čeština",  "zh-cn": "中文",  "hu": "Magyar",
    "ko": "한국어",    "ja": "日本語",   "ar": "العربية",
    "hi": "हिंदी",
}

STATUS_ICON  = {"idle": "○", "generating": "⏳", "done": "●", "error": "✗"}
STATUS_COLOR = {"idle": "gray", "generating": WARN, "done": ACCENT, "error": DANGER}


@dataclass
class VoiceEntry:
    id: str
    label: str
    text: str = ""
    status: str = "idle"
    audio_path: str | None = None
    audio_original: str | None = None
    edit_pending: bool = False
    error_msg: str | None = None


def _fmt_time(secs: float) -> str:
    if not secs or not math.isfinite(secs):
        return "0:00"
    return f"{int(secs // 60)}:{int(secs % 60):02d}"


class MultiVoiceWindow(ctk.CTkToplevel):

    def __init__(self, parent_app):
        super().__init__(parent_app)
        self.title("Multi-Voci – VocalText")
        self.geometry("1200x720")
        self.minsize(900, 560)

        self._app = parent_app
        self.player = AudioPlayer()

        # Voice list state
        self._voices: list[VoiceEntry] = []
        self._selected_id: str | None = None
        self._row_widgets: dict[str, dict] = {}
        self._counter = 0

        # Generation queue
        self._gen_queue: list[str] = []
        self._generating = False
        self._stop_req = False

        # Player state (for currently selected voice)
        self._audio_path: str | None = None
        self._audio_original: str | None = None
        self._edit_pending = False
        self._sel_start: float | None = None
        self._sel_end:   float | None = None
        self._sel_drag_x0: int | None = None

        self._build()
        self._add_voice()
        self.after(200, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ══════════════════════════════════════════════════════════════════════
    #  Layout
    # ══════════════════════════════════════════════════════════════════════

    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_left()
        self._build_right()
        self._build_bottom()

    # ── Left panel ────────────────────────────────────────────────────────

    def _build_left(self):
        left = ctk.CTkFrame(self, width=240, corner_radius=0)
        left.grid(row=0, column=0, rowspan=2, sticky="nsew")
        left.grid_propagate(False)
        left.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(left, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        ctk.CTkLabel(hdr, text="Voci",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=ACCENT).pack(side="left")
        ctk.CTkButton(hdr, text="+ Aggiungi", width=84, height=26,
                      fg_color=ACCENT, hover_color=ACCENT_D,
                      text_color="#0a1810",
                      font=ctk.CTkFont(size=11, weight="bold"),
                      command=self._add_voice).pack(side="right")

        self._voice_scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self._voice_scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)

        sep = ctk.CTkFrame(left, height=1, fg_color=("gray70", "gray30"))
        sep.grid(row=2, column=0, sticky="ew", padx=12, pady=4)

        cfg = ctk.CTkFrame(left, fg_color="transparent")
        cfg.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))

        ctk.CTkLabel(cfg, text="IMPOSTAZIONI CONDIVISE",
                     font=ctk.CTkFont(size=9, weight="bold"),
                     text_color="gray").pack(anchor="w")

        ctk.CTkLabel(cfg, text="Lingua",
                     font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(6, 1))
        self._lang = tk.StringVar(value="it")
        self._lang_menu = ctk.CTkOptionMenu(
            cfg,
            values=list(LANGUAGES.values()),
            command=self._on_lang_change,
            width=210, height=28,
            fg_color=("gray85", "gray20"))
        self._lang_menu.set(LANGUAGES["it"])
        self._lang_menu.pack(anchor="w")

        self._polish = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(cfg, text="Post-processing audio",
                        variable=self._polish,
                        checkbox_width=16, checkbox_height=16,
                        fg_color=ACCENT, hover_color=ACCENT_D).pack(anchor="w", pady=(8, 0))

    def _on_lang_change(self, display: str):
        for k, v in LANGUAGES.items():
            if v == display:
                self._lang.set(k)
                break

    # ── Right panel ───────────────────────────────────────────────────────

    def _build_right(self):
        right = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=0)
        right.grid_columnconfigure(0, weight=1)
        self._build_editor(right)
        self._build_player(right)

    def _build_editor(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=(10, 4))
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self._voice_label = ctk.CTkLabel(
            frame, text="Aggiungi una voce e scrivi il testo",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT)
        self._voice_label.grid(row=0, column=0, sticky="w", pady=(0, 4))

        self._textbox = ctk.CTkTextbox(frame, font=ctk.CTkFont(size=13),
                                       wrap="word", height=130)
        self._textbox.grid(row=1, column=0, sticky="nsew")
        self._textbox.bind("<KeyRelease>", self._on_text_edit)

    def _on_text_edit(self, _=None):
        v = self._cur_voice()
        if v:
            v.text = self._textbox.get("1.0", "end").strip()

    # ── Player card ───────────────────────────────────────────────────────

    def _build_player(self, parent):
        self._player_card = ctk.CTkFrame(parent, corner_radius=10)
        self._player_card.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self._player_card.grid_columnconfigure(0, weight=1)
        self._player_card.grid_remove()

        # Waveform
        self._wave_canvas = tk.Canvas(
            self._player_card, height=70, bg="#111827",
            highlightthickness=0, cursor="crosshair")
        self._wave_canvas.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        self._wave_canvas.bind("<ButtonPress-1>",  self._sel_press)
        self._wave_canvas.bind("<B1-Motion>",       self._sel_motion)
        self._wave_canvas.bind("<ButtonRelease-1>", self._sel_release)

        # Time row
        tc = ctk.CTkFrame(self._player_card, fg_color="transparent")
        tc.grid(row=1, column=0, sticky="ew", padx=10)
        self._time_cur = ctk.CTkLabel(tc, text="0:00",
                                      font=ctk.CTkFont(size=10), text_color="gray")
        self._time_cur.pack(side="left")
        self._time_tot = ctk.CTkLabel(tc, text="0:00",
                                      font=ctk.CTkFont(size=10), text_color="gray")
        self._time_tot.pack(side="right")

        # Seek slider
        self._seek_var = tk.DoubleVar(value=0.0)
        ctk.CTkSlider(
            self._player_card, from_=0, to=100,
            variable=self._seek_var, command=self._on_seek,
            progress_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENT_D,
        ).grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 4))

        # Transport
        tr = ctk.CTkFrame(self._player_card, fg_color="transparent")
        tr.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 2))
        self._play_btn = ctk.CTkButton(
            tr, text="▶", width=44, height=36,
            fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._toggle_play)
        self._play_btn.pack(side="left", padx=(0, 6))
        ctk.CTkButton(tr, text="⏮", width=36, height=36,
                      fg_color="transparent", border_width=1,
                      font=ctk.CTkFont(size=14),
                      command=lambda: self.player.restart()).pack(side="left")

        # Edit bar (shown only when there is a selection)
        self._edit_bar = ctk.CTkFrame(self._player_card, fg_color="transparent")
        self._edit_bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 2))
        self._edit_bar.grid_remove()
        self._sel_lbl = ctk.CTkLabel(self._edit_bar, text="",
                                     font=ctk.CTkFont(size=10), text_color="gray")
        self._sel_lbl.pack(side="left", padx=(0, 8))
        ctk.CTkButton(self._edit_bar, text="✂ Elimina", width=90, height=26,
                      fg_color="transparent", border_width=1, text_color=DANGER,
                      font=ctk.CTkFont(size=11),
                      command=lambda: self._apply_edit("delete")).pack(side="left", padx=(0, 4))
        ctk.CTkButton(self._edit_bar, text="✂ Ritaglia", width=90, height=26,
                      fg_color="transparent", border_width=1, text_color=WARN,
                      font=ctk.CTkFont(size=11),
                      command=lambda: self._apply_edit("crop")).pack(side="left", padx=(0, 8))
        ctk.CTkButton(self._edit_bar, text="✕", width=26, height=26,
                      fg_color="transparent", text_color="gray",
                      font=ctk.CTkFont(size=11),
                      command=self._edit_clear_sel).pack(side="left")

        # Confirm bar
        self._confirm_bar = ctk.CTkFrame(
            self._player_card, fg_color=("gray90", "#1e2a1e"), corner_radius=6)
        self._confirm_bar.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 4))
        self._confirm_bar.grid_remove()
        ctk.CTkLabel(self._confirm_bar, text="Ascolta l'anteprima, poi:",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(side="left", padx=(8, 6))
        ctk.CTkButton(self._confirm_bar, text="✓  Conferma", height=28, width=100,
                      fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
                      font=ctk.CTkFont(size=11),
                      command=self._confirm_edit).pack(side="left", padx=(0, 6))
        ctk.CTkButton(self._confirm_bar, text="↩  Annulla", height=28, width=90,
                      fg_color="transparent", border_width=1, text_color=WARN,
                      font=ctk.CTkFont(size=11),
                      command=self._undo_edit).pack(side="left")

        # Footer
        foot = ctk.CTkFrame(self._player_card, fg_color="transparent")
        foot.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 8))
        self._clean_btn = ctk.CTkButton(
            foot, text="✨ Pulisci voce", width=130, height=28,
            fg_color="transparent", border_width=1, text_color=ACCENT,
            font=ctk.CTkFont(size=11), command=self._clean_voice)
        self._clean_btn.pack(side="left", padx=(0, 4))
        self._speed_btn = ctk.CTkButton(
            foot, text="⏱ Velocità", width=100, height=28,
            fg_color="transparent", border_width=1, text_color=ACCENT,
            font=ctk.CTkFont(size=11), command=self._show_speed_dialog)
        self._speed_btn.pack(side="left", padx=(0, 4))
        ctk.CTkButton(foot, text="Esporta…", width=90, height=28,
                      fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
                      font=ctk.CTkFont(size=11, weight="bold"),
                      command=self._show_export_dialog).pack(side="left")
        self._dur_lbl = ctk.CTkLabel(foot, text="",
                                     font=ctk.CTkFont(size=10), text_color="gray")
        self._dur_lbl.pack(side="right")

        # Status label
        self._status_lbl = ctk.CTkLabel(
            self._player_card, text="",
            font=ctk.CTkFont(size=11), text_color=DANGER)
        self._status_lbl.grid(row=7, column=0, sticky="w", padx=12, pady=(0, 4))

    # ── Bottom bar ────────────────────────────────────────────────────────

    def _build_bottom(self):
        bar = ctk.CTkFrame(self, corner_radius=0, height=54)
        bar.grid(row=1, column=1, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(2, weight=1)

        self._gen_btn = ctk.CTkButton(
            bar, text="▶  Genera tutte", width=150, height=36,
            fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start_generation)
        self._gen_btn.grid(row=0, column=0, padx=(12, 6), pady=9)

        self._stop_btn = ctk.CTkButton(
            bar, text="⏹ Stop", width=80, height=36,
            fg_color="transparent", border_width=1, text_color=DANGER,
            font=ctk.CTkFont(size=12), state="disabled",
            command=self._stop_generation)
        self._stop_btn.grid(row=0, column=1, padx=(0, 12), pady=9)

        self._prog_lbl = ctk.CTkLabel(
            bar, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self._prog_lbl.grid(row=0, column=2, sticky="w", padx=4)

        self._prog_bar = ctk.CTkProgressBar(bar, width=260, height=8,
                                             progress_color=ACCENT)
        self._prog_bar.grid(row=0, column=3, padx=(0, 16), pady=9)
        self._prog_bar.set(0)
