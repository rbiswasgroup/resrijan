"""Basic analysis of one-dimensional data (spectra, decays, digitised curves).

Steps, applied in this order by :func:`analyze` (each one optional):

1. ``convert``   – change the x unit (nm, µm, cm⁻¹, eV, THz);
2. ``crop``      – keep an x range;
3. ``smooth``    – Savitzky–Golay or moving average;
4. ``baseline``  – asymmetric least squares (ALS), polynomial, or a straight line through end points;
5. ``normalize`` – to the maximum, the area, or the 0–1 range;
6. peaks         – found automatically or placed by hand, then fitted together (Gaussian,
                   Lorentzian or pseudo-Voigt) with standard errors from the covariance;
7. ``areas``     – integrals over x ranges.

Everything is plain NumPy/SciPy and works on arrays; :func:`analyze_file` reads a data file
(ReSrijan's own ``_data.csv`` or any table) and writes the results.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# ───────────────────────────── units ─────────────────────────────
HC_EV_NM = 1239.841984          # h·c in eV·nm
UNITS = {"nm": "nm", "um": "µm", "µm": "µm", "cm-1": "cm⁻¹", "ev": "eV", "thz": "THz"}
UNIT_LABEL = {"nm": "Wavelength (nm)", "µm": "Wavelength (µm)", "cm⁻¹": "Wavenumber (cm$^{-1}$)",
              "eV": "Energy (eV)", "THz": "Frequency (THz)"}


def _unit(u: str) -> str:
    k = str(u).strip().lower().replace("^", "").replace("⁻¹", "-1").replace("μ", "u").replace("µ", "u")
    k = {"cm-1": "cm-1", "1/cm": "cm-1", "wavenumber": "cm-1", "um": "um", "micron": "um"}.get(k, k)
    if k not in UNITS:
        raise ValueError(f"unknown unit '{u}' (use nm, um, cm-1, eV or THz)")
    return UNITS[k]


def _to_ev(x, u):
    x = np.asarray(x, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return {"nm": HC_EV_NM / x, "µm": HC_EV_NM / (x * 1e3), "cm⁻¹": x * HC_EV_NM * 1e-7,
                "eV": x, "THz": x * 4.135667696e-3}[u]


def _from_ev(e, u):
    e = np.asarray(e, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return {"nm": HC_EV_NM / e, "µm": HC_EV_NM / e / 1e3, "cm⁻¹": e / (HC_EV_NM * 1e-7),
                "eV": e, "THz": e / 4.135667696e-3}[u]


def convert_x(x, frm: str, to: str) -> np.ndarray:
    """Convert x between nm, µm, cm⁻¹, eV and THz (photon energy relations)."""
    a, b = _unit(frm), _unit(to)
    return np.asarray(x, float) if a == b else _from_ev(_to_ev(x, a), b)


def convert_y_jacobian(x_old, y, frm: str, to: str) -> np.ndarray:
    """Spectral density changes when the x unit changes between wavelength and energy:
    y(E) = y(λ)·|dλ/dE|. Returned scaled to the original maximum (shapes, not absolute units)."""
    x_new = convert_x(x_old, frm, to)
    with np.errstate(divide="ignore", invalid="ignore"):
        j = np.abs(np.gradient(x_old) / np.gradient(x_new))
    out = np.asarray(y, float) * j
    m_old, m_new = np.nanmax(np.abs(y)), np.nanmax(np.abs(out))
    return out * (m_old / m_new if m_new > 0 else 1.0)


# ───────────────────────────── processing ─────────────────────────────
def smooth(y, method: str = "savgol", window: int = 11, order: int = 3) -> np.ndarray:
    """Savitzky–Golay (keeps peak heights) or a centred moving average."""
    y = np.asarray(y, float)
    n = len(y)
    window = int(window)
    if window % 2 == 0:
        window += 1
    window = min(window, n - 1 if n % 2 == 0 else n)
    if window < 3:
        return y.copy()
    if method in ("savgol", "sg", "savitzky-golay"):
        from scipy.signal import savgol_filter
        return savgol_filter(y, window, min(int(order), window - 1), mode="interp")
    if method in ("mean", "moving", "average", "boxcar"):
        k = np.ones(window) / window
        pad = window // 2
        return np.convolve(np.pad(y, pad, mode="edge"), k, mode="valid")
    raise ValueError(f"unknown smoothing method '{method}' (savgol or mean)")


def baseline_als(y, lam: float = 1e5, p: float = 0.01, n_iter: int = 15) -> np.ndarray:
    """Asymmetric least squares baseline (Eilers & Boelens 2005).
    ``lam`` sets the stiffness, ``p`` the asymmetry (small: the baseline runs under the peaks)."""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve
    y = np.asarray(y, float)
    n = len(y)
    D = sparse.diags([1.0, -2.0, 1.0], [0, -1, -2], shape=(n, n - 2), dtype=float)
    DD = lam * D.dot(D.T)
    w = np.ones(n)
    z = y
    for _ in range(n_iter):
        W = sparse.spdiags(w, 0, n, n)
        z = spsolve((W + DD).tocsc(), w * y)
        w_new = p * (y > z) + (1 - p) * (y < z)
        if np.array_equal(w_new, w):
            break
        w = w_new
    return np.asarray(z)


def baseline_poly(x, y, order: int = 2, n_iter: int = 30) -> np.ndarray:
    """Polynomial baseline fitted iteratively under the signal (points above the fit are clipped)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    xs = (x - x.mean()) / (np.ptp(x) or 1)
    yy = y.copy()
    for _ in range(n_iter):
        c = np.polyfit(xs, yy, order)
        b = np.polyval(c, xs)
        new = np.minimum(yy, b)
        if np.allclose(new, yy):
            break
        yy = new
    return np.polyval(c, xs)


