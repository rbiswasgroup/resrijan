"""Journal-grade plotting: panels from data, auto-arranged into one figure.

A figure is described by a list of panel specs (dicts, or a YAML file for the CLI).
Every panel type reads plain data files (CSV/TSV/NPZ/TIFF/PNG) or in-memory arrays.
"""
from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np
import matplotlib
matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
import matplotlib.pyplot as plt
from matplotlib import ticker
from matplotlib.gridspec import GridSpec

from . import templates as T
from .layout import auto_layout

MM = 1 / 25.4
DEFAULT_ASPECT = {"line": 1.33, "scatter": 1.33, "errorbar": 1.33, "bar": 1.33, "hist": 1.33,
                  "heatmap": 1.18, "contourf": 1.18, "contour": 1.18, "image": 1.0, "spectrum2d": 1.18}


# ───────────────────────────── data loading ─────────────────────────────
def read_table(path: str, delimiter: Optional[str] = None) -> Dict[str, np.ndarray]:
    """Read CSV/TSV/whitespace tables with a header row into {column: array}.

    Long-format files with a 'series' column are kept as strings in that column.
    Lines starting with '#' are comments.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        raise ValueError(f"{path}: empty table")
    if delimiter is None:
        head = lines[0]
        delimiter = "," if "," in head else ("\t" if "\t" in head else None)
    rows = list(csv.reader(lines, delimiter=delimiter)) if delimiter else [l.split() for l in lines]
    header = [h.strip() for h in rows[0]]
    try:
        [float(v) for v in header]
        numeric_header = True
    except ValueError:
        numeric_header = False
    if numeric_header:  # headerless numeric file
        header = [f"c{i}" for i in range(len(rows[0]))]
        body = rows
    else:
        body = rows[1:]
    cols = {h: [] for h in header}
    for r in body:
        for h, v in zip(header, r):
            cols[h].append(v.strip())
    out = {}
    for h, v in cols.items():
        try:
            out[h] = np.array([float(x) if x not in ("", "nan", "NaN") else np.nan for x in v])
        except ValueError:
            out[h] = np.array(v, dtype=object)
    return out


def read_grid(path: str):
    """Matrix file: first row = x values, first column = y values (corner ignored), or .npz."""
    if str(path).endswith(".npz"):
        d = np.load(path)
        return d["x"], d["y"], d["z"]
    arr = np.genfromtxt(path, delimiter="," if open(path, encoding="utf-8", errors="replace").readline().count(",") else None, comments="#")
    x = arr[0, 1:]
    y = arr[1:, 0]
    z = arr[1:, 1:]
    return x, y, z


def read_image(path: str) -> np.ndarray:
    from PIL import Image
    im = Image.open(path)
    a = np.asarray(im)
    return a


def _resolve(spec: dict, base: str) -> dict:
    s = dict(spec)
    if isinstance(s.get("data"), str) and not os.path.isabs(s["data"]):
        s["data"] = os.path.join(base, s["data"])
    return s


# ───────────────────────────── panel drawing ─────────────────────────────
def _series_from_spec(spec: dict):
    """Return list of dicts {x, y, yerr, xerr, label} from a line/scatter spec."""
    out = []
    if "series" in spec:          # in-memory
        for s in spec["series"]:
            out.append(dict(s))
        return out
    data = spec.get("data")
    tab = read_table(data) if isinstance(data, str) else data
    if "series" in tab and spec.get("x") in (None, "x") and "x" in tab:
        names = list(dict.fromkeys(tab["series"].tolist()))
        for n in names:
            m = tab["series"] == n
            d = {"x": tab["x"][m].astype(float), "y": tab["y"][m].astype(float), "label": str(n)}
            if "kind" in tab and str(tab["kind"][m][0]) in ("markers", "line"):
                d["kind"] = str(tab["kind"][m][0])
            for e, k in (("yerr_lo", "yerr_lo"), ("yerr_hi", "yerr_hi"), ("yerr_minus", "yerr_lo"), ("yerr_plus", "yerr_hi")):
                if e in tab:
                    d[k] = tab[e][m].astype(float)
            if "yerr" in tab:
                d["yerr"] = tab["yerr"][m].astype(float)
            out.append(d)
        return out
    keys = list(tab.keys())
    xk = spec.get("x", keys[0])
    yks = spec.get("y", [k for k in keys if k != xk])
    if isinstance(yks, str):
        yks = [yks] if yks != "all" else [k for k in keys if k != xk]
    yerrs = spec.get("yerr")
    if isinstance(yerrs, str):
        yerrs = [yerrs]
    labels = spec.get("labels", yks)
    for i, yk in enumerate(yks):
        d = {"x": np.asarray(tab[xk], float), "y": np.asarray(tab[yk], float), "label": labels[i] if i < len(labels) else yk}
        if yerrs and i < len(yerrs) and yerrs[i]:
            d["yerr"] = np.asarray(tab[yerrs[i]], float)
        out.append(d)
    return out


def _nice_scalebar(span_nm: float):
    target = span_nm * 0.22
    e = 10 ** np.floor(np.log10(target))
    for m in (5, 2, 1):
        if m * e <= target:
            v = m * e
            break
    if v >= 1000:
        return v, f"{v / 1000:g} µm", v
    if v < 1:
        return v, f"{v * 10:g} Å", v
    return v, f"{v:g} nm", v


def draw_panel(ax, spec: dict, tpl: T.Template, base: str = ".") -> Optional[Any]:
    spec = _resolve(spec, base)
    typ = spec.get("type", "line")
    L = tpl.lines
    ret = None
    if typ in ("line", "scatter", "errorbar"):
        series = _series_from_spec(spec)
        style = spec.get("style", {})
        ax_pt = _axes_width_pt(ax)
        for k, s in enumerate(series):
            s = _user_style(s, spec, k, typ)
            col = _pick_color(spec.get("colors"), k) or s.get("color") or tpl.palette[k % len(tpl.palette)]
            kind = s.get("kind") or ("markers" if typ == "scatter" else "line")
            x, y = np.asarray(s["x"], float), np.asarray(s["y"], float)
            if spec.get("sort", kind == "line" and s.get("sort", True)) and kind == "line":
                o = np.argsort(x, kind="stable")
                if np.mean(np.diff(x) < 0) < 0.05 or np.mean(np.diff(x) > 0) < 0.05:
                    pass  # already monotonic one way – keep drawing order
                else:
                    x, y = x[o], y[o]
            yerr = None
            if "yerr" in s:
                yerr = np.asarray(s["yerr"], float)
            elif "yerr_lo" in s and "yerr_hi" in s:
                yerr = np.vstack([np.asarray(s["yerr_lo"], float), np.asarray(s["yerr_hi"], float)])
                if np.all(~np.isfinite(yerr)):
                    yerr = None
            ls = s.get("linestyle", style.get("linestyle", "--" if s.get("dashed") else "-"))
            if kind == "markers" or typ == "scatter" or yerr is not None or s.get("markers_and_line"):
                marker = s.get("marker", style.get("marker", "osD^v<>ph"[k % 9]))
                ms = L["markersize"] * (1.15 if s.get("mec") else 1)
                if s.get("ms"):
                    ms = float(s["ms"])
                elif s.get("ms_frac"):          # the source's marker size relative to the plot width
                    ms = float(np.clip(s["ms_frac"] * ax_pt, 0.5 * ms, 4.0 * ms))
                mew = float(np.clip(s["mew_frac"] * ax_pt, 0.3, 3.0)) if s.get("mew_frac") else 0.6
                ax.errorbar(x, y, yerr=yerr, fmt=marker, color=col, ms=ms,
                            mfc=s.get("mfc", col), mec=s.get("mec", col), mew=mew, elinewidth=L["errorbar_lw"],
                            capsize=L["capsize"], capthick=L["errorbar_lw"], label=s.get("label"),
                            ls=ls if (kind == "line" and typ != "scatter") else "none", lw=s.get("lw", L["linewidth"]))
            else:
                lw = s.get("lw", L["linewidth"])
                if s.get("lw_frac") and "lw" not in s:
                    lw = float(np.clip(s["lw_frac"] * ax_pt, 0.4 * lw, 3.0 * lw))
                ax.plot(x, y, color=col, lw=lw, ls=s.get("linestyle", ls), label=s.get("label"))
        if spec.get("hlines"):
            for v in spec["hlines"]:
                ax.axhline(v, color="0.55", lw=0.5, ls=(0, (2, 2)), zorder=0)
        _legend(ax, spec, len(series) > 1)
    elif typ in ("heatmap", "contourf", "contour", "spectrum2d"):
        if "z" in spec:
            x, y, z = np.asarray(spec["x"]), np.asarray(spec["y"]), np.asarray(spec["z"])
        else:
            x, y, z = read_grid(spec["data"])
        vmin, vmax = spec.get("vmin"), spec.get("vmax")
        diverging = spec.get("diverging", (np.nanmin(z) < 0 < np.nanmax(z)))
        cmap = spec.get("cmap", tpl.cmap.get("diverging" if diverging else "sequential", "viridis"))
        if diverging and vmin is None and vmax is None:
            m = np.nanmax(np.abs(z))
            vmin, vmax = -m, m
        if typ == "heatmap":
            ret = ax.pcolormesh(x, y, z, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto", rasterized=True)
            if spec.get("contour_lines") is not None:
                ax.contour(x, y, z, levels=spec["contour_lines"], colors=spec.get("line_color", "k"),
                           linewidths=0.4 * tpl.axes["linewidth"] / 0.5)
        else:
            levels = spec.get("levels", 15)
            if isinstance(levels, int) and diverging:
                # odd number of bands so the zero band straddles 0 (no speckle from noise near 0)
                nb = levels if levels % 2 == 1 else levels + 1
                levels = np.linspace(vmin, vmax, nb + 1)
            if typ in ("contourf", "spectrum2d"):
                ret = ax.contourf(x, y, z, levels=levels, cmap=cmap, vmin=vmin, vmax=vmax,
                                  extend=spec.get("extend", "neither"))
            if typ in ("contour", "spectrum2d") or spec.get("contour_lines"):
                cl = spec.get("contour_lines", levels if typ != "contourf" else None)
                if cl is not None:
                    cs = ax.contour(x, y, z, levels=cl, colors=spec.get("line_color", "k"),
                                    linewidths=0.4 * tpl.axes["linewidth"] / 0.5)
                    ret = ret or cs
        if spec.get("diagonal"):
            lo, hi = max(np.min(x), np.min(y)), min(np.max(x), np.max(y))
            ax.plot([lo, hi], [lo, hi], color="k", lw=0.5 * tpl.axes["linewidth"] / 0.5)
        if spec.get("aspect_equal"):
            ax.set_aspect("equal")
        if spec.get("colorbar", True) and ret is not None and hasattr(ret, "get_cmap"):
            cb = ax.figure.colorbar(ret, ax=ax, fraction=0.05, pad=0.03, aspect=22)
            cb.outline.set_linewidth(tpl.axes["linewidth"])
            lo_, hi_ = cb.mappable.get_clim() if hasattr(cb.mappable, "get_clim") else (None, None)
            if lo_ is not None and np.isfinite([lo_, hi_]).all():
                tv = ticker.MaxNLocator(5).tick_values(lo_, hi_)
                cb.set_ticks(tv[(tv >= lo_ - 1e-9 * abs(hi_ - lo_)) & (tv <= hi_ + 1e-9 * abs(hi_ - lo_))])
            cb.ax.tick_params(width=tpl.axes["tick_width"], length=0.7 * tpl.axes["tick_length"])
            if spec.get("clabel"):
                cb.set_label(spec["clabel"], **_title_kw(spec.get("clabel_style")))
    elif typ == "image":
        img = spec["z"] if "z" in spec else read_image(spec["data"])
        nm = spec.get("nm_per_px")
        crop = spec.get("crop")
        if crop:
            x0, y0, x1, y1 = crop
            img = img[y0:y1, x0:x1]
        cmap = spec.get("cmap", "gray") if img.ndim == 2 else None
        ax.imshow(img, cmap=cmap, interpolation="none", vmin=spec.get("vmin"), vmax=spec.get("vmax"))
        ax.set_axis_off()
        _image_extras(ax, spec, img, tpl)
        if nm and spec.get("scalebar", True):
            W = img.shape[1]
            span = W * nm
            val, txt, _ = _nice_scalebar(span) if spec.get("scalebar") in (True, None, "auto") else _parse_bar(spec["scalebar"])
            Lpx = val / nm
            H = img.shape[0]
            pad = 0.05 * W
            light = np.mean(img[int(H * 0.85):, int(W * 0.6):]) > 127 if img.ndim == 2 else np.mean(img[int(H * 0.85):, int(W * 0.6):]) > 127
            colr = "k" if light else "w"
            ybar = H - pad
            ax.plot([W - pad - Lpx, W - pad], [ybar, ybar], color=colr, lw=2.2 * tpl.axes["linewidth"] / 0.5 + 0.8,
                    solid_capstyle="butt")
            ax.text(W - pad - Lpx / 2, ybar - 0.025 * H, txt, color=colr, ha="center", va="bottom",
                    fontsize=tpl.font["label"])
    elif typ == "paths":
        if spec.get("fixed_aspect") and spec.get("aspect"):
            ax.set_box_aspect(1.0 / float(spec["aspect"]))
        for ln in spec.get("lines", []):
            xy = np.asarray(ln["xy"], float)
            ax.plot(xy[:, 0], xy[:, 1], color=ln.get("color", "k"), lw=0.6 * L["linewidth"] if not ln.get("overlay") else 0.6,
                    ls=(0, (3, 2)) if ln.get("dashed") else "-", zorder=3 if ln.get("overlay") else 2)
    elif typ == "hist":
        tab = read_table(spec["data"]) if isinstance(spec.get("data"), str) else spec.get("data", {})
        v = np.asarray(spec.get("values", tab.get(spec.get("column", "")) if tab else []), float)
        v = v[np.isfinite(v)]
        ax.hist(v, bins=spec.get("bins", "auto"), color=tpl.palette[0], edgecolor="white", lw=0.3)
        if spec.get("stats", True) and len(v):
            ax.text(0.97, 0.95, f"{np.mean(v):.3g} ± {np.std(v, ddof=1):.2g}\nn = {len(v)}", transform=ax.transAxes,
                    ha="right", va="top", fontsize=tpl.font["legend"])
    elif typ == "bar" and "values" in spec:
        cats = spec.get("categories") or [str(i + 1) for i in range(len(spec["values"]))]
        vals = np.asarray(spec["values"], float)
        cols = [_pick_color(spec.get("colors"), k) or tpl.palette[k % len(tpl.palette)] for k in range(len(vals))]
        if spec.get("palette") == "template":
            cols = [tpl.palette[k % len(tpl.palette)] for k in range(len(vals))]
        err = spec.get("errors")
        x = np.arange(len(vals))
        ax.bar(x, vals, width=spec.get("width", 0.7), color=cols, edgecolor=spec.get("edgecolor", "none"),
               yerr=err, capsize=L["capsize"], error_kw={"elinewidth": L["errorbar_lw"]})
        ax.set_xticks(x, cats)
        ax.tick_params(axis="x", which="both", length=0)
        if spec.get("value_labels"):
            lv = spec.get("label_values", vals)
            ax.get_ylim()[1] if spec.get("ylim") in (None, [None, None]) else None
            up = np.asarray(err[1] if err is not None and np.ndim(err) == 2 else (err if err is not None else np.zeros(len(vals))), float)
            for xi, v, t, e in zip(x, vals, lv, up):
                ax.annotate(f"{t:g}", (xi, v + (e if np.isfinite(e) else 0)), xytext=(0, 1.5), textcoords="offset points",
                            ha="center", va="bottom", fontsize=tpl.font["legend"])
        spec = dict(spec)
        spec["minor_ticks"] = False
        if spec.get("ylim") and spec["ylim"][1] is None:
            spec["ylim"] = None
            ax.set_ylim(bottom=0)
            ax.margins(y=0.08)
    elif typ == "bar":
        tab = read_table(spec["data"]) if isinstance(spec.get("data"), str) else spec["data"]
        keys = list(tab)
        cats = tab[spec.get("x", keys[0])]
        yks = spec.get("y", keys[1:])
        n = len(yks)
        w = 0.8 / n
        for k, yk in enumerate(yks):
            ax.bar(np.arange(len(cats)) + (k - (n - 1) / 2) * w, tab[yk], width=w, label=yk,
                   color=tpl.palette[k % len(tpl.palette)])
        ax.set_xticks(np.arange(len(cats)), [str(c) for c in cats])
        if n > 1:
            ax.legend()
    else:
        raise ValueError(f"Unknown panel type '{typ}'")
    # axes cosmetics
    if typ != "image":
        if spec.get("xscale"): ax.set_xscale(spec["xscale"])
        if spec.get("yscale"): ax.set_yscale(spec["yscale"])
        if spec.get("xlim") is not None: ax.set_xlim(*spec["xlim"])
        if spec.get("ylim") is not None: ax.set_ylim(*spec["ylim"])
        if spec.get("xlabel"): ax.set_xlabel(spec["xlabel"], **_title_kw(spec.get("xlabel_style")))
        if spec.get("ylabel"): ax.set_ylabel(spec["ylabel"], **_title_kw(spec.get("ylabel_style")))
        if spec.get("minor_ticks", True):
            if ax.get_xscale() == "linear" and typ != "bar" and spec.get("xminor", True):
                ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())
            if ax.get_yscale() == "linear" and spec.get("yminor", True):
                ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
        if tpl.axes.get("mirror_ticks"):
            ax.tick_params(which="both", top=True, right=True)
        for sp in ("top", "right"):
            if sp not in tpl.axes["spines"] and typ in ("line", "scatter", "errorbar", "bar", "hist"):
                ax.spines[sp].set_visible(False)
            elif typ in ("heatmap", "contourf", "contour", "spectrum2d", "paths"):
                ax.spines[sp].set_visible(True)
        if spec.get("title"):
            ax.set_title(spec["title"], fontsize=tpl.font["label"], **_title_kw(spec.get("title_style")))
    if spec.get("xticks") is not None and typ in ("line", "scatter", "errorbar", "paths"):
        ax.set_xticks(spec["xticks"])
        if spec.get("xlim") is not None:
            ax.set_xlim(*spec["xlim"])
    if spec.get("yticks") is not None and typ in ("line", "scatter", "errorbar", "paths"):
        ax.set_yticks(spec["yticks"])
        if spec.get("ylim") is not None:
            ax.set_ylim(*spec["ylim"])
    if spec.get("y_right"):
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
    if spec.get("no_yaxis"):
        ax.spines["left"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["top"].set_visible(False)
        ax.yaxis.set_visible(False)
    if spec.get("hide_xticklabels"):
        ax.tick_params(axis="x", which="both", labelbottom=False)
    if spec.get("hide_yticklabels"):
        ax.tick_params(axis="y", which="both", labelleft=False)
    if spec.get("hide_yticks"):
        ax.set_yticks([])
    for ins in spec.get("inset_axes", []) or []:
        iax = ax.inset_axes(ins["bounds"])
        sub = dict(ins["spec"])
        with plt.rc_context({"font.size": 0.8 * tpl.font["tick"], "axes.labelsize": 0.85 * tpl.font["label"],
                             "xtick.labelsize": 0.8 * tpl.font["tick"], "ytick.labelsize": 0.8 * tpl.font["tick"]}):
            draw_panel(iax, sub, tpl, base)
    if spec.get("grid"):
        ax.grid(True, ls=(0, (3, 2)), lw=0.4, color="0.82", zorder=0)
        ax.set_axisbelow(True)
    for ann in spec.get("annotations", []) or []:
        fs = ann.get("size") or (tpl.font["tick"] * ann["size_rel"] if ann.get("size_rel") else tpl.font["legend"])
        kw = {}
        if ann.get("xytext") is not None:      # an arrow from the text to the point
            kw = {"xytext": ann["xytext"], "textcoords": ann.get("coords", "data"),
                  "arrowprops": {"arrowstyle": "-|>", "color": ann.get("color", "k"), "lw": ann.get("lw", 0.6),
                                 "shrinkA": 1.5, "shrinkB": 1.5, "mutation_scale": ann.get("head", 6)}}
        ax.annotate(ann.get("text", ""), xy=ann["xy"], xycoords=ann.get("coords", "data"), fontsize=fs,
                    ha=ann.get("ha", "center"), va=ann.get("va", "baseline" if not kw else "center"),
                    color=ann.get("color", "k"), fontweight=ann.get("weight", "normal"),
                    fontstyle=ann.get("style", "normal"), annotation_clip=False, **kw)
    if spec.get("annotations") and spec.get("title") and typ != "image":
        # labels placed above the axes (peak letters) sit under the title, as in the source
        ys = [ax.transLimits.transform(ax.transScale.transform(a["xy"]))[1]
              for a in spec["annotations"] if a.get("coords", "data") == "data"]
        top = max(ys, default=0.0)
        if top > 1.0:     # passing y turns matplotlib's automatic title placement off
            ax.set_title(spec["title"], fontsize=tpl.font["label"], y=top + 0.07, **_title_kw(spec.get("title_style")))
            ax._resrijan_title_lifted = True
    return ret


LINESTYLES = {"solid": "-", "dashed": "--", "dotted": ":", "dashdot": "-.", "none": "none",
              "-": "-", "--": "--", ":": ":", "-.": "-."}
MARKERS = {"circle": "o", "square": "s", "triangle": "^", "down": "v", "diamond": "D", "pentagon": "p",
           "hexagon": "h", "star": "*", "plus": "P", "cross": "X", "dot": ".", "none": "none"}
LEGEND_LOCS = ["best", "upper right", "upper left", "lower left", "lower right", "right", "center left",
               "center right", "lower center", "upper center", "center", "outside right", "outside top", "none"]


def _user_style(s: dict, spec: dict, k: int, typ: str) -> dict:
    """Series style chosen by the user (``linestyles``, ``markers``, ``linewidth``, ``markersize``
    lists/values in the panel spec) on top of the series' own style."""
    s = dict(s)
    ls = _pick_color(spec.get("linestyles"), k)
    if ls:
        s["linestyle"] = LINESTYLES.get(ls.lower(), ls)
    mk = _pick_color(spec.get("markers"), k)
    if mk:
        mk = MARKERS.get(mk.lower(), mk)
        if mk == "none":
            if typ == "line" and "yerr" not in s and "yerr_lo" not in s:
                s["kind"] = "line"
                s.pop("markers_and_line", None)
        else:
            s["marker"] = mk
            if typ in ("line", "errorbar") and s.get("kind") != "markers":
                s["markers_and_line"] = True
    if spec.get("linewidth"):
        s["lw"] = float(spec["linewidth"])
    if spec.get("markersize"):
        s["ms"] = float(spec["markersize"])
    return s


