"""Automatic multi-panel arrangement.

Panels keep their reading order (a, b, c … left→right, top→bottom). Every split of
the sequence into rows is scored: panels should be close to a comfortable printed
width for the target column, images keep their true aspect ratio, plots may stretch
within limits, and the figure must fit the journal's maximum height.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import List, Optional, Sequence


@dataclass
class PanelBox:
    index: int
    row: int
    x_mm: float
    y_mm: float      # from the top
    w_mm: float
    h_mm: float


@dataclass
class Layout:
    rows: List[List[int]]
    row_heights_mm: List[float]
    widths_mm: List[List[float]]
    width_mm: float
    height_mm: float
    cost: float

    def boxes(self, hgap=4.0, vgap=4.0) -> List[PanelBox]:
        out, y = [], 0.0
        for r, (row, h, ws) in enumerate(zip(self.rows, self.row_heights_mm, self.widths_mm)):
            x = 0.0
            for i, w in zip(row, ws):
                out.append(PanelBox(i, r, x, y, w, h))
                x += w + hgap
            y += h + vgap
        return out


def _compositions(n: int, max_per_row: int):
    for cuts in itertools.product([0, 1], repeat=n - 1):
        rows, cur = [], [0]
        for i, c in enumerate(cuts, 1):
            if c:
                rows.append(cur)
                cur = [i]
            else:
                cur.append(i)
        rows.append(cur)
        if all(len(r) <= max_per_row for r in rows):
            yield rows


def auto_layout(aspects: Sequence[float], width_mm: float, max_height_mm: float,
                fixed: Optional[Sequence[bool]] = None, hgap: float = 4.0, vgap: float = 4.0,
                ideal_w: Optional[float] = None, height_mm: Optional[float] = None,
                rows: Optional[List[List[int]]] = None) -> Layout:
    """Choose rows and sizes. ``aspects`` are preferred width/height ratios."""
    n = len(aspects)
    fixed = list(fixed) if fixed is not None else [False] * n
    ideal = ideal_w or min(max(width_mm / 2.6, 40.0), 72.0)
    cand_rows = [rows] if rows else list(_compositions(n, max_per_row=4 if width_mm > 120 else 3))
    best = None
    for rws in cand_rows:
        heights, widths, cost = [], [], 0.0
        for row in rws:
            avail = width_mm - hgap * (len(row) - 1)
            a = [aspects[i] for i in row]
            h = avail / sum(a)
            ws = [ai * h for ai in a]
            # all-flexible rows (plots) may stretch their aspect 0.75–1.6× to approach the ideal height
            if all(not fixed[i] for i in row) and (len(row) > 1 or h > 0.6 * max_height_mm):
                ideal_h = ideal / (sum(a) / len(a))
                h = min(max(ideal_h, h / 1.6), h / 0.75)
            heights.append(h)
            widths.append(ws)
            for w, i in zip(ws, row):
                cost += math.log(w / ideal) ** 2
                eff = w / h
                cost += 0.6 * math.log(eff / aspects[i]) ** 2 * (5.0 if fixed[i] else 1.0)
        H = sum(heights) + vgap * (len(rws) - 1)
        if H > max_height_mm:
            cost += 50 * (H / max_height_mm - 1) + 5
        if height_mm:
            cost += 4 * math.log(H / height_mm) ** 2
        # prefer balanced rows (3+3 over 4+2)
        lens = [len(r) for r in rws]
        cost += 0.15 * (max(lens) - min(lens))
        if best is None or cost < best.cost:
            best = Layout([list(r) for r in rws], heights, widths, width_mm, H, cost)
    return best
