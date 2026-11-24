"""Exact data extraction from vector paths inside a calibrated plot area."""
from __future__ import annotations

from collections import defaultdict
from typing import List, Tuple

import numpy as np

from ..detect.axes import AxesBox
from ..detect.vector import VPath, get_chars, get_paths, group_chars
from .curves import Series


def _rgb255(c):
    return tuple(int(round(v * 255)) for v in c) if c is not None else (0, 0, 0)


def _inside(bb, box: AxesBox, tol=2.0):
    return (bb[2] >= box.x0 - tol and bb[0] <= box.x1 + tol and bb[3] >= box.y0 - tol and bb[1] <= box.y1 + tol)


def _contained(bb, box: AxesBox, tol=2.0):
    return bb[0] >= box.x0 - tol and bb[2] <= box.x1 + tol and bb[1] >= box.y0 - tol and bb[3] <= box.y1 + tol


def _is_axis_like(p: VPath, box: AxesBox) -> bool:
    """Frame, spines, ticks, full-span grid lines."""
    if len(p.polys) == 1 and len(p.polys[0]) <= 5:
        pts = p.polys[0]
        w, h = np.ptp(pts[:, 0]), np.ptp(pts[:, 1])
        straight = w < 0.6 or h < 0.6
        if straight:
            if w >= 0.9 * box.w or h >= 0.9 * box.h:
                return True        # spine / frame / grid line
            tol = box.line_w + 1.5
            on_edge_x = (abs(pts[:, 1] - box.y1).min() <= tol or abs(pts[:, 1] - box.y0).min() <= tol)
            on_edge_y = (abs(pts[:, 0] - box.x0).min() <= tol or abs(pts[:, 0] - box.x1).min() <= tol)
            maxlen = max(4.0, 0.06 * max(box.w, box.h))
            if w < 0.6 and h <= maxlen and on_edge_x:
                return True
            if h < 0.6 and w <= maxlen and on_edge_y:
                return True
    return False


def _looks_closed(p) -> bool:
    poly = p.polys[0] if p.polys else None
    return poly is not None and len(poly) > 3 and np.hypot(*(poly[0] - poly[-1])) < 0.05 * max(p.w, p.h, 1e-6)


def _join_words(labels):
    """Words on one baseline, at most ~1 em apart, form one label ("Sample" + "A")."""
    from ..detect import ocr as _ocr
    labels = sorted(labels, key=lambda l: (round(l.bbox[3]), l.bbox[0]))
    out = []
    for l in labels:
        h = l.bbox[3] - l.bbox[1]
        if out:
            o = out[-1]
            oh = o.bbox[3] - o.bbox[1]
            if (abs(o.bbox[3] - l.bbox[3]) < 0.3 * max(h, oh) and 0 <= l.bbox[0] - o.bbox[2] < 1.0 * max(h, oh)
                    and abs(h / oh - 1) < 0.35
                    and np.linalg.norm(np.array(getattr(o, "color", None) or (0, 0, 0)) -
                                       np.array(getattr(l, "color", None) or (0, 0, 0))) < 60):
                bb = (o.bbox[0], min(o.bbox[1], l.bbox[1]), l.bbox[2], max(o.bbox[3], l.bbox[3]))
                n = _ocr.Label(bb, o.text + " " + l.text, None, 100.0, None)
                n.rotated = False
                n.color = getattr(o, "color", None)
                n.bold = getattr(o, "bold", False) and getattr(l, "bold", False)
                n.size = max(getattr(o, "size", 0) or 0, getattr(l, "size", 0) or 0) or None
                out[-1] = n
                continue
        out.append(l)
    return out


def _split_legend(labels, hmed):
    """(legend entries, direct point labels)."""
    if len(labels) < 2:
        return [], list(labels)
    size = max(hmed, 1e-6)
    legend = set()
    for i, a in enumerate(labels):
        col = [b for b in labels if abs(b.bbox[0] - a.bbox[0]) < 0.6 * size]
        if len(col) < 2:
            continue
        ys = sorted(0.5 * (b.bbox[1] + b.bbox[3]) for b in col)
        steps = np.diff(ys)
        if len(steps) and steps.max() < 2.6 * size and (len(steps) == 1 or steps.std() < 0.35 * steps.mean()):
            legend.update(id(b) for b in col)
    return [l for l in labels if id(l) in legend], [l for l in labels if id(l) not in legend]


