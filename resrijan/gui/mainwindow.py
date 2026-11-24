"""Main window: sidebar navigation, pages, status bar with a busy indicator, log panel,
drag-and-drop and keyboard shortcuts."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QProgressBar, QPushButton,
                               QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import __version__
from .icons import icon, nav_icon
from .jobs import JobRunner
from .pages.compose import ComposePage
from .pages.digitize import DigitizePage
from .pages.inspect import InspectPage
from .pages.plot import PlotPage
from .pages.settings import SettingsPage
from .pages.templates import TemplatesPage
from .prefs import Prefs
from .widgets import LogView, TemplateCombo

ASSETS = Path(__file__).resolve().parent / "assets"
DATA_EXT = {".csv", ".tsv", ".txt", ".dat", ".npz"}


class MainWindow(QMainWindow):
    def __init__(self, synchronous: bool = False):
        super().__init__()
        self.setWindowTitle("ReSrijan")
        self.setWindowIcon(QIcon(str(ASSETS / "resrijan-icon-512.png")))
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.prefs = Prefs()
        self.runner = JobRunner(self, synchronous=synchronous)

        # status bar first: pages report to it while they are built
        self.msg = QLabel("Ready")
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setMaximumWidth(160)
        self.busy.setVisible(False)
        self.b_log = QToolButton()
        self.b_log.setIcon(icon("terminal"))
        self.b_log.setText(" Log")
        self.b_log.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.b_log.setCheckable(True)
        sb = self.statusBar()
        sb.addWidget(self.msg, 1)
        sb.addPermanentWidget(self.busy)
        sb.addPermanentWidget(self.b_log)

        self.log = LogView()
        self.log.setVisible(False)
        self.b_log.toggled.connect(self.log.setVisible)
        self.runner.started.connect(self._job_started)
        self.runner.line.connect(self.log.add)
        self.runner.finished.connect(self._job_finished)

        # pages
        self.pages = {}
        self.stack = QStackedWidget()
        for key, cls in (("digitize", DigitizePage), ("plot", PlotPage), ("compose", ComposePage),
                         ("templates", TemplatesPage), ("inspect", InspectPage), ("settings", SettingsPage)):
            page = cls(self)
            self.pages[key] = page
            self.stack.addWidget(page)

        # sidebar
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        brand = QLabel()
        brand.setObjectName("Brand")
        pm = QPixmap(str(ASSETS / "resrijan-logo-dark-calligraphic.svg"))
        if not pm.isNull():
            brand.setPixmap(pm.scaledToWidth(196, Qt.SmoothTransformation))
        else:
            brand.setText("ReSrijan")
        sl.addWidget(brand)
        ver = QLabel(f"version {__version__}")
        ver.setObjectName("Version")
        sl.addWidget(ver)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for i, (key, page) in enumerate(self.pages.items()):
            b = QPushButton(nav_icon(page.icon), "  " + page.title.split()[0] if key != "templates" else "  Templates")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"{page.title}  (Ctrl+{i + 1})")
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav.addButton(b, i)
            sl.addWidget(b)
            if key == "inspect":
                sl.addStretch(1)
        foot = QLabel("Drop a figure, a data file\nor a template anywhere.")
        foot.setObjectName("Version")
        foot.setAlignment(Qt.AlignCenter)
        sl.addWidget(foot)

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.stack)
        right.addWidget(self.log)
        right.setStretchFactor(0, 1)
        right.setSizes([800, 180])
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(side)
        h.addWidget(right, 1)
        self.setCentralWidget(central)
        self._menus()
        self.show_page("digitize")

    # ───────────────────────── navigation ─────────────────────────
    def show_page(self, key: str):
        keys = list(self.pages)
        self.stack.setCurrentWidget(self.pages[key])
        self.nav.button(keys.index(key)).setChecked(True)

    def open_in(self, key: str, path: str):
        self.show_page(key)
        self.pages[key].open_path(path)

    def open_any(self, path: str):
        """Route a file to the page that handles it."""
        p = Path(path)
        ext = p.suffix.lower()
        if ext in (".yaml", ".yml"):
            try:
                import yaml
                y = yaml.safe_load(p.read_text()) or {}
            except Exception:  # noqa: BLE001
                y = {}
            self.open_in("templates" if isinstance(y, dict) and "widths_mm" in y else "compose", path)
        elif ext in DATA_EXT:
            self.open_in("plot", path)
        else:
            self.open_in("digitize", path)

    def _menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        act = QAction(icon("open"), "&Open…", self)
        act.setShortcut(QKeySequence.Open)
        act.triggered.connect(self.open_dialog)
        m.addAction(act)
        self.recent_menu = m.addMenu("Open &recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        q = QAction("&Quit", self)
        q.setShortcut(QKeySequence.Quit)
        q.triggered.connect(self.close)
        m.addAction(q)
        v = mb.addMenu("&View")
        for i, (key, page) in enumerate(self.pages.items()):
            a = QAction(page.title, self)
            a.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            a.triggered.connect(lambda _=False, k=key: self.show_page(k))
            v.addAction(a)
        v.addSeparator()
        lg = QAction("Show &log", self)
        lg.setShortcut(QKeySequence("Ctrl+L"))
        lg.triggered.connect(lambda: self.b_log.setChecked(not self.b_log.isChecked()))
        v.addAction(lg)
        hm = mb.addMenu("&Help")
        for txt, url in (("Tutorials", "https://github.com/rbiswasgroup/resrijan/tree/main/docs/tutorials"),
                         ("Report a problem", "https://github.com/rbiswasgroup/resrijan/issues")):
            a = QAction(txt, self)
            a.triggered.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            hm.addAction(a)
        ab = QAction("About ReSrijan", self)
        ab.triggered.connect(lambda: self.show_page("settings"))
        hm.addAction(ab)

    def _fill_recent(self):
        self.recent_menu.clear()
        rec = self.prefs.recent()
        if not rec:
            self.recent_menu.addAction("(none)").setEnabled(False)
        for p in rec:
            a = self.recent_menu.addAction(p)
            a.triggered.connect(lambda _=False, x=p: self.open_any(x))

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open", str(Path.home()),
                                           "All supported (*.pdf *.eps *.ps *.svg *.svgz *.png *.jpg *.jpeg *.tif *.tiff "
                                           "*.bmp *.gif *.webp *.csv *.tsv *.txt *.dat *.npz *.yaml *.yml);;All files (*)")
        if p:
            self.open_any(p)

    # ───────────────────────── drag & drop ─────────────────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self.open_any(url.toLocalFile())
                break

    # ───────────────────────── status ─────────────────────────
    def status(self, text: str):
        self.msg.setText(text)

    def _job_started(self, title: str):
        self.busy.setVisible(True)
        self.msg.setText(title + " …")

    def _job_finished(self, ok: bool):
        self.busy.setVisible(False)
        if not ok:
            self.msg.setText("Failed – details in the log.")
            self.b_log.setChecked(True)
        elif self.msg.text().endswith(" …"):
            self.msg.setText("Done.")

    def templates_changed(self):
        """Refresh every template selector after an import/edit/delete."""
        for page in getattr(self, "pages", {}).values():
            for cb in page.findChildren(TemplateCombo):
                cb.refresh()

    def closeEvent(self, e):
        self.runner.shutdown()
        super().closeEvent(e)