def _legend(ax, spec: dict, default: bool):
    """Legend position (any matplotlib location, 'outside right', 'outside top' or 'none'),
    frame and number of columns."""
    lg = spec.get("legend", default)
    if lg in (False, None, "none", "off") or not ax.get_legend_handles_labels()[0]:
        return
    loc = lg if isinstance(lg, str) else "best"
    kw = {"frameon": bool(spec.get("legend_frame", False)), "ncols": int(spec.get("legend_ncol", 1))}
    if loc == "outside right":
        kw.update(loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0)
    elif loc == "outside top":
        kw.update(loc="lower center", bbox_to_anchor=(0.5, 1.02), borderaxespad=0)
        kw["ncols"] = int(spec.get("legend_ncol", len(ax.get_legend_handles_labels()[0])))
    else:
        kw["loc"] = loc
    if spec.get("legend_size"):
        kw["fontsize"] = float(spec["legend_size"])
    leg = ax.legend(**kw)
    if kw["frameon"]:
        leg.get_frame().set_linewidth(0.4)
        leg.get_frame().set_edgecolor("0.3")


def _pick_color(colors, k: int):
    """k-th entry of a user colour list; None when the list is shorter or the entry is empty
    (then the series keeps its own colour or the template's palette)."""
    if not colors or k >= len(colors):
        return None
    c = str(colors[k]).strip()
    return c or None


