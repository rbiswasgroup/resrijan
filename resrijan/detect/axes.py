"""Raster detection of plot frames, axis lines, tick marks and tick labels."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import ocr
from .calibration import AxisCalibration, calibrate, repair_labels, snap_to_ticks, spacing_anomalies


@dataclass
class Segment:
    x0: float
    y0: float
    x1: float
    y1: float
    thick: float

    @property
    def length(self):
        return max(self.x1 - self.x0, self.y1 - self.y0)


@dataclass
class AxesBox:
    """Plot area in pixel coordinates of the analysed image (x0 < x1, y0 < y1)."""
    x0: float
    y0: float
    x1: float
    y1: float
    xaxis_y: float          # y of the x-axis line centre
    yaxis_x: float          # x of the y-axis line centre
    line_w: float = 1.0
    framed: bool = False
    xticks: List[float] = field(default_factory=list)
    yticks: List[float] = field(default_factory=list)
    xtick_out: float = 0.0          # length of outward x ticks (px), 0 if ticks point inward
    ytick_out: float = 0.0
    xticks_minor: List[float] = field(default_factory=list)
    yticks_minor: List[float] = field(default_factory=list)
    xlabels: list = field(default_factory=list)
    ylabels: list = field(default_factory=list)
    xcal: Optional[AxisCalibration] = None
    xcategories: list = field(default_factory=list)   # categorical x labels (bar charts)
    ycal: Optional[AxisCalibration] = None
    notes: List[dict] = field(default_factory=list)
    no_yaxis: bool = False          # x axis only (stacked spectra, offset traces)

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0

    def as_tuple(self):
        return (self.x0, self.y0, self.x1, self.y1)


def to_gray(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def dark_achromatic(rgb: np.ndarray, gray_thresh: int = 140, chroma_thresh: int = 40) -> np.ndarray:
    """Black/dark-grey ink (axes, ticks, text) – excludes coloured data."""
    r, g, b = [rgb[..., i].astype(np.int16) for i in range(3)]
    chroma = np.max(rgb, axis=2).astype(np.int16) - np.min(rgb, axis=2).astype(np.int16)
    gray = (0.299 * r + 0.587 * g + 0.114 * b)
    return (gray < gray_thresh) & (chroma < chroma_thresh)


def line_segments(mask: np.ndarray, orient: str, min_len: int) -> List[Segment]:
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1) if orient == "h" else (1, min_len))
    lines = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, k)
    n, lab, st, _ = cv2.connectedComponentsWithStats(lines, 8)
    segs = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if orient == "h":
            ys, xs = np.nonzero(lab[y:y + h, x:x + w] == i)
            yc = y + float(np.mean(ys)) + 0.5
            segs.append(Segment(x, yc, x + w, yc, a / max(w, 1)))
        else:
            ys, xs = np.nonzero(lab[y:y + h, x:x + w] == i)
            xc = x + float(np.mean(xs)) + 0.5
            segs.append(Segment(xc, y, xc, y + h, a / max(h, 1)))
    return segs


def find_axes(rgb: np.ndarray, min_frac: float = 0.12, max_boxes: int = 16, any_colour: bool = False) -> List[AxesBox]:
    """Find plot areas (bottom-left axis corners, with or without a full frame).

    ``any_colour`` also accepts coloured axis lines (e.g. a blue x axis)."""
    H, W = rgb.shape[:2]
    mask = dark_achromatic(rgb, 170, 60)
    if any_colour:
        g = rgb.astype(np.int16)
        mask = mask | ((g.min(axis=2) < 150) & ((g.max(axis=2) - g.min(axis=2)) > 60))
    min_len = max(25, int(min_frac * min(H, W)))
    if any_colour:
        # coloured ink also includes filled data (bars, maps): only long, thin lines count
        hs = [s_ for s_ in line_segments(mask, "h", int(0.4 * W)) if s_.thick <= max(6, 0.01 * H)]
        vs = [s_ for s_ in line_segments(mask, "v", int(0.4 * H)) if s_.thick <= max(6, 0.01 * W)]
    else:
        hs = line_segments(mask, "h", min_len)
        vs = line_segments(mask, "v", min_len)
    boxes = []
    for h in hs:
        for v in vs:
            tol = max(4.0, 2.5 * max(h.thick, v.thick))
            gap = 0.03 * max(h.length, v.length)
            # corner: v sits at h's left end and v's bottom reaches h
            if abs(v.x0 - h.x0) <= tol + gap and abs(v.y1 - h.y0) <= tol + gap and v.y0 < h.y0 - 10:
                bx = AxesBox(x0=v.x0, y0=v.y0 + v.thick / 2, x1=h.x1 - h.thick / 2, y1=h.y0, xaxis_y=h.y0,
                             yaxis_x=v.x0, line_w=0.5 * (h.thick + v.thick))
                # full frame? then the opposite spines give the exact far edges
                top = [s for s in hs if abs(s.y0 - v.y0) <= tol + v.thick and abs(s.x0 - h.x0) <= tol + gap
                       and abs(s.x1 - h.x1) <= tol + gap]
                right = [s for s in vs if abs(s.x0 - h.x1) <= tol + gap + h.thick and abs(s.y1 - h.y0) <= tol + gap]
                bx.framed = bool(top and right)
                if right:
                    bx.x1 = min(right, key=lambda s: abs(s.x0 - h.x1)).x0
                if top:
                    bx.y0 = min(top, key=lambda s: abs(s.y0 - v.y0)).y0
                boxes.append(bx)
    # remove duplicates and boxes nested in bigger ones that share no corner (legend frames)
    boxes.sort(key=lambda b: -b.w * b.h)
    keep: List[AxesBox] = []
    for b in boxes:
        dup = False
        for k in keep:
            if abs(b.x0 - k.x0) < 6 and abs(b.y1 - k.y1) < 6:
                dup = True
                break
            inside = b.x0 >= k.x0 - 2 and b.x1 <= k.x1 + 2 and b.y0 >= k.y0 - 2 and b.y1 <= k.y1 + 2
            if inside:
                dup = True
                break
        if not dup:
            keep.append(b)
    return keep[:max_boxes]


def _tick_scan(mask: np.ndarray, axis_pos: float, lo: float, hi: float, orient: str,
               line_w: float, max_len: int, direction: int) -> Tuple[np.ndarray, np.ndarray]:
    """Return (positions, run lengths) of ink columns/rows leaving the axis line.

    orient "x": axis is horizontal at y=axis_pos; scan columns lo..hi.
    direction +1 scans downward (outside for x), -1 upward (inside).
    """
    H, W = mask.shape
    start = int(round(axis_pos + direction * (line_w / 2 + 1.0)))
    runs = []
    idx = np.arange(int(max(0, np.floor(lo))), int(min((W if orient == "x" else H), np.ceil(hi))))
    for i in idx:
        n = 0
        for s in range(max_len):
            p = start + direction * s
            if orient == "x":
                if p < 0 or p >= H or not mask[p, i]:
                    break
            else:
                if p < 0 or p >= W or not mask[i, p]:
                    break
            n += 1
        runs.append(n)
    return idx.astype(float), np.asarray(runs)


def _group_ticks(idx, runs, weights_img, axis_pos, orient, direction, line_w, min_len=2):
    sel = runs >= min_len
    ticks, lens = [], []
    i = 0
    n = len(idx)
    while i < n:
        if not sel[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and sel[j + 1]:
            j += 1
        width = j - i + 1
        if width <= max(6, 4 * line_w):  # ticks are thin; wider blobs are text/curves
            cols = idx[i:j + 1]
            L = int(np.median(runs[i:j + 1]))
            start = int(round(axis_pos + direction * (line_w / 2 + 1.0)))
            w = []
            for c in cols:
                if orient == "x":
                    a, b = sorted((start, start + direction * L))
                    w.append(weights_img[a:b + 1, int(c)].sum())
                else:
                    a, b = sorted((start, start + direction * L))
                    w.append(weights_img[int(c), a:b + 1].sum())
            w = np.asarray(w, dtype=float)
            pos = float(np.sum((cols + 0.5) * w) / max(w.sum(), 1e-9))
            ticks.append(pos)
            lens.append(int(runs[i:j + 1].max()))
        i = j + 1
    return np.asarray(ticks), np.asarray(lens)


def detect_ticks(rgb: np.ndarray, box: AxesBox):
    gray = to_gray(rgb)
    mask = dark_achromatic(rgb, 170, 60)
    weights = (255.0 - gray.astype(float)) / 255.0
    max_len = int(max(6, min(40, 0.06 * max(box.w, box.h))))
    out = {}
    for orient in ("x", "y"):
        if orient == "x":
            axis_pos, lo, hi = box.xaxis_y, box.x0 - 2, box.x1 + 3
        else:
            axis_pos, lo, hi = box.yaxis_x, box.y0 - 2, box.y1 + 3
        best = None
        for direction in ((+1, -1) if orient == "x" else (-1, +1)):  # outside first
            idx, runs = _tick_scan(mask, axis_pos, lo, hi, orient, box.line_w, max_len, direction)
            t, L = _group_ticks(idx, runs, weights, axis_pos, orient, direction, box.line_w)
            # drop the perpendicular axis line itself (very long run at the corner)
            keep = L < max_len - 1
            t, L = t[keep], L[keep]
            if best is None or len(t) > len(best[0]):
                best = (t, L, direction)
        t, L, direction = best
        out_len = float(L.max()) if (len(t) and direction == (+1 if orient == "x" else -1)) else 0.0
        if orient == "x":
            box.xtick_out = out_len
        else:
            box.ytick_out = out_len
        if len(t):
            Lmax = L.max()
            major = t[L >= 0.75 * Lmax] if (L < 0.75 * Lmax).any() and (L >= 0.75 * Lmax).sum() >= 2 else t
            minor = t[L < 0.75 * Lmax] if len(major) != len(t) else np.array([])
        else:
            major, minor = t, np.array([])
        out[orient] = (np.sort(major), np.sort(minor), direction)
    box.xticks, box.xticks_minor = list(out["x"][0]), list(out["x"][1])
    box.yticks, box.yticks_minor = list(out["y"][0]), list(out["y"][1])
    return box


def _nearest_row(labels, key, axis_pos, sign):
    """Keep labels in the band closest to the axis (drops axis titles further out)."""
    labs = [l for l in labels if l.value is not None]
    if not labs:
        return []
    d = np.array([sign * (key(l) - axis_pos) for l in labs])
    order = np.argsort(d)
    first = d[order[0]]
    hgt = np.median([l.bbox[3] - l.bbox[1] for l in labs])
    band = max(hgt * 0.9, 4)
    return [labs[i] for i in order if d[i] - first <= band]


def read_tick_labels(rgb: np.ndarray, box: AxesBox, all_boxes: Optional[List[AxesBox]] = None):
    gray = to_gray(rgb)
    H, W = gray.shape
    reach_y = int(max(25, 0.18 * box.h))
    reach_x = int(max(40, 0.35 * box.w))
    # x labels: below the x axis
    xr = (box.x0 - 0.12 * box.w, box.xaxis_y + box.line_w / 2 + box.xtick_out + 2, box.x1 + 0.12 * box.w,
          min(H, box.xaxis_y + reach_y))
    xr = _clip_to_neighbours(xr, box, all_boxes)
    labs = ocr.find_labels(gray, xr, numeric=True)
    box.xlabels = _nearest_row(labs, lambda l: l.bbox[1], box.xaxis_y, +1)
    # y labels: left of the y axis
    yr = (max(0, box.yaxis_x - reach_x), box.y0 - 0.06 * box.h, box.yaxis_x - box.line_w / 2 - box.ytick_out - 2,
          box.y1 + 0.06 * box.h)
    yr = _clip_to_neighbours(yr, box, all_boxes)
    labs = ocr.find_labels(gray, yr, numeric=True)
    box.ylabels = _nearest_row(labs, lambda l: -l.bbox[2], -box.yaxis_x, +1)
    return box


def _clip_to_neighbours(r, box, all_boxes):
    if not all_boxes:
        return r
    x0, y0, x1, y1 = r
    for o in all_boxes:
        if o is box:
            continue
        # a neighbour plot area intersecting the search region trims it
        if o.x0 < x1 and o.x1 > x0 and o.y0 < y1 and o.y1 > y0:
            if o.y0 >= box.y1:          # neighbour below
                y1 = min(y1, o.y0 - 2)
            elif o.x1 <= box.x0:        # neighbour to the left
                x0 = max(x0, o.x1 + 2)
    return (x0, y0, x1, y1)


def calibrate_box(box: AxesBox, xscale="auto", yscale="auto") -> AxesBox:
    for ax in ("x", "y"):
        labs = box.xlabels if ax == "x" else box.ylabels
        ticks = box.xticks if ax == "x" else box.yticks
        if not labs:
            box.notes.append({"level": "error", "code": f"{ax}_no_labels",
                              "msg": f"No numeric {ax}-tick labels were read; supply a manual calibration."})
            continue
        centres = [l.cx if ax == "x" else l.cy for l in labs]
        spacing = np.median(np.diff(sorted(ticks))) if len(ticks) >= 2 else (box.w if ax == "x" else box.h) / 4
        pos, snapped = snap_to_ticks(centres, ticks, 0.45 * spacing)
        if not all(snapped):
            box.notes.append({"level": "warn", "code": f"{ax}_label_unsnapped",
                              "msg": f"{snapped.count(False)} {ax}-label(s) had no tick mark nearby; "
                                     "label centres used (lower precision)."})
        vals = [l.value for l in labs]
        span = (box.w if ax == "x" else box.h)
        sc = (xscale if ax == "x" else yscale)
        good = [(p, v) for p, v in zip(pos, vals) if v is not None]
        cal = calibrate(ax, [g[0] for g in good], [g[1] for g in good], scale=sc, source="ocr", span=span)
        if (cal is None or cal.rejected or len(good) < len(labs)) and sc != "log" and \
                (cal is None or cal.scale == "linear"):
            rep = repair_labels(pos, [l.text for l in labs], vals)
            if rep is not None:
                newv, score = rep
                cal2 = calibrate(ax, pos, newv, scale="linear", source="ocr+repair", span=span)
                if cal2 is not None and not cal2.rejected and (cal is None or cal2.n_used > cal.n_used):
                    fixed = [(l.text, v) for l, v in zip(labs, newv) if l.value is None or abs(l.value - v) > 1e-9]
                    box.notes.append({"level": "warn", "code": f"{ax}_labels_repaired",
                                      "msg": f"{ax}-labels corrected from tick regularity: " +
                                             ", ".join(f"'{t}' -> {v:g}" for t, v in fixed)})
                    for l, v in zip(labs, newv):
                        l.value = v
                    cal = cal2
        if cal is None:
            box.notes.append({"level": "error", "code": f"{ax}_calibration_failed",
                              "msg": f"{ax}-axis could not be calibrated from labels {[l.text for l in labs]}."})
            continue
        for r in cal.rejected:
            box.notes.append({"level": "warn", "code": f"{ax}_label_rejected",
                              "msg": f"{ax}-label value {r['value']:g} is inconsistent with the other ticks "
                                     f"({r['residual']:+.1f} px) and was ignored (likely misread)."})
        sp = spacing_anomalies(ticks)
        if sp and cal.scale == "linear":
            box.notes.append({"level": "warn", "code": f"{ax}_tick_spacing",
                              "msg": f"Non-uniform {ax} major-tick spacing at {len(sp)} place(s): "
                                     "possible axis break or uneven axis."})
        if cal.reversed:
            box.notes.append({"level": "info", "code": f"{ax}_reversed",
                              "msg": f"{ax}-axis is reversed (values decrease along the axis)."})
        if ax == "x":
            box.xcal = cal
        else:
            box.ycal = cal
    return box


def _inside_photo(b: AxesBox, regions, f=0.2) -> bool:
    """A box whose tick-label zones (left of and below the plot) also lie inside a
    photograph is a feature of that photograph, not a plot."""
    ex = (b.x0 - f * b.w, b.y0, b.x1, b.y1 + f * b.h)
    area = (ex[2] - ex[0]) * (ex[3] - ex[1])
    for r in regions:
        ix = max(0.0, min(ex[2], r[2]) - max(ex[0], r[0]))
        iy = max(0.0, min(ex[3], r[3]) - max(ex[1], r[1]))
        if ix * iy > 0.85 * area:
            return True
    return False


def analyse_axes(rgb: np.ndarray, xscale="auto", yscale="auto", photos=()) -> List[AxesBox]:
    """``photos``: pixel boxes of photographs/micrographs on the page (see imagefig)."""
    H, W = rgb.shape[:2]
    real = lambda b: b.w > 0.03 * W and b.h > 0.03 * H     # noqa: E731  (degenerate boxes from single lines)
    boxes = [b for b in find_axes(rgb) if real(b) and not _inside_photo(b, photos)]
    if not boxes:
        boxes = [b for b in find_axes(rgb, any_colour=True) if real(b) and not _inside_photo(b, photos)]
        for b in boxes:
            b.notes.append({"level": "info", "code": "coloured_axis", "msg": "An axis line is coloured (not black)."})
    for b in boxes:
        detect_ticks(rgb, b)
    for b in boxes:
        read_tick_labels(rgb, b, boxes)
        calibrate_box(b, xscale, yscale)
    return boxes
