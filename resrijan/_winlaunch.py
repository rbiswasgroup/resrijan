"""Start the GUI from a Windows shortcut.

Shortcuts run ``pythonw.exe``, which has no console: an error during start-up would close the
program silently. This launcher writes everything (Python errors, Qt messages and even native
crashes) to ``%LOCALAPPDATA%\\ReSrijan\\logs\\gui.log`` and shows a message box with the error
and the log's location when ReSrijan cannot start.

Only the standard library is imported before the log is open.
"""
from __future__ import annotations

import datetime
import faulthandler
import os
import platform
import sys
import traceback
from pathlib import Path


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    d = Path(base) / "ReSrijan" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _message_box(title: str, text: str):
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 | 0x10000)   # error icon, foreground
            return
        except Exception:  # noqa: BLE001
            pass
    sys.__stderr__ and sys.__stderr__.write(f"{title}\n{text}\n")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = log_dir() / "gui.log"
    log = open(path, "w", encoding="utf-8", buffering=1)          # noqa: SIM115 – open for the whole session
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log
    faulthandler.enable(log)                                       # native crashes (DLLs, Qt) end up in the log
    log.write(f"ReSrijan GUI start {datetime.datetime.now().isoformat(timespec='seconds')}\n"
              f"python {sys.version}\nexecutable {sys.executable}\nprefix {sys.prefix}\n"
              f"platform {platform.platform()}\ncwd {os.getcwd()}\nargs {argv}\n"
              f"QT_PLUGIN_PATH={os.environ.get('QT_PLUGIN_PATH', '')}\n"
              f"PATH (first entries)={os.pathsep.join(os.environ.get('PATH', '').split(os.pathsep)[:6])}\n\n")
    try:
        try:
            from PySide6.QtCore import qInstallMessageHandler

            def qt_msg(kind, ctx, msg):
                log.write(f"[Qt {int(kind) if hasattr(kind, '__int__') else kind}] {msg}\n")
            qInstallMessageHandler(qt_msg)
        except Exception:  # noqa: BLE001 – reported by the import below
            pass
        from resrijan.gui import main as gui_main
        rc = gui_main(argv)
        log.write(f"\nexit code {rc}\n")
        if rc:
            log.flush()
            _message_box("ReSrijan could not start",
                         _tail(path) + f"\n\nThe full log is in:\n{path}")
        return rc or 0
    except SystemExit as exc:
        return int(exc.code or 0) if not isinstance(exc.code, str) else 1
    except BaseException:  # noqa: BLE001 – show every start-up failure
        tb = traceback.format_exc()
        log.write("\n" + tb)
        log.flush()
        _message_box("ReSrijan could not start",
                     tb.strip().splitlines()[-1] + "\n\n" + _tail(path, 25) +
                     f"\n\nThe full log is in:\n{path}\n\nPlease send this file to the ReSrijan team. "
                     "The Start-menu entry 'ReSrijan – troubleshoot' shows more.")
        return 1


def _tail(path: Path, n: int = 15) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


if __name__ == "__main__":
    sys.exit(main())
