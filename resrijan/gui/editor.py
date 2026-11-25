"""Data editor: correct digitised points by hand.

Opened from the Digitize results (the original figure is shown behind the points) or for any data
table. Points can be dragged, added, deleted (one by one or in a box) and typed in a table; series
can be split, merged, renamed and deleted. Every change can be undone.

Saving writes ``<name>_edited.csv`` (same long format as ``*_data.csv``), ``<name>_edits.json``
(what was changed, and the background used) and – from Digitize – a replot that keeps the
panel's style.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

PALETTE = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#FFFFFF"]
TOL_PX = 9


# ───────────────────────────── data model ─────────────────────────────
@dataclass
class Series:
    name: str
    x: np.ndarray
    y: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    kind: str = "line"
    source: str = "edited"

    def take(self, idx) -> "Series":
        return Series(self.name, self.x[idx], self.y[idx], self.lo[idx], self.hi[idx], self.kind, self.source)


@dataclass
class EditData:
    series: List[Series] = field(default_factory=list)
    log: List[str] = field(default_factory=list)

    # file I/O ------------------------------------------------------------
    @classmethod
    def from_csv(cls, path: str) -> "EditData":
        from ..plot.engine import read_table
        tab = read_table(path)
        out = cls()
        if "series" in tab and "x" in tab and "y" in tab:
            names = list(dict.fromkeys(str(v) for v in tab["series"]))
            for n in names:
                m = np.array([str(v) == n for v in tab["series"]])
                lo = tab["yerr_minus"][m].astype(float) if "yerr_minus" in tab else np.full(m.sum(), np.nan)
                hi = tab["yerr_plus"][m].astype(float) if "yerr_plus" in tab else np.full(m.sum(), np.nan)
                kind = str(tab["kind"][m][0]) if "kind" in tab else "line"
                src = str(tab["source"][m][0]) if "source" in tab else "edited"
                out.series.append(Series(n, tab["x"][m].astype(float), tab["y"][m].astype(float), lo, hi,
                                         kind if kind in ("line", "markers") else "line", src))
        else:
            keys = [k for k in tab if tab[k].dtype != object]
            if len(keys) < 2:
                raise ValueError(f"{Path(path).name}: needs an x column and at least one y column")
            x = tab[keys[0]].astype(float)
            for k in keys[1:]:
                n = len(x)
                out.series.append(Series(k, x.copy(), tab[k].astype(float), np.full(n, np.nan), np.full(n, np.nan)))
        return out

    def to_csv(self, path: str):
        rows = ["series,x,y,yerr_minus,yerr_plus,kind,source"]
        for s in self.series:
            name = f'"{s.name}"' if ("," in s.name or '"' in s.name) else s.name
            for i in range(len(s.x)):
                rows.append(f"{name},{s.x[i]:.10g},{s.y[i]:.10g},{s.lo[i]:.6g},{s.hi[i]:.6g},{s.kind},{s.source}")
        Path(path).write_text("\n".join(rows) + "\n")

    # operations (each returns a short description for the log) -------------
    def names(self) -> List[str]:
        return [s.name for s in self.series]

    def move_point(self, si: int, i: int, x: float, y: float) -> str:
        s = self.series[si]
        s.x[i], s.y[i] = x, y
        return f"moved point {i + 1} of '{s.name}' to ({x:.6g}, {y:.6g})"

    def add_point(self, si: int, x: float, y: float) -> str:
        s = self.series[si]
        if s.kind == "line" and len(s.x) > 1 and np.all(np.diff(s.x) >= 0):
            i = int(np.searchsorted(s.x, x))
        elif s.kind == "line" and len(s.x) > 1 and np.all(np.diff(s.x) <= 0):
            i = len(s.x) - int(np.searchsorted(s.x[::-1], x))
        else:
            i = len(s.x)
        s.x, s.y = np.insert(s.x, i, x), np.insert(s.y, i, y)
        s.lo, s.hi = np.insert(s.lo, i, np.nan), np.insert(s.hi, i, np.nan)
        return f"added a point to '{s.name}' at ({x:.6g}, {y:.6g})"

    def delete_points(self, si: int, idx) -> str:
        s = self.series[si]
        idx = sorted(set(int(i) for i in idx))
        keep = np.setdiff1d(np.arange(len(s.x)), idx)
        self.series[si] = s.take(keep)
        return f"deleted {len(idx)} point(s) from '{s.name}'"

    def split(self, si: int, idx, name: str) -> str:
        s = self.series[si]
        idx = np.array(sorted(set(int(i) for i in idx)))
        if not len(idx):
            raise ValueError("select the points that should form the new series")
        new = s.take(idx)
        new.name = name
        self.series[si] = s.take(np.setdiff1d(np.arange(len(s.x)), idx))
        self.series.insert(si + 1, new)
        return f"moved {len(idx)} point(s) of '{s.name}' to a new series '{name}'"

    def merge(self, keep: int, other: int) -> str:
        a, b = self.series[keep], self.series[other]
        x, y = np.concatenate([a.x, b.x]), np.concatenate([a.y, b.y])
        lo, hi = np.concatenate([a.lo, b.lo]), np.concatenate([a.hi, b.hi])
        if a.kind == "line":
            o = np.argsort(x, kind="stable")
            x, y, lo, hi = x[o], y[o], lo[o], hi[o]
        self.series[keep] = Series(a.name, x, y, lo, hi, a.kind, a.source)
        del self.series[other]
        return f"merged '{b.name}' into '{a.name}'"

    def rename(self, si: int, name: str) -> str:
        old = self.series[si].name
        self.series[si].name = name
        return f"renamed '{old}' to '{name}'"

    def delete_series(self, si: int) -> str:
        s = self.series.pop(si)
        return f"deleted series '{s.name}' ({len(s.x)} points)"


def panel_background(p) -> Optional[dict]:
    """The plot area of a digitised panel as an image placed in data coordinates."""
    b = getattr(p, "box", None)
    if b is None or b.xcal is None or b.ycal is None or getattr(p, "page", None) is None:
        return None
    rgb = p.page.rgb
    x0, y0, x1, y1 = (int(round(v)) for v in (b.x0, b.y0, b.x1, b.y1))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(rgb.shape[1], x1), min(rgb.shape[0], y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return {"rgb": rgb[y0:y1, x0:x1].copy(),
            "extent": [float(b.xcal.to_data(x0)), float(b.xcal.to_data(x1)),
                       float(b.ycal.to_data(y1)), float(b.ycal.to_data(y0))],
            "xscale": b.xcal.scale, "yscale": b.ycal.scale}


def apply_to_spec(spec: dict, data: EditData) -> dict:
    """The panel's replot spec with the edited points (series styles kept by name)."""
    spec = copy.deepcopy(spec)
    old = {s.get("label"): s for s in spec.get("series", [])}
    new = []
    for k, s in enumerate(data.series):
        d = dict(old.get(s.name) or {"label": s.name, "kind": s.kind})
        d.update({"x": s.x, "y": s.y, "label": s.name})
        if np.isfinite(s.lo).any() or np.isfinite(s.hi).any():
            d["yerr_lo"], d["yerr_hi"] = s.lo, s.hi
        else:
            d.pop("yerr_lo", None)
            d.pop("yerr_hi", None)
        new.append(d)
    spec["series"] = new
    spec.pop("data", None)
    return spec


