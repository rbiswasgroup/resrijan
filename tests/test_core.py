"""Fast unit tests:  python -m pytest tests/"""
import pytest

from resrijan.detect.ocr import parse_number
from resrijan.detect.calibration import calibrate, repair_labels
from resrijan.plot.layout import auto_layout
from resrijan.plot import templates


@pytest.mark.parametrize("s,v", [("1.5", 1.5), ("−0.5", -0.5), ("1,000", 1000), ("0,25", 0.25),
                                 ("10^-3", 1e-3), ("2x10^4", 2e4), ("1e-2", 0.01), ("10⁻²", 0.01), ("abc", None)])
def test_parse_number(s, v):
    r = parse_number(s)
    assert (r is None and v is None) or abs(r - v) < 1e-12


def test_linear_calibration_rejects_misread():
    pos = [100, 200, 300, 400, 500]
    val = [0, 1, 2, 7, 4]                      # '3' misread as '7'
    c = calibrate("x", pos, val)
    assert c.scale == "linear" and len(c.rejected) == 1
    assert abs(c.to_data(300) - 2) < 1e-9


def test_log_calibration():
    c = calibrate("y", [500, 400, 300, 200], [1e-3, 1e-2, 1e-1, 1])
    assert c.scale == "log" and abs(c.to_data(350) - 10 ** -1.5) < 1e-9


def test_label_repair():
    out, score = repair_labels([10, 60, 110], [".600", "1650", "170"], [0.6, 1650, 170])
    assert out == [1600, 1650, 1700]


def test_layout_two_by_two():
    lay = auto_layout([1.33] * 4, 183, 170)
    assert lay.rows == [[0, 1], [2, 3]] and lay.height_mm < 170


def test_templates_load():
    for k in ("natchem", "acs", "aps", "science", "pnas", "rsc"):
        t = templates.get(k)
        assert t.width_mm("single") > 50 and t.rc()["pdf.fonttype"] == 42
    assert templates.get("jpcl").key == "acs"


def test_svg_loads_as_vector(tmp_path):
    from resrijan.io.loader import load
    svg = tmp_path / "t.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80">'
                   '<line x1="10" y1="70" x2="90" y2="70" stroke="black"/>'
                   '<polyline points="10,60 50,20 90,40" fill="none" stroke="red"/>'
                   '<text x="10" y="78" font-size="8">0</text></svg>')
    pg = load(str(svg), dpi=144)[0]
    assert pg.kind == "vector" and len(pg.pdf_page.get_drawings()) >= 2
    assert "0" in pg.pdf_page.get_text()


def test_direct_labels_split_by_colour_and_keep_bold():
    """Two adjacent point labels in different colours ("Mg" next to "Ca") stay apart;
    bold spans are remembered."""
    from resrijan.detect.vector import VChar, group_chars
    from resrijan.extract.vector_series import _join_words

    def ch(c, x, col, word):
        return VChar(c, (x, 0.0, x + 8.0, 12.0), 12.0, (x, 10.0), (1.0, 0.0), word, col, True)

    orange, green = (255, 140, 0), (22, 181, 43)
    chars = [ch("M", 0, orange, 1), ch("g", 8, orange, 1),
             ch("C", 22, green, 2), ch("a", 30, green, 2)]
    labs = _join_words(group_chars(chars))
    assert sorted(l.text for l in labs) == ["Ca", "Mg"]
    assert all(l.bold for l in labs)


def test_inset_is_not_a_row_neighbour_and_clip_bounds_paths():
    import numpy as np
    from resrijan.detect.axes import AxesBox
    from resrijan.detect.vector import VPath, _same_row
    main = AxesBox(x0=0, y0=0, x1=100, y1=100, xaxis_y=100, yaxis_x=0, line_w=1)
    ins = AxesBox(x0=50, y0=10, x1=90, y1=40, xaxis_y=40, yaxis_x=50, line_w=1)
    assert _same_row(main, AxesBox(x0=110, y0=0, x1=200, y1=100, xaxis_y=100, yaxis_x=110, line_w=1))
    ins.inset_of = main
    assert not _same_row(main, ins)
    p = VPath([np.array([[0.0, 90.0], [10.0, -50.0]])], (0, 0, 0), None, 1.0, "", False, (0, -50, 10, 90),
              clip=(0, 20, 100, 100))
    assert p.vis_bbox[1] == 20          # a peak cut by its clip rectangle ends at the clip


def test_source_column_grid():
    """A 4-panel row over a 6-panel row keeps the source columns (empty cells on the left)."""
    from resrijan.pipeline import _columns_from_source
    xs = [(16, 750), (766, 1500), (1734, 2468), (2484, 3218), (3452, 4186), (4202, 4936)]
    keys = [("plot", 500, 700, *xs[k]) for k in range(2, 6)] + [("plot", 1600, 700, *x) for x in xs]
    rows = [[0, 1, 2, 3], [4, 5, 6, 7, 8, 9]]
    assert _columns_from_source(rows, keys) == [[2, 3, 4, 5], [0, 1, 2, 3, 4, 5]]
    assert _columns_from_source([[0, 1], [2, 3]], keys[:4]) is None        # equal rows: plain layout
