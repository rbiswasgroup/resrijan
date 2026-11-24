"""Image figures: micrographs, photographs, time-lapse strips and insets.

A page is split into *frames* (photographs / micrographs), each kept at its native
resolution when the source embeds it as a bitmap. Insets (a frame lying inside a
larger one) are linked to their parent. Per frame the module reads

* the title printed just above it ("0 min", "5 min" …) and text labels on it,
* the scale bar – exactly from vector strokes + text when available, otherwise from
  the pixels (bar + OCR),
* drawn annotations – lines, arrows, rectangles – with their lengths,
* d-spacing labels ("d = 0.22 nm (021)") and the lattice-fringe period from the FFT,
  which cross-check each other (and give the size of an unlabelled inset scale bar),

and, when frame titles are numbers with a common unit, turns the per-frame
measurements (arrow lengths, separations of paired lines) into data series.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np
from scipy import ndimage as ndi

from ..detect import ocr
from . import micrograph as micro

UNIT_NM = micro.UNIT_NM
_D_RE = re.compile(r"\bd\s*[=:≈~]?\s*(\d+(?:[.,]\d+)?)\s*(nm|Å|A|pm)", re.I)
_HKL_RE = re.compile(r"\(\s*(-?\d)\s*,?\s*(-?\d)\s*,?\s*(-?\d)\s*(?:,?\s*(-?\d))?\s*\)")
_VAL_RE = re.compile(r"^\s*(?:t\s*=\s*)?([-+]?\d+(?:[.,]\d+)?)\s*([A-Za-zµμ°%][A-Za-z°µμ/%]*)?\s*$")
TIME_UNITS = {"fs", "ps", "ns", "µs", "us", "ms", "s", "sec", "min", "mins", "h", "hr", "hrs", "d", "day", "days"}


# ───────────────────────── data classes ─────────────────────────
@dataclass(eq=False)
class Annotation:
    kind: str                         # line | arrow | rect | polyline | head
    pts: np.ndarray                   # (N, 2) native pixel coordinates of the host frame
    color: Tuple[int, int, int]
    width_px: float = 1.0
    dashed: bool = False
    source: str = "vector"

    @property
    def length_px(self) -> float:
        if self.kind == "rect":
            return float(np.hypot(*(self.pts[2] - self.pts[0])))
        return float(np.sum(np.hypot(*np.diff(self.pts, axis=0).T)))

    @property
    def angle_deg(self) -> float:
        d = self.pts[-1] - self.pts[0]
        return float(np.degrees(np.arctan2(-d[1], d[0])))

    @property
    def hex(self) -> str:
        return "#%02x%02x%02x" % tuple(int(c) for c in self.color)


@dataclass
class Frame:
    box: Tuple[float, float, float, float]          # page pixels
    rgb: np.ndarray                                 # native pixels
    sx: float = 1.0                                 # native px per page px
    sy: float = 1.0
    source: str = "raster"                          # vector-image | raster
    pt_rect: Optional[tuple] = None                 # PDF points (vector pages)
    parent: Optional[int] = None
    children: List[int] = field(default_factory=list)
    title: str = ""
    labels: List[dict] = field(default_factory=list)       # text on the frame (native px)
    annotations: List[Annotation] = field(default_factory=list)
    bar: Optional[micro.ScaleBar] = None
    bar_hidden: List[int] = field(default_factory=list)    # drawing ids used as scale bar / its text
    unlabelled_bars: List[Annotation] = field(default_factory=list)
    nm_per_px: Optional[float] = None
    lattice: List[dict] = field(default_factory=list)
    dlabels: List[dict] = field(default_factory=list)
    drawings: list = field(default_factory=list)            # replot paths in native px (top-level frames)
    texts: list = field(default_factory=list)               # replot texts in native px (top-level frames)
    notes: List[dict] = field(default_factory=list)
    full_rgb: Optional[np.ndarray] = None                  # whole embedded bitmap (incl. clipped-away parts)
    crop_off: Tuple[int, int] = (0, 0)                      # visible crop origin inside full_rgb
    instrument_bar: Optional[dict] = None                   # bar burnt into the pixels by the microscope software

    @property
    def w(self):
        return self.box[2] - self.box[0]

    @property
    def h(self):
        return self.box[3] - self.box[1]

    def to_native(self, x, y):
        return (np.asarray(x, float) - self.box[0]) * self.sx, (np.asarray(y, float) - self.box[1]) * self.sy

    @property
    def gray(self):
        return cv2.cvtColor(self.rgb, cv2.COLOR_RGB2GRAY)

    @property
    def is_colour(self) -> bool:
        c = self.rgb.max(2).astype(int) - self.rgb.min(2)
        return float(np.percentile(c, 90)) > 25


# ───────────────────────── frame detection ─────────────────────────
def _overlap(a, b) -> float:
    """Area of a∩b divided by the area of a."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


def looks_photographic(rgb: np.ndarray) -> bool:
    """Photographs/micrographs: few blank pixels and pixel-level noise/texture everywhere
    (rendered plots, colour bars and flat fills have none)."""
    if rgb.shape[0] < 16 or rgb.shape[1] < 16:
        return False
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    white = float((g > 248).mean())
    hp = np.abs(g - cv2.blur(g, (3, 3)))
    return white < 0.5 and float(np.median(hp)) >= 0.45


def _visible_part(page_rgb, place, img):
    """Which native pixels of a placed bitmap are actually visible on the rendered page
    (figures often clip photos with a clip path). Returns (x0, y0, x1, y1) or None."""
    H, W = page_rgb.shape[:2]
    ih, iw = img.shape[:2]
    x0, y0, x1, y1 = place
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    # resample the rendered placement rectangle (inside the page) onto the native grid
    X0, Y0, X1, Y1 = max(0, int(np.floor(x0))), max(0, int(np.floor(y0))), min(W, int(np.ceil(x1))), min(H, int(np.ceil(y1)))
    if X1 - X0 < 4 or Y1 - Y0 < 4:
        return None
    sub = cv2.cvtColor(page_rgb[Y0:Y1, X0:X1], cv2.COLOR_RGB2GRAY).astype(np.float32)
    nx0 = int(round((X0 - x0) / (x1 - x0) * iw)); nx1 = int(round((X1 - x0) / (x1 - x0) * iw))
    ny0 = int(round((Y0 - y0) / (y1 - y0) * ih)); ny1 = int(round((Y1 - y0) / (y1 - y0) * ih))
    nx1, ny1 = min(iw, max(nx1, nx0 + 1)), min(ih, max(ny1, ny0 + 1))
    sub = cv2.resize(sub, (nx1 - nx0, ny1 - ny0), interpolation=cv2.INTER_AREA)
    ref = cv2.cvtColor(img[ny0:ny1, nx0:nx1], cv2.COLOR_RGB2GRAY).astype(np.float32)
    ok = np.abs(sub - ref) < 8
    r = _longest_run(ok.mean(axis=1) > 0.2)
    c = _longest_run(ok.mean(axis=0) > 0.2)
    if r is None or c is None or r[1] - r[0] < 4 or c[1] - c[0] < 4:
        return None
    x0, y0, x1, y1 = nx0 + c[0], ny0 + r[0], nx0 + c[1], ny0 + r[1]
    # anti-aliased borders are not clipping: snap edges that are within a few pixels
    tx, ty = max(4, int(0.012 * iw)), max(4, int(0.012 * ih))
    x0 = 0 if x0 <= tx else x0
    y0 = 0 if y0 <= ty else y0
    x1 = iw if iw - x1 <= tx else x1
    y1 = ih if ih - y1 <= ty else y1
    return (x0, y0, x1, y1)


def _longest_run(v: np.ndarray, gap: int = 3):
    """Longest stretch of True values, bridging gaps of up to ``gap`` False values."""
    idx = np.nonzero(v)[0]
    if len(idx) == 0:
        return None
    br = np.nonzero(np.diff(idx) > gap + 1)[0]
    starts = np.r_[idx[0], idx[br + 1]]
    ends = np.r_[idx[br], idx[-1]] + 1
    k = int(np.argmax(ends - starts))
    return int(starts[k]), int(ends[k])


