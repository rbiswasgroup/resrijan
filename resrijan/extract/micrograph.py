"""Microscopy images: scale-bar calibration, annotation removal, particle sizing."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np
from scipy import ndimage as ndi

from ..detect import ocr

UNIT_NM = {"pm": 1e-3, "Å": 0.1, "A": 0.1, "nm": 1.0, "um": 1e3, "µm": 1e3, "μm": 1e3, "mm": 1e6}
_UNIT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(pm|nm|µm|μm|um|mm|Å|A)\b", re.I)


@dataclass
class ScaleBar:
    x0: float
    x1: float
    y: float
    thickness: float
    length_px: float
    value: Optional[float] = None
    unit: Optional[str] = None
    text: str = ""
    text_box: Optional[Tuple[int, int, int, int]] = None
    panel_box: Optional[Tuple[int, int, int, int]] = None
    polarity: str = "white"

    @property
    def nm_per_px(self) -> Optional[float]:
        if self.value is None or self.unit is None:
            return None
        return self.value * UNIT_NM[self.unit] / self.length_px


@dataclass
class MicroResult:
    gray: np.ndarray
    bar: Optional[ScaleBar]
    nm_per_px: Optional[float]
    annotation_mask: np.ndarray
    particles: Optional[dict] = None
    notes: List[dict] = field(default_factory=list)


def looks_like_micrograph(rgb: np.ndarray) -> bool:
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hist = np.bincount(g.ravel(), minlength=256) / g.size
    white = hist[245:].sum()
    mid = hist[30:225].sum()
    chroma = (rgb.max(2).astype(int) - rgb.min(2)).mean()
    return white < 0.35 and mid > 0.45 and chroma < 25


def _parse_scale_text(txt: str):
    t = txt.replace("u m", "um").replace("µ", "µ").replace("O", "0")
    m = _UNIT_RE.search(t)
    if not m:
        return None, None
    val = float(m.group(1).replace(",", "."))
    unit = m.group(2)
    unit = {"UM": "µm", "Um": "µm", "um": "µm", "μm": "µm", "NM": "nm", "Nm": "nm", "a": "Å", "A": "Å"}.get(unit, unit)
    if unit not in UNIT_NM:
        unit = unit.lower()
    return val, unit if unit in UNIT_NM else None


def _bar_edges(gray: np.ndarray, row: float, x0: int, x1: int, thick: int, polarity: str):
    """Sub-pixel bar ends from the half-maximum crossings of the row profile."""
    r0 = int(max(0, row - thick / 2 + 1)); r1 = int(min(gray.shape[0], row + thick / 2))
    prof = gray[r0:max(r1, r0 + 1), :].astype(float).mean(axis=0)
    if polarity == "black":
        prof = 255 - prof
    inside = np.median(prof[x0 + 2:x1 - 2]) if x1 - x0 > 6 else prof[x0:x1].max()
    left_bg = np.median(prof[max(0, x0 - 8):max(1, x0 - 2)]) if x0 > 3 else prof.min()
    right_bg = np.median(prof[x1 + 2:x1 + 8]) if x1 + 3 < len(prof) else prof.min()

    def cross(i0, step, bg):
        half = 0.5 * (inside + bg)
        i = i0
        while 0 < i < len(prof) - 1 and prof[i] >= half:
            i += step
        # linear interpolation between pixel i (background side) and i - step (bar side)
        a, b = prof[i], prof[i - step]
        f = (half - a) / (b - a) if b != a else 0.5
        return i - step * f

    left = cross(x0 + 2, -1, left_bg)
    right = cross(x1 - 3, +1, right_bg)
    # pixel-centre convention: pixel i spans [i, i+1]
    return left + 0.5, right + 0.5


def find_scale_bar(rgb: np.ndarray) -> Optional[ScaleBar]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape
    best = None
    for polarity, mask in (("white", gray >= 235), ("black", gray <= 20)):
        lab, n = ndi.label(mask)
        for i, sl in enumerate(ndi.find_objects(lab), 1):
            if sl is None:
                continue
            h = sl[0].stop - sl[0].start
            w = sl[1].stop - sl[1].start
            if w < 0.03 * W or w > 0.7 * W or h < 2 or w < 4 * h:
                continue
            comp = lab[sl] == i
            fill = comp.mean()
            if fill < 0.85:
                continue
            # contrast with what surrounds it (a bar sits on a plain panel or the image)
            y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
            ring = gray[max(0, y0 - 3):min(H, y1 + 3), max(0, x0 - 3):min(W, x1 + 3)].astype(float)
            contrast = abs(ring.mean() - gray[y0:y1, x0:x1].mean())
            score = fill * min(w / (6 * h), 3) + (1.0 if y0 > 0.6 * H else 0) + contrast / 100
            # text with a unit nearby is decisive
            tb = (max(0, x0 - int(0.3 * w)), max(0, y0 - int(max(5 * h, 0.08 * H))),
                  min(W, x1 + int(0.3 * w)), min(H, y1 + int(max(5 * h, 0.08 * H))))
            sub = gray[tb[1]:tb[3], tb[0]:tb[2]].copy()
            sub[(y0 - tb[1]):(y1 - tb[1]), (x0 - tb[0]):(x1 - tb[0])] = sub.mean()
            # clean binary of the bar's polarity (white text on a busy image is unreadable otherwise)
            pol = (sub >= 225) if polarity == "white" else (sub <= 30)
            pol[(y0 - tb[1]):(y1 - tb[1]), (x0 - tb[0]):(x1 - tb[0])] = False
            clean = np.where(pol, 0, 255).astype(np.uint8)
            val = unit = None
            txt = ""
            if pol.sum() > 10:
                for ps in (6, 7, 11):
                    t, _c = ocr.read_text(clean, psm=ps)
                    val, unit = _parse_scale_text(t)
                    if val is not None:
                        txt = t
                        break
            if val is not None:
                conf = 100.0
            if polarity == "white" or sub.mean() < 110:
                sub = 255 - sub
            if val is None:
                txt, conf = ocr.read_text(sub, psm=6)
                val, unit = _parse_scale_text(txt)
            if val is None:
                txt2, _ = ocr.read_text(sub, psm=11)
                val, unit = _parse_scale_text(txt2)
                txt = txt2 if val is not None else txt
            if val is not None:
                score += 5
            cand = (score, polarity, (y0, y1, x0, x1), val, unit, txt, tb)
            if best is None or cand[0] > best[0]:
                best = cand
    if best is None:
        return None
    score, polarity, (y0, y1, x0, x1), val, unit, txt, tb = best
    row = 0.5 * (y0 + y1) - 0.5
    left, right = _bar_edges(gray, row + 0.5, x0, x1, y1 - y0, polarity)
    bar = ScaleBar(left, right, row + 0.5, y1 - y0, right - left, val, unit, txt.strip(), tb, None, polarity)
    # the plain panel behind bar + text (to mask from analysis)
    panel = _panel(gray, (x0, y0, x1, y1), tb)
    bar.panel_box = panel
    return bar


def _panel(gray, bar_box, text_box):
    """Grow the bar/text box over a uniform backing panel if there is one."""
    x0, y0, x1, y1 = min(bar_box[0], text_box[0]), min(bar_box[1], text_box[1]), max(bar_box[2], text_box[2]), max(bar_box[3], text_box[3])
    H, W = gray.shape
    for _ in range(200):
        grown = False
        for side in ("l", "r", "t", "b"):
            if side == "l" and x0 > 0:
                strip = gray[y0:y1, x0 - 1]
            elif side == "r" and x1 < W:
                strip = gray[y0:y1, x1]
            elif side == "t" and y0 > 0:
                strip = gray[y0 - 1, x0:x1]
            elif side == "b" and y1 < H:
                strip = gray[y1, x0:x1]
            else:
                continue
            if strip.std() < 6 and (strip.mean() < 30 or strip.mean() > 225):
                if side == "l": x0 -= 1
                if side == "r": x1 += 1
                if side == "t": y0 -= 1
                if side == "b": y1 += 1
                grown = True
        if not grown:
            break
    return (x0, y0, x1, y1)


def analyse_particles(gray: np.ndarray, valid: np.ndarray, nm_per_px: Optional[float], min_px: int = 20,
                      dark_particles: Optional[bool] = None) -> dict:
    """Threshold + watershed particle sizing. Diameters are area-equivalent."""
    from skimage.filters import threshold_otsu
    from skimage.segmentation import watershed
    from skimage.feature import peak_local_max
    from skimage.measure import regionprops, label as sklabel
    g = cv2.GaussianBlur(gray, (0, 0), 1.2).astype(float)
    vals = g[valid]
    t = threshold_otsu(vals)
    if dark_particles is None:
        dark_particles = (vals < t).mean() < 0.5
    fg = (g < t) if dark_particles else (g > t)
    fg &= valid
    fg = ndi.binary_opening(fg, iterations=1)
    fg = ndi.binary_fill_holes(fg)
    dist = ndi.distance_transform_edt(fg)
    lab0 = sklabel(fg)
    coords = peak_local_max(dist, min_distance=max(3, int(np.sqrt(min_px))), labels=lab0, exclude_border=False)
    markers = np.zeros_like(lab0)
    markers[tuple(coords.T)] = np.arange(1, len(coords) + 1)
    lab = watershed(-dist, markers, mask=fg)
    H, W = gray.shape
    border = ~ndi.binary_erosion(valid, iterations=2)
    rows = []
    for r in regionprops(lab):
        if r.area < min_px:
            continue
        rr, cc = r.coords[:, 0], r.coords[:, 1]
        touches = border[rr, cc].any()
        d_px = 2 * np.sqrt(r.area / np.pi)
        rows.append({"cx_px": float(r.centroid[1] + 0.5), "cy_px": float(r.centroid[0] + 0.5), "area_px": int(r.area),
                     "eq_diam_px": float(d_px), "eccentricity": float(r.eccentricity), "edge": bool(touches),
                     "eq_diam_nm": float(d_px * nm_per_px) if nm_per_px else None})
    inner = [r for r in rows if not r["edge"]]
    d = np.array([r["eq_diam_nm"] if nm_per_px else r["eq_diam_px"] for r in inner])
    stats = {}
    if len(d):
        stats = {"n": int(len(d)), "mean": float(d.mean()), "sd": float(d.std(ddof=1)) if len(d) > 1 else 0.0,
                 "median": float(np.median(d)), "unit": "nm" if nm_per_px else "px",
                 "polydispersity_pct": float(100 * d.std() / d.mean())}
    return {"particles": rows, "stats": stats, "labels": lab, "threshold": float(t), "dark": bool(dark_particles)}


def analyse_micrograph(rgb: np.ndarray, particles: bool = True) -> MicroResult:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape
    notes = []
    bar = find_scale_bar(rgb)
    ann = np.zeros_like(gray, dtype=bool)
    nm = None
    if bar is None:
        notes.append({"level": "error", "code": "no_scale_bar",
                      "msg": "No scale bar found; sizes are reported in pixels. Supply --scale '<px>=<value unit>'."})
    else:
        x0, y0, x1, y1 = bar.panel_box
        ann[max(0, y0 - 2):y1 + 2, max(0, x0 - 2):x1 + 2] = True
        nm = bar.nm_per_px
        if nm is None:
            notes.append({"level": "error", "code": "scale_text_unread",
                          "msg": f"Scale bar found ({bar.length_px:.1f} px) but its text '{bar.text}' was not "
                                 "readable; supply the value with --scale."})
        else:
            notes.append({"level": "info", "code": "scale",
                          "msg": f"Scale bar {bar.value:g} {bar.unit} = {bar.length_px:.2f} px → "
                                 f"{nm:.4g} nm/px (±{nm * 1.0 / bar.length_px:.2g} nm/px from ±1 px edge uncertainty)."})
    # data bar (SEM info strip) along the bottom: rows that are uniform and very different
    rowstd = gray.std(axis=1)
    bottom = H
    while bottom > 0.7 * H and rowstd[bottom - 1] < 2.5:
        bottom -= 1
    if bottom < H - 5:
        ann[bottom:, :] = True
        notes.append({"level": "info", "code": "info_strip", "msg": f"Info strip of {H - bottom} px rows at the bottom excluded."})
    valid = ~ann
    sat_lo = (gray[valid] <= 1).mean(); sat_hi = (gray[valid] >= 254).mean()
    if sat_lo > 0.01 or sat_hi > 0.01:
        notes.append({"level": "warn", "code": "saturation",
                      "msg": f"Clipped intensities: {sat_lo * 100:.1f}% black, {sat_hi * 100:.1f}% white "
                             "(quantitative intensity analysis is unreliable)."})
    # JPEG blockiness
    d = np.abs(np.diff(gray.astype(float), axis=1))
    if W > 64:
        blk = d[:, 7::8].mean() / max(d.mean(), 1e-6)
        if blk > 1.25:
            notes.append({"level": "warn", "code": "jpeg_blocks",
                          "msg": f"8×8 JPEG block artefacts detected (ratio {blk:.2f}); fine detail may be lost."})
    res = MicroResult(gray, bar, nm, ann, None, notes)
    if particles:
        try:
            res.particles = analyse_particles(gray, valid, nm)
        except Exception as exc:  # pragma: no cover
            notes.append({"level": "warn", "code": "particles_failed", "msg": f"Particle analysis failed: {exc}"})
    return res
