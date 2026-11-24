"""Scoring of digitised data against ground truth."""
import numpy as np
from scipy.spatial import cKDTree


def _norm(v, lim, scale):
    v = np.asarray(v, float)
    lo, hi = lim
    if scale == "log":
        return (np.log10(np.clip(v, 1e-300, None)) - np.log10(lo)) / (np.log10(hi) - np.log10(lo))
    return (v - lo) / (hi - lo)


def curve_errors(ex, ey, tx, ty, xlim, ylim, xscale="linear", yscale="linear"):
    """Perpendicular distance of extracted points to the true curve, % of axis range."""
    tx, ty = np.asarray(tx, float), np.asarray(ty, float)
    # densify truth
    s = np.linspace(0, 1, len(tx))
    sd = np.linspace(0, 1, max(20000, 20 * len(tx)))
    dx = np.interp(sd, s, tx)
    dy = np.interp(sd, s, ty) if yscale == "linear" else 10 ** np.interp(sd, s, np.log10(ty))
    T = np.c_[_norm(dx, xlim, xscale), _norm(dy, ylim, yscale)]
    E = np.c_[_norm(ex, xlim, xscale), _norm(ey, ylim, yscale)]
    ok = np.all(np.isfinite(E), axis=1)
    E = E[ok]
    if len(E) == 0:
        return None
    d, _ = cKDTree(T).query(E)
    # coverage: fraction of the true x-range that has extracted points
    bins = np.linspace(min(T[:, 0]), max(T[:, 0]), 101)
    h, _ = np.histogram(E[:, 0], bins)
    cov = float((h > 0).mean())
    return {"rms_pct": float(np.sqrt(np.mean(d ** 2)) * 100), "p95_pct": float(np.percentile(d, 95) * 100),
            "max_pct": float(d.max() * 100), "n": int(len(E)), "coverage_pct": cov * 100}


def match_series(extracted, truth_series, xlim, ylim, xscale, yscale):
    """Greedy best match of extracted series (list of (name, x, y)) to truth dict."""
    res = {}
    used = set()
    for tname, t in truth_series.items():
        best = None
        for i, (ename, ex, ey) in enumerate(extracted):
            if i in used:
                continue
            e = curve_errors(ex, ey, t["x"], t["y"], xlim, ylim, xscale, yscale)
            if e is None:
                continue
            key = e["p95_pct"] - 0.02 * e["coverage_pct"]
            if best is None or key < best[0]:
                best = (key, i, ename, e)
        if best:
            used.add(best[1])
            res[tname] = dict(best[3], matched=best[2])
        else:
            res[tname] = None
    return res


def point_errors(ex, ey, tx, ty, xlim, ylim, xscale="linear", yscale="linear"):
    T = np.c_[_norm(tx, xlim, xscale), _norm(ty, ylim, yscale)]
    E = np.c_[_norm(ex, xlim, xscale), _norm(ey, ylim, yscale)]
    if len(E) == 0:
        return None
    d, idx = cKDTree(E).query(T)
    found = d < 0.03
    return {"rms_pct": float(np.sqrt(np.mean(d[found] ** 2)) * 100) if found.any() else None,
            "max_pct": float(d[found].max() * 100) if found.any() else None,
            "recall_pct": float(found.mean() * 100), "n_extracted": int(len(E)), "n_true": int(len(T)),
            "idx": idx, "found": found}
