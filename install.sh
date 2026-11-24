#!/usr/bin/env bash
# Install ReSrijan on Ubuntu / Debian (22.04, 24.04 tested) into a virtual environment.
#   ./install.sh            -> ~/.local/share/resrijan-venv, command 'resrijan' in ~/.local/bin
#   ./install.sh --system   -> also install the apt packages (needs sudo)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${RESRIJAN_VENV:-$HOME/.local/share/resrijan-venv}"

if [[ "${1:-}" == "--system" ]] || ! command -v tesseract >/dev/null || ! command -v gs >/dev/null; then
  echo "Installing system packages (tesseract OCR, Ghostscript, fonts, Python venv)…"
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-pip tesseract-ocr ghostscript librsvg2-bin fonts-liberation fonts-dejavu-core
  echo "Optional: 'sudo apt install ttf-mscorefonts-installer' gives true Arial / Times New Roman."
fi

python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip wheel >/dev/null
"$VENV/bin/pip" install "$HERE"
mkdir -p "$HOME/.local/bin"
ln -sf "$VENV/bin/resrijan" "$HOME/.local/bin/resrijan"
echo
echo "ReSrijan installed.  Try:  resrijan templates"
echo "(If 'resrijan' is not found, add ~/.local/bin to your PATH.)"
