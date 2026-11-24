"""Axis calibration: map pixel / point coordinates to data values.

A calibration is fitted from (position, value) pairs taken from tick marks and their
labels. Linear and logarithmic models are both tried with RANSAC, so a single misread
label cannot corrupt the fit; rejected labels are reported as anomalies.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Sequence

import numpy as np


@dataclass
class AxisCalibration:
    axis: str                     # "x" or "y"
    scale: str                    # "linear" or "log"
    a: float                      # f(value) = a * pos + b, f = id or log10
    b: float
    rms_px: float = 0.0           # RMS residual of tick positions (pixels / points)
    n_used: int = 0
    positions: List[float] = field(default_factory=list)
    values: List[float] = field(default_factory=list)
    rejected: List[dict] = field(default_factory=list)
    source: str = "auto"          # "vector-text", "ocr", "manual", "inferred"
    unit_per_px: float = 0.0      # data resolution near the axis centre

    def to_data(self, pos):
        pos = np.asarray(pos, dtype=float)
        f = self.a * pos + self.b
        return 10.0 ** f if self.scale == "log" else f

    def to_pos(self, val):
        val = np.asarray(val, dtype=float)
        f = np.log10(val) if self.scale == "log" else val
        return (f - self.b) / self.a

    @property
    def reversed(self) -> bool:
        # x grows to the right in images; y grows downward, so a normal y axis has a < 0
        return (self.a < 0) if self.axis == "x" else (self.a > 0)

    def as_dict(self):
        d = asdict(self)
        d["reversed"] = self.reversed
        return d


def _fit(pos, f):
    A = np.vstack([pos, np.ones_like(pos)]).T
    sol, *_ = np.linalg.lstsq(A, f, rcond=None)
    return float(sol[0]), float(sol[1])


def _ransac(pos: np.ndarray, f: np.ndarray, tol: float):
    n = len(pos)
    best = None
    pairs = itertools.combinations(range(n), 2) if n <= 40 else (
        tuple(np.random.default_rng(0).choice(n, 2, replace=False)) for _ in range(800))
    for i, j in pairs:
        if pos[i] == pos[j] or f[i] == f[j]:
            continue
        a = (f[j] - f[i]) / (pos[j] - pos[i])
        b = f[i] - a * pos[i]
        pred = (f - b) / a
        res = np.abs(pred - pos)
        inl = res < tol
        score = (inl.sum(), -np.sqrt(np.mean(res[inl] ** 2)) if inl.any() else 0)
        if best is None or score > best[0]:
            best = (score, inl)
    if best is None:
        return None
    inl = best[1]
    a, b = _fit(pos[inl], f[inl])
    # one refinement pass
    res = np.abs((f - b) / a - pos)
    inl = res < tol
    if inl.sum() >= 2:
        a, b = _fit(pos[inl], f[inl])
    res = (f - b) / a - pos
    return a, b, inl, res


def calibrate(axis: str, positions: Sequence[float], values: Sequence[float],
              scale: str = "auto", tol: Optional[float] = None, source: str = "auto",
              span: Optional[float] = None) -> Optional[AxisCalibration]:
    """Fit an axis calibration from label positions and values.

    ``scale`` may be "linear", "log" or "auto". ``tol`` is the inlier tolerance in
    position units (default: 1.5% of the label span, at least 1.5 units).
    """
    pos = np.asarray(positions, dtype=float)
    val = np.asarray(values, dtype=float)
    ok = np.isfinite(pos) & np.isfinite(val)
    pos, val = pos[ok], val[ok]
    if len(pos) < 2:
        return None
    span = span or (pos.max() - pos.min())
    tol = tol or max(1.5, 0.015 * span)
    cands = []
    scales = ["linear", "log"] if scale == "auto" else [scale]
    for sc in scales:
        if sc == "log":
            if np.any(val <= 0):
                continue
            f = np.log10(val)
        else:
            f = val
        r = _ransac(pos, f, tol)
        if r is None:
            continue
        a, b, inl, res = r
        if inl.sum() < 2:
            continue
        rms = float(np.sqrt(np.mean(res[inl] ** 2)))
        cands.append((int(inl.sum()), -rms, sc, a, b, inl, res))
    if not cands:
        return None
    # prefer more inliers, then lower residual; linear wins ties (simpler model)
    cands.sort(key=lambda c: (c[0], round(c[1], 1), c[2] == "linear"), reverse=True)
    n_in, negrms, sc, a, b, inl, res = cands[0]
    # "log" needs >= 3 inliers spanning > 1 decade to be preferred over linear
    if sc == "log" and scale == "auto":
        f = np.log10(val[inl])
        lin = [c for c in cands if c[2] == "linear"]
        if (n_in < 3 or f.max() - f.min() < 0.9) and lin and lin[0][0] >= n_in - 0:
            n_in, negrms, sc, a, b, inl, res = lin[0]
    rejected = [{"position": float(p), "value": float(v), "residual": float(r)}
                for p, v, r, k in zip(pos, val, res, inl) if not k]
    cal = AxisCalibration(axis=axis, scale=sc, a=a, b=b, rms_px=float(-negrms), n_used=int(n_in),
                          positions=[float(p) for p in pos[inl]], values=[float(v) for v in val[inl]],
                          rejected=rejected, source=source)
    mid = 0.5 * (pos.min() + pos.max())
    cal.unit_per_px = float(abs(cal.to_data(mid + 0.5) - cal.to_data(mid - 0.5)))
    return cal


def manual(axis: str, spec: str, scale: str = "linear") -> AxisCalibration:
    """Build a calibration from a manual spec "pos1:val1,pos2:val2[,...]"."""
    pairs = [p.split(":") for p in spec.split(",") if p.strip()]
    pos = [float(p[0]) for p in pairs]
    val = [float(p[1]) for p in pairs]
    cal = calibrate(axis, pos, val, scale=scale, tol=1e9, source="manual")
    if cal is None:
        raise ValueError(f"Could not build manual calibration from {spec!r}")
    return cal


def snap_to_ticks(label_pos: Sequence[float], ticks: Sequence[float], max_dist: float):
    """Replace label centres by the nearest tick position (ticks are more precise)."""
    ticks = np.asarray(ticks, dtype=float)
    out, snapped = [], []
    for p in label_pos:
        if len(ticks):
            k = int(np.argmin(np.abs(ticks - p)))
            if abs(ticks[k] - p) <= max_dist:
                out.append(float(ticks[k])); snapped.append(True)
                continue
        out.append(float(p)); snapped.append(False)
    return out, snapped


def spacing_anomalies(ticks: Sequence[float], rel_tol: float = 0.08):
    """Flag non-uniform major tick spacing (possible axis break / non-linear axis)."""
    t = np.sort(np.asarray(ticks, dtype=float))
    if len(t) < 3:
        return []
    d = np.diff(t)
    med = np.median(d)
    if med <= 0:
        return []
    bad = np.where(np.abs(d - med) > rel_tol * med)[0]
    return [{"between": (float(t[i]), float(t[i + 1])), "spacing": float(d[i]), "median": float(med)}
            for i in bad]


# ───────────────────────── label repair ─────────────────────────
NICE = (1.0, 2.0, 2.5, 5.0)


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _sim(pred: float, text: str) -> float:
    ps = f"{pred:.6g}"
    a, b = _digits(ps), _digits(text)
    if not a and not b:
        return 0.0
    sim = 1.0 - _lev(a, b) / max(len(a), len(b), 1)
    neg_ok = (pred < 0) == text.strip().startswith(("-", "−"))
    return sim * (1.0 if neg_ok else 0.7)


def _nice(step: float) -> float:
    if step == 0 or not math.isfinite(step):
        return step
    e = math.floor(math.log10(abs(step)))
    m = abs(step) / 10 ** e
    best = min(NICE + (10.0,), key=lambda n: abs(n - m))
    return math.copysign(best * 10 ** e, step)


def repair_labels(positions: Sequence[float], texts: Sequence[str], values: Sequence[Optional[float]]):
    """Correct OCR misreads on a linear axis with evenly spaced labelled ticks.

    Hypotheses (anchor value, nice step) are scored by how well the predicted label
    strings match what OCR read, character by character. Returns (values, score) or
    None if no confident repair exists.
    """
    pos = np.asarray(positions, dtype=float)
    n = len(pos)
    if n < 3:
        return None
    order = np.argsort(pos)
    pos = pos[order]
    texts = [texts[i] for i in order]
    vals = [values[i] for i in order]
    d = np.diff(pos)
    step_px = float(np.median(d))
    if step_px <= 0 or np.any(np.abs(d - step_px) > 0.12 * step_px * np.maximum(1, np.round(d / step_px))):
        return None
    k = np.round((pos - pos[0]) / step_px).astype(int)
    best = None
    known = [(i, v) for i, v in enumerate(vals) if v is not None]
    for (i, vi), (j, vj) in itertools.permutations(known, 2):
        if k[i] == k[j]:
            continue
        step = _nice((vj - vi) / (k[j] - k[i]))
        if step == 0:
            continue
        for anchor, va in ((i, vi), (j, vj)):
            pred = [va + step * (k[m] - k[anchor]) for m in range(n)]
            pred = [round(p / step) * step if abs(step) >= 1e-12 else p for p in pred]
            score = sum(_sim(p, t) for p, t in zip(pred, texts))
            if best is None or score > best[0]:
                best = (score, pred)
    # single-anchor hypotheses with nice steps of several magnitudes
    for i, vi in known:
        mag = math.floor(math.log10(abs(vi))) if vi != 0 else 0
        for e in range(mag - 3, mag + 1):
            for m in NICE:
                for sgn in (1, -1):
                    step = sgn * m * 10 ** e
                    pred = [round((vi + step * (k[q] - k[i])) / step) * step for q in range(n)]
                    score = sum(_sim(p, t) for p, t in zip(pred, texts))
                    if best is None or score > best[0] + 1e-9:
                        best = (score, pred)
    if best is None or best[0] < 0.6 * n:
        return None
    out = [None] * n
    for o, p in zip(order, best[1]):
        out[o] = float(p)
    return out, best[0] / n