def baseline_ends(x, y, frac: float = 0.05) -> np.ndarray:
    """Straight line through the mean of the first and last ``frac`` of the points."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    k = max(1, int(len(x) * frac))
    x0, y0 = x[:k].mean(), y[:k].mean()
    x1, y1 = x[-k:].mean(), y[-k:].mean()
    return y0 + (y1 - y0) * (x - x0) / ((x1 - x0) or 1)


def baseline(x, y, method: str = "als", **kw) -> np.ndarray:
    if method == "als":
        return baseline_als(y, lam=kw.get("lam", 1e5), p=kw.get("p", 0.01))
    if method == "poly":
        return baseline_poly(x, y, order=kw.get("order", 2))
    if method in ("ends", "linear"):
        return baseline_ends(x, y)
    raise ValueError(f"unknown baseline '{method}' (als, poly or ends)")


def normalize(x, y, mode: str = "max") -> Tuple[np.ndarray, float]:
    """Returns (y scaled, divisor)."""
    y = np.asarray(y, float)
    if mode == "max":
        d = np.nanmax(np.abs(y))
    elif mode == "area":
        d = abs(_trapz(y, x))
    elif mode == "minmax":
        lo = np.nanmin(y)
        d = np.nanmax(y) - lo
        return (y - lo) / (d or 1), d
    else:
        raise ValueError(f"unknown normalisation '{mode}' (max, area or minmax)")
    return y / (d or 1), d


def _trapz(y, x):
    f = getattr(np, "trapezoid", None) or np.trapz
    return float(f(y, x))


def integrate(x, y, lo: float, hi: float) -> float:
    """Area under y between lo and hi (trapezoids, end points interpolated)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    o = np.argsort(x)
    x, y = x[o], y[o]
    lo, hi = min(lo, hi), max(lo, hi)
    m = (x > lo) & (x < hi)
    xs = np.concatenate([[lo], x[m], [hi]])
    ys = np.concatenate([[np.interp(lo, x, y)], y[m], [np.interp(hi, x, y)]])
    return _trapz(ys, xs)


# ───────────────────────────── peaks ─────────────────────────────
SQ = math.sqrt(math.log(2))
SHAPES = ("gauss", "lorentz", "voigt")


def gauss(x, h, c, w):
    return h * np.exp(-4 * math.log(2) * ((x - c) / w) ** 2)


