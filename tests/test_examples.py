"""End-to-end tests on the example figures (fast vector cases + one bitmap)."""
import shutil
from pathlib import Path

import numpy as np
import pytest

from resrijan import digitize, write_outputs

EX = Path(__file__).resolve().parent.parent / "examples"
needs_gs = pytest.mark.skipif(shutil.which("gs") is None, reason="Ghostscript not installed")
needs_tess = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")


def test_line_pdf_exact():
    p = digitize(str(EX / "01_line_plot/line_multi.pdf"))[0]
    assert p.mode == "vector" and p.kind == "line"
    assert sorted(s.name for s in p.series) == ["damped", "gauss", "ramp", "sigmoid"]
    ramp = next(s for s in p.series if s.name == "ramp")
    # ramp: y = 0.12 x - 0.6
    assert np.allclose(ramp.y, 0.12 * np.asarray(ramp.x) - 0.6, atol=1e-3)
    assert ramp.dashed


@needs_gs
def test_log_eps():
    p = digitize(str(EX / "03_log_axis/log_decay.eps"))[0]
    assert p.box.ycal.scale == "log"
    mono = next(s for s in p.series if s.name == "mono")
    x, y = np.asarray(mono.x), np.asarray(mono.y)
    assert np.allclose(np.log10(y), np.log10(np.exp(-x / 3.2)), atol=2e-3)


def test_bar_svg():
    p = digitize(str(EX / "05_bar_chart/bar_err.svg"))[0]
    assert p.kind == "bar"
    vals = [round(b.value, 3) for b in p.bars]
    assert vals == [2.4, 5.8, 9.35, 10.7, 6.9, 1.6]


@needs_tess
def test_bar_png_categories():
    p = digitize(str(EX / "05_bar_chart/bar_err.png"))[0]
    assert [b.category for b in p.bars] == ["Pt", "Pd", "Ni", "Co", "Fe", "Cu"]
    assert all(abs(b.value - t) < 0.05 for b, t in zip(p.bars, [2.4, 5.8, 9.35, 10.7, 6.9, 1.6]))


def test_heatmap_pdf_native_image():
    p = digitize(str(EX / "06_heatmap_2dir/heatmap_2dir.pdf"))[0]
    assert p.kind == "heatmap" and p.mode == "embedded-image"
    assert -1.0 <= np.nanmin(p.grid.z) < -0.8 and 0.8 < np.nanmax(p.grid.z) <= 1.0


@needs_tess
def test_micrograph_scale():
    p = digitize(str(EX / "08_micrograph/micrograph_tem.png"))[0]
    assert p.kind == "micrograph"
    assert abs(p.micro.nm_per_px - 0.5) < 0.005
    assert p.micro.particles["stats"]["n"] == 60


def test_multipanel_reading_order(tmp_path):
    ps = digitize(str(EX / "09_multipanel_page/multipanel_page.pdf"))
    assert [p.kind for p in ps] == ["line", "line", "scatter", "line"]
    res = write_outputs(ps, str(tmp_path), template="natchem", formats=["svg"], stem="mp")
    assert Path(res["report"]).exists() and res["combined"]
    svg = Path(res["combined"][0]).read_text()
    assert "<text" in svg            # editable text
