"""Image figures, inset plots, minus signs, x-only axes, contour lines, unnumbered axes."""
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from resrijan.extract.imagefig import lattice_peaks  # noqa: E402
from resrijan.pipeline import digitize  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


def _save(fig, path):
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def test_lattice_period_precision():
    rng = np.random.default_rng(3)
    for p, ang in ((5.3, 20.0), (13.7, 101.0), (19.4, 160.0)):
        H, W = 200, 240
        y, x = np.mgrid[0:H, 0:W]
        th = np.radians(ang)
        g = 128 + 40 * np.cos(2 * np.pi * (x * np.cos(th) - y * np.sin(th)) / p) + rng.normal(0, 20, (H, W))
        pk = lattice_peaks(np.clip(g, 0, 255).astype(np.uint8))[0]
        assert abs(pk["period_px"] / p - 1) < 0.002
        assert min(abs(pk["angle_deg"] - ang), 180 - abs(pk["angle_deg"] - ang)) < 0.5


@pytest.mark.skipif(not (EX / "12_hrtem_insets" / "hrtem_insets.pdf").exists(), reason="example not generated")
def test_hrtem_insets_example():
    truth = json.loads((EX / "12_hrtem_insets" / "truth.json").read_text())
    panels = digitize(str(EX / "12_hrtem_insets" / "hrtem_insets.pdf"))
    main = [p for p in panels if p.frame is not None and p.frame.parent is None]
    assert len(main) == 1
    assert abs(main[0].frame.nm_per_px / truth["nm_per_px"] - 1) < 0.002
    assert main[0].frame.rgb.shape[0] == truth["visible_rows"]           # clipped strip excluded
    assert any(n["code"] == "bar_crosscheck" for n in main[0].notes)      # hidden instrument bar read
    insets = [p for p in panels if p.frame is not None and p.frame.parent is not None]
    assert len(insets) == 4
    for p in insets:
        assert abs(p.frame.registration["mag"] - 4.0) < 0.01
        d = p.frame.dlabels[0]
        true = next(t for t in truth["insets"] if t["label"].startswith(f"d = {d['d']:g}"))
        assert abs(d["measured_nm"] - true["true_d_nm"]) < 0.004
        flagged = any(n["code"] == "d_check" and n["level"] == "warn" for n in p.notes)
        assert flagged == (not true["label_correct"])


@pytest.mark.skipif(not (EX / "13_timelapse" / "timelapse.svg").exists(), reason="example not generated")
def test_timelapse_example():
    truth = json.loads((EX / "13_timelapse" / "truth.json").read_text())
    panels = digitize(str(EX / "13_timelapse" / "timelapse.svg"))
    frames = [p for p in panels if p.frame is not None]
    assert [p.frame.title for p in frames] == ["0 min", "10 min", "20 min", "30 min", "40 min"]
    der = [p for p in panels if p.mode == "derived"]
    assert der
    sep = next(s for s in der[0].series if "separation" in s.name)
    arr = next(s for s in der[0].series if "arrow 1" in s.name)
    for t, ys, ya in zip(sep.x, sep.y, arr.y):
        fr = next(f for f in truth["frames"] if f["time_min"] == t)
        assert abs(ys - fr["perpendicular_px"]) < 0.2
        assert abs(ya - fr["arrow_px"][0]) < 0.2


def test_negative_ticks_and_point_labels(tmp_path):
    fig, ax = plt.subplots(figsize=(4, 4))
    pts = {"A": (-14.2, -14.4, "D", "#ff8c00"), "B": (-7.5, -12.6, "o", "#f21f1f"), "C": (-8.8, -11.9, "^", "#263bff")}
    for name, (x, y, m, c) in pts.items():
        ax.plot([x], [y], m, ms=10, mfc=c, mec="k")
        ax.text(x + 0.5, y, name, color=c, va="center")
    ax.plot([-16, -4], [-16, -4], "--", color="0.5")
    ax.set_xlim(-16, -4); ax.set_ylim(-16, -4)
    ax.set_xlabel(r"$E^{\mathrm{calc}}_{\mathrm{b-1}}$ (kJ/mol)")
    panels = digitize(_save(fig, tmp_path / "parity.pdf"))
    p = panels[0]
    assert p.box.xcal.to_data(p.box.x0) == pytest.approx(-16, abs=0.01)
    assert p.box.ycal.to_data(p.box.y0) == pytest.approx(-4, abs=0.01)
    byname = {s.name: s for s in p.series if s.kind == "markers"}
    for name, (x, y, m, c) in pts.items():
        s = byname[name]
        assert s.x[0] == pytest.approx(x, abs=0.01) and s.y[0] == pytest.approx(y, abs=0.01)
        assert s.style["marker"] == {"D": "D", "o": "o", "^": "^"}[m]


