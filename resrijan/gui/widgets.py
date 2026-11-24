"""Reusable widgets: zoomable image view with region and tick picking, file pickers,
format/template/width selectors, tables, the command bar and the log."""
from __future__ import annotations

import csv
import shlex
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGraphicsEllipseItem, QGraphicsItem,
                               QGraphicsLineItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

from .icons import icon
from .theme import C


# ───────────────────────────── images ─────────────────────────────
def np_to_qimage(a: np.ndarray) -> QImage:
    a = np.ascontiguousarray(a)
    if a.ndim == 2:
        a = np.ascontiguousarray(np.dstack([a] * 3))
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)
    if a.shape[2] == 4:
        a = np.ascontiguousarray(a[:, :, :3])
    h, w = a.shape[:2]
    return QImage(a.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def file_to_qimage(path: str, dpi: float = 110) -> Optional[QImage]:
    """Any picture ReSrijan writes: PNG/JPG/TIFF directly, PDF/SVG/EPS rendered (first page)."""
    p = Path(path)
    if not p.exists():
        return None
    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"):
        im = QImage(str(p))
        return None if im.isNull() else im
    try:
        if p.suffix.lower() in (".tif", ".tiff"):
            from PIL import Image
            return np_to_qimage(np.asarray(Image.open(p).convert("RGB")))
        import pymupdf
        doc = pymupdf.open(str(p))
        pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
        return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
    except Exception:  # noqa: BLE001
        return None


class ImageView(QGraphicsView):
    """Zoom (wheel), pan (drag), and two tools: ``region`` (drag a rectangle) and ``pick``
    (click points). Coordinates are image pixels."""
    hovered = Signal(float, float)
    region_drawn = Signal(QRectF)
    picked = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setMouseTracking(True)
        self.setMinimumSize(240, 200)
        self._pix: Optional[QGraphicsPixmapItem] = None
        self._autofit = True                 # keep fitting on resize until the user zooms
        self._tool = "pan"
        self._drag_start: Optional[QPointF] = None
        self._rubber: Optional[QGraphicsRectItem] = None
        self._region_item: Optional[QGraphicsRectItem] = None
        self._marks: List[QGraphicsItem] = []
        self._placeholder = QGraphicsSimpleTextItem("")
        self._placeholder.setBrush(QBrush(QColor(C["muted"])))
        f = QFont()
        f.setPointSize(13)
        self._placeholder.setFont(f)
        self.scene().addItem(self._placeholder)

    # content
    def set_placeholder(self, text: str):
        self._placeholder.setText(text)
        self._placeholder.setVisible(self._pix is None)

    def set_image(self, img, fit: bool = True):
        if isinstance(img, np.ndarray):
            img = np_to_qimage(img)
        elif isinstance(img, (str, Path)):
            img = file_to_qimage(str(img))
        self.clear_overlays(keep_region=False)
        if self._pix is not None:
            self.scene().removeItem(self._pix)
            self._pix = None
        if img is None or img.isNull():
            self._placeholder.setVisible(True)
            return
        self._placeholder.setVisible(False)
        self._pix = self.scene().addPixmap(QPixmap.fromImage(img))
        self._pix.setTransformationMode(Qt.SmoothTransformation)
        self._pix.setZValue(0)
        self.scene().setSceneRect(self._pix.boundingRect())
        if fit:
            self._autofit = True
            self.fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._autofit:
            self.fit()

    def showEvent(self, e):
        super().showEvent(e)
        if self._autofit:
            self.fit()

    def image_size(self):
        if self._pix is None:
            return 0, 0
        r = self._pix.boundingRect()
        return r.width(), r.height()

    def has_image(self) -> bool:
        return self._pix is not None

    def fit(self):
        if self._pix is not None:
            self.fitInView(self._pix, Qt.KeepAspectRatio)

    def fit_and_follow(self):
        self._autofit = True
        self.fit()

    def zoom(self, f: float):
        self._autofit = False
        self.scale(f, f)

    # tools
    def set_tool(self, tool: str):
        self._tool = tool
        self.setDragMode(QGraphicsView.ScrollHandDrag if tool == "pan" else QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.CrossCursor if tool in ("region", "pick") else Qt.OpenHandCursor)

    def wheelEvent(self, e):
        if self._pix is None:
            return
        self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)

    def _clamp(self, p: QPointF) -> QPointF:
        w, h = self.image_size()
        return QPointF(min(max(p.x(), 0.0), w), min(max(p.y(), 0.0), h))

    def mousePressEvent(self, e):
        if self._pix is not None and e.button() == Qt.LeftButton and self._tool in ("region", "pick"):
            p = self._clamp(self.mapToScene(e.position().toPoint()))
            if self._tool == "pick":
                self.picked.emit(p.x(), p.y())
                return
            self._drag_start = p
            self._rubber = self.scene().addRect(QRectF(p, p), QPen(QColor(C["accent2"]), 0, Qt.DashLine),
                                                QBrush(QColor(25, 195, 177, 40)))
            self._rubber.setZValue(5)
            return
        if self._pix is not None and e.button() == Qt.LeftButton:
            self._autofit = False            # the user is panning
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        p = self.mapToScene(e.position().toPoint())
        if self._pix is not None:
            self.hovered.emit(p.x(), p.y())
        if self._rubber is not None and self._drag_start is not None:
            self._rubber.setRect(QRectF(self._drag_start, self._clamp(p)).normalized())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._rubber is not None:
            r = self._rubber.rect()
            self.scene().removeItem(self._rubber)
            self._rubber, self._drag_start = None, None
            if r.width() > 3 and r.height() > 3:
                self.show_region(r)
                self.region_drawn.emit(r)
            return
        super().mouseReleaseEvent(e)

    # overlays
    def show_region(self, r: Optional[QRectF]):
        if self._region_item is not None:
            self.scene().removeItem(self._region_item)
            self._region_item = None
        if r is not None and self._pix is not None:
            pen = QPen(QColor(C["accent2"]), 2)
            pen.setCosmetic(True)
            self._region_item = self.scene().addRect(r, pen, QBrush(QColor(25, 195, 177, 30)))
            self._region_item.setZValue(4)

    def add_mark(self, x: float, y: float, text: str, color: str):
        pen = QPen(QColor(color), 2)
        pen.setCosmetic(True)
        s = max(4.0, 0.012 * max(self.image_size()))
        items = [QGraphicsLineItem(x - s, y, x + s, y), QGraphicsLineItem(x, y - s, x, y + s),
                 QGraphicsEllipseItem(x - s / 2, y - s / 2, s, s)]
        for it in items:
            it.setPen(pen)
        t = QGraphicsSimpleTextItem(text)
        t.setBrush(QBrush(QColor(color)))
        f = QFont()
        f.setPointSizeF(10)
        f.setBold(True)
        t.setFont(f)
        t.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        t.setPos(x + s, y - 2 * s)
        items.append(t)
        for it in items:
            it.setZValue(6)
            self.scene().addItem(it)
        self._marks.extend(items)

    def clear_overlays(self, keep_region: bool = True):
        for it in self._marks:
            self.scene().removeItem(it)
        self._marks = []
        if not keep_region:
            self.show_region(None)


