"""Text with science in it: a title field with Greek letters and symbols, superscript and
subscript buttons and a live preview (matplotlib mathtext), and a colour button."""
from __future__ import annotations

import io
from typing import Callable, Optional, Union

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QColorDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit,
                               QToolButton, QVBoxLayout, QWidget, QWidgetAction)

from .theme import C

# (label shown on the button, text inserted). Rarer symbols are inserted as mathtext so they
# render in every journal font; common ones as Unicode characters.
GREEK = [(c, c) for c in "αβγδεζηθικλμνξπρστυφχψω"] + [("ϵ", "ϵ"), ("ϑ", "ϑ"), ("ϕ", "ϕ")]
GREEK_CAP = [(c, c) for c in "ΓΔΘΛΞΠΣΥΦΨΩ"]
MATHS = [("±", "±"), ("∓", r"$\mp$"), ("×", "×"), ("·", "·"), ("÷", "÷"), ("−", "−"), ("≈", "≈"), ("≃", r"$\simeq$"),
         ("≠", "≠"), ("≡", "≡"), ("≤", "≤"), ("≥", "≥"), ("≪", r"$\ll$"), ("≫", r"$\gg$"), ("∝", r"$\propto$"),
         ("∞", "∞"), ("√", "√"), ("∂", "∂"), ("∇", r"$\nabla$"), ("∫", "∫"), ("∑", "∑"), ("∏", "∏"),
         ("⟨", r"$\langle$"), ("⟩", r"$\rangle$"), ("‖", r"$\Vert$"), ("⊥", r"$\perp$"), ("∥", r"$\parallel$"),
         ("∈", r"$\in$"), ("Δ", "Δ"), ("′", "′"), ("″", "″")]
UNITS = [("°", "°"), ("°C", "°C"), ("Å", "Å"), ("µ", "µ"), ("Ω", "Ω"), ("ℏ", r"$\hbar$"), ("‰", "‰"), ("%", "%"),
         ("→", "→"), ("←", "←"), ("↔", "↔"), ("⇌", r"$\rightleftharpoons$"), ("↑", "↑"), ("↓", "↓"),
         ("cm⁻¹", "cm$^{-1}$"), ("s⁻¹", "s$^{-1}$"), ("M⁻¹", "M$^{-1}$"), ("mol⁻¹", "mol$^{-1}$"),
         ("H₂O", "H$_{2}$O"), ("D₂O", "D$_{2}$O")]
SECTIONS = [("Greek", GREEK), ("Greek capitals", GREEK_CAP), ("Mathematics", MATHS), ("Units, arrows, formulae", UNITS)]

# colour-blind-safe Okabe–Ito palette + neutrals (suggested in the colour menu)
PRESETS = [("Black", "#000000"), ("Orange", "#E69F00"), ("Sky blue", "#56B4E9"), ("Bluish green", "#009E73"),
           ("Yellow", "#F0E442"), ("Blue", "#0072B2"), ("Vermilion", "#D55E00"), ("Reddish purple", "#CC79A7"),
           ("Grey", "#7F7F7F"), ("Navy", "#1F3A93"), ("Dark red", "#8B0000")]

Target = Union[QLineEdit, QPlainTextEdit]


def insert_text(w: Target, text: str):
    if isinstance(w, QLineEdit):
        w.insert(text)
    else:
        w.textCursor().insertText(text)
    w.setFocus()


def wrap_script(w: Target, kind: str):
    """Selected text → superscript ``$^{…}$`` or subscript ``$_{…}$``; with nothing selected, insert
    an empty one and put the cursor between the braces."""
    mark = "^" if kind == "sup" else "_"
    if isinstance(w, QLineEdit):
        sel = w.selectedText()
        if sel:
            w.insert(f"${mark}{{{sel}}}$")
        else:
            pos = w.cursorPosition()
            t = w.text()
            w.setText(t[:pos] + f"${mark}{{}}$" + t[pos:])
            w.setCursorPosition(pos + 3)
    else:
        cur = w.textCursor()
        sel = cur.selectedText()
        if sel:
            cur.insertText(f"${mark}{{{sel}}}$")
        else:
            cur.insertText(f"${mark}{{}}$")
            cur.movePosition(cur.MoveOperation.Left, cur.MoveMode.MoveAnchor, 2)
            w.setTextCursor(cur)
    w.setFocus()


class SymbolButton(QToolButton):
    """Ω button: a palette of Greek letters and symbols, inserted into ``target()`` at the cursor."""

    def __init__(self, target: Callable[[], Target], parent=None):
        super().__init__(parent)
        self.target = target
        self.setText("Ω")
        self.setToolTip("Insert a Greek letter or symbol")
        self.setPopupMode(QToolButton.InstantPopup)
        f = self.font()
        f.setPointSizeF(f.pointSizeF() + 1)
        self.setFont(f)
        menu = QMenu(self)
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)
        sym_font = QFont()
        sym_font.setPointSizeF(12)
        for title, items in SECTIONS:
            h = QLabel(title)
            h.setObjectName("Muted")
            lay.addWidget(h)
            grid = QGridLayout()
            grid.setSpacing(2)
            for i, (label, ins) in enumerate(items):
                b = QToolButton()
                b.setText(label)
                b.setFont(sym_font)
                b.setMinimumSize(34 if len(label) <= 2 else 54, 30)
                b.setToolTip(ins)
                b.clicked.connect(lambda _=False, t=ins: (insert_text(self.target(), t), menu.close()))
                grid.addWidget(b, i // 10, i % 10)
            lay.addLayout(grid)
        act = QWidgetAction(menu)
        act.setDefaultWidget(panel)
        menu.addAction(act)
        self.setMenu(menu)


def script_buttons(target: Callable[[], Target]):
    sup = QToolButton()
    sup.setText("x²")
    sup.setToolTip("Superscript: the selected text (or a new one) becomes $^{…}$")
    sup.clicked.connect(lambda: wrap_script(target(), "sup"))
    sub = QToolButton()
    sub.setText("x₂")
    sub.setToolTip("Subscript: the selected text (or a new one) becomes $_{…}$")
    sub.clicked.connect(lambda: wrap_script(target(), "sub"))
    return sup, sub


def render_label(text: str, color: str = "#e6ebf5", size: float = 11.0, dpi: float = 110) -> QImage:
    """The text as matplotlib draws it (mathtext); raises ValueError if it cannot be drawn."""
    from matplotlib.figure import Figure
    fig = Figure(figsize=(0.1, 0.1), dpi=dpi)
    fig.patch.set_alpha(0)
    fig.text(0, 0, text, fontsize=size, color=color, family="DejaVu Sans")
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, transparent=True, bbox_inches="tight", pad_inches=0.02)
    except Exception as exc:  # noqa: BLE001 – mathtext parse errors come in several types
        raise ValueError(str(exc).splitlines()[0] if str(exc) else type(exc).__name__) from None
    return QImage.fromData(buf.getvalue())