def edited_path(path: str) -> str:
    p = Path(path)
    stem = p.stem[:-7] if p.stem.endswith("_edited") else p.stem
    stem = stem[:-5] if stem.endswith("_data") else stem
    return str(p.with_name(stem + "_data_edited.csv"))


# ───────────────────────────── dialog ─────────────────────────────
class DataEditor(QDialog):
    saved = Signal(str)          # path of the edited CSV

    MODES = (("move", "Move", "Drag a point to move it"),
             ("add", "Add", "Click to add a point to the active series"),
             ("delete", "Delete", "Click a point to delete it, or drag a box to delete all points inside"),
             ("select", "Select", "Drag a box to select points of the active series (then split or delete)"))

    def __init__(self, path: Optional[str] = None, data: Optional[EditData] = None, background: Optional[dict] = None,
                 spec: Optional[dict] = None, template: str = "natchem", formats=("pdf", "svg", "png"),
                 title: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit data" + (f" – {title}" if title else ""))
        self.resize(1300, 820)
        self.path = path
        self.data = data or (EditData.from_csv(path) if path else EditData())
        self.background = background
        if background is None and path:
            self.background = _load_background(edited_path(path))
        self.spec = spec
        self.template, self.formats = template, list(formats)
        self.active = 0
        self.selected: List[int] = []
        self._undo: List[EditData] = []
        self._redo: List[EditData] = []
        self._drag = None
        self._box = None
        self.out_path = None
        self._build()
        self.redraw(full=True)

    # ── layout ──
    def _build(self):
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        for i, (key, text, tip) in enumerate(self.MODES):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setProperty("mode", key)
            self.mode_group.addButton(b, i)
            bar.addWidget(b)
        self.mode_group.button(0).setChecked(True)
        self.mode_group.idClicked.connect(lambda _: self._clear_tool())
        bar.addSpacing(12)
        self.b_undo = QPushButton("Undo")
        self.b_redo = QPushButton("Redo")
        self.b_undo.clicked.connect(self.undo)
        self.b_redo.clicked.connect(self.redo)
        bar.addWidget(self.b_undo)
        bar.addWidget(self.b_redo)
        bar.addSpacing(12)
        self.bg = QCheckBox("Original figure behind")
        self.bg.setChecked(self.background is not None)
        self.bg.setEnabled(self.background is not None)
        self.bg.toggled.connect(lambda: self.redraw(full=True))
        bar.addWidget(self.bg)
        bar.addStretch(1)
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        bar.addWidget(self.hint)
        root.addLayout(bar)

        sp = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(8, 6), dpi=100, facecolor="#0f1320")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.ax = self.fig.add_subplot(111)
        self.toolbar = NavigationToolbar2QT(self.canvas, left)
        ll.addWidget(self.toolbar)
        ll.addWidget(self.canvas, 1)
        sp.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        rl.addWidget(_muted("Series (click to make active)"))
        self.slist = QListWidget()
        self.slist.currentRowChanged.connect(self._series_clicked)
        rl.addWidget(self.slist, 2)
        g = QHBoxLayout()
        for text, fn, tip in (("Rename", self.rename, "Rename the active series"),
                              ("Split", self.split, "Move the selected points to a new series"),
                              ("Merge…", self.merge, "Merge another series into the active one"),
                              ("Delete", self.delete_series, "Delete the active series")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            g.addWidget(b)
        rl.addLayout(g)
        rl.addWidget(_muted("Points of the active series (type to correct a value)"))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["x", "y"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._cell_edited)
        self.table.itemSelectionChanged.connect(self._table_selected)
        rl.addWidget(self.table, 5)
        h = QHBoxLayout()
        self.b_delsel = QPushButton("Delete selected")
        self.b_delsel.clicked.connect(self.delete_selected)
        h.addWidget(self.b_delsel)
        h.addStretch(1)
        rl.addLayout(h)
        sp.addWidget(right)
        sp.setSizes([900, 380])
        root.addWidget(sp, 1)

        bottom = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        bottom.addWidget(self.status, 1)
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        self.b_save = QPushButton("Save edited data")
        self.b_save.setObjectName("Primary")
        self.b_save.clicked.connect(self.save)
        bottom.addWidget(cancel)
        bottom.addWidget(self.b_save)
        root.addLayout(bottom)

        self.canvas.mpl_connect("button_press_event", self._press)
        self.canvas.mpl_connect("motion_notify_event", self._motion)
        self.canvas.mpl_connect("button_release_event", self._release)
        QShortcut(QKeySequence.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.Redo, self, activated=self.redo)
        QShortcut(QKeySequence.Delete, self, activated=self.delete_selected)
        QShortcut(QKeySequence("Backspace"), self, activated=self.delete_selected)

    def mode(self) -> str:
        b = self.mode_group.checkedButton()
        return b.property("mode") if b else "move"

    def set_mode(self, key: str):
        for b in self.mode_group.buttons():
            b.setChecked(b.property("mode") == key)

    def _clear_tool(self):
        if self.toolbar.mode:            # leave matplotlib's zoom/pan so clicks reach the editor
            if "zoom" in str(self.toolbar.mode):
                self.toolbar.zoom()
            else:
                self.toolbar.pan()
        self.hint.setText(dict((k, t) for k, _, t in self.MODES)[self.mode()])

    # ── drawing ──
    def redraw(self, full: bool = False):
        ax = self.ax
        xl, yl = (ax.get_xlim(), ax.get_ylim()) if not full and ax.has_data() else (None, None)
        ax.clear()
        ax.set_facecolor("#ffffff")
        for sp in ax.spines.values():
            sp.set_color("#8a96b0")
        ax.tick_params(colors="#c8d0e0", labelsize=8)
        bg = self.background if (self.background is not None and self.bg.isChecked()) else None
        if bg is not None:
            if bg.get("xscale") == "log":
                ax.set_xscale("log")
            if bg.get("yscale") == "log":
                ax.set_yscale("log")
            ax.imshow(bg["rgb"], extent=bg["extent"], aspect="auto", alpha=0.55, zorder=0, interpolation="bilinear")
        for k, s in enumerate(self.data.series):
            c = PALETTE[k % (len(PALETTE) - 1)]
            act = k == self.active
            if s.kind == "line" and len(s.x) > 1:
                ax.plot(s.x, s.y, "-", color=c, lw=1.2 if act else 0.8, alpha=1 if act else 0.6, zorder=2)
            ax.plot(s.x, s.y, "o", ms=5 if act else 3, mfc=c if act else "none", mec="k" if act else c,
                    mew=0.6, alpha=1 if act else 0.7, zorder=3, label=s.name)
            if act and self.selected:
                sel = [i for i in self.selected if i < len(s.x)]
                ax.plot(s.x[sel], s.y[sel], "s", ms=9, mfc="none", mec="#D00000", mew=1.3, zorder=4)
        if self.data.series:
            leg = ax.legend(fontsize=7, loc="best", framealpha=0.8)
            leg.set_zorder(5)
        if bg is not None and full:
            ax.set_xlim(bg["extent"][0], bg["extent"][1])
            ax.set_ylim(bg["extent"][2], bg["extent"][3])
        elif xl is not None:
            ax.set_xlim(xl)
            ax.set_ylim(yl)
        self.fig.tight_layout(pad=0.6)
        self.canvas.draw_idle()
        self._fill_lists()

    def _fill_lists(self):
        self.slist.blockSignals(True)
        self.slist.clear()
        for k, s in enumerate(self.data.series):
            it = QListWidgetItem(f"{s.name}   ({len(s.x)} {'points' if s.kind == 'markers' else 'pts, line'})")
            self.slist.addItem(it)
        if self.data.series:
            self.active = min(self.active, len(self.data.series) - 1)
            self.slist.setCurrentRow(self.active)
        self.slist.blockSignals(False)
        self.table.blockSignals(True)
        s = self.cur()
        self.table.setRowCount(0 if s is None else len(s.x))
        if s is not None:
            for i in range(len(s.x)):
                self.table.setItem(i, 0, QTableWidgetItem(f"{s.x[i]:.8g}"))
                self.table.setItem(i, 1, QTableWidgetItem(f"{s.y[i]:.8g}"))
        self.table.blockSignals(False)
        self.b_undo.setEnabled(bool(self._undo))
        self.b_redo.setEnabled(bool(self._redo))
        n = sum(len(s.x) for s in self.data.series)
        self.status.setText(f"{len(self.data.series)} series, {n} points"
                            + (f" · {len(self.data.log)} change(s)" if self.data.log else ""))

    def cur(self) -> Optional[Series]:
        return self.data.series[self.active] if 0 <= self.active < len(self.data.series) else None

    # ── undo ──
    def _do(self, fn, *args):
        snap = copy.deepcopy(self.data)
        msg = fn(*args)
        self._undo.append(snap)
        self._redo.clear()
        self.data.log.append(msg)
        self.selected = []
        self.redraw()
        return msg

    def undo(self):
        if self._undo:
            self._redo.append(copy.deepcopy(self.data))
            self.data = self._undo.pop()
            self.selected = []
            self.redraw()

    def redo(self):
        if self._redo:
            self._undo.append(copy.deepcopy(self.data))
            self.data = self._redo.pop()
            self.selected = []
            self.redraw()

    # ── mouse ──
    def _nearest(self, ev, only_active: bool = False):
        best = (None, None, TOL_PX)
        T = self.ax.transData
        for k, s in enumerate(self.data.series):
            if only_active and k != self.active or not len(s.x):
                continue
            with np.errstate(all="ignore"):
                pts = T.transform(np.column_stack([s.x, s.y]))
            d = np.hypot(pts[:, 0] - ev.x, pts[:, 1] - ev.y)
            d[~np.isfinite(d)] = np.inf
            i = int(np.argmin(d))
            if d[i] < best[2]:
                best = (k, i, d[i])
        return best[0], best[1]

    def _press(self, ev):
        if ev.inaxes is not self.ax or ev.button != 1 or self.toolbar.mode:
            return
        m = self.mode()
        if m == "move":
            k, i = self._nearest(ev)
            if k is not None:
                if k != self.active:
                    self.active = k
                    self.redraw()
                self._drag = (k, i, copy.deepcopy(self.data))
        elif m == "add":
            if self.cur() is None:
                self.data.series.append(Series("series 1", np.array([]), np.array([]), np.array([]), np.array([])))
                self.active = 0
            self._do(self.data.add_point, self.active, float(ev.xdata), float(ev.ydata))
        elif m in ("delete", "select"):
            if m == "delete":
                k, i = self._nearest(ev)
                if k is not None:
                    self.active = k
                    self._do(self.data.delete_points, k, [i])
                    return
            self._box = (ev.xdata, ev.ydata, None)

    def _motion(self, ev):
        if ev.inaxes is not self.ax:
            return
        if self._drag is not None and ev.xdata is not None:
            k, i, _ = self._drag
            s = self.data.series[k]
            s.x[i], s.y[i] = ev.xdata, ev.ydata
            self.redraw()
        elif self._box is not None and ev.xdata is not None:
            x0, y0, patch = self._box
            if patch is not None:
                patch.remove()
            from matplotlib.patches import Rectangle
            patch = Rectangle((min(x0, ev.xdata), min(y0, ev.ydata)), abs(ev.xdata - x0), abs(ev.ydata - y0),
                              fill=True, fc=(0.85, 0.1, 0.1, 0.12), ec="#D00000", lw=0.8, ls="--", zorder=6)
            self.ax.add_patch(patch)
            self._box = (x0, y0, patch)
            self.canvas.draw_idle()

    def _release(self, ev):
        if self._drag is not None:
            k, i, before = self._drag
            self._drag = None
            s = self.data.series[k]
            moved = (s.x[i], s.y[i]) != (before.series[k].x[i], before.series[k].y[i])
            if moved:
                self._undo.append(before)
                self._redo.clear()
                self.data.log.append(f"moved point {i + 1} of '{s.name}' to ({s.x[i]:.6g}, {s.y[i]:.6g})")
            self.redraw()
        elif self._box is not None:
            x0, y0, patch = self._box
            self._box = None
            if patch is not None:
                patch.remove()
            if ev.xdata is None or patch is None:
                self.redraw()
                return
            idx = self.points_in(min(x0, ev.xdata), max(x0, ev.xdata), min(y0, ev.ydata), max(y0, ev.ydata))
            if self.mode() == "delete" and idx:
                self._do(self.data.delete_points, self.active, idx)
            else:
                self.select(idx)

    def points_in(self, xa, xb, ya, yb) -> List[int]:
        s = self.cur()
        if s is None:
            return []
        m = (s.x >= xa) & (s.x <= xb) & (s.y >= ya) & (s.y <= yb)
        return [int(i) for i in np.flatnonzero(m)]

    def select(self, idx: List[int]):
        self.selected = list(idx)
        self.redraw()
        self.table.blockSignals(True)
        self.table.clearSelection()
        for i in self.selected:
            self.table.selectRow(i)
        self.table.blockSignals(False)
        self.hint.setText(f"{len(self.selected)} point(s) selected – Split or Delete selected")

    # ── series and table actions ──
    def _series_clicked(self, row: int):
        if row >= 0 and row != self.active:
            self.active = row
            self.selected = []
            self.redraw()

    def _table_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if rows != self.selected:
            self.selected = rows
            self.redraw()
            self.table.blockSignals(True)
            for i in rows:
                self.table.selectRow(i)
            self.table.blockSignals(False)

    def _cell_edited(self, item):
        s = self.cur()
        try:
            v = float(item.text())
        except ValueError:
            self._fill_lists()
            return
        i = item.row()
        x, y = (v, s.y[i]) if item.column() == 0 else (s.x[i], v)
        self._do(self.data.move_point, self.active, i, x, y)

    def delete_selected(self):
        if self.selected and self.cur() is not None:
            self._do(self.data.delete_points, self.active, self.selected)

    def rename(self):
        s = self.cur()
        if s is None:
            return
        name, ok = QInputDialog.getText(self, "Rename series", "New name:", text=s.name)
        if ok and name.strip() and name.strip() != s.name:
            self._do(self.data.rename, self.active, name.strip())

    def split(self, name: Optional[str] = None):
        if not self.selected:
            QMessageBox.information(self, "Split", "Select points first (Select tool, or rows in the table).")
            return
        if not name:
            name, ok = QInputDialog.getText(self, "Split series", "Name of the new series:",
                                            text=f"{self.cur().name} (2)")
            if not ok or not name.strip():
                return
        self._do(self.data.split, self.active, self.selected, name.strip())

    def merge(self, other: Optional[str] = None):
        names = [n for k, n in enumerate(self.data.names()) if k != self.active]
        if not names:
            return
        if other is None:
            other, ok = QInputDialog.getItem(self, "Merge series", f"Merge into '{self.cur().name}':", names, 0, False)
            if not ok:
                return
        j = self.data.names().index(other)
        keep = self.active
        self._do(self.data.merge, keep, j)
        self.active = keep - (1 if j < keep else 0)
        self.redraw()

    def delete_series(self):
        if self.cur() is None:
            return
        self._do(self.data.delete_series, self.active)
        self.active = max(0, self.active - 1)
        self.redraw()

    # ── saving ──
    def save(self) -> Optional[str]:
        base = self.path or str(Path.home() / "edited_data.csv")
        out = edited_path(base)
        self.data.to_csv(out)
        log = {"source": self.path, "edited": out, "changes": self.data.log}
        if self.background is not None:
            png = out[:-4] + "_background.png"
            from PIL import Image
            Image.fromarray(self.background["rgb"]).save(png)
            log["background"] = {"file": Path(png).name, "extent": self.background["extent"],
                                 "xscale": self.background.get("xscale", "linear"),
                                 "yscale": self.background.get("yscale", "linear")}
        Path(out[:-4] + "_edits.json").write_text(json.dumps(log, indent=1))
        files = [out]
        if self.spec is not None:
            try:
                import matplotlib.pyplot as plt
                from ..plot.engine import figure, save
                fig, _, _ = figure([apply_to_spec(self.spec, self.data)], template=self.template, width="single",
                                   labels=False)
                files += save(fig, out[:-4].replace("_data_edited", "_replot_edited"), self.formats)
                plt.close(fig)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Replot", f"The data were saved, but the replot failed:\n{exc}")
        self.out_path = out
        self.status.setText("Saved " + ", ".join(Path(f).name for f in files))
        self.saved.emit(out)
        return out


def _load_background(edited_csv: str) -> Optional[dict]:
    """Background saved with an earlier edit of the same data (kept for reopening)."""
    j = Path(edited_csv[:-4] + "_edits.json")
    if not j.exists():
        return None
    try:
        b = json.loads(j.read_text()).get("background")
        if not b:
            return None
        from PIL import Image
        rgb = np.asarray(Image.open(j.with_name(b["file"])).convert("RGB"))
        return {"rgb": rgb, "extent": b["extent"], "xscale": b.get("xscale", "linear"),
                "yscale": b.get("yscale", "linear")}
    except Exception:  # noqa: BLE001
        return None


def _muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("Muted")
    return lab


__all__ = ["DataEditor", "EditData", "Series", "apply_to_spec", "edited_path", "panel_background"]