def instrument_bar(gray: np.ndarray) -> Optional[dict]:
    """Scale bar drawn by the microscope software inside a white label box: a solid bar
    or a thin bracket |‾‾‾| with end ticks, and its text ("5 nm", "200 pm")."""
    H, W = gray.shape
    bright = (gray > 225).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(bright, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if y < 0.5 * H or w < 0.04 * W or w > 0.5 * W or h < 6 or w < 1.3 * h:
            continue
        filled = ndi.binary_fill_holes(lab[y:y + h, x:x + w] == i)
        if filled.mean() < 0.9:
            continue
        inner = gray[y + 1:y + h - 1, x + 1:x + w - 1].astype(float)
        if inner.size == 0:
            continue
        dark = inner < 0.5 * (inner.max() + inner.min())
        # longest dark horizontal run in the upper part of the box: the bar
        cand = None
        for r in range(dark.shape[0]):
            row = dark[r]
            if not row.any():
                continue
            idx = np.nonzero(row)[0]
            splits = np.nonzero(np.diff(idx) > 1)[0]
            starts = np.r_[idx[0], idx[splits + 1]]
            ends = np.r_[idx[splits], idx[-1]]
            k = int(np.argmax(ends - starts))
            L = ends[k] - starts[k] + 1
            if L >= 0.3 * dark.shape[1] and (cand is None or L > cand[0] + 0.5):
                cand = (L, r, starts[k], ends[k])
        if cand is None:
            continue
        L, r, a0, a1 = cand
        thick = 1
        while r + thick < dark.shape[0] and dark[r + thick, a0 + 2:max(a0 + 3, a1 - 1)].mean() > 0.8:
            thick += 1
        # end ticks: dark pixels below both ends, but not below the middle → bracket bar
        below = dark[r + thick:r + thick + 3]
        tick = below.shape[0] > 0 and below[:, max(0, a0 - 1):a0 + 2].any() and below[:, a1 - 1:a1 + 2].any()
        if tick:
            tw = max(1, int(dark[r + thick:r + thick + 2, a0:a0 + 4].sum(axis=1).max()) if below.shape[0] else 1)
            length = (a1 - a0 + 1) - tw            # tick centre to tick centre
        else:
            length = a1 - a0 + 1
        # text: OCR of the box with the bar removed, upscaled
        txt_img = gray[y:y + h, x:x + w].copy()
        txt_img[1 + r:1 + r + thick + 3, 1 + a0 - 1:1 + a1 + 2] = 255
        txt_img[:2, :] = 255; txt_img[-2:, :] = 255; txt_img[:, :2] = 255; txt_img[:, -2:] = 255
        val, unit, txt = None, None, ""
        for fz in (6, 4, 8):
            try:
                big = cv2.resize(txt_img, None, fx=fz, fy=fz, interpolation=cv2.INTER_CUBIC)
                t, _c = ocr.read_text(big, psm=7)
            except Exception:  # pragma: no cover
                break
            t = t.replace("pn", "pm").replace("prn", "pm").replace("O", "0").replace("o", "0")
            v, u = micro._parse_scale_text(t)
            if v is not None:
                val, unit, txt = v, u, t.strip()
                break
            txt = txt or t.strip()
        sc = L / dark.shape[1] + (1 if val is not None else 0)
        if best is None or sc > best[0]:
            best = (sc, {"length_px": float(length), "value": val, "unit": unit, "text": txt, "bracket": bool(tick),
                         "box": [int(x), int(y), int(x + w), int(y + h)], "uncertainty_px": 1.0})
    return best[1] if best else None


def _raster_frames(rgb: np.ndarray, min_frac=0.008, max_dim=1600) -> List[tuple]:
    H, W = rgb.shape[:2]
    f = min(1.0, max_dim / max(H, W))
    small = cv2.resize(rgb, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else rgb
    h, w = small.shape[:2]
    g = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    chroma = small.max(2).astype(int) - small.min(2)
    fg = ((g < 238) | (chroma > 18)).astype(np.uint8)
    k = max(3, int(0.012 * min(h, w)) | 1)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg, 8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if bw * bh < min_frac * h * w or max(bw / bh, bh / bw) > 8:
            continue
        filled = ndi.binary_fill_holes(lab[y:y + bh, x:x + bw] == i)
        if filled.mean() < 0.82:
            continue
        box = (x / f, y / f, (x + bw) / f, (y + bh) / f)
        out.append(_refine_edges(rgb, box))
    return out


def _refine_edges(rgb, box):
    """Move each edge of a frame box to the last row/column that is mostly non-blank."""
    H, W = rgb.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    pad = max(3, int(0.004 * max(H, W)))
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
    sub = rgb[Y0:Y1, X0:X1]
    g = cv2.cvtColor(sub, cv2.COLOR_RGB2GRAY)
    fg = (g < 238) | ((sub.max(2).astype(int) - sub.min(2)) > 18)
    cols = np.nonzero(fg.mean(axis=0) > 0.5)[0]
    rows = np.nonzero(fg.mean(axis=1) > 0.5)[0]
    if len(cols) < 2 or len(rows) < 2:
        return tuple(float(v) for v in box)
    return (float(X0 + cols[0]), float(Y0 + rows[0]), float(X0 + cols[-1] + 1), float(Y0 + rows[-1] + 1))


def find_frames(page, rgb: np.ndarray, embedded=None, exclude=()) -> List[Frame]:
    """Frames on a page. Vector pages use the embedded bitmaps (native pixels, exact
    placement); bitmaps are segmented into rectangular photographic regions.
    ``exclude``: page-pixel boxes (calibrated plots) whose images are plot content."""
    frames: List[Frame] = []
    H, W = rgb.shape[:2]
    off = page.meta.get("offset_px", (0, 0)) if page is not None else (0, 0)
    if embedded:
        for im in embedded:
            r = im["rect"]
            box = (r[0] * page.scale - off[0], r[1] * page.scale - off[1],
                   r[2] * page.scale - off[0], r[3] * page.scale - off[1])
            box = (max(0.0, box[0]), max(0.0, box[1]), min(float(W), box[2]), min(float(H), box[3]))
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                continue
            if (box[2] - box[0]) * (box[3] - box[1]) < 0.006 * W * H:
                continue
            if max((box[2] - box[0]) / (box[3] - box[1]), (box[3] - box[1]) / (box[2] - box[0])) > 8:
                continue      # colour bars, rules
            img = im["rgb"]
            ih, iw = img.shape[:2]
            # native px per page px; crop to the visible part of the placement rect
            fx, fy = iw / ((r[2] - r[0]) * page.scale), ih / ((r[3] - r[1]) * page.scale)
            ox, oy = r[0] * page.scale - off[0], r[1] * page.scale - off[1]
            cx0, cy0 = int(max(0, (box[0] - ox) * fx)), int(max(0, (box[1] - oy) * fy))
            cx1, cy1 = int(min(iw, np.ceil((box[2] - ox) * fx))), int(min(ih, np.ceil((box[3] - oy) * fy)))
            v = _visible_part(rgb, (ox, oy, ox + iw / fx, oy + ih / fy), img)
            if v is not None:
                cx0, cy0, cx1, cy1 = max(cx0, v[0]), max(cy0, v[1]), min(cx1, v[2]), min(cy1, v[3])
            if cx1 - cx0 < 8 or cy1 - cy0 < 8:
                continue
            fr = Frame(box, img[cy0:cy1, cx0:cx1].copy(), fx, fy, "vector-image", tuple(r))
            fr.box = (ox + cx0 / fx, oy + cy0 / fy, ox + cx1 / fx, oy + cy1 / fy)
            fr.full_rgb, fr.crop_off = img, (cx0, cy0)
            if (cx0, cy0, cx1, cy1) != (0, 0, iw, ih):
                fr.notes.append({"level": "info", "code": "clipped",
                                 "msg": f"Only native px ({cx0}, {cy0})–({cx1}, {cy1}) of the {iw}×{ih} bitmap are visible "
                                        "(the rest is clipped in the figure)."})
            frames.append(fr)
        # drop duplicates (same image placed twice at the same spot)
        keep = []
        for fr in sorted(frames, key=lambda f: -f.w * f.h):
            if any(_overlap(fr.box, k.box) > 0.97 and _overlap(k.box, fr.box) > 0.97 for k in keep):
                continue
            keep.append(fr)
        frames = keep
    else:
        for box in _raster_frames(rgb):
            x0, y0, x1, y1 = [int(round(v)) for v in box]
            frames.append(Frame(box, rgb[y0:y1, x0:x1].copy(), 1.0, 1.0, "raster"))
    frames = [f for f in frames if not any(_overlap(f.box, e) > 0.3 for e in exclude)]
    # parents: an inset lies (almost) entirely inside a larger frame
    frames.sort(key=lambda f: -f.w * f.h)
    for i, fr in enumerate(frames):
        for j in range(i):
            if _overlap(fr.box, frames[j].box) > 0.9 and frames[j].w * frames[j].h > 1.5 * fr.w * fr.h:
                fr.parent = j            # smallest enclosing comes last → keep overwriting
        if fr.parent is not None:
            frames[fr.parent].children.append(i)
    return frames


def reading_order(frames: List[Frame]) -> List[int]:
    """Indices of top-level frames in reading order (rows, then left→right)."""
    top = [i for i, f in enumerate(frames) if f.parent is None]
    if not top:
        return []
    hs = np.median([frames[i].h for i in top])
    return sorted(top, key=lambda i: (round(frames[i].box[1] / (0.5 * hs)), frames[i].box[0]))


# ───────────────────────── text ─────────────────────────
def vector_text_blocks(pdf_page, scale: float, off=(0, 0)) -> List[dict]:
    """Lines of text (page px) merged into blocks; subscripts/superscripts become mathtext."""
    lines = []
    for b in pdf_page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            if abs(ln["dir"][1]) > 0.2:
                continue
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            big = max(s["size"] for s in spans)
            base = max(s["origin"][1] for s in spans if s["size"] >= 0.95 * big)
            txt = ""
            for s in spans:
                t = s["text"]
                if s["size"] < 0.85 * big and t.strip():
                    t = ("$_{%s}$" if s["origin"][1] > base - 0.1 * big else "$^{%s}$") % t.strip()
                txt += t
            x0 = min(s["bbox"][0] for s in spans); y0 = min(s["bbox"][1] for s in spans)
            x1 = max(s["bbox"][2] for s in spans); y1 = max(s["bbox"][3] for s in spans)
            col = spans[0]["color"]
            lines.append({"text": txt.strip(), "box": [x0 * scale - off[0], y0 * scale - off[1],
                                                       x1 * scale - off[0], y1 * scale - off[1]],
                          "size_pt": big, "bold": bool(spans[0]["flags"] & 16),
                          "color": ((col >> 16) & 255, (col >> 8) & 255, col & 255)})
    return merge_lines(lines)


def merge_lines(lines: List[dict], key=None) -> List[dict]:
    """Stack lines into blocks: same size, baseline step ≤ 1.4 × size, overlapping in x,
    and (if ``key`` is given) the same key – e.g. the frame the line sits on."""
    lines = sorted(lines, key=lambda l: (l["box"][3], l["box"][0]))
    blocks = []
    for ln in lines:
        h = ln["box"][3] - ln["box"][1]
        k = key(ln) if key else None
        for bl in blocks:
            last = bl["lines"][-1]
            step = ln["box"][3] - last["box"][3]
            ov = min(ln["box"][2], last["box"][2]) - max(ln["box"][0], last["box"][0])
            if (bl["key"] == k and 0.5 * h < step < 1.4 * h and abs(h / (last["box"][3] - last["box"][1]) - 1) < 0.15
                    and ov > 0.3 * min(ln["box"][2] - ln["box"][0], last["box"][2] - last["box"][0])):
                bl["lines"].append(ln)
                bl["box"] = [min(bl["box"][0], ln["box"][0]), min(bl["box"][1], ln["box"][1]),
                             max(bl["box"][2], ln["box"][2]), max(bl["box"][3], ln["box"][3])]
                break
        else:
            blocks.append({"lines": [ln], "box": list(ln["box"]), "key": k})
    for bl in blocks:
        bl["text"] = " ".join(l["text"] for l in bl["lines"])
    return blocks


def raster_titles(rgb: np.ndarray, frames: List[Frame]):
    """OCR the text line printed just above each top-level frame (bitmap pages)."""
    H, W = rgb.shape[:2]
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    for fr in frames:
        if fr.parent is not None:
            continue
        x0, y0, x1, y1 = [int(round(v)) for v in fr.box]
        span = int(min(0.25 * (y1 - y0), 0.12 * H))
        X0, X1 = max(0, int(x0 - 0.1 * (x1 - x0))), min(W, int(x1 + 0.1 * (x1 - x0)))
        Y0, Y1 = max(0, y0 - span), max(0, y0 - 2)
        if Y1 - Y0 < 6:
            continue
        sub = g[Y0:Y1, X0:X1]
        csub = rgb[Y0:Y1, X0:X1]
        ink = ((sub < 120) & ((csub.max(2).astype(int) - csub.min(2)) < 60)).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(ink, 8)
        comps = [st[i] for i in range(1, n) if st[i][4] >= 3 and st[i][3] >= 3 and st[i][2] < 0.8 * (X1 - X0)]
        if not comps:
            continue
        hmed = float(np.median([c[3] for c in comps]))
        low = max(c[1] + c[3] for c in comps)
        line = [c for c in comps if c[1] + c[3] >= low - 0.6 * hmed]
        cx0 = min(c[0] for c in line); cx1 = max(c[0] + c[2] for c in line)
        cy0 = min(c[1] for c in line); cy1 = max(c[1] + c[3] for c in line)
        if cy1 - cy0 < 4:
            continue
        pad = max(3, (cy1 - cy0) // 3)
        crop = np.full((cy1 - cy0 + 2 * pad, cx1 - cx0 + 2 * pad), 255, np.uint8)
        m = np.zeros_like(ink, bool)
        for c in line:
            m[c[1]:c[1] + c[3], c[0]:c[0] + c[2]] = True
        part = np.where(m[cy0:cy1, cx0:cx1], sub[cy0:cy1, cx0:cx1], 255)
        crop[pad:pad + cy1 - cy0, pad:pad + cx1 - cx0] = part
        try:
            txt, conf = ocr.read_text(crop, psm=7)
        except Exception:  # pragma: no cover
            continue
        txt = txt.strip()
        if txt and conf >= 55:
            fr.title = txt


def parse_dlabel(text: str) -> Optional[dict]:
    m = _D_RE.search(text)
    if not m:
        return None
    unit = {"a": "Å", "A": "Å"}.get(m.group(2), m.group(2).lower() if m.group(2) != "Å" else "Å")
    d = float(m.group(1).replace(",", "."))
    h = _HKL_RE.search(text[m.end():]) or _HKL_RE.search(text)
    hkl = "(" + "".join(g for g in h.groups() if g is not None) + ")" if h else ""
    return {"d": d, "unit": unit, "d_nm": d * UNIT_NM[unit], "hkl": hkl, "text": text}


def parse_value(text: str):
    """'5 min' → (5.0, 'min'); '20' → (20.0, ''); otherwise None."""
    t = text.replace("$", "").replace("_{", "").replace("^{", "").replace("}", "")
    m = _VAL_RE.match(t)
    if not m:
        return None
    return float(m.group(1).replace(",", ".")), (m.group(2) or "").replace("μ", "µ")


# ───────────────────────── vector annotations ─────────────────────────
def _rgb255(c):
    return tuple(int(round(255 * v)) for v in c[:3]) if c is not None else None


def _items_native(items, frame: Frame, scale: float, off) -> list:
    """Drawing items (PDF points) → items in native px of ``frame``."""
    def P(p):
        x, y = frame.to_native(p.x * scale - off[0], p.y * scale - off[1])
        return (float(x), float(y))
    out = []
    for it in items:
        op = it[0]
        if op == "l":
            out.append(("l", P(it[1]), P(it[2])))
        elif op == "c":
            out.append(("c", P(it[1]), P(it[2]), P(it[3]), P(it[4])))
        elif op == "re":
            r = it[1]
            out.append(("re", P(r.tl), P(r.br)))
        elif op == "qu":
            q = it[1]
            out.append(("qu", P(q.ul), P(q.ur), P(q.lr), P(q.ll)))
    return out


def _poly_points(items) -> np.ndarray:
    pts = []
    for it in items:
        if it[0] == "l":
            pts += [it[1], it[2]]
        elif it[0] == "c":
            pts += [it[1], it[4]]
        elif it[0] == "re":
            (x0, y0), (x1, y1) = it[1], it[2]
            pts += [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        elif it[0] == "qu":
            pts += list(it[1:])
    a = np.asarray(pts, float)
    if len(a) > 1:   # drop consecutive duplicates
        a = a[np.r_[True, np.hypot(*np.diff(a, axis=0).T) > 1e-6]]
    return a


def attach_vector_content(page, frames: List[Frame], blocks: List[dict]):
    """Assign vector drawings and text to frames: annotations (for measurement) go to the
    smallest frame containing them, replot paths/texts to the top-level frame."""
    pg = page.pdf_page
    s = page.scale
    off = page.meta.get("offset_px", (0, 0))
    try:
        draws = pg.get_drawings()
    except Exception:  # pragma: no cover
        draws = []

    def host(box, frac=0.6):
        best = None
        for i, fr in enumerate(frames):
            if _overlap(box, fr.box) >= frac:
                if best is None or fr.w * fr.h < frames[best].w * frames[best].h:
                    best = i
        return best

    def top(i):
        while frames[i].parent is not None:
            i = frames[i].parent
        return i

    per_frame = {i: [] for i in range(len(frames))}
    for k, d in enumerate(draws):
        r = d["rect"]
        box = (r.x0 * s - off[0], r.y0 * s - off[1], r.x1 * s - off[0], r.y1 * s - off[1])
        if box[2] - box[0] < 0.5 and box[3] - box[1] < 0.5:
            continue
        i = host((box[0] - 0.5, box[1] - 0.5, box[2] + 0.5, box[3] + 0.5))
        if i is None:
            continue
        fr = frames[i]
        if (box[2] - box[0]) * (box[3] - box[1]) > 0.85 * fr.w * fr.h:
            continue                  # frame border / background
        stroke, fill = _rgb255(d.get("color")), _rgb255(d.get("fill"))
        if stroke is None and fill is None:
            continue
        per_frame[i].append((k, d, box, stroke, fill))

    for i, lst in per_frame.items():
        fr = frames[i]
        T = top(i)
        for k, d, box, stroke, fill in lst:
            nat = _items_native(d["items"], fr, s, off)
            pts = _poly_points(nat)
            w = (d.get("width") or 1.0) * s * fr.sx
            dashed = bool(d.get("dashes")) and d.get("dashes") not in ("[] 0", "[] 0.0")
            ann = None
            # straight Bézier segments (matplotlib arrows, Inkscape lines) count as lines
            nat = [("l", it[1], it[4]) if it[0] == "c" and _collinear(it[1:]) else it for it in nat]
            pts = _poly_points(nat)
            only_lines = all(it[0] == "l" for it in nat)
            small = max(box[2] - box[0], box[3] - box[1]) < 0.12 * max(fr.w, fr.h)
            if d["type"] in ("s", "fs") and stroke is not None:
                if all(it[0] == "re" for it in nat) and len(nat) == 1:
                    (x0, y0), (x1, y1) = nat[0][1], nat[0][2]
                    ann = Annotation("rect", np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]), stroke, w, dashed)
                elif only_lines and len(pts) >= 2:
                    straight = len(pts) == 2 or _max_dev(pts) < max(1.5, 0.02 * np.hypot(*(pts[-1] - pts[0])))
                    ann = Annotation("line" if straight else "polyline",
                                     pts[[0, -1]] if straight else pts, stroke, w, dashed)
                    if not straight:
                        arr = _shaft_and_head(pts)
                        if arr is not None:
                            ann = Annotation("arrow", arr, stroke, w, dashed)
            if d["type"] in ("f", "fs") and fill is not None and only_lines and 3 <= len(pts) <= 8 and small:
                ann = Annotation("head", pts, fill, w if (d["type"] == "fs" and stroke is not None) else 0, False)
            if ann is not None:
                ann._draw_id = k
                fr.annotations.append(ann)
            frames[T].drawings.append({"id": k, "items": _items_native(d["items"], frames[T], s, off),
                                       "stroke": stroke if d["type"] in ("s", "fs") else None,
                                       "fill": fill if d["type"] in ("f", "fs") else None,
                                       "lw_px": (d.get("width") or 1.0) * s * frames[T].sx,
                                       "dashes": d.get("dashes"), "even_odd": bool(d.get("even_odd")),
                                       "closed": bool(d.get("closePath"))})
        _make_arrows(fr)

    # text: labels on frames, titles just above top-level frames, the rest is page text
    blocks[:] = merge_lines([ln for bl in blocks for ln in bl["lines"]], key=lambda ln: host(ln["box"], 0.5))
    order = reading_order(frames)
    page_text = []
    used = set()
    for bi, bl in enumerate(blocks):
        i = host(bl["box"], 0.5)
        if i is None:
            continue
        used.add(bi)
        fr = frames[i]
        nx, ny = fr.to_native([bl["box"][0], bl["box"][2]], [bl["box"][1], bl["box"][3]])
        lab = {"text": bl["text"], "block": bi, "box": [float(nx[0]), float(ny[0]), float(nx[1]), float(ny[1])],
               "color": bl["lines"][0]["color"], "bold": bl["lines"][0]["bold"], "lines": [l["text"] for l in bl["lines"]]}
        fr.labels.append(lab)
        dl = parse_dlabel(bl["text"])
        if dl:
            dl["box"] = lab["box"]
            fr.dlabels.append(dl)
        T = top(i)
        tx, ty = frames[T].to_native([bl["box"][0], bl["box"][2]], [bl["box"][1], bl["box"][3]])
        frames[T].texts.append({"block": bi, "lines": [l["text"] for l in bl["lines"]],
                                "box": [float(tx[0]), float(ty[0]), float(tx[1]), float(ty[1])],
                                "color": bl["lines"][0]["color"], "bold": bl["lines"][0]["bold"],
                                "size_frac": (bl["lines"][0]["box"][3] - bl["lines"][0]["box"][1]) / frames[T].h})
    # titles: closest unused block above each top-level frame
    cand = []
    for i in order:
        fr = frames[i]
        for bi, bl in enumerate(blocks):
            if bi in used:
                continue
            h = bl["box"][3] - bl["box"][1]
            gap = fr.box[1] - bl["box"][3]
            cx = 0.5 * (bl["box"][0] + bl["box"][2])
            if -0.3 * h <= gap <= 2.5 * h and fr.box[0] - 0.15 * fr.w <= cx <= fr.box[2] + 0.15 * fr.w:
                cand.append((gap, i, bi))
    for gap, i, bi in sorted(cand):
        if frames[i].title or bi in used:
            continue
        frames[i].title = blocks[bi]["text"]
        used.add(bi)
    for bi, bl in enumerate(blocks):
        if bi not in used:
            page_text.append(bl)
    return page_text


def _collinear(p, tol=0.5) -> bool:
    a, b = np.asarray(p[0], float), np.asarray(p[-1], float)
    d = b - a
    L = np.hypot(*d)
    if L < 1e-9:
        return False
    n = np.array([-d[1], d[0]]) / L
    return all(abs((np.asarray(q, float) - a) @ n) < max(tol, 0.01 * L) for q in p[1:-1])


def _shaft_and_head(pts: np.ndarray):
    """One path = long shaft + small head polygon at one end (matplotlib, Inkscape markers
    converted to paths): return [tail, tip] or None."""
    if len(pts) < 4:
        return None
    seg = np.hypot(*np.diff(pts, axis=0).T)
    k = int(np.argmax(seg))
    L = seg[k]
    a, b = pts[k], pts[k + 1]
    rest = np.delete(pts, [k, k + 1], axis=0)
    if len(rest) == 0:
        return None
    da, db = np.hypot(*(rest - a).T).max(), np.hypot(*(rest - b).T).max()
    tail, end = (a, b) if db < da else (b, a)
    near = rest[np.hypot(*(rest - end).T) < 0.4 * L]
    if len(near) < 2 or len(near) < 0.8 * len(rest):
        return None
    u = (end - tail) / L
    tip = near[np.argmax((near - tail) @ u)]
    if (tip - tail) @ u < 0.98 * L:
        tip = end
    return np.array([tail, tip])


def _max_dev(pts: np.ndarray) -> float:
    a, b = pts[0], pts[-1]
    d = b - a
    L = np.hypot(*d)
    if L < 1e-9:
        return float(np.max(np.hypot(*(pts - a).T)))
    n = np.array([-d[1], d[0]]) / L
    return float(np.max(np.abs((pts - a) @ n)))


def _make_arrows(fr: Frame):
    """Join a line with a small filled head at one end into an arrow (tail → tip)."""
    lines = [a for a in fr.annotations if a.kind == "line"]
    heads = [a for a in fr.annotations if a.kind == "head"]
    used = set()
    for ln in lines:
        best = None
        for hi, hd in enumerate(heads):
            if hi in used or _cdist(ln.color, hd.color) > 40:
                continue
            size = max(np.ptp(hd.pts[:, 0]), np.ptp(hd.pts[:, 1]))
            if size > 0.6 * ln.length_px:
                continue
            for e in (0, 1):
                end, other = ln.pts[e], ln.pts[1 - e]
                c = hd.pts.mean(axis=0)
                if np.hypot(*(end - c)) > 1.2 * size:
                    continue
                tip = hd.pts[np.argmax(np.hypot(*(hd.pts - other).T))]
                v1, v2 = tip - other, end - other
                cosang = v1 @ v2 / (np.hypot(*v1) * np.hypot(*v2) + 1e-9)
                if cosang < np.cos(np.radians(15)):
                    continue
                score = np.hypot(*(end - c))
                if best is None or score < best[0]:
                    best = (score, hi, e, tip)
        if best:
            _, hi, e, tip = best
            used.add(hi)
            hd = heads[hi]
            tail = ln.pts[1 - e]
            if hd.width_px > 0:      # stroked head: the visible tip is the miter of the outline
                P = hd.pts
                k = int(np.argmin(np.hypot(*(P - tip).T)))
                nb = [P[(k - 1) % len(P)], P[(k + 1) % len(P)]]
                v1, v2 = nb[0] - tip, nb[1] - tip
                cosa = v1 @ v2 / (np.hypot(*v1) * np.hypot(*v2) + 1e-12)
                half = 0.5 * np.arccos(np.clip(cosa, -1, 1))
                if half > np.radians(5):
                    u = (tip - tail) / (np.hypot(*(tip - tail)) + 1e-12)
                    tip = tip + u * (0.5 * hd.width_px / np.sin(half))
            ln.kind = "arrow"
            ln.pts = np.array([tail, tip])
            ln._head_id = getattr(heads[hi], "_draw_id", None)
    used_ids = {id(heads[k]) for k in used}
    fr.annotations = [a for a in fr.annotations if id(a) not in used_ids]


def _cdist(a, b) -> float:
    return float(np.sqrt(sum((int(x) - int(y)) ** 2 for x, y in zip(a, b))))


# ───────────────────────── scale bars ─────────────────────────
def vector_scale_bars(frames: List[Frame], blocks: List[dict], page):
    """A scale bar is a straight horizontal stroke (or thin filled bar) on a frame;
    its value is the unit text right above or below it."""
    for fi, fr in enumerate(frames):
        cands = []
        for a in fr.annotations:
            if a.kind not in ("line", "rect") or a.dashed:
                continue
            p = a.pts
            if a.kind == "line":
                if abs(p[1, 1] - p[0, 1]) > max(0.5, 0.02 * a.length_px):
                    continue
                x0, x1, y = min(p[:, 0]), max(p[:, 0]), 0.5 * (p[0, 1] + p[1, 1])
                thick = a.width_px
            else:
                x0, x1 = p[:, 0].min(), p[:, 0].max()
                y0, y1 = p[:, 1].min(), p[:, 1].max()
                if (y1 - y0) > 0.25 * (x1 - x0):
                    continue
                y, thick = 0.5 * (y0 + y1), y1 - y0
            L = x1 - x0
            if L < 0.02 * fr.rgb.shape[1] or L > 0.6 * fr.rgb.shape[1]:
                continue
            cands.append((a, x0, x1, y, thick))
        # filled thin bars ("f" rectangles) were not kept as annotations: look in drawings
        for d in (fr.drawings if fr.parent is None else []):
            if d["fill"] is None or d["stroke"] is not None or len(d["items"]) != 1 or d["items"][0][0] != "re":
                continue
            (x0, y0), (x1, y1) = d["items"][0][1], d["items"][0][2]
            x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
            if (y1 - y0) < 0.25 * (x1 - x0) and 0.02 * fr.rgb.shape[1] < x1 - x0 < 0.6 * fr.rgb.shape[1]:
                a = Annotation("rect", np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]), d["fill"], 0)
                a._draw_id = d["id"]
                cands.append((a, x0, x1, 0.5 * (y0 + y1), y1 - y0))
        best = None
        for a, x0, x1, y, thick in cands:
            L = x1 - x0
            for lab in fr.labels:
                val, unit = micro._parse_scale_text(lab["text"])
                if val is None or parse_dlabel(lab["text"]):
                    continue
                bx = lab["box"]
                th = bx[3] - bx[1]
                cx = 0.5 * (bx[0] + bx[2])
                gap = min(abs(y - bx[3]), abs(bx[1] - y))
                if not (x0 - 0.5 * L <= cx <= x1 + 0.5 * L) or gap > 1.6 * th + thick:
                    continue
                score = gap / th + abs(cx - 0.5 * (x0 + x1)) / L
                if best is None or score < best[0]:
                    best = (score, a, x0, x1, y, thick, lab, val, unit)
        if best:
            _, a, x0, x1, y, thick, lab, val, unit = best
            fr.bar = micro.ScaleBar(x0, x1, y, thick, x1 - x0, val, unit, lab["text"], None, None,
                                    "white" if np.mean(a.color) > 127 else "black")
            fr.bar._source = "vector"
            fr.nm_per_px = fr.bar.nm_per_px
            fr.bar_hidden = [getattr(a, "_draw_id", -1)]
            fr._bar_label = lab
            fr.annotations = [q for q in fr.annotations if q is not a]
        # remaining short horizontal strokes near a corner without text: unlabelled bars
        for a, x0, x1, y, thick in cands:
            if fr.bar is not None and abs(x0 - fr.bar.x0) < 1e-6 and abs(y - fr.bar.y) < 1e-6:
                continue
            Hn, Wn = fr.rgb.shape[:2]
            if a.kind == "line" and (y > 0.7 * Hn or y < 0.3 * Hn) and (x1 - x0) < 0.3 * Wn and any(a is q for q in fr.annotations):
                fr.unlabelled_bars.append(a)


