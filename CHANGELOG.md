# Changelog

## 0.6.0 — 2026-11-25

**Correct the data by hand**
* Data editor in the GUI (Digitize results → **Edit data…**, or File → Edit data file…): the points are drawn over the original plot; move, add and delete points (one by one or in a box), type exact values, split, merge, rename and delete series, with undo/redo.
* Saving writes `*_data_edited.csv` (same format as `*_data.csv`), a JSON log of every change, and a replot in the panel's style. The original data are kept.

**Analysis** (`resrijan analyze`, GUI page **Analyze**, `resrijan.analysis`)
* Unit conversion (nm, µm, cm⁻¹, eV, THz; optional intensity Jacobian), cropping, Savitzky–Golay or moving-average smoothing, ALS / polynomial / end-point baselines, normalisation (max, area, 0–1).
* Peak fitting (Gaussian, Lorentzian, pseudo-Voigt with fitted Lorentzian fraction) at automatic or given positions, with a linear background; standard errors for centre, height, FWHM and area; R² and RMS residual.
* Areas over x ranges. Outputs: processed data, peak table, JSON summary, and a journal-style figure with components and residuals.
* GUI: live preview, peak table with errors, and peaks placed by clicking on the preview.

* Deconvolution of overlapping bands: `--peaks shoulders` (second-derivative minima find hidden bands), `--components N`, `--fit-range`, `--center-window`, `--fwhm-range`; each component's share of the area (%) with its error. GUI: the same in the Analyze page.

**Curve fitting** (`resrijan fit`, GUI page **Fit**, `resrijan.curvefit`)
* Any formula in x (checked before use) or a preset: 1–3 exponentials, stretched exponential (KWW), exponential + KWW, damped oscillation, MSD (1-D, 2-D, 3-D, anomalous, ballistic start), linear, quadratic, power law, Arrhenius, VFT, Gaussian, Lorentzian, logistic, Hill.
* Starting values, lower/upper bounds and fixed constants per parameter; full or custom fit range; weights from an uncertainty column; several series fitted at once; multi-start bounded least squares.
* Standard errors, R², reduced χ², flags for constants that end at a bound; derived quantities (e.g. ⟨τ⟩ = (τ/β)Γ(1/β), D in other units) with errors propagated through the covariance matrix.
* Outputs: parameter table (one row per series), fitted curves, JSON with covariances, and a figure with residuals (fit range shaded). GUI: parameter table, fit range set by clicking, live preview.

**Styling**
* `plot`: `--linestyles`, `--markers`, `--linewidth`, `--markersize`, `--legend` (any position, `outside right`, `outside top`, `none`), `--legend-frame`, `--legend-cols`, `--grid`, `--font`, `--font-scale`, `--line-scale`, `--text` and `--arrow` labels (data or axes coordinates, optional colour).
* Compose specs: the same keys per panel, and `font`, `font_scale`, `line_scale` for the figure.
* GUI Plot page: line and marker per series, and a **Look** box (legend, sizes, font, scale, grid, text labels and arrows with the symbol palette).

**Projects**
* File → Save/Open project (`.resrijan`, JSON): every page's state – figure, region, clicked ticks, options, plot look, analysis settings, compose spec. Paths inside the project folder are stored relative to it.

**Other**
* GUI: Plot, Analyze and Fit share the data file – open it once and it follows you between the pages; the Digitize results send a panel's data (edited, if corrected) to Plot, Analyze or Fit with one click.
* `resrijan doctor` checks the installation (libraries, OCR, Ghostscript, a test window). On Windows the GUI starts through a launcher that logs to `%LOCALAPPDATA%\ReSrijan\logs\gui.log` and shows a message instead of closing silently when something is wrong.
* Data files with a `kind` column (`markers`/`line`) are plotted with markers or lines accordingly.
* Tutorials 19 (analysis, deconvolution) and 20 (curve fitting), examples `15_analysis` and `16_curve_fit`; tutorials 12 and 18 extended.

## 0.5.0 — 2026-11-25
* **Graphical interface** (`pip install "resrijan[gui]"`, then `resrijan gui` or `resrijan-gui`): a dark Qt interface with every command and option of the CLI.
  * Digitize, with a page preview, region drawing and tick clicking for manual calibration, and a results browser (replots, overlays, data, notes, combined figure, report).
  * Plot, with column and error-column pickers and a live preview.
  * Compose, a YAML editor with a preview.
  * Templates: browse with a sample figure; import (validated), duplicate, edit and delete your own.
  * Inspect, and Settings (defaults, output folder, application-menu entry for Linux).
  * Each page shows the equivalent `resrijan` command; the GUI runs the CLI's own parser and functions, so both give identical results.
* CLI: commands are split into reusable `run_*` functions and `build_parser()`; new `gui` command.
* GUI title boxes: a palette of Greek letters, mathematical symbols and units; superscript and subscript buttons; a live preview that flags formulas that cannot be drawn.
* Colours: a colour per series in Plot and a title colour in Plot and Digitize (CLI: `plot --colors`, `plot/digitize --label-color`; invalid colours are refused with a clear message).
* Image figures: bitmaps drawn through a transparency mask (3-D AFM renderings written by Cairo) keep their white background instead of turning black, and are no longer cropped; text placed over an image keeps its size relative to the image.
* Tutorial 18 (the graphical interface).

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
