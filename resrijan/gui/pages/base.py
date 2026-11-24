"""Common page layout: title + subtitle, an options column (scrollable) and a work area."""
from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QSplitter,
                               QVBoxLayout, QWidget)

if TYPE_CHECKING:  # pragma: no cover
    from ..mainwindow import MainWindow


class Page(QWidget):
    title = ""
    subtitle = ""
    icon = "open"

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 14)
        outer.setSpacing(10)
        head = QVBoxLayout()
        head.setSpacing(2)
        t = QLabel(self.title)
        t.setObjectName("PageTitle")
        s = QLabel(self.subtitle)
        s.setObjectName("PageSubtitle")
        s.setWordWrap(True)
        head.addWidget(t)
        head.addWidget(s)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body, 1)

    # layout helpers
    def split(self, left_width: int = 470):
        """Options column (scrollable) | work area. Returns (options_layout, work_layout)."""
        sp = QSplitter(Qt.Horizontal)
        sp.setChildrenCollapsible(False)
        opts = QWidget()
        ol = QVBoxLayout(opts)
        ol.setContentsMargins(0, 0, 8, 0)
        ol.setSpacing(4)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(opts)
        sc.setMinimumWidth(360)
        work = QWidget()
        wl = QVBoxLayout(work)
        wl.setContentsMargins(8, 0, 0, 0)
        wl.setSpacing(8)
        sp.addWidget(sc)
        sp.addWidget(work)
        sp.setStretchFactor(1, 1)
        sp.setSizes([left_width, 900])
        self.body.addWidget(sp, 1)
        self.options_scroll = sc
        return ol, wl

    @staticmethod
    def group(title: str, layout_parent: QVBoxLayout) -> QFormLayout:
        g = QGroupBox(title)
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        f.setHorizontalSpacing(10)
        f.setVerticalSpacing(8)
        f.setRowWrapPolicy(QFormLayout.WrapLongRows)
        layout_parent.addWidget(g)
        return f

    @staticmethod
    def row(*widgets, stretch: int = -1) -> QWidget:
        """Widgets side by side; ``stretch`` is the index of the one that takes the free space
        (-1: none, the row is left-aligned)."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        for i, x in enumerate(widgets):
            h.addWidget(x, 1 if i == stretch else 0)
        if stretch < 0:
            h.addStretch(1)
        return w

    # running commands through the real CLI parser
    def parse(self, argv: Sequence[str]):
        from ...cli import build_parser
        return build_parser().parse_args(list(argv))

    def error(self, title: str, msg: str):
        QMessageBox.critical(self, title, msg[:3000])

    def info(self, title: str, msg: str):
        QMessageBox.information(self, title, msg)

    def command_text(self, argv: Sequence[str]) -> str:
        return "resrijan " + " ".join(shlex.quote(a) for a in argv)

    def open_path(self, path: str):  # pragma: no cover – overridden by pages that accept files
        pass
