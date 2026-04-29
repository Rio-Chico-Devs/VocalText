#!/usr/bin/env bash
# VocalText – setup Linux/macOS
set -e

echo "=== VocalText Setup ==="

# Python check
python3 -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ richiesto'" \
  || { echo "Errore: serve Python 3.10+"; exit 1; }

# espeak-ng (Linux only, voce di sistema)
if [[ "$(uname)" == "Linux" ]]; then
  if ! command -v espeak-ng &>/dev/null; then
    echo "Installazione espeak-ng…"
    sudo apt-get install -y espeak-ng 2>/dev/null \
      || sudo dnf install -y espeak-ng 2>/dev/null \
      || sudo pacman -S --noconfirm espeak-ng 2>/dev/null \
      || echo "Installa espeak-ng manualmente: sudo apt install espeak-ng"
  fi
fi

# Python deps
echo "Installazione dipendenze Python…"
pip3 install -r requirements.txt

echo ""
echo "=== Setup dipendenze completato ==="
echo ""
echo "PROSSIMO STEP — scarica i modelli neurali (UNA SOLA VOLTA, ~2.3 GB):"
echo "   python3 scripts/download_models.py"
echo ""
echo "Da quel momento l'app gira 100% offline. Avvio:"
echo "   python3 main.py"
