# ReSrijan tutorials

Each tutorial uses a ready-made file in [`examples/`](../../examples) and shows the real console output and pictures that ReSrijan produces from it. Every example figure was drawn from known data, so you can see how close the extraction gets; the full accuracy table is in [`validation/RESULTS.md`](../../validation/RESULTS.md).

| # | Tutorial | Example input | What you learn |
|---|---|---|---|
| 0 | [Installation and first run](00-getting-started.md) | — | install on Ubuntu, check the setup, read the HTML report |
| 1 | [Line plots](01-line-plots.md) | `line_multi.png`, `line_multi.pdf` | bitmap vs vector input, series names from the legend, dashed lines |
| 2 | [Spectra and reversed axes](02-spectra.md) | `ir_spectrum.png` | sharp peaks, reversed wavenumber axis, open (L-shaped) axes |
| 3 | [Logarithmic axes](03-log-axes.md) | `log_decay.eps`, `log_decay.png` | 10ⁿ labels, EPS input, the APS template |
| 4 | [Scatter plots with error bars](04-scatter-errorbars.md) | `scatter_err.png` | symbols, overlapping symbols, error-bar ends |
| 5 | [Bar charts](05-bar-charts.md) | `bar_err.svg`, `bar_err.png` | categorical axes, printed values cross-checked, error bars |
| 6 | [Heat maps and 2D-IR spectra](06-heatmaps-2dir.md) | `heatmap_2dir.png`, `heatmap_2dir.pdf` | colour-bar inversion, embedded images, contour overlays |
| 7 | [Filled contour plots](07-contour-plots.md) | `contourf_pes.pdf` | discrete colour levels, open-ended "extend" bands |
| 8 | [Micrographs](08-micrographs.md) | `micrograph_tem.png` | scale bars, pixel size, particle sizing, new scale bar |
| 9 | [Multi-panel pages](09-multipanel-pages.md) | `multipanel_page.pdf` | several panels at once, `--page`, `--region`, combined replot |
| 10 | [SVG, EPS and PS files](10-svg-eps-ps.md) | `bar_err.svg`, `log_decay.eps` | vector formats, outlined text |
| 11 | [When automatic reading fails](11-manual-calibration.md) | any | `inspect`, `pick`, `--xcal/--ycal`, `--scale`, `--type` |
| 12 | [Plot your own data](12-plot-your-data.md) | `examples/10_plot_your_data/*.csv` | `resrijan plot` with journal templates |
| 13 | [Compose a multi-panel figure](13-compose-figures.md) | `figure_natchem.yaml` | YAML figure specs, automatic layout, panel letters |
| 14 | [Journal templates](14-journal-templates.md) | — | built-in templates, writing your own |
| 15 | [Python API](15-python-api.md) | — | using ReSrijan from scripts and notebooks |
| 16 | [Image figures](16-image-figures.md) | `hrtem_insets.pdf`, `timelapse.svg` | HRTEM insets, d-spacing check, time-lapse series, `--scale` |
| 17 | [Tricky axes](17-tricky-axes.md) | `examples/14_tricky_axes/*.pdf` | parity plots, stacked spectra, unnumbered axes, contour pairs, point labels |
| 18 | [The graphical interface](18-gui.md) | any | every command in a window: previews, clicking ticks, data editor, projects |
| 19 | [Analyse spectra and curves](19-analysis.md) | `examples/15_analysis/*.csv` | baseline, smoothing, unit conversion, peak fitting with errors, deconvolution, areas |
| 20 | [Curve fitting](20-curve-fitting.md) | `examples/16_curve_fit/*.csv` | time constants from correlation functions, D from MSD, your own formulas with bounds |

To regenerate every output and picture used here:

```bash
python tools/build_examples.py
```
