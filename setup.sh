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
echo "=== Fatto! Avvia l'app con: ==="
echo "   python3 main.py"
echo ""
echo "Per voci di qualità superiore scarica un modello Piper:"
echo "   ./scripts/download-piper.sh it_IT-paola-medium"