class ImagePanel(QWidget):
    """ImageView with a small toolbar (fit, zoom) and a pixel read-out."""

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.view = ImageView()
        self.view.set_placeholder(placeholder)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        self.toolbar = bar
        for name, tip, fn in (("fit", "Fit to window", self.view.fit_and_follow),
                              ("zoomin", "Zoom in", lambda: self.view.zoom(1.25)),
                              ("zoomout", "Zoom out", lambda: self.view.zoom(0.8))):
            b = QToolButton()
            b.setIcon(icon(name))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        self.coords = QLabel("")
        self.coords.setObjectName("Muted")
        bar.addWidget(self.coords)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)
        self.view.hovered.connect(lambda x, y: self.coords.setText(f"x {x:,.1f}  y {y:,.1f} px"))

    def add_tool_button(self, btn: QWidget, index: int = 3):
        self.toolbar.insertWidget(index, btn)


# ───────────────────────────── inputs ─────────────────────────────
class PathEdit(QWidget):
    """Line edit + browse button. ``mode``: open | save | dir."""
    changed = Signal(str)

    def __init__(self, mode: str = "open", filt: str = "", placeholder: str = "", parent=None):
        super().__init__(parent)
        self.mode, self.filt = mode, filt
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.editingFinished.connect(lambda: self.changed.emit(self.text()))
        b = QToolButton()
        b.setIcon(icon("folder"))
        b.setToolTip("Browse…")
        b.clicked.connect(self.browse)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.edit, 1)
        lay.addWidget(b)

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, t: str, emit: bool = False):
        self.edit.setText(t or "")
        if emit:
            self.changed.emit(self.text())

    def browse(self):
        start = self.text() or str(Path.home())
        if self.mode == "dir":
            p = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        elif self.mode == "save":
            p, _ = QFileDialog.getSaveFileName(self, "Save as", start, self.filt)
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Open", start, self.filt)
        if p:
            self.setText(p, emit=True)


