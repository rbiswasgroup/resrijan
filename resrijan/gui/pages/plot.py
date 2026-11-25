"""Plot: every option of `resrijan plot` with column pickers and a live preview."""
from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTableWidget, QTableWidgetItem)

from ... import cli
from ..icons import icon
from ..render import plot_preview
from ..widgets import CommandBar, FormatChecks, ImagePanel, PathEdit, TemplateCombo, WidthCombo, primary_button
from ..textedit import ColorButton, MathLineEdit
from .base import Page

DATA_FILTER = ("Data (*.csv *.tsv *.txt *.dat *.npz *.png *.tif *.tiff *.jpg);;All files (*)")
CMAPS = ["", "viridis", "magma", "inferno", "plasma", "cividis", "RdBu_r", "coolwarm", "seismic", "PuOr_r",
         "Greys", "gray", "turbo"]
TABLE_KINDS = {"line", "scatter", "errorbar", "bar", "hist"}
GRID_KINDS = {"heatmap", "contourf", "contour", "spectrum2d"}


class PlotPage(Page):
    title = "Plot"
    subtitle = "Turn your own data file into a journal-style figure."
    icon = "plot"

    def __init__(self, win):
        super().__init__(win)
        P = win.prefs
        self.columns: List[str] = []
        opts, work = self.split(470)

        d = self.group("Data", opts)
        self.data = PathEdit("open", DATA_FILTER, "CSV, TSV or text table; grid CSV; NPZ; image")
        self.data.changed.connect(self.open_path)
        d.addRow("File", self.data)
        self.kind = QComboBox()
        self.kind.addItems(cli.PLOT_KINDS)
        self.kind.currentTextChanged.connect(self._kind_changed)
        d.addRow("Plot type", self.kind)

        c = self.group("Columns", opts)
        self.c_group = c.parentWidget()
        self.x = QComboBox()
        c.addRow("x", self.x)
        self.ytab = QTableWidget(0, 4)
        self.ytab.setHorizontalHeaderLabels(["Plot", "y column", "error bars", "colour"])
        self.ytab.verticalHeader().setVisible(False)
        self.ytab.horizontalHeader().setStretchLastSection(True)
        self.ytab.setMinimumHeight(130)
        self.ytab.setMaximumHeight(200)
        c.addRow("y", self.ytab)
        self.column = QComboBox()
        c.addRow("Histogram of", self.column)

        a = self.group("Axes and labels", opts)
        self.xlabel, self.ylabel, self.clabel = MathLineEdit(), MathLineEdit(), MathLineEdit()
        self.xlabel.setPlaceholderText("e.g. t (ps)")
        self.ylabel.setPlaceholderText("e.g. C(t) or k (s$^{-1}$)")
        self.clabel.setPlaceholderText("colour-bar title (maps)")
        a.addRow("x title", self.xlabel)
        a.addRow("y title", self.ylabel)
        a.addRow("Colour bar", self.clabel)
        self.label_color = ColorButton("Black (journal style)")
        self.label_color.changed.connect(self.changed)
        a.addRow("Title colour", self.row(self.label_color))
        self.xscale, self.yscale = QComboBox(), QComboBox()
        for cb in (self.xscale, self.yscale):
            cb.addItem("default", "")
            cb.addItem("linear", "linear")
            cb.addItem("log", "log")
        a.addRow("Scales", self.row(QLabel("x"), self.xscale, QLabel("y"), self.yscale))
        self.xlim, self.ylim = QLineEdit(), QLineEdit()
        self.xlim.setPlaceholderText("min,max (reverse: max,min)")
        self.ylim.setPlaceholderText("min,max")
        a.addRow("x range", self.xlim)
        a.addRow("y range", self.ylim)
        self.cmap = QComboBox()
        self.cmap.setEditable(True)
        self.cmap.addItems(CMAPS)
        self.cmap.setToolTip("Matplotlib colour map for maps and images (empty: the template's choice)")
        a.addRow("Colour map", self.cmap)
        self.nm = QDoubleSpinBox()
        self.nm.setRange(0, 1e6)
        self.nm.setDecimals(5)
        self.nm.setSpecialValueText("no scale bar")
        self.nm.setSuffix(" nm/px")
        a.addRow("Image pixel", self.nm)

        s = self.group("Style and output", opts)
        self.template = TemplateCombo()
        self.template.set_value(P.get("template"))
        s.addRow("Journal", self.template)
        self.width = WidthCombo(P.get("width"))
        s.addRow("Width", self.width)
        self.formats = FormatChecks(default=P.get("formats"))
        s.addRow("Formats", self.formats)
        self.out = PathEdit("save", "Figure base name (*)", "next to the data: <name>_plot")
        s.addRow("Save as", self.out)
        opts.addStretch(1)

        bar = QHBoxLayout()
        self.auto = QCheckBox("Live preview")
        self.auto.setChecked(P.get("auto_preview"))
        refresh = QPushButton(icon("refresh"), "Preview")
        refresh.clicked.connect(self.preview)
        bar.addWidget(self.auto)
        bar.addStretch(1)
        bar.addWidget(refresh)
        work.addLayout(bar)
        self.view = ImagePanel("Choose a data file to see the figure.")
        work.addWidget(self.view, 1)
        self.cmd = CommandBar()
        bottom = QHBoxLayout()
        bottom.addWidget(self.cmd, 1)
        self.save_btn = primary_button("Save figure", "save")
        self.save_btn.clicked.connect(self.save)
        bottom.addWidget(self.save_btn)
        work.addLayout(bottom)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self.preview)
        for e in (self.xlabel, self.ylabel, self.clabel, self.xlim, self.ylim):
            e.textChanged.connect(self.changed)
        for cb in (self.x, self.column, self.xscale, self.yscale, self.template, self.width):
            cb.currentIndexChanged.connect(self.changed)
        self.cmap.currentTextChanged.connect(self.changed)
        self.width.editTextChanged.connect(self.changed)
        self.nm.valueChanged.connect(self.changed)
        self.formats.changed.connect(self.changed)
        self.out.edit.textChanged.connect(self.changed)
        self.ytab.itemChanged.connect(self.changed)
        self._kind_changed(self.kind.currentText())

    # ───────────────────────── data ─────────────────────────
    def open_path(self, path: str):
        if not path or not Path(path).is_file():
            return
        self.data.setText(path)
        self.win.prefs.add_recent(path)
        self.out.edit.setPlaceholderText(str(Path(path).with_name(Path(path).stem + "_plot")))
        self.columns = []
        if Path(path).suffix.lower() in (".csv", ".tsv", ".txt", ".dat", ".npz"):
            try:
                from ...plot.engine import read_table
                self.columns = list(read_table(path).keys())
            except Exception:  # noqa: BLE001 – grids and images have no columns
                self.columns = []
        else:
            self.kind.setCurrentText("image")
        self._fill_columns()
        self.changed()

    def _fill_columns(self):
        cols = self.columns
        for cb in (self.x, self.column):
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(cols)
            cb.blockSignals(False)
        self.ytab.blockSignals(True)
        self.ytab.setRowCount(0)
        for i, name in enumerate(cols[1:]):
            self.ytab.insertRow(i)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            low = name.lower()
            is_err = _is_error_column(low)
            chk.setCheckState(Qt.Unchecked if is_err else Qt.Checked)
            self.ytab.setItem(i, 0, chk)
            it = QTableWidgetItem(name)
            it.setFlags(Qt.ItemIsEnabled)
            self.ytab.setItem(i, 1, it)
            err = QComboBox()
            err.addItem("")
            err.addItems(cols)
            if not is_err:                   # pair a data column with its error column (err_urea ↔ D_urea)
                stem = low.split("_")[-1]
                guess = next((c for c in cols if _is_error_column(c.lower()) and
                              (c.lower() in (f"err_{low}", f"{low}_err", f"sd_{low}", f"d{low}")
                               or c.lower().endswith("_" + stem) or c.lower().endswith(stem + "_err"))), "")
                err.setCurrentText(guess)
            err.currentIndexChanged.connect(self.changed)
            self.ytab.setCellWidget(i, 2, err)
            col = ColorButton()
            col.changed.connect(self.changed)
            self.ytab.setCellWidget(i, 3, col)
        self.ytab.blockSignals(False)
        for c in (0, 1, 3):
            self.ytab.resizeColumnToContents(c)

    def _kind_changed(self, kind: str):
        table = kind in TABLE_KINDS
        self.c_group.setVisible(table)
        self.column.setEnabled(kind == "hist")
        self.ytab.setEnabled(kind != "hist")
        self.clabel.setEnabled(kind in GRID_KINDS or kind == "image")
        self.cmap.setEnabled(kind in GRID_KINDS or kind == "image")
        self.nm.setEnabled(kind == "image")
        self.changed()

    # ───────────────────────── command ─────────────────────────
    def _colors(self):
        return [self.ytab.cellWidget(r, 3).value() for r in range(self.ytab.rowCount())
                if self.ytab.item(r, 0).checkState() == Qt.Checked]

    def _y_and_err(self):
        ys, errs = [], []
        for r in range(self.ytab.rowCount()):
            if self.ytab.item(r, 0).checkState() == Qt.Checked:
                ys.append(self.ytab.item(r, 1).text())
                errs.append(self.ytab.cellWidget(r, 2).currentText())
        return ys, errs

    def argv(self, for_preview: bool = False) -> List[str]:
        path = self.data.text()
        kind = self.kind.currentText()
        a = ["plot", path or "DATA"]
        if kind != "line":
            a += ["--kind", kind]
        if kind in TABLE_KINDS and self.columns:
            if kind == "hist":
                if self.column.currentText():
                    a += ["--column", self.column.currentText()]
            else:
                if self.x.currentText():
                    a += ["-x", self.x.currentText()]
                ys, errs = self._y_and_err()
                if ys:
                    a += ["-y", ",".join(ys)]
                if any(errs):
                    a += ["--yerr", ",".join(errs)]
                cols = self._colors()
                if any(cols):
                    a += ["--colors", ",".join(cols)]
        for flag, e in (("--xlabel", self.xlabel), ("--ylabel", self.ylabel), ("--clabel", self.clabel),
                        ("--xlim", self.xlim), ("--ylim", self.ylim)):
            if e.isEnabled() and e.text().strip():
                a += [flag, e.text().strip()]
        for flag, cb in (("--xscale", self.xscale), ("--yscale", self.yscale)):
            if cb.currentData():
                a += [flag, cb.currentData()]
        if self.cmap.isEnabled() and self.cmap.currentText().strip():
            a += ["--cmap", self.cmap.currentText().strip()]
        if self.nm.isEnabled() and self.nm.value() > 0:
            a += ["--nm-per-px", f"{self.nm.value():g}"]
        if self.label_color.value():
            a += ["--label-color", self.label_color.value()]
        if self.template.value() and self.template.value() != "natchem":
            a += ["-t", self.template.value()]
        if self.width.value() != "single":
            a += ["--width", self.width.value()]
        out = self.out.text() or (str(Path(path).with_name(Path(path).stem + "_plot")) if path else "")
        if out:
            a += ["-o", out]
        if self.formats.value() != "pdf,svg,png":
            a += ["-f", self.formats.value()]
        return a

    def changed(self, *_):
        self.cmd.set_argv(self.argv())
        if self.auto.isChecked() and self.data.text():
            self._timer.start()

    def _parsed(self):
        argv = self.argv()
        try:
            return argv, self.parse(argv)
        except SystemExit:
            return argv, None

    def preview(self):
        if not self.data.text():
            return
        if self.win.runner.busy:
            self._timer.start()              # try again when the running task is done
            return
        argv, a = self._parsed()
        if a is None:
            return
        self.win.runner.run("Preview", lambda: plot_preview(a), self._show,
                            lambda m: self.view.view.set_placeholder("Cannot draw this – see the log."))

    def _show(self, png: bytes):
        self.view.view.set_image(QImage.fromData(png), fit=not self.view.view.has_image())

    def save(self):
        if not self.data.text():
            self.error("Plot", "Choose a data file first.")
            return
        if not self.formats.value():
            self.error("Plot", "Tick at least one format.")
            return
        argv, a = self._parsed()
        if a is None:
            self.error("Plot", "These options are not valid:\n\n" + self.command_text(argv))
            return

        def job():
            print(self.command_text(argv))
            files = cli.run_plot(a)
            print("\n".join(files))
            return files

        self.win.runner.run("Saving figure", job,
                            lambda files: self.win.status("Saved " + ", ".join(Path(f).name for f in files)),
                            lambda m: self.error("Plot failed", m))


def _is_error_column(name: str) -> bool:
    """Column names that hold uncertainties (plotted as error bars, not as data)."""
    return name.startswith(("err", "sd_", "std", "sigma", "unc", "yerr")) or name.endswith(("_err", "_sd", "_std"))
