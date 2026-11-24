# 15 · Python API

Everything the command line does is available from Python, which is handy in Jupyter notebooks and analysis scripts.

## Digitise

```python
from resrijan import digitize, write_outputs

panels = digitize("examples/01_line_plot/line_multi.pdf")      # list of Panel objects
p = panels[0]
print(p.kind, p.mode, p.xlim, p.ylim)                          # line vector (0.0, 10.0) (-1.5, 2.0)

for s in p.series:                                             # line / scatter
    print(s.name, s.kind, s.color_rgb, len(s.x))
    # s.x, s.y               data coordinates (NumPy arrays)
    # s.yerr_lo, s.yerr_hi   error-bar lengths (minus / plus) or None

# bar charts:      p.bars   -> Bar(category, value, err_plus, err_minus, annotated, color)
# heat maps:       p.grid   -> Grid(x, y, z, filled, lo, hi)
# micrographs:     p.micro  -> MicroResult(nm_per_px, bar, particles)
# notes:           p.notes  -> [{"level": "warn", "code": ..., "msg": ...}, ...]

write_outputs(panels, "out/", template="acs", formats=["pdf", "svg", "png"])
```

`digitize()` takes the same options as the command line: `pages=[0]` (0-based), `region=(x0, y0, x1, y1)`, `dpi=600`, `kind="auto"`, `xscale`/`yscale`, `xcal="px:val,px:val"`, `ycal=...`, `scale="100=50 nm"` and `prefer="vector"`.

## Into pandas

```python
import pandas as pd
df = pd.DataFrame({"x": p.series[0].x, "y": p.series[0].y})
```

## Plot

```python
from resrijan.plot.engine import figure, save
import numpy as np

t = np.linspace(0, 6, 200)
panels = [
    {"type": "line", "series": [{"x": t, "y": np.exp(-t), "label": "fit"}],
     "xlabel": "t (ps)", "ylabel": "C(t)", "yscale": "log"},
    {"type": "image", "data": "examples/08_micrograph/micrograph_tem.png", "nm_per_px": 0.5},
    {"type": "bar", "categories": ["A", "B", "C"], "values": [3.2, 5.1, 4.4], "errors": [0.2, 0.3, 0.2]},
]
fig, axes, layout = figure(panels, template="natchem", width="double")
save(fig, "figure1", ["pdf", "svg", "tiff"])
```

`axes` are ordinary matplotlib axes, so you can add anything before saving:

```python
axes[0].axvline(2.0, color="0.5", lw=0.5, ls=":")
```

## Lower-level pieces

| module | use |
|---|---|
| `resrijan.io.loader` | `load(path)` → pages with rendering and vector access |
| `resrijan.detect.axes` / `resrijan.detect.vector` | find axes, ticks, labels and calibrations |
| `resrijan.detect.calibration` | `calibrate(axis, positions, values)` (RANSAC, linear or log) |
| `resrijan.extract.curves` / `vector_series` / `bars` / `heatmap` / `micrograph` | the extractors |
| `resrijan.plot.templates` | `get("acs").rc()` → matplotlib rcParams for a journal |
| `resrijan.plot.layout` | `auto_layout(aspects, width_mm, max_height_mm)` |

Next: [16 · Image figures](16-image-figures.md)

That is the end of the basic series. The accuracy figures are in [`validation/RESULTS.md`](../../validation/RESULTS.md), and how to contribute is in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