def lorentz(x, h, c, w):
    return h / (1 + 4 * ((x - c) / w) ** 2)


def pvoigt(x, h, c, w, eta):
    return eta * lorentz(x, h, c, w) + (1 - eta) * gauss(x, h, c, w)


def peak_area(shape, h, w, eta=0.5):
    ag = h * w * math.sqrt(math.pi / (4 * math.log(2)))
    al = h * w * math.pi / 2
    return {"gauss": ag, "lorentz": al, "voigt": eta * al + (1 - eta) * ag}[shape]


@dataclass
class Peak:
    center: float
    height: float
    fwhm: float
    area: float
    center_err: float = float("nan")
    height_err: float = float("nan")
    fwhm_err: float = float("nan")
    area_err: float = float("nan")
    eta: Optional[float] = None
    eta_err: Optional[float] = None


def find_peaks(x, y, prominence: float = 0.05, max_peaks: int = 10, min_distance: Optional[float] = None) -> List[float]:
    """Peak positions (x) whose prominence exceeds ``prominence`` × the data range."""
    from scipy.signal import find_peaks as fp
    x, y = np.asarray(x, float), np.asarray(y, float)
    rng = float(np.nanmax(y) - np.nanmin(y)) or 1.0
    kw = {"prominence": prominence * rng}
    if min_distance:
        dx = np.median(np.abs(np.diff(x))) or 1
        kw["distance"] = max(1, int(min_distance / dx))
    idx, props = fp(y, **kw)
    order = np.argsort(props["prominences"])[::-1][:max_peaks]
    return sorted(float(x[i]) for i in idx[order])


def _guess_width(x, y, c):
    """FWHM estimate around x = c."""
    i = int(np.argmin(np.abs(x - c)))
    h = y[i]
    half = h / 2
    lo = i
    while lo > 0 and y[lo] > half:
        lo -= 1
    hi = i
    while hi < len(y) - 1 and y[hi] > half:
        hi += 1
    w = abs(x[hi] - x[lo])
    return w if w > 0 else 5 * float(np.median(np.abs(np.diff(x))) or 1)


@dataclass
class FitResult:
    shape: str
    peaks: List[Peak]
    background: List[float]                 # linear background a + b·x (fitted when requested)
    r2: float
    rmse: float
    model: np.ndarray = field(repr=False)          # on the analysed x (the whole range)
    components: List[np.ndarray] = field(repr=False)
    x_range: Tuple[float, float] = (float("nan"), float("nan"))   # x range the fit used


