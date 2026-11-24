# Examples

Each folder holds an input figure drawn from known data and is used by one tutorial. The commands in [`docs/tutorials/`](../docs/tutorials/README.md) write their output into an `output/` folder next to the input, which git ignores.

| folder | input | tutorial |
|---|---|---|
| `01_line_plot` | `line_multi.png`, `line_multi.pdf` | [Line plots](../docs/tutorials/01-line-plots.md) |
| `02_ir_spectrum` | `ir_spectrum.png` | [Spectra and reversed axes](../docs/tutorials/02-spectra.md) |
| `03_log_axis` | `log_decay.eps`, `log_decay.png` | [Logarithmic axes](../docs/tutorials/03-log-axes.md) |
| `04_scatter_errorbars` | `scatter_err.png` | [Scatter plots with error bars](../docs/tutorials/04-scatter-errorbars.md) |
| `05_bar_chart` | `bar_err.svg`, `bar_err.png` | [Bar charts](../docs/tutorials/05-bar-charts.md) |
| `06_heatmap_2dir` | `heatmap_2dir.png`, `heatmap_2dir.pdf` | [Heat maps and 2D-IR](../docs/tutorials/06-heatmaps-2dir.md) |
| `07_contour` | `contourf_pes.pdf` | [Filled contour plots](../docs/tutorials/07-contour-plots.md) |
| `08_micrograph` | `micrograph_tem.png` | [Micrographs](../docs/tutorials/08-micrographs.md) |
| `09_multipanel_page` | `multipanel_page.pdf` | [Multi-panel pages](../docs/tutorials/09-multipanel-pages.md) |
| `10_plot_your_data` | `correlation.csv`, `diffusion.csv`, `2dir_grid.csv` | [Plot your own data](../docs/tutorials/12-plot-your-data.md) |
| `11_compose_figure` | `figure_natchem.yaml` + `data/` | [Compose a multi-panel figure](../docs/tutorials/13-compose-figures.md) |

Run everything and refresh the tutorial pictures with:

```bash
python tools/build_examples.py
```

The input figures are regenerated (together with many more test cases and their ground truth) by `python validation/make_testset.py testset`.
