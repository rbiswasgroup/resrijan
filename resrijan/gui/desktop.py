"""Linux desktop integration: an application-menu entry with the ReSrijan icon."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
MIME = ["application/pdf", "application/postscript", "image/x-eps", "image/svg+xml", "image/png", "image/jpeg",
        "image/tiff", "text/csv"]


def install_entry() -> Path:
    """Write ~/.local/share/applications/resrijan.desktop and the icon; returns the entry path."""
    share = Path.home() / ".local" / "share"
    icon_dir = share / "icons" / "hicolor" / "512x512" / "apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ASSETS / "resrijan-icon-512.png", icon_dir / "resrijan.png")
    svg_dir = share / "icons" / "hicolor" / "scalable" / "apps"
    svg_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ASSETS / "resrijan-icon.svg", svg_dir / "resrijan.svg")
    app_dir = share / "applications"
    app_dir.mkdir(parents=True, exist_ok=True)
    entry = app_dir / "resrijan.desktop"
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=ReSrijan\n"
        "GenericName=Figure digitiser\n"
        "Comment=Digitise, analyse, fit and redraw scientific figures in journal style\n"
        f"Exec={sys.executable} -m resrijan gui %f\n"
        "Icon=resrijan\n"
        "Terminal=false\n"
        "Categories=Science;Education;Graphics;\n"
        f"MimeType={';'.join(MIME)};\n"
        "StartupWMClass=resrijan\n", encoding="utf-8")
    for tool in (["update-desktop-database", str(app_dir)], ["gtk-update-icon-cache", "-f", "-t", str(share / "icons" / "hicolor")]):
        if shutil.which(tool[0]):
            subprocess.run(tool, capture_output=True)
    return entry


def remove_entry():
    share = Path.home() / ".local" / "share"
    for p in (share / "applications" / "resrijan.desktop", share / "icons" / "hicolor" / "512x512" / "apps" / "resrijan.png",
              share / "icons" / "hicolor" / "scalable" / "apps" / "resrijan.svg"):
        if p.exists():
            p.unlink()