def fit_peaks(x, y, centers: Sequence[float], shape: str = "voigt", background: bool = True,
              fix_centers: bool = False, center_window: Optional[float] = None,
              fwhm_range: Optional[Tuple[float, float]] = None,
              fit_range: Optional[Tuple[float, float]] = None) -> FitResult:
    """Fit a sum of peaks (and a linear background) by least squares – also to deconvolve
    overlapping bands into components.

    ``center_window``: each centre may move at most this far from its starting position;
    ``fwhm_range``: limits for every width; ``fit_range``: fit only x in (lo, hi) (the model and the
    components are still returned on all of x).
    Errors are one standard deviation from the covariance matrix, scaled by the residual variance."""
    from scipy.optimize import curve_fit
    if shape not in SHAPES:
        raise ValueError(f"unknown peak shape '{shape}' (gauss, lorentz or voigt)")
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    o = np.argsort(x)
    x, y = x[o], y[o]
    x_all = x
    if fit_range is not None:
        lo_, hi_ = min(fit_range), max(fit_range)
        m = (x >= lo_) & (x <= hi_)
        if m.sum() < 5:
            raise ValueError(f"fewer than 5 points in the fit range {lo_:g}–{hi_:g}")
        x, y = x[m], y[m]
    if not len(centers):
        raise ValueError("no peaks to fit")
    if fwhm_range is not None and min(fwhm_range) >= max(fwhm_range):
        raise ValueError("the FWHM range must have its lower limit below the upper limit")
    span = float(np.ptp(x)) or 1.0
    dx = float(np.median(np.diff(x))) if len(x) > 1 else 1.0
    npar = 4 if shape == "voigt" else 3
    p0, lo, hi = [], [], []
    yr = float(np.ptp(y)) or 1.0
    wlo, whi = (dx * 0.5, span) if fwhm_range is None else (max(min(fwhm_range), 1e-12), max(fwhm_range))
    for c in centers:
        h = float(np.interp(c, x, y)) - (float(np.min(y)) if background else 0)
        w = min(_guess_width(x, y, c), span / 2, span / (2 * len(centers)) if len(centers) > 2 else span)
        w = float(np.clip(max(w, 2 * dx), wlo * 1.0001, whi * 0.9999))
        clo, chi = (c - 1e-9, c + 1e-9) if fix_centers else (x[0], x[-1])
        if center_window is not None and not fix_centers:
            clo, chi = max(x[0], c - abs(center_window)), min(x[-1], c + abs(center_window))
        p0 += [max(h, 1e-3 * yr), float(np.clip(c, clo, chi)), w]
        lo += [0, clo, wlo]
        hi += [10 * yr, chi, whi]
        if shape == "voigt":
            p0.append(0.5); lo.append(0.0); hi.append(1.0)
    if background:
        p0 += [float(np.min(y)), 0.0]
        lo += [-np.inf, -np.inf]
        hi += [np.inf, np.inf]
    xm = x.mean()

    def comps(xx, *p):
        out = []
        for k in range(len(centers)):
            q = p[k * npar:(k + 1) * npar]
            out.append(pvoigt(xx, *q) if shape == "voigt" else (gauss if shape == "gauss" else lorentz)(xx, *q))
        return out

    def model(xx, *p):
        m = np.sum(comps(xx, *p), axis=0)
        if background:
            m = m + p[-2] + p[-1] * (xx - xm)
        return m

    p0 = np.clip(p0, np.asarray(lo) + 1e-12, np.asarray(hi) - 1e-12)
    popt, pcov = curve_fit(model, x, y, p0=p0, bounds=(lo, hi), maxfev=20000)
    perr = np.sqrt(np.clip(np.diag(pcov), 0, None)) if np.all(np.isfinite(pcov)) else np.full(len(popt), np.nan)
    fit = model(x, *popt)
    res = y - fit
    ss = float(np.sum((y - y.mean()) ** 2)) or 1.0
    fit_all = model(x_all, *popt)
    peaks = []
    for k in range(len(centers)):
        q, e = popt[k * npar:(k + 1) * npar], perr[k * npar:(k + 1) * npar]
        h, c, w = q[:3]
        eta = float(q[3]) if shape == "voigt" else None
        a = peak_area(shape, h, w, eta if eta is not None else 0.5)
        # area error: first-order propagation from height and width (their covariance ignored)
        ae = a * math.sqrt((e[0] / h) ** 2 + (e[2] / w) ** 2) if h > 0 and w > 0 else float("nan")
        peaks.append(Peak(center=float(c), height=float(h), fwhm=float(w), area=float(a),
                          center_err=float(e[1]), height_err=float(e[0]), fwhm_err=float(e[2]), area_err=float(ae),
                          eta=eta, eta_err=float(e[3]) if shape == "voigt" else None))
    bg = [float(popt[-2] - popt[-1] * xm), float(popt[-1])] if background else [0.0, 0.0]
    return FitResult(shape=shape, peaks=peaks, background=bg, r2=1 - float(np.sum(res ** 2)) / ss,
                     rmse=float(np.sqrt(np.mean(res ** 2))), model=fit_all, components=comps(x_all, *popt),
                     x_range=(float(x[0]), float(x[-1])))


