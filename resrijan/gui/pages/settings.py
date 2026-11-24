"""Settings: defaults for every page, desktop integration, and About."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QSpinBox, QVBoxLayout)

from ... import __version__
from .. import desktop
from .. import templates_io as TIO
from ..icons import icon
from ..widgets import FormatChecks, PathEdit, TemplateCombo, WidthCombo, primary_button
from .base import Page


class SettingsPage(Page):
    title = "Settings"
    subtitle = "Defaults used when you open a file, and how ReSrijan fits into your desktop."
    icon = "settings"

    def __init__(self, win):
        super().__init__(win)
        P = win.prefs
        cols = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        cols.addLayout(left, 3)
        cols.addSpacing(16)
        cols.addLayout(right, 2)
        self.body.addLayout(cols, 1)

        r = self.group("Replots", left)
        self.template = TemplateCombo()
        self.template.set_value(P.get("template"))
        r.addRow("Journal", self.template)
        self.width = WidthCombo(P.get("width"))
        r.addRow("Width", self.width)
        self.formats = FormatChecks(default=P.get("formats"))
        r.addRow("Formats", self.formats)

        d = self.group("Digitizing", left)
        self.dpi = QDoubleSpinBox()
        self.dpi.setRange(72, 2400)
        self.dpi.setDecimals(0)
        self.dpi.setSingleStep(50)
        self.dpi.setSuffix(" dpi")
        self.dpi.setValue(P.get("dpi"))
        self.dpi.setToolTip("Resolution at which PDF/EPS/SVG pages are rendered for reading (600 is the command-line default)")
        d.addRow("Render resolution", self.dpi)
        self.max_series = QSpinBox()
        self.max_series.setRange(1, 60)
        self.max_series.setValue(P.get("max_series"))
        d.addRow("Max. series", self.max_series)
        self.out_mode = QComboBox()
        self.out_mode.addItem("Next to the figure (<name>_resrijan)", "next")
        self.out_mode.addItem("In one folder", "folder")
        self.out_mode.setCurrentIndex(0 if P.get("out_mode") == "next" else 1)
        d.addRow("Output", self.out_mode)
        self.out_folder = PathEdit("dir")
        self.out_folder.setText(P.get("out_folder"))
        self.out_folder.setEnabled(P.get("out_mode") == "folder")
        self.out_mode.currentIndexChanged.connect(lambda i: self.out_folder.setEnabled(i == 1))
        d.addRow("Folder", self.out_folder)
        self.open_report = QCheckBox("Open the HTML report in the browser after each run")
        self.open_report.setChecked(P.get("open_report"))
        d.addRow("", self.open_report)

        v = self.group("Previews", left)
        self.preview_dpi = QDoubleSpinBox()
        self.preview_dpi.setRange(50, 300)
        self.preview_dpi.setDecimals(0)
        self.preview_dpi.setSuffix(" dpi")
        self.preview_dpi.setValue(P.get("preview_dpi"))
        v.addRow("Figure preview", self.preview_dpi)
        self.auto_preview = QCheckBox("Redraw Plot and Compose previews while you edit")
        self.auto_preview.setChecked(P.get("auto_preview"))
        v.addRow("", self.auto_preview)
        btns = QHBoxLayout()
        save = primary_button("Save settings", "save")
        save.clicked.connect(self.save)
        reset = QPushButton("Restore defaults")
        reset.clicked.connect(self.reset)
        btns.addWidget(save)
        btns.addWidget(reset)
        btns.addStretch(1)
        left.addLayout(btns)
        left.addStretch(1)

        a = self.group("Desktop", right)
        b_inst = QPushButton(icon("import"), "Add to the application menu")
        b_inst.setToolTip("Creates ~/.local/share/applications/resrijan.desktop with the ReSrijan icon")
        b_inst.clicked.connect(self.install_desktop)
        b_rm = QPushButton("Remove")
        b_rm.clicked.connect(self.remove_desktop)
        a.addRow(self.row(b_inst, b_rm))
        tl = QLabel(f"Your journal templates live in<br><code>{TIO.user_dir()}</code>")
        tl.setWordWrap(True)
        tl.setObjectName("Muted")
        a.addRow(tl)

        ab = self.group("About", right)
        logo = QLabel()
        pm = QPixmap(str(Path(__file__).resolve().parent.parent / "assets" / "resrijan-logo-dark-calligraphic.svg"))
        if not pm.isNull():
            logo.setPixmap(pm.scaledToWidth(330, Qt.SmoothTransformation))
        ab.addRow(logo)
        txt = QLabel(
            f"<b>ReSrijan {__version__}</b> (पुनःसृजन, “re-creation”)<br>"
            "Turns published scientific figures back into data and redraws them in journal style.<br><br>"
            "Everything runs on this computer; nothing is uploaded.<br>"
            "Every action here is a <code>resrijan</code> command – see the command line under each page.<br><br>"
            "<a href='https://github.com/rbiswasgroup/resrijan'>github.com/rbiswasgroup/resrijan</a> · "
            "<a href='https://github.com/rbiswasgroup/resrijan/tree/main/docs/tutorials'>tutorials</a><br>"
            "Licence: GNU AGPL v3 or later.")
        txt.setWordWrap(True)
        txt.setOpenExternalLinks(True)
        ab.addRow(txt)
        right.addStretch(1)

    def save(self):
        P = self.win.prefs
        P.set("template", self.template.value() or "natchem")
        P.set("width", self.width.value())
        P.set("formats", self.formats.value() or "pdf,svg,png")
        P.set("dpi", self.dpi.value())
        P.set("max_series", self.max_series.value())
        P.set("out_mode", self.out_mode.currentData())
        P.set("out_folder", self.out_folder.text())
        P.set("open_report", self.open_report.isChecked())
        P.set("preview_dpi", self.preview_dpi.value())
        P.set("auto_preview", self.auto_preview.isChecked())
        self.win.status("Settings saved. They apply to files you open from now on.")

    def reset(self):
        if QMessageBox.question(self, "Settings", "Restore all settings to their defaults?") == QMessageBox.Yes:
            self.win.prefs.reset()
            P = self.win.prefs
            self.template.set_value(P.get("template"))
            self.width.setCurrentText(P.get("width"))
            self.formats.set_value(P.get("formats"))
            self.dpi.setValue(P.get("dpi"))
            self.max_series.setValue(P.get("max_series"))
            self.out_mode.setCurrentIndex(0)
            self.out_folder.setText(P.get("out_folder"))
            self.open_report.setChecked(P.get("open_report"))
            self.preview_dpi.setValue(P.get("preview_dpi"))
            self.auto_preview.setChecked(P.get("auto_preview"))

    def install_desktop(self):
        try:
            p = desktop.install_entry()
        except OSError as exc:
            self.error("Desktop", str(exc))
            return
        self.info("Desktop", f"ReSrijan is now in your application menu.\n\n{p}")

    def remove_desktop(self):
        desktop.remove_entry()
        self.win.status("Removed the application-menu entry.")

    @staticmethod
    def _open(url: str):
        QDesktopServices.openUrl(QUrl(url))
