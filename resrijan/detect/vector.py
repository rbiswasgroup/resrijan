"""Exact extraction from vector figures (PDF, and EPS/PS converted to PDF).

Paths and glyphs are read straight from the page content stream with PyMuPDF, so
tick positions and data vertices carry no pixel quantisation at all. All geometry is
returned in the pixel coordinates of the page rendering (points x render scale), so
vector and raster results can be overlaid and compared directly.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .axes import AxesBox
from . import ocr


@dataclass
class VPath:
    polys: List[np.ndarray]           # list of (N, 2) arrays in pixel units
    stroke: Optional[Tuple[float, float, float]]
    fill: Optional[Tuple[float, float, float]]
    width: float                      # stroke width in pixels
    dashes: str
    closed: bool
    bbox: Tuple[float, float, float, float]
    seqno: int = 0
    clip: Optional[Tuple[float, float, float, float]] = None   # active clip rectangle (pixels), if any

    @property
    def vis_bbox(self):
        """Bounding box of the visible part (the path clipped to its clip rectangle)."""
        if self.clip is None:
            return self.bbox
        b, c = self.bbox, self.clip
        v = (max(b[0], c[0]), max(b[1], c[1]), min(b[2], c[2]), min(b[3], c[3]))
        return v if v[0] <= v[2] and v[1] <= v[3] else self.bbox

    @property
    def w(self):
        return self.bbox[2] - self.bbox[0]

    @property
    def h(self):
        return self.bbox[3] - self.bbox[1]

    def style_key(self):
        def rc(c):
            return None if c is None else tuple(round(v, 2) for v in c)
        return (rc(self.stroke), round(self.width, 1) if self.stroke else None, self.dashes if self.stroke else None,
                rc(self.fill))


def _bezier(p0, p1, p2, p3, n=12):
    t = np.linspace(0, 1, n)[:, None]
    return ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3


def _with_clips(pdf_page):
    """Drawings with the clip rectangle in force for each (intersection of the enclosing
    clips; ``extended`` drawings nest clips and groups by ``level``)."""
    try:
        dr = pdf_page.get_drawings(extended=True)
    except TypeError:  # pragma: no cover  (old PyMuPDF)
        for d in pdf_page.get_drawings():
            yield d, None
        return
    stack = []                      # (level, rect or None)
    for d in dr:
        lvl = d.get("level", 0)
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        typ = d.get("type")
        if typ in ("clip", "group"):
            r = d.get("scissor") if typ == "clip" else None
            stack.append((lvl, tuple(r) if r is not None else None))
            continue
        rect = None
        for _, r in stack:
            if r is None:
                continue
            rect = r if rect is None else (max(rect[0], r[0]), max(rect[1], r[1]), min(rect[2], r[2]), min(rect[3], r[3]))
        yield d, rect


def get_paths(pdf_page, scale: float) -> List[VPath]:
    out = []
    for d, clip in _with_clips(pdf_page):
        polys, cur = [], []
        last = None
        for it in d["items"]:
            op = it[0]
            if op == "l":
                a, b = np.array([it[1].x, it[1].y]), np.array([it[2].x, it[2].y])
                if last is None or np.hypot(*(a - last)) > 1e-3:
                    if len(cur) > 1:
                        polys.append(np.array(cur))
                    cur = [a]
                cur.append(b)
                last = b
            elif op == "c":
                p = [np.array([q.x, q.y]) for q in it[1:5]]
                if last is None or np.hypot(*(p[0] - last)) > 1e-3:
                    if len(cur) > 1:
                        polys.append(np.array(cur))
                    cur = [p[0]]
                cur.extend(_bezier(*p)[1:])
                last = p[3]
            elif op == "re":
                r = it[1]
                if len(cur) > 1:
                    polys.append(np.array(cur))
                polys.append(np.array([[r.x0, r.y0], [r.x1, r.y0], [r.x1, r.y1], [r.x0, r.y1], [r.x0, r.y0]]))
                cur, last = [], None
            elif op == "qu":
                q = it[1]
                if len(cur) > 1:
                    polys.append(np.array(cur))
                polys.append(np.array([[q.ul.x, q.ul.y], [q.ur.x, q.ur.y], [q.lr.x, q.lr.y], [q.ll.x, q.ll.y],
                                       [q.ul.x, q.ul.y]]))
                cur, last = [], None
        if len(cur) > 1:
            polys.append(np.array(cur))
        if not polys:
            continue
        polys = [p * scale for p in polys]
        allp = np.vstack(polys)
        typ = d.get("type", "s")
        stroke = d.get("color") if "s" in typ else None
        fill = d.get("fill") if "f" in typ else None
        out.append(VPath(polys=polys, stroke=tuple(stroke) if stroke else None,
                         fill=tuple(fill) if fill else None, width=float(d.get("width") or 0) * scale,
                         dashes=str(d.get("dashes") or ""), closed=bool(d.get("closePath")),
                         bbox=(allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max()),
                         seqno=int(d.get("seqno", 0)),
                         clip=tuple(v * scale for v in clip) if clip is not None else None))
    return out


@dataclass
class VChar:
    c: str
    bbox: Tuple[float, float, float, float]
    size: float
    origin: Tuple[float, float]
    dir: Tuple[float, float] = (1.0, 0.0)   # text direction (rotated titles are not tick labels)
    word: int = -1                           # whitespace-separated word id within the page
    color: Tuple[int, int, int] = (0, 0, 0)
    bold: bool = False


def _is_bold(span) -> bool:
    font = span.get("font", "")
    return bool(span.get("flags", 0) & 16) or any(k in font for k in ("Bold", "Black", "Heavy", "Semibold", "Demi"))


def _same_color(a, b, tol=60.0) -> bool:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 < tol


def get_chars(pdf_page, scale: float) -> List[VChar]:
    chars = []
    raw = pdf_page.get_text("rawdict")
    word = 0
    for b in raw.get("blocks", []):
        for ln in b.get("lines", []):
            d = tuple(round(v, 3) for v in ln.get("dir", (1.0, 0.0)))
            word += 1
            for sp in ln.get("spans", []):
                for ch in sp.get("chars", []):
                    c = ch["c"]
                    if not c.strip():
                        word += 1          # whitespace ends a word ("1h   2h" are two labels)
                        continue
                    bb = tuple(v * scale for v in ch["bbox"])
                    col = sp.get("color", 0)
                    chars.append(VChar(c, bb, sp["size"] * scale, (ch["origin"][0] * scale, ch["origin"][1] * scale),
                                       d, word, ((col >> 16) & 255, (col >> 8) & 255, col & 255), _is_bold(sp)))
    return chars


def _h(c: VChar) -> float:
    return c.bbox[3] - c.bbox[1]


def _sz(c: VChar) -> float:
    """Font size; falls back to the glyph box when the reported size is degenerate
    (Ghostscript-converted EPS/PS often reports a scaled-down font matrix)."""
    return c.size if c.size > 0.5 * _h(c) else 0.75 * _h(c)


def _is_sup(small: VChar, big: VChar) -> bool:
    """``small`` is a superscript of ``big`` (font size or glyph box smaller, baseline raised)."""
    raised = big.origin[1] - small.origin[1]
    if _sz(small) < 0.85 * _sz(big):
        return 0 < raised < 0.75 * _sz(big)
    return _h(small) < 0.85 * _h(big) and 0.2 * _h(big) < raised < 0.8 * _h(big)


def _is_sub(small: VChar, big: VChar) -> bool:
    """``small`` is a subscript of ``big`` (smaller, baseline lowered)."""
    low = small.origin[1] - big.origin[1]
    return _sz(small) < 0.85 * _sz(big) and 0.05 * _sz(big) < low < 0.6 * _sz(big)


def group_chars(chars: List[VChar]):
    """Cluster glyphs into labels; superscripts become '^' exponents."""
    n = len(chars)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        a = chars[i]
        for j in range(i + 1, n):
            b = chars[j]
            s = max(_sz(a), _sz(b))
            dx = max(0, max(a.bbox[0], b.bbox[0]) - min(a.bbox[2], b.bbox[2]))
            dbase = abs(a.origin[1] - b.origin[1])
            same_line = dbase < 0.25 * s
            if a.dir != b.dir or not _same_color(a.color, b.color):
                continue           # adjacent labels in different colours ("Mg" next to "Ca") stay apart
            if a.dir[0] < 0.9:
                # rotated text (axis titles): only glyphs of the same word belong together
                if a.word == b.word:
                    parent[find(i)] = find(j)
                continue
            sup = _is_sup(a, b) or _is_sup(b, a) or _is_sub(a, b) or _is_sub(b, a)
            same_word = a.word == b.word or a.word < 0
            if dx < 0.35 * s and ((same_line and same_word) or sup):
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(chars[i])
    labels = []
    for g in groups.values():
        g.sort(key=lambda c: c.bbox[0])
        big = max(g, key=lambda c: (_sz(c), _h(c)))
        main, sup = "", ""
        prev = None
        for c in g:
            if c is not big and _is_sup(c, big):
                sup += c.c
            else:
                if prev is not None and c.bbox[0] - prev.bbox[2] > 0.22 * _sz(big):
                    main += " "
                main += c.c
                prev = c
        text = main + (f"^{sup}" if sup else "")
        # display form with sub/superscripts as mathtext (annotations in the replot)
        disp, prev, run, kind_run = "", None, "", None
        base_y = big.origin[1]
        for c in g:
            k = "main"
            if c is not big and _sz(c) < 0.85 * _sz(big):
                k = "sup" if big.origin[1] - c.origin[1] > 0.1 * _sz(big) else "sub"
            if k != kind_run and run:
                disp += run if kind_run == "main" else ("$^{\\mathregular{%s}}$" if kind_run == "sup" else "$_{\\mathregular{%s}}$") % run.replace("−", "-")
                run = ""
            if k == "main" and prev is not None and c.bbox[0] - prev.bbox[2] > 0.22 * _sz(big):
                run += " "
            run += c.c
            kind_run, prev = k, c
        if run:
            disp += run if kind_run == "main" else ("$^{\\mathregular{%s}}$" if kind_run == "sup" else "$_{\\mathregular{%s}}$") % run.replace("−", "-")
        _ = base_y
        val = None
        if sup:
            m = main.replace("×", "x").replace("−", "-")
            try:
                e = float(sup.replace("−", "-"))
                if m.endswith("10"):
                    pre = m[:-2].rstrip("x")
                    val = (float(pre) if pre not in ("", "-") else (-1.0 if pre == "-" else 1.0)) * 10 ** e
            except ValueError:
                val = None
        else:
            val = ocr.parse_number(main)
        bb = (min(c.bbox[0] for c in g), min(c.bbox[1] for c in g), max(c.bbox[2] for c in g),
              max(c.bbox[3] for c in g))
        lab = ocr.Label(bb, text, val, 100.0, sup or None)
        lab.rotated = g[0].dir[0] < 0.9
        lab.color = g[0].color
        lab.bold = sum(c.bold for c in g) > 0.5 * len(g)
        lab.display = disp.replace("$$", "")
        lab.size = _sz(big)
        labels.append(lab)
    return labels


def minus_bars(paths: List[VPath]) -> List[VPath]:
    """Small filled bars that typeset a minus sign (matplotlib mathtext, TeX, Origin draw
    '−' as a rule rather than a glyph)."""
    out = []
    for p in paths:
        if p.fill is None or len(p.polys) != 1 or len(p.polys[0]) > 6:
            continue
        w, h = p.w, p.h
        if 0 < min(w, h) and max(w, h) / max(min(w, h), 1e-6) >= 3.5:
            out.append(p)
    return out


def attach_minus(labels, bars: List[VPath]):
    """Numeric labels with a minus bar just before them become negative."""
    used = set()
    for lab in labels:
        if lab.value is None or getattr(lab, "rotated", False) or lab.text.lstrip().startswith(("-", "−")):
            continue
        x0, y0, x1, y1 = lab.bbox
        h = y1 - y0
        for k, b in enumerate(bars):
            if k in used or b.w <= b.h:
                continue
            bx0, by0, bx1, by1 = b.bbox
            cy = 0.5 * (by0 + by1)
            if (x0 - 0.75 * h <= bx1 <= x0 + 0.1 * h and y0 + 0.25 * h <= cy <= y1 - 0.15 * h
                    and 0.2 * h <= b.w <= 1.0 * h):
                lab.value = -lab.value
                lab.text = "−" + lab.text
                used.add(k)
                break
    return used


def _straight(p: VPath, orient: str, tol=0.6):
    if len(p.polys) != 1 or len(p.polys[0]) < 2:
        return False
    pts = p.polys[0]
    if orient == "h":
        return np.ptp(pts[:, 1]) <= tol and np.ptp(pts[:, 0]) > 0
    return np.ptp(pts[:, 0]) <= tol and np.ptp(pts[:, 1]) > 0


def _is_dark(c):
    return c is not None and max(c) < 0.45 and (max(c) - min(c)) < 0.2


def find_axes(paths: List[VPath], page_w: float, page_h: float, min_len_px: float) -> List[AxesBox]:
    hs, vs = [], []
    for p in paths:
        if p.stroke is not None and _is_dark(p.stroke):
            for poly in p.polys:
                if len(poly) < 2:
                    continue
                # split rectangles/polylines into straight edges
                for a, b in zip(poly[:-1], poly[1:]):
                    if abs(a[1] - b[1]) < 0.6 and abs(a[0] - b[0]) >= min_len_px:
                        hs.append((min(a[0], b[0]), a[1], max(a[0], b[0]), p.width))
                    elif abs(a[0] - b[0]) < 0.6 and abs(a[1] - b[1]) >= min_len_px:
                        vs.append((a[0], min(a[1], b[1]), max(a[1], b[1]), p.width))
        elif p.fill is not None and _is_dark(p.fill) and p.stroke is None:
            # axes drawn as thin filled rectangles
            if p.h < 3 and p.w >= min_len_px:
                hs.append((p.bbox[0], 0.5 * (p.bbox[1] + p.bbox[3]), p.bbox[2], p.h))
            elif p.w < 3 and p.h >= min_len_px:
                vs.append((0.5 * (p.bbox[0] + p.bbox[2]), p.bbox[1], p.bbox[3], p.w))
    boxes = []
    for (hx0, hy, hx1, hw) in hs:
        for (vx, vy0, vy1, vw) in vs:
            tol = max(2.0, 2 * max(hw, vw))
            if abs(vx - hx0) <= tol and abs(vy1 - hy) <= tol and vy0 < hy - 10:
                top = any(abs(y - vy0) <= tol and abs(x0 - hx0) <= tol and abs(x1 - hx1) <= tol for x0, y, x1, _ in hs)
                right = any(abs(x - hx1) <= tol and abs(y1 - hy) <= tol for x, y0, y1, _ in vs)
                boxes.append(AxesBox(x0=vx, y0=vy0, x1=hx1, y1=hy, xaxis_y=hy, yaxis_x=vx,
                                     line_w=max(hw, vw, 0.5), framed=top and right))
    boxes.sort(key=lambda b: -b.w * b.h)
    keep = []
    for b in boxes:
        if any(abs(b.x0 - k.x0) < 3 and abs(b.y1 - k.y1) < 3 for k in keep):
            continue
        parent = next((k for k in keep if b.x0 >= k.x0 - 1 and b.x1 <= k.x1 + 1 and b.y0 >= k.y0 - 1 and b.y1 <= k.y1 + 1), None)
        if parent is not None:
            # a framed box well inside a plot, big enough to be an inset (legend frames are smaller)
            frac = b.w * b.h / (parent.w * parent.h)
            if not (b.framed and 0.06 <= frac <= 0.6 and b.x0 > parent.x0 + 3 and b.y1 < parent.y1 - 3):
                continue
            b.inset_of = parent
            parent.insets = getattr(parent, "insets", []) + [b]
        keep.append(b)
    return keep


def find_xonly_axes(paths: List[VPath], boxes: List[AxesBox], labels, min_len_px: float) -> List[AxesBox]:
    """Bottom axis lines without a y axis (stacked NMR/IR/XRD spectra): a long dark
    horizontal line with numbered ticks below it and data drawn above it."""
    hs = []
    for p in paths:
        col = p.stroke if p.stroke is not None else p.fill
        if col is None or not _is_dark(col):
            continue
        if p.stroke is not None:
            for poly in p.polys:
                for a, b in zip(poly[:-1], poly[1:]):
                    if abs(a[1] - b[1]) < 0.6 and abs(a[0] - b[0]) >= min_len_px:
                        hs.append((min(a[0], b[0]), a[1], max(a[0], b[0]), p.width))
        elif p.h < max(3.0, 0.02 * p.w) and p.w >= min_len_px:
            hs.append((p.bbox[0], 0.5 * (p.bbox[1] + p.bbox[3]), p.bbox[2], p.h))
    out = []
    for x0, y, x1, lw in sorted(hs, key=lambda t: -(t[2] - t[0])):
        if any(b.x0 - 3 <= x0 and x1 <= b.x1 + 3 and b.y0 - 3 <= y <= b.y1 + 3 for b in boxes + out):
            continue
        w = x1 - x0
        nums = [l for l in labels if l.value is not None and not getattr(l, "rotated", False)
                and x0 - 0.05 * w <= l.cx <= x1 + 0.05 * w and y < l.bbox[1] < y + 0.25 * w]
        if len(nums) < 3:
            continue
        # data above the line, within its x range
        above = [p for p in paths if p.bbox[3] < y - 1 and p.bbox[0] >= x0 - 0.02 * w and p.bbox[2] <= x1 + 0.02 * w
                 and (p.stroke is not None or p.fill is not None) and max(p.w, p.h) > 0.02 * w]
        if not above:
            continue
        top = min(p.vis_bbox[1] for p in above)        # a trace clipped at the top ends where it is cut
        if y - top < 0.1 * w:
            continue
        # labels just above the highest trace (sample names …) belong to the panel
        txt = [l for l in labels if l.value is None and not getattr(l, "rotated", False)
               and x0 <= l.cx <= x1 and top - 0.15 * (y - top) <= l.bbox[1] < top]
        if txt:
            top = min(top, min(l.bbox[1] for l in txt))
        b = AxesBox(x0=x0, y0=top - 0.02 * (y - top), x1=x1, y1=y, xaxis_y=y, yaxis_x=x0 - 1e6, line_w=max(lw, 0.5))
        b.no_yaxis = True
        out.append(b)
    return out


def find_ticks(paths: List[VPath], box: AxesBox):
    """Short dark straight strokes perpendicular to and touching each axis."""
    maxlen = max(4.0, 0.06 * max(box.w, box.h))
    xt, yt = [], []
    for p in paths:
        if p.stroke is None or not _is_dark(p.stroke):
            continue
        for poly in p.polys:
            for a, b in zip(poly[:-1], poly[1:]):
                dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
                tol = box.line_w + 1.5
                if dx < 0.3 and 0.5 < dy <= maxlen:                 # vertical tick
                    x = a[0]
                    if box.x0 - tol <= x <= box.x1 + tol and (min(a[1], b[1]) - tol <= box.xaxis_y <= max(a[1], b[1]) + tol):
                        xt.append((x, dy, max(a[1], b[1]) > box.xaxis_y + 0.5))
                elif dy < 0.3 and 0.5 < dx <= maxlen:               # horizontal tick
                    y = a[1]
                    if box.y0 - tol <= y <= box.y1 + tol and (min(a[0], b[0]) - tol <= box.yaxis_x <= max(a[0], b[0]) + tol):
                        yt.append((y, dx, min(a[0], b[0]) < box.yaxis_x - 0.5))

    def split(t, outside_sign):
        if not t:
            return [], [], 0.0
        arr = np.array([(v[0], v[1]) for v in t])
        # deduplicate (same tick drawn twice, e.g. frame top/bottom)
        pos = np.unique(np.round(arr[:, 0], 3))
        L = np.array([arr[np.abs(arr[:, 0] - q) < 1e-3, 1].max() for q in pos])
        Lmax = L.max()
        major = pos[L >= 0.75 * Lmax]
        minor = pos[L < 0.75 * Lmax]
        out = max([v[1] for v in t if v[2]], default=0.0)
        return list(major), list(minor), out

    box.xticks, box.xticks_minor, box.xtick_out = split(xt, +1)
    box.yticks, box.yticks_minor, box.ytick_out = split(yt, -1)
    return box


def label_axes(box: AxesBox, labels, all_boxes: List[AxesBox]):
    reach_y = max(25, 0.2 * box.h)
    reach_x = max(40, 0.4 * box.w)
    labels = [l for l in labels if not getattr(l, "rotated", False)]
    mx = 0.03 if getattr(box, "no_yaxis", False) else 0.12
    xs = [l for l in labels if box.x0 - mx * box.w <= l.cx <= box.x1 + mx * box.w
          and box.xaxis_y < l.bbox[1] <= box.xaxis_y + reach_y and l.value is not None]
    ys = [l for l in labels if box.yaxis_x - reach_x <= l.bbox[2] <= box.yaxis_x and
          box.y0 - 0.06 * box.h <= l.cy <= box.y1 + 0.06 * box.h and l.value is not None]
    # nearest band only
    if xs:
        top = min(l.bbox[1] for l in xs)
        hgt = np.median([l.bbox[3] - l.bbox[1] for l in xs])
        xs = [l for l in xs if l.bbox[1] - top <= 0.9 * hgt]
    if ys:
        right = max(l.bbox[2] for l in ys)
        wid = np.median([l.bbox[3] - l.bbox[1] for l in ys])
        ys = [l for l in ys if right - l.bbox[2] <= 1.2 * wid + 2]
    elif not getattr(box, "no_yaxis", False):
        # y labels on the right-hand side (paired panels, twin layouts)
        rs = [l for l in labels if box.x1 <= l.bbox[0] <= box.x1 + reach_x and
              box.y0 - 0.06 * box.h <= l.cy <= box.y1 + 0.06 * box.h and l.value is not None
              and not any(o is not box and o.x0 - 2 <= l.cx <= o.x1 + 2 and o.y0 <= l.cy <= o.y1 for o in all_boxes)]
        if len(rs) >= 2:
            left = min(l.bbox[0] for l in rs)
            wid = np.median([l.bbox[3] - l.bbox[1] for l in rs])
            ys = [l for l in rs if l.bbox[0] - left <= 1.2 * wid + 2]
            box.y_right = True
    box.xlabels, box.ylabels = xs, ys
    if xs:
        row_top = min(l.bbox[1] for l in xs)
        hgt = np.median([l.bbox[3] - l.bbox[1] for l in xs])
        unit = [l for l in labels if l.value is None and abs(l.bbox[1] - row_top) < 0.8 * hgt
                and box.x1 - 0.05 * box.w <= l.cx <= box.x1 + 0.25 * box.w]
        if unit:
            box.xunit_text = unit[0].text.strip("[]() ")
    # categorical x axis (bar charts): words, not numbers, under the axis
    cats = [l for l in labels if box.x0 - 0.12 * box.w <= l.cx <= box.x1 + 0.12 * box.w
            and box.xaxis_y < l.cy <= box.xaxis_y + reach_y and l.value is None]
    if len(cats) >= 2 and len(xs) < 2:
        top = min(l.cy for l in cats)
        hgt = np.median([l.bbox[3] - l.bbox[1] for l in cats])
        box.xcategories = sorted([l for l in cats if l.cy - top <= 0.9 * hgt], key=lambda l: l.cx)
    return box


def analyse(page, xscale="auto", yscale="auto", rgb_fallback=True) -> List[AxesBox]:
    """Vector analysis of a page: axes, exact ticks, text labels, calibration."""
    from .axes import calibrate_box, read_tick_labels
    paths = get_paths(page.pdf_page, page.scale)
    H, W = page.rgb.shape[:2]
    boxes = find_axes(paths, W, H, max(20, 0.08 * min(W, H)))
    chars = get_chars(page.pdf_page, page.scale)
    labels = group_chars(chars) if chars else []
    if labels:
        attach_minus(labels, minus_bars(paths))
        boxes = boxes + find_xonly_axes(paths, boxes, labels, max(20, 0.08 * min(W, H)))
    if not boxes:
        return []
    for b in boxes:
        find_ticks(paths, b)
        label_axes(b, labels, boxes)
        cat = bool(getattr(b, "xcategories", None))
        if rgb_fallback and ((len(b.xlabels) < 2 and not cat) or (len(b.ylabels) < 2 and not b.no_yaxis)):
            # glyphs outlined or missing: OCR the rendering for this box
            xl, yl = b.xlabels, b.ylabels
            read_tick_labels(page.rgb, b, boxes)
            got = (len(b.xlabels) >= 2 and len(xl) < 2) or (len(b.ylabels) >= 2 and len(yl) < 2)
            if len(xl) >= 2:
                b.xlabels = xl
            if len(yl) >= 2:
                b.ylabels = yl
            if got:
                b.notes.append({"level": "info", "code": "ocr_fallback",
                                "msg": "Tick labels are not stored as text in this file; read by OCR."})
    boxes = _drop_legend_frames(boxes, paths)
    _fix_shared_labels(boxes)
    for b in boxes:
        cat = bool(getattr(b, "xcategories", None))
        calibrate_box(b, xscale, yscale)
        if cat:
            b.xcal = None
            b.notes = [n for n in b.notes if not n["code"].startswith("x_")]
            b.notes.append({"level": "info", "code": "x_categorical",
                            "msg": "x-axis is categorical: " + ", ".join(l.text for l in b.xcategories)})
        for c in (b.xcal, b.ycal):
            if c is not None and c.source == "ocr" and labels:
                c.source = "vector-text"
    _share_calibrations(boxes)
    return boxes


def _drop_legend_frames(boxes: List[AxesBox], paths: List[VPath]) -> List[AxesBox]:
    """A framed box inside a plot is an inset plot only if it has ticks or tick numbers,
    or data reaching across it (bars, curves). A legend frame holds only short line
    samples, small markers and text."""
    out = []
    for b in boxes:
        par = getattr(b, "inset_of", None)
        if par is None or len(b.xlabels) >= 2 or len(b.ylabels) >= 2:
            out.append(b)
            continue
        # (single labels or ticks may be the parent's, next to the frame)
        inside = [p for p in paths if b.x0 - 1 <= p.bbox[0] and p.bbox[2] <= b.x1 + 1
                  and b.y0 - 1 <= p.bbox[1] and p.bbox[3] <= b.y1 + 1
                  and not (p.w > 0.95 * b.w and p.h > 0.95 * b.h)]          # not the frame itself
        if any(p.h > 0.35 * b.h or p.w > 0.5 * b.w for p in inside):
            out.append(b)
            continue
        par.insets = [i for i in getattr(par, "insets", []) if i is not b]
    return out


def _same_row(a: AxesBox, b: AxesBox) -> bool:
    if getattr(a, "inset_of", None) is b or getattr(b, "inset_of", None) is a:
        return False          # an inset is not a neighbouring panel (labels under it belong to the parent)
    ov = min(a.y1, b.y1) - max(a.y0, b.y0)
    return ov > 0.8 * min(a.h, b.h)


def _fix_shared_labels(boxes: List[AxesBox]):
    """Panels side by side: tick labels belong to the panel they sit next to.
    * x labels lying under another panel are dropped;
    * y labels between two panels go to the nearer box edge – a right-hand y axis
      (labels right of the right spine) is common in paired panels."""
    for b in boxes:
        others = [o for o in boxes if o is not b and _same_row(o, b)]
        b.xlabels = [l for l in b.xlabels
                     if b.x0 - 0.03 * b.w <= l.cx <= b.x1 + 0.03 * b.w
                     or not any(o.x0 - 0.03 * o.w <= l.cx <= o.x1 + 0.03 * o.w for o in others)]
        b.xlabels = [l for l in b.xlabels if not any(o.x0 + 2 <= l.bbox[0] and l.bbox[2] <= o.x1 - 2 for o in others)]
    for b in boxes:
        if not b.ylabels:
            continue
        left_nb = [o for o in boxes if o is not b and _same_row(o, b) and o.x1 <= b.x0 + 2]
        if not left_nb:
            continue
        a = max(left_nb, key=lambda o: o.x1)
        right_edge = max(l.bbox[2] for l in b.ylabels)
        left_edge = min(l.bbox[0] for l in b.ylabels)
        if left_edge - a.x1 < b.x0 - right_edge and left_edge > a.x1 - 2:
            a.ylabels, b.ylabels = list(b.ylabels), []
            a.y_right = True
            a.notes.append({"level": "info", "code": "y_right", "msg": "y-axis labels are on the right-hand side."})


def _share_calibrations(boxes: List[AxesBox]):
    """A panel without its own axis numbers takes the calibration of a neighbour in the
    same row (y) or column (x) whose axis spans exactly the same pixels."""
    import copy
    for b in boxes:
        if b.ycal is None:
            cands = [o for o in boxes if o is not b and o.ycal is not None and o.ycal.source != "relative"
                     and abs(o.y0 - b.y0) < 3 and abs(o.y1 - b.y1) < 3]
            if cands:
                o = min(cands, key=lambda o: abs(o.x0 - b.x0))
                b.ycal = copy.deepcopy(o.ycal)
                b.ycal.source = "shared"
                b.notes = [n for n in b.notes if not n["code"].startswith("y_")]
                b.notes.append({"level": "info", "code": "y_shared",
                                "msg": "y axis has no numbers of its own; it shares the y scale of the panel beside it."})
        if b.xcal is None:
            cands = [o for o in boxes if o is not b and o.xcal is not None and abs(o.x0 - b.x0) < 3 and abs(o.x1 - b.x1) < 3]
            if cands:
                o = min(cands, key=lambda o: abs(o.y0 - b.y0))
                b.xcal = copy.deepcopy(o.xcal)
                b.xcal.source = "shared"
                b.notes = [n for n in b.notes if not n["code"].startswith("x_")]
                b.notes.append({"level": "info", "code": "x_shared",
                                "msg": "x axis has no numbers of its own; it shares the x scale of the panel above/below."})