def _title_kw(st) -> dict:
    """Axis-title colour/weight kept from the source."""
    st = st or {}
    kw = {}
    if st.get("color"):
        kw["color"] = st["color"]
    if st.get("weight"):
        kw["fontweight"] = st["weight"]
    return kw


def _axes_width_pt(ax) -> float:
    return ax.get_position().width * ax.figure.get_size_inches()[0] * 72


def _image_extras(ax, spec: dict, img, tpl):
    """Insets, vector overlays (paths, lines, arrows) and text on an image panel.
    Coordinates are image pixels (x right, y down)."""
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch
    H, W = img.shape[:2]
    for ins in spec.get("insets", []) or []:
        z = ins["z"] if "z" in ins else read_image(ins["data"])
        x0, y0, x1, y1 = ins["box"]
        ax.imshow(z, cmap="gray" if z.ndim == 2 else None, extent=(x0, x1, y1, y0), interpolation="none", zorder=2)
        if ins.get("frame", True):
            ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec=ins.get("frame_color", "w"),
                                       lw=0.4, zorder=2.5))
    # scale factor: image px → points on the page (for line widths)
    bbox = ax.get_position()
    fig_w_pt = ax.figure.get_size_inches()[0] * 72
    pt_per_px = bbox.width * fig_w_pt / W if W else 1.0
    for d in spec.get("paths", []) or []:
        verts, codes = [], []
        for it in d["items"]:
            op = it[0]
            if op == "l":
                verts += [it[1], it[2]]; codes += [MPath.MOVETO, MPath.LINETO]
            elif op == "c":
                verts += [it[1], it[2], it[3], it[4]]; codes += [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4]
            elif op == "re":
                (a, b), (c, e) = it[1], it[2]
                verts += [(a, b), (c, b), (c, e), (a, e), (a, b)]
                codes += [MPath.MOVETO, MPath.LINETO, MPath.LINETO, MPath.LINETO, MPath.CLOSEPOLY]
            elif op == "qu":
                verts += [it[1], it[2], it[3], it[4], it[1]]
                codes += [MPath.MOVETO, MPath.LINETO, MPath.LINETO, MPath.LINETO, MPath.CLOSEPOLY]
        if not verts:
            continue
        # join consecutive segments that share end points into one sub-path (proper fills/joins)
        v2, c2 = [verts[0]], [codes[0]]
        for v, c in zip(verts[1:], codes[1:]):
            if c == MPath.MOVETO and np.hypot(v[0] - v2[-1][0], v[1] - v2[-1][1]) < 1e-6:
                continue
            v2.append(v); c2.append(c)
        if d.get("closed") and c2[-1] != MPath.CLOSEPOLY:
            v2.append(v2[-1]); c2.append(MPath.CLOSEPOLY)
        fc = d.get("fill")
        ec = d.get("stroke")
        lw = max(0.3, d.get("lw_px", 1.0) * pt_per_px) if ec is not None else 0
        ls = "-"
        if d.get("dashes") and str(d["dashes"]).strip() not in ("[] 0", "[] 0.0", ""):
            ls = (0, (3, 2))
        patch = PathPatch(MPath(v2, c2), facecolor=_c(fc) if fc is not None else "none",
                          edgecolor=_c(ec) if ec is not None else "none", lw=lw, ls=ls, zorder=3,
                          capstyle="butt", joinstyle="miter")
        ax.add_patch(patch)
    for a in spec.get("arrows", []) or []:
        (x0, y0), (x1, y1) = a["xy"]
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0), zorder=3,
                    arrowprops=dict(arrowstyle="-|>", color=_c(a.get("color", "w")), lw=a.get("lw", 1.0),
                                    shrinkA=0, shrinkB=0, mutation_scale=a.get("head", 6)))
    for t in spec.get("texts", []) or []:
        x0, y0, x1, y1 = t["box"]
        lines = t.get("lines") or [t["text"]]
        txt = ax.text(0.5 * (x0 + x1), 0.5 * (y0 + y1), "\n".join(lines), ha="center", va="center", zorder=4,
                color=_c(t.get("color", "k")), fontsize=t.get("size", _text_size(ax, t, tpl)),
                fontweight="bold" if t.get("bold") else "normal", linespacing=1.0)
        if t.get("size_frac") and "size" not in t:
            txt._resrijan_size_frac = (t["size_frac"], tpl.font["label"])     # final size after the layout
    ax.set_xlim(-0.5, W - 0.5)
    ax.set_ylim(H - 0.5, -0.5)
    if spec.get("title"):
        ax.set_title(spec["title"], fontsize=tpl.font["label"], pad=2)


