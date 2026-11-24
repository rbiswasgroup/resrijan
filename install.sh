#!/usr/bin/env bash
# Install ReSrijan on Ubuntu / Debian (22.04, 24.04 tested) into a virtual environment.
#   ./install.sh            -> ~/.local/share/resrijan-venv with the GUI; commands 'resrijan' and
#                              'resrijan-gui' in ~/.local/bin; ReSrijan in the application menu
#   ./install.sh --no-gui   -> command line only
#   ./install.sh --system   -> also (re)install the apt packages (needs sudo)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${RESRIJAN_VENV:-$HOME/.local/share/resrijan-venv}"
GUI=1
SYSTEM=0
for arg in "$@"; do
  case "$arg" in
    --no-gui) GUI=0 ;;
    --system) SYSTEM=1 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

if [[ $SYSTEM == 1 ]] || ! command -v tesseract >/dev/null || ! command -v gs >/dev/null; then
  echo "Installing system packages (tesseract OCR, Ghostscript, fonts, Python venv)…"
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-pip tesseract-ocr ghostscript librsvg2-bin fonts-liberation fonts-dejavu-core
  if [[ $GUI == 1 ]]; then
    sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libfontconfig1 libdbus-1-3
  fi
  echo "Optional: 'sudo apt install ttf-mscorefonts-installer' gives true Arial / Times New Roman."
fi

python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip wheel >/dev/null
mkdir -p "$HOME/.local/bin"
if [[ $GUI == 1 ]]; then
  "$VENV/bin/pip" install "$HERE[gui]"
  ln -sf "$VENV/bin/resrijan-gui" "$HOME/.local/bin/resrijan-gui"
  "$VENV/bin/python" -c "from resrijan.gui.desktop import install_entry; print('Application menu:', install_entry())"
else
  "$VENV/bin/pip" install "$HERE"
fi
ln -sf "$VENV/bin/resrijan" "$HOME/.local/bin/resrijan"
echo
echo "ReSrijan installed.  Try:  resrijan templates"
if [[ $GUI == 1 ]]; then
  echo "Graphical interface:  resrijan gui   (or ReSrijan in your application menu)"
fi
echo "(If 'resrijan' is not found, add ~/.local/bin to your PATH.)"
