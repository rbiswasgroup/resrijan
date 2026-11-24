# Changelog

## 0.4.0 — 2026-11-24

First public release.

**Reading figures**
* Input: PDF, EPS, EPSI, PS, SVG/SVGZ and bitmaps (PNG, JPG, TIFF 8/16-bit and float, BMP, GIF, WebP). Several panels per page are found and processed together; `--page` and `--region` select parts of a paper.
* Vector files are read from their drawing commands: curves, symbols, bars and tick labels are exact. Embedded images are taken at their native resolution; clip paths are honoured (SVGs with clip paths or masks go through `rsvg-convert`).
* Bitmaps: sub-pixel tick location, OCR of tick labels with RANSAC calibration, colour separation in CIELAB, peak tracing along steep flanks, symbol template matching.
* Axes: linear, logarithmic and reversed axes; categorical axes; y labels on the right; axes shared between neighbouring panels; unnumbered y axes (relative values); stacked spectra without a y axis; framed inset plots.
* Text: sub- and superscripts and drawn minus signs become mathtext; title colour and weight are kept; text drawn as outlines (EPS converted by Ghostscript) is read by OCR.

**Figure types**
* Line and scatter plots with error bars; series named from the legend or from labels placed next to the points; marker shape, size and colours kept.
* Bar charts: categories, error bars, printed values cross-checked against the drawn heights, stray shapes flagged.
* Heat maps and 2D-IR spectra (colour-bar inversion), filled contours (discrete levels), contour-line panels such as 2D NMR (every loop exact, with peak labels and pair titles).
* Micrographs: scale bar, pixel size, particle sizing.
* Image figures: photographs and micrographs as frames; magnified insets located in their parent image (position and magnification); the microscope's own burnt-in scale bar; HRTEM lattice fringes (FFT refined by a zoomed DFT, with ±) checked against printed d-spacings; drawn arrows and line pairs measured, and time-lapse rows turned into data series.

**Output**
* CSV data, an HTML report overlaying the extraction on the original, and an anomaly report (misread labels, uneven ticks, clipping, occlusion, colour-map saturation, JPEG artefacts, data resolution).
* Replots as editable PDF/SVG/EPS or PNG/TIFF in journal styles: `natchem`, `acs`, `aps`, `jcp`, `science`, `pnas`, `rsc`, `presentation`, or your own YAML template. Replots keep the source's proportions (marker and line sizes, minor ticks, column layout of multi-panel pages).
* `resrijan plot` and `resrijan compose` build figures from your own data with automatic multi-panel layout.

**Quality**
* Ground-truth validation suite (`validation/`), 18 tutorials with example files built from simulated data, CI on Python 3.10, 3.12 and 3.13.