def _text_size(ax, t: dict, tpl) -> float:
    """Text on an image keeps its size relative to the image (``size_frac`` = line height / image
    height in the source), within sensible limits; otherwise the template's label size."""
    frac = t.get("size_frac")
    if not frac:
        return tpl.font["label"]
    h_pt = ax.get_position().height * ax.figure.get_size_inches()[1] * 72
    return float(np.clip(frac * h_pt / 1.16, 0.8 * tpl.font["label"], 4.0 * tpl.font["label"]))


def _c(c):
    if isinstance(c, str):
        return c
    c = tuple(c)
    return tuple(v / 255 for v in c[:3]) if max(c[:3]) > 1 else c[:3]


def _parse_bar(s):
    m = re.match(r"\s*([\d.]+)\s*(nm|µm|um|Å)", str(s))
    v = float(m.group(1)); u = m.group(2)
    nm = v * {"nm": 1, "µm": 1000, "um": 1000, "Å": 0.1}[u]
    return nm, f"{v:g} {u.replace('um', 'µm')}", nm


def _panel_aspect(spec: dict, base: str) -> (float, bool):
    if "aspect" in spec:
        return float(spec["aspect"]), bool(spec.get("fixed_aspect", False))
    typ = spec.get("type", "line")
    if typ == "image":
        try:
            img = spec["z"] if "z" in spec else read_image(_resolve(spec, base)["data"])
            if spec.get("crop"):
                x0, y0, x1, y1 = spec["crop"]
                return (x1 - x0) / (y1 - y0), True
            return img.shape[1] / img.shape[0], True
        except Exception:
            return 1.0, True
    return DEFAULT_ASPECT.get(typ, 1.33), False


