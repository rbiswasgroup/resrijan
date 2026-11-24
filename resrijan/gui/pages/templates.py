"""Templates: browse journal styles with a sample figure; import, duplicate, edit and delete
your own (`resrijan templates`, user folder ~/.config/resrijan/templates)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QImage
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import templates_io as TIO
from ..icons import icon
from ..render import template_sample
from ..widgets import ImagePanel
from .base import Page


class TemplatesPage(Page):
    title = "Journal templates"
    subtitle = "Every replot follows a template: column widths, fonts, line widths, colours. Import your own or adapt a built-in one."
    icon = "templates"

    def __init__(self, win):
        super().__init__(win)
        bar = QHBoxLayout()
        self.b_import = QPushButton(icon("import"), "Import…")
        self.b_import.setToolTip("Add a template YAML file to your templates folder")
        self.b_import.clicked.connect(self.import_dialog)
        self.b_dup = QPushButton(icon("duplicate"), "Duplicate as new…")
        self.b_dup.clicked.connect(self.duplicate)
        self.b_save = QPushButton(icon("save"), "Save changes")
        self.b_save.clicked.connect(self.save_changes)
        self.b_del = QPushButton(icon("delete"), "Delete")
        self.b_del.setObjectName("Danger")
        self.b_del.clicked.connect(self.delete)
        self.b_folder = QPushButton(icon("folder"), "Open folder")
        self.b_folder.clicked.connect(self.open_folder)
        for b in (self.b_import, self.b_dup, self.b_save, self.b_del):
            bar.addWidget(b)
        bar.addStretch(1)
        self.where = QLabel("Your templates folder")
        self.where.setObjectName("Muted")
        self.where.setToolTip(str(TIO.user_dir()))
        bar.addWidget(self.where)
        bar.addWidget(self.b_folder)
        self.body.addLayout(bar)

        sp = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Key", "Journal", "Source"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.currentItemChanged.connect(self.select)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.sample = ImagePanel("Sample figure in this style")
        self.yaml = QPlainTextEdit()
        self.yaml.setObjectName("Code")
        f = QFont("DejaVu Sans Mono")
        f.setPointSizeF(10)
        self.yaml.setFont(f)
        self.tabs.addTab(self.sample, "Sample figure")
        self.tabs.addTab(self.yaml, "Definition (YAML)")
        rl.addWidget(self.tabs, 1)
        sp.addWidget(self.tree)
        sp.addWidget(right)
        sp.setSizes([420, 800])
        self.body.addWidget(sp, 1)
        self.refresh()

    # ───────────────────────── list ─────────────────────────
    def refresh(self, select: str = ""):
        from ...plot import templates as T
        TIO.reload()
        cur = select or (self.tree.currentItem().text(0) if self.tree.currentItem() else "natchem")
        self.tree.clear()
        for t in T.available():
            src = "yours" if TIO.is_user_template(t) else "built-in"
            it = QTreeWidgetItem([t.key, t.name, src])
            it.setData(0, Qt.UserRole, t.key)
            self.tree.addTopLevelItem(it)
            if t.key == cur:
                self.tree.setCurrentItem(it)
        for c in range(3):
            self.tree.resizeColumnToContents(c)
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.win.templates_changed()

    def current(self):
        from ...plot import templates as T
        it = self.tree.currentItem()
        return T.get(it.data(0, Qt.UserRole)) if it else None

    def select(self, *_):
        t = self.current()
        if t is None:
            return
        mine = TIO.is_user_template(t)
        self.summary.setText(
            f"<b style='font-size:15px'>{t.name}</b> &nbsp; <span style='color:#8a96b0'>key <code>{t.key}</code>"
            + (f" · also: {', '.join(t.aliases)}" if t.aliases else "") + "</span><br>"
            + "Widths: " + ", ".join(f"{k} {v:g} mm" for k, v in t.widths_mm.items())
            + f" · max height {t.max_height_mm:g} mm · {t.font['names'][0]} {t.font['tick']}–{t.font['label']} pt"
            + f" · panel label '{t.label(0)}' · font on this computer: {t.resolved_font()}")
        try:
            self.yaml.setPlainText(Path(t.path).read_text(encoding="utf-8"))
        except OSError:
            self.yaml.setPlainText("")
        self.yaml.setReadOnly(not mine)
        self.b_save.setEnabled(mine)
        self.b_del.setEnabled(mine)
        self.sample.view.set_image(None)
        self.sample.view.set_placeholder("Drawing a sample …")
        self._rendered = None
        if self.isVisible():
            self._render(t.key)

    def showEvent(self, e):
        super().showEvent(e)
        t = self.current()
        if t is not None and getattr(self, "_rendered", None) != t.key:
            self._render(t.key)

    def _render(self, key: str):
        if self.win.runner.busy:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(400, lambda: self._render(key))
            return
        self._rendered = key

        def show(png):
            cur = self.current()
            if cur is not None and cur.key == key:
                self.sample.view.set_image(QImage.fromData(png))

        self.win.runner.run(f"Sample figure ({key})", lambda: template_sample(key), show,
                            lambda m: self.sample.view.set_placeholder("This template cannot draw a figure – see the log."))

    # ───────────────────────── actions ─────────────────────────
    def import_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Import a journal template", str(Path.home()), "Template (*.yaml *.yml)")
        if p:
            self.import_path(p)

    def import_path(self, path: str):
        try:
            y = TIO.validate(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.error("Import", f"{Path(path).name} is not a usable template.\n\n{exc}")
            return
        key = y["key"]
        overwrite = False
        if key in TIO.builtin_keys():
            ok = QMessageBox.question(self, "Import", f"'{key}' is a built-in template. Import yours under the same key "
                                      "and use it instead of the built-in one?")
            if ok != QMessageBox.Yes:
                return
        if TIO.target_path(key).exists():
            if QMessageBox.question(self, "Import", f"You already have a template '{key}'. Replace it?") != QMessageBox.Yes:
                return
            overwrite = True
        try:
            dest = TIO.import_file(path, overwrite=overwrite)
        except (OSError, ValueError) as exc:
            self.error("Import", str(exc))
            return
        self.refresh(select=key)
        self.win.status(f"Imported template '{key}' → {dest}")

    def duplicate(self):
        t = self.current()
        if t is None:
            return
        key, ok = QInputDialog.getText(self, "Duplicate template", "Key for the new template (lower case, e.g. mylab):",
                                       text=f"{t.key}-custom")
        if not ok or not key.strip():
            return
        name, ok = QInputDialog.getText(self, "Duplicate template", "Journal / style name:", text=f"{t.name} (custom)")
        if not ok:
            return
        text = TIO.duplicate_text(t.path, key.strip().lower(), name.strip() or key)
        try:
            TIO.save_template(text, overwrite=False)
        except FileExistsError:
            self.error("Duplicate", f"You already have a template '{key}'.")
            return
        except ValueError as exc:
            self.error("Duplicate", str(exc))
            return
        self.refresh(select=key.strip().lower())
        self.tabs.setCurrentIndex(1)
        self.win.status(f"Created '{key}'. Edit its definition, then Save changes.")

    def save_changes(self):
        t = self.current()
        if t is None or not TIO.is_user_template(t):
            return
        text = self.yaml.toPlainText()
        try:
            y = TIO.validate(text)
        except ValueError as exc:
            self.error("Save", str(exc))
            return
        if y["key"] != t.key:
            self.error("Save", "Keep the same 'key' (use Duplicate as new to make another template).")
            return
        TIO.save_template(text, overwrite=True)
        self.refresh(select=t.key)
        self.win.status(f"Saved template '{t.key}'.")

    def delete(self):
        t = self.current()
        if t is None or not TIO.is_user_template(t):
            return
        if QMessageBox.question(self, "Delete", f"Delete your template '{t.key}' ({t.path})?") != QMessageBox.Yes:
            return
        TIO.delete(t.key)
        self.refresh(select="natchem")

    def open_folder(self):
        d = TIO.user_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def open_path(self, path: str):
        self.import_path(path)
