"""General non-linear curve fitting with user expressions.

A model is a formula in ``x`` such as ``A*exp(-x/tau) + C`` or ``6*D*x``. Every other name in it
(not a function or a constant) is a fitted parameter. Each parameter can have a starting value,
lower and upper bounds, or be fixed. Fits use bounded least squares (trust-region reflective) from
several starting points, and report standard errors from the covariance matrix.

Derived quantities (e.g. the mean relaxation time of a stretched exponential,
``tau/beta*gamma(1/beta)``) get errors by linear propagation through the covariance matrix.

Expressions are parsed and checked before use: only arithmetic, numbers, ``x``, the parameters,
the functions in :data:`FUNCTIONS` and the constants in :data:`CONSTANTS` are allowed.
"""
from __future__ import annotations

import ast
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import special

FUNCTIONS = {
    "exp": np.exp, "log": np.log, "ln": np.log, "log10": np.log10, "log2": np.log2, "sqrt": np.sqrt,
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "arcsin": np.arcsin, "arccos": np.arccos, "arctan": np.arctan,
    "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh, "abs": np.abs, "erf": special.erf, "erfc": special.erfc,
    "gamma": special.gamma, "heaviside": lambda v: np.heaviside(v, 0.5), "sign": np.sign,
    "min": np.minimum, "max": np.maximum,
}
CONSTANTS = {"pi": math.pi, "e": math.e, "kB": 1.380649e-23, "R": 8.314462618, "NA": 6.02214076e23,
             "h": 6.62607015e-34, "hbar": 1.054571817e-34, "c0": 299792458.0, "kB_eV": 8.617333262e-5}
_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Mod, ast.FloorDiv)

# ───────────────────────────── presets ─────────────────────────────
# name: (expression, description, derived quantities)
PRESETS: Dict[str, Tuple[str, str, Dict[str, str]]] = {
    "exp1": ("A*exp(-x/tau) + C", "single exponential decay", {}),
    "exp2": ("A1*exp(-x/tau1) + A2*exp(-x/tau2) + C", "two exponentials",
             {"tau_avg": "(A1*tau1 + A2*tau2)/(A1 + A2)"}),
    "exp3": ("A1*exp(-x/tau1) + A2*exp(-x/tau2) + A3*exp(-x/tau3) + C", "three exponentials",
             {"tau_avg": "(A1*tau1 + A2*tau2 + A3*tau3)/(A1 + A2 + A3)"}),
    "kww": ("A*exp(-(x/tau)**beta) + C", "stretched exponential (KWW)", {"tau_avg": "tau/beta*gamma(1/beta)"}),
    "exp_kww": ("A1*exp(-x/tau1) + A2*exp(-(x/tau2)**beta) + C", "fast exponential + stretched exponential",
                {"tau2_avg": "tau2/beta*gamma(1/beta)",
                 "tau_avg": "(A1*tau1 + A2*tau2/beta*gamma(1/beta))/(A1 + A2)"}),
    "damped_cos": ("A*exp(-x/tau)*cos(w*x + phi) + C", "damped oscillation", {"period": "2*pi/w"}),
    "msd3d": ("6*D*x + c", "MSD, 3-D diffusion (slope 6D)", {}),
    "msd2d": ("4*D*x + c", "MSD, 2-D diffusion (slope 4D)", {}),
    "msd1d": ("2*D*x + c", "MSD, 1-D diffusion (slope 2D)", {}),
    "msd_anomalous": ("6*K*x**alpha", "MSD, anomalous diffusion (3-D)", {}),
    "msd_ballistic": ("6*D*x*(1 - exp(-x/tau)) ", "MSD with a ballistic start (3-D)", {}),
    "linear": ("a*x + b", "straight line", {}),
    "quadratic": ("a*x**2 + b*x + c", "parabola", {}),
    "power": ("A*x**n", "power law", {}),
    "arrhenius": ("A*exp(-Ea/(R*x))", "Arrhenius, Ea in J/mol (x = T in K)", {"Ea_kJ": "Ea/1000"}),
    "vft": ("A*exp(B/(x - T0))", "Vogel–Fulcher–Tammann", {}),
    "gaussian": ("A*exp(-(x - x0)**2/(2*s**2)) + C", "Gaussian", {"fwhm": "2*sqrt(2*log(2))*abs(s)"}),
    "lorentzian": ("A/(1 + ((x - x0)/g)**2) + C", "Lorentzian", {"fwhm": "2*abs(g)"}),
    "logistic": ("A/(1 + exp(-(x - x0)/k)) + C", "sigmoid", {}),
    "hill": ("A*x**n/(K**n + x**n)", "Hill / binding curve", {}),
}
DEFAULT_BOUNDS = {"beta": (0.0, 1.0), "alpha": (0.0, 2.0)}


