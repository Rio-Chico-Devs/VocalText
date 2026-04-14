#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  VocalText – Piper TTS setup helper
#  Downloads the piper binary and optionally a voice model
#  Usage: ./scripts/download-piper.sh [voice_id]
#  Example: ./scripts/download-piper.sh it_IT-paola-medium
# ─────────────────────────────────────────────────────────

set -e

PIPER_VERSION="2023.11.14-2"
PLATFORM="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

# Normalise arch
case "$ARCH" in
  x86_64)  ARCH="x86_64" ;;
  aarch64) ARCH="aarch64" ;;
  arm64)   ARCH="aarch64" ;;
  *)       echo "Architettura non supportata: $ARCH"; exit 1 ;;
esac

# Build download URL
case "$PLATFORM" in
  linux)   TARBALL="piper_linux_${ARCH}.tar.gz" ;;
  darwin)  TARBALL="piper_macos_${ARCH}.tar.gz" ;;
  *)       echo "Piattaforma non supportata: $PLATFORM"; exit 1 ;;
esac

BASE_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}"
BIN_DIR="./bin/${PLATFORM}"

echo "── Scaricamento Piper TTS ${PIPER_VERSION} ──"
mkdir -p "$BIN_DIR"

TMPDIR_DL=$(mktemp -d)
trap 'rm -rf "$TMPDIR_DL"' EXIT

curl -fL "${BASE_URL}/${TARBALL}" -o "${TMPDIR_DL}/${TARBALL}"
tar -xzf "${TMPDIR_DL}/${TARBALL}" -C "${TMPDIR_DL}"

# Find the piper binary
PIPER_BIN=$(find "$TMPDIR_DL" -name "piper" -type f | head -1)
if [ -z "$PIPER_BIN" ]; then
  echo "Errore: binario piper non trovato nel tarball"
  exit 1
fi

cp "$PIPER_BIN" "${BIN_DIR}/piper"
chmod +x "${BIN_DIR}/piper"

# Also copy espeak-ng-data if present
ESPEAK_DATA=$(find "$TMPDIR_DL" -name "espeak-ng-data" -type d | head -1)
if [ -n "$ESPEAK_DATA" ]; then
  cp -r "$ESPEAK_DATA" "${BIN_DIR}/"
  echo "  espeak-ng-data copiato"
fi

echo "✓ Piper installato in ${BIN_DIR}/piper"

# ── Optionally download a voice model ──────────────────────────────────────
VOICE_ID="${1:-}"
if [ -z "$VOICE_ID" ]; then
  echo ""
  echo "Suggerimento: scarica una voce con:"
  echo "  $0 it_IT-paola-medium"
  echo "  $0 en_US-lessac-medium"
  exit 0
fi

echo ""
echo "── Scaricamento modello vocale: ${VOICE_ID} ──"

# Parse voice id: lang-speaker-quality  →  lang/lang_region/speaker/quality/
IFS='-' read -r LANG_CODE SPEAKER QUALITY <<< "$VOICE_ID"
LANG_PREFIX="${LANG_CODE:0:2}"
MODEL_DIR="./models/${VOICE_ID}"
mkdir -p "$MODEL_DIR"

HF_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main"
VOICE_PATH="${LANG_PREFIX}/${LANG_CODE}/${SPEAKER}/${QUALITY}"

for FILE in "${VOICE_ID}.onnx" "${VOICE_ID}.onnx.json"; do
  URL="${HF_BASE}/${VOICE_PATH}/${FILE}"
  echo "  Scaricamento ${FILE}…"
  curl -fL "$URL" -o "${MODEL_DIR}/${FILE}"
done

echo "✓ Modello salvato in ${MODEL_DIR}/"
echo ""
echo "Riavvia VocalText per utilizzare la nuova voce."