# ───────────────────────── raster annotations ─────────────────────────
def raster_annotations(rgb: np.ndarray, min_len_frac=0.04) -> List[Annotation]:
    """Strongly saturated thin strokes (drawn lines/arrows) on a photograph."""
    H, W = rgb.shape[:2]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    S, V, Hh = hsv[..., 1].astype(int), hsv[..., 2].astype(int), hsv[..., 0].astype(int)
    thr = max(90, int(np.percentile(S, 97)) + 15)
    cand = (S >= thr) & (V >= 80)
    if cand.mean() > 0.15 or cand.sum() < 20:
        return []
    hist = np.bincount(Hh[cand], minlength=180).astype(float)
    hist = ndi.gaussian_filter1d(hist, 2, mode="wrap")
    peaks = [i for i in range(180) if hist[i] > 0.05 * hist.max() and hist[i] >= hist[(i - 1) % 180]
             and hist[i] >= hist[(i + 1) % 180]]
    out = []
    minL = min_len_frac * min(H, W)
    for pk in peaks:
        dh = np.minimum(np.abs(Hh - pk), 180 - np.abs(Hh - pk))
        m = cand & (dh <= 10)
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
        col = tuple(int(v) for v in np.median(rgb[m.astype(bool) & cand], axis=0))
        for i in range(1, n):
            ys, xs = np.nonzero(lab == i)
            if len(xs) < 10:
                continue
            P = np.c_[xs, ys].astype(float)
            c = P.mean(axis=0)
            u, sv, vt = np.linalg.svd(P - c, full_matrices=False)
            d = vt[0]
            t = (P - c) @ d
            L = t.max() - t.min()
            if L < minL:
                continue
            width = len(xs) / max(L, 1)
            if width > max(4.0, 0.25 * L):
                continue
            nrm = np.array([-d[1], d[0]])
            q = (P - c) @ nrm
            ends = []
            for side in (t.min(), t.max()):
                sel = np.abs(t - side) < max(1.0, 0.5 * width)
                ends.append(c + side * d + np.median(q[sel]) * nrm)
            # width profile: a head makes one end markedly wider
            nb = 20
            bins = np.clip(((t - t.min()) / (L + 1e-9) * nb).astype(int), 0, nb - 1)
            prof = np.bincount(bins, minlength=nb) / (L / nb)
            med = np.median(prof)
            kind, pts = "line", np.array(ends)
            if prof[-3:].max() > 2.2 * med and prof[:3].max() < 1.6 * med:
                kind, pts = "arrow", np.array([ends[0], c + t.max() * d])
            elif prof[:3].max() > 2.2 * med and prof[-3:].max() < 1.6 * med:
                kind, pts = "arrow", np.array([ends[1], c + t.min() * d])
            out.append(Annotation(kind, pts, col, float(np.median(prof)), False, "raster"))
    return _merge_collinear(out, max(3.0, 0.006 * max(H, W)))