class ExpressionError(ValueError):
    pass


def parse_model(expr: str, var: str = "x") -> Tuple[object, List[str]]:
    """Check ``expr`` and return (compiled code, parameter names in order of appearance)."""
    expr = expr.strip().replace("^", "**")
    if not expr:
        raise ExpressionError("the model is empty")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"cannot read the model: {exc.msg} at character {exc.offset}") from None
    names: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ExpressionError(f"'{type(node).__name__}' is not allowed in a model")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                fn = getattr(node.func, "id", "?")
                raise ExpressionError(f"unknown function '{fn}' (allowed: {', '.join(sorted(FUNCTIONS))})")
            if node.keywords:
                raise ExpressionError("keyword arguments are not allowed")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ExpressionError("only numbers are allowed as constants")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in FUNCTIONS and node.id not in CONSTANTS and node.id != var:
            if node.id.startswith("_"):
                raise ExpressionError(f"names cannot start with '_' ({node.id})")
            if node.id not in names:
                names.append(node.id)
    # order of appearance in the text, not in the tree walk
    names.sort(key=lambda n: _first_pos(expr, n))
    return compile(tree, "<model>", "eval"), names


def _first_pos(expr: str, name: str) -> int:
    import re
    m = re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", expr)
    return m.start() if m else 10 ** 6


def evaluate(code, names: Sequence[str], params: Sequence[float], x, var: str = "x"):
    env = {"__builtins__": {}}
    env.update(FUNCTIONS)
    env.update(CONSTANTS)
    env.update(dict(zip(names, params)))
    env[var] = x
    with np.errstate(all="ignore"):
        v = eval(code, env)  # noqa: S307 – the tree was checked by parse_model
    return np.broadcast_to(np.asarray(v, float), np.shape(x)).astype(float)


# ───────────────────────────── fitting ─────────────────────────────
@dataclass
class Param:
    name: str
    value: Optional[float] = None       # starting value (None: automatic)
    lo: float = -np.inf
    hi: float = np.inf
    fixed: bool = False


@dataclass
class FitOutcome:
    expr: str
    names: List[str]
    values: Dict[str, float]
    errors: Dict[str, float]
    fixed: List[str]
    derived: Dict[str, Tuple[float, float]]
    r2: float
    chi2_red: float
    rmse: float
    n: int
    dof: int
    x: np.ndarray = field(repr=False)
    y: np.ndarray = field(repr=False)
    fit: np.ndarray = field(repr=False)
    x_range: Tuple[float, float] = (np.nan, np.nan)
    at_bounds: List[str] = field(default_factory=list)
    covariance: Optional[np.ndarray] = field(default=None, repr=False)
    message: str = ""


