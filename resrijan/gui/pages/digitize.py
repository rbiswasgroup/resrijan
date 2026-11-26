"""Digitize: every option of `resrijan digitize`, an interactive preview (draw the region,
click ticks for manual calibration) and a results browser (replots, overlays, data, notes)."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QSpinBox, QSplitter, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ... import cli
from ..icons import icon
from ..render import preview_pages
from ..theme import C
from ..widgets import (CommandBar, CsvTable, FormatChecks, ImagePanel, PathEdit, TemplateCombo, WidthCombo, badge,
                       primary_button, tool_button)
from ..textedit import ColorButton, MathLineEdit
from .base import Page

FIGURE_FILTER = ("Figures (*.pdf *.eps *.epsi *.epsf *.ps *.svg *.svgz *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp);;"
                 "All files (*)")
LEVEL_COL = {"error": C["red"], "warn": C["saffron"], "info": C["muted"]}


class DigitizePage(Page):
    title = "Digitize"
    subtitle = "Extract the data from a published figure, check it against the original, and redraw it in journal style."
    icon = "digitize"

    def __init__(self, win):
        super().__init__(win)
        P = win.prefs
        self.pages: list = []              # [(index, rgb, kind, scale)] preview pages
        self.cur = 0                       # position in self.pages
        self.region: Optional[tuple] = None  # fractions x0, y0, x1, y1
        self.picks = {"x": [], "y": []}    # (px, py, value) in preview pixels of self.cur
        self.result = None
        opts, work = self.split(470)

        # ── figure
        f = self.group("Figure", opts)
        self.file = PathEdit("open", FIGURE_FILTER, "PDF, EPS, SVG, PNG, JPG, TIFF …")
        self.file.changed.connect(self.open_path)
        f.addRow("File", self.file)
        self.page_list = QListWidget()
        self.page_list.setMaximumHeight(92)
        self.page_list.setToolTip("Tick the pages to digitise (none ticked = all pages). Click a page to preview it.")
        self.page_list.currentRowChanged.connect(self.show_page)
        self.page_list.itemChanged.connect(self.update_command)
        f.addRow("Pages", self.page_list)
        self.dpi = QDoubleSpinBox()
        self.dpi.setRange(72, 2400)
        self.dpi.setDecimals(0)
        self.dpi.setSingleStep(50)
        self.dpi.setSuffix(" dpi")
        self.dpi.setValue(P.get("dpi"))
        self.dpi.setToolTip("Render resolution for PDF/EPS/PS/SVG (bitmaps are used at their own resolution)")
        f.addRow("Resolution", self.dpi)
        self.prefer = QComboBox()
        self.prefer.addItems(cli.PREFER)
        self.prefer.setToolTip("auto: vector data where the file has it, otherwise pixels")
        f.addRow("Read from", self.prefer)

        # ── region & calibration
        r = self.group("Region and calibration", opts)
        self.region_edit = QLineEdit()
        self.region_edit.setPlaceholderText("whole page – or draw a box on the preview")
        self.region_edit.setToolTip("x0,y0,x1,y1 as 0–1 page fractions or pixels")
        self.region_edit.editingFinished.connect(self._region_typed)
        self.b_region = tool_button("region", "Draw the region on the preview", checkable=True)
        b_rclear = tool_button("clear", "Whole page (clear the region)")
        b_rclear.clicked.connect(lambda: self.set_region(None))
        r.addRow("Region", self.row(self.region_edit, self.b_region, b_rclear, stretch=0))
        self.region_edit.setMinimumWidth(170)
        self.xcal = QLineEdit()
        self.xcal.setPlaceholderText("automatic – or click x ticks")
        self.xcal.setToolTip("Manual x calibration 'px:value,px:value' in rendered-image pixels")
        self.ycal = QLineEdit()
        self.ycal.setPlaceholderText("automatic – or click y ticks")
        self.ycal.setToolTip("Manual y calibration 'px:value,px:value'")
        self.b_pickx = tool_button("pickx", "Click x-axis ticks on the preview and type their values", checkable=True)
        self.b_picky = tool_button("picky", "Click y-axis ticks on the preview and type their values", checkable=True)
        b_pclear = tool_button("clear", "Remove the clicked ticks")
        b_pclear.clicked.connect(self.clear_picks)
        r.addRow("x calibration", self.row(self.xcal, self.b_pickx, stretch=0))
        r.addRow("y calibration", self.row(self.ycal, self.b_picky, b_pclear, stretch=0))
        for e in (self.xcal, self.ycal):
            e.setMinimumWidth(170)
        self.scale = QLineEdit()
        self.scale.setPlaceholderText("from the scale bar – or e.g. 100=50 nm")
        self.scale.setToolTip("Micrograph scale override: pixels=value unit, e.g. '100=50 nm'")
        r.addRow("Image scale", self.scale)
        for b, tool in ((self.b_region, "region"), (self.b_pickx, "x"), (self.b_picky, "y")):
            b.toggled.connect(lambda on, t=tool: self._tool_toggled(t, on))

        # ── extraction
        x = self.group("Extraction", opts)
        self.kind = QComboBox()
        self.kind.addItems(cli.DIGITIZE_TYPES)
        self.kind.setToolTip("auto detects the figure type of each panel")
        x.addRow("Figure type", self.kind)
        self.xscale = QComboBox()
        self.xscale.addItems(cli.SCALES)
        self.yscale = QComboBox()
        self.yscale.addItems(cli.SCALES)
        x.addRow("Axis scales", self.row(QLabel("x"), self.xscale, QLabel("y"), self.yscale))
        self.max_series = QSpinBox()
        self.max_series.setRange(1, 60)
        self.max_series.setValue(P.get("max_series"))
        x.addRow("Max. series", self.max_series)
        self.particles = QCheckBox("Size the particles in micrographs")
        self.particles.setChecked(True)
        x.addRow("", self.particles)

        # ── replot
        p = self.group("Replot", opts)
        self.template = TemplateCombo()
        self.template.set_value(P.get("template"))
        p.addRow("Journal", self.template)
        self.width = WidthCombo(P.get("width"))
        p.addRow("Width", self.width)
        self.formats = FormatChecks(default=P.get("formats"))
        p.addRow("Formats", self.formats)
        self.xlabel = MathLineEdit("as read from the figure")
        self.ylabel = MathLineEdit("as read, e.g. k (s$^{-1}$)")
        p.addRow("x title", self.xlabel)
        p.addRow("y title", self.ylabel)
        self.label_color = ColorButton("As read from the figure")
        self.label_color.changed.connect(self.update_command)
        p.addRow("Title colour", self.row(self.label_color))

        # ── output
        o = self.group("Output", opts)
        self.out = PathEdit("dir", placeholder="next to the figure: <name>_resrijan")
        o.addRow("Folder", self.out)
        self.strict = QCheckBox("Strict: report the run as failed if any panel has errors")
        o.addRow("", self.strict)
        opts.addStretch(1)

        # ── work area: preview | results
        self.tabs = QTabWidget()
        prev = QWidget()
        pl = QVBoxLayout(prev)
        pl.setContentsMargins(8, 8, 8, 8)
        self.preview = ImagePanel("Open a figure (or drop it on the window) to start.")
        self.preview.view.region_drawn.connect(self._region_drawn)
        self.preview.view.picked.connect(self._picked)
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        pl.addWidget(self.preview, 1)
        pl.addWidget(self.hint)
        self.tabs.addTab(prev, icon("digitize"), "Figure")
        self.results = self._build_results()
        self.tabs.addTab(self.results, icon("report"), "Results")
        work.addWidget(self.tabs, 1)
        self.cmd = CommandBar()
        bottom = QHBoxLayout()
        bottom.addWidget(self.cmd, 1)
        self.run_btn = primary_button("Digitize", "run")
        self.run_btn.clicked.connect(self.run)
        bottom.addWidget(self.run_btn)
        work.addLayout(bottom)

        # every change updates the command line shown under the preview
        for wdg in (self.region_edit, self.xcal, self.ycal, self.scale, self.xlabel, self.ylabel):
            wdg.textChanged.connect(self.update_command)
        for cb in (self.prefer, self.kind, self.xscale, self.yscale, self.template, self.width):
            cb.currentIndexChanged.connect(self.update_command)
        self.width.editTextChanged.connect(self.update_command)
        self.dpi.valueChanged.connect(self._dpi_changed)
        self.max_series.valueChanged.connect(self.update_command)
        for cb in (self.particles, self.strict):
            cb.toggled.connect(self.update_command)
        self.formats.changed.connect(self.update_command)
        self.out.edit.textChanged.connect(self.update_command)
        self.update_command()

    # ───────────────────────── results area ─────────────────────────
    def _build_results(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        top = QHBoxLayout()
        self.summary = QHBoxLayout()
        top.addLayout(self.summary)
        top.addStretch(1)
        self.b_report = QPushButton(icon("report"), "Open report")
        self.b_report.clicked.connect(lambda: self._open(self.result and self.result[1]["report"]))
        self.b_folder = QPushButton(icon("folder"), "Open folder")
        self.b_folder.clicked.connect(lambda: self._open(self.result and self.result[2]))
        self.b_edit = QPushButton(icon("edit"), "Edit data…")
        self.b_edit.setToolTip("Correct the points of the selected panel by hand: move, add, delete, split, merge")
        self.b_edit.clicked.connect(self.edit_data)
        self.b_send = []
        for key, text, tip in (("plot", "Plot", "Replot this panel's data with your own styling"),
                               ("analyze", "Analyze", "Baseline, peaks and deconvolution of this panel's data"),
                               ("fit", "Fit", "Fit a model to this panel's data")):
            b = QPushButton(text)
            b.setToolTip(tip + " (the edited data, if you corrected them)")
            b.clicked.connect(lambda _=False, k=key: self.send_data(k))
            self.b_send.append(b)
        for b in (self.b_edit, *self.b_send, self.b_report, self.b_folder):
            b.setEnabled(False)
            top.addWidget(b)
        lay.addLayout(top)
        sp = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Panel", "Type", "Read from", "Content", "Warn.", "Err."])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.currentItemChanged.connect(self._panel_selected)
        self.notes = QListWidget()
        self.notes.setWordWrap(True)
        ll.addWidget(self.tree, 2)
        lbl = QLabel("Notes")
        lbl.setObjectName("Muted")
        ll.addWidget(lbl)
        ll.addWidget(self.notes, 3)
        self.rtabs = QTabWidget()
        self.v_replot = ImagePanel("Replot of the selected panel")
        self.v_overlay = ImagePanel("Extracted data drawn over the original")
        self.data = CsvTable()
        self.v_combined = ImagePanel("All panels in one figure")
        self.rtabs.addTab(self.v_replot, "Replot")
        self.rtabs.addTab(self.v_overlay, "Overlay")
        self.rtabs.addTab(self.data, "Data")
        self.rtabs.addTab(self.v_combined, "Combined")
        sp.addWidget(left)
        sp.addWidget(self.rtabs)
        sp.setSizes([430, 700])
        lay.addWidget(sp, 1)
        return w

    # ───────────────────────── file & preview ─────────────────────────
    def open_path(self, path: str):
        if not path:
            return
        if not Path(path).is_file():
            self.error("File not found", path)
            return
        self.file.setText(path)
        self.win.prefs.add_recent(path)
        self.out.edit.setPlaceholderText(self.win.prefs.output_dir(path))
        self.pages, self.cur = [], 0
        self.region = None
        self.region_edit.clear()
        self.clear_picks()
        self.page_list.clear()
        self.preview.view.set_image(None)
        self.preview.view.set_placeholder("Loading preview …")
        self.update_command()
        self.tabs.setCurrentIndex(0)
        dpi = self.win.prefs.get("preview_dpi")
        if not self.win.runner.run(f"Loading {Path(path).name}", lambda: preview_pages(path, dpi), self._preview_loaded,
                                   lambda m: self.preview.view.set_placeholder("Preview failed – see the log.")):
            QTimer.singleShot(400, lambda: self.open_path(path))    # another job is running: try again shortly

    def _preview_loaded(self, pages):
        self.pages = pages
        self.page_list.blockSignals(True)
        self.page_list.clear()
        for idx, rgb, kind, _ in pages:
            it = QListWidgetItem(f"Page {idx + 1}   ·   {rgb.shape[1]}×{rgb.shape[0]} px preview   ·   {kind}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.page_list.addItem(it)
        self.page_list.blockSignals(False)
        self.page_list.setVisible(True)
        if pages:
            self.page_list.setCurrentRow(0)
            self.show_page(0)
        self._update_hint()
        pend, self._pending = getattr(self, "_pending", None), None
        if pend:
            self._apply_view_state(pend)

    def show_page(self, i: int):
        if not (0 <= i < len(self.pages)):
            return
        if i != self.cur and (self.picks["x"] or self.picks["y"]):
            self.clear_picks()               # ticks belong to the page they were clicked on
        self.cur = i
        self.preview.view.set_image(self.pages[i][1])
        self._draw_overlays()

    def _factor(self) -> float:
        """Preview pixel → pixel of the image the pipeline works on (rendered at the chosen dpi)."""
        if not self.pages:
            return 1.0
        kind = self.pages[self.cur][2]
        return 1.0 if kind == "raster" else self.dpi.value() / self.win.prefs.get("preview_dpi")

    # ───────────────────────── tools ─────────────────────────
    def _tool_toggled(self, tool: str, on: bool):
        btns = {"region": self.b_region, "x": self.b_pickx, "y": self.b_picky}
        if on:
            for t, b in btns.items():
                if t != tool and b.isChecked():
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)
            self.preview.view.set_tool("region" if tool == "region" else "pick")
            self.tabs.setCurrentIndex(0)
        elif not any(b.isChecked() for b in btns.values()):
            self.preview.view.set_tool("pan")
        self._update_hint()

    def _active_tool(self) -> str:
        return "region" if self.b_region.isChecked() else "x" if self.b_pickx.isChecked() else "y" if self.b_picky.isChecked() else ""

    def _update_hint(self):
        t = self._active_tool()
        text = {"region": "Drag a rectangle around the panel to digitise.",
                "x": "Click an x-axis tick mark, then type its value. Two or more ticks are needed.",
                "y": "Click a y-axis tick mark, then type its value. Two or more ticks are needed."}.get(
            t, "Scroll to zoom, drag to pan. Use the tools on the left to draw a region or click ticks." if self.pages else "")
        if self.region and self.pages and self.pages[self.cur][2] == "vector":
            text += ("  ⚠ With a region, this vector file is read from its pixels (less exact). "
                     "Leave the region empty to read the exact vector data; all panels are found automatically.")
        self.hint.setText(text)

    def _region_drawn(self, r: QRectF):
        w, h = self.preview.view.image_size()
        self.set_region((r.left() / w, r.top() / h, r.right() / w, r.bottom() / h))
        self.b_region.setChecked(False)

    def set_region(self, frac: Optional[tuple]):
        self.region = frac
        self.region_edit.setText(",".join(f"{v:.4f}" for v in frac) if frac else "")
        self._draw_overlays()
        self._update_cal_strings()
        self._update_hint()

    def _region_typed(self):
        t = self.region_edit.text().strip()
        if not t:
            self.set_region(None)
            return
        try:
            v = [float(s) for s in t.replace(" ", "").split(",")]
            assert len(v) == 4
        except (ValueError, AssertionError):
            self.error("Region", "Give four numbers: x0,y0,x1,y1 (0–1 page fractions or pixels).")
            return
        if all(0 <= s <= 1 for s in v):
            self.region = tuple(v)
        elif self.pages:                     # pixels of the rendered image → fractions for the preview
            f = self._factor()
            w, h = self.preview.view.image_size()
            self.region = (v[0] / f / w, v[1] / f / h, v[2] / f / w, v[3] / f / h)
        self._draw_overlays()
        self._update_cal_strings()
        self._update_hint()

    def _picked(self, x: float, y: float):
        axis = self._active_tool()
        if axis not in ("x", "y"):
            return
        txt, ok = QInputDialog.getText(self, f"{axis}-axis tick", f"Value of the {axis} tick at ({x:.1f}, {y:.1f}):")
        if not ok or not txt.strip():
            return
        try:
            val = float(txt.replace("−", "-").replace(",", "."))
        except ValueError:
            self.error("Tick value", f"'{txt}' is not a number.")
            return
        self.picks[axis].append((x, y, val))
        self._draw_overlays()
        self._update_cal_strings()

    def clear_picks(self):
        self.picks = {"x": [], "y": []}
        self.xcal.clear()
        self.ycal.clear()
        self._draw_overlays()

    def _update_cal_strings(self):
        """Clicked ticks → --xcal/--ycal in the pixels the pipeline uses: rendered at the chosen
        dpi and measured from the corner of the region (when one is set)."""
        if not self.pages:
            return
        f = self._factor()
        w, h = self.preview.view.image_size()
        ox = oy = 0.0
        if self.region:
            ox, oy = round(self.region[0] * w * f), round(self.region[1] * h * f)
        if self.picks["x"]:
            self.xcal.setText(cli.calibration_string([(px * f - ox, v) for px, _, v in self.picks["x"]]))
        if self.picks["y"]:
            self.ycal.setText(cli.calibration_string([(py * f - oy, v) for _, py, v in self.picks["y"]]))

    def _dpi_changed(self):
        self._update_cal_strings()
        self.update_command()

    def _draw_overlays(self):
        v = self.preview.view
        v.clear_overlays(keep_region=False)
        if not v.has_image():
            return
        w, h = v.image_size()
        if self.region:
            x0, y0, x1, y1 = self.region
            v.show_region(QRectF(x0 * w, y0 * h, (x1 - x0) * w, (y1 - y0) * h))
        for axis, col in (("x", C["saffron"]), ("y", C["accent2"])):
            for px, py, val in self.picks[axis]:
                v.add_mark(px, py, f"{axis} = {val:g}", col)

    # ───────────────────────── command & run ─────────────────────────
    def argv(self) -> List[str]:
        path = self.file.text()
        out = self.out.text() or (self.win.prefs.output_dir(path) if path else "")
        a = ["digitize", path or "FILE", "-o", out or "OUT"]
        pages = [str(self.pages[i][0] + 1) for i in range(self.page_list.count())
                 if self.page_list.item(i).checkState() == Qt.Checked and i < len(self.pages)]
        if pages:
            a += ["--page", ",".join(pages)]
        if self.region_edit.text().strip():
            a += ["--region", self.region_edit.text().strip()]
        if self.dpi.value() != 600:
            a += ["--dpi", f"{self.dpi.value():g}"]
        for flag, w, default in (("--type", self.kind, "auto"), ("--xscale", self.xscale, "auto"),
                                 ("--yscale", self.yscale, "auto"), ("--prefer", self.prefer, "auto")):
            if w.currentText() != default:
                a += [flag, w.currentText()]
        for flag, e in (("--xcal", self.xcal), ("--ycal", self.ycal), ("--scale", self.scale)):
            if e.text().strip():
                a += [flag, e.text().strip()]
        if self.max_series.value() != 12:
            a += ["--max-series", str(self.max_series.value())]
        if not self.particles.isChecked():
            a.append("--no-particles")
        if self.template.value() and self.template.value() != "natchem":
            a += ["-t", self.template.value()]
        if self.width.value() != "single":
            a += ["--width", self.width.value()]
        if self.formats.value() != "pdf,svg,png":
            a += ["-f", self.formats.value()]
        if self.label_color.value():
            a += ["--label-color", self.label_color.value()]
        for flag, e in (("--xlabel", self.xlabel), ("--ylabel", self.ylabel)):
            if e.text().strip():
                a += [flag, e.text().strip()]
        a.append("-v")
        if self.strict.isChecked():
            a.append("--strict")
        return a

    def update_command(self, *_):
        self.cmd.set_argv(self.argv())

    def run(self):
        path = self.file.text()
        if not path or not Path(path).is_file():
            self.error("Digitize", "Choose a figure file first.")
            return
        if not self.formats.value():
            self.error("Digitize", "Tick at least one replot format.")
            return
        argv = self.argv()
        try:
            a = self.parse(argv)
        except SystemExit:
            self.error("Digitize", "These options are not valid:\n\n" + self.command_text(argv))
            return

        def job():
            print(self.command_text(argv))
            panels, res, out = cli.run_digitize(a)
            for p in panels:                  # the same console output as the command line
                print(cli.panel_summary(p))
                for n in p.notes:
                    print(f"      [{n['level']}] {n['msg']}")
            print(f"\nReport: {res['report']}")
            return panels, res, out

        self.run_btn.setEnabled(False)
        if not self.win.runner.run(f"Digitizing {Path(path).name}", job, self._done, lambda m: self._failed(m)):
            self.run_btn.setEnabled(True)
            self.info("Busy", "Another task is still running; try again when it has finished.")

    def _failed(self, msg: str):
        self.run_btn.setEnabled(True)
        self.error("Digitize failed", msg)

    def _done(self, result):
        self.run_btn.setEnabled(True)
        self.result = result
        panels, res, out = result
        self.tree.clear()
        n_err = n_warn = 0
        for i, p in enumerate(panels):
            e = sum(n["level"] == "error" for n in p.notes)
            w = sum(n["level"] == "warn" for n in p.notes)
            n_err, n_warn = n_err + e, n_warn + w
            it = QTreeWidgetItem([p.id, p.kind, p.mode, cli.panel_what(p), str(w), str(e)])
            it.setData(0, Qt.UserRole, i)
            if e:
                it.setForeground(5, QBrush(QColor(C["red"])))
            if w:
                it.setForeground(4, QBrush(QColor(C["saffron"])))
            self.tree.addTopLevelItem(it)
        for c in range(6):
            self.tree.resizeColumnToContents(c)
        while self.summary.count():
            it = self.summary.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.summary.addWidget(badge(f"{len(panels)} panel{'s' if len(panels) != 1 else ''}", "info"))
        self.summary.addWidget(badge(f"{n_warn} warning{'s' if n_warn != 1 else ''}", "warn" if n_warn else "ok"))
        self.summary.addWidget(badge(f"{n_err} error{'s' if n_err != 1 else ''}", "error" if n_err else "ok"))
        for b in (self.b_report, self.b_folder):
            b.setEnabled(True)
        comb = self._best_image(res.get("combined") or [])
        self.v_combined.view.set_image(comb)
        self.rtabs.setTabEnabled(3, bool(comb))
        if panels:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.tabs.setCurrentIndex(1)
        self.win.status(f"Digitized {Path(self.file.text()).name}: {len(panels)} panel(s), {n_warn} warning(s), {n_err} error(s).")
        if self.strict.isChecked() and n_err:
            self.error("Strict mode", f"{n_err} error(s) in the extraction – see the notes.")
        if self.win.prefs.get("open_report"):
            self._open(res["report"])

    @staticmethod
    def _best_image(files) -> Optional[str]:
        files = [files] if isinstance(files, str) else list(files or [])
        for ext in (".png", ".pdf", ".svg", ".tiff", ".eps"):
            for f in files:
                if f.lower().endswith(ext) and Path(f).exists() and ext != ".eps":
                    return f
        return None

    def _panel_selected(self, item, _prev=None):
        if item is None or not self.result:
            return
        p = self.result[0][item.data(0, Qt.UserRole)]
        self.notes.clear()
        for n in p.notes:
            it = QListWidgetItem(f"[{n['level']}] {n['msg']}")
            it.setForeground(QBrush(QColor(LEVEL_COL.get(n["level"], C["text"]))))
            self.notes.addItem(it)
        rp = self._best_image(p.files.get("replot") or [])
        self.v_replot.view.set_image(rp)
        if not rp:
            self.v_replot.view.set_placeholder("No replot for this panel (see the notes).")
        self.v_overlay.view.set_image(p.files.get("overlay"))
        data = p.files.get("edited") or p.files.get("data") or p.files.get("contours") or p.files.get("annotations")
        self.data.load(data)
        self.b_edit.setEnabled(bool(p.series) and bool(p.files.get("data")))
        for b in self.b_send:
            b.setEnabled(bool(p.series) and bool(p.files.get("data")))
        if p.files.get("replot_edited"):
            self.v_replot.view.set_image(self._best_image(p.files["replot_edited"]))

    def current_panel(self):
        it = self.tree.currentItem()
        return None if it is None or not self.result else self.result[0][it.data(0, Qt.UserRole)]

    def send_data(self, key: str):
        """Open the selected panel's data (edited version first) on the Plot, Analyze or Fit page."""
        p = self.current_panel()
        if p is None:
            return
        path = p.files.get("edited") or p.files.get("data")
        if path:
            self.win.open_in(key, path)

    def edit_data(self):
        from ...pipeline import panel_spec
        from ..editor import DataEditor, EditData, edited_path, panel_background
        p = self.current_panel()
        if p is None or not p.files.get("data"):
            return
        src = p.files["data"]
        prev = edited_path(src)
        data = EditData.from_csv(prev if Path(prev).exists() else src)
        try:
            spec = panel_spec(p)
        except Exception:  # noqa: BLE001
            spec = None
        dlg = DataEditor(src, data=data, background=panel_background(p), spec=spec,
                         template=self.template.value() or "natchem",
                         formats=[f for f in self.formats.value().split(",") if f], title=p.id, parent=self)

        def saved(out):
            p.files["edited"] = out
            rp = Path(out[:-4].replace("_data_edited", "_replot_edited"))
            files = [str(rp.with_suffix("." + f)) for f in self.formats.value().split(",") if f]
            p.files["replot_edited"] = [f for f in files if Path(f).exists()]
            self._panel_selected(self.tree.currentItem())
            self.win.status(f"Saved edited data: {Path(out).name}")
        dlg.saved.connect(saved)
        self.editor = dlg
        dlg.show()

    # ───────────────────────── project files ─────────────────────────
    def state(self) -> dict:
        checked = [i for i in range(self.page_list.count()) if self.page_list.item(i).checkState() == Qt.Checked]
        return {"file": self.file.text(), "pages_checked": checked, "current": self.cur, "dpi": self.dpi.value(),
                "prefer": self.prefer.currentText(), "region": list(self.region) if self.region else None,
                "region_text": self.region_edit.text(), "picks": {k: [list(t) for t in v] for k, v in self.picks.items()},
                "xcal": self.xcal.text(), "ycal": self.ycal.text(), "scale": self.scale.text(),
                "type": self.kind.currentText(), "xscale": self.xscale.currentText(),
                "yscale": self.yscale.currentText(), "max_series": self.max_series.value(),
                "particles": self.particles.isChecked(), "template": self.template.value(),
                "width": self.width.value(), "formats": self.formats.value(), "xlabel": self.xlabel.text(),
                "ylabel": self.ylabel.text(), "label_color": self.label_color.value(), "out": self.out.text(),
                "strict": self.strict.isChecked()}

    def set_state(self, s: dict):
        from ..project import set_combo
        self.dpi.setValue(float(s.get("dpi", self.dpi.value())))
        set_combo(self.prefer, s.get("prefer"))
        set_combo(self.kind, s.get("type"))
        set_combo(self.xscale, s.get("xscale"))
        set_combo(self.yscale, s.get("yscale"))
        self.max_series.setValue(int(s.get("max_series", 12)))
        self.particles.setChecked(bool(s.get("particles", True)))
        if s.get("template"):
            self.template.set_value(s["template"])
        if s.get("width"):
            self.width.setCurrentText(s["width"])
        if s.get("formats"):
            self.formats.set_value(s["formats"])
        self.xlabel.setText(s.get("xlabel", ""))
        self.ylabel.setText(s.get("ylabel", ""))
        self.label_color.set_value(s.get("label_color", ""))
        self.out.setText(s.get("out", ""))
        self.strict.setChecked(bool(s.get("strict")))
        self.scale.setText(s.get("scale", ""))
        f = s.get("file", "")
        if f and Path(f).is_file():
            self._pending = s
            self.open_path(f)            # region, ticks and pages are restored once the preview is loaded
        else:
            self.xcal.setText(s.get("xcal", ""))
            self.ycal.setText(s.get("ycal", ""))
            if f:
                raise FileNotFoundError(f"figure not found: {f}")
        self.update_command()

    def _apply_view_state(self, s: dict):
        for i in s.get("pages_checked", []):
            if i < self.page_list.count():
                self.page_list.item(i).setCheckState(Qt.Checked)
        cur = int(s.get("current", 0))
        if 0 <= cur < len(self.pages):
            self.page_list.setCurrentRow(cur)
            self.show_page(cur)
        self.picks = {k: [tuple(t) for t in v] for k, v in (s.get("picks") or {"x": [], "y": []}).items()}
        self.picks.setdefault("x", [])
        self.picks.setdefault("y", [])
        self.region = tuple(s["region"]) if s.get("region") else None
        self.region_edit.setText(s.get("region_text", ""))
        self.xcal.setText(s.get("xcal", ""))
        self.ycal.setText(s.get("ycal", ""))
        self._draw_overlays()
        self._update_hint()
        self.update_command()

    @staticmethod
    def _open(path):
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))
