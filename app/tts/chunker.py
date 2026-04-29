"""
Chunker intelligente per testi lunghi → XTTS v2.

XTTS degrada su testi > ~250 caratteri (inizia a ripetere, tagliare o
glitchare). Questo modulo spezza il testo rispettando la punteggiatura
naturale (prima frasi, poi sotto-frasi, poi parole) e calcola la
pausa da inserire tra i chunk in base al segno di punteggiatura che
termina ogni chunk.

Strategia:
  1. Normalizza whitespace (ma preserva \\n\\n per paragrafi)
  2. Split per separatori di frase: .  !  ?  ;  \\n\\n
  3. Se una frase supera il budget → sotto-split su ,  :  —
  4. Se ancora troppo lunga → split per parole
  5. Unisce frasi corte consecutive finché stanno nel budget
     (preserva la prosodia naturale del modello)
"""

from __future__ import annotations
import re


# Budget conservativo (hard-limit reale di XTTS varia per lingua: en~250, it~213)
# Stiamo larghi per evitare del tutto la zona di degrado.
DEFAULT_MAX_CHARS = 200

# Pause (in ms) associate al segno di punteggiatura che termina il chunk.
# Questi valori sono stati calibrati a orecchio per suonare naturali —
# non esiste uno standard, ma una narrazione professionale tipica usa:
PAUSE_MS = {
    ".":    280,   # fine frase
    "!":    320,   # esclamazione (leggermente più lunga per enfasi)
    "?":    340,   # domanda (attesa di risposta)
    ";":    220,
    ":":    200,
    ",":    110,
    "—":    140,   # trattino lungo
    "\n\n": 450,   # paragrafo
    "":      50,   # split forzato a metà parola — pausa minima
}

_SENT_SPLIT = re.compile(r'([.!?;]+|\n{2,})')
_SUB_SPLIT  = re.compile(r'([,:—])')


def chunk_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[dict]:
    """
    Spezza il testo in chunk <= max_chars, preservando il più possibile
    la punteggiatura naturale.

    Ritorna: [{"text": str, "pause_ms": int}, ...]
    pause_ms è la pausa DOPO quel chunk (0 per l'ultimo).
    """
    text = _normalize(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [{"text": text, "pause_ms": 0}]

    # Fase 1: dividi in unità di frase {text, trailing_punct}
    units = _split_sentences(text)

    # Fase 2: per ogni unità troppo lunga, sotto-split
    expanded: list[dict] = []
    for u in units:
        if len(u["text"]) <= max_chars:
            expanded.append(u)
        else:
            expanded.extend(_subsplit_long(u, max_chars))

    # Fase 3: raggruppa unità consecutive se insieme stanno nel budget
    # (aiuta la prosodia — XTTS genera meglio frasi "complete" che spezzoni)
    merged = _merge_short(expanded, max_chars)

    # Fase 4: assegna pause in base alla punteggiatura terminale
    out: list[dict] = []
    for i, u in enumerate(merged):
        is_last = (i == len(merged) - 1)
        punct   = u.get("trail", "")
        pause   = 0 if is_last else PAUSE_MS.get(punct, 80)
        out.append({"text": u["text"].strip(), "pause_ms": pause})
    return [c for c in out if c["text"]]


# ── Interne ────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    # Conserva le newline multiple come marker di paragrafo
    text = re.sub(r'\r\n?', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _split_sentences(text: str) -> list[dict]:
    """Split su . ! ? ; e \\n\\n — conserva il separatore come trail."""
    parts = _SENT_SPLIT.split(text)
    units: list[dict] = []
    buf = ""
    for tok in parts:
        if not tok:
            continue
        if _SENT_SPLIT.fullmatch(tok):
            # È un separatore — chiude l'unità corrente
            trail = tok.strip()
            if trail.startswith("\n"):
                trail = "\n\n"
            else:
                trail = trail[0]   # prendi solo il primo carattere (es. "!!!"→"!")
            if buf.strip():
                units.append({"text": buf.strip(), "trail": trail})
                buf = ""
        else:
            buf += tok
    if buf.strip():
        units.append({"text": buf.strip(), "trail": "."})   # aggiunge punto implicito
    return units


def _subsplit_long(unit: dict, max_chars: int) -> list[dict]:
    """Unità singola troppo lunga → spezza su , : — poi per parole se serve."""
    text  = unit["text"]
    trail = unit["trail"]

    parts = _SUB_SPLIT.split(text)
    units: list[dict] = []
    buf = ""
    last_sub_trail = ""
    for tok in parts:
        if not tok:
            continue
        if _SUB_SPLIT.fullmatch(tok):
            last_sub_trail = tok
            if len(buf) > max_chars:
                units.extend(_word_split(buf, max_chars, last_sub_trail or ""))
                buf = ""
            else:
                if buf.strip():
                    units.append({"text": buf.strip(), "trail": last_sub_trail})
                    buf = ""
        else:
            buf += tok
    if buf.strip():
        if len(buf) > max_chars:
            units.extend(_word_split(buf, max_chars, trail))
        else:
            units.append({"text": buf.strip(), "trail": trail})

    # L'ultima unità eredita il trail originale (fine della frase completa)
    if units:
        units[-1]["trail"] = trail
    return units


def _word_split(text: str, max_chars: int, trail: str) -> list[dict]:
    """Ultima risorsa: spezza per parole. Il trail è del chunk finale."""
    words = text.split()
    if not words:
        return []
    units: list[dict] = []
    buf = ""
    for w in words:
        candidate = (buf + " " + w).strip() if buf else w
        if len(candidate) > max_chars and buf:
            units.append({"text": buf, "trail": ""})   # split forzato → pausa minima
            buf = w
        else:
            buf = candidate
    if buf:
        units.append({"text": buf, "trail": trail})
    return units


def _merge_short(units: list[dict], max_chars: int) -> list[dict]:
    """
    Unisce unità consecutive se la loro lunghezza combinata sta nel budget.
    Preserva il trail dell'ultima unità del gruppo (punteggiatura finale).
    """
    if not units:
        return []
    merged: list[dict] = []
    cur = dict(units[0])
    for nxt in units[1:]:
        # Stima con separatore: " " + trail_precedente + next_text
        join_sep = _punct_glue(cur["trail"])
        combined = len(cur["text"]) + len(join_sep) + len(nxt["text"])
        if combined <= max_chars:
            cur["text"] = cur["text"] + join_sep + nxt["text"]
            cur["trail"] = nxt["trail"]
        else:
            merged.append(cur)
            cur = dict(nxt)
    merged.append(cur)
    return merged


def _punct_glue(trail: str) -> str:
    """Come si riunisce un'unità al trail precedente."""
    if trail == "\n\n":
        return ". "
    if trail in (".", "!", "?", ";"):
        return trail + " "
    if trail in (",", ":", "—"):
        return trail + " "
    return " "
