"""GUI tests (headless). The GUI must run the same commands as the CLI and give the same results."""
import os
import re
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    home = tmp_path_factory.mktemp("guihome")
    os.environ["XDG_CONFIG_HOME"] = str(home / "config")          # isolated QSettings
    os.environ["RESRIJAN_TEMPLATES"] = str(home / "templates")     # isolated user templates
    from resrijan.gui import templates_io
    templates_io.reload()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from resrijan.gui import theme
    from resrijan.gui.mainwindow import MainWindow
    theme.apply(app)
    w = MainWindow(synchronous=True)
    w.show()
    yield w
    w.close()
    os.environ.pop("RESRIJAN_TEMPLATES", None)
    templates_io.reload()


def test_cli_has_gui_command():
    from resrijan.cli import build_parser
    a = build_parser().parse_args(["gui"])
    assert a.cmd == "gui" and a.file is None


def test_digitize_page_matches_cli(win, tmp_path):
    from resrijan.cli import main
    d = win.pages["digitize"]
    src = str(EX / "05_bar_chart" / "bar_err.svg")
    d.open_path(src)
    assert len(d.pages) == 1 and d.pages[0][2] == "vector"
    d.out.setText(str(tmp_path / "gui"))
    d.formats.set_value("png")
    argv = d.argv()
    assert argv[:2] == ["digitize", src] and "-f" in argv and "png" in argv
    d.run()
    panels, res, out = d.result
    assert d.tree.topLevelItemCount() == 1 and panels[0].kind == "bar"
    # the command shown in the GUI, run through the real CLI, gives identical data
    cli_argv = [a if a != str(tmp_path / "gui") else str(tmp_path / "cli") for a in argv]
    assert main(cli_argv) == 0
    g = (tmp_path / "gui" / "bar_err_p1_a_bars.csv").read_text()
    c = (tmp_path / "cli" / "bar_err_p1_a_bars.csv").read_text()
    assert g == c


def test_clicked_ticks_become_calibration(win):
    from PySide6.QtCore import QRectF
    d = win.pages["digitize"]
    d.open_path(str(EX / "05_bar_chart" / "bar_err.svg"))
    pdpi = win.prefs.get("preview_dpi")
    d.dpi.setValue(300)
    f = 300 / pdpi
    d.picks["x"] = [(100.0, 50.0, 1.0), (200.0, 50.0, 3.0)]
    d.picks["y"] = [(40.0, 250.0, 0.0), (40.0, 50.0, 10.0)]
    d._update_cal_strings()
    assert d.xcal.text() == f"{100 * f:.2f}:1,{200 * f:.2f}:3"
    assert d.ycal.text() == f"{250 * f:.2f}:0,{50 * f:.2f}:10"
    # with a region, pixels are measured from the region's corner (as the pipeline crops)
    w, h = d.preview.view.image_size()
    d._region_drawn(QRectF(0.1 * w, 0.2 * h, 0.5 * w, 0.5 * h))
    ox, oy = round(0.1 * w * f), round(0.2 * h * f)
    assert d.xcal.text().split(",")[0] == f"{100 * f - ox:.2f}:1"
    assert d.ycal.text().split(",")[1] == f"{50 * f - oy:.2f}:10"
    assert "--region" in d.argv() and "--xcal" in d.argv()
    d.clear_picks()
    d.set_region(None)


def test_plot_page_pairs_error_columns(win, tmp_path):
    p = win.pages["plot"]
    p.auto.setChecked(False)
    p.open_path(str(EX / "10_plot_your_data" / "diffusion.csv"))
    p.kind.setCurrentText("errorbar")
    a = p.argv()
    assert a[a.index("-x") + 1] == "T_K"
    assert a[a.index("-y") + 1] == "D_urea,D_water"
    assert a[a.index("--yerr") + 1] == "err_urea,err_water"
    p.out.setText(str(tmp_path / "fig"))
    p.formats.set_value("png")
    p.save()
    assert (tmp_path / "fig.png").exists()
    p.preview()
    assert p.view.view.has_image()


def test_template_import_validate_delete(win, tmp_path):
    from resrijan.gui import templates_io as TIO
    from resrijan.plot import templates as T
    t = win.pages["templates"]
    src = Path(T.get("natchem").path).read_text()
    good = tmp_path / "mylab.yaml"
    good.write_text(TIO.duplicate_text(T.get("natchem").path, "mylab", "My lab style"))
    t.import_path(str(good))
    assert (TIO.user_dir() / "mylab.yaml").exists()
    assert T.get("mylab").name == "My lab style"
    combo = win.pages["digitize"].template
    assert combo.findData("mylab") >= 0          # every template selector was refreshed
    with pytest.raises(ValueError):
        TIO.validate(src.replace("palette:", "colours:"))
    with pytest.raises(ValueError):
        TIO.validate(re.sub(r"(?m)^key:.*$", "key: Bad Key", src))
    TIO.delete("mylab")
    with pytest.raises(KeyError):
        T.get("mylab")


def test_open_any_routes_files(win, tmp_path):
    win.open_any(str(EX / "10_plot_your_data" / "correlation.csv"))
    assert win.stack.currentWidget() is win.pages["plot"]
    spec = tmp_path / "fig.yaml"
    shutil.copy(EX / "11_compose_figure" / "figure_natchem.yaml", spec)
    for f in (EX / "11_compose_figure" / "data").iterdir():
        (tmp_path / "data").mkdir(exist_ok=True)
        shutil.copy(f, tmp_path / "data" / f.name)
    win.open_any(str(spec))
    assert win.stack.currentWidget() is win.pages["compose"]
    assert win.pages["compose"].view.view.has_image()


def test_compose_preview_png():
    import yaml
    from resrijan.gui.render import compose_preview
    spec_path = EX / "11_compose_figure" / "figure_natchem.yaml"
    png = compose_preview(yaml.safe_load(spec_path.read_text()), str(spec_path.parent))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
