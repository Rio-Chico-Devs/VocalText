"""
Dialog impostazioni pulizia voce.
Condiviso da window.py e multi_voice_window.py.
"""
from __future__ import annotations
import tkinter as tk
import customtkinter as ctk

ACCENT   = "#4ecca3"
ACCENT_D = "#3aaf8d"
WARN     = "#f4a261"

# Preset rapidi: (denoise_strength, dry_mix, gate)
PRESETS: dict[str, dict] = {
    "Delicata": dict(denoise=0.50, mix=0.25, gate="gentle"),
    "Normale":  dict(denoise=0.70, mix=0.18, gate="normal"),
    "Forte":    dict(denoise=0.88, mix=0.08, gate="strong"),
}

_GATE_LABELS = ["Spento", "Dolce", "Normale", "Forte"]
_GATE_VALUES = ["off",    "gentle", "normal", "strong"]

# Parametri di default (modificati ogni volta che l'utente applica)
_last: dict = dict(denoise=0.70, mix=0.18, gate="normal")


def show_clean_dialog(parent, on_apply) -> None:
    """
    Mostra il dialog impostazioni pulizia.
    on_apply(denoise_strength, dry_mix, gate) viene chiamato al click Applica.
    Ricorda i parametri dell'ultima sessione.
    """
    win = ctk.CTkToplevel(parent)
    win.title("Impostazioni pulizia voce")
    win.geometry("460x370")
    win.resizable(False, False)
    win.grab_set()

    ctk.CTkLabel(win, text="Impostazioni pulizia voce",
                 font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(18, 2))
    ctk.CTkLabel(win, text="Regola l'intensità prima di applicare.",
                 font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(0, 10))

    denoise_var = tk.DoubleVar(value=_last["denoise"])
    mix_var     = tk.DoubleVar(value=_last["mix"])
    gate_var    = tk.StringVar(value=_last["gate"])

    # ── Preset ────────────────────────────────────────────────────────────
    pf = ctk.CTkFrame(win, fg_color="transparent")
    pf.pack(fill="x", padx=28, pady=(0, 12))
    ctk.CTkLabel(pf, text="Preset:",
                 font=ctk.CTkFont(size=11), text_color="gray").pack(side="left", padx=(0, 8))

    denoise_lbl_ref: list = []
    mix_lbl_ref:     list = []
    gate_btns:       dict = {}

    def _update_gate_btns(val: str):
        for v, btn in gate_btns.items():
            active = (v == val)
            btn.configure(
                fg_color=ACCENT if active else "transparent",
                text_color="#0a1810" if active else ("gray20", "gray80"))

    def _apply_preset(name: str):
        p = PRESETS[name]
        denoise_var.set(p["denoise"])
        mix_var.set(p["mix"])
        gate_var.set(p["gate"])
        if denoise_lbl_ref:
            denoise_lbl_ref[0].configure(text=f"{p['denoise'] * 100:.0f}%")
        if mix_lbl_ref:
            mix_lbl_ref[0].configure(text=f"{p['mix'] * 100:.0f}%")
        _update_gate_btns(p["gate"])

    for name in PRESETS:
        ctk.CTkButton(pf, text=name, width=82, height=26,
                      fg_color="transparent", border_width=1,
                      font=ctk.CTkFont(size=11),
                      command=lambda n=name: _apply_preset(n)).pack(side="left", padx=2)

    # ── Slider: rimozione rumore ──────────────────────────────────────────
    rf = ctk.CTkFrame(win, fg_color="transparent")
    rf.pack(fill="x", padx=28, pady=(0, 2))
    ctk.CTkLabel(rf, text="Rimozione rumore",
                 font=ctk.CTkFont(size=12)).pack(side="left")
    d_lbl = ctk.CTkLabel(rf, text=f"{_last['denoise'] * 100:.0f}%",
                          font=ctk.CTkFont(size=12, weight="bold"),
                          text_color=ACCENT)
    d_lbl.pack(side="right")
    denoise_lbl_ref.append(d_lbl)

    ctk.CTkSlider(win, from_=0.30, to=0.92, number_of_steps=62,
                  variable=denoise_var,
                  command=lambda v: d_lbl.configure(text=f"{float(v) * 100:.0f}%"),
                  progress_color=ACCENT, button_color=ACCENT,
                  button_hover_color=ACCENT_D).pack(fill="x", padx=28, pady=(0, 12))

    # ── Slider: naturalezza ───────────────────────────────────────────────
    nf = ctk.CTkFrame(win, fg_color="transparent")
    nf.pack(fill="x", padx=28, pady=(0, 2))
    ctk.CTkLabel(nf, text="Naturalezza (mix originale)",
                 font=ctk.CTkFont(size=12)).pack(side="left")
    m_lbl = ctk.CTkLabel(nf, text=f"{_last['mix'] * 100:.0f}%",
                          font=ctk.CTkFont(size=12, weight="bold"),
                          text_color=ACCENT)
    m_lbl.pack(side="right")
    mix_lbl_ref.append(m_lbl)

    ctk.CTkSlider(win, from_=0.0, to=0.40, number_of_steps=40,
                  variable=mix_var,
                  command=lambda v: m_lbl.configure(text=f"{float(v) * 100:.0f}%"),
                  progress_color=ACCENT, button_color=ACCENT,
                  button_hover_color=ACCENT_D).pack(fill="x", padx=28, pady=(0, 12))

    # ── Noise gate ────────────────────────────────────────────────────────
    gf = ctk.CTkFrame(win, fg_color="transparent")
    gf.pack(fill="x", padx=28, pady=(0, 16))
    ctk.CTkLabel(gf, text="Noise gate:",
                 font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 10))

    def _on_gate(val: str):
        gate_var.set(val)
        _update_gate_btns(val)

    for label, val in zip(_GATE_LABELS, _GATE_VALUES):
        btn = ctk.CTkButton(gf, text=label, width=74, height=26,
                             fg_color="transparent", border_width=1,
                             font=ctk.CTkFont(size=11),
                             command=lambda v=val: _on_gate(v))
        btn.pack(side="left", padx=2)
        gate_btns[val] = btn
    _update_gate_btns(_last["gate"])

    # ── Pulsanti ──────────────────────────────────────────────────────────
    bf = ctk.CTkFrame(win, fg_color="transparent")
    bf.pack(fill="x", padx=28, pady=(0, 16))

    def _confirm():
        global _last
        d = float(denoise_var.get())
        m = float(mix_var.get())
        g = gate_var.get()
        _last = dict(denoise=d, mix=m, gate=g)
        win.destroy()
        on_apply(d, m, g)

    ctk.CTkButton(bf, text="✨ Applica", height=36,
                  fg_color=ACCENT, hover_color=ACCENT_D, text_color="#0a1810",
                  font=ctk.CTkFont(size=13, weight="bold"),
                  command=_confirm).pack(side="left", expand=True, fill="x", padx=(0, 4))
    ctk.CTkButton(bf, text="Annulla", height=36,
                  fg_color="transparent", border_width=1,
                  command=win.destroy).pack(side="left", expand=True, fill="x", padx=(4, 0))