class FormatChecks(QWidget):
    changed = Signal()

    def __init__(self, formats: Sequence[str] = ("pdf", "svg", "eps", "png", "tiff"), default: str = "pdf,svg,png",
                 parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.boxes = {}
        for f in formats:
            cb = QCheckBox(f.upper())
            cb.toggled.connect(self.changed)
            lay.addWidget(cb)
            self.boxes[f] = cb
        lay.addStretch(1)
        self.set_value(default)

    def value(self) -> str:
        return ",".join(f for f, cb in self.boxes.items() if cb.isChecked())

    def set_value(self, v: str):
        want = {s.strip().lower() for s in (v or "").split(",")}
        for f, cb in self.boxes.items():
            cb.setChecked(f in want)


class TemplateCombo(QComboBox):
    """Journal templates (built-in and imported) plus "Other file…" for a template YAML."""
    OTHER = "Other template file…"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumContentsLength(18)
        self.activated.connect(self._maybe_browse)
        self.refresh()

    def refresh(self, select: Optional[str] = None):
        from ..plot import templates as T
        cur = select or self.value()
        self.blockSignals(True)
        self.clear()
        for t in T.available():
            self.addItem(f"{t.key} — {t.name}", t.key)
        self.addItem(self.OTHER, None)
        self.blockSignals(False)
        if cur:
            self.set_value(cur)

    def value(self) -> str:
        d = self.currentData()
        return d or ""

    def set_value(self, v: str):
        i = self.findData(v)
        if i < 0 and v and Path(v).is_file():
            self.insertItem(self.count() - 1, f"{Path(v).name} (file)", v)
            i = self.findData(v)
        if i >= 0:
            self.setCurrentIndex(i)

    def _maybe_browse(self, i: int):
        if self.itemData(i) is None:
            p, _ = QFileDialog.getOpenFileName(self, "Template file", str(Path.home()), "Template (*.yaml *.yml)")
            if p:
                self.set_value(p)
            else:
                self.setCurrentIndex(0)


class WidthCombo(QComboBox):
    """single | onehalf | double, or a width in mm."""

    def __init__(self, default: str = "single", parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.addItems(["single", "onehalf", "double"])
        self.setCurrentText(default)
        self.setToolTip("Column width of the replot: single, onehalf, double, or a width in mm (e.g. 120)")

    def value(self) -> str:
        return self.currentText().strip() or "single"


# ───────────────────────────── output ─────────────────────────────
class CsvTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)

    def load(self, path: Optional[str], max_rows: int = 5000):
        self.clear()
        self.setRowCount(0)
        self.setColumnCount(0)
        if not path or not Path(path).exists():
            return
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            return
        head, body = rows[0], rows[1:max_rows + 1]
        self.setColumnCount(len(head))
        self.setHorizontalHeaderLabels(head)
        self.setRowCount(len(body))
        for r, row in enumerate(body):
            for c, v in enumerate(row):
                self.setItem(r, c, QTableWidgetItem(v))
        self.resizeColumnsToContents()


class CommandBar(QFrame):
    """Shows the exact `resrijan …` command the GUI runs; copyable for scripts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.label = QLabel()
        self.label.setObjectName("Muted")
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setWordWrap(True)
        f = QFont("DejaVu Sans Mono")
        f.setPointSizeF(9.5)
        self.label.setFont(f)
        b = QToolButton()
        b.setIcon(icon("copy"))
        b.setToolTip("Copy the command")
        b.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text))
        t = QLabel()
        t.setPixmap(icon("terminal", C["accent"]).pixmap(18, 18))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 6, 6)
        lay.addWidget(t)
        lay.addWidget(self.label, 1)
        lay.addWidget(b)
        self.text = ""

    def set_argv(self, argv: Sequence[str]):
        from .._platform import WINDOWS
        if WINDOWS:                    # quoting for cmd.exe / PowerShell
            import subprocess
            self.text = "resrijan " + subprocess.list2cmdline(list(argv))
        else:
            self.text = "resrijan " + " ".join(shlex.quote(a) for a in argv)
        self.label.setText(self.text)


class LogView(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Code")
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)

    def add(self, text: str):
        self.appendPlainText(text)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


def badge(text: str, kind: str = "info") -> QLabel:
    col = {"ok": C["green"], "warn": C["saffron"], "error": C["red"], "info": C["accent"]}[kind]
    lb = QLabel(text)
    lb.setObjectName("Badge")
    lb.setStyleSheet(f"background: {col}22; color: {col}; border: 1px solid {col}66;")
    lb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return lb


def primary_button(text: str, icon_name: Optional[str] = None) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("Primary")
    if icon_name:
        b.setIcon(icon(icon_name, "#04201d"))
    b.setCursor(Qt.PointingHandCursor)
    return b


def tool_button(icon_name: str, tip: str, checkable: bool = False, text: str = "") -> QToolButton:
    b = QToolButton()
    b.setIcon(icon(icon_name))
    b.setToolTip(tip)
    b.setCheckable(checkable)
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    return b