def find_shoulders(x, y, max_peaks: int = 10, prominence: float = 0.05, window: Optional[int] = None) -> List[float]:
    """Peak and shoulder positions from minima of the smoothed second derivative.

    Overlapping bands often show up only as shoulders, without a maximum of their own; the second
    derivative still has a minimum at each band centre. ``prominence`` is relative to the range of
    −y″; positions where the signal itself is below 10 % of its range are ignored. ``window``
    (points) sets the smoothing of y″; the default, 1/15 of the points, suits bands wider than that."""
    from scipy.signal import find_peaks as fp
    from scipy.signal import savgol_filter
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(y)
    if n < 9:
        return []
    dx = float(np.mean(np.diff(x))) or 1.0
    win = window or max(9, int(n / 15) | 1)       # strong smoothing: y″ amplifies noise
    win = min(win | 1, n - 1 if n % 2 == 0 else n)
    d2 = -savgol_filter(y, win, 3, deriv=2, delta=dx)
    rng = float(np.nanmax(d2) - np.nanmin(d2)) or 1.0
    idx, props = fp(d2, prominence=prominence * rng, height=0)
    yr = float(np.nanmax(y) - np.nanmin(y)) or 1.0
    keep = [(props["prominences"][k], i) for k, i in enumerate(idx) if y[i] - np.nanmin(y) > 0.1 * yr]
    keep.sort(reverse=True)
    return sorted(float(x[i]) for _, i in keep[:max_peaks])


def component_positions(x, y, n: int, found: Sequence[float], fit_range: Optional[Tuple[float, float]] = None) -> List[float]:
    """Exactly ``n`` starting positions: the strongest of ``found`` first, then the middle of the
    widest gaps (and edges) of the range until there are ``n``."""
    lo, hi = (float(np.min(x)), float(np.max(x))) if fit_range is None else (min(fit_range), max(fit_range))
    pos = [c for c in found if lo <= c <= hi][:n]
    while len(pos) < n:
        pts = sorted([lo] + pos + [hi])
        gaps = [(b - a, (a + b) / 2) for a, b in zip(pts[:-1], pts[1:])]
        pos.append(max(gaps)[1])
    return sorted(pos)


# ───────────────────────────── data files ─────────────────────────────
def load_series(path: str, x: Optional[str] = None, y: Optional[str] = None,
                series: Optional[str] = None) -> List[Tuple[str, np.ndarray, np.ndarray]]:
    """[(name, x, y)] from a table: ReSrijan's long format (series,x,y,…) or columns."""
    from .plot.engine import read_table
    tab = read_table(path)
    out = []
    if "series" in tab and "x" in tab and "y" in tab and x in (None, "x") and y in (None, "y"):
        names = list(dict.fromkeys(str(v) for v in tab["series"]))
        for n in names:
            if series and n != series:
                continue
            m = np.array([str(v) == n for v in tab["series"]])
            out.append((n, tab["x"][m].astype(float), tab["y"][m].astype(float)))
    else:
        keys = [k for k in tab if tab[k].dtype != object]
        if not keys:
            raise ValueError(f"{path}: no numeric columns")
        xk = x or keys[0]
        if xk not in tab:
            raise ValueError(f"{path}: no column '{xk}' (columns: {', '.join(tab)})")
        yks = [v.strip() for v in y.split(",")] if y else [k for k in keys if k != xk]
        for k in yks:
            if k not in tab:
                raise ValueError(f"{path}: no column '{k}' (columns: {', '.join(tab)})")
            if series and k != series:
                continue
            out.append((k, np.asarray(tab[xk], float), np.asarray(tab[k], float)))
    if not out:
        raise ValueError(f"{path}: no series to analyse" + (f" named '{series}'" if series else ""))
    return out


@dataclass
class Analysis:
    name: str
    x: np.ndarray
    y_raw: np.ndarray
    y: np.ndarray                       # after smoothing, baseline subtraction and normalisation
    baseline: Optional[np.ndarray]
    fit: Optional[FitResult]
    areas: List[Dict]
    steps: List[str]
    x_unit: Optional[str] = None


