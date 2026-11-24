"""Screenshots of the GUI for the documentation (docs/images/gui_*.png).

    QT_QPA_PLATFORM=offscreen python tools/gui_screenshots.py

Uses a temporary settings folder, so your own GUI settings are not touched."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
IMG = ROOT / "docs" / "images"
TMP = Path(tempfile.mkdtemp(prefix="resrijan_shots_"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["MPLBACKEND"] = "Agg"
os.environ["XDG_CONFIG_HOME"] = str(TMP / "config")
os.environ["RESRIJAN_TEMPLATES"] = str(TMP / "templates")

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from resrijan.gui import theme  # noqa: E402
from resrijan.gui.mainwindow import MainWindow  # noqa: E402

app = QApplication([])
theme.apply(app)
w = MainWindow(synchronous=True)
w.resize(1440, 900)
w.show()


def pump(sec=0.4):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()


def shot(name, width=1280):
    pump()
    p = IMG / f"gui_{name}.png"
    w.grab().save(str(p))
    im = Image.open(p).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(p, optimize=True)
    print("written", p)


# 1 · Digitize: manual calibration – x and y ticks clicked on a bitmap (positions of the real ticks)
d = w.pages["digitize"]
d.open_path(str(EX / "02_ir_spectrum" / "ir_spectrum.png"))
d.b_picky.setChecked(True)
d.picks["x"] = [(183.5, 551.5, 4000.0), (659.5, 551.5, 2000.0), (897.5, 551.5, 1000.0)]
d.picks["y"] = [(183.5, 551.5, 0.0), (183.5, 253.5, 0.6), (183.5, 55.5, 1.0)]
d._draw_overlays()
d._update_cal_strings()
d._update_hint()
shot("digitize_calibration")
d.clear_picks()
d.b_picky.setChecked(False)

# 1b · Digitize results on a vector figure
d.open_path(str(EX / "09_multipanel_page" / "multipanel_page.pdf"))
d.out.setText(str(TMP / "out"))
d.template.set_value("acs")
d.run()
d.rtabs.setCurrentIndex(0)
shot("digitize_results")

# 2 · Plot
w.show_page("plot")
p = w.pages["plot"]
p.open_path(str(EX / "10_plot_your_data" / "diffusion.csv"))
p.kind.setCurrentText("errorbar")
p.xlabel.setText("T (K)")
p.ylabel.setText("D (10$^{-9}$ m$^2$ s$^{-1}$)")
p.preview()
shot("plot")

# 3 · Compose
w.show_page("compose")
w.pages["compose"].example()
shot("compose")

# 4 · Templates
w.show_page("templates")
pump(0.6)
shot("templates")

# 5 · Inspect
w.show_page("inspect")
i = w.pages["inspect"]
i.out.setText(str(TMP / "ruler" / "hrtem"))
i.dpi.setValue(150)
i.open_path(str(EX / "12_hrtem_insets" / "hrtem_insets.pdf"))
shot("inspect")

# 6 · Settings
w.show_page("settings")
shot("settings")
sys.exit(0)
