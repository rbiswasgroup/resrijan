"""OCR helpers for tick labels, colour-bar labels and scale-bar text.

The approach is geometric first, OCR second: characters are found as connected
components, grouped into labels, and each label is read on its own (Tesseract,
single-line mode, character whitelist). Minus signs and superscript exponents are
detected from geometry, because OCR engines routinely drop them.
"""
from __future__ import annotations

import math
import re
import shutil
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

try:
    import pytesseract
    _HAS_TESS = shutil.which("tesseract") is not None
except Exception:  # pragma: no cover
    pytesseract = None
    _HAS_TESS = False

SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
MINUS_CHARS = "−–—‒﹣－"


def tesseract_available() -> bool:
    return _HAS_TESS


def parse_number(text: str) -> Optional[float]:
    """Parse a tick-label string into a float. Returns None if it is not a number."""
    if text is None:
        return None
    s = text.strip()
    if not s:
        return None
    for ch in MINUS_CHARS:
        s = s.replace(ch, "-")
    s = s.replace(" ", "").replace(" ", "")
    s = s.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
    s = s.replace("×", "x").replace("*", "x").replace("·", "x")
    # superscript unicode
    if any(c in s for c in "⁰¹²³⁴⁵⁶⁷⁸⁹⁻"):
        m = re.match(r"^(.*?)([⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)$", s)
        if m:
            base, exp = m.group(1), m.group(2).translate(SUPERSCRIPTS)
            s = f"{base}^{exp}"
    # thousands separators vs decimal comma
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    s = s.strip(".")
    m = re.fullmatch(r"([-+]?\d*\.?\d+)x10\^?([-+]?\d+)", s)
    if m:
        return float(m.group(1)) * 10.0 ** int(m.group(2))
    m = re.fullmatch(r"10\^([-+]?\d+(\.\d+)?)", s)
    if m:
        return 10.0 ** float(m.group(1))
    m = re.fullmatch(r"([-+]?\d*\.?\d+)[eE]([-+]?\d+)", s)
    if m:
        return float(m.group(1)) * 10.0 ** int(m.group(2))
    try:
        v = float(s)
        if math.isfinite(v):
            return v
    except ValueError:
        pass
    return None


@dataclass
class Label:
    bbox: Tuple[int, int, int, int]   # x0, y0, x1, y1 in the coordinates of the input image
    text: str
    value: Optional[float]
    conf: float
    exponent: Optional[str] = None

    @property
    def cx(self):
        return 0.5 * (self.bbox[0] + self.bbox[2])

    @property
    def cy(self):
        return 0.5 * (self.bbox[1] + self.bbox[3])


def ink_mask(gray: np.ndarray, thresh: Optional[int] = None) -> np.ndarray:
    """Dark text on a light background; threshold half-way between paper and ink."""
    if thresh is None:
        bg = float(np.median(gray))
        dark = float(np.percentile(gray, 0.5))
        if bg - dark < 40:
            return np.zeros_like(gray, dtype=bool)
        thresh = 0.5 * (bg + dark)
    return gray < thresh


def components(mask: np.ndarray, min_area: int = 2):
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    comps = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a >= min_area:
            comps.append((x, y, x + w, y + h, a))
    return comps


def group_components(comps, gap_x: float, gap_y: float):
    """Group character components into words/labels (single-linkage on bbox gaps)."""
    n = len(comps)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        a = comps[i]
        for j in range(i + 1, n):
            b = comps[j]
            dx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
            dy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
            if dx <= gap_x and dy <= gap_y:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(comps[i])
    out = []
    for g in groups.values():
        x0 = min(c[0] for c in g); y0 = min(c[1] for c in g)
        x1 = max(c[2] for c in g); y1 = max(c[3] for c in g)
        out.append(((x0, y0, x1, y1), g))
    return out


def _tess(img: np.ndarray, whitelist: Optional[str], psm: int = 7) -> Tuple[str, float]:
    if not _HAS_TESS:
        return "", 0.0
    cfg = f"--psm {psm} --oem 1"
    if whitelist:
        cfg += f" -c tessedit_char_whitelist={whitelist}"
    try:
        d = pytesseract.image_to_data(img, config=cfg, output_type=pytesseract.Output.DICT)
    except Exception:
        return "", 0.0
    words, confs = [], []
    for t, c in zip(d["text"], d["conf"]):
        t = t.strip()
        if t:
            words.append(t)
            try:
                confs.append(float(c))
            except ValueError:
                pass
    return "".join(words), (float(np.mean(confs)) if confs else 0.0)


