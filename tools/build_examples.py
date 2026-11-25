"""Run every example and refresh the tutorial images.

    python tools/build_examples.py            # outputs go to examples/*/output/ (git-ignored)

The pictures used by the tutorials are copied, down-scaled, into docs/images/, and
the console output of each run is saved in docs/_runs/ so the tutorials can quote it.
"""
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
IMG = ROOT / "docs" / "images"
RUNS = ROOT / "docs" / "_runs"
IMG.mkdir(parents=True, exist_ok=True)
RUNS.mkdir(parents=True, exist_ok=True)
ENV = dict(os.environ, PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))

# (folder, command arguments, run name)
JOBS = [
    ("01_line_plot", ["digitize", "line_multi.png", "-o", "output/png", "-v"], "line_png"),
    ("01_line_plot", ["digitize", "line_multi.pdf", "-o", "output/pdf", "-t", "acs", "-v"], "line_pdf"),
    ("02_ir_spectrum", ["digitize", "ir_spectrum.png", "-o", "output", "-v"], "ir"),
    ("03_log_axis", ["digitize", "log_decay.eps", "-o", "output/eps", "-t", "aps", "-v"], "log_eps"),
    ("03_log_axis", ["digitize", "log_decay.png", "-o", "output/png", "-v"], "log_png"),
    ("04_scatter_errorbars", ["digitize", "scatter_err.png", "-o", "output", "-v"], "scatter"),
    ("05_bar_chart", ["digitize", "bar_err.svg", "-o", "output/svg", "-v",
                      "--ylabel", "Rate (mmol h$^{-1}$)"], "bar_svg"),
    ("05_bar_chart", ["digitize", "bar_err.png", "-o", "output/png", "-t", "jcp", "-v"], "bar_png"),
    ("06_heatmap_2dir", ["digitize", "heatmap_2dir.png", "-o", "output/png", "-v"], "heat_png"),
    ("06_heatmap_2dir", ["digitize", "heatmap_2dir.pdf", "-o", "output/pdf", "-v"], "heat_pdf"),
    ("07_contour", ["digitize", "contourf_pes.pdf", "-o", "output", "-v"], "contour"),
    ("08_micrograph", ["digitize", "micrograph_tem.png", "-o", "output", "-v"], "micro"),
    ("09_multipanel_page", ["digitize", "multipanel_page.pdf", "-o", "output", "-t", "natchem", "-v"], "multi"),
    ("10_plot_your_data", ["plot", "correlation.csv", "-x", "t_ps", "-y", "urea_2M,urea_8M,water", "--yscale", "log",
                           "--xlabel", "t (ps)", "--ylabel", "C(t)", "-t", "natchem", "-o", "output/correlation_natchem"], "plot_line"),
    ("10_plot_your_data", ["plot", "diffusion.csv", "--kind", "scatter", "-x", "T_K", "-y", "D_urea,D_water",
                           "--yerr", "err_urea,err_water", "--xlabel", "T (K)",
                           "--ylabel", "D (10$^{-9}$ m$^2$ s$^{-1}$)", "-t", "acs", "-o", "output/diffusion_acs"], "plot_scatter"),
    ("10_plot_your_data", ["plot", "2dir_grid.csv", "--kind", "spectrum2d", "--xlabel", "$\\omega_1$ (cm$^{-1}$)",
                           "--ylabel", "$\\omega_3$ (cm$^{-1}$)", "--clabel", "ΔOD", "-t", "pnas",
                           "-o", "output/2dir_pnas"], "plot_2d"),
    ("11_compose_figure", ["compose", "figure_natchem.yaml"], "compose"),
    ("12_hrtem_insets", ["digitize", "hrtem_insets.pdf", "-o", "output/pdf", "-v"], "hrtem_pdf"),
    ("12_hrtem_insets", ["digitize", "hrtem_insets.png", "-o", "output/png", "-v"], "hrtem_png"),
    ("13_timelapse", ["digitize", "timelapse.svg", "-o", "output/svg", "-v"], "timelapse_svg"),
    ("15_analysis", ["analyze", "ir_spectrum.csv", "--smooth", "savgol:9:3", "--baseline", "als:1e7:0.01",
                     "--peaks", "auto", "--area", "1400:1500", "--xlabel", "Wavenumber (cm$^{-1}$)",
                     "--ylabel", "Absorbance", "-o", "output/ir", "-f", "png,pdf"], "analysis"),
    ("15_analysis", ["analyze", "amide_band.csv", "--baseline", "ends", "--components", "3", "--shape", "gauss",
                     "--fwhm-range", "5:40", "--xlabel", "Wavenumber (cm$^{-1}$)", "--ylabel", "Absorbance",
                     "-o", "output/amide", "-f", "png,pdf"], "deconvolution"),
    ("16_curve_fit", ["fit", "correlation.csv", "-m", "kww", "--xscale", "log", "--xlabel", "t (ps)",
                      "--ylabel", "C(t)", "-o", "output/ccf", "-f", "png,pdf"], "fit_ccf"),
    ("16_curve_fit", ["fit", "msd.csv", "-m", "msd3d", "--range", "20:200", "--derived", "D_cm2_s=D*1e-4",
                      "--xlabel", "t (ps)", "--ylabel", "MSD (Å$^2$)", "-o", "output/msd", "-f", "png,pdf"], "fit_msd"),
    ("13_timelapse", ["digitize", "timelapse.svg", "-o", "output/scaled", "--scale", "100=50 um"], "timelapse_scaled"),
    ("13_timelapse", ["digitize", "timelapse.png", "-o", "output/png", "-v"], "timelapse_png"),
    ("14_tricky_axes", ["digitize", "parity_plot.pdf", "-o", "output/parity", "-v"], "parity"),
    ("14_tricky_axes", ["digitize", "stacked_spectra.pdf", "-o", "output/stacked", "-v"], "stacked"),
    ("14_tricky_axes", ["digitize", "unnumbered_inset.pdf", "-o", "output/inset", "-v"], "inset"),
    ("14_tricky_axes", ["digitize", "contour_pairs.pdf", "-o", "output/contours", "-v"], "contours"),
]

