"""Analyze: every option of `resrijan analyze` with a live preview of the fit and a peak table.
Peaks can be placed by clicking the preview."""
from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QToolButton)

from ... import cli
from ..icons import icon
from ..render import analysis_preview
from ..textedit import MathLineEdit
from ..widgets import CommandBar, FormatChecks, ImagePanel, PathEdit, TemplateCombo, WidthCombo, primary_button
from .base import Page

DATA_FILTER = "Data (*.csv *.tsv *.txt *.dat);;All files (*)"
UNITS = ["", "nm", "um", "cm-1", "eV", "THz"]


def _spin(lo, hi, val, dec=0, step=1.0, special="", suffix=""):
    s = QDoubleSpinBox() if dec else QSpinBox()
    s.setRange(lo, hi)
    if dec:
        s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    if special:
        s.setSpecialValueText(special)
    if suffix:
        s.setSuffix(suffix)
    return s


class AnalyzePage(Page):
    title = "Analyze"
    subtitle = "Baseline, smoothing, normalisation, unit conversion, peak fitting with errors and areas."
    icon = "analyze"

    def __init__(self, win):
        super().__init__(win)
        P = win.prefs
        self.series_names: List[str] = []
        self._map = None
        opts, work = self.split(470)

        d = self.group("Data", opts)
        self.data = PathEdit("open", DATA_FILTER, "a table, e.g. a digitised *_data.csv")
        self.data.changed.connect(self.open_path)
        d.addRow("File", self.data)
        self.series = QComboBox()
        self.series.setToolTip("The series to analyse (Save analyses all series when 'all' is chosen)")
        d.addRow("Series", self.series)

        u = self.group("Units and range", opts)
        self.u_from, self.u_to = QComboBox(), QComboBox()
        for cb in (self.u_from, self.u_to):
            for x in UNITS:
                cb.addItem(x or "–", x)
        self.jacobian = QCheckBox("scale intensities (spectral density)")
        self.jacobian.setToolTip("When converting wavelength ↔ energy, multiply by |dλ/dE| so areas are kept")
        u.addRow("Convert x", self.row(QLabel("from"), self.u_from, QLabel("to"), self.u_to))
        u.addRow("", self.jacobian)
        self.crop_lo, self.crop_hi = QLineEdit(), QLineEdit()
        self.crop_lo.setPlaceholderText("from")
        self.crop_hi.setPlaceholderText("to")
        u.addRow("Keep x", self.row(self.crop_lo, QLabel("–"), self.crop_hi, stretch=0))

        p = self.group("Processing", opts)
        self.smooth = QComboBox()
        for t, v in (("none", ""), ("Savitzky–Golay", "savgol"), ("moving average", "mean")):
            self.smooth.addItem(t, v)
        self.sm_win = _spin(3, 501, 11, suffix=" points")
        self.sm_win.setSingleStep(2)
        self.sm_ord = _spin(1, 6, 3)
        self.sm_ord.setPrefix("order ")
        p.addRow("Smooth", self.row(self.smooth, self.sm_win, self.sm_ord))
        self.base = QComboBox()
        for t, v in (("none", ""), ("asymmetric least squares", "als"), ("polynomial", "poly"),
                     ("line through the ends", "ends")):
            self.base.addItem(t, v)
        self.b_lam = QLineEdit("1e5")
        self.b_lam.setToolTip("ALS stiffness λ: larger = smoother baseline (1e3–1e9)")
        self.b_p = QLineEdit("0.01")
        self.b_p.setToolTip("ALS asymmetry p: smaller = the baseline stays further under the peaks (0.001–0.1)")
        self.b_ord = _spin(0, 8, 2)
        self.b_ord.setPrefix("order ")
        p.addRow("Baseline", self.base)
        self.b_row = self.row(QLabel("λ"), self.b_lam, QLabel("p"), self.b_p, self.b_ord)
        p.addRow("", self.b_row)
        self.norm = QComboBox()
        for t, v in (("none", ""), ("maximum = 1", "max"), ("area = 1", "area"), ("0 to 1", "minmax")):
            self.norm.addItem(t, v)
        p.addRow("Normalise", self.norm)

        k = self.group("Peaks and deconvolution", opts)
        self.pk_mode = QComboBox()
        for t, v in (("none", ""), ("find maxima", "auto"), ("find maxima and shoulders (2nd derivative)", "shoulders"),
                     ("deconvolve into N components", "components"), ("at these positions", "manual")):
            self.pk_mode.addItem(t, v)
        self.pk_mode.setToolTip("Shoulders and N components find overlapping (merged) bands from minima of the "
                                "second derivative")
        k.addRow("Fit peaks", self.pk_mode)
        self.ncomp = _spin(1, 30, 3)
        self.ncomp.setSuffix(" components")
        k.addRow("Number", self.ncomp)
        self.pk_list = QLineEdit()
        self.pk_list.setPlaceholderText("e.g. 1450, 1600 – or click on the preview")
        k.addRow("Positions", self.pk_list)
        self.shape = QComboBox()
        for t, v in (("pseudo-Voigt", "voigt"), ("Gaussian", "gauss"), ("Lorentzian", "lorentz")):
            self.shape.addItem(t, v)
        k.addRow("Shape", self.shape)
        self.prom = _spin(0.001, 1, 0.05, dec=3, step=0.01)
        self.prom.setToolTip("Automatic search: a peak must rise this fraction of the data range above its surroundings")
        self.maxp = _spin(1, 50, 10)
        k.addRow("Search", self.row(QLabel("prominence"), self.prom, QLabel("max."), self.maxp))
        self.fr_lo, self.fr_hi = QLineEdit(), QLineEdit()
        self.fr_lo.setPlaceholderText("all")
        self.fr_hi.setPlaceholderText("all")
        self.fr_lo.setToolTip("Fit the peaks only over this x range (the rest is kept and shown)")
        k.addRow("Fit range", self.row(self.fr_lo, QLabel("–"), self.fr_hi, stretch=0))
        self.cwin = _spin(0, 1e6, 0, dec=3, step=1.0, special="free")
        self.cwin.setToolTip("Each centre may move at most this far from its starting position (0: free)")
        self.w_lo, self.w_hi = QLineEdit(), QLineEdit()
        self.w_lo.setPlaceholderText("min")
        self.w_hi.setPlaceholderText("max")
        self.w_lo.setToolTip("Limits for every peak width (FWHM), in x units")
        k.addRow("Centre ±", self.cwin)
        k.addRow("FWHM", self.row(self.w_lo, QLabel("–"), self.w_hi, stretch=0))
        self.areas = QLineEdit()
        self.areas.setPlaceholderText("LO:HI, LO:HI  e.g. 1400:1500")
        k.addRow("Areas", self.areas)

        o = self.group("Figure and output", opts)
        self.xlabel, self.ylabel = MathLineEdit(), MathLineEdit()
        self.xlabel.setPlaceholderText("automatic from the unit, e.g. Wavenumber (cm$^{-1}$)")
        self.ylabel.setPlaceholderText("Intensity")
        o.addRow("x title", self.xlabel)
        o.addRow("y title", self.ylabel)
        self.template = TemplateCombo()
        self.template.set_value(P.get("template"))
        o.addRow("Journal", self.template)
        self.width = WidthCombo(P.get("width"))
        o.addRow("Width", self.width)
        self.formats = FormatChecks(default=P.get("formats"))
        o.addRow("Formats", self.formats)
        self.out = PathEdit("save", "Base name (*)", "next to the data: <name>_analysis")
        o.addRow("Save as", self.out)
        opts.addStretch(1)

        bar = QHBoxLayout()
        self.auto = QCheckBox("Live preview")
        self.auto.setChecked(P.get("auto_preview"))
        self.pick = QToolButton()
        self.pick.setText(" Add peaks by clicking")
        self.pick.setIcon(icon("peak"))
        self.pick.setCheckable(True)
        self.pick.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.pick.setToolTip("Click on a peak in the preview to fit a peak there")
        self.pick.toggled.connect(lambda on: self.view.view.set_tool("pick" if on else "pan"))
        clear = QPushButton("Clear peaks")
        clear.clicked.connect(lambda: self.pk_list.setText(""))
        refresh = QPushButton(icon("refresh"), "Preview")
        refresh.clicked.connect(self.preview)
        bar.addWidget(self.auto)
        bar.addWidget(self.pick)
        bar.addWidget(clear)
        bar.addStretch(1)
        bar.addWidget(refresh)
        work.addLayout(bar)
        self.view = ImagePanel("Choose a data file to see its analysis.")
        self.view.view.picked.connect(self._picked)
        work.addWidget(self.view, 3)
        self.steps = QLabel("")
        self.steps.setObjectName("Muted")
        self.steps.setWordWrap(True)
        work.addWidget(self.steps)
        self.table = QTableWidget(0, 0)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(150)
        self.table.setMaximumHeight(220)
        work.addWidget(self.table, 1)
        self.cmd = CommandBar()
        bottom = QHBoxLayout()
        bottom.addWidget(self.cmd, 1)
        self.save_btn = primary_button("Save results", "save")
        self.save_btn.clicked.connect(self.save)
        bottom.addWidget(self.save_btn)
        work.addLayout(bottom)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self.preview)
        for e in (self.crop_lo, self.crop_hi, self.b_lam, self.b_p, self.pk_list, self.areas, self.xlabel, self.ylabel,
                  self.fr_lo, self.fr_hi, self.w_lo, self.w_hi):
            e.textChanged.connect(self.changed)
        for cb in (self.series, self.u_from, self.u_to, self.smooth, self.base, self.norm, self.pk_mode, self.shape,
                   self.template, self.width):
            cb.currentIndexChanged.connect(self.changed)
        for sp in (self.sm_win, self.sm_ord, self.b_ord, self.prom, self.maxp, self.ncomp, self.cwin):
            sp.valueChanged.connect(self.changed)
        self.jacobian.toggled.connect(self.changed)
        self.width.editTextChanged.connect(self.changed)
        self.formats.changed.connect(self.changed)
        self.out.edit.textChanged.connect(self.changed)
        self.pk_list.textEdited.connect(lambda *_: self._manual())
        self._enable()

    # ───────────────────────── data ─────────────────────────
    def open_path(self, path: str):
        if not path or not Path(path).is_file():
            return
        self.data.setText(path)
        self.win.prefs.add_recent(path)
        self.out.edit.setPlaceholderText(str(Path(path).with_name(Path(path).stem + "_analysis")))
        try:
            from ...analysis import load_series
            self.series_names = [n for n, _, _ in load_series(path)]
        except Exception as exc:  # noqa: BLE001
            self.series_names = []
            self.win.status(f"Cannot read {Path(path).name}: {exc}")
        self.series.blockSignals(True)
        self.series.clear()
        if len(self.series_names) > 1:
            self.series.addItem("all (preview: the first)", "")
        for n in self.series_names:
            self.series.addItem(n, n)
        if len(self.series_names) > 1:
            self.series.setCurrentIndex(1)
        self.series.blockSignals(False)
        self.changed()

    def _manual(self):
        if self.pk_list.text().strip() and self.pk_mode.currentData() != "manual":
            self.pk_mode.setCurrentIndex(self.pk_mode.findData("manual"))

    def _picked(self, px: float, py: float):
        if not self._map:
            return
        x0, x1, lo, hi = self._map
        if not (x0 <= px <= x1):
            return
        v = lo + (px - x0) / (x1 - x0) * (hi - lo)
        cur = [t.strip() for t in self.pk_list.text().split(",") if t.strip()]
        cur.append(f"{v:.4g}")
        self.pk_list.setText(", ".join(cur))
        self.pk_mode.setCurrentIndex(self.pk_mode.findData("manual"))

    def _enable(self):
        b = self.base.currentData()
        self.b_row.setVisible(bool(b) and b != "ends")
        self.b_lam.setVisible(b == "als")
        self.b_p.setVisible(b == "als")
        for w in self.b_row.findChildren(QLabel):
            w.setVisible(b == "als")
        self.b_ord.setVisible(b == "poly")
        sm = self.smooth.currentData()
        self.sm_win.setEnabled(bool(sm))
        self.sm_ord.setEnabled(sm == "savgol")
        m = self.pk_mode.currentData()
        self.pk_list.setEnabled(m in ("", "manual"))
        on = bool(m) or bool(self.pk_list.text().strip())
        for w in (self.shape, self.fr_lo, self.fr_hi, self.cwin, self.w_lo, self.w_hi):
            w.setEnabled(on)
        self.prom.setEnabled(m in ("auto", "shoulders", "components"))
        self.maxp.setEnabled(m in ("auto", "shoulders"))
        self.ncomp.setEnabled(m == "components")
        self.jacobian.setEnabled(bool(self.u_from.currentData() and self.u_to.currentData()))

    # ───────────────────────── command ─────────────────────────
    def argv(self, preview: bool = False) -> List[str]:
        path = self.data.text()
        a = ["analyze", path or "DATA"]
        ser = self.series.currentData()
        if ser:
            a += ["--series", ser]
        if self.u_from.currentData() and self.u_to.currentData():
            a += ["--convert", f"{self.u_from.currentData()}:{self.u_to.currentData()}"]
            if self.jacobian.isChecked():
                a.append("--jacobian")
        lo, hi = self.crop_lo.text().strip(), self.crop_hi.text().strip()
        if lo and hi:
            a += ["--crop", f"{lo}:{hi}"]
        sm = self.smooth.currentData()
        if sm == "savgol":
            a += ["--smooth", f"savgol:{self.sm_win.value()}:{self.sm_ord.value()}"]
        elif sm:
            a += ["--smooth", f"mean:{self.sm_win.value()}"]
        b = self.base.currentData()
        if b == "als":
            a += ["--baseline", f"als:{self.b_lam.text().strip() or '1e5'}:{self.b_p.text().strip() or '0.01'}"]
        elif b == "poly":
            a += ["--baseline", f"poly:{self.b_ord.value()}"]
        elif b:
            a += ["--baseline", b]
        if self.norm.currentData():
            a += ["--normalize", self.norm.currentData()]
        m = self.pk_mode.currentData()
        if m in ("auto", "shoulders"):
            a += ["--peaks", m]
            if self.maxp.value() != 10:
                a += ["--max-peaks", str(self.maxp.value())]
        elif m == "components":
            a += ["--components", str(self.ncomp.value())]
        elif m == "manual" and self.pk_list.text().strip():
            a += ["--peaks", ",".join(t.strip() for t in self.pk_list.text().split(",") if t.strip())]
        if m in ("auto", "shoulders", "components") and abs(self.prom.value() - 0.05) > 1e-9:
            a += ["--prominence", f"{self.prom.value():g}"]
        if m or self.pk_list.text().strip():
            if self.shape.currentData() != "voigt":
                a += ["--shape", self.shape.currentData()]
            lo, hi = self.fr_lo.text().strip(), self.fr_hi.text().strip()
            if lo and hi:
                a += ["--fit-range", f"{lo}:{hi}"]
            if self.cwin.value() > 0:
                a += ["--center-window", f"{self.cwin.value():g}"]
            lo, hi = self.w_lo.text().strip(), self.w_hi.text().strip()
            if lo or hi:
                a += ["--fwhm-range", f"{lo or 0}:{hi or 1e12}"]
        if self.areas.text().strip():
            a += ["--area", ",".join(t.strip() for t in self.areas.text().split(",") if t.strip())]
        for flag, e in (("--xlabel", self.xlabel), ("--ylabel", self.ylabel)):
            if e.text().strip():
                a += [flag, e.text().strip()]
        if self.template.value() and self.template.value() != "natchem":
            a += ["-t", self.template.value()]
        if self.width.value() != "single":
            a += ["--width", self.width.value()]
        out = self.out.text() or (str(Path(path).with_name(Path(path).stem + "_analysis")) if path else "")
        if out:
            a += ["-o", out]
        if self.formats.value() != "pdf,svg,png":
            a += ["-f", self.formats.value()]
        return a

    def changed(self, *_):
        self._enable()
        self.cmd.set_argv(self.argv())
        if self.auto.isChecked() and self.data.text():
            self._timer.start()

    def _parsed(self, argv):
        import contextlib
        import io
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                return self.parse(argv), ""
        except SystemExit:
            return None, err.getvalue().strip().splitlines()[-1] if err.getvalue().strip() else "invalid options"

    def preview(self):
        if not self.data.text():
            return
        if self.win.runner.busy:
            self._timer.start()
            return
        argv = self.argv()
        if not self.series.currentData() and self.series_names:
            argv = argv[:2] + ["--series", self.series_names[0]] + argv[2:]
        a, msg = self._parsed(argv)
        if a is None:
            self.steps.setText("⚠ " + msg.replace("resrijan analyze: error: ", ""))
            return
        self.win.runner.run("Analysing", lambda: analysis_preview(a), self._show,
                            lambda m: self.steps.setText("⚠ " + m.strip().splitlines()[-1]))

    def _show(self, res):
        png, an, mapping = res
        self._map = mapping
        self.view.view.set_image(QImage.fromData(png), fit=not self.view.view.has_image())
        from ...analysis import summary_lines
        self.steps.setText(" · ".join(an.steps) or "No processing chosen.")
        self._fill_table(an)
        self.win.status("; ".join(summary_lines(an)[1:2]) or "Preview ready.")

    def _fill_table(self, an):
        from ...analysis import _fmt, peak_table
        rows = peak_table(an)
        heads = ["peak", "centre", "FWHM", "height", "area", "area %"]
        if rows and "eta" in rows[0]:
            heads.append("Lorentz. fraction")
        areas = an.areas
        self.table.clear()
        self.table.setColumnCount(len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        self.table.setRowCount(len(rows) + len(areas))
        for i, r in enumerate(rows):
            vals = [str(r["peak"]), _fmt(r["center"], r["center_err"]), _fmt(r["fwhm"], r["fwhm_err"]),
                    _fmt(r["height"], r["height_err"]), _fmt(r["area"], r["area_err"]),
                    _fmt(r["area_pct"], r["area_pct_err"])]
            if "eta" in r:
                vals.append(_fmt(r["eta"], r["eta_err"]))
            for c, v in enumerate(vals):
                self.table.setItem(i, c, QTableWidgetItem(v))
        for j, ar in enumerate(areas):
            i = len(rows) + j
            self.table.setItem(i, 0, QTableWidgetItem("area"))
            self.table.setItem(i, 1, QTableWidgetItem(f"{ar['from']:g} – {ar['to']:g}"))
            self.table.setItem(i, 4, QTableWidgetItem(f"{ar['area']:.6g}"))
        if an.fit:
            self.table.setToolTip(f"R² = {an.fit.r2:.5f}, RMS residual {an.fit.rmse:.3g}; errors are one standard deviation")
        self.table.resizeColumnsToContents()

    def save(self):
        if not self.data.text():
            self.error("Analyze", "Choose a data file first.")
            return
        if not self.formats.value():
            self.error("Analyze", "Tick at least one format.")
            return
        argv = self.argv()
        a, msg = self._parsed(argv)
        if a is None:
            self.error("Analyze", "These options are not valid:\n\n" + msg)
            return

        def job():
            from ...analysis import summary_lines
            print(self.command_text(argv))
            res = cli.run_analyze(a)
            for an, files in res:
                print("\n".join(summary_lines(an)))
            return res

        def done(res):
            n = sum(len(f) for _, f in res)
            self.win.status(f"Saved {n} file(s) for {len(res)} series.")

        self.win.runner.run("Saving analysis", job, done, lambda m: self.error("Analysis failed", m))

    # project files
    def state(self) -> dict:
        return {"data": self.data.text(), "series": self.series.currentData(), "from": self.u_from.currentData(),
                "to": self.u_to.currentData(), "jacobian": self.jacobian.isChecked(),
                "crop": [self.crop_lo.text(), self.crop_hi.text()], "smooth": self.smooth.currentData(),
                "sm_win": self.sm_win.value(), "sm_ord": self.sm_ord.value(), "baseline": self.base.currentData(),
                "lam": self.b_lam.text(), "p": self.b_p.text(), "b_ord": self.b_ord.value(),
                "normalize": self.norm.currentData(), "peaks_mode": self.pk_mode.currentData(),
                "peaks": self.pk_list.text(), "shape": self.shape.currentData(), "prominence": self.prom.value(),
                "max_peaks": self.maxp.value(), "components": self.ncomp.value(),
                "fit_range": [self.fr_lo.text(), self.fr_hi.text()], "center_window": self.cwin.value(),
                "fwhm": [self.w_lo.text(), self.w_hi.text()], "areas": self.areas.text(), "xlabel": self.xlabel.text(),
                "ylabel": self.ylabel.text(), "template": self.template.value(), "width": self.width.value(),
                "formats": self.formats.value(), "out": self.out.text()}

    def set_state(self, s: dict):
        from ..project import set_combo
        if s.get("data") and Path(s["data"]).is_file():
            self.open_path(s["data"])
        set_combo(self.series, s.get("series"))
        set_combo(self.u_from, s.get("from"))
        set_combo(self.u_to, s.get("to"))
        self.jacobian.setChecked(bool(s.get("jacobian")))
        lo, hi = (s.get("crop") or ["", ""])[:2]
        self.crop_lo.setText(lo)
        self.crop_hi.setText(hi)
        set_combo(self.smooth, s.get("smooth"))
        self.sm_win.setValue(int(s.get("sm_win", 11)))
        self.sm_ord.setValue(int(s.get("sm_ord", 3)))
        set_combo(self.base, s.get("baseline"))
        self.b_lam.setText(s.get("lam", "1e5"))
        self.b_p.setText(s.get("p", "0.01"))
        self.b_ord.setValue(int(s.get("b_ord", 2)))
        set_combo(self.norm, s.get("normalize"))
        set_combo(self.pk_mode, s.get("peaks_mode"))
        self.pk_list.setText(s.get("peaks", ""))
        set_combo(self.shape, s.get("shape", "voigt"))
        self.prom.setValue(float(s.get("prominence", 0.05)))
        self.maxp.setValue(int(s.get("max_peaks", 10)))
        self.ncomp.setValue(int(s.get("components", 3)))
        lo, hi = (s.get("fit_range") or ["", ""])[:2]
        self.fr_lo.setText(lo)
        self.fr_hi.setText(hi)
        self.cwin.setValue(float(s.get("center_window", 0)))
        lo, hi = (s.get("fwhm") or ["", ""])[:2]
        self.w_lo.setText(lo)
        self.w_hi.setText(hi)
        self.areas.setText(s.get("areas", ""))
        self.xlabel.setText(s.get("xlabel", ""))
        self.ylabel.setText(s.get("ylabel", ""))
        if s.get("template"):
            self.template.set_value(s["template"])
        if s.get("width"):
            self.width.setCurrentText(s["width"])
        if s.get("formats"):
            self.formats.set_value(s["formats"])
        self.out.setText(s.get("out", ""))
        self.changed()