def analyze(x, y, name: str = "y", convert: Optional[Tuple[str, str]] = None, jacobian: bool = False,
            crop: Optional[Tuple[float, float]] = None, smooth_opt: Optional[Tuple[str, int, int]] = None,
            baseline_opt: Optional[Tuple[str, dict]] = None, normalize_opt: Optional[str] = None,
            peaks: Optional[Sequence[float]] = None, auto_peaks: bool = False, prominence: float = 0.05,
            max_peaks: int = 10, shape: str = "voigt", fit_background: Optional[bool] = None,
            areas: Sequence[Tuple[float, float]] = (), peak_method: Optional[str] = None,
            n_components: Optional[int] = None, center_window: Optional[float] = None,
            fwhm_range: Optional[Tuple[float, float]] = None,
            fit_range: Optional[Tuple[float, float]] = None) -> Analysis:
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    steps, unit = [], None
    if convert:
        frm, to = convert
        x_new = convert_x(x, frm, to)
        if jacobian:
            y = convert_y_jacobian(x, y, frm, to)
        x = x_new
        unit = _unit(to)
        steps.append(f"x converted from {_unit(frm)} to {unit}" + (" (intensity × |dλ/dE|)" if jacobian else ""))
    o = np.argsort(x, kind="stable")
    x, y = x[o], y[o]
    if crop:
        lo, hi = min(crop), max(crop)
        m = (x >= lo) & (x <= hi)
        if m.sum() < 5:
            raise ValueError(f"fewer than 5 points between {lo:g} and {hi:g}")
        x, y = x[m], y[m]
        steps.append(f"cropped to {lo:g}–{hi:g}")
    y_raw = y.copy()
    if smooth_opt:
        meth, win, order = smooth_opt
        y = smooth(y, meth, win, order)
        steps.append(f"smoothed ({meth}, window {win}" + (f", order {order})" if meth == "savgol" else ")"))
    base = None
    if baseline_opt:
        meth, kw = baseline_opt
        base = baseline(x, y, meth, **kw)
        y = y - base
        steps.append(f"baseline subtracted ({meth}" + "".join(f", {k} {v:g}" for k, v in kw.items()) + ")")
    if normalize_opt:
        y, d = normalize(x, y, normalize_opt)
        if base is not None:
            base = base / (d or 1)
        steps.append(f"normalised ({normalize_opt}, divided by {d:.6g})")
    centers = list(peaks or [])
    xs, ys = x, y
    if fit_range is not None:
        m = (x >= min(fit_range)) & (x <= max(fit_range))
        xs, ys = x[m], y[m]
    if auto_peaks or n_components:
        method = peak_method or ("shoulders" if n_components else "prominence")
        if method == "shoulders":
            found = find_shoulders(xs, ys, max_peaks=max(max_peaks, n_components or 0), prominence=prominence)
            how = "peaks and shoulders (second derivative)"
        else:
            found = find_peaks(xs, ys, prominence=prominence, max_peaks=max(max_peaks, n_components or 0))
            how = f"peak(s) (prominence > {prominence:g} of the range)"
        if n_components:
            ordered = sorted(found, key=lambda c: -float(np.interp(c, xs, ys)))
            centers = component_positions(xs, ys, int(n_components), ordered, fit_range)
            steps.append(f"{len(found)} {how} found; {n_components} component(s) placed")
        else:
            centers = sorted(set(centers) | set(found))
            steps.append(f"{len(found)} {how} found")
    fit = None
    if centers:
        fit = fit_peaks(x, y, centers, shape=shape, background=True if fit_background is None else fit_background,
                        center_window=center_window, fwhm_range=fwhm_range, fit_range=fit_range)
        rng_txt = f" over {fit.x_range[0]:g}–{fit.x_range[1]:g}" if fit_range is not None else ""
        steps.append(f"{len(centers)} {shape} peak(s) fitted{rng_txt}, R² = {fit.r2:.4f}")
    ar = []
    for lo, hi in areas:
        ar.append({"from": float(lo), "to": float(hi), "area": integrate(x, y, lo, hi)})
    if ar:
        steps.append(f"{len(ar)} area(s) integrated")
    return Analysis(name=name, x=x, y_raw=y_raw, y=y, baseline=base, fit=fit, areas=ar, steps=steps, x_unit=unit)