# ───────────────────────────── figure assembly ─────────────────────────────
def figure(panels: List[dict], template: str = "natchem", width: Union[str, float] = "double",
           height: Optional[float] = None, labels: Union[bool, List[str]] = True,
           rows: Optional[List[List[int]]] = None, base: str = ".", hgap_mm: float = 6.0, vgap_mm: float = 5.0,
           cols: Optional[List[List[int]]] = None, style: Optional[dict] = None):
    """Build a multi-panel figure. Returns (fig, axes, layout).
    ``style``: ``font`` (family name), ``font_scale`` (all text sizes), ``line_scale`` (line widths).
    ``cols`` (with ``rows``): column of each panel on a common grid; rows with fewer panels
    keep empty cells, so every row has the same panel size (source layouts)."""
    tpl = _styled(T.get(template), style)
    W = tpl.width_mm(width)
    asp = [_panel_aspect(p, base) for p in panels]
    grid = None
    if rows and cols and len(cols) == len(rows):
        ncol = max(max(c) for c in cols) + 1
        full = next((r for r, c in zip(rows, cols) if len(c) == ncol), None)
        if full is not None:
            # lay out the grid as if every row were full; empty cells take the full row's aspect
            col_asp = [asp[i] for i in full]
            ext, ext_rows, grid = list(asp), [], []
            for r, c in zip(rows, cols):
                er, gr = [], {}
                for k in range(ncol):
                    if k in c:
                        i = r[c.index(k)]
                        er.append(i)
                        gr[k] = i
                    else:
                        ext.append(col_asp[k])
                        er.append(len(ext) - 1)
                ext_rows.append(er)
                grid.append(gr)
            lay = auto_layout([a for a, _ in ext], W, tpl.max_height_mm, [f for _, f in ext], hgap_mm, vgap_mm,
                              height_mm=height, rows=ext_rows)
    if grid is None:
        lay = auto_layout([a for a, _ in asp], W, tpl.max_height_mm, [f for _, f in asp], hgap_mm, vgap_mm,
                          height_mm=height, rows=rows)
    with plt.rc_context(tpl.rc()):
        fig = plt.figure(figsize=(W * MM, lay.height_mm * MM), layout="constrained")
        fig.get_layout_engine().set(w_pad=1.0 * MM, h_pad=1.0 * MM, wspace=0.02, hspace=0.03)
        outer = GridSpec(len(lay.rows), 1, figure=fig, height_ratios=lay.row_heights_mm)
        axes = [None] * len(panels)
        for r, (row, ws) in enumerate(zip(lay.rows, lay.widths_mm)):
            inner = outer[r].subgridspec(1, len(row), width_ratios=ws)
            for c, i in enumerate(row):
                if i < len(panels):          # cells beyond the panel list are empty grid cells
                    axes[i] = fig.add_subplot(inner[0, c])
        for i, (ax, p) in enumerate(zip(axes, panels)):
            draw_panel(ax, p, tpl, base)
        if labels:
            labs = labels if isinstance(labels, list) else [tpl.label(i) for i in range(len(panels))]
            _panel_labels(fig, axes, labs, tpl)
        _span_titles(fig, axes, panels)
        _fit_image_texts(fig)
    fig._resrijan_template = tpl
    return fig, axes, lay


