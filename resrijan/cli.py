"""Command-line interface:  resrijan <command> ...

  digitize  FILE      extract data from figures (PDF/EPS/PS/SVG/PNG/JPG/TIFF) and replot them
  plot      DATA      plot a data file with a journal template
  analyze   DATA      baseline, smoothing, normalisation, unit conversion, peak fitting, areas
  fit       DATA      fit any model (formula or preset) with bounds, fixed values and a fit range
  compose   SPEC.yaml build a multi-panel figure from a YAML description
  templates           list journal templates
  inspect   FILE      show pages, embedded images and a pixel-ruler image (for manual calibration)
  pick      FILE      click ticks to build --xcal/--ycal strings (needs a display)
  gui                 open the graphical interface (needs: pip install "resrijan[gui]")
  doctor              check the installation (libraries, OCR, Ghostscript, the GUI)

Each command is split into ``run_*`` (does the work, returns results) and ``cmd_*`` (prints
them). The GUI builds the same command line, parses it with :func:`build_parser` and calls
the same ``run_*`` functions, so both always behave identically.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import os
import sys
from pathlib import Path

from . import __version__

DIGITIZE_TYPES = ["auto", "line", "scatter", "bar", "heatmap", "contourf", "contour", "micrograph"]
PLOT_KINDS = ["line", "scatter", "errorbar", "heatmap", "contourf", "contour", "spectrum2d", "image", "hist", "bar"]
SCALES = ["auto", "linear", "log"]
PREFER = ["auto", "vector", "raster"]
FORMATS = ["pdf", "svg", "eps", "png", "tiff"]


def _formats(s):
    return [f.strip().lower() for f in s.split(",") if f.strip()]


# ───────────────────────────── digitize ─────────────────────────────
def panel_what(p) -> str:
    return (f"{len(p.series)} series" if p.series else
            f"{len(p.contours)} contour lines" if p.kind == "contour" else
            f"{len(p.bars)} bars" if p.bars else
            f"grid {p.grid.z.shape[1]}×{p.grid.z.shape[0]}" if p.grid is not None else
            (f"{p.micro.nm_per_px:.4g} nm/px" if p.micro and p.micro.nm_per_px else "") if p.micro else "")


def panel_summary(p) -> str:
    """One console line per panel (also shown in the GUI's result list)."""
    n_err = sum(n["level"] == "error" for n in p.notes)
    n_warn = sum(n["level"] == "warn" for n in p.notes)
    return f"  {p.id:8s} {p.kind:11s} {p.mode:15s} {panel_what(p):22s} warnings: {n_warn}  errors: {n_err}"


def run_digitize(a):
    """Digitise ``a.file`` with the parsed options; returns (panels, outputs, out_dir)."""
    from .pipeline import digitize, write_outputs
    pages = [int(p) - 1 for p in a.page.split(",")] if a.page else None
    out = a.out or (Path(a.file).stem + "_resrijan")
    panels = digitize(a.file, pages=pages, region=a.region, dpi=a.dpi, kind=a.type, xscale=a.xscale,
                      yscale=a.yscale, xcal=a.xcal, ycal=a.ycal, scale=a.scale, prefer=a.prefer,
                      particles=not a.no_particles, max_series=a.max_series)
    for p in panels:
        if a.xlabel is not None:
            p.xlabel = a.xlabel
        if a.ylabel is not None:
            p.ylabel = a.ylabel
        if getattr(a, "label_color", None) and p.box is not None:   # replot axis titles in this colour
            ts = dict(getattr(p.box, "title_style", None) or {})
            for k in ("x", "y"):
                ts[k] = {**ts.get(k, {}), "color": a.label_color}
            p.box.title_style = ts
    res = write_outputs(panels, out, template=a.template, formats=_formats(a.formats), width=a.width,
                        stem=Path(a.file).stem)
    return panels, res, out


def cmd_digitize(a):
    panels, res, _ = run_digitize(a)
    errors = 0
    for p in panels:
        errors += sum(n["level"] == "error" for n in p.notes)
        print(panel_summary(p))
        if a.verbose:
            for n in p.notes:
                print(f"      [{n['level']}] {n['msg']}")
    print(f"\nReport: {res['report']}")
    return 1 if (errors and a.strict) else 0


# ───────────────────────────── plot ─────────────────────────────
def plot_spec(a) -> dict:
    """Plot-engine panel spec from the parsed ``plot`` options."""
    spec = {"type": a.kind, "data": os.path.abspath(a.data)}
    for k in ("x", "xlabel", "ylabel", "xscale", "yscale", "clabel", "cmap", "column"):
        v = getattr(a, k, None)
        if v:
            spec[k] = v
    if a.y:
        spec["y"] = a.y.split(",")
    if a.yerr:
        spec["yerr"] = a.yerr.split(",")
    if a.xlim:
        spec["xlim"] = [float(v) for v in a.xlim.split(",")]
    if a.ylim:
        spec["ylim"] = [float(v) for v in a.ylim.split(",")]
    if a.nm_per_px:
        spec["nm_per_px"] = a.nm_per_px
    if getattr(a, "colors", None):
        spec["colors"] = [c.strip() for c in a.colors.split(",")]
    if getattr(a, "label_color", None):
        for k in ("xlabel_style", "ylabel_style", "clabel_style"):
            spec[k] = {"color": a.label_color}
    style_spec(a, spec)
    return spec


def _split(v):
    return [t.strip() for t in v.split(",")] if v else None


def style_spec(a, spec: dict) -> dict:
    """Series and legend styling options shared by ``plot`` and ``analyze``."""
    if getattr(a, "linestyles", None):
        spec["linestyles"] = _split(a.linestyles)
    if getattr(a, "markers", None):
        spec["markers"] = _split(a.markers)
    if getattr(a, "linewidth", None):
        spec["linewidth"] = a.linewidth
    if getattr(a, "markersize", None):
        spec["markersize"] = a.markersize
    if getattr(a, "legend", None):
        spec["legend"] = a.legend
    if getattr(a, "legend_frame", False):
        spec["legend_frame"] = True
    if getattr(a, "legend_cols", None):
        spec["legend_ncol"] = a.legend_cols
    if getattr(a, "grid", False):
        spec["grid"] = True
    anns = [parse_text(t) for t in (getattr(a, "text", None) or [])] + \
           [parse_arrow(t) for t in (getattr(a, "arrow", None) or [])]
    if anns:
        spec["annotations"] = spec.get("annotations", []) + anns
    return spec


def figure_style(a) -> dict:
    st = {}
    if getattr(a, "font", None):
        st["font"] = a.font
    if getattr(a, "font_scale", None):
        st["font_scale"] = a.font_scale
    if getattr(a, "line_scale", None):
        st["line_scale"] = a.line_scale
    return st


def _coord(v: str, what: str) -> float:
    try:
        return float(v)
    except ValueError:
        raise ValueError(f"{what}: '{v}' is not a number") from None


def parse_text(t: str) -> dict:
    """'x,y,text[,colour]' (data coordinates) – a text label. Use 'axes:x,y,text' for 0–1 axes fractions."""
    coords = "data"
    if t.startswith("axes:"):
        coords, t = "axes fraction", t[5:]
    parts = t.split(",", 2)
    if len(parts) < 3:
        raise ValueError(f"--text '{t}': expected x,y,text")
    x, y, rest = parts
    text, col = rest, "k"
    if "|" in rest:
        text, col = rest.rsplit("|", 1)
    return {"xy": [_coord(x, "--text"), _coord(y, "--text")], "text": text, "coords": coords,
            "color": col.strip() or "k", "ha": "center", "va": "center"}


def parse_arrow(t: str) -> dict:
    """'x0,y0,x1,y1[,text]' – an arrow from (x0, y0) to (x1, y1), with optional text at its tail."""
    coords = "data"
    if t.startswith("axes:"):
        coords, t = "axes fraction", t[5:]
    parts = t.split(",", 4)
    if len(parts) < 4:
        raise ValueError(f"--arrow '{t}': expected x0,y0,x1,y1[,text]")
    x0, y0, x1, y1 = (_coord(v, "--arrow") for v in parts[:4])
    text, col = (parts[4] if len(parts) > 4 else ""), "k"
    if "|" in text:
        text, col = text.rsplit("|", 1)
    return {"xy": [x1, y1], "xytext": [x0, y0], "text": text, "coords": coords, "color": col.strip() or "k"}


def _check_colors(ap, a):
    """Reject colours matplotlib does not know (before any work is done)."""
    from matplotlib.colors import is_color_like
    bad = [c for c in ((getattr(a, "colors", None) or "").split(",") + [getattr(a, "label_color", None) or ""])
           if c.strip() and not is_color_like(c.strip())]
    if bad:
        ap.error("unknown colour(s): " + ", ".join(bad) + " (use names such as 'navy' or hex codes such as '#1b9e77')")


def run_plot(a):
    """Plot ``a.data``; returns the list of files written."""
    import matplotlib.pyplot as plt
    from .plot.engine import figure, save
    fig, _, _ = figure([plot_spec(a)], template=a.template, width=a.width, labels=False, style=figure_style(a))
    out = a.out or Path(a.data).stem + "_plot"
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    files = save(fig, out, _formats(a.formats))
    plt.close(fig)
    return files


def cmd_plot(a):
    print("\n".join(run_plot(a)))


# ───────────────────────────── analyze ─────────────────────────────
def _num_list(v, what):
    out = []
    for t in (v or "").split(","):
        if t.strip():
            out.append(_coord(t.strip(), what))
    return out


def analyze_options(a) -> dict:
    """Keyword arguments for :func:`resrijan.analysis.analyze` from the parsed options."""
    from .analysis import parse_ranges
    kw = {}
    if a.convert:
        frm, _, to = a.convert.partition(":")
        if not to:
            raise ValueError("--convert: expected FROM:TO, e.g. nm:eV")
        kw["convert"] = (frm, to)
        kw["jacobian"] = a.jacobian
    if a.crop:
        r = parse_ranges(a.crop)
        if len(r) != 1:
            raise ValueError("--crop: expected LO:HI")
        kw["crop"] = r[0]
    if a.smooth:
        p = a.smooth.split(":")
        kw["smooth_opt"] = (p[0], int(p[1]) if len(p) > 1 else 11, int(p[2]) if len(p) > 2 else 3)
    if a.baseline and a.baseline != "none":
        p = a.baseline.split(":")
        m = p[0]
        bkw = {}
        if m == "als":
            if len(p) > 1:
                bkw["lam"] = float(p[1])
            if len(p) > 2:
                bkw["p"] = float(p[2])
        elif m == "poly":
            bkw["order"] = int(p[1]) if len(p) > 1 else 2
        kw["baseline_opt"] = (m, bkw)
    if a.normalize and a.normalize != "none":
        kw["normalize_opt"] = a.normalize
    if a.peaks:
        if a.peaks.strip() in ("auto", "shoulders"):
            kw["auto_peaks"] = True
            kw["peak_method"] = "prominence" if a.peaks.strip() == "auto" else "shoulders"
        else:
            kw["peaks"] = _num_list(a.peaks, "--peaks")
    if a.components:
        if a.components < 1:
            raise ValueError("--components: at least 1")
        kw["n_components"] = a.components
        kw.setdefault("peak_method", "shoulders")
    if a.center_window is not None:
        kw["center_window"] = a.center_window
    for opt, key in (("fwhm_range", "fwhm_range"), ("fit_range", "fit_range")):
        v = getattr(a, opt)
        if v:
            r = parse_ranges(v)
            if len(r) != 1:
                raise ValueError(f"--{opt.replace('_', '-')}: expected LO:HI")
            kw[key] = r[0]
    kw.update(prominence=a.prominence, max_peaks=a.max_peaks, shape=a.shape)
    if a.area:
        kw["areas"] = parse_ranges(a.area)
    return kw


def run_analyze(a):
    """Analyse every selected series of ``a.data``; returns [(Analysis, files)]."""
    from .analysis import analyze, load_series, write
    out = a.out or (Path(a.data).stem + "_analysis")
    kw = analyze_options(a)
    res = []
    series = load_series(a.data, x=a.x, y=a.y, series=a.series)
    for name, x, y in series:
        an = analyze(x, y, name=name, **kw)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        base = os.path.join(out, safe) if len(series) > 1 or os.path.isdir(out) else out
        files = write(an, base, template=a.template, formats=_formats(a.formats), width=a.width,
                      xlabel=a.xlabel, ylabel=a.ylabel)
        res.append((an, files))
    return res


def cmd_analyze(a):
    from .analysis import summary_lines
    for an, files in run_analyze(a):
        print("\n".join(summary_lines(an)))
        print("  files: " + ", ".join(str(v) if not isinstance(v, list) else ", ".join(v) for v in files.values()))


# ───────────────────────────── fit ─────────────────────────────
def fit_inputs(a):
    """(expression, Param list, derived dict, x range) from the parsed ``fit`` options."""
    from .curvefit import merge_params, model_for, parse_derived, parse_params, preset_bounds
    expr, derived = model_for(a.model)
    params = merge_params(preset_bounds(a.model), parse_params(a.p0, a.bounds, a.fix))
    derived.update(parse_derived(a.derived))
    rng = None
    if a.range:
        from .analysis import parse_ranges
        r = parse_ranges(a.range)
        if len(r) != 1:
            raise ValueError("--range: expected LO:HI")
        rng = r[0]
    return expr, params, derived, rng


def load_fit_series(a):
    """[(name, x, y, sigma or None)] for ``fit``."""
    from .plot.engine import read_table
    from .analysis import load_series
    out = []
    tab = read_table(a.data)
    long = "series" in tab and "x" in tab and "y" in tab and a.x in (None, "x") and a.y in (None, "y")
    for name, x, y in load_series(a.data, x=a.x, y=a.y, series=a.series):
        sig = None
        if a.sigma:
            if long and a.sigma in ("errors", "yerr"):
                m = np.array([str(v) == name for v in tab["series"]])
                lo = tab.get("yerr_minus", tab.get("yerr_lo"))
                hi = tab.get("yerr_plus", tab.get("yerr_hi"))
                if lo is None or hi is None:
                    raise ValueError("--sigma errors: the file has no yerr_minus/yerr_plus columns")
                sig = 0.5 * (np.asarray(lo[m], float) + np.asarray(hi[m], float))
            elif a.sigma in tab:
                sig = np.asarray(tab[a.sigma], float)
            else:
                raise ValueError(f"--sigma: no column '{a.sigma}' (columns: {', '.join(tab)})")
        out.append((name, x, y, sig))
    return out


def run_fit(a):
    """Fit every selected series; returns (results, files) with results = [(name, outcome, x, y)]."""
    from .curvefit import fit, write
    expr, params, derived, rng = fit_inputs(a)
    results = []
    for name, x, y, sig in load_fit_series(a):
        import copy
        r = fit(x, y, expr, copy.deepcopy(params), x_range=rng, sigma=sig, derived=derived, n_starts=a.starts,
                absolute_sigma=a.absolute_sigma)
        results.append((name, r, x, y))
    out = a.out or (Path(a.data).stem + "_fit")
    files = write(results, out, template=a.template, formats=_formats(a.formats), width=a.width,
                  xlabel=a.xlabel, ylabel=a.ylabel, xscale=a.xscale, yscale=a.yscale)
    return results, files


def cmd_fit(a):
    from .curvefit import PRESETS, summary_lines
    if a.list_models:
        for k, (e, d, der) in PRESETS.items():
            print(f"{k:14s} {e:55s} {d}" + (f"  [derived: {', '.join(der)}]" if der else ""))
        return 0
    if not a.data:
        print("resrijan fit: give a data file (or --list-models)", file=sys.stderr)
        return 2
    results, files = run_fit(a)
    for name, r, _, _ in results:
        print("\n".join(summary_lines(name, r)))
        if r.at_bounds:
            print(f"  note: {', '.join(r.at_bounds)} ended at a bound – widen it or check the model")
    print("files: " + ", ".join(str(v) if not isinstance(v, list) else ", ".join(v) for v in files.values()))


# ───────────────────────────── compose ─────────────────────────────
def run_compose(a):
    from .plot.engine import compose
    return compose(a.spec, a.out, _formats(a.formats) if a.formats else None)


def cmd_compose(a):
    print("\n".join(run_compose(a)))


# ───────────────────────────── templates ─────────────────────────────
def template_summary(t) -> str:
    w = ", ".join(f"{k} {v:g} mm" for k, v in t.widths_mm.items())
    return (f"{t.key:13s} {t.name:34s} {w}; max height {t.max_height_mm:g} mm; "
            f"{t.font['names'][0]} {t.font['tick']}–{t.font['label']} pt; panel label "
            f"'{t.label(0)}'  [font used here: {t.resolved_font()}]")


def cmd_templates(a):
    from .plot.templates import available
    for t in available():
        print(template_summary(t))


# ───────────────────────────── inspect ─────────────────────────────
def page_info(pg) -> dict:
    from .io.loader import embedded_images
    info = {"page": pg.index + 1, "kind": pg.kind, "size_px": [pg.width, pg.height], "scale_px_per_pt": pg.scale}
    if pg.pdf_page is not None:
        info["vector_paths"] = len(pg.pdf_page.get_drawings())
        info["text_chars"] = len(pg.pdf_page.get_text("text"))
        info["embedded_images"] = [{"size": list(im["rgb"].shape[:2][::-1]), "rect_pt": [round(v, 1) for v in im["rect"]],
                                    "dpi": round(im["native_dpi"])} for im in embedded_images(pg)]
    return info


def run_inspect(a):
    """Page information and a pixel-ruler PNG per page; returns [(info, ruler_path)]."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .io.loader import load
    pages = load(a.file, pages=[int(a.page) - 1] if a.page else None, dpi=a.dpi)
    res = []
    for pg in pages:
        info = page_info(pg)
        out = (a.out or Path(a.file).stem) + f"_p{pg.index + 1}_ruler.png"
        if os.path.dirname(out):
            os.makedirs(os.path.dirname(out), exist_ok=True)
        h, w = pg.rgb.shape[:2]
        fig, ax = plt.subplots(figsize=(10, 10 * h / w), dpi=150)
        ax.imshow(pg.rgb, interpolation="none")
        ax.minorticks_on()
        ax.grid(which="major", color="r", lw=0.3, alpha=0.6)
        ax.grid(which="minor", color="r", lw=0.15, alpha=0.3)
        ax.tick_params(labelsize=6)
        fig.savefig(out, bbox_inches="tight")
        plt.close(fig)
        res.append((info, out))
    return res


def cmd_inspect(a):
    for info, out in run_inspect(a):
        print(json.dumps(info))
        print("pixel ruler:", out)


# ───────────────────────────── pick ─────────────────────────────
def calibration_string(pairs) -> str:
    """``[(pixel, value), …]`` → the 'px:value,px:value' string of --xcal/--ycal."""
    return ",".join(f"{px:.2f}:{float(v):g}" for px, v in pairs)


def cmd_pick(a):
    import matplotlib.pyplot as plt
    from .io.loader import load
    pg = load(a.file, pages=[int(a.page) - 1] if a.page else None, dpi=a.dpi)[0]
    plt.imshow(pg.rgb)
    res = {}
    for ax in ("x", "y"):
        plt.title(f"Click two (or more) {ax}-ticks, then press Enter")
        pts = plt.ginput(n=-1, timeout=0)
        pairs = []
        for (px, py) in pts:
            v = input(f"  value of the {ax}-tick at ({px:.1f}, {py:.1f}): ")
            pairs.append((px if ax == "x" else py, float(v)))
        res[ax] = calibration_string(pairs)
    print(f"\n  --xcal \"{res['x']}\" --ycal \"{res['y']}\"")


# ───────────────────────────── gui ─────────────────────────────
def cmd_gui(a):
    from .gui import main as gui_main
    return gui_main([a.file] if a.file else [])


# ───────────────────────────── doctor ─────────────────────────────
def doctor_checks(gui: bool = True):
    """[(name, ok, detail)] – what ReSrijan needs, and whether it works here."""
    import importlib
    import platform
    import shutil
    out = [("python", True, f"{platform.python_version()} ({sys.executable})"),
           ("system", True, platform.platform()), ("resrijan", True, f"{__version__} ({Path(__file__).parent})")]
    for mod, attr in (("numpy", "__version__"), ("scipy", "__version__"), ("matplotlib", "__version__"),
                      ("cv2", "__version__"), ("skimage", "__version__"), ("sklearn", "__version__"),
                      ("fitz", "VersionBind"), ("PIL", "__version__"), ("yaml", "__version__"),
                      ("pytesseract", "__version__")):
        try:
            m = importlib.import_module(mod)
            out.append((mod, True, str(getattr(m, attr, "ok"))))
        except Exception as exc:  # noqa: BLE001
            out.append((mod, False, f"{type(exc).__name__}: {exc}"))
    try:
        import pytesseract
        out.append(("tesseract (OCR)", True, str(pytesseract.get_tesseract_version()).splitlines()[0]))
    except Exception as exc:  # noqa: BLE001
        out.append(("tesseract (OCR)", False, f"{exc} – bitmaps without vector text cannot be read"))
    gs = next((shutil.which(n) for n in ("gs", "gswin64c", "gswin32c") if shutil.which(n)), None)
    out.append(("ghostscript (EPS/PS)", bool(gs), gs or "not found – EPS and PS input will not work"))
    rs = shutil.which("rsvg-convert")
    out.append(("rsvg-convert (SVG clips)", True, rs or "not found – optional (SVGs are read with MuPDF)"))
    if gui:
        try:
            import os
            os.environ.setdefault("MPLBACKEND", "Agg")
            from PySide6 import __version__ as pv
            from PySide6.QtWidgets import QApplication, QLabel
            from PySide6.QtCore import QTimer
            app = QApplication.instance() or QApplication([sys.argv[0]])
            w = QLabel("ReSrijan doctor")
            w.show()
            QTimer.singleShot(300, app.quit)
            app.exec()
            w.close()
            out.append(("GUI (PySide6/Qt)", True, f"PySide6 {pv}, platform '{app.platformName()}', window opened"))
        except Exception as exc:  # noqa: BLE001
            out.append(("GUI (PySide6/Qt)", False, f"{type(exc).__name__}: {exc}"))
    return out


def cmd_doctor(a):
    bad = 0
    for name, ok, detail in doctor_checks(gui=not a.no_gui):
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {name:26s} {detail}")
    print("\nEverything needed works." if not bad else f"\n{bad} problem(s) – see FAIL above.")
    return 1 if bad else 0


# ───────────────────────────── parser ─────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="resrijan", description="ReSrijan – literature figure digitiser and journal figure engine")
    ap.add_argument("--version", action="version", version=f"resrijan {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("digitize", aliases=["digitise", "extract"], help="extract data from a figure file (PDF, EPS, PS, SVG, PNG, JPG, TIFF …)")
    d.add_argument("file")
    d.add_argument("-o", "--out", help="output folder (default: <file>_resrijan)")
    d.add_argument("--page", help="page number(s), 1-based, comma separated (default: all)")
    d.add_argument("--region", help="crop x0,y0,x1,y1 in pixels or 0–1 page fractions")
    d.add_argument("--dpi", type=float, default=600, help="render resolution for PDF/EPS/PS (default 600)")
    d.add_argument("--type", default="auto", choices=DIGITIZE_TYPES)
    d.add_argument("--xscale", default="auto", choices=SCALES)
    d.add_argument("--yscale", default="auto", choices=SCALES)
    d.add_argument("--xcal", help="manual x calibration 'px:value,px:value' (rendered-image pixels)")
    d.add_argument("--ycal", help="manual y calibration 'px:value,px:value'")
    d.add_argument("--scale", help="micrograph scale override, e.g. '100=50 nm' (pixels=value unit)")
    d.add_argument("--prefer", default="auto", choices=PREFER)
    d.add_argument("--max-series", type=int, default=12)
    d.add_argument("--no-particles", action="store_true", help="skip particle analysis for micrographs")
    d.add_argument("-t", "--template", default="natchem", help="journal template for replots")
    d.add_argument("--width", default="single", help="replot width: single|onehalf|double|<mm>")
    d.add_argument("-f", "--formats", default="pdf,svg,png", help="replot formats: pdf,svg,eps,png,tiff")
    d.add_argument("--xlabel", help="x-axis title for the replot (overrides what was read)")
    d.add_argument("--ylabel", help="y-axis title for the replot, e.g. 'C(t)' or 'k (s$^{-1}$)'")
    d.add_argument("--label-color", help="colour of the replot's axis titles, e.g. navy or '#1f3a93' (default: as read)")
    d.add_argument("-v", "--verbose", action="store_true")
    d.add_argument("--strict", action="store_true", help="exit 1 if any panel has errors")
    d.set_defaults(fn=cmd_digitize)

    p = sub.add_parser("plot", help="plot a data file with a journal template")
    p.add_argument("data")
    p.add_argument("--kind", default="line", choices=PLOT_KINDS)
    p.add_argument("-x"); p.add_argument("-y", help="column(s), comma separated")
    p.add_argument("--yerr", help="error column(s)")
    p.add_argument("--xlabel"); p.add_argument("--ylabel"); p.add_argument("--clabel")
    p.add_argument("--xscale"); p.add_argument("--yscale"); p.add_argument("--xlim"); p.add_argument("--ylim")
    p.add_argument("--cmap"); p.add_argument("--column", help="column for histograms")
    p.add_argument("--nm-per-px", type=float, help="image pixel size for a scale bar")
    p.add_argument("--colors", help="series colours in order, comma separated, e.g. '#1b9e77,,navy' (empty: the template's palette)")
    p.add_argument("--label-color", help="colour of the axis and colour-bar titles")
    add_style_args(p)
    p.add_argument("-t", "--template", default="natchem")
    p.add_argument("--width", default="single")
    p.add_argument("-o", "--out")
    p.add_argument("-f", "--formats", default="pdf,svg,png")
    p.set_defaults(fn=cmd_plot)

    n = sub.add_parser("analyze", aliases=["analyse"], help="baseline, smoothing, normalisation, unit conversion, peak fitting, areas")
    n.add_argument("data", help="table (CSV/TSV/text) – e.g. a digitised *_data.csv")
    n.add_argument("-x", help="x column (default: the first, or 'x' in ReSrijan data files)")
    n.add_argument("-y", help="y column(s), comma separated (default: all)")
    n.add_argument("--series", help="analyse only this series (name in a ReSrijan data file, or a y column)")
    n.add_argument("--convert", help="x unit conversion FROM:TO among nm, um, cm-1, eV, THz, e.g. nm:eV")
    n.add_argument("--jacobian", action="store_true", help="with --convert: scale intensities by |dλ/dE| (spectral densities)")
    n.add_argument("--crop", help="keep x between LO:HI (after conversion)")
    n.add_argument("--smooth", help="savgol[:window[:order]] or mean[:window], e.g. savgol:11:3")
    n.add_argument("--baseline", help="als[:lambda[:p]], poly[:order], ends or none (e.g. als:1e5:0.01)")
    n.add_argument("--normalize", "--normalise", choices=["max", "area", "minmax", "none"])
    n.add_argument("--peaks", help="'auto' (maxima), 'shoulders' (second derivative: also hidden bands) "
                   "or starting positions, e.g. 1450,1600")
    n.add_argument("--components", type=int, help="deconvolve into exactly N components (positions from the "
                   "second derivative, gaps filled)")
    n.add_argument("--center-window", type=float, help="each peak centre may move at most this far from its start")
    n.add_argument("--fwhm-range", help="limits for every peak width, LO:HI")
    n.add_argument("--fit-range", help="fit peaks only over LO:HI (the rest is kept and shown)")
    n.add_argument("--shape", default="voigt", choices=["gauss", "lorentz", "voigt"], help="peak shape (default: pseudo-Voigt)")
    n.add_argument("--prominence", type=float, default=0.05, help="with --peaks auto: minimum prominence as a fraction of the range")
    n.add_argument("--max-peaks", type=int, default=10)
    n.add_argument("--area", help="integrate over LO:HI ranges, comma separated, e.g. 400:500,600:700")
    n.add_argument("--xlabel"); n.add_argument("--ylabel")
    n.add_argument("-t", "--template", default="natchem")
    n.add_argument("--width", default="single")
    n.add_argument("-o", "--out", help="output base name or folder (default: <data>_analysis)")
    n.add_argument("-f", "--formats", default="pdf,svg,png")
    n.set_defaults(fn=cmd_analyze)

    q = sub.add_parser("fit", help="non-linear fit of any formula (or a preset) with bounds and a fit range")
    q.add_argument("data", nargs="?", help="table (CSV/TSV/text) – e.g. a correlation function or an MSD")
    q.add_argument("-x", help="x column (default: the first)")
    q.add_argument("-y", help="y column(s), comma separated (default: all) – each is fitted separately")
    q.add_argument("--series", help="fit only this series (ReSrijan data file) or y column")
    q.add_argument("-m", "--model", default="exp1",
                   help="a preset (see --list-models) or a formula in x, e.g. 'A*exp(-(x/tau)**beta) + C'")
    q.add_argument("--p0", help="starting values, e.g. 'A=1,tau=10' (others are guessed)")
    q.add_argument("--bounds", help="limits LO:HI, e.g. 'tau=0:1e4,beta=0:1,C=:0' (an empty side is open)")
    q.add_argument("--fix", help="fixed values, e.g. 'C=0'")
    q.add_argument("--range", help="fit only x between LO:HI (the figure still shows all data)")
    q.add_argument("--derived", help="quantities from the parameters, ';' separated, e.g. 'tau_avg=tau/beta*gamma(1/beta)'")
    q.add_argument("--sigma", help="y uncertainty column used as weights ('errors' for ReSrijan data files)")
    q.add_argument("--absolute-sigma", action="store_true", help="treat --sigma as absolute (no rescaling by χ²)")
    q.add_argument("--starts", type=int, default=12, help="number of starting points tried (default 12)")
    q.add_argument("--xscale", choices=["linear", "log"]); q.add_argument("--yscale", choices=["linear", "log"])
    q.add_argument("--xlabel"); q.add_argument("--ylabel")
    q.add_argument("--list-models", action="store_true", help="list the preset models and exit")
    q.add_argument("-t", "--template", default="natchem")
    q.add_argument("--width", default="single")
    q.add_argument("-o", "--out", help="output base name (default: <data>_fit)")
    q.add_argument("-f", "--formats", default="pdf,svg,png")
    q.set_defaults(fn=cmd_fit)

    c = sub.add_parser("compose", help="multi-panel figure from a YAML spec")
    c.add_argument("spec"); c.add_argument("-o", "--out"); c.add_argument("-f", "--formats")
    c.set_defaults(fn=cmd_compose)

    t = sub.add_parser("templates", help="list journal templates")
    t.set_defaults(fn=cmd_templates)

    i = sub.add_parser("inspect", help="file info + pixel ruler image")
    i.add_argument("file"); i.add_argument("--page"); i.add_argument("--dpi", type=float, default=600); i.add_argument("-o", "--out")
    i.set_defaults(fn=cmd_inspect)

    k = sub.add_parser("pick", help="click tick marks to build manual calibrations (GUI)")
    k.add_argument("file"); k.add_argument("--page"); k.add_argument("--dpi", type=float, default=600)
    k.set_defaults(fn=cmd_pick)

    dr = sub.add_parser("doctor", help="check the installation (libraries, OCR, Ghostscript, the GUI)")
    dr.add_argument("--no-gui", action="store_true", help="skip opening a test window")
    dr.set_defaults(fn=cmd_doctor)

    g = sub.add_parser("gui", help="open the graphical interface (pip install \"resrijan[gui]\")")
    g.add_argument("file", nargs="?", help="figure or data file to open")
    g.set_defaults(fn=cmd_gui)
    return ap


def add_style_args(p):
    g = p.add_argument_group("style")
    g.add_argument("--linestyles", help="per series: solid, dashed, dotted, dashdot or none, comma separated")
    g.add_argument("--markers", help="per series: circle, square, triangle, down, diamond, star, cross, none … (or matplotlib codes)")
    g.add_argument("--linewidth", type=float, help="line width in points (all series)")
    g.add_argument("--markersize", type=float, help="marker size in points (all series)")
    g.add_argument("--legend", help="legend position: best, upper right, … , outside right, outside top, none")
    g.add_argument("--legend-frame", action="store_true", help="draw a frame around the legend")
    g.add_argument("--legend-cols", type=int, help="number of legend columns")
    g.add_argument("--grid", action="store_true", help="light dashed grid")
    g.add_argument("--font", help="font family, e.g. Arial, Helvetica, 'Times New Roman' (default: the journal's)")
    g.add_argument("--font-scale", type=float, help="scale all text sizes, e.g. 1.2")
    g.add_argument("--line-scale", type=float, help="scale line widths and marker sizes, e.g. 1.5")
    g.add_argument("--text", action="append", help="text label 'x,y,text' in data units (or 'axes:x,y,text'); "
                   "add '|colour' for colour; repeatable")
    g.add_argument("--arrow", action="append", help="arrow 'x0,y0,x1,y1[,text]' from (x0,y0) to (x1,y1); repeatable")


def _check_style(ap, a):
    from .plot.engine import LEGEND_LOCS
    if getattr(a, "legend", None) and a.legend not in LEGEND_LOCS:
        ap.error(f"--legend: '{a.legend}' is not one of: " + ", ".join(LEGEND_LOCS))
    for t in getattr(a, "text", None) or []:
        try:
            parse_text(t)
        except ValueError as exc:
            ap.error(str(exc))
    for t in getattr(a, "arrow", None) or []:
        try:
            parse_arrow(t)
        except ValueError as exc:
            ap.error(str(exc))
    if a.cmd == "fit" and not a.list_models:
        try:
            from .curvefit import parse_model
            expr, params, derived, _ = fit_inputs(a)
            _, names = parse_model(expr)
            extra = [p.name for p in params if p.name not in names]
            if extra:
                raise ValueError(f"not in the model: {', '.join(extra)} (parameters: {', '.join(names)})")
        except ValueError as exc:
            ap.error(str(exc))
    if a.cmd in ("analyze", "analyse"):
        try:
            analyze_options(a)
        except (ValueError, IndexError) as exc:
            ap.error(str(exc))


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    _check_colors(ap, a)
    _check_style(ap, a)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