def _prep(gray_crop: np.ndarray, target_h: int = 48) -> np.ndarray:
    h = gray_crop.shape[0]
    f = max(1.0, target_h / max(h, 1))
    g = cv2.resize(gray_crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    g = cv2.copyMakeBorder(g, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=255)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return b


NUM_WHITELIST = "0123456789.-,"


def read_label(gray: np.ndarray, group, numeric: bool = True) -> Label:
    """Read one label (bbox + character components) from a grayscale image."""
    (x0, y0, x1, y1), comps = group
    y1 - y0
    # --- geometric minus sign: leading flat component in the vertical middle
    comps_sorted = sorted(comps, key=lambda c: c[0])
    minus = False
    body = comps_sorted
    if len(comps_sorted) >= 2:
        c = comps_sorted[0]
        cw, ch = c[2] - c[0], c[3] - c[1]
        ccy = 0.5 * (c[1] + c[3])
        rest = comps_sorted[1:]
        ry0 = min(r[1] for r in rest); ry1 = max(r[3] for r in rest)
        if cw >= 1.5 * ch and ch <= 0.3 * (ry1 - ry0) and ry0 + 0.2 * (ry1 - ry0) < ccy < ry1 - 0.15 * (ry1 - ry0):
            minus = True
            body = rest
    # --- superscript split: components whose bottom sits well above the baseline
    bx0 = min(c[0] for c in body); min(c[1] for c in body)
    bx1 = max(c[2] for c in body); by1 = max(c[3] for c in body)
    baseline = by1
    tall = max(c[3] - c[1] for c in body)
    sup = [c for c in body if c[3] < baseline - 0.35 * tall and c[0] > bx0 + 0.3 * (bx1 - bx0)]
    base = [c for c in body if c not in sup]
    exponent = None
    pad = 2
    if sup and base:
        bb = (min(c[0] for c in base), min(c[1] for c in base), max(c[2] for c in base), max(c[3] for c in base))
        sb = (min(c[0] for c in sup), min(c[1] for c in sup), max(c[2] for c in sup), max(c[3] for c in sup))
        # minus inside the exponent?
        sup_sorted = sorted(sup, key=lambda c: c[0])
        sminus = False
        if len(sup_sorted) >= 2:
            c = sup_sorted[0]
            if (c[2] - c[0]) >= 1.3 * (c[3] - c[1]):
                sminus = True
                sb = (min(cc[0] for cc in sup_sorted[1:]), min(cc[1] for cc in sup_sorted[1:]),
                      max(cc[2] for cc in sup_sorted[1:]), max(cc[3] for cc in sup_sorted[1:]))
        btxt, bconf = _tess(_prep(gray[max(0, bb[1]-pad):bb[3]+pad, max(0, bb[0]-pad):bb[2]+pad]), "0123456789.x×")
        stxt, sconf = _tess(_prep(gray[max(0, sb[1]-pad):sb[3]+pad, max(0, sb[0]-pad):sb[2]+pad]), "0123456789-")
        stxt = stxt.replace("-", "")
        exponent = ("-" if sminus else "") + stxt
        txt = f"{btxt}^{exponent}"
        val = None
        try:
            e = int(exponent)
            bt = btxt.replace("×", "x")
            if bt == "10":
                val = 10.0 ** e
            elif bt.endswith("x10"):
                val = float(bt[:-3]) * 10.0 ** e
            elif bt.endswith("10") and len(bt) > 2:   # "1x10" with x lost
                val = float(bt[:-2]) * 10.0 ** e
        except Exception:
            val = None
        if minus and val is not None:
            val = -val
            txt = "-" + txt
        return Label((x0, y0, x1, y1), txt, val, min(bconf, sconf), exponent)
    cx0 = min(c[0] for c in body); cy0 = min(c[1] for c in body)
    cx1 = max(c[2] for c in body); cy1 = max(c[3] for c in body)
    crop = gray[max(0, cy0 - pad):cy1 + pad, max(0, cx0 - pad):cx1 + pad]
    img = _prep(crop)
    txt, conf = _tess(img, NUM_WHITELIST if numeric else None, 7)
    if numeric and parse_number(txt) is None:
        # short labels ("0", "4") often defeat line mode: retry as word / raw line / char
        for psm in (8, 13, 10):
            t2, c2 = _tess(img, NUM_WHITELIST, psm)
            if parse_number(t2) is not None:
                txt, conf = t2, c2
                break
    if minus and not txt.startswith("-"):
        txt = "-" + txt
    val = parse_number(txt) if numeric else None
    return Label((x0, y0, x1, y1), txt, val, conf)


def read_text(gray_crop: np.ndarray, psm: int = 7) -> Tuple[str, float]:
    """Free-text OCR (for axis titles, scale-bar text)."""
    return _tess(_prep(gray_crop, 40), None, psm)


def find_labels(gray: np.ndarray, region, numeric: bool = True, char_h_range=(4, 200),
                exclude_long: int = 0) -> List[Label]:
    """Find and read all labels inside ``region`` = (x0, y0, x1, y1) of ``gray``."""
    x0, y0, x1, y1 = [int(v) for v in region]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(gray.shape[1], x1), min(gray.shape[0], y1)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return []
    sub = gray[y0:y1, x0:x1]
    mask = ink_mask(sub)
    comps = components(mask, 2)
    comps = [c for c in comps if (c[3] - c[1]) <= char_h_range[1] and (c[2] - c[0]) <= 6 * char_h_range[1]]
    if exclude_long:
        comps = [c for c in comps if max(c[2] - c[0], c[3] - c[1]) < exclude_long or min(c[2]-c[0], c[3]-c[1]) > 3]
    if not comps:
        return []
    hs = np.array([c[3] - c[1] for c in comps if (c[3] - c[1]) >= char_h_range[0]])
    if len(hs):
        big = hs[hs >= 0.5 * np.percentile(hs, 90)]
        ch = float(np.median(big))
    else:
        ch = 8.0
    groups = group_components(comps, gap_x=0.55 * ch, gap_y=0.25 * ch)
    labels = []
    for (bx0, by0, bx1, by1), g in groups:
        if (by1 - by0) < char_h_range[0]:
            continue
        lab = read_label(sub, ((bx0, by0, bx1, by1), g), numeric)
        lab.bbox = (lab.bbox[0] + x0, lab.bbox[1] + y0, lab.bbox[2] + x0, lab.bbox[3] + y0)
        labels.append(lab)
    return labels
