"""Raster extraction of line and marker series from a calibrated plot area.

Colour separation uses the physics of anti-aliasing: every edge pixel of a line is a
mix of the series colour and the background, so it lies on the segment between them
in CIELAB. Each pixel is assigned to the series whose mixing segment it is closest
to, and the mixing fraction becomes its coverage weight. Curve positions are then
coverage-weighted centroids (sub-pixel), taken per column on flat parts and per row
on steep parts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage.color import rgb2lab, lab2rgb

from ..detect.axes import AxesBox
from ..detect import ocr


@dataclass
class Series:
    name: str
    kind: str                        # "line" or "markers"
    color_rgb: Tuple[int, int, int]
    px: np.ndarray                   # pixel x (image coordinates)
    py: np.ndarray                   # pixel y
    x: Optional[np.ndarray] = None   # data coordinates
    y: Optional[np.ndarray] = None
    yerr_lo: Optional[np.ndarray] = None
    yerr_hi: Optional[np.ndarray] = None
    dashed: bool = False
    notes: List[dict] = field(default_factory=list)
    source: str = "raster"
    style: dict = field(default_factory=dict)
    raw: Optional[tuple] = None      # unsmoothed pixel trace (raster lines)

    def to_data(self, box: AxesBox):
        self.x = box.xcal.to_data(self.px)
        self.y = box.ycal.to_data(self.py)
        return self


def _lab(rgb: np.ndarray) -> np.ndarray:
    return rgb2lab(rgb.astype(np.float32) / 255.0).astype(np.float32)


def background_lab(lab: np.ndarray) -> np.ndarray:
    flat = lab.reshape(-1, 3)
    q = np.round(flat / 2.0)
    vals, inv, cnt = np.unique(q, axis=0, return_inverse=True, return_counts=True)
    k = int(np.argmax(cnt))
    return flat[inv.ravel() == k].mean(axis=0)


def remove_gridlines(ink: np.ndarray, lab: np.ndarray, bg: np.ndarray) -> Tuple[np.ndarray, int]:
    """Drop full-span, light, achromatic horizontal/vertical lines (grids)."""
    H, W = ink.shape
    out = ink.copy()
    n = 0
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    light = (lab[..., 0] > 55) & (chroma < 10)
    for orient in ("h", "v"):
        L = int((0.25 * W) if orient == "h" else (0.25 * H))
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1) if orient == "h" else (1, L))
        lines = cv2.morphologyEx((ink & light).astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)
        if lines.any():
            lines = cv2.dilate(lines.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & light
            n += int(ndi.label(lines)[1])
            out &= ~lines
    # remnants of the plot frame hugging the crop border (any darkness)
    achro = chroma < 12
    for orient in ("h", "v"):
        L = int((0.5 * W) if orient == "h" else (0.5 * H))
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1) if orient == "h" else (1, L))
        lines = cv2.morphologyEx((ink & achro).astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)
        lab_, nl = ndi.label(lines)
        for sl in ndi.find_objects(lab_):
            if sl is None:
                continue
            r0, r1, c0, c1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
            if orient == "h" and (r0 <= 3 or r1 >= H - 3):
                out[max(0, r0 - 1):r1 + 1, :] &= ~achro[max(0, r0 - 1):r1 + 1, :]
            if orient == "v" and (c0 <= 3 or c1 >= W - 3):
                out[:, max(0, c0 - 1):c1 + 1] &= ~achro[:, max(0, c0 - 1):c1 + 1]
    return out, n


def text_boxes(gray: np.ndarray, char_h: float) -> List[Tuple[Tuple[int, int, int, int], str]]:
    """Words inside the plot area (legends, annotations) via Tesseract sparse mode."""
    if not ocr.tesseract_available():
        return []
    import pytesseract
    f = max(1.0, 32.0 / max(char_h, 1.0))
    g = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC) if f > 1.01 else gray
    try:
        d = pytesseract.image_to_data(g, config="--psm 11 --oem 1", output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    out = []
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        try:
            conf = float(d["conf"][i])
        except ValueError:
            conf = -1
        if not t or conf < 55:
            continue
        alnum = sum(ch.isalnum() for ch in t)
        if alnum < 2 and not (alnum == 1 and conf > 85):
            continue
        x, y, w, h = (int(round(v / f)) for v in (d["left"][i], d["top"][i], d["width"][i], d["height"][i]))
        if not (0.45 * char_h <= h <= 2.2 * char_h):
            continue
        out.append(((x, y, x + w, y + h), t))
    # merge words on the same line into entries
    out.sort(key=lambda b: (b[0][1], b[0][0]))
    merged = []
    for bb, t in out:
        if merged:
            pb, pt = merged[-1]
            same_row = abs((pb[1] + pb[3]) / 2 - (bb[1] + bb[3]) / 2) < 0.5 * char_h
            if same_row and 0 <= bb[0] - pb[2] < 1.2 * char_h:
                merged[-1] = ((pb[0], min(pb[1], bb[1]), bb[2], max(pb[3], bb[3])), pt + " " + t)
                continue
        merged.append((bb, t))
    return merged


def _core_pixels(dE: np.ndarray, ink: np.ndarray) -> np.ndarray:
    mx = ndi.maximum_filter(dE, size=3)
    return ink & (dE >= mx - 1e-3) & (dE > 25)


def cluster_colours(lab: np.ndarray, core: np.ndarray, bg: np.ndarray, min_px: int) -> List[np.ndarray]:
    from sklearn.cluster import DBSCAN
    pts = lab[core]
    if len(pts) < 10:
        return []
    rng = np.random.default_rng(0)
    if len(pts) > 25000:
        pts = pts[rng.choice(len(pts), 25000, replace=False)]
    lab_ = DBSCAN(eps=5.0, min_samples=8).fit_predict(pts)
    cents = []
    for k in set(lab_) - {-1}:
        m = pts[lab_ == k]
        if len(m) >= min_px:
            cents.append((len(m), np.median(m, axis=0)))
    cents.sort(key=lambda c: -c[0])
    merged = []
    for n, c in cents:
        for i, (n2, c2) in enumerate(merged):
            if np.linalg.norm(c - c2) < 12:
                merged[i] = (n2 + n, (c2 * n2 + c * n) / (n2 + n))
                break
        else:
            merged.append((n, c))
    return [c for n, c in merged]


def assign(lab: np.ndarray, ink: np.ndarray, bg: np.ndarray, centres: List[np.ndarray]):
    """Coverage maps (H, W, K) from projection onto background→centre segments."""
    H, W = ink.shape
    K = len(centres)
    cov = np.zeros((H, W, K), np.float32)
    if K == 0:
        return cov
    idx = np.nonzero(ink)
    P = lab[idx] - bg                        # (N,3)
    C = np.stack([c - bg for c in centres])  # (K,3)
    cc = (C * C).sum(1)
    t = np.clip(P @ C.T / cc, 0, 1.15)       # (N,K)
    proj = t[:, :, None] * C[None]
    d = np.linalg.norm(P[:, None, :] - proj, axis=2)
    best = np.argmin(d, axis=1)
    dmin = d[np.arange(len(best)), best]
    tb = t[np.arange(len(best)), best]
    ok = (dmin < np.maximum(9.0, 0.22 * np.sqrt(cc[best]))) & (tb > 0.12)
    for k in range(K):
        m = ok & (best == k)
        cov[idx[0][m], idx[1][m], k] = np.minimum(tb[m], 1.0)
    return cov


def _runs(col: np.ndarray, thr: float):
    on = col > thr
    if not on.any():
        return []
    d = np.diff(np.concatenate([[0], on.astype(np.int8), [0]]))
    s = np.nonzero(d == 1)[0]
    e = np.nonzero(d == -1)[0]
    return list(zip(s, e))


def _centroid(w: np.ndarray, a: int, b: int, ext: int = 1):
    a2, b2 = max(0, a - ext), min(len(w), b + ext)
    seg = w[a2:b2]
    pos = np.arange(a2, b2) + 0.5
    s = seg.sum()
    return float((seg * pos).sum() / s) if s > 0 else 0.5 * (a + b)


def trace_line(cov: np.ndarray, thr: float = 0.3):
    """Trace one series (coverage map) into an ordered list of sub-pixel points."""
    H, W = cov.shape
    runs_by_col = [_runs(cov[:, i], thr) for i in range(W)]
    lens = [b - a for rr in runs_by_col for a, b in rr]
    if not lens:
        return np.zeros((0, 2)), 1.0
    thick = float(np.median(lens))
    pts = []
    prev = None
    prev2 = None
    last_steep = None
    for i in range(W):
        rr = runs_by_col[i]
        if not rr:
            continue
        if prev is not None and len(rr) > 1:
            pred = prev[1] + ((prev[1] - prev2[1]) if prev2 is not None and prev[0] - prev2[0] < 3 else 0)
            rr = sorted(rr, key=lambda r: min(abs(r[0] - pred), abs(r[1] - pred)))
        elif prev is None and len(rr) > 1:
            rr = sorted(rr, key=lambda r: -(cov[r[0]:r[1], i].sum()))
        a, b = rr[0]
        if (b - a) > 2.2 * thick + 1:
            # steep: walk the run in the direction of travel, row centroids give x;
            # rows already walked for the previous (adjacent) column are not repeated
            down = prev is None or prev[1] <= 0.5 * (a + b)
            rows = list(range(a, b)) if down else list(range(b - 1, a - 1, -1))
            if last_steep is not None and last_steep[0] == i - 1:
                la, lb = last_steep[1], last_steep[2]
                rows = [r for r in rows if not (la <= r < lb)]
            last_steep = (i, a, b)
            if not rows:
                continue
            for r in rows:
                lo, hi = max(0, i - 3), min(W, i + 4)
                seg = cov[r, lo:hi]
                if seg.sum() <= 0:
                    continue
                x = float((seg * (np.arange(lo, hi) + 0.5)).sum() / seg.sum())
                pts.append((x, r + 0.5))
            prev2, prev = prev, (i + 0.5, pts[-1][1])
        else:
            y = _centroid(cov[:, i], a, b)
            pts.append((i + 0.5, y))
            prev2, prev = prev, (i + 0.5, y)
    return np.asarray(pts), thick


def _gaps(px: np.ndarray, thick: float):
    if len(px) < 3:
        return []
    d = np.diff(np.sort(px))
    return [(float(np.sort(px)[i]), float(np.sort(px)[i + 1])) for i in np.nonzero(d > max(3.0, 2 * thick))[0]]


def detect_markers(mask: np.ndarray, thick: float):
    """Return (centres, sizes, labelled-marker-mask) if the series is drawn with markers."""
    filled = ndi.binary_fill_holes(mask)
    r = max(1, int(round(1.2 * thick)))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    opened = cv2.morphologyEx(filled.astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)
    lab, n = ndi.label(opened)
    if n < 3:
        return None
    sl = ndi.find_objects(lab)
    areas = np.array(ndi.sum(opened, lab, range(1, n + 1)))
    sizes = np.array([max(s[0].stop - s[0].start, s[1].stop - s[1].start) for s in sl])
    med_a = np.median(areas)
    compact = np.array([(a / max((s[0].stop - s[0].start) * (s[1].stop - s[1].start), 1)) > 0.45 and
                        0.5 < (s[1].stop - s[1].start) / max(s[0].stop - s[0].start, 1) < 2.0
                        for a, s in zip(areas, sl)])
    similar = (areas > 0.4 * med_a) & (areas < 4.5 * med_a)
    good = compact & similar
    if good.sum() < 3 or good.mean() < 0.6:
        return None
    return lab, [i + 1 for i in np.nonzero(good | (similar & (areas > 1.5 * med_a)))[0]], med_a, int(np.median(sizes))


def _cap_centre(mask, col, end, direction, size, thick):
    """Centre row of an error-bar cap starting at row ``end`` (or the bar end)."""
    lo, hi = max(0, col - size), min(mask.shape[1], col + size + 1)
    widths = []
    r = end
    for _ in range(int(3 * thick) + 3):
        if r < 0 or r >= mask.shape[0]:
            break
        widths.append((r, mask[r, lo:hi].sum()))
        r += direction
    if not widths:
        return end + 0.5
    base = min(w for _, w in widths)
    cap = [rr for rr, w in widths if w > base + 2]
    if cap and abs(cap[0] - end) <= 1:
        run = [cap[0]]
        for rr in cap[1:]:
            if abs(rr - run[-1]) == 1:
                run.append(rr)
        return float(np.mean(run)) + 0.5
    return end + 0.5


def extract_markers(cov: np.ndarray, mask: np.ndarray, thick: float, det):
    lab, ids, med_a, size = det
    pts, errs = [], []
    for i in ids:
        m = lab == i
        a = m.sum()
        ys, xs = np.nonzero(m)
        nsplit = int(round(a / med_a)) if a > 1.6 * med_a else 1
        groups = [(xs, ys)]
        if nsplit > 1:
            from sklearn.cluster import KMeans
            km = KMeans(n_clusters=nsplit, n_init=4, random_state=0).fit(np.c_[xs, ys])
            groups = [(xs[km.labels_ == k], ys[km.labels_ == k]) for k in range(nsplit)]
        for gx, gy in groups:
            cx, cy = gx.mean() + 0.5, gy.mean() + 0.5
            pts.append((cx, cy))
            # error bar: vertical run of the same colour through the centre column
            col = int(cx)
            colmask = mask[:, max(0, col - 1):col + 2].any(axis=1)
            top = int(gy.min()); bot = int(gy.max())
            t = top
            while t - 1 >= 0 and (colmask[t - 1] or (t - 2 >= 0 and colmask[t - 2])):
                t -= 1
            b = bot
            while b + 1 < len(colmask) and (colmask[b + 1] or (b + 2 < len(colmask) and colmask[b + 2])):
                b += 1
            minext = max(2.0, 0.15 * size)
            has = (top - t) > minext or (b - bot) > minext
            if has:
                errs.append((_cap_centre(mask, col, t, +1, size, thick), _cap_centre(mask, col, b, -1, size, thick)))
            else:
                errs.append((np.nan, np.nan))
    pts = np.asarray(pts)
    order = np.argsort(pts[:, 0])
    return pts[order], np.asarray(errs)[order]


def _marker_template(mask: np.ndarray, thick: float):
    """Find one clean, isolated marker blob to use as a template (line+symbol plots)."""
    filled = ndi.binary_fill_holes(mask)
    r = max(1, int(round(1.2 * thick)))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    opened = cv2.morphologyEx(filled.astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)
    lab, n = ndi.label(opened)
    best = None
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if min(h, w) < 2.5 * thick or not (0.6 < w / max(h, 1) < 1.6) or max(h, w) > 0.15 * max(mask.shape):
            continue
        fill = (lab[sl] == i).mean()
        if fill < 0.5:
            continue
        if best is None or fill > best[0]:
            best = (fill, sl)
    if best is None:
        return None
    sl = best[1]
    pad = 2
    y0, y1 = max(0, sl[0].start - pad), min(mask.shape[0], sl[0].stop + pad)
    x0, x1 = max(0, sl[1].start - pad), min(mask.shape[1], sl[1].stop + pad)
    return mask[y0:y1, x0:x1].astype(np.float32), filled[y0:y1, x0:x1].astype(np.float32)


def match_markers(cov: np.ndarray, tmpl: np.ndarray, thr: float = 0.5, min_ink: float = 0.7):
    """Normalised cross-correlation of the series coverage with a marker template."""
    th, tw = tmpl.shape
    if cov.shape[0] < th or cov.shape[1] < tw:
        return np.zeros((0, 2)), np.zeros(0)
    res = cv2.matchTemplate(cov.astype(np.float32), tmpl, cv2.TM_CCOEFF_NORMED)
    size = max(th, tw)
    mx = ndi.maximum_filter(res, size=int(0.8 * size) | 1)
    peaks = np.argwhere((res >= mx - 1e-6) & (res > thr))
    pts, sc = [], []
    tsum = float(tmpl.sum())
    csum = cv2.boxFilter(cov.astype(np.float32), -1, (tw, th), normalize=False, anchor=(0, 0),
                         borderType=cv2.BORDER_CONSTANT)
    for (y, x) in peaks:
        # the window must hold about as much ink as one symbol (a bare line holds far less)
        if not (min_ink * tsum <= csum[y, x] <= 1.6 * tsum):
            continue
        # sub-pixel peak by parabola fit
        dx = dy = 0.0
        if 0 < x < res.shape[1] - 1:
            a, b, c = res[y, x - 1], res[y, x], res[y, x + 1]
            den = a - 2 * b + c
            dx = 0.5 * (a - c) / den if den != 0 else 0
        if 0 < y < res.shape[0] - 1:
            a, b, c = res[y - 1, x], res[y, x], res[y + 1, x]
            den = a - 2 * b + c
            dy = 0.5 * (a - c) / den if den != 0 else 0
        pts.append((x + dx + tw / 2, y + dy + th / 2))
        sc.append(res[y, x])
    return np.asarray(pts).reshape(-1, 2), np.asarray(sc)


def legend_map(cov: np.ndarray, tboxes, char_h: float, names: List[str]):
    """Match legend entries to series by the colour drawn just left of each text."""
    mapping = {}
    K = cov.shape[2]
    for (x0, y0, x1, y1), text in tboxes:
        hx0 = int(max(0, x0 - 4.5 * char_h)); hx1 = int(max(0, x0 - 0.2 * char_h))
        cy0 = int(max(0, (y0 + y1) / 2 - 0.6 * char_h)); cy1 = int((y0 + y1) / 2 + 0.6 * char_h)
        if hx1 <= hx0:
            continue
        w = cov[cy0:cy1, hx0:hx1].reshape(-1, K).sum(0)
        if w.max() > 1.0:
            k = int(np.argmax(w))
            if k not in mapping:
                mapping[k] = text
    return mapping


def extract_series(rgb: np.ndarray, box: AxesBox, char_h: float = 10.0, max_series: int = 12,
                   kind: str = "auto") -> Tuple[List[Series], dict]:
    """Extract all line/marker series inside ``box`` from an RGB image."""
    inset = int(np.ceil(box.line_w / 2 + 1.5))
    X0, Y0 = int(np.floor(box.x0)) + inset, int(np.floor(box.y0)) + inset
    X1, Y1 = int(np.ceil(box.x1)) - inset, int(np.ceil(box.y1)) - inset
    crop = rgb[Y0:Y1, X0:X1]
    info = {"crop": (X0, Y0, X1, Y1), "notes": []}
    if crop.size == 0:
        return [], info
    lab = _lab(crop)
    bg = background_lab(lab)
    dE = np.linalg.norm(lab - bg, axis=2)
    ink = dE > 12
    ink, ngrid = remove_gridlines(ink, lab, bg)
    if ngrid:
        info["notes"].append({"level": "info", "code": "gridlines", "msg": f"{ngrid} grid line(s) removed."})
    # text inside the plot (legend, annotations)
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    gray_txt = gray.copy()
    gray_txt[chroma > 18] = 255              # legends are (almost always) dark text
    tb = text_boxes(gray_txt, char_h)
    for bb, t in text_boxes(gray, char_h):          # second pass on the plain image; union
        if not any(max(0, min(bb[2], o[2]) - max(bb[0], o[0])) * max(0, min(bb[3], o[3]) - max(bb[1], o[1])) > 0
                   for o, _ in tb):
            tb.append((bb, t))
    # keep only boxes whose ink is mostly dark & achromatic (real text, not markers/curves)
    keep_tb = []
    for (x0, y0, x1, y1), t in tb:
        sub_ink = ink[y0:y1, x0:x1]
        if sub_ink.sum() == 0:
            continue
        dark_txt = (chroma[y0:y1, x0:x1] < 18) & (lab[y0:y1, x0:x1, 0] < 60)
        if dark_txt[sub_ink].mean() >= 0.6:
            keep_tb.append(((x0, y0, x1, y1), t))
    tb = keep_tb
    text_mask = np.zeros_like(ink)
    for (x0, y0, x1, y1), t in tb:
        pad = int(0.15 * char_h) + 1
        text_mask[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = True
    # inward tick marks (short dark strokes touching the frame) and legend frames
    dark_a = ink & (chroma < 12) & (lab[..., 0] < 70)
    lab_d, nd = ndi.label(dark_a)
    Hc, Wc = ink.shape
    for i, sl in enumerate(ndi.find_objects(lab_d), 1):
        if sl is None:
            continue
        r0, r1, c0, c1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        h, w_ = r1 - r0, c1 - c0
        touches = r0 <= 3 or c0 <= 3 or r1 >= Hc - 3 or c1 >= Wc - 3
        if touches and max(h, w_) <= 0.08 * min(Hc, Wc) and min(h, w_) <= 4 + box.line_w:
            ink[lab_d == i] = False
            continue
        comp = lab_d[sl] == i
        if comp.mean() < 0.25 and min(h, w_) > 1.5 * char_h:
            for (x0, y0, x1, y1), t in tb:
                if c0 <= x0 and c1 >= x1 and r0 <= y0 and r1 >= y1:
                    ink[lab_d == i] = False
                    break
    core = _core_pixels(dE, ink & ~text_mask)
    min_px = max(12, int(0.01 * crop.shape[1]))
    cents = cluster_colours(lab, core, bg, min_px)[:max_series]
    cov = assign(lab, ink, bg, cents)
    names = {}
    if tb:
        names = legend_map(cov, tb, char_h, [])
        # blank legend text + handle rows so they are not traced
        for (x0, y0, x1, y1), t in tb:
            hx0 = int(max(0, x0 - 4.5 * char_h))
            cy0 = int(max(0, (y0 + y1) / 2 - 0.7 * char_h)); cy1 = int((y0 + y1) / 2 + 0.7 * char_h)
            cov[cy0:cy1, hx0:x1 + 2, :] = 0
        info["legend"] = [t for _, t in tb]
    series: List[Series] = []
    for k, c in enumerate(cents):
        w = cov[:, :, k]
        if w.sum() < min_px:
            continue
        mask = w > 0.3
        rgbc = np.clip(lab2rgb(c[None, None, :].astype(np.float64))[0, 0] * 255, 0, 255).astype(int)
        name = names.get(k, f"series_{len(series) + 1}")
        lens = [b - a for i in range(0, w.shape[1], max(1, w.shape[1] // 200)) for a, b in _runs(w[:, i], 0.3)]
        thick = float(np.median(lens)) if lens else 1.0
        det = detect_markers(mask, thick) if kind in ("auto", "markers", "scatter") else None
        if det is not None:
            pts, errs = extract_markers(w, mask, thick, det)
            tm = _marker_template(mask, thick)
            if tm is not None:
                mpts, msc = match_markers(w, tm[0], 0.7)
                size = det[3]
                extra = [q for q in mpts if np.min(np.hypot(pts[:, 0] - q[0], pts[:, 1] - q[1])) > 0.6 * size] if len(pts) else list(mpts)
                if extra:
                    pts = np.vstack([pts, np.asarray(extra)])
                    errs = np.vstack([errs, np.full((len(extra), 2), np.nan)])
                    o = np.argsort(pts[:, 0]); pts, errs = pts[o], errs[o]
            s = Series(name, "markers", tuple(int(v) for v in rgbc), pts[:, 0] + X0, pts[:, 1] + Y0)
            if np.isfinite(errs).any():
                s.yerr_lo = errs[:, 1] + Y0  # pixel y of lower whisker end (larger y)
                s.yerr_hi = errs[:, 0] + Y0
            s.style = {"marker_px": det[3]}
        else:
            tm = _marker_template(mask, thick) if kind in ("auto", "markers", "scatter") else None
            mp = None
            if tm is not None:
                tmpl = tm[0]
                mpts, msc = match_markers(w, tmpl, 0.5, 0.5)
                if len(mpts) < 3 and tm[1].mean() > tm[0].mean() + 0.15:
                    # hollow symbols: match filled shapes (robust to partly hidden rings)
                    fw = ndi.binary_fill_holes(mask).astype(np.float32)
                    mpts, msc = match_markers(fw, tm[1], 0.5, 0.6)
                if len(mpts) >= 3:
                    mp = mpts
            if mp is not None:
                # line + symbols: the symbols are the data points
                o = np.argsort(mp[:, 0])
                s = Series(name, "markers", tuple(int(v) for v in rgbc), mp[o, 0] + X0, mp[o, 1] + Y0)
                s.style = {"marker_px": int(max(tm[0].shape)) - 4, "connected": True}
                s.notes.append({"level": "info", "code": "line_symbols",
                                "msg": f"{name}: line-and-symbol series; symbol centres (template matched) are reported."})
                series.append(s)
                continue
            pts, thick = trace_line(w)
            if len(pts) < 5:
                continue
            s = Series(name, "line", tuple(int(v) for v in rgbc), pts[:, 0] + X0, pts[:, 1] + Y0)
            # dashes: many regular runs of empty columns inside the traced span
            occ = (w > 0.3).any(axis=0)
            on = np.nonzero(occ)[0]
            gaps = []
            if len(on) > 2:
                inner = ~occ[on[0]:on[-1] + 1]
                d = np.diff(np.r_[0, inner.astype(np.int8), 0])
                st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
                gaps = [(on[0] + a_, on[0] + b_) for a_, b_ in zip(st, en) if b_ - a_ >= 2]
            if len(gaps) >= 4:
                gl = np.array([b - a for a, b in gaps])
                span = on[-1] - on[0] + 1
                if np.std(gl) < 0.6 * np.mean(gl) + 1 and gl.sum() > 0.12 * span:
                    s.dashed = True
            elif [g for g in gaps if g[1] - g[0] > 2 * thick]:
                s.notes.append({"level": "warn", "code": "gap",
                                "msg": f"{len(gaps)} gap(s) in trace (occlusion by another series or legend?)."})
            s.style = {"line_px": thick}
            s.raw = (s.px.copy(), s.py.copy())
            cx, cy = clean_trace(s.px, s.py, thick)
            if s.dashed:
                # dashes: interpolate across the regular gaps on a column grid
                o = np.argsort(cx)
                xs = np.arange(np.floor(cx.min()), np.ceil(cx.max()) + 1, 1.0)
                cy = np.interp(xs, cx[o], cy[o]); cx = xs
            s.px, s.py = cx, cy
        # clipping at the plot frame
        if s.kind == "line" and len(s.py):
            near = (s.py < Y0 + 1.5 * thick) | (s.py > Y1 - 1.5 * thick)
            if near.mean() > 0.02:
                s.notes.append({"level": "warn", "code": "clipped",
                                "msg": f"{near.mean() * 100:.0f}% of points touch the top/bottom of the plot: "
                                       "data may be clipped at the axis limits."})
        series.append(s)
    # drop faint residual clusters (anti-aliasing mixtures, leftovers of overlays)
    if len(series) > 1:
        weight = {id(s): (len(s.px) * (s.style.get("marker_px", 1) ** 2 if s.kind == "markers" else s.style.get("line_px", 1)))
                  for s in series}
        top = max(weight.values())
        kept = []
        for s in series:
            if weight[id(s)] < 0.06 * top and s.name.startswith("series_"):
                info["notes"].append({"level": "info", "code": "weak_series",
                                      "msg": f"Dropped a faint colour cluster rgb{s.color_rgb} ({len(s.px)} pts) as residue."})
                continue
            kept.append(s)
        series = kept
    # keep the legend's order (top to bottom) so replots list series as the original did
    if tb and names:
        order = {t: (bb[1], bb[0]) for bb, t in tb}
        series.sort(key=lambda s_: order.get(s_.name, (1e9, 1e9)))
    info["n_colours"] = len(cents)
    info["text"] = tb
    return series, info


def densify(px: np.ndarray, py: np.ndarray, step: float = 1.0, breaks=None):
    """Interpolate a polyline at ~``step`` pixel spacing (keeps sub-path breaks)."""
    px, py = np.asarray(px, float), np.asarray(py, float)
    if len(px) < 2:
        return px, py
    cuts = [0] + list(breaks or []) + [len(px)]
    ox, oy = [], []
    for a, b in zip(cuts[:-1], cuts[1:]):
        x, y = px[a:b], py[a:b]
        if len(x) < 2:
            ox.append(x); oy.append(y)
            continue
        d = np.r_[0, np.cumsum(np.hypot(np.diff(x), np.diff(y)))]
        n = max(2, int(d[-1] / step) + 1)
        t = np.linspace(0, d[-1], n)
        ox.append(np.interp(t, d, x)); oy.append(np.interp(t, d, y))
    return np.concatenate(ox), np.concatenate(oy)


def clean_trace(px: np.ndarray, py: np.ndarray, thick: float, step: float = 1.0):
    """Smooth a raw raster trace along its arc length and resample it evenly.

    Removes the sub-pixel zig-zag left by per-column / per-row centroiding on steep
    parts without rounding off real features narrower than ~2 line widths.
    """
    from scipy.signal import savgol_filter
    from scipy.ndimage import median_filter
    px, py = np.asarray(px, float), np.asarray(py, float)
    if len(px) < 7:
        return px, py
    # reject stray pixels (JPEG ringing / crossings) far from the running median along the trace
    w = int(max(9, 4 * thick)) | 1
    mx, my = median_filter(px, w, mode="nearest"), median_filter(py, w, mode="nearest")
    dev = np.hypot(px - mx, py - my)
    keep = dev <= max(3.0, 2.0 * thick)
    if keep.mean() > 0.8:
        px, py = px[keep], py[keep]
    # break the trace where it jumps (gaps: occlusion, dashes)
    d = np.hypot(np.diff(px), np.diff(py))
    cuts = np.nonzero(d > max(3.0, 2.5 * thick))[0] + 1
    segs = np.split(np.arange(len(px)), cuts)
    ox, oy = [], []
    for idx in segs:
        x, y = px[idx], py[idx]
        if len(x) < 5:
            ox.append(x); oy.append(y)
            continue
        sl = np.r_[0, np.cumsum(np.hypot(np.diff(x), np.diff(y)))]
        keep = np.r_[True, np.diff(sl) > 1e-6]
        x, y, sl = x[keep], y[keep], sl[keep]
        n = max(2, int(sl[-1] / step) + 1)
        t = np.linspace(0, sl[-1], n)
        xi, yi = np.interp(t, sl, x), np.interp(t, sl, y)
        win = int(max(5, 2 * round(1.5 * thick / step) + 1))
        if len(xi) > win:
            xi = savgol_filter(xi, win, 2, mode="interp")
            yi = savgol_filter(yi, win, 2, mode="interp")
        ox.append(xi); oy.append(yi)
    return np.concatenate(ox), np.concatenate(oy)