def _guess(name: str, x, y) -> float:
    """A sensible starting value from the parameter's name and the data."""
    n = name.lower()
    xs = float(np.nanmax(x) - np.nanmin(x)) or 1.0
    yr = float(np.nanmax(y) - np.nanmin(y)) or 1.0
    digits = "".join(ch for ch in n if ch.isdigit())
    k = int(digits) if digits else 1
    if n.startswith(("tau", "t0", "tc", "lifetime")) or n in ("t", "k_inv"):
        return xs * (0.05, 0.3, 1.0, 3.0)[min(k - 1, 3)]
    if n in ("beta",):
        return 0.6
    if n in ("alpha", "n"):
        return 1.0
    if n in ("d", "k") and len(x) > 2:            # MSD slope / 6 (3-D) as the default scale
        with np.errstate(all="ignore"):
            s = np.polyfit(x, y, 1)[0]
        return abs(s) / 6 or 1.0
    if n.startswith(("a", "amp", "y0", "b")) and n not in ("alpha",):
        return yr / max(k, 1) if n.startswith(("a", "amp")) else float(np.nanmin(y))
    if n in ("c", "offset", "y_inf", "baseline"):
        return float(np.nanmean(y[-max(1, len(y) // 10):]))
    if n in ("x0", "xc", "mu", "center", "centre"):
        return float(x[np.nanargmax(y)])
    if n in ("s", "sigma", "g", "w", "width", "fwhm"):
        return xs / 10
    if n == "ea":
        return 30000.0
    if n == "t0":
        return float(np.nanmin(x)) * 0.5
    return 1.0


def _starts(params: List[Param], x, y, n_starts: int, rng) -> List[np.ndarray]:
    free = [p for p in params if not p.fixed]
    base = []
    for p in free:
        v = p.value if p.value is not None else _guess(p.name, x, y)
        if not np.isfinite(v):
            v = 1.0
        lo, hi = p.lo, p.hi
        if v <= lo or v >= hi:
            v = (lo + hi) / 2 if np.isfinite(lo) and np.isfinite(hi) else (lo + abs(lo) * 0.1 + 1e-3 if np.isfinite(lo) else hi - abs(hi) * 0.1 - 1e-3)
        base.append(v)
    starts = [np.array(base, float)]
    for _ in range(n_starts - 1):
        s = []
        for p, v in zip(free, base):
            if np.isfinite(p.lo) and np.isfinite(p.hi):
                if p.lo > 0 and p.hi / p.lo > 100:
                    s.append(float(np.exp(rng.uniform(np.log(p.lo), np.log(p.hi)))))
                else:
                    s.append(float(rng.uniform(p.lo, p.hi)))
            else:
                f = float(np.exp(rng.normal(0, 1.2)))
                cand = v * f if v != 0 else rng.normal(0, 1)
                s.append(float(np.clip(cand, p.lo + 1e-12 * (1 + abs(p.lo)) if np.isfinite(p.lo) else -np.inf,
                                       p.hi - 1e-12 * (1 + abs(p.hi)) if np.isfinite(p.hi) else np.inf)))
        starts.append(np.array(s, float))
    return starts


def fit(x, y, expr: str, params: Optional[Sequence[Param]] = None, x_range: Optional[Tuple[float, float]] = None,
        sigma=None, derived: Optional[Dict[str, str]] = None, n_starts: int = 12, seed: int = 0,
        absolute_sigma: bool = False) -> FitOutcome:
    """Fit ``expr`` to (x, y). ``params`` sets starting values, bounds and fixed values by name;
    parameters not listed start from automatic guesses without bounds (presets add sensible bounds)."""
    from scipy.optimize import least_squares
    code, names = parse_model(expr)
    if not names:
        raise ExpressionError("the model has no parameters to fit")
    given = {p.name: p for p in (params or [])}
    unknown = [n for n in given if n not in names]
    if unknown:
        raise ExpressionError(f"not in the model: {', '.join(unknown)} (parameters: {', '.join(names)})")
    plist = []
    for n in names:
        p = given.get(n) or Param(n)
        if n not in given and n in DEFAULT_BOUNDS:
            p.lo, p.hi = DEFAULT_BOUNDS[n]
        if p.fixed and p.value is None:
            raise ExpressionError(f"'{n}' is fixed but has no value")
        if p.lo >= p.hi:
            raise ExpressionError(f"'{n}': the lower bound must be below the upper bound")
        plist.append(p)
    x, y = np.asarray(x, float), np.asarray(y, float)
    w = None if sigma is None else np.asarray(sigma, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if w is not None:
        ok &= np.isfinite(w) & (w > 0)
    if x_range is not None:
        lo, hi = min(x_range), max(x_range)
        ok &= (x >= lo) & (x <= hi)
    xs, ys = x[ok], y[ok]
    ws = w[ok] if w is not None else None
    free = [i for i, p in enumerate(plist) if not p.fixed]
    if len(xs) <= len(free):
        raise ValueError(f"{len(xs)} points for {len(free)} free parameters – widen the range")
    full = np.array([p.value if p.fixed else np.nan for p in plist], float)

    def model(pf, xx):
        q = full.copy()
        q[free] = pf
        return evaluate(code, names, q, xx)

    def resid(pf):
        r = model(pf, xs) - ys
        if ws is not None:
            r = r / ws
        r[~np.isfinite(r)] = 1e30
        return r

    lb = np.array([plist[i].lo for i in free])
    ub = np.array([plist[i].hi for i in free])
    rng = np.random.default_rng(seed)
    best = None
    for p0 in _starts(plist, xs, ys, max(1, n_starts), rng):
        with np.errstate(invalid="ignore"):
            p0 = np.clip(p0, np.where(np.isfinite(lb), lb + 1e-12 * (1 + np.abs(lb)), -np.inf),
                         np.where(np.isfinite(ub), ub - 1e-12 * (1 + np.abs(ub)), np.inf))
        p0 = np.where(np.isfinite(p0), p0, 1.0)
        try:
            r = least_squares(resid, p0, bounds=(lb, ub), method="trf", x_scale="jac", max_nfev=4000)
        except (ValueError, FloatingPointError):
            continue
        if best is None or r.cost < best.cost:
            best = r
    if best is None or not np.isfinite(best.cost) or best.cost >= 1e50:
        raise ValueError("the fit failed: the model gives no finite values for these data – check the "
                         "expression, the starting values and the bounds")
    n, dof = len(xs), max(1, len(xs) - len(free))
    J = best.jac
    res = resid(best.x)
    chi2 = float(np.sum(res ** 2))
    chi2_red = chi2 / dof
    try:
        cov = np.linalg.pinv(J.T @ J)
        if not (absolute_sigma and ws is not None):
            cov = cov * chi2_red
    except np.linalg.LinAlgError:
        cov = np.full((len(free), len(free)), np.nan)
    errs = np.sqrt(np.clip(np.diag(cov), 0, None))
    values, errors = {}, {}
    q = full.copy()
    q[free] = best.x
    for i, p in enumerate(plist):
        values[p.name] = float(q[i])
        errors[p.name] = float(errs[free.index(i)]) if i in free else 0.0
    at_b = [plist[i].name for k, i in enumerate(free)
            if (np.isfinite(lb[k]) and abs(best.x[k] - lb[k]) <= 1e-6 * (1 + abs(lb[k])))
            or (np.isfinite(ub[k]) and abs(best.x[k] - ub[k]) <= 1e-6 * (1 + abs(ub[k])))]
    yfit = model(best.x, xs)
    ss_tot = float(np.sum((ys - ys.mean()) ** 2)) or 1.0
    r2 = 1 - float(np.sum((ys - yfit) ** 2)) / ss_tot
    full_cov = np.zeros((len(plist), len(plist)))
    for a, i in enumerate(free):
        for b, j in enumerate(free):
            full_cov[i, j] = cov[a, b]
    out = FitOutcome(expr=expr, names=names, values=values, errors=errors, fixed=[p.name for p in plist if p.fixed],
                     derived={}, r2=r2, chi2_red=chi2_red, rmse=float(np.sqrt(np.mean((ys - yfit) ** 2))), n=n,
                     dof=dof, x=xs, y=ys, fit=yfit, x_range=(float(xs.min()), float(xs.max())), at_bounds=at_b,
                     covariance=full_cov, message=best.message)
    _order_components(out)
    if derived:
        q = np.array([out.values[n] for n in names])
        out.derived = derived_values(derived, names, q, out.covariance)
    return out


def _order_components(r: FitOutcome):
    """Sums of exponentials (A1, tau1, A2, tau2 …) are reported with the fastest component first."""
    import re
    idx = sorted({int(m.group(1)) for n in r.names for m in [re.fullmatch(r"tau(\d)", n)] if m})
    if len(idx) < 2 or not all(f"A{i}" in r.names for i in idx) or any(f"tau{i}" in r.fixed or f"A{i}" in r.fixed for i in idx):
        return
    if "beta" in r.names:                      # exponential + stretched: the components are not interchangeable
        return
    order = sorted(idx, key=lambda i: r.values[f"tau{i}"])
    if order == idx:
        return
    perm = list(range(len(r.names)))
    for new, old in zip(idx, order):
        for p in ("A", "tau"):
            perm[r.names.index(f"{p}{new}")] = r.names.index(f"{p}{old}")
    vals = [r.values[r.names[j]] for j in perm]
    errs = [r.errors[r.names[j]] for j in perm]
    r.values = dict(zip(r.names, vals))
    r.errors = dict(zip(r.names, errs))
    r.at_bounds = [r.names[perm.index(r.names.index(n))] for n in r.at_bounds]
    if r.covariance is not None:
        r.covariance = r.covariance[np.ix_(perm, perm)]


def derived_values(derived: Dict[str, str], names: List[str], values, cov) -> Dict[str, Tuple[float, float]]:
    """Value and propagated standard error of each derived expression of the parameters."""
    out = {}
    q = np.asarray(values, float)
    for key, ex in derived.items():
        code, used = parse_model(ex, var="__none__")
        bad = [u for u in used if u not in names]
        if bad:
            raise ExpressionError(f"derived '{key}': unknown name(s) {', '.join(bad)}")

        def f(v):
            return float(evaluate(code, names, v, np.float64(0.0), var="__none__"))
        v0 = f(q)
        g = np.zeros(len(q))
        for i in range(len(q)):
            h = 1e-6 * (abs(q[i]) + 1e-12) or 1e-9
            qp, qm = q.copy(), q.copy()
            qp[i] += h
            qm[i] -= h
            g[i] = (f(qp) - f(qm)) / (2 * h)
        var = float(g @ cov @ g)
        out[key] = (v0, math.sqrt(var) if var >= 0 and np.isfinite(var) else float("nan"))
    return out


# ───────────────────────────── text options ─────────────────────────────
def parse_params(p0: Optional[str] = None, bounds: Optional[str] = None, fix: Optional[str] = None) -> List[Param]:
    """'A=1,tau=10' · 'tau=0:1e4,beta=0:1' (empty side = unbounded, e.g. 'C=:0') · 'C=0'."""
    ps: Dict[str, Param] = {}

    def get(n):
        n = n.strip()
        if not n.isidentifier():
            raise ExpressionError(f"'{n}' is not a parameter name")
        return ps.setdefault(n, Param(n))
    for part in _items(p0):
        n, v = _kv(part, "--p0")
        get(n).value = _num(v, f"--p0 {n}")
    for part in _items(bounds):
        n, v = _kv(part, "--bounds")
        if ":" not in v:
            raise ExpressionError(f"--bounds {n}: expected LO:HI (either side may be empty)")
        lo, hi = v.split(":", 1)
        p = get(n)
        p.lo = _num(lo, f"--bounds {n}") if lo.strip() else -np.inf
        p.hi = _num(hi, f"--bounds {n}") if hi.strip() else np.inf
    for part in _items(fix):
        n, v = _kv(part, "--fix")
        p = get(n)
        p.value = _num(v, f"--fix {n}")
        p.fixed = True
    return list(ps.values())


def parse_derived(s: Optional[str]) -> Dict[str, str]:
    """'tau_avg=tau/beta*gamma(1/beta); D_um=D*1e12' → {name: expression} (';' separates items)."""
    out = {}
    for part in (s or "").split(";"):
        if part.strip():
            n, v = _kv(part, "--derived")
            if not n.isidentifier():
                raise ExpressionError(f"--derived: '{n}' is not a valid name")
            parse_model(v, var="__none__")
            out[n] = v.strip()
    return out


def _items(s):
    return [t for t in (s or "").split(",") if t.strip()]


def _kv(part, what):
    if "=" not in part:
        raise ExpressionError(f"{what}: expected NAME=VALUE, got '{part.strip()}'")
    n, v = part.split("=", 1)
    return n.strip(), v.strip()


def _num(v, what):
    try:
        return float(v)
    except ValueError:
        raise ExpressionError(f"{what}: '{v}' is not a number") from None


def model_for(model: str) -> Tuple[str, Dict[str, str]]:
    """A preset name or an expression → (expression, preset's derived quantities)."""
    key = model.strip()
    if key in PRESETS:
        e, _, d = PRESETS[key]
        return e, dict(d)
    return key, {}


def preset_bounds(model: str) -> List[Param]:
    """Sensible bounds for presets: amplitudes and times positive, β in (0, 1], …"""
    if model.strip() not in PRESETS:
        return []
    _, names = parse_model(PRESETS[model.strip()][0])
    out = []
    for n in names:
        lo, hi = -np.inf, np.inf
        nl = n.lower()
        if nl.startswith("tau") or nl in ("d", "k", "s", "g", "ea"):
            lo = 0.0
        if nl == "beta":
            lo, hi = 0.05, 1.0
        if nl == "alpha":
            lo, hi = 0.0, 2.0
        if nl.startswith("a") and model.startswith(("exp", "kww")) and nl != "alpha":
            lo = 0.0
        if lo != -np.inf or hi != np.inf:
            out.append(Param(n, None, lo, hi))
    return out


def merge_params(base: List[Param], user: List[Param]) -> List[Param]:
    d = {p.name: p for p in base}
    for p in user:
        if p.name in d:
            q = d[p.name]
            if p.value is not None:
                q.value = p.value
            if np.isfinite(p.lo) or np.isfinite(p.hi) or p.lo != -np.inf:
                q.lo, q.hi = p.lo, p.hi
            q.fixed = p.fixed or q.fixed
        else:
            d[p.name] = p
    return list(d.values())


# ───────────────────────────── output ─────────────────────────────
def fmt(v, e=None) -> str:
    if v is None or not np.isfinite(v):
        return "nan"
    if e is None or not np.isfinite(e) or e <= 0:
        return f"{v:.6g}"
    d = max(0, -int(math.floor(math.log10(e))) + 1)
    if abs(v) >= 1e5 or (abs(v) < 1e-3 and v != 0):
        return f"{v:.{max(2, int(math.floor(math.log10(abs(v)))) - int(math.floor(math.log10(e))) + 1)}e} ± {e:.2g}"
    return f"{v:.{d}f} ± {e:.{d}f}" if d < 10 else f"{v:.6g} ± {e:.2g}"


def summary_lines(name: str, r: FitOutcome) -> List[str]:
    out = [f"{name}: {r.expr}   (x {r.x_range[0]:g} … {r.x_range[1]:g}, {r.n} points, R² = {r.r2:.5f}, "
           f"reduced χ² = {r.chi2_red:.4g})"]
    for k in r.names:
        tag = " (fixed)" if k in r.fixed else (" (at a bound!)" if k in r.at_bounds else "")
        out.append(f"  {k} = {fmt(r.values[k], r.errors[k])}{tag}")
    for k, (v, e) in r.derived.items():
        out.append(f"  {k} = {fmt(v, e)}  (derived)")
    return out


def write(results: List[Tuple[str, FitOutcome, np.ndarray, np.ndarray]], base: str, template: str = "natchem",
          formats: Sequence[str] = ("pdf", "svg", "png"), width="single", xlabel: Optional[str] = None,
          ylabel: Optional[str] = None, xscale: Optional[str] = None, yscale: Optional[str] = None) -> Dict[str, object]:
    """``results``: [(series name, outcome, all x, all y)]. Writes _params.csv, _fit.csv, _fit.json and a figure."""
    import matplotlib.pyplot as plt
    from .plot.engine import save
    os.makedirs(os.path.dirname(os.path.abspath(base)) or ".", exist_ok=True)
    files: Dict[str, object] = {}
    names = results[0][1].names
    dnames = list(results[0][1].derived)
    head = ["series"] + [c for n in names for c in (n, n + "_err")] + [c for n in dnames for c in (n, n + "_err")] + \
           ["r2", "chi2_red", "n", "x_min", "x_max"]
    with open(base + "_params.csv", "w", encoding="utf-8") as fh:
        fh.write(",".join(head) + "\n")
        for name, r, _, _ in results:
            row = [_q(name)] + [f"{v:.10g}" for n in names for v in (r.values[n], r.errors[n])]
            row += [f"{v:.10g}" for n in dnames for v in r.derived.get(n, (np.nan, np.nan))]
            row += [f"{r.r2:.8g}", f"{r.chi2_red:.6g}", str(r.n), f"{r.x_range[0]:.10g}", f"{r.x_range[1]:.10g}"]
            fh.write(",".join(row) + "\n")
    files["params"] = base + "_params.csv"
    with open(base + "_fit.csv", "w", encoding="utf-8") as fh:
        fh.write("series,x,y,fit,residual\n")
        for name, r, _, _ in results:
            for a, b, c in zip(r.x, r.y, r.fit):
                fh.write(f"{_q(name)},{a:.10g},{b:.10g},{c:.10g},{b - c:.6g}\n")
    files["fit"] = base + "_fit.csv"
    meta = {"model": results[0][1].expr, "series": [
        {"name": name, "x_range": list(r.x_range), "n": r.n, "dof": r.dof, "r2": r.r2, "chi2_red": r.chi2_red,
         "rmse": r.rmse, "parameters": {k: {"value": r.values[k], "error": r.errors[k], "fixed": k in r.fixed,
                                            "at_bound": k in r.at_bounds} for k in r.names},
         "derived": {k: {"value": v, "error": e} for k, (v, e) in r.derived.items()},
         "covariance": r.covariance.tolist() if r.covariance is not None else None}
        for name, r, _, _ in results]}
    Path(base + "_fit.json").write_text(json.dumps(meta, indent=1, default=float), encoding="utf-8")
    files["json"] = base + "_fit.json"
    fig = fit_figure(results, template=template, width=width, xlabel=xlabel, ylabel=ylabel, xscale=xscale, yscale=yscale)
    files["figure"] = save(fig, base + "_fit", formats)
    plt.close(fig)
    return files


def _q(s: str) -> str:
    return f'"{s}"' if ("," in s or '"' in s) else s


def fit_figure(results, template: str = "natchem", width="single", xlabel=None, ylabel=None, xscale=None,
               yscale=None, style: Optional[dict] = None):
    """Data (symbols), fitted curves over the whole data range (dashed outside the fit range) and residuals."""
    import matplotlib.pyplot as plt
    from .plot import templates as T
    from .plot.engine import MM, _styled
    tpl = _styled(T.get(template), style)
    W = tpl.width_mm(width)
    H = W * 0.86
    with plt.rc_context(tpl.rc()):
        fig = plt.figure(figsize=(W * MM, H * MM), layout="constrained")
        fig.get_layout_engine().set(w_pad=1.0 * MM, h_pad=1.0 * MM, hspace=0.0)
        gs = fig.add_gridspec(2, 1, height_ratios=[3.2, 1])
        ax = fig.add_subplot(gs[0])
        axr = fig.add_subplot(gs[1], sharex=ax)
        many = len(results) > 1
        for k, (name, r, xa, ya) in enumerate(results):
            col = tpl.palette[k % len(tpl.palette)]
            ms = tpl.lines["markersize"] * (0.7 if len(xa) > 60 else 1.0)
            ax.plot(xa, ya, "o", ms=ms, mfc="none", mec=col, mew=0.6, label=name if many else "data", zorder=2,
                    alpha=0.45 if len(xa) > 60 else 1.0)
            code, nm = parse_model(r.expr)
            q = [r.values[n] for n in nm]
            xf = np.asarray(xa, float)
            xf = xf[np.isfinite(xf)]
            if xscale == "log" and np.all(xf > 0):
                grid = np.geomspace(xf.min(), xf.max(), 600)
            else:
                grid = np.linspace(xf.min(), xf.max(), 600)
            yy = evaluate(code, nm, q, grid)
            inside = (grid >= r.x_range[0]) & (grid <= r.x_range[1])
            ax.plot(grid[inside], yy[inside], "-", color="#D55E00" if not many else col, lw=1.2,
                    label="fit" if not many else None, zorder=3)
            if (~inside).any():
                out_ = np.where(inside, np.nan, yy)
                ax.plot(grid, out_, ":", color="#D55E00" if not many else col, lw=0.8, zorder=3)
            axr.plot(r.x, r.y - r.fit, "o", ms=ms * 0.8, mfc="none", mec=col, mew=0.5)
        axr.axhline(0, color="0.55", lw=0.5, ls=(0, (2, 2)))
        lo, hi = min(r.x_range[0] for _, r, _, _ in results), max(r.x_range[1] for _, r, _, _ in results)
        for a in (ax, axr):
            if xscale:
                a.set_xscale(xscale)
        if yscale:
            ax.set_yscale(yscale)
        x_all = np.concatenate([np.asarray(xa, float) for _, _, xa, _ in results])
        if np.isfinite(lo) and (lo > np.nanmin(x_all) or hi < np.nanmax(x_all)):
            for a in (ax, axr):
                a.axvspan(lo, hi, color="0.5", alpha=0.07, lw=0, zorder=0)
        ax.tick_params(axis="x", which="both", labelbottom=False)
        ax.set_ylabel(ylabel or "y")
        axr.set_xlabel(xlabel or "x")
        axr.set_ylabel("Resid.")
        axr.yaxis.set_major_locator(plt.MaxNLocator(3, symmetric=True))
        ax.legend(loc="best")
        for a in (ax, axr):
            for sp in ("top", "right"):
                if sp not in tpl.axes["spines"]:
                    a.spines[sp].set_visible(False)
        fig.align_ylabels([ax, axr])
    fig._resrijan_template = tpl
    return fig
