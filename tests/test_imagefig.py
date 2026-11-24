"""Unit tests for resrijan.extract.imagefig (image figures: frames, insets, labels, bars)."""
import cv2
import numpy as np
import pytest

from resrijan.extract import imagefig


@pytest.mark.parametrize("text, d_nm, hkl", [
    ("d = 0.248 nm (101)", 0.248, "(101)"),
    ("d=2.6 Å (002)", 0.26, "(002)"),
    ("d:0.23nm", 0.23, ""),
])
def test_parse_dlabel(text, d_nm, hkl):
    d = imagefig.parse_dlabel(text)
    assert d is not None and abs(d["d_nm"] - d_nm) < 1e-9 and d["hkl"] == hkl


def test_parse_dlabel_rejects_plain_text():
    assert imagefig.parse_dlabel("TiO2 (anatase)") is None
    assert imagefig.parse_dlabel("5 nm") is None          # scale-bar text, not a d-spacing


@pytest.mark.parametrize("text, val", [("5 min", (5.0, "min")), ("20", (20.0, "")), ("1,5 h", (1.5, "h"))])
def test_parse_value(text, val):
    assert imagefig.parse_value(text) == val


def test_parse_value_rejects_words():
    assert imagefig.parse_value("control") is None


def _texture(H, W, seed=0):
    rng = np.random.default_rng(seed)
    g = cv2.GaussianBlur(rng.normal(128, 40, (H, W)).astype(np.float32), (0, 0), 2.0)
    return np.clip(g, 0, 255).astype(np.uint8)


def test_register_inset_finds_crop_and_magnification():
    parent = _texture(300, 400)
    x0, y0, w, h, mag = 120, 80, 60, 45, 3.0
    inset = cv2.resize(parent[y0:y0 + h, x0:x0 + w], None, fx=mag, fy=mag, interpolation=cv2.INTER_CUBIC)
    reg = imagefig.register_inset(parent, inset)
    assert reg is not None
    assert abs(reg["mag"] / mag - 1) < 0.01
    assert abs(reg["box"][0] - x0) <= 1 and abs(reg["box"][1] - y0) <= 1
    assert reg["ncc"] > 0.9


def test_register_inset_rejects_unrelated_image():
    assert imagefig.register_inset(_texture(300, 400, 1), _texture(150, 200, 2)) is None


def test_looks_photographic():
    noise = np.random.default_rng(3).normal(0, 6, (120, 160))      # detector noise
    g = np.clip(_texture(120, 160) + noise, 0, 255).astype(np.uint8)
    rgb = np.dstack([g] * 3)
    assert imagefig.looks_photographic(rgb)
    plot = np.full((120, 160, 3), 255, np.uint8)
    plot[60, 10:150] = 0
    assert not imagefig.looks_photographic(plot)


def test_to_unit_and_nice_lengths():
    assert imagefig.to_unit(0.5)[1] in ("nm", "pm", "Å")
    v, u = imagefig.to_unit(2500)
    assert u == "µm" and abs(v - 2.5) < 1e-9
    assert imagefig._nice_len(4.7) == 5
    assert imagefig._nice_len(0.19) == pytest.approx(0.2)
