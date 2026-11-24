"""Inspect: pages, vector content, embedded images and pixel-ruler images (`resrijan inspect`)."""
from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QPushButton, QSpinBox, QSplitter, QTreeWidget,
                               QTreeWidgetItem)

from ... import cli
from ..icons import icon
from ..widgets import CommandBar, ImagePanel, PathEdit, primary_button
from .base import Page
from .digitize import FIGURE_FILTER


class InspectPage(Page):
    title = "Inspect"
    subtitle = ("What a file contains: pages, vector drawing, text, embedded images and their resolution, "
                "plus a pixel ruler for reading coordinates by eye.")
    icon = "inspect"

    def __init__(self, win):
        super().__init__(win)
        self.results = []
        opts, work = self.split(380)
        g = self.group("File", opts)
        self.file = PathEdit("open", FIGURE_FILTER, "PDF, EPS, SVG, PNG …")
        self.file.changed.connect(self.update_command)
        g.addRow("File", self.file)
        self.page = QSpinBox()
        self.page.setRange(0, 9999)
        self.page.setSpecialValueText("all pages")
        g.addRow("Page", self.page)
        self.dpi = QDoubleSpinBox()
        self.dpi.setRange(72, 2400)
        self.dpi.setDecimals(0)
        self.dpi.setSingleStep(50)
        self.dpi.setSuffix(" dpi")
        self.dpi.setValue(600)
        g.addRow("Resolution", self.dpi)
        self.out = PathEdit("save", "Ruler image base name (*)", "next to the file: <name>_pN_ruler.png")
        g.addRow("Ruler images", self.out)
        to_dig = QPushButton(icon("digitize"), "Open in Digitize")
        to_dig.clicked.connect(lambda: self.file.text() and self.win.open_in("digitize", self.file.text()))
        opts.addWidget(to_dig)
        opts.addStretch(1)

        sp = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Property", "Value"])
        self.tree.currentItemChanged.connect(self._selected)
        self.view = ImagePanel("Pixel ruler of the page")
        sp.addWidget(self.tree)
        sp.addWidget(self.view)
        sp.setSizes([360, 700])
        work.addWidget(sp, 1)
        bottom = QHBoxLayout()
        self.cmd = CommandBar()
        bottom.addWidget(self.cmd, 1)
        self.run_btn = primary_button("Inspect", "inspect")
        self.run_btn.clicked.connect(self.run)
        bottom.addWidget(self.run_btn)
        work.addLayout(bottom)
        for w in (self.page, self.dpi):
            w.valueChanged.connect(self.update_command)
        self.out.edit.textChanged.connect(self.update_command)
        self.update_command()

    def open_path(self, path: str):
        self.file.setText(path)
        self.update_command()
        self.run()

    def argv(self) -> List[str]:
        path = self.file.text()
        a = ["inspect", path or "FILE"]
        if self.page.value():
            a += ["--page", str(self.page.value())]
        if self.dpi.value() != 600:
            a += ["--dpi", f"{self.dpi.value():g}"]
        out = self.out.text() or (str(Path(path).with_suffix("")) if path else "")
        if out:
            a += ["-o", out]
        return a

    def update_command(self, *_):
        self.cmd.set_argv(self.argv())

    def run(self):
        if not self.file.text() or not Path(self.file.text()).is_file():
            self.error("Inspect", "Choose a file first.")
            return
        argv = self.argv()
        a = self.parse(argv)

        def job():
            import json
            print(self.command_text(argv))
            res = cli.run_inspect(a)
            for info, out in res:
                print(json.dumps(info))
                print("pixel ruler:", out)
            return res

        self.win.runner.run("Inspecting", job, self._done, lambda m: self.error("Inspect failed", m))

    def _done(self, results):
        self.results = results
        self.tree.clear()
        first = None
        for k, (info, ruler) in enumerate(results):
            top = QTreeWidgetItem([f"Page {info['page']}", info["kind"]])
            top.setData(0, 256, k)
            for key, val in info.items():
                if key in ("page", "kind"):
                    continue
                if key == "embedded_images":
                    sub = QTreeWidgetItem([f"embedded images ({len(val)})", ""])
                    for j, im in enumerate(val):
                        sub.addChild(QTreeWidgetItem([f"image {j + 1}", f"{im['size'][0]}×{im['size'][1]} px, "
                                                      f"{im['dpi']} dpi, at {im['rect_pt']} pt"]))
                    top.addChild(sub)
                else:
                    shown = f"{val[0]} × {val[1]} px" if key == "size_px" else (f"{val:.4g}" if isinstance(val, float) else str(val))
                    top.addChild(QTreeWidgetItem([key.replace("_", " "), shown]))
            top.addChild(QTreeWidgetItem(["pixel ruler", ruler]))
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
            first = first or top
        self.tree.resizeColumnToContents(0)
        if first is not None:
            self.tree.setCurrentItem(first)
        self.win.status(f"Inspected {Path(self.file.text()).name}: {len(results)} page(s).")

    def _selected(self, item, _prev=None):
        while item is not None and item.parent() is not None:
            item = item.parent()
        if item is None:
            return
        k = item.data(0, 256)
        if k is not None and 0 <= k < len(self.results):
            self.view.view.set_image(self.results[k][1])