def _marker_shape(p) -> str:
    """Matplotlib marker code from a marker outline."""
    poly = p.polys[0] if p.polys else None
    if poly is None or len(poly) < 3:
        return "o"
    P = poly[:-1] if np.hypot(*(poly[0] - poly[-1])) < 1e-3 else poly
    n = len(P)
    if n > 8:
        return "o"
    c = P.mean(axis=0)
    ang = np.degrees(np.arctan2(-(P[:, 1] - c[1]), P[:, 0] - c[0])) % 360
    if n == 3:
        ymin = P[:, 1].argmin()          # vertex with the smallest y (top on the page)
        lone_top = abs(P[ymin, 0] - c[0]) < 0.2 * p.w
        return "^" if lone_top else "v"
    if n == 4:
        axis_aligned = all(min(a % 90, 90 - a % 90) > 30 for a in ang)
        return "s" if axis_aligned else "D"
    if n == 5:
        return "p"
    if n == 6:
        return "h"
    return "o"


def _name_by_point_labels(series, labels):
    """Each marker series takes the name of the closest direct label (colour-matched when
    the text is coloured); the label position is kept for the replot."""
    used = set()
    for s in sorted(series, key=lambda q: q.kind != "markers"):
        if not len(s.px) or not s.name.startswith("series_") and s.kind != "markers":
            continue
        best = None
        for k, lab in enumerate(labels):
            if k in used:
                continue
            cx, cy = 0.5 * (lab.bbox[0] + lab.bbox[2]), 0.5 * (lab.bbox[1] + lab.bbox[3])
            d = np.min(np.hypot(s.px - cx, s.py - cy))
            h = lab.bbox[3] - lab.bbox[1]
            col = getattr(lab, "color", None)
            cmatch = col is not None and any(c is not None and np.linalg.norm(np.array(col) - np.array(c)) < 60
                                             for c in (s.style.get("face"), s.style.get("edge"), s.color_rgb))
            if s.kind != "markers":
                if not cmatch or sum(col) < 60:      # traces: only colour-matched labels (black text is generic)
                    continue
                d = d / 3                            # labels sit at a trace's end, farther than marker labels
            if d > 6 * h:
                continue
            score = d / h - (3 if cmatch else 0)
            if best is None or score < best[0]:
                best = (score, k, lab)
        if best:
            _, k, lab = best
            used.add(k)
            s.name = lab.text
            s.style["label_box"] = lab.bbox
            s.style["label_color"] = getattr(lab, "color", None)


def _glyph_labels(page, cand, box):
    """Group small filled dark paths (outlined text) into words; read them by OCR."""
    from ..detect import ocr
    lim = 0.05 * min(box.w, box.h)
    gl = [(i, p) for i, p in enumerate(cand)
          if p.stroke is None and p.fill is not None and max(p.fill) < 0.4 and (max(p.fill) - min(p.fill)) < 0.15
          and 0 < p.h < lim and p.w < 1.5 * lim]
    if len(gl) < 2:
        return [], set()
    hs = np.median([p.h for _, p in gl])
    n = len(gl)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a in range(n):
        A = gl[a][1].bbox
        for b in range(a + 1, n):
            B = gl[b][1].bbox
            dx = max(0, max(A[0], B[0]) - min(A[2], B[2]))
            vo = min(A[3], B[3]) - max(A[1], B[1])
            if dx < 0.9 * hs and vo > -0.2 * hs:
                parent[find(a)] = find(b)
    groups = {}
    for k in range(n):
        groups.setdefault(find(k), []).append(gl[k])
    labels, used = [], set()
    gray = page.rgb.mean(axis=2).astype(np.uint8)
    for g in groups.values():
        if len(g) < 2:
            continue
        x0 = min(p.bbox[0] for _, p in g); y0 = min(p.bbox[1] for _, p in g)
        x1 = max(p.bbox[2] for _, p in g); y1 = max(p.bbox[3] for _, p in g)
        pad = int(0.3 * hs) + 2
        crop = gray[max(0, int(y0) - pad):int(y1) + pad, max(0, int(x0) - pad):int(x1) + pad]
        txt, conf = ocr.read_text(crop, psm=7) if crop.size else ("", 0)
        labels.append(ocr.Label((x0, y0, x1, y1), txt.strip() or f"label_{len(labels) + 1}", None, conf))
        used.update(i for i, _ in g)
    return labels, used


