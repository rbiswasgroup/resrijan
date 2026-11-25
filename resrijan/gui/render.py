"""Figure → PNG bytes for previews (runs in worker threads; matplotlib uses the Agg backend)."""
from __future__ import annotations

import io

import numpy as np


def figure_png(fig, dpi: float = 160) -> bytes:
    import matplotlib.pyplot as plt
    tpl = getattr(fig, "_resrijan_template", None)
    buf = io.BytesIO()
    with plt.rc_context(tpl.rc() if tpl else {}):
        fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    return buf.getvalue()


def plot_preview(args, dpi: float = 160) -> bytes:
    """Preview of `resrijan plot …` (parsed args) without writing files."""
    from ..cli import figure_style, plot_spec
    from ..plot.engine import figure
    fig, _, _ = figure([plot_spec(args)], template=args.template, width=args.width, labels=False,
                       style=figure_style(args))
    return figure_png(fig, dpi)


def analysis_preview(args, dpi: float = 160):
    """Analyse the first selected series of `resrijan analyze …` (parsed args) without writing files.
    Returns (png, Analysis, (plot-area left px, right px, x at left, x at right))."""
    from ..analysis import analysis_figure, analyze, load_series
    from ..cli import analyze_options
    name, x, y = load_series(args.data, x=args.x, y=args.y, series=args.series)[0]
    an = analyze(x, y, name=name, **analyze_options(args))
    fig = analysis_figure(an, template=args.template, width=args.width, xlabel=args.xlabel, ylabel=args.ylabel)
    fig.canvas.draw()
    ax = fig.axes[0]
    bb, k = ax.get_window_extent(), dpi / fig.dpi
    lo, hi = ax.get_xlim()
    return figure_png(fig, dpi), an, (bb.x0 * k, bb.x1 * k, lo, hi)


def fit_preview(args, dpi: float = 160):
    """Fit every selected series of `resrijan fit …` (parsed args) without writing files.
    Returns (png, results, (plot-area left px, right px, x at left, x at right, log x))."""
    import copy
    from ..cli import fit_inputs, load_fit_series
    from ..curvefit import fit, fit_figure
    expr, params, derived, rng = fit_inputs(args)
    results = []
    for name, x, y, sig in load_fit_series(args):
        r = fit(x, y, expr, copy.deepcopy(params), x_range=rng, sigma=sig, derived=derived, n_starts=args.starts,
                absolute_sigma=args.absolute_sigma)
        results.append((name, r, x, y))
    fig = fit_figure(results, template=args.template, width=args.width, xlabel=args.xlabel, ylabel=args.ylabel,
                     xscale=args.xscale, yscale=args.yscale)
    fig.canvas.draw()
    ax = fig.axes[0]
    bb, k = ax.get_window_extent(), dpi / fig.dpi
    lo, hi = ax.get_xlim()
    return figure_png(fig, dpi), results, (bb.x0 * k, bb.x1 * k, lo, hi, args.xscale == "log")


def compose_preview(spec: dict, base: str, dpi: float = 130) -> bytes:
    """Preview of a compose YAML spec (already parsed) without writing files."""
    from ..plot.engine import figure
    figspec = spec.get("figure", {}) or {}
    fig, _, _ = figure(spec["panels"], template=figspec.get("template", "natchem"),
                       width=figspec.get("width", "double"), height=figspec.get("height"),
                       labels=figspec.get("labels", True), rows=figspec.get("rows"), base=base,
                       style={k: figspec[k] for k in ("font", "font_scale", "line_scale") if k in figspec})
    return figure_png(fig, dpi)


def template_sample(template: str, dpi: float = 150) -> bytes:
    """A small two-panel figure (lines + symbols with error bars) drawn with ``template``."""
    from ..plot.engine import figure
    x = np.linspace(0, 10, 200)
    xs = np.arange(1, 10)
    rng = np.random.default_rng(3)
    lines = {"type": "line", "xlabel": "Time (ps)", "ylabel": "Signal (a.u.)",
             "series": [{"x": x, "y": np.exp(-x / 4) * np.cos(1.3 * x), "label": "damped"},
                        {"x": x, "y": 0.6 * np.exp(-((x - 6) / 1.2) ** 2) - 0.3, "label": "gauss"},
                        {"x": x, "y": 0.5 * np.tanh(x - 3) - 0.1, "label": "step"}]}
    pts = {"type": "scatter", "xlabel": "T (K)", "ylabel": "k (s$^{-1}$)",
           "series": [{"x": 280 + 10 * xs, "y": 0.4 * xs + rng.normal(0, 0.2, xs.size), "yerr": 0.2 + 0 * xs,
                       "label": "sample A", "kind": "markers"},
                      {"x": 280 + 10 * xs, "y": 0.25 * xs + 0.5 + rng.normal(0, 0.2, xs.size), "yerr": 0.25 + 0 * xs,
                       "label": "sample B", "kind": "markers"}]}
    fig, _, _ = figure([lines, pts], template=template, width="double", labels=True)
    return figure_png(fig, dpi)


def preview_pages(path: str, dpi: float):
    """Low-resolution pages of a figure file for the Digitize preview.
    Returns [(index, rgb, kind, scale)] – ``scale`` is pixels per PDF point (1 for bitmaps)."""
    from ..io.loader import load
    return [(pg.index, pg.rgb, pg.kind, pg.scale) for pg in load(path, dpi=dpi)]