def _styled(tpl, style: Optional[dict]):
    """A copy of the template with the user's font and size changes."""
    import dataclasses
    if not style:
        return tpl
    font, lines, pl = dict(tpl.font), dict(tpl.lines), dict(tpl.panel_label)
    if style.get("font"):
        font["names"] = [style["font"]] + [n for n in font["names"] if n != style["font"]]
        from matplotlib import font_manager
        fams = {f.name: f for f in font_manager.fontManager.ttflist}
        if style["font"] in fams and "serif" in style["font"].lower() and "sans" not in style["font"].lower():
            font["family"] = "serif"
    fs = float(style.get("font_scale") or 1.0)
    if fs != 1.0:
        for k in ("size", "label", "tick", "legend"):
            font[k] = round(font[k] * fs, 2)
        pl["size"] = round(pl.get("size", 8) * fs, 2)
    ls = float(style.get("line_scale") or 1.0)
    if ls != 1.0:
        for k in ("linewidth", "errorbar_lw"):
            if k in lines:
                lines[k] = lines[k] * ls
        lines["markersize"] = lines["markersize"] * ls ** 0.5
    return dataclasses.replace(tpl, font=font, lines=lines, panel_label=pl)


def font_names() -> List[str]:
    """Font families matplotlib can use on this computer."""
    from matplotlib import font_manager
    return sorted({f.name for f in font_manager.fontManager.ttflist})


