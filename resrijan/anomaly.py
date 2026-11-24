"""Consistency checks run on every extraction, reported in the JSON and HTML report."""
from __future__ import annotations

from typing import List

import numpy as np


def _note(level, code, msg, **kw):
    d = {"level": level, "code": code, "msg": msg}
    d.update(kw)
    return d


def calibration_checks(box) -> List[dict]:
    out = []
    for cal in (box.xcal, box.ycal):
        if cal is None:
            continue
        if cal.n_used < 3 and cal.source not in ("manual", "relative"):
            out.append(_note("warn", f"{cal.axis}_two_labels",
                             f"{cal.axis}-axis calibrated from only {cal.n_used} labels: no redundancy to catch a misread."))
        if cal.rms_px > 1.0:
            out.append(_note("warn", f"{cal.axis}_cal_rms",
                             f"{cal.axis}-tick residual {cal.rms_px:.2f} px RMS: ticks are not evenly placed "
                             "(non-linear axis or distorted image?)."))
        if cal.scale == "log":
            out.append(_note("info", f"{cal.axis}_log", f"{cal.axis}-axis is logarithmic."))
    if box.xcal is not None and box.ycal is not None:
        out.append(_note("info", "resolution",
                         f"Resolution: 1 px = {box.xcal.unit_per_px:.3g} (x), {box.ycal.unit_per_px:.3g} (y) "
                         "data units near the axis centre."))
    return out


def series_checks(s, box) -> List[dict]:
    out = []
    if s.y is None or len(s.y) < 7:
        return out
    y = np.asarray(s.y, float)
    np.log10(np.clip(y, 1e-300, None)) if (box.ycal is not None and box.ycal.scale == "log") else y
    if s.kind == "line" and s.source == "raster" and len(s.px) > 5:
        # spikes in pixel space: a point far off the chord of its neighbours
        P = np.c_[s.px, s.py]
        a, b, c = P[:-2], P[1:-1], P[2:]
        ab = c - a
        L = np.linalg.norm(ab, axis=1)
        cross = np.abs(ab[:, 0] * (b - a)[:, 1] - ab[:, 1] * (b - a)[:, 0]) / np.maximum(L, 1e-9)
        thick = float(s.style.get("line_px", 2.0))
        spikes = np.nonzero((cross > max(4.0, 3 * thick)) & (L < 0.5 * cross))[0] + 1
        if len(spikes):
            out.append(_note("warn", "spikes",
                             f"{s.name}: {len(spikes)} isolated spike(s) (e.g. x={s.x[spikes[0]]:.4g}); "
                             "check for crossings with other series or text.", index=spikes[:50].tolist()))
        dx = np.diff(s.px)
        big = dx[np.abs(dx) > 2.0]
        if len(big) and (np.sign(big) != np.sign(np.median(dx))).mean() > 0.05:
            out.append(_note("info", "multivalued",
                             f"{s.name}: curve turns back in x (multi-valued or loop); drawing order kept."))
    return out


def duplicate_series(series) -> List[dict]:
    out = []
    for i in range(len(series)):
        for j in range(i + 1, len(series)):
            a, b = series[i], series[j]
            if a.kind != "line" or b.kind != "line" or a.x is None or b.x is None:
                continue
            lo, hi = max(np.min(a.x), np.min(b.x)), min(np.max(a.x), np.max(b.x))
            if hi <= lo:
                continue
            xs = np.linspace(lo, hi, 200)
            oa, ob = np.argsort(a.x), np.argsort(b.x)
            ya = np.interp(xs, np.asarray(a.x)[oa], np.asarray(a.y)[oa])
            yb = np.interp(xs, np.asarray(b.x)[ob], np.asarray(b.y)[ob])
            rng = max(np.ptp(ya), np.ptp(yb), 1e-12)
            close = np.abs(ya - yb) < 0.01 * rng
            if close.mean() > 0.3:
                out.append(_note("info", "overlap",
                                 f"{a.name} and {b.name} coincide over {close.mean() * 100:.0f}% of their common range; "
                                 "the hidden series is interpolated where it is covered."))
    return out
