"""Analysis (baseline, smoothing, units, peak fitting, areas) and plot styling options."""
import json

import numpy as np
import pytest

from resrijan import analysis as A
from resrijan.cli import main, parse_arrow, parse_text


def _spectrum(noise=0.005, seed=0):
    rng = np.random.default_rng(seed)
    x = np.linspace(1000, 2000, 900)
    y = (0.2 + 1e-4 * (x - 1000) + A.lorentz(x, 1.0, 1450, 30) + A.gauss(x, 0.6, 1600, 40)
         + rng.normal(0, noise, x.size))
    return x, y


def test_unit_conversions_round_trip():
    nm = np.array([400.0, 500.0, 800.0])
    assert np.allclose(A.convert_x(nm, "nm", "eV"), 1239.841984 / nm)
    assert np.allclose(A.convert_x(nm, "nm", "cm-1"), 1e7 / nm)
    assert np.allclose(A.convert_x(A.convert_x(nm, "nm", "THz"), "THz", "nm"), nm)
    assert np.allclose(A.convert_x(nm / 1000, "um", "nm"), nm)
    with pytest.raises(ValueError):
        A.convert_x(nm, "nm", "furlong")


def test_peak_fit_recovers_known_peaks_within_errors():
    x, y = _spectrum()
    fit = A.fit_peaks(x, y, [1450, 1600], shape="voigt")
    p1, p2 = fit.peaks
    assert abs(p1.center - 1450) < 4 * p1.center_err + 0.2
    assert abs(p2.center - 1600) < 4 * p2.center_err + 0.2
    assert abs(p1.fwhm - 30) < 1.0 and abs(p2.fwhm - 40) < 1.5
    assert abs(p1.height - 1.0) < 0.03 and abs(p2.height - 0.6) < 0.03
    assert p1.eta > 0.8 and p2.eta < 0.2                 # Lorentzian and Gaussian told apart
    assert fit.r2 > 0.99
    assert all(np.isfinite([p.area_err for p in fit.peaks]))


def test_auto_peaks_baseline_and_areas():
    x, y = _spectrum()
    an = A.analyze(x, y, baseline_opt=("als", {"lam": 1e7, "p": 0.02}), auto_peaks=True, areas=[(1300, 1700)])
    assert [round(p.center) for p in an.fit.peaks] == [1450, 1600]
    assert abs(np.median(an.y[x < 1300])) < 0.02         # flat after baseline removal
    total = sum(p.area for p in an.fit.peaks)
    assert abs(an.areas[0]["area"] - total) / total < 0.15


def test_smoothing_normalisation_and_integration():
    x = np.linspace(0, 1, 201)
    y = np.sin(np.pi * x)
    assert np.allclose(A.smooth(y, "savgol", 11, 3), y, atol=1e-3)
    yn, d = A.normalize(x, 3 * y, "max")
    assert abs(yn.max() - 1) < 1e-12 and abs(d - 3) < 1e-9
    assert abs(A.integrate(x, y, 0, 1) - 2 / np.pi) < 1e-4
    ya, _ = A.normalize(x, y, "area")
    assert abs(A.integrate(x, ya, 0, 1) - 1) < 1e-6


def test_analyze_command_writes_results(tmp_path):
    x, y = _spectrum()
    f = tmp_path / "ir.csv"
    f.write_text("wn,abs\n" + "\n".join(f"{a},{b}" for a, b in zip(x, y)))
    out = tmp_path / "res" / "ir"
    assert main(["analyze", str(f), "--baseline", "poly:1", "--peaks", "1450,1600", "--shape", "voigt",
                 "--area", "1400:1500", "-o", str(out), "-f", "png"]) == 0
    meta = json.loads((tmp_path / "res" / "ir_analysis.json").read_text())
    assert len(meta["peaks"]) == 2 and meta["fit"]["r2"] > 0.99
    head = (tmp_path / "res" / "ir_processed.csv").read_text().splitlines()[0]
    assert head.startswith("x,y_raw,baseline,y,fit,peak1,peak2,residual")
    assert (tmp_path / "res" / "ir_peaks.csv").exists() and (tmp_path / "res" / "ir_analysis.png").exists()


def test_analyze_rejects_bad_options(tmp_path):
    f = tmp_path / "d.csv"
    f.write_text("x,y\n1,2\n2,3\n")
    for bad in (["--convert", "nm"], ["--peaks", "12,abc"], ["--crop", "1:2:3"]):
        with pytest.raises(SystemExit):
            main(["analyze", str(f)] + bad)


def test_style_options(tmp_path):
    src = "examples/10_plot_your_data/diffusion.csv"
    assert main(["plot", src, "--kind", "errorbar", "-x", "T_K", "-y", "D_urea,D_water", "--yerr", "err_urea,err_water",
                 "--linestyles", "dashed,", "--markers", "square,none", "--legend", "outside top", "--legend-frame",
                 "--font-scale", "1.2", "--text", "300,4,label|navy", "--arrow", "290,3.5,318,2,here",
                 "--grid", "-o", str(tmp_path / "s"), "-f", "png"]) == 0
    assert (tmp_path / "s.png").exists()
    assert parse_text("axes:0.1,0.9,(a)")["coords"] == "axes fraction"
    a = parse_arrow("1,2,3,4,peak, shoulder|red")
    assert a["xytext"] == [1, 2] and a["xy"] == [3, 4] and a["text"] == "peak, shoulder" and a["color"] == "red"
    with pytest.raises(SystemExit):
        main(["plot", src, "--legend", "somewhere"])
    with pytest.raises(SystemExit):
        main(["plot", src, "--text", "1,two,x"])
