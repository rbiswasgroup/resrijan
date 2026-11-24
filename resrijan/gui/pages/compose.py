"""Compose: edit a multi-panel figure spec (YAML), preview it, build it (`resrijan compose`)."""
from __future__ import annotations

from pathlib import Path
from typing import List

import yaml
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QImage
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSplitter

from ... import cli
from ..icons import icon
from ..render import compose_preview
from ..widgets import CommandBar, FormatChecks, ImagePanel, PathEdit, primary_button
from ..textedit import ColorButton, SymbolButton, insert_text, script_buttons
from .base import Page

NEW_SPEC = """# Multi-panel figure: one entry per panel, laid out automatically.
# Paths are relative to this file. See tutorial 13 for every option.
figure:
  template: natchem          # natchem | acs | aps | jcp | science | pnas | rsc | presentation | path/to/own.yaml
  width: double              # single | onehalf | double | <mm>
  labels: true               # a, b, c … in the journal's style
  formats: [pdf, svg, png]
  output: output/my_figure   # relative to this file
panels:
  - type: line
    data: data.csv
    x: time
    y: [signal_a, signal_b]
    labels: ["sample A", "sample B"]
    xlabel: "t (ps)"
    ylabel: "Signal (a.u.)"
  - type: scatter
    data: data.csv
    x: time
    y: [signal_a]
    xlabel: "t (ps)"
    ylabel: "Signal (a.u.)"
"""


