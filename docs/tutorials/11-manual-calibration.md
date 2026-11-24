# 11 · When automatic reading fails

Every problem shows up in the report, so read the notes there first (or run with `-v`). The table below covers the common ones.

| note in the report | cause | fix |
|---|---|---|
| `No numeric x-tick labels were read` | unusual font, very low resolution, labels touching other text | manual calibration (below) |
| `x-label value … is inconsistent … ignored` | one label misread | usually harmless: the other labels carry the fit |
| `x-axis calibrated from only 2 labels` | only two labels readable | check the overlay; add a manual calibration if in doubt |
| `No plot axes found` | no axis lines (ggplot-style panels), or several figures on one page | `--region` to crop, `--type`, or manual calibration |
| `Filled map without a detectable colour bar` | no colour bar, or one far from the plot | the values cannot be recovered; only the image is redrawn |
| `No scale bar found` | micrograph without a bar, or the bar is part of the image | `--scale "px=value unit"` |

## 1. See the pixel coordinates

```bash
resrijan inspect figure.png
```

This prints facts about the file (pages, vector content, embedded images) and writes `figure_p1_ruler.png`: the page with a pixel grid on it. Zoom in and note the pixel positions of two ticks on each axis.

## 2. Or click them

On a desktop with a display:

```bash
resrijan pick figure.png
```

Click two or more ticks on the x-axis and press Enter, then do the same on the y-axis. Type each tick's value when asked. It prints the options to use:

```text
  --xcal "212.30:0,955.60:20" --ycal "618.70:0.001,43.10:1"
```

## 3. Run with a manual calibration

```bash
resrijan digitize figure.png --xcal "212.3:0,955.6:20" --ycal "618.7:0.001,43.1:1" --yscale log
```

A manual calibration replaces the automatic one for that axis. Everything else (series separation, checks, replot) works as usual.

## Other options

* `--type line|scatter|bar|heatmap|contourf|micrograph` skips automatic type detection.
* `--prefer raster` ignores vector content. Use it if a PDF's vector drawing is broken or decorative.
* `--dpi 1200` renders vector pages at a higher resolution for the image steps (OCR, overlays).
* `--max-series 20` allows more than 12 colours.
* `--xlabel` and `--ylabel` set the axis titles of the replot.

Next: [12 · Plot your own data](12-plot-your-data.md)