def _fit_image_texts(fig):
    """Text on images keeps its source size relative to the image: set once the layout is final."""
    texts = [(ax, t) for ax in fig.axes for t in ax.texts if hasattr(t, "_resrijan_size_frac")]
    if not texts:
        return
    fig.canvas.draw()
    for ax, t in texts:
        frac, label = t._resrijan_size_frac
        h_pt = ax.get_window_extent().height * 72 / fig.dpi
        t.set_fontsize(float(np.clip(frac * h_pt / 1.16, 0.8 * label, 4.0 * label)))


def _span_titles(fig, axes, panels):
    """A title shared by several neighbouring panels (``title_span``) is centred over them."""
    todo = [(i, int(p["title_span"])) for i, p in enumerate(panels) if p.get("title") and p.get("title_span", 1) > 1]
    if not todo:
        return
    fig.canvas.draw()
    for i, n in todo:
        grp = [a for a in axes[i:i + n] if a is not None]
        if len(grp) < 2:
            continue
        p0 = grp[0].get_position()
        if any(abs(a.get_position().y1 - p0.y1) > 0.02 for a in grp):
            continue                       # not in one row in this layout
        cx = 0.5 * (p0.x0 + grp[-1].get_position().x1)
        ax, t = grp[0], grp[0].title
        y = t.get_position()[1]
        if any(a._left_title.get_text() for a in grp) and not getattr(ax, "_resrijan_title_lifted", False):
            # panel letters share the title's line: lift the title one line above them
            h_pt = p0.height * fig.get_size_inches()[1] * 72
            y += 1.3 * t.get_fontsize() / max(h_pt, 1e-6)
        ax.set_title(t.get_text(), x=(cx - p0.x0) / p0.width, y=y, fontsize=t.get_fontsize(),
                     color=t.get_color(), fontweight=t.get_fontweight())


