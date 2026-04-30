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
from dataclasses import dataclass
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

EMOTIONS = [
    "Generico", "Narrazione", "Rabbia", "Tristezza",
    "Pianto", "Felicità", "Sfida", "Urla", "Sussurro",
]

STATUS_ICON  = {"idle": "○", "generating": "⏳", "done": "●", "error": "✗"}
STATUS_COLOR = {"idle": "gray", "generating": WARN, "done": ACCENT, "error": DANGER}


@dataclass
class VoiceEntry:
    id: str
    label: str
    text: str = ""
    emotion: str = "Generico"
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
        self._gen_total = 0
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
        frame.grid_rowconfigure(2, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self._voice_label = ctk.CTkLabel(
            frame, text="Aggiungi una voce e scrivi il testo",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT)
        self._voice_label.grid(row=0, column=0, sticky="w", pady=(0, 2))

        # Emotion selector per-voce
        em_row = ctk.CTkFrame(frame, fg_color="transparent")
        em_row.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkLabel(em_row, text="Tono:",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(side="left")
        self._emotion_var = tk.StringVar(value="Generico")
        self._emotion_menu_mv = ctk.CTkOptionMenu(
            em_row, variable=self._emotion_var,
            values=EMOTIONS,
            command=self._on_mv_emotion_change,
            fg_color=("gray85", "gray25"),
            button_color=ACCENT, button_hover_color=ACCENT_D,
            width=160, height=26,
            dynamic_resizing=False)
        self._emotion_menu_mv.pack(side="left", padx=(6, 0))
        self._emotion_hint = ctk.CTkLabel(
            em_row, text="", font=ctk.CTkFont(size=10),
            text_color="gray")
        self._emotion_hint.pack(side="left", padx=(8, 0))

        self._textbox = ctk.CTkTextbox(frame, font=ctk.CTkFont(size=13),
                                       wrap="word", height=130)
        self._textbox.grid(row=2, column=0, sticky="nsew")
        self._textbox.bind("<KeyRelease>", self._on_text_edit)

    def _on_text_edit(self, _=None):
        v = self._cur_voice()
        if v:
            v.text = self._textbox.get("1.0", "end").strip()

    def _on_mv_emotion_change(self, value: str):
        v = self._cur_voice()
        if v:
            v.emotion = value
        self._update_emotion_hint(value)

    def _update_emotion_hint(self, emotion: str):
        """Mostra se il tono ha un file dedicato o se userà il fallback generico."""
        if emotion == "Generico":
            self._emotion_hint.configure(text="")
            return
        em_ref = getattr(self._app, "_emotion_refs", {}).get(emotion)
        if em_ref and os.path.exists(em_ref):
            self._emotion_hint.configure(text="● file caricato", text_color=ACCENT)
        else:
            self._emotion_hint.configure(
                text="○ nessun file → usa generico", text_color=WARN)

    def _get_voice_ref(self, v: "VoiceEntry") -> "str | None":
        """WAV di riferimento per la voce v: usa il tono specifico se caricato."""
        if v.emotion and v.emotion != "Generico":
            em_ref = getattr(self._app, "_emotion_refs", {}).get(v.emotion)
            if em_ref and os.path.exists(em_ref):
                return em_ref
        return self._app._ref_wav

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
        self._regen_btn = ctk.CTkButton(
            foot, text="↺ Rifai", width=74, height=28,
            fg_color="transparent", border_width=1, text_color=WARN,
            font=ctk.CTkFont(size=11), state="disabled",
            command=self._regenerate_voice)
        self._regen_btn.pack(side="left", padx=(0, 4))
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

    # ══════════════════════════════════════════════════════════════════════
    #  Voice list management
    # ══════════════════════════════════════════════════════════════════════

    def _add_voice(self):
        self._counter += 1
        vid = f"v{self._counter}"
        entry = VoiceEntry(id=vid, label=f"Voce {self._counter}")
        self._voices.append(entry)
        self._build_voice_row(entry)
        self._select_voice(vid)

    def _build_voice_row(self, entry: VoiceEntry):
        row = ctk.CTkFrame(self._voice_scroll, corner_radius=6,
                           fg_color=("gray88", "gray20"), height=46)
        row.pack(fill="x", pady=3, padx=2)
        row.pack_propagate(False)
        row.grid_columnconfigure(1, weight=1)

        icon = ctk.CTkLabel(row, text=STATUS_ICON[entry.status], width=22,
                            font=ctk.CTkFont(size=13),
                            text_color=STATUS_COLOR[entry.status])
        icon.grid(row=0, column=0, padx=(8, 2), sticky="ns")

        name = ctk.CTkLabel(row, text=entry.label,
                            font=ctk.CTkFont(size=12), anchor="w")
        name.grid(row=0, column=1, sticky="ew", padx=2)

        del_btn = ctk.CTkButton(row, text="✕", width=24, height=24,
                                fg_color="transparent", hover_color=DANGER,
                                text_color="gray", font=ctk.CTkFont(size=10),
                                command=lambda vid=entry.id: self._delete_voice(vid))
        del_btn.grid(row=0, column=2, padx=(0, 4))

        for w in (row, icon, name):
            w.bind("<Button-1>", lambda e, vid=entry.id: self._select_voice(vid))

        self._row_widgets[entry.id] = {"row": row, "icon": icon, "name": name}

    def _select_voice(self, vid: str):
        # Save current text and player state — but only if switching to a
        # DIFFERENT voice. Re-selecting the same voice (e.g. after generation
        # completes) must not overwrite freshly-set audio_path with stale
        # player state.
        if self._selected_id and self._selected_id != vid:
            old = self._get_voice(self._selected_id)
            if old:
                old.text = self._textbox.get("1.0", "end").strip()
                old.audio_path     = self._audio_path
                old.audio_original = self._audio_original
                old.edit_pending   = self._edit_pending

        self._selected_id = vid
        v = self._get_voice(vid)
        if not v:
            return

        # Highlight row
        for vid2, w in self._row_widgets.items():
            w["row"].configure(border_width=2 if vid2 == vid else 0,
                               border_color=ACCENT)

        # Update editor
        self._voice_label.configure(text=v.label)
        self._textbox.delete("1.0", "end")
        self._textbox.insert("1.0", v.text)
        self._emotion_var.set(v.emotion)
        self._update_emotion_hint(v.emotion)

        # Update player
        self._edit_clear_sel()
        self.player.stop()
        self._audio_path     = v.audio_path
        self._audio_original = v.audio_original
        self._edit_pending   = v.edit_pending

        if v.audio_path and os.path.exists(v.audio_path):
            duration = self.player.load(v.audio_path)
            self._time_tot.configure(text=_fmt_time(duration))
            self._dur_lbl.configure(text=f"{_fmt_time(duration)} · WAV")
            self._draw_waveform(v.audio_path)
            self._seek_var.set(0)
            self._play_btn.configure(text="▶")
            self._player_card.grid()
            if self._edit_pending:
                self._confirm_bar.grid()
            else:
                self._confirm_bar.grid_remove()
        else:
            self._player_card.grid_remove()
            self._confirm_bar.grid_remove()
        self._regen_btn.configure(
            state="normal" if v.status in ("done", "error") else "disabled")

    def _delete_voice(self, vid: str):
        v = self._get_voice(vid)
        if not v or v.status == "generating":
            return
        for p in [v.audio_path, v.audio_original]:
            if p and os.path.exists(p):
                try: os.unlink(p)
                except Exception: pass
        self._voices = [x for x in self._voices if x.id != vid]
        w = self._row_widgets.pop(vid, None)
        if w:
            w["row"].destroy()
        if self._selected_id == vid:
            self._selected_id = None
            self._audio_path = None
            self._player_card.grid_remove()
            if self._voices:
                self._select_voice(self._voices[-1].id)

    def _update_voice_row(self, vid: str):
        v = self._get_voice(vid)
        w = self._row_widgets.get(vid)
        if not v or not w:
            return
        w["icon"].configure(text=STATUS_ICON[v.status],
                            text_color=STATUS_COLOR[v.status])
        if vid == self._selected_id:
            self._regen_btn.configure(
                state="normal" if v.status in ("done", "error") else "disabled")

    def _get_voice(self, vid: str) -> VoiceEntry | None:
        return next((v for v in self._voices if v.id == vid), None)

    def _cur_voice(self) -> VoiceEntry | None:
        return self._get_voice(self._selected_id) if self._selected_id else None

    # ══════════════════════════════════════════════════════════════════════
    #  Generation queue
    # ══════════════════════════════════════════════════════════════════════

    def _start_generation(self):
        if self._generating:
            return
        # Save current text first
        v = self._cur_voice()
        if v:
            v.text = self._textbox.get("1.0", "end").strip()

        self._gen_queue = [v.id for v in self._voices
                           if v.status == "idle" and v.text.strip()]
        if not self._gen_queue:
            return

        self._gen_total = len(self._gen_queue)
        self._stop_req = False
        self._generating = True
        self._gen_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._generate_next()

    def _stop_generation(self):
        self._stop_req = True
        self._stop_btn.configure(state="disabled")

    def _generate_next(self):
        if self._stop_req or not self._gen_queue:
            self._on_generation_done()
            return

        vid = self._gen_queue.pop(0)
        v = self._get_voice(vid)
        if not v:
            self._generate_next()
            return

        done_in_batch = self._gen_total - len(self._gen_queue) - 1
        self._prog_lbl.configure(
            text=f"Generazione {v.label} ({done_in_batch + 1}/{self._gen_total})…")
        self._prog_bar.set(done_in_batch / self._gen_total if self._gen_total else 0)

        v.status = "generating"
        self._update_voice_row(vid)

        voice    = self._app._voice
        ref_wav  = self._get_voice_ref(v)
        lang     = self._lang.get()
        polish   = self._polish.get()

        if not voice:
            self._on_voice_error(vid, "Nessuna voce selezionata nella finestra principale.")
            return

        self._app.engine.generate(
            text=v.text,
            voice=voice,
            language=lang,
            reference_wav=ref_wav,
            polish=polish,
            on_done=lambda p, _vid=vid: self.after(0, lambda: self._on_voice_done(_vid, p)),
            on_error=lambda m, _vid=vid: self.after(0, lambda: self._on_voice_error(_vid, m)),
        )

    def _on_voice_done(self, vid: str, path: str):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        v = self._get_voice(vid)
        if v:
            v.status = "done"
            v.audio_path = path
            self._update_voice_row(vid)
            # Auto-load nel player se la voce è già selezionata, oppure se la
            # voce attualmente selezionata non ha ancora audio (così la prima
            # voce completata appare automaticamente nel player).
            cur = self._cur_voice()
            if self._selected_id == vid or (cur and not cur.audio_path):
                self._select_voice(vid)

        done_in_batch = self._gen_total - len(self._gen_queue)
        self._prog_bar.set(done_in_batch / self._gen_total if self._gen_total else 0)
        self._generate_next()

    def _on_voice_error(self, vid: str, msg: str):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        v = self._get_voice(vid)
        if v:
            v.status = "error"
            v.error_msg = msg
            self._update_voice_row(vid)
        self._generate_next()

    def _on_generation_done(self):
        self._generating = False
        self._gen_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        done  = len([x for x in self._voices if x.status == "done"])
        total = len([x for x in self._voices if x.text.strip()])
        self._prog_lbl.configure(text=f"Completate: {done}/{total}")
        self._prog_bar.set(1.0 if self._gen_total else 0)

    def _regenerate_voice(self):
        v = self._cur_voice()
        if not v or v.status == "generating":
            return
        if not v.text.strip():
            self._show_status("Testo vuoto: scrivi il testo prima di rigenerare.", DANGER)
            return
        if not self._app._voice:
            self._show_status("Nessuna voce selezionata nella finestra principale.", DANGER)
            return

        # Clean up existing audio for this voice
        for p in (v.audio_path, v.audio_original):
            if p and os.path.exists(p):
                try: os.unlink(p)
                except Exception: pass
        v.audio_path     = None
        v.audio_original = None
        v.edit_pending   = False
        v.status         = "idle"
        v.error_msg      = None
        self._update_voice_row(v.id)

        # Reset player display
        self.player.stop()
        self._audio_path     = None
        self._audio_original = None
        self._edit_pending   = False
        self._player_card.grid_remove()
        self._confirm_bar.grid_remove()

        if self._generating:
            # Piggyback on the running batch
            self._gen_queue.append(v.id)
            self._gen_total += 1
        else:
            self._stop_req   = False
            self._generating = True
            self._gen_queue  = [v.id]
            self._gen_total  = 1
            self._gen_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._generate_next()

    # ══════════════════════════════════════════════════════════════════════
    #  Player logic
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
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._play_btn.configure(text="▶")
        self._seek_var.set(0)
        self._time_cur.configure(text="0:00")
        self._update_playhead(0.0)

    def _on_seek(self, value):
        if not self.player.duration:
            return
        secs = (float(value) / 100.0) * self.player.duration
        self.player.seek(secs)
        self._time_cur.configure(text=_fmt_time(secs))
        self._update_playhead(secs)

    def _seek_to_x(self, x: int):
        w = self._wave_canvas.winfo_width()
        if w <= 0:
            return
        secs = max(0.0, min(x / w, 1.0)) * self.player.duration
        self.player.seek(secs)
        self.player.play(on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

    def _tick(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if self.player.is_playing and self.player.duration > 0:
            pos = self.player.position
            self._seek_var.set((pos / self.player.duration) * 100)
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
        h = self._wave_canvas.winfo_height() or 70
        self._wave_canvas.delete("playhead")
        self._wave_canvas.create_line(x, 0, x, h, fill=ACCENT, width=2, tags="playhead")

    # ── Waveform ──────────────────────────────────────────────────────────

    def _draw_waveform(self, path: str):
        self.update_idletasks()
        W = self._wave_canvas.winfo_width() or 700
        H = self._wave_canvas.winfo_height() or 70
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
                samples = [samples[i] for i in range(0, len(samples), n_channels)]
            max_val = 2 ** (sampwidth * 8 - 1)
            norm = [s / max_val for s in samples]
            step = max(1, len(norm) // W)
            bars = [max(abs(s) for s in norm[i:i + step])
                    for i in range(0, len(norm), step)][:W]
            for x, amp in enumerate(bars):
                bh = max(2, amp * (H - 8))
                y0 = (H - bh) / 2
                self._wave_canvas.create_line(x, y0, x, y0 + bh, fill=ACCENT, tags="wave")
        except Exception:
            import random; random.seed(42)
            for x in range(W):
                amp = 0.2 + 0.6 * abs(math.sin(x * 0.12)) * (0.5 + 0.5 * random.random())
                bh = max(2, amp * (H - 8))
                y0 = (H - bh) / 2
                self._wave_canvas.create_line(x, y0, x, y0 + bh, fill=ACCENT, tags="wave")

    # ── Selection ─────────────────────────────────────────────────────────

    def _sel_press(self, event):
        self._sel_drag_x0 = event.x
        self._sel_start = None
        self._sel_end   = None
        self._wave_canvas.delete("selection")
        self._edit_bar.grid_remove()

    def _sel_motion(self, event):
        if self._sel_drag_x0 is None or not self.player.duration:
            return
        x0, x1 = self._sel_drag_x0, event.x
        xa, xb = min(x0, x1), max(x0, x1)
        if xb - xa < 3:
            return
        H = self._wave_canvas.winfo_height() or 70
        self._wave_canvas.delete("selection")
        self._wave_canvas.create_rectangle(xa, 0, xb, H,
            fill=ACCENT, stipple="gray25", outline=ACCENT, width=1, tags="selection")
        self._wave_canvas.create_line(xa, 0, xa, H, fill=ACCENT, width=2, tags="selection")
        self._wave_canvas.create_line(xb, 0, xb, H, fill=ACCENT, width=2, tags="selection")

    def _sel_release(self, event):
        if self._sel_drag_x0 is None:
            return
        dx = abs(event.x - self._sel_drag_x0)
        if dx < 6 or not self.player.duration:
            self._wave_canvas.delete("selection")
            self._edit_bar.grid_remove()
            self._sel_drag_x0 = None
            self._seek_to_x(event.x)
            return
        w  = self._wave_canvas.winfo_width()
        xa = min(self._sel_drag_x0, event.x)
        xb = max(self._sel_drag_x0, event.x)
        dur = self.player.duration
        self._sel_start = max(0.0, (xa / w) * dur)
        self._sel_end   = min(dur,  (xb / w) * dur)
        self._sel_drag_x0 = None
        self._sel_lbl.configure(
            text=f"{_fmt_time(self._sel_start)} → {_fmt_time(self._sel_end)}"
                 f"  ({_fmt_time(self._sel_end - self._sel_start)})")
        self._edit_bar.grid()

    def _edit_clear_sel(self):
        self._sel_start = None
        self._sel_end   = None
        self._wave_canvas.delete("selection")
        self._edit_bar.grid_remove()

    # ── Editing ───────────────────────────────────────────────────────────

    def _apply_edit(self, mode: str):
        if self._sel_start is None or not self._audio_path:
            return
        path = self._audio_path
        try:
            with wave.open(path, "rb") as wf:
                n_ch = wf.getnchannels(); sw = wf.getsampwidth()
                sr   = wf.getframerate(); n_fr = wf.getnframes()
                raw  = wf.readframes(n_fr)
            fmt = {1: "b", 2: "h", 4: "i"}.get(sw, "h")
            all_s = list(struct.unpack(f"<{n_fr * n_ch}{fmt}", raw))
            s0 = max(0, min(int(self._sel_start * sr) * n_ch, len(all_s)))
            s1 = max(0, min(int(self._sel_end   * sr) * n_ch, len(all_s)))
            result = (all_s[:s0] + all_s[s1:]) if mode == "delete" else all_s[s0:s1]
            if not result:
                self._show_status("La modifica produrrebbe un file vuoto.", DANGER)
                return
            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="vt_mvedit_")
            os.close(fd)
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(n_ch); wf.setsampwidth(sw); wf.setframerate(sr)
                wf.writeframes(struct.pack(f"<{len(result)}{fmt}", *result))
            if not self._edit_pending:
                self._audio_original = path
                self._edit_pending   = True
            self._audio_path = tmp
            self.player.stop()
            duration = self.player.load(tmp)
            label = "eliminata" if mode == "delete" else "ritagliato"
            self._time_tot.configure(text=_fmt_time(duration))
            self._dur_lbl.configure(text=f"{_fmt_time(duration)} · WAV ({label})")
            self._draw_waveform(tmp)
            self._edit_clear_sel()
            self._confirm_bar.grid()
            self._hide_status()
            self.player.play(on_end=lambda: self.after(0, self._on_play_end))
            self._play_btn.configure(text="⏸")
        except Exception as exc:
            self._show_status(f"Errore editing: {exc}", DANGER)

    def _confirm_edit(self):
        if not self._edit_pending:
            return
        if self._audio_original and self._audio_original != self._audio_path:
            try: os.unlink(self._audio_original)
            except Exception: pass
        self._audio_original = None
        self._edit_pending   = False
        self._confirm_bar.grid_remove()
        self._dur_lbl.configure(text=f"{_fmt_time(self.player.duration or 0)} · WAV")
        v = self._cur_voice()
        if v:
            v.audio_path = self._audio_path
            v.audio_original = None
            v.edit_pending = False

    def _undo_edit(self):
        if not self._edit_pending or not self._audio_original:
            self._confirm_bar.grid_remove()
            return
        if self._audio_path and self._audio_path != self._audio_original:
            try: os.unlink(self._audio_path)
            except Exception: pass
        self._audio_path     = self._audio_original
        self._audio_original = None
        self._edit_pending   = False
        self._confirm_bar.grid_remove()
        v = self._cur_voice()
        if v:
            v.audio_path     = self._audio_path
            v.audio_original = None
            v.edit_pending   = False
        self.player.stop()
        duration = self.player.load(self._audio_path)
        self._time_tot.configure(text=_fmt_time(duration))
        self._dur_lbl.configure(text=f"{_fmt_time(duration)} · WAV")
        self._draw_waveform(self._audio_path)
        self._edit_clear_sel()
        self.player.play(on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

    # ══════════════════════════════════════════════════════════════════════
    #  Pulisci voce
    # ══════════════════════════════════════════════════════════════════════

    def _clean_voice(self):
        if not self._audio_path:
            return
        from app.ui.clean_dialog import show_clean_dialog
        show_clean_dialog(self, self._run_clean)

    def _run_clean(self, denoise: float, mix: float, gate: str):
        if not self._audio_path:
            return
        from app.audio.enhance import clean_voice
        src = self._audio_path
        fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="vt_mvclean_")
        os.close(fd)
        self._clean_btn.configure(state="disabled", text="⏳ Pulizia…")
        self._show_status("Pulizia voce in corso…", WARN)

        def _run():
            try:
                ok = clean_voice(src, tmp,
                                 denoise_strength=denoise,
                                 dry_mix=mix,
                                 gate=gate)
                self.after(0, lambda: self._on_clean_done(tmp, ok))
            except Exception as exc:
                self.after(0, lambda: self._on_clean_error(str(exc), tmp))

        threading.Thread(target=_run, daemon=True).start()

    def _on_clean_done(self, tmp: str, ok: bool):
        self._clean_btn.configure(state="normal", text="✨ Pulisci voce")
        if not ok or not os.path.exists(tmp):
            self._show_status("Pulizia non riuscita.", DANGER)
            try: os.unlink(tmp)
            except Exception: pass
            return
        if not self._edit_pending:
            self._audio_original = self._audio_path
            self._edit_pending   = True
        self._audio_path = tmp
        self.player.stop()
        duration = self.player.load(tmp)
        self._time_tot.configure(text=_fmt_time(duration))
        self._dur_lbl.configure(text=f"{_fmt_time(duration)} · WAV (pulito)")
        self._draw_waveform(tmp)
        self._edit_clear_sel()
        self._confirm_bar.grid()
        self._hide_status()
        self.player.play(on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

    def _on_clean_error(self, msg: str, tmp: str):
        self._clean_btn.configure(state="normal", text="✨ Pulisci voce")
        try: os.unlink(tmp)
        except Exception: pass
        self._show_status(f"Errore pulizia: {msg}", DANGER)

    # ══════════════════════════════════════════════════════════════════════
    #  Velocità
    # ══════════════════════════════════════════════════════════════════════

    def _show_speed_dialog(self):
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
                     font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(0, 10))

        speed_var = tk.DoubleVar(value=1.0)
        val_lbl = ctk.CTkLabel(win, text="1.00×",
                               font=ctk.CTkFont(size=22, weight="bold"),
                               text_color=ACCENT)
        val_lbl.pack(pady=(0, 4))

        ctk.CTkSlider(win, from_=0.50, to=2.00, number_of_steps=150,
                      variable=speed_var,
                      command=lambda v: val_lbl.configure(text=f"{float(v):.2f}×"),
                      progress_color=ACCENT, button_color=ACCENT,
                      button_hover_color=ACCENT_D).pack(fill="x", padx=30, pady=(0, 4))

        pr = ctk.CTkFrame(win, fg_color="transparent")
        pr.pack(fill="x", padx=30, pady=(0, 12))
        for label, val in [("0.75×", 0.75), ("1.00×", 1.00), ("1.25×", 1.25), ("1.50×", 1.50)]:
            ctk.CTkButton(pr, text=label, width=60, height=24,
                          fg_color="transparent", border_width=1,
                          text_color=("gray20", "gray80"),
                          font=ctk.CTkFont(size=10),
                          command=lambda v=val: (speed_var.set(v),
                                                 val_lbl.configure(text=f"{v:.2f}×"))
                          ).pack(side="left", expand=True, padx=2)

        br = ctk.CTkFrame(win, fg_color="transparent")
        br.pack(fill="x", padx=30, pady=(0, 12))
        ctk.CTkButton(br, text="Applica", height=32,
                      fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: (win.destroy(), self._apply_speed(float(speed_var.get())))
                      ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(br, text="Annulla", height=32,
                      fg_color="transparent", border_width=1,
                      command=win.destroy).pack(side="left", expand=True, fill="x", padx=(4, 0))

    def _apply_speed(self, factor: float):
        if not self._audio_path or abs(factor - 1.0) < 0.01:
            return
        from app.audio.speed import change_speed
        src = self._audio_path
        fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="vt_mvspeed_")
        os.close(fd)
        self._speed_btn.configure(state="disabled", text="⏳ Elaborazione…")
        self._show_status(f"Cambio velocità a {factor:.2f}×…", WARN)

        def _run():
            try:
                ok = change_speed(src, tmp, factor)
                self.after(0, lambda: self._on_speed_done(tmp, ok, factor))
            except Exception as exc:
                self.after(0, lambda: self._on_speed_error(str(exc), tmp))

        threading.Thread(target=_run, daemon=True).start()

    def _on_speed_done(self, tmp: str, ok: bool, factor: float):
        self._speed_btn.configure(state="normal", text="⏱ Velocità")
        if not ok or not os.path.exists(tmp):
            self._show_status("Cambio velocità non riuscito.", DANGER)
            try: os.unlink(tmp)
            except Exception: pass
            return
        if not self._edit_pending:
            self._audio_original = self._audio_path
            self._edit_pending   = True
        self._audio_path = tmp
        self.player.stop()
        duration = self.player.load(tmp)
        self._time_tot.configure(text=_fmt_time(duration))
        self._dur_lbl.configure(text=f"{_fmt_time(duration)} · WAV ({factor:.2f}×)")
        self._draw_waveform(tmp)
        self._edit_clear_sel()
        self._confirm_bar.grid()
        self._hide_status()
        self.player.play(on_end=lambda: self.after(0, self._on_play_end))
        self._play_btn.configure(text="⏸")

    def _on_speed_error(self, msg: str, tmp: str):
        self._speed_btn.configure(state="normal", text="⏱ Velocità")
        try: os.unlink(tmp)
        except Exception: pass
        self._show_status(f"Errore velocità: {msg}", DANGER)

    # ══════════════════════════════════════════════════════════════════════
    #  Export
    # ══════════════════════════════════════════════════════════════════════

    def _show_export_dialog(self):
        if not self._audio_path:
            return
        ffmpeg  = self._find_ffmpeg()
        has_mp3 = self._has_lameenc() or bool(ffmpeg)
        has_ogg = self._has_soundfile_ogg() or bool(ffmpeg)

        win = ctk.CTkToplevel(self)
        win.title("Esporta audio")
        win.geometry("440x360")
        win.resizable(False, False)
        win.grab_set()

        ctk.CTkLabel(win, text="Esporta Audio",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(18, 8))

        fmt_var = tk.StringVar(value="wav")
        ff = ctk.CTkFrame(win, fg_color="transparent")
        ff.pack(fill="x", padx=24, pady=(0, 10))
        for label, val, enabled in [
            ("WAV  – Lossless, massima fedeltà",      "wav", True),
            ("MP3  – Compresso, compatibile ovunque",  "mp3", has_mp3),
            ("OGG  – Compresso, ottimale web/voce",    "ogg", has_ogg),
        ]:
            ctk.CTkRadioButton(ff, text=label, variable=fmt_var, value=val,
                               state="normal" if enabled else "disabled",
                               fg_color=ACCENT, hover_color=ACCENT_D,
                               font=ctk.CTkFont(size=12)).pack(anchor="w", pady=3)

        ctk.CTkLabel(win, text="QUALITÀ  (per MP3/OGG)",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray").pack(anchor="w", padx=24)
        quality_var = tk.StringVar(value="web")
        qf = ctk.CTkFrame(win, fg_color="transparent")
        qf.pack(fill="x", padx=24, pady=(4, 14))
        for label, val in [("Web ready  ~48 kbps", "web"),
                           ("Alta       ~128 kbps", "high"),
                           ("Massima    ~320 kbps", "max")]:
            ctk.CTkRadioButton(qf, text=label, variable=quality_var, value=val,
                               fg_color=ACCENT, hover_color=ACCENT_D,
                               font=ctk.CTkFont(size=12)).pack(anchor="w", pady=2)

        def do_export():
            fmt  = fmt_var.get()
            ext  = {"wav": ".wav", "mp3": ".mp3", "ogg": ".ogg"}[fmt]
            v    = self._cur_voice()
            name = v.label if v else "output"
            dest = filedialog.asksaveasfilename(
                title="Salva come", defaultextension=ext,
                filetypes=[(fmt.upper(), f"*{ext}"), ("Tutti i file", "*.*")],
                initialfile=f"VocalText_{name}{ext}")
            if not dest:
                return
            win.destroy()
            self._do_export(fmt, quality_var.get(), dest)

        ctk.CTkButton(win, text="Scegli destinazione ed Esporta",
                      height=40, fg_color=ACCENT, hover_color=ACCENT_D,
                      text_color="#0a1810",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=do_export).pack(fill="x", padx=24, pady=(0, 8))
        ctk.CTkButton(win, text="Annulla", height=30,
                      fg_color="transparent", border_width=1,
                      command=win.destroy).pack(fill="x", padx=24)

    def _do_export(self, fmt: str, quality: str, dest: str):
        import shutil
        src = self._audio_path
        if fmt == "wav":
            try:
                shutil.copy2(src, dest)
                kb = os.path.getsize(dest) / 1024
                self._show_status(f"Salvato: {os.path.basename(dest)} ({kb:.0f} KB)", ACCENT)
            except Exception as exc:
                self._show_status(f"Errore: {exc}", DANGER)
            return
        self._show_status("Esportazione in corso…", WARN)
        threading.Thread(target=self._export_worker,
                         args=(fmt, quality, src, dest), daemon=True).start()

    def _export_worker(self, fmt: str, quality: str, src: str, dest: str):
        import subprocess
        try:
            if fmt == "mp3" and self._has_lameenc():
                self._export_mp3_lameenc(src, dest, quality)
            elif fmt == "ogg" and self._has_soundfile_ogg():
                self._export_ogg_soundfile(src, dest, quality)
            else:
                ffmpeg = self._find_ffmpeg()
                if not ffmpeg:
                    self.after(0, lambda: self._show_status("FFmpeg non trovato.", DANGER))
                    return
                cmd = [ffmpeg, "-y", "-i", src]
                if fmt == "mp3":
                    cmd += ["-codec:a", "libmp3lame", "-q:a",
                            {"max": "0", "high": "2", "web": "5"}.get(quality, "3")]
                else:
                    cmd += ["-codec:a", "libopus", "-b:a",
                            {"max": "128k", "high": "64k", "web": "32k"}.get(quality, "48k"),
                            "-ac", "1", "-ar", "48000"]
                cmd.append(dest)
                r = subprocess.run(cmd, capture_output=True, timeout=120)
                if r.returncode != 0:
                    err = r.stderr.decode(errors="replace")[-200:]
                    self.after(0, lambda: self._show_status(f"Errore FFmpeg: {err}", DANGER))
                    return
            if os.path.exists(dest):
                kb = os.path.getsize(dest) / 1024
                self.after(0, lambda: self._show_status(
                    f"Esportato: {os.path.basename(dest)} ({kb:.0f} KB)", ACCENT))
        except Exception as exc:
            self.after(0, lambda: self._show_status(f"Errore esportazione: {exc}", DANGER))

    @staticmethod
    def _has_lameenc() -> bool:
        try: import lameenc; return True
        except ImportError: return False

    @staticmethod
    def _has_soundfile_ogg() -> bool:
        try:
            import soundfile as sf
            return bool(sf.available_subtypes("OGG"))
        except Exception: return False

    @staticmethod
    def _soundfile_ogg_subtype() -> str:
        try:
            import soundfile as sf
            s = sf.available_subtypes("OGG")
            return "OPUS" if "OPUS" in s else "VORBIS"
        except Exception: return "VORBIS"

    @staticmethod
    def _find_ffmpeg():
        import shutil
        f = shutil.which("ffmpeg")
        if f: return f
        for p in [r"C:\ffmpeg\bin\ffmpeg.exe",
                  r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]:
            if os.path.exists(p): return p
        return None

    @staticmethod
    def _export_mp3_lameenc(src: str, dest: str, quality: str):
        import lameenc, wave as _wave, struct as _struct, numpy as _np
        bitrate = {"max": 320, "high": 128, "web": 48}.get(quality, 64)
        with _wave.open(src, "rb") as wf:
            n_ch = wf.getnchannels(); sw = wf.getsampwidth()
            sr   = wf.getframerate(); raw = wf.readframes(wf.getnframes())
        fmt = {1: "b", 2: "h", 4: "i"}.get(sw, "h")
        s = _np.array(_struct.unpack(f"<{len(raw)//sw}{fmt}", raw), dtype=_np.float32)
        if sw != 2:
            s = (s / (2 ** (sw * 8 - 1)) * 32767).astype(_np.int16)
        else:
            s = s.astype(_np.int16)
        if n_ch > 1:
            s = s.reshape(-1, n_ch).mean(axis=1).astype(_np.int16)
        enc = lameenc.Encoder()
        enc.set_bit_rate(bitrate); enc.set_in_sample_rate(sr)
        enc.set_channels(1); enc.set_quality(2)
        mp3 = enc.encode(s.tobytes()) + enc.flush()
        with open(dest, "wb") as f: f.write(mp3)

    @staticmethod
    def _export_ogg_soundfile(src: str, dest: str, quality: str):
        import soundfile as sf, numpy as _np
        data, sr = sf.read(src, dtype="float32", always_2d=False)
        if data.ndim > 1: data = data.mean(axis=1)
        subtype = MultiVoiceWindow._soundfile_ogg_subtype()
        if subtype == "OPUS":
            target_sr = 24000 if quality == "web" else 48000
            if int(sr) not in [8000, 12000, 16000, 24000, 48000]:
                try:
                    from scipy.signal import resample_poly
                    from math import gcd
                    g = gcd(int(sr), target_sr)
                    data = resample_poly(data, target_sr // g, int(sr) // g).astype(_np.float32)
                    sr = target_sr
                except Exception: sr = target_sr
        sf.write(dest, data, int(sr), format="OGG", subtype=subtype,
                 compression_level={"max": 0.0, "high": 0.3, "web": 0.7}.get(quality, 0.5))

    # ══════════════════════════════════════════════════════════════════════
    #  Utilities
    # ══════════════════════════════════════════════════════════════════════

    def _show_status(self, msg: str, color: str = DANGER):
        # Icona coerente col tipo di messaggio
        if color == ACCENT:
            icon = "✓"
        elif color == WARN:
            icon = "⏳"
        else:
            icon = "⚠"
        self._status_lbl.configure(text=f"{icon}  {msg}", text_color=color)

    def _hide_status(self):
        self._status_lbl.configure(text="")

    def _on_close(self):
        # Cleanup di tutti i temp files (audio generati + backup edit)
        for v in self._voices:
            for p in (v.audio_path, v.audio_original):
                if p and os.path.exists(p):
                    try:
                        os.unlink(p)
                    except Exception:
                        pass
        self.player.quit()
        # Rimuove il riferimento singleton dal parent
        try:
            if getattr(self._app, "_multi_voice_win", None) is self:
                self._app._multi_voice_win = None
        except Exception:
            pass
        self.destroy()