class MathLineEdit(QWidget):
    """A one-line title field with Ω (symbols), x² / x₂ and a live preview. Behaves like a
    QLineEdit for the pages (text, setText, textChanged, setPlaceholderText)."""
    textChanged = Signal(str)

    def __init__(self, placeholder: str = "", preview: bool = True, parent=None):
        super().__init__(parent)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(self.textChanged)
        sym = SymbolButton(lambda: self.edit)
        sup, sub = script_buttons(lambda: self.edit)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        row.addWidget(self.edit, 1)
        for b in (sym, sup, sub):
            row.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addLayout(row)
        self.preview = QLabel()
        self.preview.setMinimumHeight(0)
        self.preview.setVisible(False)
        lay.addWidget(self.preview)
        self._show_preview = preview
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._render)
        self.edit.textChanged.connect(lambda _: self._timer.start())

    # QLineEdit-like API
    def text(self) -> str:
        return self.edit.text()

    def setText(self, t: str):
        self.edit.setText(t or "")
        self._render()

    def clear(self):
        self.edit.clear()

    def setPlaceholderText(self, t: str):
        self.edit.setPlaceholderText(t)

    def setToolTip(self, t: str):
        self.edit.setToolTip(t)

    def _render(self):
        t = self.edit.text().strip()
        if not self._show_preview or not t or "$" not in t and not any(ord(ch) > 127 for ch in t):
            self.preview.setVisible(False)     # plain text needs no preview
            return
        self.preview.setVisible(True)
        if t.count("$") % 2:
            self._error("unmatched $ – formulas are written between two $ signs")
            return
        try:
            img = render_label(t)
        except ValueError as exc:
            self._error(str(exc))
            return
        self.preview.setStyleSheet("")
        self.preview.setToolTip("How the title will look (preview font; the replot uses the journal's font)")
        self.preview.setPixmap(QPixmap.fromImage(img))

    def _error(self, msg: str):
        self.preview.setPixmap(QPixmap())
        self.preview.setText(f"⚠ {msg}")
        self.preview.setStyleSheet(f"color: {C['saffron']}; font-size: 11px;")

    def is_valid(self) -> bool:
        t = self.edit.text().strip()
        if not t:
            return True
        if t.count("$") % 2:
            return False
        try:
            render_label(t)
            return True
        except ValueError:
            return False


def color_icon(color: Optional[str], size: int = 18) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if color:
        p.setBrush(QColor(color))
        p.setPen(QColor(C["border"]))
        p.drawRoundedRect(1, 1, size - 2, size - 2, 4, 4)
    else:                                  # automatic: a split swatch of palette colours
        p.setPen(QColor(C["border"]))
        for i, c in enumerate(("#0072B2", "#D55E00", "#009E73", "#CC79A7")):
            p.setBrush(QColor(c))
            p.drawRect(1 + i * (size - 2) / 4, 1, (size - 2) / 4, size - 2)
    p.end()
    return QIcon(pm)


class ColorButton(QToolButton):
    """Colour swatch: click to choose a colour; the arrow menu has suggested colours and
    "Automatic" (the journal template's palette). ``value()`` is '' for automatic."""
    changed = Signal(str)

    def __init__(self, auto_text: str = "Automatic (journal palette)", parent=None):
        super().__init__(parent)
        self._color = ""
        self.auto_text = auto_text
        self.setPopupMode(QToolButton.MenuButtonPopup)
        self.clicked.connect(self.choose)
        m = QMenu(self)
        m.addAction(color_icon(None), auto_text, lambda: self.set_value("", emit=True))
        m.addSeparator()
        for name, hexc in PRESETS:
            m.addAction(color_icon(hexc), name, lambda h=hexc: self.set_value(h, emit=True))
        m.addSeparator()
        m.addAction("Other colour…", self.choose)
        self.setMenu(m)
        self._refresh()

    def value(self) -> str:
        return self._color

    def set_value(self, c: str, emit: bool = False):
        self._color = (c or "").strip()
        self._refresh()
        if emit:
            self.changed.emit(self._color)

    def choose(self):
        c = QColorDialog.getColor(QColor(self._color or "#0072B2"), self, "Choose a colour")
        if c.isValid():
            self.set_value(c.name(), emit=True)

    def _refresh(self):
        self.setIcon(color_icon(self._color or None))
        self.setToolTip(self._color or self.auto_text)
