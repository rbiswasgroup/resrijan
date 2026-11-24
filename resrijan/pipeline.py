"""End-to-end digitisation: file → panels → calibrated data → checks → replot."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

import cv2
import numpy as np

from .io.loader import Page, crop as crop_page, embedded_images, load
from .detect import axes as raxes, ocr, vector
from .detect.calibration import manual as manual_cal
from .extract import bars as barmod, curves, heatmap, imagefig, micrograph
from .extract.vector_series import extract_vector_series
from . import anomaly


@dataclass
class Panel:
    id: str
    kind: str                         # line | scatter | heatmap | contourf | micrograph
    mode: str                         # vector | raster | embedded-image
    page: Page
    box: Optional[raxes.AxesBox] = None
    series: list = field(default_factory=list)
    grid: Optional[heatmap.Grid] = None
    colorbar: Optional[heatmap.ColorBar] = None
    micro: Optional[micrograph.MicroResult] = None
    xlabel: str = ""
    ylabel: str = ""
    clabel: str = ""
    notes: List[dict] = field(default_factory=list)
    files: dict = field(default_factory=dict)
    contours: list = field(default_factory=list)
    bars: list = field(default_factory=list)
    gridlines: bool = False                # source plot had grid lines
    point_labels: list = field(default_factory=list)   # text placed on the plot (point/trace/peak labels)
    contour_style: list = field(default_factory=list)
    overlays: list = field(default_factory=list)
    frame: Optional[object] = None         # imagefig.Frame for photo/micrograph frames
    frames: Optional[list] = None          # all frames of the page (insets for the replot)
    title: str = ""

    @property
    def xlim(self):
        b = self.box
        if b is None or b.xcal is None:
            return None
        return _snap((b.xcal.to_data(b.x0), b.xcal.to_data(b.x1)), b.xcal) if b and b.xcal else None

    @property
    def ylim(self):
        b = self.box
        return _snap((b.ycal.to_data(b.y1), b.ycal.to_data(b.y0)), b.ycal) if b and b.ycal else None


def _snap(lim, cal, tol=0.012):
    """Snap axis limits that sit a hair away from a tick value (frame-line thickness)."""
    lo, hi = float(lim[0]), float(lim[1])
    vals = sorted(cal.values)
    if cal.scale == "log":
        f = lambda v: np.log10(v)
        g = lambda v: 10 ** v
    else:
        f = g = lambda v: v
    a, b = f(lo), f(hi)
    span = abs(b - a)
    fv = [f(v) for v in vals] if vals else []
    step = np.median(np.diff(fv)) if len(fv) >= 2 else None
    out = []
    for v in (a, b):
        cand = list(fv)
        if step:
            cand.append(fv[0] + round((v - fv[0]) / step) * step)
            if cal.scale == "log":
                cand.append(round(v))
        best = min(cand, key=lambda c: abs(c - v)) if cand else v
        out.append(best if abs(best - v) < tol * span else v)
    return (float(g(out[0])), float(g(out[1])))


# ───────────────────────── axis titles ─────────────────────────
def _titles_vector(page: Page, box) -> tuple:
    d = page.pdf_page.get_text("dict")
    sc = page.scale
    _xl, _yl = "", ""
    lab_bottom = max([l.bbox[3] for l in box.xlabels], default=box.y1 + box.xtick_out)
    lab_left = min([l.bbox[0] for l in box.ylabels], default=box.x0 - box.ytick_out)
    best_x, best_y = None, None
    lab_right = max([l.bbox[2] for l in box.ylabels], default=box.x0)
    try:
        bars = [tuple(v / sc for v in p.bbox) for p in vector.minus_bars(vector.get_paths(page.pdf_page, sc))]
    except Exception:  # pragma: no cover
        bars = []
    all_lines = [ln for b in d.get("blocks", []) for ln in b.get("lines", [])]
    for _ in [0]:
        for ln in _merge_block_lines(all_lines):
            text = _span_text(ln["spans"], ln.get("dir", (1, 0)), bars).strip()
            if not text or ocr.parse_number(text) is not None:
                continue
            x0, y0, x1, y1 = (v * sc for v in ln["bbox"])
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            dirv = ln.get("dir", (1, 0))
            if abs(dirv[0]) > 0.9 and box.x0 - 0.1 * box.w < cx < box.x1 + 0.1 * box.w and lab_bottom - 2 < y0 < lab_bottom + 0.3 * box.h:
                if best_x is None or y0 < best_x[0]:
                    best_x = (y0, text, _line_style(ln))
            if abs(dirv[1]) > 0.9 and box.y0 < cy < box.y1 and lab_left - 0.35 * box.w < cx < lab_left + 0.25 * max(lab_right - lab_left, 1):
                if best_y is None or cx > best_y[0]:
                    best_y = (cx, text, _line_style(ln))
    box.title_style = {k: b[2] for k, b in (("x", best_x), ("y", best_y)) if b and b[2]}
    return (best_x[1] if best_x else ""), (best_y[1] if best_y else "")


def _line_style(ln) -> dict:
    """Colour and weight of an axis title when they differ from plain black text."""
    spans = [sp for sp in ln["spans"] if sp.get("text", "").strip()]
    if not spans:
        return {}
    out = {}
    if sum(vector._is_bold(sp) for sp in spans) > 0.5 * len(spans):
        out["weight"] = "bold"
    col = spans[0].get("color", 0)
    if col and all(sp.get("color", 0) == col for sp in spans):
        out["color"] = "#%06x" % col
    return out


def _merge_block_lines(lines):
    prev = None
    cur = [{"spans": l["spans"], "bbox": l["bbox"], "dir": l.get("dir", (1, 0))} for l in lines]
    while prev is None or len(cur) < prev:
        prev = len(cur)
        cur = _merge_once(cur)
    return cur


def _merge_once(lines):
    """Lines of one text block that sit on top of each other (main text, superscript,
    subscript runs are separate 'lines' in PDFs) become one line."""
    out = []
    for ln in lines:
        dirv = tuple(round(v, 2) for v in ln.get("dir", (1, 0)))
        along = np.array(dirv, float)
        bb = ln["bbox"]
        pa = sorted([np.dot([bb[0], bb[1]], along), np.dot([bb[2], bb[3]], along)])
        for o in out:
            if o["dir_r"] != dirv:
                continue
            ob = o["bbox"]
            size = max(s["size"] for s in o["spans"] + ln["spans"])
            # overlapping across the reading direction and adjacent along it
            if dirv[0] > 0.9:
                cross = min(bb[3], ob[3]) - max(bb[1], ob[1])
                hmin = min(bb[3] - bb[1], ob[3] - ob[1])
            else:
                cross = min(bb[2], ob[2]) - max(bb[0], ob[0])
                hmin = min(bb[2] - bb[0], ob[2] - ob[0])
            gap = max(pa[0], o["pa"][0]) - min(pa[1], o["pa"][1])
            if cross > 0.3 * hmin and gap < 0.6 * size:
                o["spans"] = o["spans"] + ln["spans"]
                o["bbox"] = (min(ob[0], bb[0]), min(ob[1], bb[1]), max(ob[2], bb[2]), max(ob[3], bb[3]))
                o["pa"] = (min(o["pa"][0], pa[0]), max(o["pa"][1], pa[1]))
                break
        else:
            out.append({"spans": list(ln["spans"]), "bbox": tuple(bb), "dir": ln.get("dir", (1, 0)), "dir_r": dirv,
                        "pa": (pa[0], pa[1])})
    for o in out:
        along = np.array(o["dir_r"], float)
        o["spans"].sort(key=lambda s: min(np.dot([s["bbox"][0], s["bbox"][1]], along),
                                          np.dot([s["bbox"][2], s["bbox"][3]], along)))
    return out


_UNIT_EXP = re.compile(r"\b(cm|mm|nm|µm|m|s|ps|fs|ns|K|g|kg|mol|L|Hz|eV|J|M|Å)(\^)?([-−]?\d+)(?=[\s)\]/,]|$)")


_SYMBOL_GREEK = str.maketrans("abgdezhqiklmnxoprstufcywGDQLXPSFYWJjv",
                              "αβγδεζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩϑφϖ")


def _span_text(spans, dirv=(1.0, 0.0), bars=()) -> str:
    """Join PDF text spans into mathtext: smaller spans above the baseline become
    superscripts, below it subscripts; drawn minus bars between script spans become '−'
    (e.g. E$^{calc}_{b-1}$ (kJ/mol), cm$^{-1}$)."""
    spans = [s for s in spans if s["text"]]
    if not spans:
        return ""
    big = max(s["size"] for s in spans)
    up = np.array([dirv[1], -dirv[0]], float)
    along = np.array([dirv[0], dirv[1]], float)
    mains = [np.dot(s["origin"], up) for s in spans if s["size"] >= 0.85 * big]
    base = float(np.median(mains)) if mains else 0.0
    toks = []
    for s in spans:
        t = s["text"]
        font = s.get("font", "")
        if "Symbol" in font:
            t = t.translate(_SYMBOL_GREEK)
        elif "Ital" in font or "Oblique" in font:
            t = re.sub(r"[A-Za-z]+", lambda m: "$\\mathit{" + m.group(0) + "}$", t)
        kind = "main"
        if s["size"] < 0.85 * big and t.strip():
            off = np.dot(s["origin"], up) - base
            kind = "sup" if off > 0.12 * big else ("sub" if off < -0.04 * big else "main")
        bx = s["bbox"]
        corners = np.array([[bx[0], bx[1]], [bx[2], bx[1]], [bx[0], bx[3]], [bx[2], bx[3]]])
        pa, pu = corners @ along, corners @ up
        toks.append([kind, t, (pa.min(), pa.max()), (pu.min(), pu.max())])
    # minus bars in the gap between two script spans of the same kind
    for a, b in zip(toks[:-1], toks[1:]):
        if a[0] == b[0] and a[0] != "main":
            for bar in bars:
                c = np.array([0.5 * (bar[0] + bar[2]), 0.5 * (bar[1] + bar[3])])
                ca, cu = c @ along, c @ up
                if a[2][1] - 0.5 <= ca <= b[2][0] + 0.5 and min(a[3][0], b[3][0]) <= cu <= max(a[3][1], b[3][1]):
                    a[1] = a[1].rstrip() + "-"
                    break
    out, i = "", 0
    esc = lambda t: t.strip().replace("−", "-").replace(" ", r"\ ")   # noqa: E731
    while i < len(toks):
        if toks[i][0] == "main":
            out += toks[i][1]
            i += 1
            continue
        sup = sub = ""
        while i < len(toks) and toks[i][0] != "main":
            if toks[i][0] == "sup":
                sup += toks[i][1]
            else:
                sub += toks[i][1]
            i += 1
        m = "$"
        if sup:
            m += "^{\\mathregular{" + esc(sup) + "}}"
        if sub:
            m += "_{\\mathregular{" + esc(sub) + "}}"
        out += m + "$"
    out = out.replace("$$", "")            # adjacent math runs: T + _w → $T_w$
    # plain-text unit exponents such as "cm-1" or "s^-1" → cm$^{-1}$
    return _UNIT_EXP.sub(lambda m: f"{m.group(1)}$^{{{m.group(3).replace('−', '-')}}}$", out)


def _clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    # drop unbalanced trailing/leading OCR debris such as '}' or '|'
    while t and t[-1] in "}]|_~'`\"" and t.count(t[-1]) > {"}": t.count("{"), "]": t.count("[")}.get(t[-1], 0):
        t = t[:-1].rstrip()
    t = re.sub(r"(\w)\(", r"\1 (", t)       # "Time(ps)" -> "Time (ps)"
    # OCR'd unit exponents: "cm-1", "cm7*", "cm~*" … → cm$^{-1}$ (inverse units dominate in chemistry)
    t = re.sub(r"mScm", "mS cm", t)
    t = re.sub(r"(?<![A-Za-z])(cm|mm|nm|ps|fs|ns|s|m|K|L|mol|M|Hz|g)\s?[-–~—]?[1lI7]?[*~]?(?=\)\s*$)",
               lambda m: m.group(1) + ("$^{-1}$" if m.group(0) != m.group(1) else ""), t)
    return t if sum(c.isalpha() for c in t) >= 1 else ""


def _titles_raster(rgb, box) -> tuple:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape
    labs = box.xlabels + box.ylabels
    ch = float(np.median([l.bbox[3] - l.bbox[1] for l in labs])) if labs else 12.0
    xl = yl = ""
    top = int(max([l.bbox[3] for l in box.xlabels], default=box.y1 + box.xtick_out + ch) + 1)
    reg = gray[top:min(H, int(top + 2.6 * ch)), max(0, int(box.x0)):min(W, int(box.x1))]
    if reg.size and (reg < 128).any():
        rows = np.nonzero((reg < 128).any(axis=1))[0]
        cols = np.nonzero((reg < 128).any(axis=0))[0]
        # text running past the panel edges is a heading for several panels, not this x title
        if cols[0] > 2 and cols[-1] < reg.shape[1] - 3:
            reg = reg[max(0, rows[0] - 2):rows[-1] + 3]
            xl, c = ocr.read_text(reg, psm=7)
            xl = xl if c >= 75 else ""
    right = int(min([l.bbox[0] for l in box.ylabels], default=box.x0 - box.ytick_out - 2 * ch) - 1)
    reg = gray[max(0, int(box.y0)):min(H, int(box.y1)), max(0, int(right - 2.6 * ch)):max(0, right)]
    if reg.size and (reg < 128).any():
        cols = np.nonzero((reg < 128).any(axis=0))[0]
        reg = reg[:, max(0, cols[0] - 2):cols[-1] + 3]
        rot = np.ascontiguousarray(np.rot90(reg, k=-1))
        best = ("", 0.0)
        for tgt in (40, 64):          # two scales; keep the more confident reading
            f = max(1.0, tgt / max(rot.shape[0], 1))
            big = cv2.resize(rot, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC) if f > 1 else rot
            t, c = ocr.read_text(big, psm=7)
            if c > best[1]:
                best = (t, c)
        yl = best[0] if best[1] >= 75 else ""
    return _clean_title(xl), _clean_title(yl)


# ───────────────────────── main entry ─────────────────────────
def _parse_region(region, page: Page):
    if region is None:
        return None
    v = [float(t) for t in str(region).replace(" ", "").split(",")] if not isinstance(region, (list, tuple)) else list(region)
    if all(0 <= t <= 1 for t in v):
        return (v[0] * page.width, v[1] * page.height, v[2] * page.width, v[3] * page.height)
    return tuple(v)


def _char_h(box) -> float:
    labs = box.xlabels + box.ylabels
    return float(np.median([l.bbox[3] - l.bbox[1] for l in labs])) if labs else max(8.0, 0.03 * box.h)


def _plot_fill_fraction(rgb, box) -> float:
    X0, Y0, X1, Y1 = int(box.x0) + 3, int(box.y0) + 3, int(box.x1) - 3, int(box.y1) - 3
    c = rgb[Y0:Y1, X0:X1].astype(int)
    if c.size == 0:
        return 0.0
    nonwhite = (np.abs(c - 255).sum(axis=2) > 30)
    return float(nonwhite.mean())


def digitize(path: str, pages: Optional[Sequence[int]] = None, region=None, dpi: float = 600,
             kind: str = "auto", xscale: str = "auto", yscale: str = "auto", xcal: Optional[str] = None,
             ycal: Optional[str] = None, scale: Optional[str] = None, prefer: str = "auto",
             particles: bool = True, max_series: int = 12) -> List[Panel]:
    """Digitise every figure panel found in ``path``.

    ``prefer``: "auto" (vector when available), "vector" or "raster".
    ``xcal``/``ycal``: manual calibrations "px:value,px:value" in rendered-image pixels.
    ``scale``: micrograph scale override "<pixels>=<value> <unit>", e.g. "100=50 nm".
    """
    out: List[Panel] = []
    for page in load(path, pages=pages, dpi=dpi):
        reg = _parse_region(region, page)
        work = crop_page(page, reg) if reg else page
        work.meta.get("offset_px", (0, 0))
        panels = _process_page(work, kind, xscale, yscale, xcal, ycal, scale, prefer, particles, max_series)
        _names_across_panels(panels)
        for k, p in enumerate(panels):
            p.id = f"p{page.index + 1}_{chr(97 + k)}"
        out.extend(panels)
    return out


def _process_page(page: Page, kind, xscale, yscale, xcal, ycal, scale, prefer, particles, max_series) -> List[Panel]:
    rgb = page.rgb
    panels: List[Panel] = []
    if kind == "micrograph":
        img = _image_panels(page, rgb, [], scale, particles, kind)
        return img or [_micro_panel(page, rgb, scale, particles)]
    boxes, mode = [], "raster"
    use_vec = page.pdf_page is not None and prefer in ("auto", "vector") and not page.meta.get("offset_px")
    if use_vec:
        try:
            boxes = vector.analyse(page, xscale, yscale)
            mode = "vector"
        except Exception:  # pragma: no cover
            boxes = []
        if not boxes:
            mode = "raster"
    if not boxes:
        photos = []
        if kind in ("auto", "micrograph"):
            if page.pdf_page is not None:
                off = page.meta.get("offset_px", (0, 0))
                photos = [(im["rect"][0] * page.scale - off[0], im["rect"][1] * page.scale - off[1],
                           im["rect"][2] * page.scale - off[0], im["rect"][3] * page.scale - off[1])
                          for im in embedded_images(page, min_px=48)]
            else:
                photos = imagefig._raster_frames(rgb)
        boxes = raxes.analyse_axes(rgb, xscale, yscale, photos=photos)
    # photographs / micrographs (and their insets): never plots
    img_panels = []
    if kind in ("auto", "micrograph"):
        calibrated = [_expand(b.as_tuple(), 0.25) for b in boxes if b.xcal is not None or b.ycal is not None]
        try:
            img_panels = _image_panels(page, rgb, calibrated, scale, particles, kind)
        except Exception as exc:  # pragma: no cover
            img_panels = []
            panels_err = Panel("p", "unknown", mode, page)
            panels_err.notes.append({"level": "warn", "code": "image_failed", "msg": f"Image analysis failed: {exc}"})
            img_panels = [panels_err]
        fboxes = [q.frame.box for q in img_panels if q.frame is not None]
        # axis-like lines inside a photo without tick numbers are features of the image
        boxes = [b for b in boxes if b.xcal is not None or b.ycal is not None
                 or not any(imagefig._overlap(b.as_tuple(), fb) > 0.5 for fb in fboxes)]
    if not boxes and img_panels:
        return img_panels
    if not boxes:
        if page.pdf_page is not None:
            for im in embedded_images(page):
                if micrograph.looks_like_micrograph(im["rgb"]):
                    sub = Page(page.source, page.index, im["rgb"], 1.0, "raster", native_dpi=im["native_dpi"],
                               meta={"embedded_rect": im["rect"]})
                    panels.append(_micro_panel(sub, im["rgb"], scale, particles, mode="embedded-image"))
            if panels:
                return panels
        if kind in ("auto",) and micrograph.looks_like_micrograph(rgb):
            return [_micro_panel(page, rgb, scale, particles)]
        p = Panel("p", "unknown", mode, page)
        p.notes.append({"level": "error", "code": "no_axes",
                        "msg": "No plot axes found. Crop to one panel with --region, or pass --type micrograph."})
        return [p]
    # reading order: rows top→bottom (by plot top edge), then left→right
    hs = np.median([b.h for b in boxes])
    boxes.sort(key=lambda b: (round(b.y1 / (0.5 * hs)), b.x0))
    paths = vector.get_paths(page.pdf_page, page.scale) if mode == "vector" else None
    chars = vector.get_chars(page.pdf_page, page.scale) if mode == "vector" else None
    text_labels = vector.group_chars(chars) if chars else None
    for box in boxes:
        if xcal:
            box.xcal = manual_cal("x", xcal, "log" if xscale == "log" else "linear")
            box.notes = [n for n in box.notes if not n["code"].startswith("x_")]
        if ycal:
            box.ycal = manual_cal("y", ycal, "log" if yscale == "log" else "linear")
            box.notes = [n for n in box.notes if not n["code"].startswith("y_")]
        p = Panel("p", "line", mode, page, box)
        if box.ycal is None and mode == "vector" and paths is not None and kind in ("auto", "bar"):
            cal = _ycal_from_bar_values(paths, box, text_labels)
            if cal is not None:
                box.ycal = cal
                box.notes = [n for n in box.notes if not n["code"].startswith("y_")]
                box.notes.append({"level": "info", "code": "y_from_bar_values",
                                  "msg": "The y-axis has no numbers; calibrated from the values printed on the bars "
                                         f"({', '.join(f'{v:g}' for v in cal.values[1:])}), zero at the axis."})
        if box.ycal is None and box.xcal is not None:
            box.ycal = _relative_cal("y", box)
            box.notes = [n for n in box.notes if not (n["code"].startswith("y_") and n["level"] == "error")]
            if getattr(box, "no_yaxis", False):
                box.notes.append({"level": "info", "code": "y_relative",
                                  "msg": "No y axis (stacked/offset traces): intensities are relative, as a fraction of the "
                                         "panel height (0 = x axis, 1 = top); the stacking offsets are kept."})
            else:
                box.notes.append({"level": "warn", "code": "y_relative",
                                  "msg": "The y-axis has no tick numbers: y is given as a fraction of the axis height "
                                         "(0 = bottom, 1 = top). Give --ycal 'px:value,px:value' for real units."})
        p.notes.extend(box.notes)
        if box.ycal is None:
            p.kind = "uncalibrated"
            panels.append(p)
            continue
        # bar charts first (they also fill the plot area, like maps)
        if kind in ("auto", "bar"):
            if _bar_panel(p, page, rgb, box, mode, paths, text_labels):
                try:
                    p.xlabel, p.ylabel = _titles_vector(page, box) if mode == "vector" else ("", "")
                    if not p.ylabel:
                        p.ylabel = _titles_raster(rgb, box)[1]
                except Exception:
                    pass
                p.notes.extend(n for n in anomaly.calibration_checks(box) if n["code"] != "resolution")
                panels.append(p)
                continue
        if box.xcal is None:
            p.kind = "uncalibrated"
            p.notes.append({"level": "error", "code": "x_uncalibrated",
                            "msg": "x-axis could not be calibrated and no bars were found; supply --xcal."})
            panels.append(p)
            continue
        # titles
        try:
            p.xlabel, p.ylabel = _titles_vector(page, box) if mode == "vector" else ("", "")
            if not p.xlabel and getattr(box, "xunit_text", ""):
                p.xlabel = box.xunit_text
            if not p.xlabel or not p.ylabel:
                rx, ry = _titles_raster(rgb, box)
                p.xlabel, p.ylabel = p.xlabel or rx, p.ylabel or ry
        except Exception:
            pass
        if mode == "vector" and paths is not None and kind in ("auto", "contour") and _contour_panel(p, box, paths):
            p.notes.extend(anomaly.calibration_checks(box))
            panels.append(p)
            continue
        fill = _plot_fill_fraction(rgb, box)
        cb = heatmap.find_colorbar(rgb, box) if kind in ("auto", "heatmap", "contourf") else None
        is_map = kind in ("heatmap", "contourf") or (kind == "auto" and (fill > 0.35 or (cb is not None and fill > 0.15)))
        if is_map:
            _map_panel(p, page, rgb, box, cb, text_labels)
        else:
            _series_panel(p, page, rgb, box, mode, paths, chars, kind, max_series)
        p.notes.extend(anomaly.calibration_checks(box))
        panels.append(p)
    if mode == "vector" and paths is not None:
        _outlined_titles(panels, paths, text_labels)
    if img_panels:
        panels = _reading_order(panels + img_panels)
    return panels


def _outlined_titles(panels, paths, text_labels=None):
    """Titles just above contour panels ("Sample A"), stored as text or drawn as outlines.
    A title centred over a pair of panels in one row is kept on the left one with
    ``title_span`` 2."""
    from .extract.vector_series import _join_words, outlined_words
    words_txt = _join_words([l for l in (text_labels or []) if l.value is None and not getattr(l, "rotated", False)])
    cps = [p for p in panels if p.kind == "contour" and p.box is not None and not p.title]
    if not cps:
        return
    hmed = float(np.median([p.box.h for p in cps]))
    for p in cps:
        b = p.box
        right = [q for q in cps if q is not p and abs(q.box.y0 - b.y0) < 0.05 * hmed and q.box.x0 > b.x1 - 2]
        nb = min(right, key=lambda q: q.box.x0) if right else None
        x1 = nb.box.x1 if nb is not None and nb.box.x0 - b.x1 < 0.3 * b.w else b.x1
        region = (b.x0, b.y0 - 0.3 * b.h, x1, b.y0 - 0.02 * b.h)
        used = {tuple(l.bbox) for l in (p.point_labels or [])}
        cand = [w for w in words_txt if region[0] <= 0.5 * (w.bbox[0] + w.bbox[2]) <= region[2]
                and region[1] <= 0.5 * (w.bbox[1] + w.bbox[3]) <= region[3]]
        if not cand:
            cand = outlined_words(paths, region, max_h=0.15 * b.h)
        words = [w for w in cand if tuple(w.bbox) not in used and ocr.parse_number(w.text) is None and len(w.text) > 1]
        if not words:
            continue
        w = min(words, key=lambda w: b.y0 - w.bbox[3])          # the line nearest the panel
        cx = 0.5 * (w.bbox[0] + w.bbox[2])
        p.title = w.text
        p.title_style = {"color": "#%02x%02x%02x" % tuple(getattr(w, "color", None) or (0, 0, 0))}
        if getattr(w, "stroke_rel", 0) > 0.17 or getattr(w, "bold", False):
            p.title_style["weight"] = "bold"
        if cx > b.x1 and nb is not None:
            p.title_span = 2
            nb.title = ""


def _bar_legend(paths, box, labels, bars):
    """Colour legend inside a bar chart: small filled swatch + text to its right.
    Returns {bar colour (rgb tuple): name, "_rows": [swatch y]} when every bar colour is named."""
    from .extract.vector_series import _join_words
    if not labels:
        return {}
    words = _join_words([l for l in labels if l.value is None and not getattr(l, "rotated", False)
                         and box.x0 < l.cx < box.x1 and box.y0 < l.cy < box.y1])
    out, rows = {}, []
    for l in words:
        h = l.bbox[3] - l.bbox[1]
        for p in paths:
            if p.fill is None or p.w > 4 * h or p.h > 2 * h:
                continue
            if l.bbox[0] - 4 * h <= p.bbox[2] <= l.bbox[0] + 1 and abs(0.5 * (p.bbox[1] + p.bbox[3]) - l.cy) < 0.6 * h:
                col = tuple(int(round(v * 255)) for v in p.fill[:3])
                out[col] = l.text
                rows.append(0.5 * (p.bbox[1] + p.bbox[3]))
                break
    cols = {tuple(b.color) for b in bars}
    if not out or not cols <= set(out):
        return {}
    out["_rows"] = rows
    return out


def _names_across_panels(panels):
    """Unnamed traces take the name of an identically coloured, named trace in another
    panel of the same figure (stacked spectra labelled once, at the right)."""
    named = [(np.array(s.color_rgb, float), s.name) for p in panels for s in p.series if not s.name.startswith("series_")]
    for p in panels:
        own = {s.name for s in p.series}
        for s in p.series:
            if not s.name.startswith("series_"):
                continue
            c = np.array(s.color_rgb, float)
            cand = [(np.linalg.norm(c - nc), n) for nc, n in named if n not in own]
            if cand:
                d, n = min(cand)
                if d < 25 and sum(1 for dd, _ in cand if dd < 25) == 1:
                    s.name = n
                    own.add(n)


def _contour_panel(p: Panel, box, paths) -> bool:
    """Contour-line plots drawn as vector loops (2D NMR, PES maps): many closed stroked
    polylines inside the axes. Keeps every loop exactly, with its colour; dashed boxes
    and other strokes are kept as overlays."""
    inside = [q for q in paths if q.bbox[0] >= box.x0 - 2 and q.bbox[2] <= box.x1 + 2
              and q.bbox[1] >= box.y0 - 2 and q.bbox[3] <= box.y1 + 2]
    loops, overlays = [], []
    for q in inside:
        if q.stroke is None:
            continue
        dashed = bool(q.dashes) and q.dashes.strip() not in ("[] 0", "[]0", "")
        for poly in q.polys:
            ext = max(np.ptp(poly[:, 0]), np.ptp(poly[:, 1]))
            if ext >= 0.98 * max(box.w, box.h):
                continue
            closed = len(poly) >= 8 and np.hypot(*(poly[0] - poly[-1])) < 0.1 * max(ext, 1e-6)
            if closed and not dashed:
                loops.append((poly, tuple(int(round(255 * v)) for v in q.stroke[:3]), q.width))
            elif dashed or len(poly) <= 6:
                if len(poly) <= 6 and ext < 0.03 * max(box.w, box.h) and not dashed:
                    continue                              # tick marks
                overlays.append((poly, tuple(int(round(255 * v)) for v in q.stroke[:3]), q.width, dashed))
    strokes = sum(1 for q in inside if q.stroke is not None for poly in q.polys if len(poly) >= 8)
    big = [l for l in loops if max(np.ptp(l[0][:, 0]), np.ptp(l[0][:, 1])) > 0.05 * max(box.w, box.h)]
    sizes = {round(float(np.log(max(np.ptp(l[0][:, 0]), 1e-6))), 1) for l in loops}
    # contour levels: many loops, several of them large, in many different sizes (markers are all alike)
    if len(loops) < 6 or len(loops) < 0.5 * max(strokes, 1) or len(big) < 3 or len(sizes) < 4:
        return False
    p.kind = "contour"
    p.contours = [l[0] for l in loops]
    p.contour_style = [{"color": l[1], "width_px": l[2]} for l in loops]
    p.overlays = overlays
    if not getattr(p, "point_labels", None):
        # peak labels drawn as outlines inside the panel or just above it (2D NMR assignments)
        from .extract.vector_series import outlined_words
        region = (box.x0, box.y0 - 0.15 * box.h, box.x1, box.y1)
        p.point_labels = outlined_words(paths, region, max_h=0.12 * box.h)
    cols = sorted({l[1] for l in loops})
    p.notes.append({"level": "info", "code": "contour_lines",
                    "msg": f"{len(loops)} contour loops in {len(cols)} colour(s), taken exactly from the vector paths."})
    return True


def _relative_cal(axis, box):
    from .detect.calibration import calibrate
    if axis == "y":
        cal = calibrate("y", [box.y1, box.y0], [0.0, 1.0], scale="linear", tol=1e9, source="relative")
    else:
        cal = calibrate("x", [box.x0, box.x1], [0.0, 1.0], scale="linear", tol=1e9, source="relative")
    return cal


def _ycal_from_bar_values(paths, box, labels):
    """Bars with their values printed on top and no numbered y axis: value ∝ height."""
    from .detect.calibration import calibrate
    try:
        bars, _ = barmod.vector_bars(paths, box)
    except Exception:  # pragma: no cover
        return None
    if len(bars) < 2 or not barmod.plausible(bars, box) or not labels:
        return None
    pos, val = [], []
    for b in bars:
        best = None
        for l in labels:
            if l.value is None or getattr(l, "rotated", False):
                continue
            if b.x0 - 0.2 * (b.x1 - b.x0) <= l.cx <= b.x1 + 0.2 * (b.x1 - b.x0) and b.top - 0.25 * box.h <= l.bbox[3] <= b.top + 2:
                d = b.top - l.bbox[3]
                if best is None or d < best[0]:
                    best = (d, l)
        if best:
            pos.append(b.top)
            val.append(best[1].value)
    if len(pos) < 2:
        return None
    base = float(np.median([b.base for b in bars]))
    h = base - np.array(pos)
    k = float(np.sum(h * val) / np.sum(h * h))
    if np.max(np.abs(k * h - val) / np.maximum(np.abs(val), 1e-9)) > 0.03:
        return None            # printed values are not proportional to the bar heights
    return calibrate("y", [base] + pos, [0.0] + val, scale="linear", tol=1e9, source="bar-values")


def _expand(b, f):
    w, h = b[2] - b[0], b[3] - b[1]
    return (b[0] - f * w, b[1] - f * h, b[2] + f * w, b[3] + f * h)


def _panel_box(p):
    if p.box is not None:
        return p.box.as_tuple()
    if p.frame is not None:
        return p.frame.box
    return (0, 1e9, 0, 1e9)


def _reading_order(panels):
    hs = np.median([_panel_box(p)[3] - _panel_box(p)[1] for p in panels if p.box is not None or p.frame is not None] or [1])
    return sorted(panels, key=lambda p: (round(_panel_box(p)[3] / (0.5 * hs)), _panel_box(p)[0]))


def _image_panels(page, rgb, exclude, scale, particles, kind) -> List[Panel]:
    """Photographs, micrographs and insets on a page → one panel per frame (+ a derived
    series panel when frames carry numeric titles such as '5 min')."""
    emb = embedded_images(page, min_px=48) if page.pdf_page is not None else None
    frames = imagefig.find_frames(page, rgb, emb or None, exclude=exclude) if emb else []
    vector_frames = bool(frames)
    if not frames:
        frames = imagefig.find_frames(page, rgb, None, exclude=exclude)
        if exclude:   # mixed plot + photo pages: only clearly photographic regions
            frames = [f for f in frames if imagefig.looks_photographic(f.rgb)]
            for i, f in enumerate(frames):
                f.parent, f.children = None, []
    if not frames:
        return []
    if len(frames) == 1 and frames[0].source == "raster" and frames[0].w * frames[0].h > 0.8 * rgb.shape[0] * rgb.shape[1]:
        return []          # the whole bitmap is one image: the classic micrograph path handles it
    page_text = []
    if vector_frames:
        blocks = imagefig.vector_text_blocks(page.pdf_page, page.scale, page.meta.get("offset_px", (0, 0)))
        page_text = imagefig.attach_vector_content(page, frames, blocks)
        imagefig.vector_scale_bars(frames, blocks, page)
    else:
        imagefig.raster_titles(rgb, frames)
        for f in frames:
            try:
                f.annotations = imagefig.raster_annotations(f.rgb)
            except Exception:  # pragma: no cover
                f.annotations = []
    imagefig.analyse_frames(frames, scale)
    out = []
    mode = "vector" if vector_frames else "raster"
    order_all = []
    for i in imagefig.reading_order(frames):        # parents in reading order, each followed by its insets
        order_all.append(i)
        order_all += sorted(frames[i].children, key=lambda c: (frames[c].box[1], frames[c].box[0]))
    order_all += [i for i in range(len(frames)) if i not in order_all]
    for i in order_all:
        fr = frames[i]
        gray = fr.gray
        mask = np.zeros(gray.shape, bool)
        if fr.bar is not None and fr.bar.panel_box is not None:
            x0, y0, x1, y1 = fr.bar.panel_box
            mask[max(0, y0 - 2):y1 + 2, max(0, x0 - 2):x1 + 2] = True
        r = micrograph.MicroResult(gray, fr.bar, fr.nm_per_px, mask, None, [])
        if particles and fr.parent is None and not fr.children and not fr.is_colour and not fr.lattice and len(frames) == 1:
            try:
                r.particles = micrograph.analyse_particles(gray, ~mask, fr.nm_per_px)
            except Exception:  # pragma: no cover
                pass
        p = Panel("p", "micrograph", mode + ("-image" if mode == "vector" else ""), page, micro=r)
        p.frame, p.frames, p.title = fr, frames, fr.title
        p.notes.extend(fr.notes)
        if fr.parent is not None:
            p.notes.insert(0, {"level": "info", "code": "inset", "msg": "Inset of the frame it sits on."})
        out.append(p)
    # numbers in frame titles → per-frame measurements as data series
    order = imagefig.reading_order(frames)
    ser = imagefig.frame_series(frames, order)
    if ser:
        sp = Panel("p", "line", "derived", page)
        heading = " ".join(b["text"] for b in page_text).strip()
        for k, s_ in enumerate(ser["series"]):
            col = (0, 0, 0)
            cname = s_["name"].split()[0]
            for fr in frames:
                for a in fr.annotations:
                    if imagefig.colour_name(a.color) == cname:
                        col = tuple(int(v) for v in a.color)
            name = f"{heading}: {s_['name']}" if heading else s_["name"]
            sd = s_["sd"]
            ser_obj = curves.Series(name, "line", col, s_["x"], s_["y"], s_["x"], s_["y"],
                                    yerr_lo=sd if np.isfinite(sd).any() else None,
                                    yerr_hi=sd if np.isfinite(sd).any() else None, source="frames")
            sp.series.append(ser_obj)
        sp.xlabel, sp.ylabel = ser["xlabel"], ser["ylabel"]
        sp.frames = frames
        sp.notes.append({"level": "info", "code": "frame_series",
                         "msg": f"{len(ser['series'])} series measured on {len(order)} frames titled "
                                + ", ".join(repr(frames[i].title) for i in order) + "."})
        if ser["yunit"] == "px":
            sp.notes.append({"level": "warn", "code": "units_px",
                             "msg": "Lengths are in native image pixels (no scale bar); all frames must share one magnification "
                                    "for the trend to be meaningful. Give --scale for physical units."})
        out.append(sp)
    return out


def _bar_panel(p: Panel, page, rgb, box, mode, paths, text_labels) -> bool:
    bars, stray = ([], [])
    if mode == "vector" and paths is not None:
        bars, stray = barmod.vector_bars(paths, box)
    if not barmod.plausible(bars, box):
        bars = []
    else:
        barmod.vector_errorbars(paths, bars, box)
    raster_mode = False
    if len(bars) < 2:
        bars = barmod.raster_bars(rgb, box)
        raster_mode = True
        if bars:
            barmod.raster_errorbars(rgb, bars, box)
    if not barmod.plausible(bars, box):
        return False
    if raster_mode and mode == "vector":
        p.mode = "raster+vector-axes"
    if box.xcal is not None and not getattr(box, "xcategories", None) and len(bars) < 2:
        return False
    inner = [l for l in (text_labels or []) if box.x0 < l.cx < box.x1 and box.y0 - 0.1 * box.h < l.cy < box.y1]
    if not inner:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        inner = ocr.find_labels(gray, (box.x0 + 2, box.y0 - 0.1 * box.h, box.x1 - 2, box.y1 - 2), numeric=True)
    legend_names = _bar_legend(paths, box, text_labels, bars) if mode == "vector" and paths is not None else {}
    if legend_names:
        stray = [st for st in stray if not any(abs(0.5 * (st.bbox[1] + st.bbox[3]) - y) < 2 * (st.bbox[3] - st.bbox[1]) + 4
                                               for y in legend_names.get("_rows", []))]
    if legend_names and not getattr(box, "xcategories", None):
        for b in bars:
            b.category = legend_names.get(tuple(b.color), b.category)
        box.xcategories = []
        p.notes.append({"level": "info", "code": "bar_legend", "msg": "Bar names taken from the colour legend inside the plot."})
    elif not getattr(box, "xcategories", None):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        words = barmod.ocr_categories(gray, box, len(bars))
        if len(words) != len(bars):
            H = gray.shape[0]
            reg = (box.x0 - 0.05 * box.w, box.y1 + box.xtick_out + 2, box.x1 + 0.05 * box.w, min(H, box.y1 + 0.15 * box.h))
            w2 = [l for l in ocr.find_labels(gray, reg, numeric=False) if l.text.strip()]
            for l in w2:
                t, _ = ocr.read_text(gray[int(l.bbox[1]) - 2:int(l.bbox[3]) + 2, int(l.bbox[0]) - 2:int(l.bbox[2]) + 2])
                l.text = t.strip() or l.text
            if abs(len(w2) - len(bars)) < abs(len(words) - len(bars)):
                words = w2
        words = [l for l in words if l.text]
        # OCR case slips ("2H" next to "4h"): make number+unit labels follow the majority case
        pat = [l for l in words if re.fullmatch(r"\d+(\.\d+)?[A-Za-z]{1,3}", l.text)]
        if len(pat) >= 2:
            low = sum(l.text[-1].islower() for l in pat)
            for l in pat:
                l.text = re.sub(r"[A-Za-z]+$", lambda m: m.group(0).lower() if low >= len(pat) - low else m.group(0).upper(), l.text)
        box.xcategories = sorted(words, key=lambda l: l.cx)
    barmod.assign_labels(bars, box, inner)
    p.notes.extend(barmod.finish(bars, box))
    for b in bars:
        p.notes.extend(b.notes)
    for st in stray:
        p.notes.append({"level": "warn", "code": "stray_shape",
                        "msg": f"A filled shape (rgb{tuple(int(v * 255) for v in st.fill)}) at x≈{0.5 * (st.bbox[0] + st.bbox[2]):.0f}px "
                               "does not stand on the axis: likely a misplaced copy in the drawing; ignored."})
    p.bars = sorted(bars, key=lambda b: b.cx)
    p.kind = "bar"
    # the x axis of a bar chart is categorical: drop any numeric x calibration and its notes
    box.xcal = None
    p.notes = [n for n in p.notes if not n["code"].startswith("x_") or n["code"] == "x_categorical"]
    if not any(n["code"] == "x_categorical" for n in p.notes) and box.xcategories:
        p.notes.insert(0, {"level": "info", "code": "x_categorical",
                           "msg": "x-axis is categorical: " + ", ".join(l.text for l in box.xcategories)})
    return True


def _series_panel(p: Panel, page, rgb, box, mode, paths, chars, kind, max_series):
    series = []
    if mode == "vector":
        series, info = extract_vector_series(page, box, paths, chars)
        p.gridlines = info.get("grid", 0) >= 3
        p.point_labels = info.get("point_labels", [])
        if not series:
            p.notes.append({"level": "info", "code": "raster_fallback",
                            "msg": "No vector data paths in the plot area (embedded bitmap?); used image analysis."})
            p.mode = "raster+vector-axes"
    if not series:
        series, info = curves.extract_series(rgb, box, _char_h(box), max_series, kind)
        p.notes.extend(info.get("notes", []))
    for s in series:
        s.to_data(box)
        if s.yerr_lo is not None:
            s.yerr_lo = np.abs(box.ycal.to_data(s.yerr_lo) - s.y)   # store as +/- magnitudes
            s.yerr_hi = np.abs(box.ycal.to_data(s.yerr_hi) - s.y)
        p.notes.extend(s.notes)
        p.notes.extend(anomaly.series_checks(s, box))
    p.notes.extend(anomaly.duplicate_series(series))
    p.series = series
    p.kind = "scatter" if series and all(s.kind == "markers" for s in series) else "line"


def _map_panel(p: Panel, page, rgb, box, cb, text_labels):
    if cb is None:
        p.notes.append({"level": "error", "code": "no_colorbar",
                        "msg": "Filled map without a detectable colour bar: values cannot be recovered "
                               "(only the image is replotted)."})
        p.kind = "heatmap"
        return
    heatmap.calibrate_colorbar(rgb, cb, text_labels)
    image = None
    if page.pdf_page is not None:
        for im in embedded_images(page, min_px=40):
            r = [v * page.scale for v in im["rect"]]
            ov = max(0, min(r[2], box.x1) - max(r[0], box.x0)) * max(0, min(r[3], box.y1) - max(r[1], box.y0))
            if ov > 0.8 * box.w * box.h:
                image = (im["rgb"], tuple(r))
                p.mode = "embedded-image"
                p.notes.append({"level": "info", "code": "native_image",
                                "msg": f"Map stored as an embedded {im['rgb'].shape[1]}×{im['rgb'].shape[0]} image: "
                                       "values read from its native pixels."})
                break
    p.grid = heatmap.extract_grid(rgb, box, cb, image=image)
    p.colorbar = cb
    p.kind = "contourf" if cb.discrete else "heatmap"
    p.notes.extend(p.grid.notes)
    try:
        p.contours = heatmap.contour_lines(rgb, box, cb)
    except Exception:
        p.contours = []


def _micro_panel(page, rgb, scale, particles, mode="raster") -> Panel:
    r = micrograph.analyse_micrograph(rgb, particles=False)
    if scale:
        m = re.match(r"\s*([\d.]+)\s*=\s*([\d.]+)\s*(\S+)", scale)
        if m:
            px, val, unit = float(m.group(1)), float(m.group(2)), m.group(3).replace("um", "µm")
            r.nm_per_px = val * micrograph.UNIT_NM.get(unit, 1.0) / px
            r.notes.append({"level": "info", "code": "scale_manual", "msg": f"Manual scale {scale} → {r.nm_per_px:.4g} nm/px."})
    if particles:
        try:
            r.particles = micrograph.analyse_particles(r.gray, ~r.annotation_mask, r.nm_per_px)
        except Exception as exc:
            r.notes.append({"level": "warn", "code": "particles_failed", "msg": str(exc)})
    p = Panel("p", "micrograph", mode, page, micro=r)
    p.notes.extend(r.notes)
    return p


# ───────────────────────── outputs ─────────────────────────
def _cmap_from_colorbar(cb: heatmap.ColorBar):
    from matplotlib.colors import ListedColormap
    from skimage.color import lab2rgb
    lut = cb.lut_lab if not cb.discrete else np.stack([b[2] for b in cb.bands])
    rgbl = np.clip(lab2rgb(lut[None].astype(np.float64))[0], 0, 1)
    # colour-bar position runs top→bottom (v) or left→right (h); values must increase along the cmap
    v = cb.cal.to_data(cb.lut_pos if not cb.discrete else np.array([0.5 * (b[0] + b[1]) for b in cb.bands]))
    if v[0] > v[-1]:
        rgbl = rgbl[::-1]
    return ListedColormap(rgbl, name="from_colorbar")


def panel_spec(p: Panel) -> Optional[dict]:
    """Plot-engine spec that re-creates the panel from the extracted data."""
    spec = _panel_spec(p)
    ts = getattr(p.box, "title_style", None) if p.box is not None else None
    if spec is not None and ts:
        for k, st in ts.items():
            if spec.get(k + "label"):
                spec[k + "label_style"] = st
    return spec


def _panel_spec(p: Panel) -> Optional[dict]:
    if p.kind in ("line", "scatter") and p.series:
        ser, ann = [], []
        for s in p.series:
            d = {"x": np.asarray(s.x), "y": np.asarray(s.y), "label": s.name, "kind": s.kind,
                 "color": "#%02x%02x%02x" % tuple(s.color_rgb), "dashed": s.dashed}
            if s.yerr_lo is not None:
                d["yerr_lo"], d["yerr_hi"] = s.yerr_lo, s.yerr_hi
            if s.kind == "line" and s.source == "vector":
                d["sort"] = False
            if s.source == "frames":
                d["markers_and_line"] = True
            st = s.style or {}
            if st.get("linestyle"):
                d["linestyle"] = st["linestyle"]
            if s.kind == "line" and s.name.startswith("series_"):
                twin = next((o for o in p.series if o is not s and o.kind == "markers" and not o.name.startswith("series_")
                             and np.linalg.norm(np.array(o.color_rgb) - np.array(s.color_rgb)) < 40), None)
                if twin is not None:          # a fit/guide line drawn in a named marker series' colour
                    d["label"] = "_" + twin.name + " (line)"
            if s.kind == "markers" and st.get("marker"):
                d["marker"] = st["marker"]
                if st.get("face") is not None:
                    d["mfc"] = "#%02x%02x%02x" % tuple(st["face"])
                    d["color"] = d["mfc"]
                if st.get("edge") is not None:
                    d["mec"] = "#%02x%02x%02x" % tuple(st["edge"])
            if p.box is not None and p.box.w > 0 and s.source == "vector":
                # sizes as a fraction of the plot width, so the replot keeps the source's proportions
                if s.kind == "markers" and st.get("marker_px"):
                    # matplotlib's 'D' size is the side of the rotated square, not its diagonal
                    ext = float(st["marker_px"]) / (np.sqrt(2) if st.get("marker") == "D" else 1.0)
                    d["ms_frac"] = round(ext / p.box.w, 5)
                    if st.get("edge_px"):
                        d["mew_frac"] = round(float(st["edge_px"]) / p.box.w, 6)
                if s.kind == "line" and st.get("width_px"):
                    d["lw_frac"] = round(float(st["width_px"]) / p.box.w, 6)

            ser.append(d)
        spec = {"type": "line", "series": ser, "xlim": p.xlim, "ylim": p.ylim,
                "xscale": p.box.xcal.scale if p.box else "linear", "yscale": p.box.ycal.scale if p.box else "linear",
                "xlabel": p.xlabel, "ylabel": p.ylabel}
        tick_sz = [getattr(l, "size", None) for l in (p.box.xlabels + p.box.ylabels if p.box else [])]
        tick_sz = float(np.median([v for v in tick_sz if v])) if any(tick_sz) else None
        for lab in getattr(p, "point_labels", []) or []:
            bx = lab.bbox
            a = {"text": getattr(lab, "display", lab.text) or lab.text,
                 "xy": [float(p.box.xcal.to_data(0.5 * (bx[0] + bx[2]))), float(p.box.ycal.to_data(0.5 * (bx[1] + bx[3])))],
                 "color": "#%02x%02x%02x" % tuple(getattr(lab, "color", None) or (0, 0, 0)),
                 "ha": "center", "va": "center"}
            if getattr(lab, "bold", False):
                a["weight"] = "bold"
            if tick_sz and getattr(lab, "size", None):
                a["size_rel"] = round(float(lab.size) / tick_sz, 3)     # relative to the tick labels
            ann.append(a)
        if ann:
            spec["annotations"] = ann
        # a legend only when the series are not named by labels placed on the plot itself
        spec["legend"] = len(ser) > 1 and any(not s.name.startswith("series_") for s in p.series) and not ann
        for ax_, cal in (("x", p.box.xcal if p.box else None), ("y", p.box.ycal if p.box else None)):
            if cal is not None and cal.source in ("vector-text", "ocr") and len(cal.values) >= 3 and cal.scale == "linear":
                spec[ax_ + "ticks"] = sorted(float(v) for v in cal.values)      # major ticks where the source had them
        if p.mode == "derived":
            spec["aspect"] = 2.6          # a short strip under the image row
        if p.box is not None and getattr(p.box, "no_yaxis", False):
            spec["no_yaxis"] = True
            spec["legend"] = False
        if p.box is not None and p.box.ycal is not None and p.box.ycal.source in ("relative", "bar-values"):
            spec["hide_yticklabels"] = True
            if p.box.ycal.source == "relative" and p.box.yticks:
                yt = [t for t in p.box.yticks
                      if not (getattr(p.box, "framed", False) and min(abs(t - p.box.y0), abs(t - p.box.y1)) < 0.005 * p.box.h)]
                # (in a framed plot, "ticks" at the very ends are the frame's corners)
                spec["yticks"] = sorted(float(v) for v in p.box.ycal.to_data(np.array(yt)))
        if p.box is not None and abs(p.box.w / p.box.h - 1) < 0.04:
            spec["aspect"], spec["fixed_aspect"] = 1.0, True     # square plots (parity plots) stay square
        if p.gridlines:
            spec["grid"] = True
        _minor_from_source(spec, p)
        if p.xlim and p.xlim[0] > p.xlim[1]:
            spec["xlim"] = p.xlim  # reversed axes are kept reversed
        return spec
    if p.kind == "bar" and p.bars:
        sp = _bar_spec(p)
        if p.box is not None and p.box.ycal is not None and p.box.ycal.source == "bar-values":
            sp["hide_yticklabels"] = True
            if not p.box.yticks:
                sp["hide_yticks"] = True      # the source has no y ticks at all
        return sp
    return _other_spec(p)


def _minor_from_source(spec: dict, p: Panel):
    """Minor ticks only where the source has them (vector files, where ticks are exact)."""
    b = p.box
    if b is None or p.mode != "vector":
        return
    if len(b.xticks) >= 2 and not b.xticks_minor:
        spec["xminor"] = False
    if len(b.yticks) >= 2 and not b.yticks_minor:
        spec["yminor"] = False


def _bar_spec(p):
    if True:
        return {"type": "bar", "categories": [b.category for b in p.bars], "values": [b.value for b in p.bars],
                "colors": ["#%02x%02x%02x" % tuple(b.color) for b in p.bars], "ylabel": p.ylabel, "xlabel": p.xlabel,
                "errors": ([[b.err_minus or 0 for b in p.bars], [b.err_plus or 0 for b in p.bars]]
                           if any(b.err_plus is not None for b in p.bars) else None),
                "ylim": [min(0.0, p.ylim[0]) if p.ylim else 0.0, p.ylim[1] if p.ylim else None],
                "value_labels": any(b.annotated is not None for b in p.bars),
                "label_values": [b.annotated if b.annotated is not None else b.value for b in p.bars]}


def _contour_spec(p):
    b = p.box
    lines = []
    for c, st in zip(p.contours, p.contour_style):
        lines.append({"xy": np.c_[b.xcal.to_data(c[:, 0]), b.ycal.to_data(c[:, 1])],
                      "color": "#%02x%02x%02x" % st["color"]})
    for poly, col, w, dashed in getattr(p, "overlays", []):
        lines.append({"xy": np.c_[b.xcal.to_data(poly[:, 0]), b.ycal.to_data(poly[:, 1])],
                      "color": "#%02x%02x%02x" % col, "dashed": dashed, "overlay": True})
    spec = {"type": "paths", "lines": lines, "xlim": p.xlim, "ylim": p.ylim, "xlabel": p.xlabel, "ylabel": p.ylabel,
            "title": p.title}
    if p.title and getattr(p, "title_style", None):
        spec["title_style"] = p.title_style
    if getattr(p, "title_span", 1) > 1:
        spec["title_span"] = p.title_span
    for ax_, cal in (("x", b.xcal), ("y", b.ycal)):
        if cal is not None and cal.source in ("vector-text", "ocr", "shared") and len(cal.values) >= 2:
            spec[ax_ + "ticks"] = sorted(float(v) for v in cal.values)
    if getattr(b, "y_right", False):
        spec["y_right"] = True
    labs = getattr(p, "point_labels", None) or []
    if labs:
        tick_h = [l.bbox[3] - l.bbox[1] for l in (b.xlabels + b.ylabels)]
        def cap_h(l):
            h = getattr(l, "glyph_h", l.bbox[3] - l.bbox[1])
            # lower-case letters without ascenders ("a", "e") are only x-height tall
            return h / 0.72 if l.text and set(l.text) <= set("acemnorsuvwxz") else h
        font_h = max(cap_h(l) for l in labs)            # one font size per panel
        rel = round(font_h / float(np.median(tick_h)), 3) if tick_h else None
        spec["annotations"] = []
        for l in labs:
            a = {"text": l.text, "xy": [float(b.xcal.to_data(0.5 * (l.bbox[0] + l.bbox[2]))),
                                        float(b.ycal.to_data(0.5 * (l.bbox[1] + l.bbox[3])))],
                 "color": "#%02x%02x%02x" % tuple(l.color), "ha": "center", "va": "center"}
            if rel:
                a["size_rel"] = rel
            spec["annotations"].append(a)
    if b.ycal is not None and b.ycal.source == "shared":
        spec["hide_yticklabels"] = True
    spec["aspect"], spec["fixed_aspect"] = b.w / b.h, True
    _minor_from_source(spec, p)
    return spec


def _other_spec(p):
    if p.kind == "contour" and p.contours:
        return _contour_spec(p)
    if p.kind in ("heatmap", "contourf") and p.grid is not None:
        g = p.grid
        spec = {"type": "heatmap" if p.kind == "heatmap" else "contourf", "x": g.x, "y": g.y, "z": g.z,
                "xlabel": p.xlabel, "ylabel": p.ylabel, "clabel": p.clabel, "xlim": p.xlim, "ylim": p.ylim,
                "cmap": _cmap_from_colorbar(p.colorbar)}
        cal = p.colorbar.cal
        v = cal.to_data(np.array([p.colorbar.lut_pos[0], p.colorbar.lut_pos[-1]]))
        spec["vmin"], spec["vmax"] = float(min(v)), float(max(v))
        if p.kind == "contourf":
            lv = sorted(set(np.round(np.r_[g.lo[np.isfinite(g.lo)], g.hi[np.isfinite(g.hi)]], 10)))
            spec["levels"] = lv
            spec["extend"] = "max" if np.isinf(g.hi).any() else "neither"
            spec.pop("vmin"); spec.pop("vmax")
        return spec
    if p.kind == "micrograph" and p.frame is not None:
        return _frame_spec(p)
    if p.kind == "micrograph" and p.micro is not None:
        r = p.micro
        img = r.gray.copy()
        H = img.shape[0]
        if r.annotation_mask.any():
            rows = np.nonzero(r.annotation_mask.any(axis=1))[0]
            if rows.min() > 0.8 * H:          # annotation band at the bottom: crop it off
                img = img[:rows.min()]
            elif rows.max() < 0.2 * H:        # … or at the top
                img = img[rows.max() + 1:]
            else:
                img = cv2.inpaint(img, r.annotation_mask.astype(np.uint8), 5, cv2.INPAINT_TELEA)
        return {"type": "image", "z": img, "nm_per_px": r.nm_per_px, "scalebar": True}
    return None


def _frame_spec(p: Panel) -> dict:
    """Image panel: native pixels, insets, vector overlays, editable text, scale bar."""
    fr = p.frame
    img = fr.rgb if fr.is_colour else fr.gray
    spec = {"type": "image", "z": img, "nm_per_px": fr.nm_per_px, "title": fr.title, "scalebar": False}
    drawn_bar = fr.bar is not None and getattr(fr.bar, "_source", "") == "vector"
    burnt_visible = (fr.bar is not None and getattr(fr.bar, "_source", "") == "pixels") or \
        (fr.instrument_bar is not None and fr.instrument_bar.get("visible"))
    if fr.nm_per_px and fr.parent is None and not drawn_bar and not burnt_visible:
        spec["scalebar"] = True          # calibrated (e.g. from a clipped instrument bar) but no bar shown
    if fr.parent is None and p.frames:
        spec["insets"] = []
        for c in fr.children:
            ch = p.frames[c]
            x, y = fr.to_native([ch.box[0], ch.box[2]], [ch.box[1], ch.box[3]])
            spec["insets"].append({"z": ch.rgb if ch.is_colour else ch.gray,
                                   "box": [float(x[0]), float(y[0]), float(x[1]), float(y[1])], "frame": False})
        spec["paths"] = list(fr.drawings)          # the authors' own overlays and scale bar, as vectors
        spec["texts"] = list(fr.texts)
    return spec


def write_outputs(panels: List[Panel], out_dir: str, template: str = "natchem",
                  formats: Sequence[str] = ("pdf", "svg", "png"), width="single", stem: str = "figure"):
    """CSV/JSON data, overlays, replots (per panel and combined) and an HTML report."""
    from .plot.engine import figure, save
    from . import report
    import matplotlib.pyplot as plt
    os.makedirs(out_dir, exist_ok=True)
    specs, rowkeys = [], []
    inset_specs = {}
    for q in panels:
        par = getattr(q.box, "inset_of", None) if q.box is not None else None
        if par is not None and any(o.box is par for o in panels):
            sp = panel_spec(q)
            if sp is not None:
                b = q.box
                inset_specs.setdefault(id(par), []).append(
                    {"spec": sp, "bounds": [(b.x0 - par.x0) / par.w, (par.y1 - b.y1) / par.h, b.w / par.w, b.h / par.h],
                     "panel": q.id})
    for p in panels:
        base = os.path.join(out_dir, f"{stem}_{p.id}")
        p.files = {}
        meta = {"id": p.id, "source": p.page.source, "page": p.page.index + 1, "kind": p.kind, "mode": p.mode,
                "xlabel": p.xlabel, "ylabel": p.ylabel, "notes": p.notes}
        if p.box is not None:
            meta["plot_box_px"] = [float(v) for v in p.box.as_tuple()]
            meta["x_calibration"] = p.box.xcal.as_dict() if p.box.xcal else None
            meta["y_calibration"] = p.box.ycal.as_dict() if p.box.ycal else None
            meta["xlim"], meta["ylim"] = p.xlim, p.ylim
        if p.series:
            rows = ["series,x,y,yerr_minus,yerr_plus,kind,source"]
            for s in p.series:
                for i in range(len(s.x)):
                    lo = s.yerr_lo[i] if s.yerr_lo is not None else np.nan
                    hi = s.yerr_hi[i] if s.yerr_hi is not None else np.nan
                    rows.append(f"{_csvq(s.name)},{s.x[i]:.10g},{s.y[i]:.10g},{lo:.6g},{hi:.6g},{s.kind},{s.source}")
            Path(base + "_data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
            p.files["data"] = base + "_data.csv"
            meta["series"] = [{"name": s.name, "kind": s.kind, "n": int(len(s.x)), "color": s.color_rgb,
                               "dashed": s.dashed, "source": s.source,
                               "x_range": [float(np.nanmin(s.x)), float(np.nanmax(s.x))]} for s in p.series]
        if p.bars:
            rows = ["category,value,err_plus,err_minus,annotated_value,x_left_px,x_right_px,top_px,color_hex"]
            for b in p.bars:
                ep = "" if b.err_plus is None else f"{b.err_plus:.6g}"
                em = "" if b.err_minus is None else f"{b.err_minus:.6g}"
                rows.append(f"{_csvq(b.category)},{b.value:.8g},{ep},{em},{'' if b.annotated is None else f'{b.annotated:g}'},"
                            f"{b.x0:.3f},{b.x1:.3f},{b.top:.3f},#{b.color[0]:02x}{b.color[1]:02x}{b.color[2]:02x}")
            Path(base + "_bars.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
            p.files["data"] = base + "_bars.csv"
            meta["bars"] = [{"category": b.category, "value": b.value, "annotated": b.annotated,
                             "color": b.color, "slices": b.n_parts} for b in p.bars]
        if p.grid is not None:
            g = p.grid
            m = np.vstack([np.r_[np.nan, g.x], np.c_[g.y, g.z]])
            np.savetxt(base + "_grid.csv", m, delimiter=",", fmt="%.8g",
                       header="first row: x, first column: y, body: z")
            np.savez_compressed(base + "_grid.npz", x=g.x, y=g.y, z=g.z, filled=g.filled,
                                **({"lo": g.lo, "hi": g.hi} if g.lo is not None else {}))
            p.files["data"] = base + "_grid.csv"
            p.files["npz"] = base + "_grid.npz"
            meta["grid_shape"] = list(g.z.shape)
            meta["z_range"] = [float(np.nanmin(g.z)), float(np.nanmax(g.z))]
            meta["colorbar"] = {"discrete": p.colorbar.discrete, "calibration": p.colorbar.cal.as_dict(),
                                "n_bands": len(p.colorbar.bands)}
            if p.contours:
                with open(base + "_contours.csv", "w", encoding="utf-8") as fh:
                    fh.write("contour,x,y\n")
                    for k, c in enumerate(p.contours):
                        xs = p.box.xcal.to_data(c[:, 0]); ys = p.box.ycal.to_data(c[:, 1])
                        for a, b in zip(xs, ys):
                            fh.write(f"{k},{a:.8g},{b:.8g}\n")
                p.files["contours"] = base + "_contours.csv"
        if p.kind == "contour" and p.contours and p.grid is None:
            with open(base + "_contours.csv", "w", encoding="utf-8") as fh:
                fh.write("contour,x,y,color\n")
                for k, (c, st) in enumerate(zip(p.contours, p.contour_style)):
                    xs = p.box.xcal.to_data(c[:, 0]); ys = p.box.ycal.to_data(c[:, 1])
                    col = "#%02x%02x%02x" % st["color"]
                    for a, b in zip(xs, ys):
                        fh.write(f"{k},{a:.8g},{b:.8g},{col}\n")
            p.files["data"] = base + "_contours.csv"
            meta["n_contours"] = len(p.contours)
            meta["xlim"], meta["ylim"] = p.xlim, p.ylim
        if p.frame is not None:
            _write_frame(p, base, meta)
        elif p.micro is not None:
            r = p.micro
            meta["nm_per_px"] = r.nm_per_px
            if r.bar:
                meta["scale_bar"] = {"length_px": r.bar.length_px, "value": r.bar.value, "unit": r.bar.unit,
                                     "text": r.bar.text, "box": r.bar.panel_box}
            from PIL import Image
            im = Image.fromarray(r.gray)
            if r.nm_per_px:
                ppcm = 1e7 / r.nm_per_px  # pixels per cm
                im.save(base + "_calibrated.tif", resolution=ppcm, resolution_unit=3)
            else:
                im.save(base + "_calibrated.tif")
            p.files["image"] = base + "_calibrated.tif"
            if r.particles:
                pr = r.particles
                meta["particles"] = pr["stats"]
                with open(base + "_particles.csv", "w", encoding="utf-8") as fh:
                    fh.write("id,cx_px,cy_px,area_px,eq_diam_px,eq_diam_nm,eccentricity,touches_edge\n")
                    for k, q in enumerate(pr["particles"]):
                        fh.write(f"{k},{q['cx_px']:.2f},{q['cy_px']:.2f},{q['area_px']},{q['eq_diam_px']:.3f},"
                                 f"{q['eq_diam_nm'] if q['eq_diam_nm'] is not None else ''},{q['eccentricity']:.3f},{int(q['edge'])}\n")
                p.files["data"] = base + "_particles.csv"
        Path(base + "_meta.json").write_text(json.dumps(meta, indent=1, default=_json), encoding="utf-8")
        p.files["meta"] = base + "_meta.json"
        # overlay for visual verification
        try:
            p.files["overlay"] = report.overlay(p, base + "_overlay.png")
        except Exception as exc:  # pragma: no cover
            p.notes.append({"level": "warn", "code": "overlay_failed", "msg": str(exc)})
        spec = panel_spec(p)
        if spec is not None and p.box is not None and id(p.box) in inset_specs:
            spec["inset_axes"] = inset_specs[id(p.box)]
        is_inset_plot = p.box is not None and getattr(p.box, "inset_of", None) is not None and \
            any(id(p.box.inset_of) == k for k in inset_specs)
        if spec is not None:
            if not (p.frame is not None and p.frame.parent is not None) and not is_inset_plot:   # insets live inside their parent
                specs.append(spec)
                rowkeys.append(_source_row(p))
            try:
                fig, _, _ = figure([spec], template=template, width=width, labels=False)
                p.files["replot"] = save(fig, base + "_replot", formats)
                plt.close(fig)
            except Exception as exc:
                p.notes.append({"level": "warn", "code": "replot_failed", "msg": f"Replot failed: {exc}"})
        if p.micro is not None and p.micro.particles and p.micro.particles["stats"]:
            d = [q["eq_diam_nm"] if p.micro.nm_per_px else q["eq_diam_px"] for q in p.micro.particles["particles"] if not q["edge"]]
            hs = {"type": "hist", "values": d, "xlabel": "Diameter (nm)" if p.micro.nm_per_px else "Diameter (px)",
                  "ylabel": "Count"}
            specs.append(hs)
    if len(specs) > 1:
        rows = _rows_from_source(rowkeys)
        cols = _columns_from_source(rows, rowkeys)
        try:
            fig, _, _ = figure(specs, template=template, width="double", rows=rows, cols=cols)
        except Exception:
            fig, _, _ = figure(specs, template=template, width="double")
        combined = save(fig, os.path.join(out_dir, f"{stem}_combined"), formats)
        plt.close(fig)
    else:
        combined = []
    rep = report.html(panels, os.path.join(out_dir, f"{stem}_report.html"), combined, template)
    return {"report": rep, "combined": combined, "panels": [p.files for p in panels]}


def _write_frame(p: Panel, base: str, meta: dict):
    from PIL import Image
    fr = p.frame
    meta.update({"title": fr.title, "frame_box_px": [float(v) for v in fr.box], "native_size": list(fr.rgb.shape[1::-1]),
                 "native_px_per_page_px": [fr.sx, fr.sy], "source": fr.source, "nm_per_px": fr.nm_per_px,
                 "parent": None if fr.parent is None else p.frames.index(p.frames[fr.parent]),
                 "labels": [{"text": l["text"], "box": l["box"]} for l in fr.labels],
                 "d_spacing_labels": [{k: v for k, v in d.items() if k != "box"} for d in fr.dlabels],
                 "lattice": fr.lattice, "registration": getattr(fr, "registration", None)})
    if fr.bar is not None:
        meta["scale_bar"] = {"length_px": fr.bar.length_px, "value": fr.bar.value, "unit": fr.bar.unit,
                             "text": fr.bar.text, "source": getattr(fr.bar, "_source", "pixels")}
    img = Image.fromarray(fr.rgb if fr.is_colour else fr.gray)
    img.save(base + "_image.png")
    if fr.nm_per_px:
        img.save(base + "_calibrated.tif", resolution=1e7 / fr.nm_per_px, resolution_unit=3)
        p.files["image"] = base + "_calibrated.tif"
    else:
        p.files["image"] = base + "_image.png"
    p.files["native"] = base + "_image.png"
    rows = ["kind,color,x0_px,y0_px,x1_px,y1_px,length_px,length,unit,angle_deg,dashed,source"]
    for a in fr.annotations:
        if a.kind == "head":
            continue
        q = a.pts
        L = a.length_px
        v, u = imagefig.to_unit(L * fr.nm_per_px) if fr.nm_per_px else (L, "px")
        rows.append(f"{a.kind},{a.hex},{q[0, 0]:.3f},{q[0, 1]:.3f},{q[-1 if a.kind != 'rect' else 2, 0]:.3f},"
                    f"{q[-1 if a.kind != 'rect' else 2, 1]:.3f},{L:.3f},{v:.6g},{u},{a.angle_deg:.2f},{int(a.dashed)},{a.source}")
    for pr in getattr(fr, "_pairs", []):
        L = pr["sep_px"]
        v, u = imagefig.to_unit(L * fr.nm_per_px) if fr.nm_per_px else (L, "px")
        rows.append(f"line_pair_separation,{pr['color']},,,,,{L:.3f},{v:.6g},{u},,0,{pr['lines'][0].source}")
    if len(rows) > 1:
        Path(base + "_annotations.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        p.files["annotations"] = base + "_annotations.csv"
    if fr.lattice:
        rows = ["rank,period_px,d_nm,angle_deg,snr"]
        for k, pk in enumerate(fr.lattice, 1):
            rows.append(f"{k},{pk['period_px']:.4f},{pk.get('d_nm', float('nan')):.5g},{pk['angle_deg']:.2f},{pk['snr']:.1f}")
        Path(base + "_lattice.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        p.files["data"] = base + "_lattice.csv"


def _source_row(p: Panel):
    """(kind, y-centre, height, x) of a panel on the source page – keeps the source rows."""
    if p.frame is not None:
        b = p.frame.box
        return ("image", 0.5 * (b[1] + b[3]), b[3] - b[1], b[0], b[2])
    if p.box is not None:
        b = p.box
        return ("plot", 0.5 * (b.y0 + b.y1), b.y1 - b.y0, b.x0, b.x1)
    return ("derived", None, None, None, None)


def _columns_from_source(rows, keys):
    """Column index of every panel when the source panels sit on a common column grid
    (e.g. a 6-panel row under a 4-panel row whose first cells hold a drawing): rows then
    keep one panel size and their empty cells. None when the panels are not on a grid."""
    if not rows or len(rows) < 2 or any(keys[i][3] is None for r in rows for i in r):
        return None
    full = max(rows, key=len)
    grid = [(keys[i][3], keys[i][4]) for i in full]
    if len({len(r) for r in rows}) == 1:
        return None                                   # all rows full: nothing to keep
    cols = []
    for r in rows:
        cr = []
        for i in r:
            x0, x1 = keys[i][3], keys[i][4]
            d = [abs(x0 - g0) + abs(x1 - g1) for g0, g1 in grid]
            c = int(np.argmin(d))
            if d[c] > 0.25 * (grid[c][1] - grid[c][0]):
                return None                           # not on the grid
            cr.append(c)
        if len(set(cr)) != len(cr) or cr != sorted(cr):
            return None
        cols.append(cr)
    return cols


def _rows_from_source(keys):
    """Image frames that shared a row in the source stay in one row; other panels follow
    in rows of up to three. Returns None (automatic layout) when nothing is gained."""
    img = [(i, k) for i, k in enumerate(keys) if k[1] is not None]
    if len(img) < 2:
        return None
    rows = []
    for i, k in sorted(img, key=lambda t: t[1][1]):
        for r in rows:
            j = r[0]
            if abs(keys[j][1] - k[1]) < 0.3 * max(keys[j][2], k[2]):
                r.append(i)
                break
        else:
            rows.append([i])
    rows = [sorted(r, key=lambda i: keys[i][3]) for r in rows]
    if len(rows) == 1 and all(keys[i][0] == "plot" for i in rows[0]) and len(rows[0]) <= 3:
        return None          # a single short row of plots: the automatic layout does as well
    rest = [i for i, k in enumerate(keys) if k[1] is None]
    for k in range(0, len(rest), 3):
        rows.append(rest[k:k + 3])
    return rows


def _csvq(s: str) -> str:
    return f'"{s}"' if ("," in s or '"' in s) else s


def _json(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)
