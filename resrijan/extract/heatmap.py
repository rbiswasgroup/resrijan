"""Heat maps, filled contours and 2D spectra: colour → value through the colour bar.

The colour bar is sampled along its long axis to build a look-up table in CIELAB and
calibrated from its own tick labels. Every plot pixel is then inverted by projecting
its colour onto the nearest LUT segment, which gives sub-step values for continuous
colour maps and exact level bands for discrete (contourf) maps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

from ..detect import ocr
from ..detect.axes import AxesBox, _nearest_row, dark_achromatic, to_gray
from ..detect.calibration import AxisCalibration, calibrate, repair_labels, snap_to_ticks
from .curves import _lab


@dataclass
class ColorBar:
    x0: float
    y0: float
    x1: float
    y1: float
    orient: str                       # "v" or "h"
    lut_lab: np.ndarray               # (N, 3) along the bar, from position 0 to N-1
    lut_pos: np.ndarray               # pixel coordinate (y for "v", x for "h") of each sample
    cal: Optional[AxisCalibration] = None
    discrete: bool = False
    bands: list = field(default_factory=list)   # (pos_lo, pos_hi, lab) for discrete bars
    labels: list = field(default_factory=list)
    notes: List[dict] = field(default_factory=list)


@dataclass
class Grid:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray                     # (ny, nx), rows ordered by increasing pixel y
    filled: np.ndarray                # True where the value was interpolated (lines, text)
    lo: Optional[np.ndarray] = None   # band limits for discrete colour maps
    hi: Optional[np.ndarray] = None
    source: str = "raster"
    notes: List[dict] = field(default_factory=list)


def _nonwhite(rgb):
    lab = _lab(rgb)
    return np.linalg.norm(lab - np.array([100.0, 0, 0]), axis=2) > 8, lab


def _merge_runs(idx: np.ndarray, rel_gap: float = 0.35) -> np.ndarray:
    """Join runs separated by short gaps (white mid-colours of diverging maps)."""
    runs = np.split(idx, np.nonzero(np.diff(idx) > 1)[0] + 1)
    runs.sort(key=len, reverse=True)
    lo, hi = runs[0][0], runs[0][-1]
    changed = True
    while changed:
        changed = False
        for r in runs:
            span = hi - lo + 1
            if r[0] > hi and r[0] - hi <= rel_gap * span + 2:
                hi = r[-1]; changed = True
            elif r[-1] < lo and lo - r[-1] <= rel_gap * span + 2:
                lo = r[0]; changed = True
    return np.arange(lo, hi + 1)


def _outline_extent(rgb, a0, a1, lo, hi, orient):
    """Extend [lo, hi) along the bar while a dark outline flanks it on both sides."""
    dark = dark_achromatic(rgb, 120, 40)
    H, W = dark.shape
    if orient == "v":
        sides = (max(0, a0 - 1), min(W - 1, a1))
        def ok(r):
            return 0 <= r < H and all(dark[r, max(0, s - 1):s + 2].any() for s in sides)
    else:
        sides = (max(0, a0 - 1), min(H - 1, a1))
        def ok(c):
            return 0 <= c < W and all(dark[max(0, s - 1):s + 2, c].any() for s in sides)
    mid = (lo + hi) // 2
    if not ok(mid):
        return lo, hi
    a = mid
    while ok(a - 1):
        a -= 1
    b = mid
    while ok(b + 1):
        b += 1
    if (b - a) >= 0.8 * (hi - lo):
        return a, b + 1
    return lo, hi


def _in(labels, region):
    x0, y0, x1, y1 = region
    out = [l for l in labels if l.value is not None and x0 <= l.cx <= x1 and y0 <= l.cy <= y1]
    return out if len(out) >= 2 else None


def find_colorbar(rgb: np.ndarray, box: AxesBox) -> Optional[ColorBar]:
    H, W = rgb.shape[:2]
    nw, lab = _nonwhite(rgb)
    np.hypot(lab[..., 1], lab[..., 2])
    cands = []
    # vertical bar right of the plot
    ys0, ys1 = int(box.y0), int(box.y1)
    xs0, xs1 = int(box.x1 + 3 + box.ytick_out), int(min(W, box.x1 + 0.5 * box.w))
    if xs1 - xs0 > 5:
        frac = nw[ys0:ys1, xs0:xs1].mean(axis=0)
        cols = np.nonzero(frac > 0.55)[0]
        if len(cols):
            # first contiguous block wider than 3 px
            blocks = np.split(cols, np.nonzero(np.diff(cols) > 1)[0] + 1)
            for b in blocks:
                if len(b) >= 4:
                    cx0, cx1 = xs0 + b[0], xs0 + b[-1] + 1
                    rows = np.nonzero(nw[:, cx0 + (cx1 - cx0) // 4: cx1 - (cx1 - cx0) // 4].mean(axis=1) > 0.9)[0]
                    rows = rows[(rows >= box.y0 - 0.2 * box.h) & (rows <= box.y1 + 0.2 * box.h)]
                    if len(rows) > 0.2 * box.h:
                        r = _merge_runs(rows)
                        # an outline (dark frame) gives the exact extent even through white colours
                        r0, r1 = _outline_extent(rgb, cx0, cx1, r[0], r[-1] + 1, "v")
                        cands.append(("v", cx0, r0, cx1, r1))
                    break
    # horizontal bar below or above
    for (ry0, ry1) in ((int(box.y1 + box.xtick_out + 3), int(min(H, box.y1 + 0.45 * box.h))),
                       (int(max(0, box.y0 - 0.3 * box.h)), int(box.y0 - 3))):
        if ry1 - ry0 > 5 and not cands:
            frac = nw[ry0:ry1, int(box.x0):int(box.x1)].mean(axis=1)
            rows = np.nonzero(frac > 0.55)[0]
            if len(rows):
                blocks = np.split(rows, np.nonzero(np.diff(rows) > 1)[0] + 1)
                for b in blocks:
                    if len(b) >= 4 and len(b) < 0.25 * box.h:
                        cy0, cy1 = ry0 + b[0], ry0 + b[-1] + 1
                        cols = np.nonzero(nw[cy0 + (cy1 - cy0) // 4: cy1 - (cy1 - cy0) // 4, :].mean(axis=0) > 0.9)[0]
                        cols = cols[(cols >= box.x0 - 0.2 * box.w) & (cols <= box.x1 + 0.2 * box.w)]
                        if len(cols) > 0.2 * box.w:
                            c = _merge_runs(cols)
                            c0, c1 = _outline_extent(rgb, cy0, cy1, c[0], c[-1] + 1, "h")
                            cands.append(("h", c0, cy0, c1, cy1))
                        break
    if not cands:
        return None
    o, x0, y0, x1, y1 = cands[0]
    # strip the outline: shrink while the border row/col is dark & achromatic
    dark = dark_achromatic(rgb, 120, 40)
    for _ in range(6):
        if x1 - x0 < 3 or y1 - y0 < 3:
            break
        if dark[y0:y1, x0].mean() > 0.5: x0 += 1
        if dark[y0:y1, x1 - 1].mean() > 0.5: x1 -= 1
        if x1 > x0 and dark[y0, x0:x1].mean() > 0.5: y0 += 1
        if x1 > x0 and dark[y1 - 1, x0:x1].mean() > 0.5: y1 -= 1
    if o == "v":
        mid = lab[y0:y1, x0 + (x1 - x0) // 4: x1 - (x1 - x0) // 4]
        lut = np.median(mid, axis=1)
        pos = np.arange(y0, y1) + 0.5
    else:
        mid = lab[y0 + (y1 - y0) // 4: y1 - (y1 - y0) // 4, x0:x1]
        lut = np.median(mid, axis=0)
        pos = np.arange(x0, x1) + 0.5
    cb = ColorBar(x0, y0, x1, y1, o, lut.astype(np.float32), pos)
    # discrete?
    d = np.linalg.norm(np.diff(lut, axis=0), axis=1)
    steps = np.nonzero(d > 3.0)[0]
    if 2 <= len(steps) <= 64 and np.median(d) < 0.5 and d[steps].sum() > 0.7 * d.sum():
        edges = [0] + list(steps + 1) + [len(lut)]
        bands = []
        for a, b in zip(edges[:-1], edges[1:]):
            if b - a >= 2:
                bands.append((pos[a] - 0.5, pos[b - 1] + 0.5, np.median(lut[a:b], axis=0)))
        if len(bands) >= 3:
            cb.discrete = True
            cb.bands = bands
    return cb


def calibrate_colorbar(rgb: np.ndarray, cb: ColorBar, text_labels=None) -> ColorBar:
    """Calibrate the colour bar from its tick labels (OCR, or vector text if given)."""
    gray = to_gray(rgb)
    H, W = gray.shape
    if cb.orient == "v":
        AxesBox(x0=cb.x0, y0=cb.y0, x1=cb.x1, y1=cb.y1, xaxis_y=cb.y1, yaxis_x=cb.x1, line_w=1.0)
        # ticks on the right edge (outward = +1)
        from ..detect.axes import _tick_scan, _group_ticks
        mask = dark_achromatic(rgb, 170, 60)
        weights = (255.0 - gray.astype(float)) / 255.0
        best = (np.array([]), np.array([]))
        ml = int(max(30, 0.06 * (cb.y1 - cb.y0)))
        for edge, direction in ((cb.x1, +1), (cb.x1 - 1, -1), (cb.x0, -1)):
            idx, runs = _tick_scan(mask, edge, cb.y0 - 2, cb.y1 + 2, "y", 1.0, ml, direction)
            t, L = _group_ticks(idx, runs, weights, edge, "y", direction, 1.0)
            t = t[L < ml - 1]
            if len(t) > len(best[0]):
                best = (t, L)
        ticks = np.sort(best[0])
        tick_len = float(best[1].max()) if len(best[1]) else 0.0
        region = (cb.x1 + 1 + tick_len, cb.y0 - 0.06 * (cb.y1 - cb.y0), min(W, cb.x1 + 0.3 * W),
                  cb.y1 + 0.06 * (cb.y1 - cb.y0))
        labs = (_in(text_labels, region) if text_labels else None) or ocr.find_labels(gray, region, numeric=True)
        labs = _nearest_row(labs, lambda l: l.bbox[0], cb.x1, +1)
        if len(labs) < 2:
            region = (max(0, cb.x0 - 0.25 * W), cb.y0 - 0.06 * (cb.y1 - cb.y0), cb.x0 - 2,
                      cb.y1 + 0.06 * (cb.y1 - cb.y0))
            labs = _nearest_row(ocr.find_labels(gray, region, numeric=True), lambda l: -l.bbox[2], -cb.x0, +1)
        centres = [l.cy for l in labs]
        axis = "y"
    else:
        mask = dark_achromatic(rgb, 170, 60)
        from ..detect.axes import _tick_scan, _group_ticks
        weights = (255.0 - gray.astype(float)) / 255.0
        ml = int(max(30, 0.06 * (cb.x1 - cb.x0)))
        idx, runs = _tick_scan(mask, cb.y1, cb.x0 - 2, cb.x1 + 2, "x", 1.0, ml, +1)
        t, L = _group_ticks(idx, runs, weights, cb.y1, "x", +1, 1.0)
        ticks = np.sort(t[L < ml - 1])
        tick_len = float(L.max()) if len(L) else 0.0
        region = (cb.x0 - 0.1 * (cb.x1 - cb.x0), cb.y1 + 1 + tick_len, cb.x1 + 0.1 * (cb.x1 - cb.x0),
                  min(H, cb.y1 + 0.15 * H))
        labs = (_in(text_labels, region) if text_labels else None) or ocr.find_labels(gray, region, numeric=True)
        labs = _nearest_row(labs, lambda l: l.bbox[1], cb.y1, +1)
        centres = [l.cx for l in labs]
        axis = "x"
    cb.labels = labs
    if len(labs) < 2:
        cb.notes.append({"level": "error", "code": "cbar_no_labels",
                         "msg": "Colour-bar labels could not be read; values are reported as the colour-bar fraction (0–1)."})
        p = cb.lut_pos
        cal = calibrate(axis, [p[0], p[-1]], ([1.0, 0.0] if cb.orient == "v" else [0.0, 1.0]), "linear",
                        tol=1e9, source="fraction")
        cb.cal = cal
        return cb
    # snap only within a few pixels: colour-bar ticks are short and easily confused with edges
    lab_h = float(np.median([l.bbox[3] - l.bbox[1] for l in labs])) if labs else 10.0
    pos, snapped = snap_to_ticks(centres, ticks, 0.4 * lab_h)
    vals = [l.value for l in labs]
    cal = calibrate(axis, pos, vals, "auto", source="ocr", span=cb.lut_pos[-1] - cb.lut_pos[0])
    if cal is None or cal.rejected:
        rep = repair_labels(pos, [l.text for l in labs], vals)
        if rep is not None:
            cal2 = calibrate(axis, pos, rep[0], "linear", source="ocr+repair")
            if cal2 is not None and not cal2.rejected:
                cb.notes.append({"level": "warn", "code": "cbar_labels_repaired",
                                 "msg": "Colour-bar labels corrected from tick regularity."})
                cal = cal2
    if cal is not None:
        for r in cal.rejected:
            cb.notes.append({"level": "warn", "code": "cbar_label_rejected",
                             "msg": f"Colour-bar label {r['value']:g} inconsistent with the others; ignored."})
    cb.cal = cal
    return cb


def invert_colors(lab_img: np.ndarray, cb: ColorBar, max_de: float = 14.0):
    """Map colours to colour-bar positions. Returns (position, distance) arrays."""
    H, W = lab_img.shape[:2]
    P = lab_img.reshape(-1, 3)
    if cb.discrete:
        cols = np.stack([b[2] for b in cb.bands])
        tree = cKDTree(cols)
        d, k = tree.query(P)
        mid = np.array([0.5 * (b[0] + b[1]) for b in cb.bands])
        pos = mid[k]
        return pos.reshape(H, W), d.reshape(H, W), k.reshape(H, W)
    lut = cb.lut_lab
    tree = cKDTree(lut)
    d, k = tree.query(P)
    # refine on the two neighbouring segments
    best_t = k.astype(np.float64)
    best_d = d.copy()
    for off in (-1, 0):
        a = np.clip(k + off, 0, len(lut) - 2)
        A, B = lut[a], lut[a + 1]
        AB = B - A
        t = np.clip(((P - A) * AB).sum(1) / np.maximum((AB * AB).sum(1), 1e-9), 0, 1)
        dd = np.linalg.norm(A + t[:, None] * AB - P, axis=1)
        better = dd < best_d
        best_d[better] = dd[better]
        best_t[better] = a[better] + t[better]
    pos = np.interp(best_t, np.arange(len(lut)), cb.lut_pos)
    return pos.reshape(H, W), best_d.reshape(H, W), None


def extract_grid(rgb: np.ndarray, box: AxesBox, cb: ColorBar, step: int = 1,
                 image: Optional[Tuple[np.ndarray, Tuple[float, float, float, float]]] = None) -> Grid:
    """Invert the plot area (or an embedded native image placed at ``rect`` px)."""
    notes = []
    if image is not None:
        img, (rx0, ry0, rx1, ry1) = image
        lab = _lab(img)
        h, w = img.shape[:2]
        px = rx0 + (np.arange(w) + 0.5) * (rx1 - rx0) / w
        py = ry0 + (np.arange(h) + 0.5) * (ry1 - ry0) / h
        selx = (px >= box.x0) & (px <= box.x1)
        sely = (py >= box.y0) & (py <= box.y1)
        lab = lab[np.ix_(sely, selx)]
        px, py = px[selx], py[sely]
        source = "embedded-image"
    else:
        inset = int(np.ceil(box.line_w / 2 + 2))
        X0, Y0 = int(np.floor(box.x0)) + inset, int(np.floor(box.y0)) + inset
        X1, Y1 = int(np.floor(box.x1)) - inset + 1, int(np.floor(box.y1)) - inset + 1
        lab = _lab(rgb[Y0:Y1:step, X0:X1:step])
        px = np.arange(X0, X1, step) + 0.5
        py = np.arange(Y0, Y1, step) + 0.5
        source = "raster"
    pos, dist, band = invert_colors(lab, cb)
    bad = dist > (10.0 if cb.discrete else 12.0)
    # dark/grey overlay lines (contours, diagonals, text) are achromatic; unless the colour
    # map itself is grey they are never data, even when close to a dark map colour
    lut_chroma = np.hypot(cb.lut_lab[:, 1], cb.lut_lab[:, 2])
    if np.median(lut_chroma) > 15:
        chroma = np.hypot(lab[..., 1], lab[..., 2])
        bad |= (chroma < 8) & (lab[..., 0] < 60)
    if bad.any() and bad.mean() < 0.5 and not cb.discrete:
        # anti-aliased fringes of overlay lines are colour mixtures: drop them too
        bad = ndi.binary_dilation(bad, iterations=2 if image is None else 1)
    z = cb.cal.to_data(pos)
    lo = hi = None
    if cb.discrete:
        b_lo = cb.cal.to_data(np.array([b[0] for b in cb.bands]))
        b_hi = cb.cal.to_data(np.array([b[1] for b in cb.bands]))
        blo, bhi = np.minimum(b_lo, b_hi), np.maximum(b_lo, b_hi)
        # "extend" triangles: end bands reaching past the labelled range are open-ended
        if cb.cal is not None and cb.cal.values:
            vmin, vmax = min(cb.cal.values), max(cb.cal.values)
            width = np.median(bhi - blo)
            from ..detect.calibration import _nice
            nw_ = _nice(width)
            if abs(nw_ - width) < 0.08 * width:
                width = nw_
            # snap band edges onto the evenly spaced level grid implied by the labels
            fin = np.isfinite(blo) & np.isfinite(bhi)
            if fin.sum() >= 3 and width > 0:
                for arr in (blo, bhi):
                    q = (arr - vmin) / width
                    near = np.abs(q - np.round(q)) < 0.25
                    arr[near] = vmin + np.round(q[near]) * width
            for i in range(len(blo)):
                if bhi[i] > vmax + 0.05 * width and blo[i] >= vmax - 0.05 * width:
                    bhi[i] = np.inf
                    notes.append({"level": "info", "code": "extend_max",
                                  "msg": f"Top colour band means 'above {vmax:g}' (open-ended)."})
                if blo[i] < vmin - 0.05 * width and bhi[i] <= vmin + 0.05 * width:
                    blo[i] = -np.inf
                    notes.append({"level": "info", "code": "extend_min",
                                  "msg": f"Bottom colour band means 'below {vmin:g}' (open-ended)."})
            z_band = np.where(np.isfinite(bhi) & np.isfinite(blo), 0.5 * (blo + bhi),
                              np.where(np.isfinite(blo), blo, bhi))
            z = z_band[band]
        lo = blo[band]
        hi = bhi[band]
    if bad.any():
        frac = bad.mean()
        notes.append({"level": "info" if frac < 0.08 else "warn", "code": "unmapped_pixels",
                      "msg": f"{frac * 100:.1f}% of plot pixels are not colour-bar colours "
                             "(contour lines, labels, overlays); filled from neighbours."})
        idx = ndi.distance_transform_edt(bad, return_distances=False, return_indices=True)
        if lo is not None:
            # discrete bands: nearest valid band (no blending between levels)
            z = z[tuple(idx)]
            lo = lo[tuple(idx)]; hi = hi[tuple(idx)]
        else:
            # continuous maps: normalised-convolution fill (smooth, no blocky nearest copies)
            w = (~bad).astype(float)
            z0 = np.where(bad, 0.0, z)
            zf = z.copy()
            for sig in (1.5, 3.0, 6.0, 12.0):
                num = ndi.gaussian_filter(z0, sig)
                den = ndi.gaussian_filter(w, sig)
                bad & (den > 0.15) & ~np.isfinite(np.where(bad, np.nan, 0) + 0)
                fill = num / np.maximum(den, 1e-9)
                upd = bad & (den > 0.15)
                zf[upd] = fill[upd]
                bad_left = bad & ~upd
                if not bad_left.any():
                    break
            if (bad & (ndi.gaussian_filter(w, 12.0) <= 0.15)).any():
                zf = np.where(np.isfinite(zf), zf, z[tuple(idx)])
            z = zf
    sat = None
    if not cb.discrete:
        p = pos[~bad]
        if p.size:
            sat = float(np.mean((p <= cb.lut_pos[0] + 0.5) | (p >= cb.lut_pos[-1] - 0.5)))
            if sat > 0.02:
                notes.append({"level": "warn", "code": "cmap_saturated",
                              "msg": f"{sat * 100:.1f}% of pixels sit at a colour-bar end: values beyond the colour "
                                     "range are clipped (true extrema may be larger)."})
    x = box.xcal.to_data(px)
    y = box.ycal.to_data(py)
    return Grid(x=x, y=y, z=z, filled=bad, lo=lo, hi=hi, source=source, notes=notes + cb.notes)


def contour_lines(rgb: np.ndarray, box: AxesBox, cb: Optional[ColorBar]):
    """Dark, achromatic thin lines inside a filled map (contour overlays) as polylines (px)."""
    from skimage.morphology import skeletonize
    inset = int(np.ceil(box.line_w / 2 + 1))
    X0, Y0, X1, Y1 = int(box.x0) + inset, int(box.y0) + inset, int(box.x1) - inset, int(box.y1) - inset
    m = dark_achromatic(rgb[Y0:Y1, X0:X1], 110, 30)
    if m.mean() < 1e-4:
        return []
    sk = skeletonize(m)
    lab, n = ndi.label(sk, np.ones((3, 3)))
    out = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        if len(xs) < 15:
            continue
        out.append(np.c_[xs + X0 + 0.5, ys + Y0 + 0.5])
    return out
