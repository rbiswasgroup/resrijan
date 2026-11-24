"""Bar charts: bar heights (and error bars) from vector rectangles or from pixels.

Vector: filled axis-aligned rectangles standing on the baseline are grouped into bars
by colour (opacity ignored, so gradient-faked bars made of many slices count as one)
and by x-adjacency. Raster: runs of non-background columns standing on the baseline.
Bar heights are read through the y calibration; categories come from the words under
the x axis and value annotations above the bars are cross-checked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from ..detect.axes import AxesBox
from ..detect import ocr


@dataclass
class Bar:
    x0: float              # pixel extent
    x1: float
    top: float             # pixel y of the bar end (top for positive bars)
    base: float
    color: tuple
    value: Optional[float] = None
    category: str = ""
    annotated: Optional[float] = None
    annotated_y: float = 0.0
    err_lo: Optional[float] = None     # pixel rows of whisker ends
    err_hi: Optional[float] = None
    err_plus: Optional[float] = None   # data units
    err_minus: Optional[float] = None
    n_parts: int = 1
    notes: List[dict] = field(default_factory=list)

    @property
    def cx(self):
        return 0.5 * (self.x0 + self.x1)


def _rgb(c):
    return tuple(int(round(v * 255)) for v in c) if c is not None else (0, 0, 0)


def _is_rect(p) -> bool:
    if len(p.polys) != 1:
        return False
    pts = p.polys[0]
    if len(pts) < 4 or len(pts) > 6:
        return False
    xs, ys = np.unique(np.round(pts[:, 0], 2)), np.unique(np.round(pts[:, 1], 2))
    return len(xs) <= 2 and len(ys) <= 2 and np.ptp(pts[:, 0]) > 0 and np.ptp(pts[:, 1]) > 0


def vector_bars(paths, box: AxesBox):
    """Return (bars, stray_shapes) from vector paths."""
    tol = max(1.5, 0.004 * box.h)
    rects, stray = [], []
    for p in paths:
        if p.fill is None or not _is_rect(p):
            continue
        x0, y0, x1, y1 = p.bbox
        if x1 < box.x0 - 1 or x0 > box.x1 + 1 or y1 < box.y0 - 1 or y0 > box.y1 + tol:
            continue
        if (x1 - x0) > 0.6 * box.w:
            continue                      # background / legend frame
        if min(p.fill) > 0.97:
            continue                      # white fill
        on_base = abs(y1 - box.y1) <= tol or abs(y0 - box.y1) <= tol
        if on_base:
            rects.append(p)
        elif (y1 - y0) > 0.05 * box.h:
            stray.append(p)
    if len(rects) < 2:
        return [], stray
    rects.sort(key=lambda p: p.bbox[0])
    groups = []
    for p in rects:
        col = np.array(p.fill)
        if groups:
            g = groups[-1]
            gap = p.bbox[0] - g["x1"]
            if gap <= max(1.0, 0.002 * box.w) and np.abs(col - g["col"]).max() < 0.03:
                g["x1"] = max(g["x1"], p.bbox[2]); g["parts"].append(p)
                continue
        groups.append({"x0": p.bbox[0], "x1": p.bbox[2], "col": col, "parts": [p]})
    bars = []
    for g in groups:
        tops = np.array([min(q.bbox[1], q.bbox[3]) if abs(q.bbox[3] - box.y1) <= tol else max(q.bbox[1], q.bbox[3])
                         for q in g["parts"]])
        widths = np.array([q.w for q in g["parts"]])
        top = float(np.average(tops, weights=widths))
        b = Bar(g["x0"], g["x1"], top, box.y1, _rgb(g["col"]), n_parts=len(g["parts"]))
        if np.ptp(tops) > max(0.5, 0.003 * box.h):
            b.notes.append({"level": "warn", "code": "bar_uneven_top",
                            "msg": f"bar at x≈{b.cx:.0f}px: its {len(tops)} slices end at different heights "
                                   f"(spread {np.ptp(tops):.1f} px); width-weighted mean used."})
        bars.append(b)
    # very narrow groups beside real bars are artefacts
    wmed = np.median([b.x1 - b.x0 for b in bars])
    bars = [b for b in bars if (b.x1 - b.x0) > 0.15 * wmed]
    return bars, stray


def raster_bars(rgb: np.ndarray, box: AxesBox):
    """Bars as runs of coloured columns standing on the x axis."""
    from skimage.color import rgb2lab
    inset = int(np.ceil(box.line_w / 2 + 1.5))
    X0, Y0 = int(box.x0) + inset, int(box.y0) + inset
    X1, Y1 = int(box.x1) - inset, int(np.floor(box.y1)) - inset
    crop = rgb[Y0:Y1 + 1, X0:X1]
    if crop.size == 0:
        return []
    lab = rgb2lab(crop.astype(np.float32) / 255.0)
    bg = np.median(lab.reshape(-1, 3)[lab.reshape(-1, 3)[:, 0] > 90], axis=0) if (lab[..., 0] > 90).any() else np.array([100, 0, 0])
    ink = np.linalg.norm(lab - bg, axis=2) > 10
    H, W = ink.shape
    base_on = ink[-3:, :].any(axis=0)
    # contiguous ink height from the baseline in every column
    heights = np.zeros(W)
    for c in range(W):
        if not base_on[c]:
            continue
        col = ink[::-1, c]
        off = np.argmax(col) if col[:3].any() else 0
        run = np.argmax(~col[off:]) if (~col[off:]).any() else len(col) - off
        heights[c] = off + run
    on = heights > 0.02 * H
    bars = []
    c = 0
    while c < W:
        if not on[c]:
            c += 1
            continue
        d = c
        while d + 1 < W and on[d + 1]:
            d += 1
        w = d - c + 1
        if 0.015 * W < w < 0.5 * W:
            core = heights[c + int(0.2 * w): d - int(0.2 * w) + 1]
            hgt = float(np.median(core)) if len(core) else float(np.median(heights[c:d + 1]))
            top_row = H - hgt
            # sub-pixel top from the coverage of the edge row
            r = int(np.clip(np.floor(top_row), 0, H - 1))
            frac = np.clip(np.linalg.norm(lab[r, c + int(0.3 * w): d - int(0.3 * w) + 1] - bg, axis=1).mean() /
                           max(np.linalg.norm(lab[min(H - 1, r + 2), c + int(0.3 * w): d - int(0.3 * w) + 1] - bg, axis=1).mean(), 1e-6), 0, 1) \
                if d - c > 4 else 1.0
            top = Y0 + r + (1 - frac)
            mid = lab[int(top_row + 0.5 * hgt) if hgt > 4 else H - 2, c + w // 2]
            from skimage.color import lab2rgb
            colr = tuple(int(v) for v in np.clip(lab2rgb(mid[None, None, :].astype(float))[0, 0] * 255, 0, 255))
            # a bar is a solid block: nearly every pixel between its top and the axis is ink
            blk = ink[int(np.ceil(top_row)) + 1:, c + int(0.15 * w): d - int(0.15 * w) + 1]
            if blk.size and blk.mean() >= 0.9 and hgt > 0.03 * H:
                bars.append(Bar(X0 + c, X0 + d + 1, float(top), box.y1, colr))
        c = d + 1
    # join pieces of one bar split by a hairline gap (same height, ≤ 3 px apart)
    merged = []
    for b in bars:
        if merged and b.x0 - merged[-1].x1 <= 3 and abs(b.top - merged[-1].top) <= 2.0:
            m = merged[-1]
            w1, w2 = m.x1 - m.x0, b.x1 - b.x0
            m.top = (m.top * w1 + b.top * w2) / (w1 + w2)
            m.x1 = b.x1
            m.color = b.color if w2 > w1 else m.color
            m.n_parts += 1
        else:
            merged.append(b)
    return merged


def assign_labels(bars: List[Bar], box: AxesBox, labels_in_plot=None):
    """Category names from words under the axis; value annotations above bars."""
    cats = list(getattr(box, "xcategories", []) or [])
    # OCR digit slips in "number+unit" categories (e.g. "l6h" between "8h" and "32h" → "16h")
    import re
    pat = [l for l in cats if re.fullmatch(r"\d+[A-Za-z]{1,3}", l.text)]
    if len(pat) >= 2:
        unit = max(set(re.sub(r"^\d+", "", l.text) for l in pat), key=lambda u: sum(l.text.endswith(u) for l in pat))
        for l in cats:
            m = re.fullmatch(r"([0-9lIOoSB]+)(" + re.escape(unit) + ")", l.text, flags=re.I)
            if m and not m.group(1).isdigit():
                l.text = m.group(1).translate(str.maketrans("lIOoSB", "110058")) + unit
    if cats:
        if len(cats) == len(bars):
            for b, l in zip(sorted(bars, key=lambda b: b.cx), sorted(cats, key=lambda l: l.cx)):
                b.category = l.text
        else:
            for l in cats:
                k = int(np.argmin([abs(b.cx - l.cx) for b in bars]))
                if not bars[k].category:
                    bars[k].category = l.text
    for i, b in enumerate(sorted(bars, key=lambda b: b.cx)):
        if not b.category:
            b.category = f"bar_{i + 1}"
    for l in labels_in_plot or []:
        if l.value is None:
            continue
        for b in bars:
            near_top = -0.25 * box.h < (b.top - l.bbox[3]) < 0.12 * box.h
            if near_top and (b.x0 - 0.6 * (b.x1 - b.x0)) <= l.cx <= (b.x1 + 0.6 * (b.x1 - b.x0)):
                if b.annotated is None or abs(l.bbox[3] - b.top) < abs(b.annotated_y - b.top):
                    b.annotated = l.value
                    b.annotated_y = l.bbox[3]
    return bars


def finish(bars: List[Bar], box: AxesBox) -> List[dict]:
    notes = []
    for b in bars:
        b.value = float(box.ycal.to_data(b.top))
        if b.err_hi is not None:
            b.err_plus = float(box.ycal.to_data(b.err_hi) - b.value)
            b.err_minus = float(b.value - box.ycal.to_data(b.err_lo))
        base_val = float(box.ycal.to_data(b.base))
        if abs(base_val) > 0.01 * abs(box.ycal.to_data(box.y0) - box.ycal.to_data(box.y1)) and box.ycal.scale == "linear":
            notes.append({"level": "info", "code": "bar_baseline",
                          "msg": f"Bars start at y = {base_val:.4g}, not 0 (truncated axis?)."})
        if b.annotated is not None:
            dif = b.value - b.annotated
            rel = abs(dif) / max(abs(b.annotated), 1e-12)
            dec = len(str(b.annotated).split(".")[1]) if "." in f"{b.annotated:g}" else 0
            half_step = 0.5 * 10 ** (-dec) if dec else 0.5
            res = box.ycal.unit_per_px
            if abs(dif) > max(half_step, 1.5 * res):
                b.notes.append({"level": "warn", "code": "bar_annotation_mismatch",
                                "msg": f"'{b.category}': drawn height gives {b.value:.4g} but the label says "
                                       f"{b.annotated:g} ({dif:+.3g}, {rel * 100:.1f}%)."})
            else:
                b.notes.append({"level": "info", "code": "bar_annotation_ok",
                                "msg": f"'{b.category}': height {b.value:.4g} agrees with its label {b.annotated:g}."})
    return notes


def vector_errorbars(paths, bars: List[Bar], box: AxesBox):
    """Vertical dark strokes centred on a bar = its error bar (ends in pixels)."""
    for p in paths:
        if p.stroke is None or len(p.polys) != 1:
            continue
        pts = p.polys[0]
        if len(pts) != 2 or abs(pts[0, 0] - pts[1, 0]) > 0.3:
            continue
        x = pts[0, 0]
        y0, y1 = sorted(pts[:, 1])
        for b in bars:
            w = b.x1 - b.x0
            if abs(x - b.cx) < 0.12 * w and y0 - 1 <= b.top <= y1 + 1 and (y1 - y0) < 0.8 * box.h:
                b.err_hi, b.err_lo = y0, y1          # pixel rows of the whisker ends
    return bars


def raster_errorbars(rgb: np.ndarray, bars: List[Bar], box: AxesBox):
    from ..detect.axes import dark_achromatic
    dark = dark_achromatic(rgb, 120, 50)
    for b in bars:
        c = int(round(b.cx))
        col = dark[:, max(0, c - 1):c + 2].any(axis=1)
        t = int(round(b.top))
        if not col[max(0, t - 2):t + 3].any():
            continue
        up = t
        while up - 1 > box.y0 and col[up - 1]:
            up -= 1
        dn = t
        while dn + 1 < box.y1 and col[dn + 1]:
            dn += 1
        if (t - up) > 2 or (dn - t) > 2:
            b.err_hi, b.err_lo = up + 0.5, dn + 0.5
    return bars


def ocr_categories(gray: np.ndarray, box: AxesBox, n_expected: int):
    """Words under a categorical axis, read as one text line (Tesseract word boxes)."""
    import cv2
    if not ocr.tesseract_available():
        return []
    import pytesseract
    H = gray.shape[0]
    y0 = int(box.y1 + box.xtick_out + 2)
    strip = gray[y0:min(H, int(box.y1 + 0.18 * box.h)), max(0, int(box.x0 - 0.05 * box.w)):int(box.x1 + 0.05 * box.w)]
    if strip.size == 0 or (strip < 128).sum() == 0:
        return []
    rows = np.nonzero((strip < 128).any(axis=1))[0]
    # first text line only
    gaps = np.nonzero(np.diff(rows) > 3)[0]
    r1 = rows[gaps[0]] if len(gaps) else rows[-1]
    line = strip[max(0, rows[0] - 3):r1 + 4]
    if r1 - rows[0] < 4:
        return []
    f = min(6.0, max(1.0, 40.0 / (r1 - rows[0])))
    big = cv2.resize(line, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    try:
        d = pytesseract.image_to_data(big, config="--psm 7 --oem 1", output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    x_off = max(0, int(box.x0 - 0.05 * box.w))
    out = []
    for t, l, w in zip(d["text"], d["left"], d["width"]):
        t = (t or "").strip()
        if not t:
            continue
        cx = (l - 20 + w / 2) / f + x_off
        lab = ocr.Label((cx - w / f / 2, y0, cx + w / f / 2, y0 + 1), t, None, 0)
        out.append(lab)
    return out


def plausible(bars: List[Bar], box: AxesBox) -> bool:
    """Real bar charts: >= 2 bars of similar width covering a fair part of the axis."""
    if len(bars) < 2:
        return False
    w = np.array([b.x1 - b.x0 for b in bars])
    if w.sum() < 0.12 * box.w:
        return False
    return float(np.std(w) / np.mean(w)) < 0.35
