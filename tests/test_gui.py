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


def test_plot_colours_and_title_colour_reach_the_cli(win, tmp_path):
    p = win.pages["plot"]
    p.auto.setChecked(False)
    p.open_path(str(EX / "10_plot_your_data" / "diffusion.csv"))
    p.kind.setCurrentText("errorbar")
    p.ytab.cellWidget(1, 3).set_value("#0072B2", emit=True)
    p.label_color.set_value("navy", emit=True)
    a = p.argv()
    assert a[a.index("--colors") + 1] == ",#0072B2"           # first series keeps the template colour
    assert a[a.index("--label-color") + 1] == "navy"
    p.ytab.cellWidget(1, 3).set_value("", emit=True)
    p.label_color.set_value("", emit=True)
    assert "--colors" not in p.argv() and "--label-color" not in p.argv()


def test_super_and_subscript_buttons_wrap_selection():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from resrijan.gui.textedit import MathLineEdit, render_label, wrap_script
    w = MathLineEdit()
    w.setText("cm-1")
    w.edit.setSelection(2, 2)
    wrap_script(w.edit, "sup")
    assert w.text() == "cm$^{-1}$" and w.is_valid()
    w.setText("H2O")
    w.edit.setSelection(1, 1)
    wrap_script(w.edit, "sub")
    assert w.text() == "H$_{2}$O"
    w.setText("$\\alpha_{")
    assert not w.is_valid()
    with pytest.raises(ValueError):
        render_label("$\\alpha_{$")
    render_label("$\\Delta G$ (kJ mol$^{-1}$), ℏω, ±, µm")


def test_colour_button_value_and_bad_colour_rejected():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from resrijan.cli import main
    from resrijan.gui.textedit import ColorButton
    b = ColorButton("Automatic")
    assert b.value() == ""
    b.set_value("#D55E00")
    assert b.value().lower() == "#d55e00"
    with pytest.raises(SystemExit):
        main(["plot", str(EX / "10_plot_your_data" / "diffusion.csv"), "--colors", "notacolour"])


def test_analyze_page_matches_cli_and_click_adds_peaks(win, tmp_path):
    import numpy as np
    from resrijan.analysis import gauss
    x = np.linspace(0, 100, 400)
    y = gauss(x, 1, 30, 6) + gauss(x, 0.5, 70, 8)
    f = tmp_path / "s.csv"
    f.write_text("x,signal\n" + "\n".join(f"{a},{b}" for a, b in zip(x, y)))
    p = win.pages["analyze"]
    win.show_page("analyze")
    p.auto.setChecked(False)
    p.open_path(str(f))
    p.pk_mode.setCurrentIndex(p.pk_mode.findData("auto"))
    p.shape.setCurrentIndex(p.shape.findData("gauss"))
    p.preview()
    assert p.table.rowCount() == 2 and p._map is not None
    x0, x1, lo, hi = p._map
    p.pk_list.setText("")
    p._picked(x0 + (30 - lo) / (hi - lo) * (x1 - x0), 5)
    assert p.pk_mode.currentData() == "manual" and abs(float(p.pk_list.text()) - 30) < 1
    a = p.argv()
    assert a[a.index("--peaks") + 1] == p.pk_list.text().strip() and "--shape" in a
    p.out.setText(str(tmp_path / "res"))
    p.formats.set_value("png")
    p.save()
    assert (tmp_path / "res_peaks.csv").exists()


def test_data_editor_operations_and_save(tmp_path):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from resrijan.gui.editor import DataEditor, EditData
    f = tmp_path / "fig_p1_a_data.csv"
    f.write_text("series,x,y,yerr_minus,yerr_plus,kind,source\n" +
                 "\n".join(f"A,{i},{i * i},nan,nan,line,vector" for i in range(10)) + "\n" +
                 "\n".join(f"B,{i},{-i},nan,nan,markers,raster" for i in range(5)) + "\n")
    ed = DataEditor(str(f))
    ed._do(ed.data.move_point, 0, 2, 2.0, 5.0)
    ed._do(ed.data.add_point, 0, 2.5, 6.0)
    assert list(ed.data.series[0].x[:4]) == [0, 1, 2, 2.5]          # inserted in x order for lines
    ed._do(ed.data.delete_points, 1, [0])
    ed.active = 0
    ed.select(ed.points_in(6, 20, -1, 1000))
    ed.split("A tail")
    assert ed.data.names() == ["A", "A tail", "B"] and len(ed.data.series[1].x) == 4
    ed.active = 0
    ed.merge("A tail")
    assert ed.data.names() == ["A", "B"] and len(ed.data.series[0].x) == 11
    ed.undo()
    assert ed.data.names() == ["A", "A tail", "B"]
    ed.redo()
    out = ed.save()
    assert out.endswith("fig_p1_a_data_edited.csv")
    back = EditData.from_csv(out)
    assert back.names() == ["A", "B"] and back.series[1].kind == "markers" and len(back.series[1].x) == 4
    log = (tmp_path / "fig_p1_a_data_edited_edits.json").read_text()
    assert "merged 'A tail' into 'A'" in log
    ed.close()