def _merge_collinear(anns: List[Annotation], tol: float) -> List[Annotation]:
    """Join pieces of one drawn line that were split (crossings, JPEG, thin strokes)."""
    lines = [a for a in anns if a.kind == "line"]
    rest = [a for a in anns if a.kind != "line"]
    merged = True
    while merged:
        merged = False
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                a, b = lines[i], lines[j]
                if _cdist(a.color, b.color) > 60:
                    continue
                d = a.pts[1] - a.pts[0]
                L = np.hypot(*d)
                if L < 1e-6:
                    continue
                d = d / L
                n = np.array([-d[1], d[0]])
                if max(abs((b.pts - a.pts[0]) @ n)) > tol:
                    continue
                ta = sorted(a.pts @ d); tb = sorted(b.pts @ d)
                if max(ta[0], tb[0]) - min(ta[1], tb[1]) > 0.25 * (ta[1] - ta[0] + tb[1] - tb[0]):
                    continue
                P = np.vstack([a.pts, b.pts]); t = P @ d
                a.pts = np.array([P[np.argmin(t)], P[np.argmax(t)]])
                lines.pop(j)
                merged = True
                break
            if merged:
                break
    return rest + lines


# ───────────────────────── lattice fringes (FFT) ─────────────────────────
def lattice_peaks(gray: np.ndarray, max_peaks: int = 4, min_snr: float = 9.0) -> List[dict]:
    """Strongest periodicities: period (px) and fringe-normal direction from the 2D FFT."""
    g = gray.astype(float)
    H, W = g.shape
    if min(H, W) < 48:
        return []
    g = g - ndi.gaussian_filter(g, max(H, W) / 20)
    win = np.outer(np.hanning(H), np.hanning(W))
    F = np.fft.fftshift(np.abs(np.fft.fft2(g * win)) ** 2)
    cy, cx = H // 2, W // 2
    yy, xx = np.mgrid[0:H, 0:W]
    fy, fx = (yy - cy) / H, (xx - cx) / W
    fr = np.hypot(fx, fy)
    valid = (fr > max(4.0 / min(H, W), 0.02)) & (fr < 0.48)
    P = ndi.gaussian_filter(F, 0.8)
    # radial background: median power at each spatial frequency
    rbin = np.clip((fr * 2 * max(H, W)).astype(int), 0, None)
    med = ndi.median(P, labels=rbin, index=np.arange(rbin.max() + 1)) if valid.any() else None
    bg = np.asarray(med)[rbin] + 1e-12
    snr = np.where(valid, P / bg, 0)
    mx = ndi.maximum_filter(snr, size=5)
    pk = np.argwhere((snr == mx) & (snr >= min_snr) & (yy * W + xx > cy * W + cx))   # one of each ± pair
    res = []
    for y, x in sorted(pk, key=lambda p: -snr[p[0], p[1]])[:4 * max_peaks]:
        y0, y1, x0, x1 = max(0, y - 1), min(H, y + 2), max(0, x - 1), min(W, x + 2)
        w = P[y0:y1, x0:x1]
        ys, xs = np.mgrid[y0:y1, x0:x1]
        yc, xc = (w * ys).sum() / w.sum(), (w * xs).sum() / w.sum()
        f1, f2 = (xc - cx) / W, (yc - cy) / H
        f = np.hypot(f1, f2)
        res.append({"period_px": float(1 / f), "angle_deg": float(np.degrees(np.arctan2(-f2, f1)) % 180),
                    "snr": float(snr[y, x]), "_f": (f1, f2)})
    for r in res:
        r.update(refine_fringes(g, r["_f"]))
    # drop harmonics (period ≈ p/2, p/3 at the same angle) and near-duplicates
    keep = []
    for r in res:
        dup = False
        for k in keep:
            da = min(abs(r["angle_deg"] - k["angle_deg"]), 180 - abs(r["angle_deg"] - k["angle_deg"]))
            if da < 4 and any(abs(r["period_px"] * n / k["period_px"] - 1) < 0.04 for n in (1, 2, 3)):
                dup = True
                break
        if not dup:
            keep.append(r)
        if len(keep) == max_peaks:
            break
    for k in keep:
        k.pop("_f", None)
    return keep


