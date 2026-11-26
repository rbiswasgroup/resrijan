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
from .pages.analyze import AnalyzePage
from .pages.compose import ComposePage
from .pages.digitize import DigitizePage
from .pages.fit import FitPage
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
        for key, cls in (("digitize", DigitizePage), ("plot", PlotPage), ("analyze", AnalyzePage), ("fit", FitPage),
                         ("compose", ComposePage),
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
    DATA_PAGES = ("plot", "analyze", "fit")
    shared_data = ""

    def show_page(self, key: str):
        keys = list(self.pages)
        page = self.pages[key]
        # Plot, Analyze and Fit share one data file: the last one opened follows you between them
        if key in self.DATA_PAGES and self.shared_data and page.data.text() != self.shared_data \
                and Path(self.shared_data).is_file():
            page.open_path(self.shared_data)
        self.stack.setCurrentWidget(page)
        self.nav.button(keys.index(key)).setChecked(True)

    def data_opened(self, path: str):
        """A data page opened ``path``: the other data pages will use it too."""
        self.shared_data = path

    def open_in(self, key: str, path: str):
        if key in self.DATA_PAGES and Path(path).is_file():
            self.shared_data = path          # show_page loads it
            self.show_page(key)
            if self.pages[key].data.text() != path:
                self.pages[key].open_path(path)
            return
        self.show_page(key)
        self.pages[key].open_path(path)

    def open_any(self, path: str):
        """Route a file to the page that handles it."""
        p = Path(path)
        ext = p.suffix.lower()
        if ext == ".resrijan":
            self.open_project(path)
        elif ext in (".yaml", ".yml"):
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
        for text, key, fn in (("Open &project…", "Ctrl+Shift+O", self.open_project),
                              ("&Save project", "Ctrl+S", self.save_project),
                              ("Save project &as…", "Ctrl+Shift+S", lambda: self.save_project(ask=True))):
            a = QAction(text, self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        ed = QAction("&Edit data file…", self)
        ed.setShortcut(QKeySequence("Ctrl+E"))
        ed.triggered.connect(self.edit_data_dialog)
        m.addAction(ed)
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

    def edit_data_dialog(self, path: str = ""):
        from .editor import DataEditor
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Edit data file", str(Path.home()),
                                                  "Data (*.csv *.tsv *.txt *.dat);;All files (*)")
        if not path:
            return None
        try:
            dlg = DataEditor(path, title=Path(path).name, parent=self)
        except Exception as exc:  # noqa: BLE001
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Edit data", str(exc))
            return None
        dlg.saved.connect(lambda out: self.status(f"Saved edited data: {Path(out).name}"))
        self.editor = dlg
        dlg.show()
        return dlg

    # ───────────────────────── projects ─────────────────────────
    project_path = None

    def project_state(self) -> dict:
        return {k: p.state() for k, p in self.pages.items() if hasattr(p, "state")}

    def save_project(self, ask: bool = False, path: str = ""):
        from . import project
        path = path or (None if ask else self.project_path)
        if not path:
            start = self.project_path or str(Path.home() / ("figure" + project.EXT))
            path, _ = QFileDialog.getSaveFileName(self, "Save project", start, f"ReSrijan project (*{project.EXT})")
            if not path:
                return None
        cur = next((k for k, p in self.pages.items() if p is self.stack.currentWidget()), "digitize")
        path = project.save(path, self.project_state(), cur)
        self.project_path = path
        self.setWindowTitle(f"ReSrijan – {Path(path).name}")
        self.prefs.add_recent(path)
        self.status(f"Project saved: {path}")
        return path

    def open_project(self, path: str = ""):
        from . import project
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open project", str(Path.home()),
                                                  f"ReSrijan project (*{project.EXT});;All files (*)")
        if not path:
            return
        try:
            doc = project.load(path)
        except Exception as exc:  # noqa: BLE001
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Open project", str(exc))
            return
        missing = []
        for key, st in doc["pages"].items():
            page = self.pages.get(key)
            if page is not None and hasattr(page, "set_state"):
                try:
                    page.set_state(st)
                except Exception as exc:  # noqa: BLE001
                    missing.append(f"{page.title}: {exc}")
        self.project_path = path
        self.setWindowTitle(f"ReSrijan – {Path(path).name}")
        self.prefs.add_recent(path)
        if doc.get("current_page") in self.pages:
            self.show_page(doc["current_page"])
        self.status(f"Project opened: {Path(path).name}" + (f" ({len(missing)} problem(s), see the log)" if missing else ""))
        for m in missing:
            self.log.add(m)

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
                                           "*.bmp *.gif *.webp *.csv *.tsv *.txt *.dat *.npz *.yaml *.yml *.resrijan);;All files (*)")
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
