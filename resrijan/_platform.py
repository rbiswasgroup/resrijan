"""Platform helpers: run external programs without console windows on Windows, and find the
Tesseract and Ghostscript copies that the Windows installer ships next to ReSrijan."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform.startswith("win")


def run(cmd, **kw) -> subprocess.CompletedProcess:
    """subprocess.run that never opens a console window on Windows (the GUI has none)."""
    if WINDOWS:
        kw.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    return subprocess.run(cmd, **kw)


def _tool_roots():
    env = os.environ.get("RESRIJAN_TOOLS")
    if env:
        yield Path(env)
    exe = Path(sys.executable).resolve().parent
    for base in (exe, exe.parent):            # pynsist: <app>\\Python\\python.exe, tools in <app>\\tools
        yield base / "tools"


def setup_bundled_tools() -> None:
    """Put bundled Tesseract/Ghostscript on PATH (only if a 'tools' folder exists, i.e. in the
    Windows installation, or when RESRIJAN_TOOLS points to one)."""
    for root in _tool_roots():
        if not root.is_dir():
            continue
        extra = []
        tess = root / "tesseract"
        if (tess / ("tesseract.exe" if WINDOWS else "tesseract")).exists():
            extra.append(str(tess))
            if (tess / "tessdata").is_dir():
                os.environ.setdefault("TESSDATA_PREFIX", str(tess / "tessdata"))
        gs = root / "gs" / "bin"
        if gs.is_dir():
            extra.append(str(gs))
        if extra:
            os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])
        return


def user_config_dir() -> Path:
    """Folder for the user's own files (journal templates): %APPDATA%\\resrijan on Windows,
    $XDG_CONFIG_HOME/resrijan or ~/.config/resrijan elsewhere."""
    if WINDOWS and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "resrijan"
    return Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "resrijan"