def test_xonly_axis_offset_spectra(tmp_path):
    x = np.linspace(-20, 20, 800)
    fig, ax = plt.subplots(figsize=(4, 4))
    for k, c in enumerate(["#e41a1c", "#377eb8", "#4daf4a"]):
        ax.plot(x, k + np.exp(-((x - 3 * k) / 0.8) ** 2), color=c)
        ax.text(-18, k + 0.3, f"S{k}", color=c)
    ax.set_xlim(20, -20)
    for sp in ("left", "right", "top"):
        ax.spines[sp].set_visible(False)
    ax.set_yticks([])
    panels = digitize(_save(fig, tmp_path / "stack.pdf"))
    p = panels[0]
    assert p.box.no_yaxis and p.box.xcal.reversed
    assert len(p.series) == 3
    for s in p.series:
        k = int(s.name[-1])
        peak = s.x[np.argmax(s.y)]
        assert peak == pytest.approx(3 * k, abs=0.1)


def test_vector_contour_lines(tmp_path):
    y, x = np.mgrid[2.5:4.0:200j, 4.35:4.55:200j]
    z = np.exp(-((x - 4.45) / 0.03) ** 2 - ((y - 3.0) / 0.1) ** 2)
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.contour(x, y, z, levels=np.linspace(0.1, 0.9, 9), colors="#1f77b4")
    ax.set_xlim(4.55, 4.35); ax.set_ylim(4.0, 2.5)
    panels = digitize(_save(fig, tmp_path / "cont.pdf"))
    p = panels[0]
    assert p.kind == "contour" and len(p.contours) >= 9
    c = p.contours[-1]
    cx = p.box.xcal.to_data(c[:, 0]).mean(); cy = p.box.ycal.to_data(c[:, 1]).mean()
    assert cx == pytest.approx(4.45, abs=0.003) and cy == pytest.approx(3.0, abs=0.01)


def test_unnumbered_y_axis_is_relative(tmp_path):
    fig, ax = plt.subplots(figsize=(4, 3))
    t = np.linspace(0, 8, 60)
    ax.plot(t, 0.2 + 0.6 * np.exp(-t / 3), "k-")
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.NullFormatter())
    panels = digitize(_save(fig, tmp_path / "rel.pdf"))
    p = panels[0]
    assert p.box.ycal.source == "relative"
    assert any(n["code"] == "y_relative" for n in p.notes)
    s = p.series[0]
    assert np.allclose(s.y, 0.2 + 0.6 * np.exp(-s.x / 3), atol=0.01)


def test_bitmap_photo_strip_is_not_a_plot(tmp_path):
    rng = np.random.default_rng(0)
    fig = plt.figure(figsize=(6, 3))
    for k in range(3):
        ax = fig.add_axes([0.03 + 0.32 * k, 0.05, 0.28, 0.8])
        img = np.clip(rng.normal(120, 30, (300, 200, 3)), 0, 255).astype(np.uint8)
        ax.imshow(img); ax.set_axis_off(); ax.set_title(f"{5 * k} min")
        ax.plot([60, 140], [0, 299], color="red", lw=1.5)
    path = tmp_path / "strip.png"
    fig.savefig(path, dpi=150); plt.close(fig)
    panels = digitize(str(path))
    assert all(p.kind != "uncalibrated" for p in panels)
    assert sum(p.frame is not None for p in panels) == 3
    assert not any(n["level"] == "error" for p in panels for n in p.notes)
    os.remove(path)


def test_framed_legend_is_not_an_inset(tmp_path):
    """A framed legend inside a plot (Origin style) is not an inset plot."""
    fig, ax = plt.subplots(figsize=(4, 3))
    x = np.arange(280, 361, 10)
    ax.plot(x, np.exp((x - 280) / 30), "o-", label="Urea")
    ax.plot(x, np.exp((x - 280) / 28), "s-", label="TMAO")
    ax.legend(loc="upper left", frameon=True, fancybox=False, edgecolor="k")
    ax.set_ylim(0, 25)
    panels = digitize(_save(fig, tmp_path / "legend.pdf"))
    assert [p.kind for p in panels] == ["line"]
    assert sorted(s.name for s in panels[0].series if s.kind == "markers") == ["TMAO", "Urea"]
