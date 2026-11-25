"""General curve fitting (expressions, presets, bounds, ranges, derived quantities) and peak deconvolution."""
import json

import numpy as np
import pytest

from resrijan import curvefit as F
from resrijan.analysis import analyze, find_shoulders, gauss
from resrijan.cli import main

T = np.geomspace(0.02, 300, 160)


def _kww(tau=25.0, beta=0.6, seed=0):
    rng = np.random.default_rng(seed)
    return 0.95 * np.exp(-(T / tau) ** beta) + rng.normal(0, 0.003, T.size)


def test_expressions_are_checked():
    _, names = F.parse_model("A1*exp(-x/tau1) + A2*exp(-(x/tau2)^beta) + C")
    assert names == ["A1", "tau1", "A2", "tau2", "beta", "C"]
    for bad in ("__import__('os')", "A.real", "x[0]*A", "lambda: 1", "open('f')", "A*exp(-x/tau"):
        with pytest.raises(F.ExpressionError):
            F.parse_model(bad)
    assert F.parse_model("6*D*x")[1] == ["D"]                  # constants pi, kB, R… are not parameters
    assert F.parse_model("A*exp(-Ea/(R*x))")[1] == ["A", "Ea"]


def test_stretched_exponential_and_mean_time():
    e, d = F.model_for("kww")
    r = F.fit(T, _kww(), e, F.preset_bounds("kww"), derived=d)
    assert abs(r.values["tau"] - 25) < 4 * r.errors["tau"] + 0.3
    assert abs(r.values["beta"] - 0.6) < 4 * r.errors["beta"] + 0.01
    from scipy.special import gamma
    v, err = r.derived["tau_avg"]
    assert abs(v - r.values["tau"] / r.values["beta"] * gamma(1 / r.values["beta"])) < 1e-9
    assert 0 < err < 0.05 * v


def test_two_exponentials_sorted_fastest_first():
    rng = np.random.default_rng(2)
    y = 0.55 * np.exp(-T / 20) + 0.4 * np.exp(-T / 0.5) + rng.normal(0, 0.003, T.size)
    e, d = F.model_for("exp2")
    r = F.fit(T, y, e, F.preset_bounds("exp2"), derived=d)
    assert r.values["tau1"] < r.values["tau2"]
    assert abs(r.values["tau1"] - 0.5) < 0.05 and abs(r.values["tau2"] - 20) < 0.5
    assert abs(r.values["A1"] - 0.4) < 0.01


def test_msd_range_bounds_fixed_and_propagated_error():
    t = np.arange(0, 200.5, 0.5)
    rng = np.random.default_rng(3)
    msd = 6 * 0.21 * t * (1 - np.exp(-t / 0.8)) + rng.normal(0, 0.05, t.size)
    r = F.fit(t, msd, "6*D*x + c", x_range=(20, 200), derived={"D_si": "D*1e-8"})
    assert r.x_range == (20.0, 200.0) and r.n == 361
    assert abs(r.values["D"] - 0.21) < 5 * r.errors["D"] + 1e-3
    assert abs(r.derived["D_si"][1] - r.errors["D"] * 1e-8) < 1e-15
    # an upper bound that is too tight is reported
    r2 = F.fit(t, msd, "6*D*x + c", F.parse_params(bounds="D=0:0.1"), x_range=(20, 200))
    assert r2.values["D"] <= 0.1 + 1e-12 and "D" in r2.at_bounds
    r3 = F.fit(t, msd, "6*D*x + c", F.parse_params(fix="c=0"), x_range=(20, 200))
    assert r3.values["c"] == 0 and r3.errors["c"] == 0 and r3.fixed == ["c"]


def test_option_parsing_errors():
    with pytest.raises(F.ExpressionError):
        F.parse_params(p0="tau")
    with pytest.raises(F.ExpressionError):
        F.parse_params(bounds="tau=5")
    with pytest.raises(F.ExpressionError):
        F.fit(T, _kww(), "A*exp(-x/tau)", F.parse_params(bounds="beta=0:1"))
    with pytest.raises(F.ExpressionError):
        F.fit(T, _kww(), "A*exp(-x/tau)", [F.Param("tau", None, 5, 1)])


def test_fit_command(tmp_path):
    f = tmp_path / "ccf.csv"
    f.write_text("t,C1,C2\n" + "\n".join(f"{a},{b},{c}" for a, b, c in zip(T, _kww(25), _kww(8, seed=1))))
    out = tmp_path / "res" / "ccf"
    assert main(["fit", str(f), "-m", "kww", "--range", "0.05:300", "--xscale", "log",
                 "-o", str(out), "-f", "png"]) == 0
    meta = json.loads((tmp_path / "res" / "ccf_fit.json").read_text())
    taus = [s["parameters"]["tau"]["value"] for s in meta["series"]]
    assert abs(taus[0] - 25) < 1 and abs(taus[1] - 8) < 0.5
    head = (tmp_path / "res" / "ccf_params.csv").read_text().splitlines()[0]
    assert head.startswith("series,A,A_err,tau,tau_err,beta,beta_err,C,C_err,tau_avg,tau_avg_err,r2")
    assert (tmp_path / "res" / "ccf_fit.png").exists()
    for bad in (["-m", "A*exp(-x/tau"], ["--bounds", "T=0:1"], ["--fix", "tau=abc"], ["--range", "1"]):
        with pytest.raises(SystemExit):
            main(["fit", str(f)] + bad)


def test_shoulders_and_deconvolution():
    rng = np.random.default_rng(5)
    x = np.linspace(1550, 1750, 401)
    y = 0.05 + gauss(x, 0.55, 1628, 22) + gauss(x, 0.85, 1652, 24) + gauss(x, 0.35, 1680, 18) \
        + rng.normal(0, 0.006, x.size)
    found = find_shoulders(x, y)
    assert len(found) == 3 and all(abs(a - b) < 4 for a, b in zip(found, (1628, 1652, 1680)))
    an = analyze(x, y, baseline_opt=("ends", {}), n_components=3, shape="gauss", fwhm_range=(5, 40),
                 center_window=15, fit_range=(1570, 1730))
    c = [p.center for p in an.fit.peaks]
    assert all(abs(a - b) < 2 for a, b in zip(c, (1628, 1652, 1680)))
    from resrijan.analysis import peak_table
    pct = [r["area_pct"] for r in peak_table(an)]
    assert abs(sum(pct) - 100) < 1e-9
    true = np.array([0.55 * 22, 0.85 * 24, 0.35 * 18])
    assert np.allclose(pct, 100 * true / true.sum(), atol=2.5)
    assert an.fit.x_range[0] >= 1570 and an.fit.x_range[1] <= 1730
