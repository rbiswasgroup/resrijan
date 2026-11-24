"""ReSrijan graphical interface (PySide6).  Start with ``resrijan gui`` or ``resrijan-gui``.

Every page builds a `resrijan …` command line, parses it with the CLI's own parser and runs
the same functions as the command line, so the GUI can do everything the CLI can (and shows
the equivalent command for scripts)."""
from __future__ import annotations

import os
import sys


def main(argv=None) -> int:
    os.environ.setdefault("MPLBACKEND", "Agg")      # figures are drawn off-screen, in worker threads
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write("The ReSrijan GUI needs PySide6:\n    pip install \"resrijan[gui]\"\n")
        return 1
    import matplotlib
    matplotlib.use("Agg")
    from PySide6.QtGui import QIcon

    from . import theme
    from .mainwindow import ASSETS, MainWindow

    argv = list(sys.argv[1:] if argv is None else argv)
    if sys.platform.startswith("win"):      # own taskbar group and icon (not Python's)
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ReSrijan.ReSrijan")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("ReSrijan")
    app.setOrganizationName("ReSrijan")
    app.setDesktopFileName("resrijan")
    app.setWindowIcon(QIcon(str(ASSETS / "resrijan-icon-512.png")))
    theme.apply(app)
    win = MainWindow()
    win.show()
    files = [a for a in argv if not a.startswith("-")]
    if files:
        win.open_any(os.path.abspath(files[0]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