def _panel_labels(fig, axes, labs, tpl):
    """Bold panel letters at the top-left of each panel's full extent (incl. tick labels)."""
    pl = tpl.panel_label
    for ax, lab in zip(axes, labs):
        ax.set_title(lab, loc="left", fontsize=pl.get("size", 8), fontweight=pl.get("weight", "bold"), pad=3)
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    for ax in axes:
        bb = ax.get_tightbbox(r)
        ab = ax.get_window_extent(r)
        if ab.width > 0:
            # shift the letter left over the tick labels / y-label (axes fraction)
            ax._left_title.set_x(min(0.0, (bb.x0 - ab.x0) / ab.width))
            ax._left_title.set_ha("left")


def save(fig, path: str, formats: Sequence[str] = ("pdf", "svg", "png"), dpi: Optional[int] = None) -> List[str]:
    """Save to several formats. Vector files keep text editable (Type 42 / SVG text)."""
    tpl = getattr(fig, "_resrijan_template", None)
    dpi = dpi or (tpl.export.get("dpi", 600) if tpl else 600)
    base, ext = os.path.splitext(path)
    if ext:
        formats = [ext.lstrip(".")]
    out = []
    rc = tpl.rc() if tpl else {}
    with plt.rc_context(rc):
        for f in formats:
            f = f.lower().lstrip(".")
            p = f"{base}.{f}"
            if f in ("tif", "tiff"):
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=dpi)
                from PIL import Image
                Image.open(buf).convert("RGB").save(p, compression="tiff_lzw", dpi=(dpi, dpi))
            elif f in ("png", "jpg", "jpeg"):
                fig.savefig(p, dpi=dpi)
            else:
                fig.savefig(p)
            if f == "svg" and tpl:
                _svg_fonts(p, tpl)
            out.append(p)
    return out


def _svg_fonts(path: str, tpl: T.Template):
    """Write the journal's preferred font stack into the SVG so Illustrator/Inkscape pick Arial etc."""
    s = Path(path).read_text(encoding="utf-8")
    stack = ", ".join(f"'{n}'" if " " in n else n for n in tpl.font["names"])
    stack += ", sans-serif" if tpl.font["family"] == "sans-serif" else ", serif"
    s = re.sub(r"font-family:[^;\"]+", f"font-family:{stack}", s)
    s = re.sub(r'font-family="[^"]+"', f'font-family="{stack}"', s)
    Path(path).write_text(s, encoding="utf-8")


def compose(spec_path: str, out: Optional[str] = None, formats=None) -> List[str]:
    """Build a figure from a YAML spec file (see examples/)."""
    import yaml
    spec = yaml.safe_load(open(spec_path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(spec_path))
    figspec = spec.get("figure", {})
    fig, axes, lay = figure(spec["panels"], template=figspec.get("template", "natchem"),
                            width=figspec.get("width", "double"), height=figspec.get("height"),
                            labels=figspec.get("labels", True), rows=figspec.get("rows"), base=base,
                            style={k: figspec[k] for k in ("font", "font_scale", "line_scale") if k in figspec})
    out = out or os.path.join(base, figspec.get("output", Path(spec_path).stem))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fmts = formats or figspec.get("formats", ["pdf", "svg", "png"])
    files = save(fig, out, fmts)
    plt.close(fig)
    return files