def _zoom_peak(g: np.ndarray, f0, half_bin: float = 0.7, n: int = 15):
    """Continuous-frequency DFT around f0 = (fx, fy) cycles/px (Hann-weighted); returns the
    refined frequency vector."""
    H, W = g.shape
    w = np.outer(np.hanning(H), np.hanning(W))
    fx0, fy0 = f0
    for step in (half_bin / W, half_bin / (4 * W)):
        dfx = np.linspace(-step, step, n) if step else [0]
        dfy = np.linspace(-step * W / H, step * W / H, n)
        # separable evaluation: exp(-2πi(fx x + fy y)) = exp(-2πi fx x) exp(-2πi fy y)
        A = (g - g.mean()) * w
        Ex = np.exp(-2j * np.pi * np.outer(fx0 + dfx, np.arange(W)))      # n × W
        Ey = np.exp(-2j * np.pi * np.outer(fy0 + dfy, np.arange(H)))      # n × H
        P = np.abs(Ey @ A @ Ex.T) ** 2                                      # n(fy) × n(fx)
        j, i = np.unravel_index(np.argmax(P), P.shape)
        fx1, fy1 = fx0 + dfx[i], fy0 + dfy[j]
        if 0 < i < n - 1:
            a_, b_, c_ = P[j, i - 1], P[j, i], P[j, i + 1]
            d = a_ - 2 * b_ + c_
            if d < 0:
                fx1 += 0.5 * (a_ - c_) / d * (dfx[1] - dfx[0])
        if 0 < j < n - 1:
            a_, b_, c_ = P[j - 1, i], P[j, i], P[j + 1, i]
            d = a_ - 2 * b_ + c_
            if d < 0:
                fy1 += 0.5 * (a_ - c_) / d * (dfy[1] - dfy[0])
        fx0, fy0 = fx1, fy1
    return fx0, fy0