def outlined_words(paths, region, max_h):
    """Text drawn as filled outlines (Ghostscript-converted EPS, "convert text to paths"):
    split filled compound paths into glyphs, group glyphs into words, rasterise each word
    from its own outlines (so nothing drawn underneath interferes) and read it by OCR.
    ``region``: (x0, y0, x1, y1); a word counts when its centre lies inside.
    Returns OCR labels with ``color`` (0-255 RGB) and ``glyph_h`` (tallest glyph)."""
    import cv2
    from ..detect import ocr
    rx0, ry0, rx1, ry1 = region
    glyphs = []                       # (bbox, [polys], colour)
    for p in paths:
        if p.stroke is not None or p.fill is None or min(p.fill) > 0.9:
            continue
        if p.bbox[2] < rx0 or p.bbox[0] > rx1 or p.bbox[3] < ry0 or p.bbox[1] > ry1:
            continue
        polys = [q for q in p.polys if len(q) >= 3 and max(np.ptp(q[:, 0]), np.ptp(q[:, 1])) < max_h * 1.5]
        polys.sort(key=lambda q: -np.ptp(q[:, 0]) * np.ptp(q[:, 1]))
        mine = []
        for q in polys:               # counters (holes) join the glyph that contains them
            bb = (q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max())
            host = next((g for g in mine if g[0][0] - 1 <= bb[0] and bb[2] <= g[0][2] + 1
                         and g[0][1] - 1 <= bb[1] and bb[3] <= g[0][3] + 1), None)
            if host is not None:
                host[1].append(q)
            else:
                mine.append([bb, [q], tuple(int(round(255 * v)) for v in p.fill[:3])])
        glyphs += [g for g in mine if 0 < g[0][3] - g[0][1] <= max_h]
    if not glyphs:
        return []
    hs = float(np.median([g[0][3] - g[0][1] for g in glyphs]))
    n = len(glyphs)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a in range(n):
        A, ca = glyphs[a][0], glyphs[a][2]
        for b in range(a + 1, n):
            B, cb = glyphs[b][0], glyphs[b][2]
            dx = max(0, max(A[0], B[0]) - min(A[2], B[2]))
            vo = min(A[3], B[3]) - max(A[1], B[1])
            if ca == cb and dx < 0.6 * hs and vo > 0.3 * min(A[3] - A[1], B[3] - B[1]):
                parent[find(a)] = find(b)
    groups = {}
    for k in range(n):
        groups.setdefault(find(k), []).append(glyphs[k])
    out = []
    for g in groups.values():
        x0 = min(q[0][0] for q in g); y0 = min(q[0][1] for q in g)
        x1 = max(q[0][2] for q in g); y1 = max(q[0][3] for q in g)
        cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        if not (rx0 <= cx <= rx1 and ry0 <= cy <= ry1):
            continue
        gh = max(q[0][3] - q[0][1] for q in g)
        f = 40.0 / max(gh, 1e-6)                  # tallest glyph → 40 px
        pad = 12
        W, H = int((x1 - x0) * f) + 2 * pad, int((y1 - y0) * f) + 2 * pad
        img = np.full((H, W), 255, np.uint8)
        polys = [np.round((q - [x0, y0]) * f + pad).astype(np.int32) for gl in g for q in gl[1]]
        cv2.fillPoly(img, polys, 0)               # even-odd: counters stay open
        # words within the group (a space is a gap wider than ~0.3 of the glyph height)
        g.sort(key=lambda q: q[0][0])
        pieces, cur = [], [g[0]]
        for a, b in zip(g[:-1], g[1:]):
            if b[0][0] - max(q[0][2] for q in cur) > 0.3 * gh:
                pieces.append(cur)
                cur = []
            cur.append(b)
        pieces.append(cur)
        words, confs = [], []
        for pc in pieces:
            px0 = int((min(q[0][0] for q in pc) - x0) * f)
            px1 = int((max(q[0][2] for q in pc) - x0) * f) + 2 * pad
            t, c = ocr.read_text(img[:, px0:px1], psm=10 if len(pc) == 1 else 7)
            if t.strip():
                words.append(t.strip())
                confs.append(c)
        if not words:
            continue
        lab = ocr.Label((x0, y0, x1, y1), " ".join(words), None, float(np.mean(confs)))
        lab.color, lab.glyph_h, lab.rotated = g[0][2], gh, False
        # stroke weight: mean stroke width (2·area/perimeter) relative to the tallest glyph
        ink = (img < 128).astype(np.uint8)
        cnts, _h = cv2.findContours(ink, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        per = sum(cv2.arcLength(c, True) for c in cnts)
        lab.stroke_rel = float(2 * ink.sum() / per / 40.0) if per > 0 else 0.0
        out.append(lab)
    return out


def extract_vector_series(page, box: AxesBox, paths=None, chars=None) -> Tuple[List[Series], dict]:
    paths = paths if paths is not None else get_paths(page.pdf_page, page.scale)
    chars = chars if chars is not None else get_chars(page.pdf_page, page.scale)
    info = {"notes": [], "legend": []}
    cand = []
    insets = getattr(box, "insets", [])
    for p in paths:
        if not _inside(p.bbox, box):
            continue
        if any(_contained(p.bbox, ib, max(2.0, 0.05 * max(ib.w, ib.h))) for ib in insets):
            continue            # belongs to an inset plot
        if p.stroke is None and p.fill is not None and min(p.fill) > 0.95 and p.w * p.h > 0.3 * box.w * box.h:
            continue  # axes background
        if _is_axis_like(p, box):
            if p.stroke is not None and min(p.stroke) > 0.6 and len(p.polys) == 1 and (p.w >= 0.9 * box.w or p.h >= 0.9 * box.h):
                info["grid"] = info.get("grid", 0) + 1
            continue
        cand.append(p)
    # legend: text inside the plot area + short paths just left of it
    def _cin(c):
        cx, cy = 0.5 * (c.bbox[0] + c.bbox[2]), 0.5 * (c.bbox[1] + c.bbox[3])
        return box.x0 < cx < box.x1 and box.y0 < cy < box.y1
    inner = [c for c in chars if _cin(c) and not any(_contained(c.bbox, ib, 4.0) for ib in insets)]
    # whole words: a label that starts inside the plot keeps its last glyphs
    words = {c.word for c in inner if c.word >= 0}
    inner += [c for c in chars if c.word in words and c not in inner and c.word >= 0
              and box.x0 - 0.1 * box.w < c.bbox[0] < box.x1 + 0.1 * box.w and box.y0 < c.bbox[3] and c.bbox[1] < box.y1]
    legend_labels = _join_words([l for l in group_chars(inner) if not getattr(l, "rotated", False)]) if inner else []
    if not legend_labels:
        # text drawn as outlined glyphs (SVG/PDF without fonts): find and OCR them
        legend_labels, glyph_ids = _glyph_labels(page, cand, box)
        cand = [p for i, p in enumerate(cand) if i not in glyph_ids]
    style_names = {}
    legend_paths = set()
    hmed = float(np.median([l.bbox[3] - l.bbox[1] for l in legend_labels])) if legend_labels else 0.0
    # a legend is a column of labels (left edges aligned, regularly stacked); scattered
    # single labels next to data points are direct labels that name those points
    legend_labels, direct = _split_legend(legend_labels, hmed)
    info["point_labels"] = direct
    for lab in legend_labels:
        size = max(lab.bbox[3] - lab.bbox[1], hmed)
        cy = 0.5 * (lab.bbox[1] + lab.bbox[3])
        handles = []
        for i, p in enumerate(cand):
            bb = p.bbox
            if (bb[2] <= lab.bbox[0] + 0.5 and bb[0] >= lab.bbox[0] - 6.0 * size and
                    bb[1] >= lab.bbox[1] - 0.8 * size and bb[3] <= lab.bbox[3] + 0.8 * size):
                handles.append((abs(0.5 * (bb[1] + bb[3]) - cy), i, p))
            # legend frame: a filled/stroked rectangle enclosing the label
            elif (bb[0] <= lab.bbox[0] and bb[2] >= lab.bbox[2] and bb[1] <= lab.bbox[1] and bb[3] >= lab.bbox[3]
                  and p.w < 0.8 * box.w and len(p.polys) == 1 and len(p.polys[0]) <= 6):
                legend_paths.add(i)
        if handles:
            dmin = min(h[0] for h in handles)
            for d, i, p in handles:
                if d <= dmin + 0.25 * size:          # the handle row of this label only
                    legend_paths.add(i)
                    style_names.setdefault(p.style_key(), lab.text)
        info["legend"].append(lab.text)
    cand = [p for i, p in enumerate(cand) if i not in legend_paths]
    groups = defaultdict(list)
    for p in cand:
        groups[p.style_key()].append(p)
    series: List[Series] = []
    small = 0.08 * max(box.w, box.h)
    marker_groups, bar_groups = [], []
    for key, ps in groups.items():
        tiny = [p for p in ps if p.w < small and p.h < small]
        areas = [p for p in tiny if p.w > 0.3 and p.h > 0.3 and (p.closed or p.fill is not None or _looks_closed(p))]
        vbars = [p for p in ps if len(p.polys) == 1 and len(p.polys[0]) == 2 and p.w < 0.3 and p.h > 0]
        hcaps = [p for p in tiny if p.h < 0.3 and p.w > 0]
        single = (len(areas) >= 1 and len(areas) == len(ps) and key[3] is not None
                  and all(p.closed or p.fill is not None for p in areas))
        if (len(areas) >= 2 and len(areas) >= 0.3 * len(ps)) or single:
            marker_groups.append((key, areas, hcaps))
        elif len(vbars) >= 2 and len(vbars) + len(hcaps) >= 0.8 * len(ps):
            bar_groups.append((key, vbars))
        else:
            pts = [poly for p in ps for poly in p.polys]
            if not pts:
                continue
            # order sub-paths left→right but keep each sub-path's own order
            pts.sort(key=lambda a: a[:, 0].min())
            seg_breaks = np.cumsum([len(a) for a in pts])[:-1]
            allp = np.vstack(pts)
            col = key[0] if key[0] is not None else key[3]
            s = Series(style_names.get(key, f"series_{len(series) + 1}"), "line", _rgb255(col),
                       allp[:, 0], allp[:, 1], source="vector")
            s.style = {"width_px": key[1], "dashes": key[2], "segments": seg_breaks.tolist()}
            s.dashed = bool(key[2]) and key[2].strip() not in ("[] 0", "[]0", "")
            # dashes drawn as separate short pieces (Inkscape "stroke to path", exploded dashes)
            if not s.dashed and len(pts) >= 6:
                lens = np.array([np.sum(np.hypot(*np.diff(a, axis=0).T)) for a in pts])
                gaps = [np.hypot(*(b[0] - a[-1])) for a, b in zip(pts[:-1], pts[1:])]
                if np.median(gaps) > 0.3 * np.median(lens) and np.median(lens) < 0.05 * max(box.w, box.h):
                    s.dashed = True
                    short = lens < 0.35 * np.median(lens[lens > np.median(lens)]) if (lens > np.median(lens)).any() else lens < 0
                    s.style["linestyle"] = "-." if 0.25 < short.mean() < 0.6 else "--"
            series.append(s)
    for key, ms, caps in marker_groups:
        cen = np.array([[0.5 * (p.bbox[0] + p.bbox[2]), 0.5 * (p.bbox[1] + p.bbox[3])] for p in ms])
        order = np.argsort(cen[:, 0])
        cen = cen[order]
        col = key[3] if key[3] is not None else key[0]
        s = Series(style_names.get(key, f"series_{len(series) + 1}"), "markers", _rgb255(col),
                   cen[:, 0], cen[:, 1], source="vector")
        s.style = {"marker_px": float(np.median([max(p.w, p.h) for p in ms])), "marker": _marker_shape(ms[0]),
                   "edge": _rgb255(key[0]) if key[0] is not None else None,
                   "face": _rgb255(key[3]) if key[3] is not None else None,
                   "edge_px": float(key[1]) if key[0] is not None and key[1] else None}
        # matching error bars: same colour, vertical, centred on the marker x
        for bkey, bars in bar_groups:
            bcol = bkey[0]
            if bcol is None or col is None or np.linalg.norm(np.array(bcol) - np.array(col)) > 0.05:
                continue
            lo = np.full(len(cen), np.nan)
            hi = np.full(len(cen), np.nan)
            for b in bars:
                xb = b.polys[0][0, 0]
                j = int(np.argmin(np.abs(cen[:, 0] - xb)))
                if abs(cen[j, 0] - xb) < 1.0:
                    ys = b.polys[0][:, 1]
                    hi[j], lo[j] = ys.min(), ys.max()
            if np.isfinite(lo).any():
                s.yerr_lo, s.yerr_hi = lo, hi
        series.append(s)
    _name_by_point_labels(series, info.get("point_labels", []))
    # clip to the plot area (vector paths are stored unclipped)
    for s in series:
        if s.kind != "line" or getattr(box, "no_yaxis", False):
            continue           # offset spectra may run past the axis line: keep them whole
        tol = 0.5
        keep = (s.px >= box.x0 - tol) & (s.px <= box.x1 + tol) & (s.py >= box.y0 - tol) & (s.py <= box.y1 + tol)
        if not keep.all():
            s.notes.append({"level": "warn", "code": "clipped",
                            "msg": f"{(~keep).sum()} vertices lie outside the axes and were clipped "
                                   "(data extend beyond the plotted range)."})
            s.px, s.py = s.px[keep], s.py[keep]
    info["n_paths"] = len(cand)
    return [s for s in series if len(s.px)], info