class ComposePage(Page):
    title = "Compose"
    subtitle = "Build a multi-panel figure from several data files, laid out and labelled in the journal's style."
    icon = "compose"

    def __init__(self, win):
        super().__init__(win)
        self.path = ""
        bar = QHBoxLayout()
        for txt, ic, fn in (("New", "duplicate", self.new), ("Open…", "open", self.open_dialog),
                            ("Save", "save", self.save), ("Save as…", "save", self.save_as),
                            ("Example", "compose", self.example)):
            b = QPushButton(icon(ic), txt)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.name = QLabel("unsaved spec")
        self.name.setObjectName("Muted")
        self.name.setMinimumWidth(80)
        self.name.setMaximumWidth(420)
        sym = SymbolButton(lambda: self.editor)
        sup, sub = script_buttons(lambda: self.editor)
        colour = ColorButton("Insert a colour code")
        colour.setToolTip("Insert a colour code at the cursor, e.g. for  colors: [...]")
        colour.changed.connect(lambda c: c and insert_text(self.editor, f'"{c}"'))
        for w in (sym, sup, sub, colour):
            bar.addWidget(w)
        bar.addWidget(self.name)
        bar.addStretch(1)
        self.auto = QCheckBox("Live preview")
        self.auto.setChecked(win.prefs.get("auto_preview"))
        prev = QPushButton(icon("refresh"), "Preview")
        prev.clicked.connect(self.preview)
        bar.addWidget(self.auto)
        bar.addWidget(prev)
        self.body.addLayout(bar)

        sp = QSplitter()
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("Code")
        f = QFont("DejaVu Sans Mono")
        f.setPointSizeF(10)
        self.editor.setFont(f)
        self.editor.setTabStopDistance(18)
        self.editor.setPlainText(NEW_SPEC)
        self.editor.textChanged.connect(self.changed)
        self.view = ImagePanel("Preview of the figure")
        sp.addWidget(self.editor)
        sp.addWidget(self.view)
        sp.setSizes([520, 700])
        self.body.addWidget(sp, 1)

        opt = QHBoxLayout()
        opt.addWidget(QLabel("Save as"))
        self.out = PathEdit("save", "Figure base name (*)", "as set in the spec (figure: output)")
        opt.addWidget(self.out, 2)
        self.own_formats = QCheckBox("Formats:")
        self.own_formats.setToolTip("Override the formats listed in the spec")
        self.formats = FormatChecks(default=win.prefs.get("formats"))
        self.formats.setEnabled(False)
        self.own_formats.toggled.connect(self.formats.setEnabled)
        opt.addWidget(self.own_formats)
        opt.addWidget(self.formats, 2)
        self.body.addLayout(opt)
        bottom = QHBoxLayout()
        self.cmd = CommandBar()
        bottom.addWidget(self.cmd, 1)
        self.build_btn = primary_button("Build figure", "run")
        self.build_btn.clicked.connect(self.build)
        bottom.addWidget(self.build_btn)
        self.body.addLayout(bottom)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(900)
        self._timer.timeout.connect(self.preview)
        self.out.edit.textChanged.connect(self.update_command)
        self.own_formats.toggled.connect(self.update_command)
        self.formats.changed.connect(self.update_command)
        self.update_command()

    # ───────────────────────── files ─────────────────────────
    def new(self):
        self.path = ""
        self.name.setText("unsaved spec")
        self.editor.setPlainText(NEW_SPEC)

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open figure spec", self.path or str(Path.home()), "YAML (*.yaml *.yml)")
        if p:
            self.open_path(p)

    def open_path(self, path: str):
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            self.error("Open", str(exc))
            return
        self.path = path
        self._show_name()
        self.editor.setPlainText(text)
        self.win.prefs.add_recent(path)
        self.update_command()
        self.preview()

    def example(self):
        from ...plot.templates import TEMPLATE_DIR
        ex = TEMPLATE_DIR.parent.parent / "examples" / "11_compose_figure" / "figure_natchem.yaml"
        if ex.exists():
            self.open_path(str(ex))
        else:
            self.info("Example", "The example figure (examples/11_compose_figure) comes with the source code on GitHub.")

    def save(self) -> bool:
        if not self.path:
            return self.save_as()
        try:
            Path(self.path).write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            self.error("Save", str(exc))
            return False
        self.win.status(f"Saved {self.path}")
        return True

    def save_as(self) -> bool:
        p, _ = QFileDialog.getSaveFileName(self, "Save figure spec", self.path or str(Path.home() / "figure.yaml"),
                                           "YAML (*.yaml *.yml)")
        if not p:
            return False
        self.path = p
        self._show_name()
        self.update_command()
        return self.save()

    def _show_name(self):
        fm = self.name.fontMetrics()
        self.name.setText(fm.elidedText(self.path, Qt.ElideMiddle, 400))
        self.name.setToolTip(self.path)

    # ───────────────────────── preview & build ─────────────────────────
    def changed(self):
        if self.auto.isChecked():
            self._timer.start()

    def preview(self):
        if self.win.runner.busy:
            self._timer.start()
            return
        try:
            spec = yaml.safe_load(self.editor.toPlainText())
            assert isinstance(spec, dict) and spec.get("panels"), "the spec needs a 'panels:' list"
        except (yaml.YAMLError, AssertionError) as exc:
            self.win.status(f"Spec not valid yet: {exc}")
            return
        base = str(Path(self.path).parent) if self.path else str(Path.home())
        self.win.runner.run("Preview", lambda: compose_preview(spec, base),
                            lambda png: self.view.view.set_image(QImage.fromData(png), fit=not self.view.view.has_image()),
                            lambda m: self.win.status("Preview failed – see the log."))

    def argv(self) -> List[str]:
        a = ["compose", self.path or "SPEC.yaml"]
        if self.out.text():
            a += ["-o", self.out.text()]
        if self.own_formats.isChecked() and self.formats.value():
            a += ["-f", self.formats.value()]
        return a

    def update_command(self, *_):
        self.cmd.set_argv(self.argv())

    def build(self):
        if not self.save():
            return
        argv = self.argv()
        a = self.parse(argv)

        def job():
            print(self.command_text(argv))
            files = cli.run_compose(a)
            print("\n".join(files))
            return files

        def done(files):
            self.win.status("Built " + ", ".join(Path(f).name for f in files))
            png = next((f for f in files if f.endswith(".png")), None)
            if png:
                self.view.view.set_image(png)

        self.win.runner.run("Building figure", job, done, lambda m: self.error("Compose failed", m))

    # project files: the spec text itself is stored (it may not have been saved to a file yet)
    def state(self) -> dict:
        return {"spec": self.path, "text": self.editor.toPlainText(), "out": self.out.text(),
                "own_formats": self.own_formats.isChecked(), "formats": self.formats.value()}

    def set_state(self, s: dict):
        self.path = s.get("spec", "") or ""
        self.editor.setPlainText(s.get("text", ""))
        self.out.setText(s.get("out", ""))
        self.own_formats.setChecked(bool(s.get("own_formats")))
        if s.get("formats"):
            self.formats.set_value(s["formats"])
        self.update_command()