# (source inside examples, image name in docs/images, max width)
SHOTS = [
    ("01_line_plot/line_multi.png", "line_input.png", 700),
    ("01_line_plot/output/png/line_multi_p1_a_overlay.png", "line_overlay.png", 800),
    ("01_line_plot/output/png/line_multi_p1_a_replot.png", "line_replot.png", 700),
    ("01_line_plot/output/pdf/line_multi_p1_a_replot.png", "line_replot_acs.png", 700),
    ("02_ir_spectrum/output/ir_spectrum_p1_a_overlay.png", "ir_overlay.png", 800),
    ("02_ir_spectrum/output/ir_spectrum_p1_a_replot.png", "ir_replot.png", 700),
    ("03_log_axis/output/eps/log_decay_p1_a_replot.png", "log_replot_aps.png", 700),
    ("03_log_axis/output/png/log_decay_p1_a_overlay.png", "log_overlay.png", 800),
    ("04_scatter_errorbars/output/scatter_err_p1_a_overlay.png", "scatter_overlay.png", 800),
    ("04_scatter_errorbars/output/scatter_err_p1_a_replot.png", "scatter_replot.png", 700),
    ("05_bar_chart/bar_err.png", "bar_input.png", 700),
    ("05_bar_chart/output/svg/bar_err_p1_a_replot.png", "bar_replot.png", 700),
    ("05_bar_chart/output/png/bar_err_p1_a_overlay.png", "bar_overlay.png", 800),
    ("06_heatmap_2dir/output/png/heatmap_2dir_p1_a_overlay.png", "heat_overlay.png", 1000),
    ("06_heatmap_2dir/output/png/heatmap_2dir_p1_a_replot.png", "heat_replot.png", 700),
    ("07_contour/output/contourf_pes_p1_a_overlay.png", "contour_overlay.png", 1000),
    ("07_contour/output/contourf_pes_p1_a_replot.png", "contour_replot.png", 700),
    ("08_micrograph/output/micrograph_tem_p1_a_overlay.png", "micro_overlay.png", 700),
    ("08_micrograph/output/micrograph_tem_combined.png", "micro_combined.png", 1000),
    ("09_multipanel_page/multipanel_page.pdf", "multi_input.png", 900),
    ("09_multipanel_page/output/multipanel_page_combined.png", "multi_combined.png", 1000),
    ("10_plot_your_data/output/correlation_natchem.png", "plot_line.png", 700),
    ("10_plot_your_data/output/diffusion_acs.png", "plot_scatter.png", 700),
    ("10_plot_your_data/output/2dir_pnas.png", "plot_2d.png", 700),
    ("11_compose_figure/output/figure_natchem.png", "compose_natchem.png", 1100),
    ("12_hrtem_insets/hrtem_insets.png", "hrtem_input.png", 800),
    ("12_hrtem_insets/output/pdf/hrtem_insets_p1_a_overlay.png", "hrtem_overlay.png", 800),
    ("12_hrtem_insets/output/pdf/hrtem_insets_p1_b_overlay.png", "hrtem_inset_overlay.png", 500),
    ("12_hrtem_insets/output/pdf/hrtem_insets_p1_a_replot.png", "hrtem_replot.png", 800),
    ("13_timelapse/timelapse.png", "timelapse_input.png", 900),
    ("15_analysis/output/ir_analysis.png", "analysis_fit.png", 800),
    ("15_analysis/output/amide_analysis.png", "deconvolution.png", 800),
    ("16_curve_fit/output/ccf_fit.png", "fit_ccf.png", 800),
    ("16_curve_fit/output/msd_fit.png", "fit_msd.png", 800),
    ("13_timelapse/output/svg/timelapse_combined.png", "timelapse_combined.png", 1000),
    ("13_timelapse/output/svg/timelapse_p1_c_overlay.png", "timelapse_overlay.png", 350),
    ("14_tricky_axes/parity_plot.pdf", "parity_input.png", 500),
    ("14_tricky_axes/output/parity/parity_plot_p1_a_replot.png", "parity_replot.png", 600),
    ("14_tricky_axes/stacked_spectra.pdf", "stacked_input.png", 500),
    ("14_tricky_axes/output/stacked/stacked_spectra_p1_a_replot.png", "stacked_replot.png", 600),
    ("14_tricky_axes/unnumbered_inset.pdf", "inset_input.png", 550),
    ("14_tricky_axes/output/inset/unnumbered_inset_p1_b_replot.png", "inset_replot.png", 650),
    ("14_tricky_axes/contour_pairs.pdf", "contours_input.png", 600),
    ("14_tricky_axes/output/contours/contour_pairs_combined.png", "contours_replot.png", 700),
]


def shrink(src: Path, dst: Path, width: int):
    if src.suffix == ".pdf":
        import pymupdf as fitz
        pg = fitz.open(src)[0]
        pix = pg.get_pixmap(dpi=110)
        pix.save(str(dst))
        src = dst
    im = Image.open(src).convert("RGB")
    if im.width > width:
        im = im.resize((width, int(im.height * width / im.width)), Image.LANCZOS)
    im.save(dst, optimize=True)


def main():
    for folder, args, name in JOBS:
        wd = EX / folder
        out = subprocess.run([sys.executable, "-m", "resrijan"] + args, cwd=wd, env=ENV,
                             capture_output=True, text=True)
        text = f"$ resrijan {' '.join(args)}\n{out.stdout}{out.stderr}"
        (RUNS / f"{name}.txt").write_text(text)
        print(f"[{out.returncode}] {folder}: resrijan {' '.join(args[:2])}")
    for src, dst, w in SHOTS:
        p = EX / src
        if p.exists():
            shrink(p, IMG / dst, w)
        else:
            print("missing:", p)
    import make_hero
    make_hero.main()


if __name__ == "__main__":
    main()