def _fmt(v, e=None):
    if v is None or not np.isfinite(v):
        return ""
    if e is None or not np.isfinite(e) or e <= 0:
        return f"{v:.6g}"
    d = max(0, -int(math.floor(math.log10(e))) + 1)
    return f"{v:.{d}f} ± {e:.{d}f}" if d < 10 else f"{v:.6g} ± {e:.2g}"


def peak_table(a: Analysis) -> List[Dict]:
    if not a.fit:
        return []
    rows = []
    total = sum(p.area for p in a.fit.peaks) or float("nan")
    for k, p in enumerate(a.fit.peaks, 1):
        r = {"peak": k, "center": p.center, "center_err": p.center_err, "height": p.height, "height_err": p.height_err,
             "fwhm": p.fwhm, "fwhm_err": p.fwhm_err, "area": p.area, "area_err": p.area_err,
             "area_pct": 100 * p.area / total, "area_pct_err": 100 * p.area_err / total}
        if p.eta is not None:
            r["eta"], r["eta_err"] = p.eta, p.eta_err
        rows.append(r)
    return rows


def summary_lines(a: Analysis) -> List[str]:
    out = [f"{a.name}: " + "; ".join(a.steps) if a.steps else f"{a.name}: no processing"]
    if a.fit:
        total = sum(p.area for p in a.fit.peaks) or float("nan")
        for k, p in enumerate(a.fit.peaks, 1):
            s = (f"  peak {k}: centre {_fmt(p.center, p.center_err)}, FWHM {_fmt(p.fwhm, p.fwhm_err)}, "
                 f"height {_fmt(p.height, p.height_err)}, area {_fmt(p.area, p.area_err)} "
                 f"({_fmt(100 * p.area / total, 100 * p.area_err / total)} %)")
            if p.eta is not None:
                s += f", Lorentzian fraction {_fmt(p.eta, p.eta_err)}"
            out.append(s)
    for r in a.areas:
        out.append(f"  area {r['from']:g}–{r['to']:g}: {r['area']:.6g}")
    return out


def write(a: Analysis, base: str, template: str = "natchem", formats: Sequence[str] = ("pdf", "svg", "png"),
          width="single", xlabel: Optional[str] = None, ylabel: Optional[str] = None) -> Dict[str, object]:
    """``base``_processed.csv, _peaks.csv, _analysis.json and a figure with the fit and residuals."""
    import matplotlib.pyplot as plt
    from .plot.engine import save
    os.makedirs(os.path.dirname(os.path.abspath(base)), exist_ok=True)
    files: Dict[str, object] = {}
    cols = {"x": a.x, "y_raw": a.y_raw}
    if a.baseline is not None:
        cols["baseline"] = a.baseline
    cols["y"] = a.y
    if a.fit:
        cols["fit"] = a.fit.model
        for k, c in enumerate(a.fit.components, 1):
            cols[f"peak{k}"] = c
        r_ = a.y - a.fit.model
        lo_, hi_ = a.fit.x_range
        cols["residual"] = np.where((a.x >= lo_) & (a.x <= hi_), r_, np.nan)
    with open(base + "_processed.csv", "w") as fh:
        fh.write(",".join(cols) + "\n")
        for i in range(len(a.x)):
            fh.write(",".join(f"{v[i]:.10g}" for v in cols.values()) + "\n")
    files["processed"] = base + "_processed.csv"
    rows = peak_table(a)
    if rows:
        keys = list(rows[0])
        with open(base + "_peaks.csv", "w") as fh:
            fh.write(",".join(keys) + "\n")
            for r in rows:
                fh.write(",".join(f"{r[k]:.8g}" if isinstance(r[k], float) else str(r[k]) for k in keys) + "\n")
        files["peaks"] = base + "_peaks.csv"
    meta = {"name": a.name, "steps": a.steps, "x_unit": a.x_unit, "areas": a.areas, "peaks": rows,
            "fit": None if not a.fit else {"shape": a.fit.shape, "r2": a.fit.r2, "rmse": a.fit.rmse,
                                           "background": {"intercept": a.fit.background[0],
                                                          "slope": a.fit.background[1]}}}
    Path(base + "_analysis.json").write_text(json.dumps(meta, indent=1, default=float))
    files["json"] = base + "_analysis.json"
    fig = analysis_figure(a, template=template, width=width, xlabel=xlabel, ylabel=ylabel)
    files["figure"] = save(fig, base + "_analysis", formats)
    plt.close(fig)
    return files