def refine_fringes(g: np.ndarray, f0) -> dict:
    """Precise fringe period and direction (zoomed DFT), with a ± from the four quadrants."""
    fx, fy = _zoom_peak(g, f0)
    f = np.hypot(fx, fy)
    out = {"period_px": float(1 / f), "angle_deg": float(np.degrees(np.arctan2(-fy, fx)) % 180)}
    H, W = g.shape
    est = []
    if min(H, W) >= 96:
        for sy in (slice(0, H // 2), slice(H // 2, H)):
            for sx in (slice(0, W // 2), slice(W // 2, W)):
                try:
                    q = g[sy, sx]
                    qx, qy = _zoom_peak(q - ndi.gaussian_filter(q, max(q.shape) / 10), (fx, fy), half_bin=0.5)
                    est.append(1 / np.hypot(qx, qy))
                except Exception:  # pragma: no cover
                    pass
    if len(est) >= 3:
        out["period_sd_px"] = float(np.std(est, ddof=1) / np.sqrt(len(est)))
    return out


def _nice_len(v: float) -> float:
    e = 10 ** np.floor(np.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e * 1.12:
            return m * e
    return 10 * e



# ───────────────────────── inset registration ─────────────────────────
def register_inset(parent_gray: np.ndarray, inset_gray: np.ndarray, mags=(1.2, 16.0)) -> Optional[dict]:
    """Find where an inset comes from in its parent image and its magnification
    (multi-scale normalised cross-correlation, refined to 0.1 %)."""
    P = parent_gray.astype(np.float32)
    T0 = inset_gray.astype(np.float32)

    def score(m):
        t = cv2.resize(T0, None, fx=1 / m, fy=1 / m, interpolation=cv2.INTER_AREA)
        if t.shape[0] < 12 or t.shape[1] < 12 or t.shape[0] >= P.shape[0] or t.shape[1] >= P.shape[1]:
            return -1.0, None, None
        r = cv2.matchTemplate(P, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        return float(mx), loc, t.shape

    grid = np.geomspace(mags[0], mags[1], 90)
    sc = [score(m)[0] for m in grid]
    k = int(np.argmax(sc))
    if sc[k] < 0.5:
        return None
    lo, hi = grid[max(0, k - 1)], grid[min(len(grid) - 1, k + 1)]
    fine = np.linspace(lo, hi, 41)
    fs = [score(m)[0] for m in fine]
    j = int(np.argmax(fs))
    m = fine[j]
    if 0 < j < len(fine) - 1:      # parabolic peak
        a, b, c = fs[j - 1], fs[j], fs[j + 1]
        den = a - 2 * b + c
        if den < 0:
            m = fine[j] + 0.5 * (a - c) / den * (fine[1] - fine[0])
    ncc, loc, shp = score(m)
    if ncc < 0.6:
        return None
    return {"mag": float(m), "ncc": ncc, "box": [float(loc[0]), float(loc[1]), float(loc[0] + shp[1]), float(loc[1] + shp[0])]}

# ───────────────────────── per-frame analysis ─────────────────────────
def analyse_frames(frames: List[Frame], scale_override: Optional[str] = None, lattice: bool = True):
    """Scale bars (raster fallback), FFT lattice, d-label cross-checks, notes."""
    manual = None
    if scale_override:
        m = re.match(r"\s*([\d.]+)\s*=\s*([\d.]+)\s*(\S+)", scale_override)
        if m:
            unit = m.group(3).replace("um", "µm")
            manual = float(m.group(2)) * UNIT_NM.get(unit, 1.0) / float(m.group(1))
    for fr in frames:
        if fr.bar is None and fr.source == "raster" and fr.parent is None:
            try:
                bar = micro.find_scale_bar(fr.rgb)
                if bar is not None and bar.value is not None:
                    fr.bar = bar
                    fr.bar._source = "pixels"
                    fr.nm_per_px = bar.nm_per_px
            except Exception:  # pragma: no cover
                pass
        if fr.bar is not None and fr.nm_per_px:
            src = getattr(fr.bar, "_source", "pixels")
            fr.notes.append({"level": "info", "code": "scale",
                             "msg": f"Scale bar {fr.bar.value:g} {fr.bar.unit} = {fr.bar.length_px:.2f} native px "
                                    f"({'drawn in the figure' if src == 'vector' else 'read from the pixels'}) → {fr.nm_per_px:.4g} nm/px."})
        # the microscope's own bar, burnt into the bitmap (often clipped away in the figure)
        if fr.source == "vector-image" and fr.full_rgb is not None:
            try:
                ib = instrument_bar(cv2.cvtColor(fr.full_rgb, cv2.COLOR_RGB2GRAY))
            except Exception:  # pragma: no cover
                ib = None
            if ib is not None:
                x0, y0, x1, y1 = ib["box"]
                cx0, cy0 = fr.crop_off
                ch, cw = fr.rgb.shape[:2]
                ib["visible"] = bool(x0 >= cx0 and y0 >= cy0 and x1 <= cx0 + cw and y1 <= cy0 + ch)
                fr.instrument_bar = ib
                where = "visible" if ib["visible"] else "hidden by the figure's clip"
                if ib["value"] is not None:
                    ib["nm_per_px"] = ib["value"] * UNIT_NM[ib["unit"]] / ib["length_px"]
                    if fr.nm_per_px:
                        dev = fr.nm_per_px / ib["nm_per_px"] - 1
                        fr.notes.append({"level": "warn" if abs(dev) > 0.03 else "info", "code": "bar_crosscheck",
                                         "msg": f"Microscope's own bar ({where}): {ib['value']:g} {ib['unit']} = {ib['length_px']:.1f} px "
                                                f"→ {ib['nm_per_px']:.4g} nm/px; the figure's bar differs by {dev * 100:+.1f}%."})
                    else:
                        fr.nm_per_px = ib["nm_per_px"]
                        fr.notes.append({"level": "info", "code": "scale",
                                         "msg": f"Scale from the microscope's own bar ({where}): {ib['value']:g} {ib['unit']} = "
                                                f"{ib['length_px']:.1f} ± 1 px → {fr.nm_per_px:.4g} nm/px."})
        if fr.nm_per_px is None and manual:
            fr.nm_per_px = manual
            fr.notes.append({"level": "info", "code": "scale_manual", "msg": f"Manual scale {scale_override} → {manual:.4g} nm/px."})
    # insets: magnified crops of their parent inherit (or cross-check) its calibration
    for fr in frames:
        if fr.parent is None:
            continue
        par = frames[fr.parent]
        try:
            reg = register_inset(par.gray, fr.gray)
        except Exception:  # pragma: no cover
            reg = None
        fr.registration = reg
        if reg is None:
            fr.notes.append({"level": "info", "code": "inset_unmatched",
                             "msg": "Inset is not a magnified crop of the surrounding image (no match)."})
            continue
        fr.notes.append({"level": "info", "code": "inset_match",
                         "msg": f"Inset matches the parent image magnified ×{reg['mag']:.3f} at native px "
                                f"({reg['box'][0]:.0f}, {reg['box'][1]:.0f})–({reg['box'][2]:.0f}, {reg['box'][3]:.0f}), "
                                f"correlation {reg['ncc']:.2f}."})
        if par.nm_per_px:
            inh = par.nm_per_px / reg["mag"]
            if fr.nm_per_px is None:
                fr.nm_per_px = inh
                fr.notes.append({"level": "info", "code": "scale_inherited",
                                 "msg": f"Scale from the parent's bar via the match: {fr.nm_per_px:.4g} nm/px."})
            else:
                dev = fr.nm_per_px / inh - 1
                fr.notes.append({"level": "warn" if abs(dev) > 0.03 else "info", "code": "inset_crosscheck",
                                 "msg": f"Own scale {fr.nm_per_px:.4g} nm/px vs parent's bar via the match {inh:.4g} nm/px "
                                        f"({dev * 100:+.1f}%)."})
        ib = fr.instrument_bar
        if ib is not None and ib.get("value") is None and fr.nm_per_px:
            Lnm = ib["length_px"] * fr.nm_per_px
            nice = _nice_len(Lnm)
            v, u = (nice * 1000, "pm") if nice < 1 else (nice, "nm")
            fr.notes.append({"level": "info", "code": "instrument_bar_implied",
                             "msg": f"Microscope's own bar ({'visible' if ib['visible'] else 'hidden by the clip'}, text unreadable): "
                                    f"{ib['length_px']:.1f} ± 1 px = {Lnm * (1000 if nice < 1 else 1):.3g} {u} at this scale "
                                    f"→ consistent with a {v:g} {u} bar ({(Lnm / nice - 1) * 100:+.1f}%)."})
    for fr in frames:
        if lattice and not fr.is_colour:
            try:
                fr.lattice = lattice_peaks(fr.gray, max_peaks=6)
            except Exception:  # pragma: no cover
                fr.lattice = []
            reg = getattr(fr, "registration", None)
            if reg and fr.lattice:
                # a ×m enlargement cannot hold detail finer than the parent's Nyquist limit
                lim = 2.2 * reg["mag"]
                drop = [q for q in fr.lattice if q["period_px"] < lim]
                fr.lattice = [q for q in fr.lattice if q["period_px"] >= lim][:4]
                if drop:
                    fr.notes.append({"level": "info", "code": "interp_artefacts",
                                     "msg": f"{len(drop)} periodicities finer than {lim:.1f} px ignored: below the resolution "
                                            "of the original image (interpolation artefacts of the enlargement)."})
        # d-spacing label vs measured fringe period
        if fr.lattice and fr.nm_per_px:
            for pk in fr.lattice:
                pk["d_nm"] = pk["period_px"] * fr.nm_per_px
                if "period_sd_px" in pk:
                    pk["d_sd_nm"] = pk["period_sd_px"] * fr.nm_per_px
        if fr.dlabels and fr.lattice:
            dl = fr.dlabels[0]
            strong = [p for p in fr.lattice if p["snr"] >= 0.25 * fr.lattice[0]["snr"]]
            if fr.nm_per_px:
                pk = min(strong, key=lambda p: abs(p["d_nm"] / dl["d_nm"] - 1))
                dm = pk["d_nm"]
                dev = dm / dl["d_nm"] - 1
                dl["measured_nm"] = dm
                dl["period_px"] = pk["period_px"]
                sd = pk.get("d_sd_nm")
                # scale uncertainty: ±1 px on the bar that calibrates this frame (≈1–2 %)
                rel_scale = 0.015
                tol = max(0.03, 2 * np.hypot((sd or 0) / dm, rel_scale))
                dl["deviation"] = dev
                rank = "strongest" if pk is fr.lattice[0] else "matching"
                pm = f" ± {sd:.3f}" if sd else ""
                fr.notes.append({"level": "warn" if abs(dev) > tol else "info", "code": "d_check",
                                 "msg": f"Printed d = {dl['d']:g} {dl['unit']} {dl['hkl']}; measured ({rank} fringe set, "
                                        f"{pk['period_px']:.2f} px) d = {dm:.3f}{pm} nm, {dev * 100:+.1f}% "
                                        + (f"— outside the ±{tol * 100:.0f}% uncertainty; check the label or the scale."
                                           if abs(dev) > tol else f"(agrees within ±{tol * 100:.0f}%).")})
            else:
                pk = fr.lattice[0]
                implied = dl["d_nm"] / pk["period_px"]
                dl["implied_nm_per_px"] = implied
                msg = (f"Printed d = {dl['d']:g} {dl['unit']} {dl['hkl']} with a fringe period of "
                       f"{pk['period_px']:.2f} px implies {implied:.4g} nm/px")
                if fr.unlabelled_bars:
                    b = fr.unlabelled_bars[0]
                    Lnm = b.length_px * implied
                    nice = _nice_len(Lnm)
                    msg += (f"; the unlabelled scale bar ({b.length_px:.1f} px) is then {Lnm:.3g} nm "
                            f"(≈ {nice:g} nm bar, off by {(Lnm / nice - 1) * 100:+.0f}%)")
                fr.notes.append({"level": "info", "code": "implied_scale", "msg": msg + "."})
        if fr.unlabelled_bars and fr.nm_per_px:
            b = fr.unlabelled_bars[0]
            v, u = to_unit(b.length_px * fr.nm_per_px)
            fr.notes.append({"level": "info", "code": "unlabelled_bar_length",
                             "msg": f"Unlabelled scale bar: {b.length_px:.1f} px = {v:.3g} {u}."})
        if fr.nm_per_px is None and fr.parent is None and not fr.dlabels:
            fr.notes.append({"level": "warn", "code": "no_scale_bar",
                             "msg": "No scale bar found: lengths are in native image pixels. Give --scale '<px>=<value unit>' "
                                    "for physical units."})
        if fr.unlabelled_bars and not fr.dlabels and fr.nm_per_px is None:
            fr.notes.append({"level": "info", "code": "unlabelled_bar",
                             "msg": f"Unlabelled scale bar of {fr.unlabelled_bars[0].length_px:.1f} native px."})
        # pairs of parallel same-colour lines: separations
        fr._pairs = line_pairs(fr.annotations)
        for a in fr.annotations:
            if a.kind == "arrow":
                fr.notes.append({"level": "info", "code": "arrow",
                                 "msg": f"Arrow ({a.hex}) {_fmt_len(a.length_px, fr.nm_per_px)}."})
        for pr in fr._pairs:
            fr.notes.append({"level": "info", "code": "line_pair",
                             "msg": f"Parallel {pr['color']} lines {_fmt_len(pr['sep_px'], fr.nm_per_px)} apart."})


def _fmt_len(px, nm_per_px) -> str:
    if not nm_per_px:
        return f"{px:.1f} px"
    v, u = to_unit(px * nm_per_px)
    return f"{px:.1f} px = {v:.4g} {u}"


def to_unit(nm: float):
    if abs(nm) >= 1e5:
        return nm / 1e6, "mm"
    if abs(nm) >= 1e3:
        return nm / 1e3, "µm"
    return nm, "nm"


def line_pairs(anns: List[Annotation]) -> List[dict]:
    """Separations of neighbouring near-parallel straight lines of one colour."""
    out = []
    lines = [a for a in anns if a.kind == "line" and a.length_px > 0]
    groups = {}
    for a in lines:
        key = next((k for k in groups if _cdist(k, a.color) < 40), a.color)
        groups.setdefault(key, []).append(a)
    for col, ls in groups.items():
        if len(ls) < 2:
            continue
        ang = np.array([np.radians(a.angle_deg) % np.pi for a in ls])
        for ref in ang:
            ls2 = [a for a, t in zip(ls, ang) if min(abs(t - ref), np.pi - abs(t - ref)) < np.radians(8)]
            if len(ls2) >= 2:
                break
        else:
            continue
        d = np.mean([((a.pts[1] - a.pts[0]) if (a.pts[1] - a.pts[0])[1] >= 0 else (a.pts[0] - a.pts[1])) /
                     max(a.length_px, 1e-9) for a in ls2], axis=0)
        d /= np.hypot(*d)
        n = np.array([-d[1], d[0]])
        ls2.sort(key=lambda a: a.pts.mean(axis=0) @ n)
        for a, b in zip(ls2[:-1], ls2[1:]):
            ta = sorted(a.pts @ d); tb = sorted(b.pts @ d)
            lo, hi = max(ta[0], tb[0]), min(ta[1], tb[1])
            if hi - lo < 0.2 * min(ta[1] - ta[0], tb[1] - tb[0]):
                lo, hi = 0.5 * (ta[0] + ta[1]), 0.5 * (ta[0] + ta[1])
            ts = np.linspace(lo, hi, 11)
            seps = []
            for t in ts:
                pa = _point_at(a, d, t); pb = _point_at(b, d, t)
                seps.append(abs((pb - pa) @ n))
            if np.mean(seps) < 2.5 * max(a.width_px, b.width_px, 1.0):
                continue
            if np.mean(seps) > 1.2 * min(a.length_px, b.length_px) or a.dashed or b.dashed:
                continue          # far-apart or dashed strokes (box edges) are not a measurement pair
            out.append({"color": "#%02x%02x%02x" % tuple(int(v) for v in a.color), "sep_px": float(np.mean(seps)),
                        "sep_sd_px": float(np.std(seps)), "lines": (a, b)})
    return out


def _point_at(a: Annotation, d, t):
    p0, p1 = a.pts[0], a.pts[1]
    t0, t1 = p0 @ d, p1 @ d
    if abs(t1 - t0) < 1e-9:
        return p0
    return p0 + (t - t0) / (t1 - t0) * (p1 - p0)


# ───────────────────────── series from titled frames ─────────────────────────
def colour_name(rgb) -> str:
    r, g, b = [int(v) for v in rgb]
    h, s, v = cv2.cvtColor(np.uint8([[[r, g, b]]]), cv2.COLOR_RGB2HSV)[0, 0]
    if s < 50:
        return "white" if v > 200 else "black" if v < 60 else "grey"
    h = int(h) * 2
    for lim, name in ((15, "red"), (40, "orange"), (70, "yellow"), (160, "green"), (200, "cyan"),
                      (260, "blue"), (300, "purple"), (340, "magenta"), (361, "red")):
        if h < lim:
            return name
    return "red"


def frame_series(frames: List[Frame], order: List[int]):
    """Per-frame measurements vs numeric frame titles → list of dicts (name, x, y, err, unit)."""
    vals = [(i, parse_value(frames[i].title)) for i in order]
    # OCR'd titles: "Omin" → 0 min, "10on" → 10 <majority unit>
    if all(f.source == "raster" for f in frames):
        good = [v for _, v in vals if v is not None]
        maj = max({u for _, u in good}, key=lambda u: sum(1 for _, x in good if x == u)) if good else ""
        fixed = []
        for i, v in vals:
            if v is not None and v[1] != maj and len(v[1]) <= 4 and maj:
                frames[i].notes.append({"level": "info", "code": "title_fixed",
                                        "msg": f"Title OCR '{frames[i].title}' read as '{v[0]:g} {maj}'."})
                v = (v[0], maj)
            if v is None:
                t = re.sub(r"^[Oo](?=[\s\dA-Za-z])", "0", frames[i].title.strip())
                m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*(\S{0,4})\s*$", t)
                if m:
                    v = (float(m.group(1).replace(",", ".")), maj)
                    frames[i].notes.append({"level": "info", "code": "title_fixed",
                                            "msg": f"Title OCR '{frames[i].title}' read as '{v[0]:g} {maj}'."})
            fixed.append((i, v))
        vals = fixed
    vals = [(i, v) for i, v in vals if v is not None]
    if len(vals) < 3:
        return None
    units = {v[1] for _, v in vals}
    if len(units) > 1:
        return None
    xunit = units.pop()
    nms = [frames[i].nm_per_px for i, _ in vals]
    phys = all(nms)
    yunit = "px"
    if phys:
        _, yunit = to_unit(np.median([n for n in nms]) * np.median([f.rgb.shape[1] for f in frames]) * 0.2)
    conv = {"nm": 1.0, "µm": 1e-3, "mm": 1e-6}

    def y_of(px, i):
        return px * frames[i].nm_per_px * conv[yunit] if phys else px

    series = {}
    for i, (x, _) in vals:
        fr = frames[i]
        arrows = {}
        for a in sorted([a for a in fr.annotations if a.kind == "arrow"], key=lambda a: a.pts[:, 1].mean()):
            arrows.setdefault(colour_name(a.color), []).append(y_of(a.length_px, i))
        for c, L in arrows.items():
            s = series.setdefault(("arrow", c), {"x": [], "y": [], "sd": [], "n": [], "each": []})
            s["x"].append(x); s["y"].append(float(np.mean(L))); s["sd"].append(float(np.std(L)) if len(L) > 1 else np.nan)
            s["n"].append(len(L)); s["each"].append(L)
        pairs = {}
        for pr in getattr(fr, "_pairs", []):
            c = colour_name(tuple(int(pr["color"][k:k + 2], 16) for k in (1, 3, 5)))
            pairs.setdefault(c, []).append(y_of(pr["sep_px"], i))
        for c, L in pairs.items():
            s = series.setdefault(("separation", c), {"x": [], "y": [], "sd": [], "n": []})
            s["x"].append(x); s["y"].append(float(np.mean(L))); s["sd"].append(np.nan); s["n"].append(len(L))
    out = []
    for (what, c), s in series.items():
        if len(s["x"]) < 2:
            continue
        # the same number of arrows on every frame: follow each arrow (top → bottom)
        if what == "arrow" and len(set(s["n"])) == 1 and s["n"][0] > 1:
            k = s["n"][0]
            for j in range(k):
                pos = "top" if j == 0 else "bottom" if j == k - 1 else ("middle" if k == 3 else f"#{j + 1}")
                out.append({"name": f"{c} arrow {j + 1} ({pos})", "x": np.array(s["x"], float),
                            "y": np.array([e[j] for e in s["each"]], float), "sd": np.full(len(s["x"]), np.nan),
                            "n": [1] * len(s["x"])})
            continue
        name = f"{c} arrow length" if what == "arrow" else f"{c} line separation"
        out.append({"name": name, "x": np.array(s["x"], float), "y": np.array(s["y"], float),
                    "sd": np.array(s["sd"], float), "n": s["n"]})
    if not out:
        return None
    xq = "Time" if xunit in TIME_UNITS else ("Temperature" if xunit in ("°C", "K") else "Value")
    return {"series": out, "xlabel": f"{xq} ({xunit})" if xunit else xq,
            "ylabel": f"Length ({yunit})", "yunit": yunit, "xunit": xunit}
