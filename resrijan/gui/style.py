"""Figure styling controls shared by the Plot and Analyze pages: legend, lines, fonts and
annotations (text labels and arrows). Every control maps to a ``resrijan plot`` option."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QVBoxLayout, QWidget)

from ..plot.engine import LEGEND_LOCS
from .textedit import ColorButton, SymbolButton, script_buttons

LINESTYLE_CHOICES = ["", "solid", "dashed", "dotted", "dashdot", "none"]
MARKER_CHOICES = ["", "none", "circle", "square", "triangle", "down", "diamond", "pentagon", "hexagon", "star",
                  "plus", "cross", "dot"]


def style_combo(choices, tip: str) -> QComboBox:
    cb = QComboBox()
    for c in choices:
        cb.addItem(c or "auto", c)
    cb.setToolTip(tip)
    return cb


def _spin(lo, hi, step, dec, special="auto", suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(dec)
    s.setSpecialValueText(special)
    s.setSuffix(suffix)
    return s


class AnnotationTable(QWidget):
    """Text labels and arrows in data coordinates (``--text`` / ``--arrow``)."""
    changed = Signal()
    COLS = ["type", "x", "y", "to x", "to y", "text", "colour"]

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.tab = QTableWidget(0, len(self.COLS))
        self.tab.setHorizontalHeaderLabels(self.COLS)
        self.tab.verticalHeader().setVisible(False)
        self.tab.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tab.horizontalHeader().setStretchLastSection(False)
        self.tab.setMinimumHeight(90)
        self.tab.setMaximumHeight(170)
        self.tab.itemChanged.connect(lambda *_: self.changed.emit())
        v.addWidget(self.tab)
        h = QHBoxLayout()
        h.setSpacing(6)
        bt = QPushButton("Text")
        bt.setToolTip("Add a text label (type its position in data units)")
        bt.clicked.connect(lambda: self.add("text"))
        ba = QPushButton("Arrow")
        ba.setToolTip("Add an arrow from (x, y) to (to x, to y); its text sits at the tail")
        ba.clicked.connect(lambda: self.add("arrow"))
        br = QPushButton("Remove")
        br.clicked.connect(self.remove)
        self._edit = None
        self.sym = SymbolButton(self._current_edit)
        self.sym.setToolTip("Insert a Greek letter or symbol into the text you clicked last")
        sup, sub = script_buttons(self._current_edit)
        h.addWidget(bt)
        h.addWidget(ba)
        h.addWidget(br)
        h.addStretch(1)
        for b in (self.sym, sup, sub):
            h.addWidget(b)
        v.addLayout(h)

    def _current_edit(self):
        return self._edit

    def add(self, kind: str, values=None):
        from PySide6.QtWidgets import QTableWidgetItem
        r = self.tab.rowCount()
        self.tab.blockSignals(True)
        self.tab.insertRow(r)
        t = QComboBox()
        t.addItems(["text", "arrow"])
        t.setCurrentText(kind)
        t.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.tab.setCellWidget(r, 0, t)
        vals = values or {}
        for c, k in enumerate(("x", "y", "x1", "y1"), 1):
            self.tab.setItem(r, c, QTableWidgetItem(str(vals.get(k, ""))))
        te = QLineEdit(str(vals.get("text", "")))
        te.setPlaceholderText("text, $\\alpha$, cm$^{-1}$ …")
        te.textChanged.connect(lambda *_: self.changed.emit())
        te.cursorPositionChanged.connect(lambda *_, e=te: setattr(self, "_edit", e))
        self.tab.setCellWidget(r, 5, te)
        if self._edit is None:
            self._edit = te
        col = ColorButton("Black")
        if vals.get("color"):
            col.set_value(vals["color"])
        col.changed.connect(lambda *_: self.changed.emit())
        self.tab.setCellWidget(r, 6, col)
        self.tab.blockSignals(False)
        self.tab.resizeColumnToContents(0)
        for c in range(1, 5):
            self.tab.setColumnWidth(c, 52)
        self.tab.setColumnWidth(5, 120)
        self.changed.emit()

    def remove(self):
        rows = sorted({i.row() for i in self.tab.selectedIndexes()} or {self.tab.rowCount() - 1}, reverse=True)
        for r in rows:
            if r >= 0:
                if self.tab.cellWidget(r, 5) is self._edit:
                    self._edit = None
                self.tab.removeRow(r)
        self.changed.emit()

    def _cell(self, r, c) -> str:
        w = self.tab.cellWidget(r, c)
        if isinstance(w, QLineEdit):
            return w.text().strip()
        it = self.tab.item(r, c)
        return it.text().strip() if it else ""

    def rows(self) -> List[dict]:
        out = []
        for r in range(self.tab.rowCount()):
            d = {"type": self.tab.cellWidget(r, 0).currentText(), "x": self._cell(r, 1), "y": self._cell(r, 2),
                 "x1": self._cell(r, 3), "y1": self._cell(r, 4), "text": self._cell(r, 5),
                 "color": self.tab.cellWidget(r, 6).value()}
            out.append(d)
        return out

    def set_rows(self, rows: List[dict]):
        self.tab.setRowCount(0)
        for d in rows or []:
            self.add(d.get("type", "text"), d)

    def argv(self) -> List[str]:
        a = []
        for d in self.rows():
            col = f"|{d['color']}" if d["color"] else ""
            try:
                if d["type"] == "text":
                    if d["x"] and d["y"] and d["text"]:
                        float(d["x"]), float(d["y"])
                        a += ["--text", f"{d['x']},{d['y']},{d['text']}{col}"]
                elif d["x"] and d["y"] and d["x1"] and d["y1"]:
                    for k in ("x", "y", "x1", "y1"):
                        float(d[k])
                    tail = f",{d['text']}{col}" if d["text"] or col else ""
                    a += ["--arrow", f"{d['x']},{d['y']},{d['x1']},{d['y1']}{tail}"]
            except ValueError:
                continue                      # incomplete row: skipped until the numbers are valid
        return a


class StyleBox(QGroupBox):
    """Legend, line and font controls plus annotations. ``argv()`` gives the matching options."""
    changed = Signal()

    def __init__(self, title: str = "Look", series_widths: bool = True, parent=None):
        super().__init__(title, parent)
        f = QFormLayout(self)
        f.setHorizontalSpacing(10)
        f.setVerticalSpacing(8)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        from PySide6.QtCore import Qt
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.legend = QComboBox()
        self.legend.addItem("automatic", "")
        for loc in LEGEND_LOCS:
            self.legend.addItem(loc, loc)
        self.legend_frame = QCheckBox("frame")
        self.legend_cols = QSpinBox()
        self.legend_cols.setRange(0, 8)
        self.legend_cols.setSpecialValueText("1 col.")
        self.legend_cols.setSuffix(" col.")
        f.addRow("Legend", _row(self.legend, self.legend_frame, self.legend_cols, stretch=0))
        self.linewidth = _spin(0, 6, 0.25, 2, suffix=" pt")
        self.markersize = _spin(0, 20, 0.5, 1, suffix=" pt")
        self.series_row = _row(QLabel("line"), self.linewidth, QLabel("marker"), self.markersize)
        f.addRow("Sizes", self.series_row)
        self._series_widths = series_widths
        self.series_row.setVisible(series_widths)
        if not series_widths:
            f.labelForField(self.series_row).setVisible(False)
        self.font = QComboBox()
        self.font.setEditable(True)
        self.font.addItem("")
        try:
            from ..plot.engine import font_names
            self.font.addItems(font_names())
        except Exception:  # noqa: BLE001
            pass
        self.font.setToolTip("Font family (empty: the journal's own font)")
        self.font.lineEdit().setPlaceholderText("journal's font")
        f.addRow("Font", self.font)
        self.font_scale = _spin(0, 3, 0.05, 2, special="×1", suffix="×")
        self.line_scale = _spin(0, 4, 0.1, 2, special="×1", suffix="×")
        f.addRow("Scale", _row(QLabel("text"), self.font_scale, QLabel("lines"), self.line_scale))
        self.grid = QCheckBox("light grid")
        f.addRow("", self.grid)
        self.notes = AnnotationTable()
        lab = QLabel("Text labels and arrows (data coordinates)")
        lab.setObjectName("Muted")
        f.addRow(lab)
        f.addRow(self.notes)
        for w in (self.legend, ):
            w.currentIndexChanged.connect(self.changed)
        self.font.currentTextChanged.connect(self.changed)
        for w in (self.legend_frame, self.grid):
            w.toggled.connect(self.changed)
        for w in (self.linewidth, self.markersize, self.font_scale, self.line_scale):
            w.valueChanged.connect(self.changed)
        self.legend_cols.valueChanged.connect(self.changed)
        self.notes.changed.connect(self.changed)

    def argv(self) -> List[str]:
        a = []
        if self.legend.currentData():
            a += ["--legend", self.legend.currentData()]
        if self.legend_frame.isChecked():
            a.append("--legend-frame")
        if self.legend_cols.value() > 1:
            a += ["--legend-cols", str(self.legend_cols.value())]
        if self._series_widths:
            if self.linewidth.value() > 0:
                a += ["--linewidth", f"{self.linewidth.value():g}"]
            if self.markersize.value() > 0:
                a += ["--markersize", f"{self.markersize.value():g}"]
        if self.font.currentText().strip():
            a += ["--font", self.font.currentText().strip()]
        if self.font_scale.value() > 0 and abs(self.font_scale.value() - 1) > 1e-9:
            a += ["--font-scale", f"{self.font_scale.value():g}"]
        if self.line_scale.value() > 0 and abs(self.line_scale.value() - 1) > 1e-9:
            a += ["--line-scale", f"{self.line_scale.value():g}"]
        if self.grid.isChecked():
            a.append("--grid")
        return a + self.notes.argv()

    # project files
    def state(self) -> dict:
        return {"legend": self.legend.currentData(), "legend_frame": self.legend_frame.isChecked(),
                "legend_cols": self.legend_cols.value(), "linewidth": self.linewidth.value(),
                "markersize": self.markersize.value(), "font": self.font.currentText(),
                "font_scale": self.font_scale.value(), "line_scale": self.line_scale.value(),
                "grid": self.grid.isChecked(), "labels": self.notes.rows()}

    def set_state(self, s: dict):
        s = s or {}
        i = self.legend.findData(s.get("legend", ""))
        self.legend.setCurrentIndex(max(i, 0))
        self.legend_frame.setChecked(bool(s.get("legend_frame")))
        self.legend_cols.setValue(int(s.get("legend_cols", 0)))
        self.linewidth.setValue(float(s.get("linewidth", 0)))
        self.markersize.setValue(float(s.get("markersize", 0)))
        self.font.setCurrentText(s.get("font", ""))
        self.font_scale.setValue(float(s.get("font_scale", 0)))
        self.line_scale.setValue(float(s.get("line_scale", 0)))
        self.grid.setChecked(bool(s.get("grid")))
        self.notes.set_rows(s.get("labels", []))


def _row(*widgets, stretch: int = -1) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    for i, x in enumerate(widgets):
        h.addWidget(x, 1 if i == stretch else 0)
    if stretch < 0:
        h.addStretch(1)
    return w