def test_project_round_trip(win, tmp_path):
    from resrijan.gui.mainwindow import MainWindow
    p = win.pages["plot"]
    p.auto.setChecked(False)
    p.open_path(str(EX / "10_plot_your_data" / "diffusion.csv"))
    p.kind.setCurrentText("errorbar")
    p.style.grid.setChecked(True)
    p.style.notes.add("arrow", {"x": 290, "y": 3.5, "x1": 318, "y1": 2, "text": "Δ"})
    p.ytab.cellWidget(0, 5).setCurrentIndex(3)
    path = win.save_project(path=str(tmp_path / "proj"))
    assert path.endswith(".resrijan")
    before = win.project_state()
    w2 = MainWindow(synchronous=True)
    w2.open_project(path)
    after = w2.project_state()
    assert after["plot"] == before["plot"] and after["analyze"] == before["analyze"]
    assert w2.pages["plot"].argv() == p.argv()
    w2.close()


def test_fit_page_presets_bounds_and_range(win, tmp_path):
    import numpy as np
    t = np.arange(0, 100.5, 0.5)
    f = tmp_path / "msd.csv"
    f.write_text("t,msd\n" + "\n".join(f"{a},{6 * 0.3 * a + 0.1}" for a in t))
    p = win.pages["fit"]
    win.show_page("fit")
    p.auto.setChecked(False)
    p.open_path(str(f))
    p.preset.setCurrentIndex(p.preset.findData("msd3d"))
    assert [r["name"] for r in p._rows()] == ["D", "c"] and p._rows()[0]["lo"] == "0"
    p.preview()
    assert "0.3" in p.ptab.item(0, 5).text()
    x0, x1, lo, hi, _ = p._map
    p.pick.setChecked(True)
    for v in (10, 90):
        p._picked(x0 + (v - lo) / (hi - lo) * (x1 - x0), 3)
    a = p.argv()
    assert a[a.index("-m") + 1] == "msd3d" and abs(float(a[a.index("--range") + 1].split(":")[0]) - 10) < 1
    p.expr.setText("6*D*x")                      # own formula: the preset is dropped, the table follows
    assert p.preset.currentData() == "" and [r["name"] for r in p._rows()] == ["D"]
    p.out.setText(str(tmp_path / "res"))
    p.formats.set_value("png")
    p.save()
    assert (tmp_path / "res_params.csv").exists()


def test_analyze_page_deconvolution_options(win, tmp_path):
    p = win.pages["analyze"]
    p.pk_mode.setCurrentIndex(p.pk_mode.findData("components"))
    p.ncomp.setValue(4)
    p.fr_lo.setText("1500")
    p.fr_hi.setText("1700")
    p.cwin.setValue(10)
    p.w_hi.setText("40")
    a = p.argv()
    assert a[a.index("--components") + 1] == "4" and a[a.index("--fit-range") + 1] == "1500:1700"
    assert a[a.index("--center-window") + 1] == "10" and a[a.index("--fwhm-range") + 1] == "0:40"


def test_data_file_follows_between_plot_analyze_fit(win, tmp_path):
    f = tmp_path / "shared.csv"
    f.write_text("t,a,b\n" + "\n".join(f"{i},{i * i},{-i}" for i in range(20)))
    win.show_page("plot")
    win.pages["plot"].auto.setChecked(False)
    win.pages["plot"].open_path(str(f))
    for key in ("analyze", "fit", "plot"):
        win.pages[key].auto.setChecked(False)
        win.show_page(key)
        assert win.pages[key].data.text() == str(f)
    assert [win.pages["fit"].ylist.item(i).text() for i in range(win.pages["fit"].ylist.count())] == ["a", "b"]


def test_digitize_results_send_data_to_fit(win, tmp_path):
    d = win.pages["digitize"]
    d.open_path(str(EX / "04_scatter_errorbars" / "scatter_err.png"))
    d.out.setText(str(tmp_path / "dg"))
    d.formats.set_value("png")
    d.run()
    assert all(b.isEnabled() for b in d.b_send)
    win.pages["fit"].auto.setChecked(False)
    d.send_data("fit")
    assert win.stack.currentWidget() is win.pages["fit"]
    assert win.pages["fit"].data.text().endswith("_data.csv") and win.pages["fit"].ylist.count() == 2
