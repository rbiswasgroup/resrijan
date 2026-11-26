"""Fit: non-linear fitting of any formula (or a preset) to one or more series, with starting values,
bounds, fixed constants, a fit range and derived quantities – every option of `resrijan fit`."""
from __future__ import annotations

import math
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QImage
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QToolButton)

from ... import cli
from ...curvefit import PRESETS, ExpressionError, preset_bounds
from ..icons import icon
from ..render import fit_preview
from ..textedit import MathLineEdit
from ..widgets import CommandBar, FormatChecks, ImagePanel, PathEdit, TemplateCombo, WidthCombo, primary_button
from .base import Page

DATA_FILTER = "Data (*.csv *.tsv *.txt *.dat);;All files (*)"
PCOLS = ["parameter", "start", "lower", "upper", "fixed", "result"]


class FitPage(Page):
    title = "Fit"
    subtitle = ("Fit any formula – exponential or stretched-exponential decays, MSD, power laws, your own "
                "expression – with bounds, fixed constants and a fit range.")
    icon = "curvefit"

    def __init__(self, win):
        super().__init__(win)
        P = win.prefs
        self.columns: List[str] = []
        self.long_format = False
        self._map = None
        self._range_clicks: List[float] = []
        self._names: List[str] = []
        opts, work = self.split(490)

        d = self.group("Data", opts)
        self.data = PathEdit("open", DATA_FILTER, "a table: correlation function, MSD, … or a *_data.csv")
        self.data.changed.connect(self.open_path)
        d.addRow("File", self.data)
        self.x = QComboBox()
        d.addRow("x", self.x)
        self.ylist = QListWidget()
        self.ylist.setMaximumHeight(110)
        self.ylist.setToolTip("Each ticked series is fitted separately with the same model")
        d.addRow("y (each fitted)", self.ylist)
        self.sigma = QComboBox()
        self.sigma.setToolTip("Uncertainties of y, used as weights 1/σ²")
        d.addRow("Weights σ", self.sigma)
        self.abs_sigma = QCheckBox("σ are absolute (no rescaling by the reduced χ²)")
        d.addRow("", self.abs_sigma)

        m = self.group("Model", opts)
        self.preset = QComboBox()
        self.preset.addItem("your own formula", "")
        for k, (e, desc, _) in PRESETS.items():
            self.preset.addItem(f"{desc}  ·  {k}", k)
        self.preset.currentIndexChanged.connect(self._preset_chosen)
        m.addRow("Preset", self.preset)
        self.expr = QLineEdit()
        f = QFont("monospace")
        f.setStyleHint(QFont.Monospace)
        self.expr.setFont(f)
        self.expr.setPlaceholderText("e.g. A*exp(-(x/tau)**beta) + C   or   6*D*x + c")
        self.expr.setToolTip("Formula in x. Every other name is a fitted constant. Functions: exp, log, ln, log10, "
                             "sqrt, sin, cos, tanh, erf, gamma, abs …; constants: pi, kB, R, NA, h.")
        m.addRow("y =", self.expr)
        self.expr_msg = QLabel("")
        self.expr_msg.setObjectName("Muted")
        self.expr_msg.setWordWrap(True)
        m.addRow("", self.expr_msg)
        self.ptab = QTableWidget(0, len(PCOLS))
        self.ptab.setHorizontalHeaderLabels(PCOLS)
        self.ptab.verticalHeader().setVisible(False)
        self.ptab.horizontalHeader().setStretchLastSection(True)
        self.ptab.setMinimumHeight(150)
        self.ptab.setMaximumHeight(240)
        self.ptab.setToolTip("Empty start: guessed from the data. Empty lower/upper: no limit. "
                             "Fixed: the constant keeps its start value.")
        m.addRow(self.ptab)
        self.derived = QLineEdit()
        self.derived.setPlaceholderText("name = formula; …   e.g. tau_avg = tau/beta*gamma(1/beta)")
        self.derived.setToolTip("Quantities computed from the fitted constants, with propagated errors")
        m.addRow("Derived", self.derived)

        r = self.group("Fit range and options", opts)
        self.r_lo, self.r_hi = QLineEdit(), QLineEdit()
        self.r_lo.setPlaceholderText("all data")
        self.r_hi.setPlaceholderText("all data")
        r.addRow("Fit x from", self.row(self.r_lo, QLabel("to"), self.r_hi, stretch=0))
        self.starts = QSpinBox()
        self.starts.setRange(1, 200)
        self.starts.setValue(12)
        self.starts.setToolTip("The fit starts from this many points (the first from your start values) and keeps the best")
        r.addRow("Starting points", self.starts)
        self.xlog, self.ylog = QCheckBox("log x"), QCheckBox("log y")
        r.addRow("Figure axes", self.row(self.xlog, self.ylog))

        o = self.group("Figure and output", opts)
        self.xlabel, self.ylabel = MathLineEdit(), MathLineEdit()
        self.xlabel.setPlaceholderText("e.g. t (ps)")
        self.ylabel.setPlaceholderText("e.g. C(t) or MSD (Å$^{2}$)")
        o.addRow("x title", self.xlabel)
        o.addRow("y title", self.ylabel)
        self.template = TemplateCombo()
        self.template.set_value(P.get("template"))
        o.addRow("Journal", self.template)
        self.width = WidthCombo(P.get("width"))
        o.addRow("Width", self.width)
        self.formats = FormatChecks(default=P.get("formats"))
        o.addRow("Formats", self.formats)
        self.out = PathEdit("save", "Base name (*)", "next to the data: <name>_fit")
        o.addRow("Save as", self.out)
        opts.addStretch(1)

        bar = QHBoxLayout()
        self.auto = QCheckBox("Live preview")
        self.auto.setChecked(P.get("auto_preview"))
        self.pick = QToolButton()
        self.pick.setText(" Set range by clicking")
        self.pick.setIcon(icon("region"))
        self.pick.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.pick.setCheckable(True)
        self.pick.setToolTip("Click the start and then the end of the fit range on the preview")
        self.pick.toggled.connect(self._pick_toggled)
        full = QPushButton("Full range")
        full.clicked.connect(lambda: (self.r_lo.setText(""), self.r_hi.setText("")))
        refresh = QPushButton(icon("refresh"), "Fit")
        refresh.clicked.connect(self.preview)
        bar.addWidget(self.auto)
        bar.addWidget(self.pick)
        bar.addWidget(full)
        bar.addStretch(1)
        bar.addWidget(refresh)
        work.addLayout(bar)
        self.view = ImagePanel("Choose a data file and a model to fit.")
        self.view.view.picked.connect(self._picked)
        work.addWidget(self.view, 3)
        self.msg = QLabel("")
        self.msg.setObjectName("Muted")
        self.msg.setWordWrap(True)
        work.addWidget(self.msg)
        self.rtab = QTableWidget(0, 0)
        self.rtab.verticalHeader().setVisible(False)
        self.rtab.setEditTriggers(QTableWidget.NoEditTriggers)
        self.rtab.setMinimumHeight(120)
        self.rtab.setMaximumHeight(220)
        work.addWidget(self.rtab, 1)
        self.cmd = CommandBar()
        bottom = QHBoxLayout()
        bottom.addWidget(self.cmd, 1)
        self.save_btn = primary_button("Save results", "save")
        self.save_btn.clicked.connect(self.save)
        bottom.addWidget(self.save_btn)
        work.addLayout(bottom)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self.preview)
        self.expr.textChanged.connect(self._expr_changed)
        for e in (self.derived, self.r_lo, self.r_hi, self.xlabel, self.ylabel):
            e.textChanged.connect(self.changed)
        for cb in (self.x, self.sigma, self.template, self.width):
            cb.currentIndexChanged.connect(self.changed)
        for c in (self.abs_sigma, self.xlog, self.ylog):
            c.toggled.connect(self.changed)
        self.starts.valueChanged.connect(self.changed)
        self.ylist.itemChanged.connect(self.changed)
        self.ptab.itemChanged.connect(self.changed)
        self.width.editTextChanged.connect(self.changed)
        self.formats.changed.connect(self.changed)
        self.out.edit.textChanged.connect(self.changed)
        self.preset.setCurrentIndex(self.preset.findData("exp1"))

    # ───────────────────────── data ─────────────────────────
    def open_path(self, path: str):
        if not path or not Path(path).is_file():
            return
        self.data.setText(path)
        self.win.prefs.add_recent(path)
        self.win.data_opened(path)
        self.out.edit.setPlaceholderText(str(Path(path).with_name(Path(path).stem + "_fit")))
        try:
            from ...plot.engine import read_table
            tab = read_table(path)
        except Exception as exc:  # noqa: BLE001
            self.win.status(f"Cannot read {Path(path).name}: {exc}")
            return
        self.columns = list(tab)
        self.long_format = "series" in tab and "x" in tab and "y" in tab
        self.x.blockSignals(True)
        self.x.clear()
        self.ylist.blockSignals(True)
        self.ylist.clear()
        self.sigma.blockSignals(True)
        self.sigma.clear()
        self.sigma.addItem("none (equal weights)", "")
        if self.long_format:
            self.x.addItem("x")
            self.x.setEnabled(False)
            for n in dict.fromkeys(str(v) for v in tab["series"]):
                it = QListWidgetItem(n)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked)
                self.ylist.addItem(it)
            if "yerr_minus" in tab:
                self.sigma.addItem("error bars of the data file", "errors")
        else:
            self.x.setEnabled(True)
            num = [c for c in self.columns if tab[c].dtype != object]
            self.x.addItems(num)
            for c in num[1:]:
                it = QListWidgetItem(c)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                low = c.lower()
                is_err = low.startswith(("err", "sd_", "std", "sigma")) or low.endswith(("_err", "_sd", "_std"))
                it.setCheckState(Qt.Unchecked if is_err else Qt.Checked)
                self.ylist.addItem(it)
                self.sigma.addItem(c, c)
        for w in (self.x, self.ylist, self.sigma):
            w.blockSignals(False)
        self.changed()

    def _ys(self) -> List[str]:
        return [self.ylist.item(i).text() for i in range(self.ylist.count())
                if self.ylist.item(i).checkState() == Qt.Checked]

    # ───────────────────────── model ─────────────────────────
    def _preset_chosen(self, *_):
        key = self.preset.currentData()
        if not key:
            return
        e, _, der = PRESETS[key]
        bounds = {p.name: p for p in preset_bounds(key)}
        self.expr.blockSignals(True)
        self.expr.setText(e)
        self.expr.blockSignals(False)
        self._rebuild_params(reset=True, bounds=bounds)
        self.derived.setText("; ".join(f"{k} = {v}" for k, v in der.items()))
        if key.startswith(("exp", "kww", "damped")) and not self.xlabel.text():
            self.xlog.setChecked(key != "damped_cos")
        elif key.startswith("msd"):
            self.xlog.setChecked(False)
        self.changed()

    def _expr_changed(self, *_):
        key = self.preset.currentData()
        if key and self.expr.text().strip() != PRESETS[key][0]:
            self.preset.blockSignals(True)
            self.preset.setCurrentIndex(0)
            self.preset.blockSignals(False)
        self._rebuild_params()
        self.changed()

    def _rebuild_params(self, reset: bool = False, bounds=None):
        from ...curvefit import parse_model
        try:
            _, names = parse_model(self.expr.text())
            self.expr_msg.setText(f"{len(names)} constant(s) to fit: {', '.join(names)}" if names else
                                  "⚠ the formula has no constants to fit")
        except ExpressionError as exc:
            self.expr_msg.setText(f"⚠ {exc}")
            return
        old = {} if reset else {r["name"]: r for r in self._rows()}
        self.ptab.blockSignals(True)
        self.ptab.setRowCount(len(names))
        for i, n in enumerate(names):
            it = QTableWidgetItem(n)
            it.setFlags(Qt.ItemIsEnabled)
            self.ptab.setItem(i, 0, it)
            o = old.get(n, {})
            b = (bounds or {}).get(n)
            lo = o.get("lo", "" if b is None or not math.isfinite(b.lo) else f"{b.lo:g}")
            hi = o.get("hi", "" if b is None or not math.isfinite(b.hi) else f"{b.hi:g}")
            for c, v in ((1, o.get("start", "")), (2, lo), (3, hi)):
                self.ptab.setItem(i, c, QTableWidgetItem(v))
            fx = QTableWidgetItem()
            fx.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            fx.setCheckState(Qt.Checked if o.get("fixed") else Qt.Unchecked)
            self.ptab.setItem(i, 4, fx)
            res = QTableWidgetItem("")
            res.setFlags(Qt.ItemIsEnabled)
            self.ptab.setItem(i, 5, res)
        self.ptab.blockSignals(False)
        self.ptab.resizeColumnToContents(0)
        for c in (1, 2, 3):
            self.ptab.setColumnWidth(c, 58)
        self.ptab.resizeColumnToContents(4)
        self._names = names

    def _rows(self) -> List[dict]:
        out = []
        for i in range(self.ptab.rowCount()):
            def t(c):
                it = self.ptab.item(i, c)
                return it.text().strip() if it else ""
            fx = self.ptab.item(i, 4)
            out.append({"name": t(0), "start": t(1), "lo": t(2), "hi": t(3),
                        "fixed": bool(fx and fx.checkState() == Qt.Checked)})
        return out

    # ───────────────────────── range by clicking ─────────────────────────
    def _pick_toggled(self, on: bool):
        self._range_clicks = []
        self.view.view.set_tool("pick" if on else "pan")
        if on:
            self.msg.setText("Click the start of the fit range on the preview, then its end.")

    def _picked(self, px: float, py: float):
        if not self._map:
            return
        x0, x1, lo, hi, logx = self._map
        f = (px - x0) / (x1 - x0)
        if not 0 <= f <= 1:
            return
        v = 10 ** (math.log10(lo) + f * (math.log10(hi) - math.log10(lo))) if logx else lo + f * (hi - lo)
        self._range_clicks.append(v)
        if len(self._range_clicks) == 1:
            self.msg.setText(f"Range starts at {v:.4g} – now click its end.")
        else:
            a, b = sorted(self._range_clicks[:2])
            self.r_lo.setText(f"{a:.4g}")
            self.r_hi.setText(f"{b:.4g}")
            self._range_clicks = []
            self.pick.setChecked(False)

    # ───────────────────────── command ─────────────────────────
    def argv(self) -> List[str]:
        path = self.data.text()
        a = ["fit", path or "DATA"]
        if not self.long_format and self.x.currentText():
            a += ["-x", self.x.currentText()]
        ys = self._ys()
        if ys and self.ylist.count() and len(ys) < self.ylist.count():
            if self.long_format:
                if len(ys) == 1:
                    a += ["--series", ys[0]]
            else:
                a += ["-y", ",".join(ys)]
        elif ys and not self.long_format:
            a += ["-y", ",".join(ys)]
        key = self.preset.currentData()
        a += ["-m", key if key else (self.expr.text().strip() or "exp1")]
        p0, bnd, fix = [], [], []
        for r in self._rows():
            n = r["name"]
            if r["fixed"]:
                fix.append(f"{n}={r['start'] or 0}")
                continue
            if r["start"]:
                p0.append(f"{n}={r['start']}")
            if r["lo"] or r["hi"]:
                bnd.append(f"{n}={r['lo']}:{r['hi']}")
        if p0:
            a += ["--p0", ",".join(p0)]
        if bnd:
            a += ["--bounds", ",".join(bnd)]
        if fix:
            a += ["--fix", ",".join(fix)]
        der = self.derived.text().strip()
        if der and (not key or der != "; ".join(f"{k} = {v}" for k, v in PRESETS[key][2].items())):
            a += ["--derived", der]
        lo, hi = self.r_lo.text().strip(), self.r_hi.text().strip()
        if lo and hi:
            a += ["--range", f"{lo}:{hi}"]
        if self.sigma.currentData():
            a += ["--sigma", self.sigma.currentData()]
            if self.abs_sigma.isChecked():
                a.append("--absolute-sigma")
        if self.starts.value() != 12:
            a += ["--starts", str(self.starts.value())]
        if self.xlog.isChecked():
            a += ["--xscale", "log"]
        if self.ylog.isChecked():
            a += ["--yscale", "log"]
        for flag, e in (("--xlabel", self.xlabel), ("--ylabel", self.ylabel)):
            if e.text().strip():
                a += [flag, e.text().strip()]
        if self.template.value() and self.template.value() != "natchem":
            a += ["-t", self.template.value()]
        if self.width.value() != "single":
            a += ["--width", self.width.value()]
        out = self.out.text() or (str(Path(path).with_name(Path(path).stem + "_fit")) if path else "")
        if out:
            a += ["-o", out]
        if self.formats.value() != "pdf,svg,png":
            a += ["-f", self.formats.value()]
        return a

    def changed(self, *_):
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
            t = err.getvalue().strip()
            return None, (t.splitlines()[-1] if t else "invalid options").replace("resrijan fit: error: ", "")

    def preview(self):
        if not self.data.text():
            return
        if self.win.runner.busy:
            self._timer.start()
            return
        argv = self.argv()
        a, msg = self._parsed(argv)
        if a is None:
            self.msg.setText("⚠ " + msg)
            return
        if self.long_format and len(self._ys()) not in (1, self.ylist.count()):
            self.msg.setText("Tick one series or all of them (data files with a 'series' column).")
            return
        self.msg.setText("Fitting …")
        self.win.runner.run("Fitting", lambda: fit_preview(a), self._show,
                            lambda m: self.msg.setText("⚠ " + m.strip().splitlines()[-1]))

    def _show(self, res):
        from ...curvefit import fmt
        png, results, mapping = res
        self._map = mapping
        self.view.view.set_image(QImage.fromData(png), fit=not self.view.view.has_image())
        name0, r0, _, _ = results[0]
        notes = [f"R² = {r0.r2:.5f}, reduced χ² = {r0.chi2_red:.4g}, {r0.n} points from x = {r0.x_range[0]:.4g} "
                 f"to {r0.x_range[1]:.4g}" + (f" (first of {len(results)} series)" if len(results) > 1 else "")]
        bad = sorted({n for _, r, _, _ in results for n in r.at_bounds})
        if bad:
            notes.append(f"⚠ {', '.join(bad)} ended at a bound – widen it or check the model")
        self.msg.setText(" · ".join(notes))
        self.ptab.blockSignals(True)
        for i, n in enumerate(r0.names):
            if i < self.ptab.rowCount():
                tag = " (fixed)" if n in r0.fixed else (" ⚠ bound" if n in r0.at_bounds else "")
                self.ptab.item(i, 5).setText(fmt(r0.values[n], r0.errors[n]) + tag)
        self.ptab.blockSignals(False)
        names = r0.names
        dn = list(r0.derived)
        heads = ["series"] + names + dn + ["R²"]
        self.rtab.clear()
        self.rtab.setColumnCount(len(heads))
        self.rtab.setHorizontalHeaderLabels(heads)
        self.rtab.setRowCount(len(results))
        for i, (name, r, _, _) in enumerate(results):
            vals = [name] + [fmt(r.values[n], r.errors[n]) for n in names] + \
                   [fmt(*r.derived[k]) for k in dn] + [f"{r.r2:.5f}"]
            for c, v in enumerate(vals):
                self.rtab.setItem(i, c, QTableWidgetItem(v))
        self.rtab.resizeColumnsToContents()
        self.win.status("Fit done.")

    def save(self):
        if not self.data.text():
            self.error("Fit", "Choose a data file first.")
            return
        if not self.formats.value():
            self.error("Fit", "Tick at least one format.")
            return
        argv = self.argv()
        a, msg = self._parsed(argv)
        if a is None:
            self.error("Fit", "These options are not valid:\n\n" + msg)
            return

        def job():
            from ...curvefit import summary_lines
            print(self.command_text(argv))
            results, files = cli.run_fit(a)
            for name, r, _, _ in results:
                print("\n".join(summary_lines(name, r)))
            return files

        self.win.runner.run("Saving fit", job,
                            lambda files: self.win.status("Saved " + ", ".join(
                                Path(f if isinstance(f, str) else f[0]).name for f in files.values())),
                            lambda m: self.error("Fit failed", m))

    # ───────────────────────── project files ─────────────────────────
    def state(self) -> dict:
        return {"data": self.data.text(), "x": self.x.currentText(), "y": self._ys(), "sigma": self.sigma.currentData(),
                "abs_sigma": self.abs_sigma.isChecked(), "preset": self.preset.currentData(),
                "expr": self.expr.text(), "params": self._rows(), "derived": self.derived.text(),
                "range": [self.r_lo.text(), self.r_hi.text()], "starts": self.starts.value(),
                "xlog": self.xlog.isChecked(), "ylog": self.ylog.isChecked(), "xlabel": self.xlabel.text(),
                "ylabel": self.ylabel.text(), "template": self.template.value(), "width": self.width.value(),
                "formats": self.formats.value(), "out": self.out.text()}

    def set_state(self, s: dict):
        from ..project import set_combo
        if s.get("data"):
            if not Path(s["data"]).is_file():
                raise FileNotFoundError(f"data file not found: {s['data']}")
            self.open_path(s["data"])
        set_combo(self.x, s.get("x"))
        ys = set(s.get("y") or [])
        for i in range(self.ylist.count()):
            it = self.ylist.item(i)
            it.setCheckState(Qt.Checked if it.text() in ys else Qt.Unchecked)
        set_combo(self.sigma, s.get("sigma") or "")
        self.abs_sigma.setChecked(bool(s.get("abs_sigma")))
        if s.get("preset"):
            set_combo(self.preset, s["preset"])
        else:
            self.preset.setCurrentIndex(0)
            self.expr.setText(s.get("expr", ""))
        rows = {r["name"]: r for r in s.get("params", [])}
        self.ptab.blockSignals(True)
        for i in range(self.ptab.rowCount()):
            r = rows.get(self.ptab.item(i, 0).text())
            if r:
                self.ptab.item(i, 1).setText(r.get("start", ""))
                self.ptab.item(i, 2).setText(r.get("lo", ""))
                self.ptab.item(i, 3).setText(r.get("hi", ""))
                self.ptab.item(i, 4).setCheckState(Qt.Checked if r.get("fixed") else Qt.Unchecked)
        self.ptab.blockSignals(False)
        self.derived.setText(s.get("derived", ""))
        lo, hi = (s.get("range") or ["", ""])[:2]
        self.r_lo.setText(lo)
        self.r_hi.setText(hi)
        self.starts.setValue(int(s.get("starts", 12)))
        self.xlog.setChecked(bool(s.get("xlog")))
        self.ylog.setChecked(bool(s.get("ylog")))
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