COMPONENT_COLORS = ["#0072B2", "#009E73", "#CC79A7", "#56B4E9", "#E69F00", "#7F7F7F"]


def analysis_figure(a: Analysis, template: str = "natchem", width="single", xlabel: Optional[str] = None,
                    ylabel: Optional[str] = None, style: Optional[dict] = None):
    """Journal-style figure: data, fit and peak components, with residuals on a shared x axis below."""
    import matplotlib.pyplot as plt
    from .plot import templates as T
    from .plot.engine import MM, _styled, draw_panel
    tpl = _styled(T.get(template), style)
    xl = xlabel or (UNIT_LABEL.get(a.x_unit) if a.x_unit else None) or "x"
    yl = ylabel or ("Normalised intensity" if any(st.startswith("normalised") for st in a.steps) else "Intensity")
    series = [{"x": a.x, "y": a.y, "label": "data", "color": "0.15",
               "kind": "markers" if len(a.x) < 60 else "line", "marker": "o"}]
    if a.fit:
        bg = a.fit.background[0] + a.fit.background[1] * a.x
        for k, c in enumerate(a.fit.components, 1):
            series.append({"x": a.x, "y": c + bg, "label": f"peak {k}" if len(a.fit.components) > 1 else "peak",
                           "color": COMPONENT_COLORS[(k - 1) % len(COMPONENT_COLORS)],
                           "linestyle": (0, (3, 1.5)), "lw": 0.7})
        series.insert(1, {"x": a.x, "y": a.fit.model, "label": "fit", "color": "#D55E00", "lw": 1.0})
    W = tpl.width_mm(width)
    H = W * (0.86 if a.fit else 0.75)
    with plt.rc_context(tpl.rc()):
        fig = plt.figure(figsize=(W * MM, H * MM), layout="constrained")
        fig.get_layout_engine().set(w_pad=1.0 * MM, h_pad=1.0 * MM, hspace=0.0)
        if a.fit:
            gs = fig.add_gridspec(2, 1, height_ratios=[3.2, 1])
            ax = fig.add_subplot(gs[0])
            axr = fig.add_subplot(gs[1], sharex=ax)
        else:
            ax, axr = fig.add_subplot(111), None
        lim = [float(a.x[0]), float(a.x[-1])]
        draw_panel(ax, {"type": "line", "series": series, "ylabel": yl, "xlabel": None if axr else xl,
                        "legend": "best", "sort": False, "xlim": lim}, tpl)
        if axr is not None:
            ax.tick_params(axis="x", which="both", labelbottom=False)
            lo_, hi_ = a.fit.x_range
            inside = (a.x >= lo_) & (a.x <= hi_)
            if not inside.all():
                for a_ in (ax, axr):
                    a_.axvspan(lo_, hi_, color="0.5", alpha=0.07, lw=0, zorder=0)
            draw_panel(axr, {"type": "line", "series": [{"x": a.x[inside], "y": (a.y - a.fit.model)[inside],
                                                         "color": "0.3", "lw": 0.6}],
                             "xlabel": xl, "ylabel": "Resid.", "legend": False, "sort": False, "hlines": [0.0],
                             "xlim": lim}, tpl)
            axr.yaxis.set_major_locator(plt.MaxNLocator(3, symmetric=True))
            fig.align_ylabels([ax, axr])
    fig._resrijan_template = tpl
    return fig


def parse_ranges(s: Optional[str]) -> List[Tuple[float, float]]:
    """'400:500,600:700' → [(400, 500), (600, 700)]."""
    out = []
    for part in (s or "").split(","):
        if part.strip():
            a, b = part.split(":")
            out.append((float(a), float(b)))
    return out


def _as_dict(a: Analysis) -> dict:          # pragma: no cover - debugging helper
    d = asdict(a)
    return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in d.items()}
