"""Command-line interface:  resrijan <command> ...

  digitize  FILE      extract data from figures (PDF/EPS/PS/SVG/PNG/JPG/TIFF) and replot them
  plot      DATA      plot a data file with a journal template
  compose   SPEC.yaml build a multi-panel figure from a YAML description
  templates           list journal templates
  inspect   FILE      show pages, embedded images and a pixel-ruler image (for manual calibration)
  pick      FILE      click ticks to build --xcal/--ycal strings (needs a display)
  gui                 open the graphical interface (needs: pip install "resrijan[gui]")

Each command is split into ``run_*`` (does the work, returns results) and ``cmd_*`` (prints
them). The GUI builds the same command line, parses it with :func:`build_parser` and calls
the same ``run_*`` functions, so both always behave identically.
"""
from __future__ import annotations

import argparse
import json
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
    return spec


def run_plot(a):
    """Plot ``a.data``; returns the list of files written."""
    import matplotlib.pyplot as plt
    from .plot.engine import figure, save
    fig, _, _ = figure([plot_spec(a)], template=a.template, width=a.width, labels=False)
    out = a.out or Path(a.data).stem + "_plot"
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    files = save(fig, out, _formats(a.formats))
    plt.close(fig)
    return files


def cmd_plot(a):
    print("\n".join(run_plot(a)))


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
    p.add_argument("-t", "--template", default="natchem")
    p.add_argument("--width", default="single")
    p.add_argument("-o", "--out")
    p.add_argument("-f", "--formats", default="pdf,svg,png")
    p.set_defaults(fn=cmd_plot)

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

    g = sub.add_parser("gui", help="open the graphical interface (pip install \"resrijan[gui]\")")
    g.add_argument("file", nargs="?", help="figure or data file to open")
    g.set_defaults(fn=cmd_gui)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
