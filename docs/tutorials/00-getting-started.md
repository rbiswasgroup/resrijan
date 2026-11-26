# 0 · Installation and first run

## Install on Windows 10/11

Download **ReSrijan-0.6.0-Setup.exe** from the [latest release](https://github.com/rbiswasgroup/resrijan/releases/latest) and run it (Windows may warn "Windows protected your PC": **More info → Run anyway**). Everything is included; no administrator rights are needed. Start **ReSrijan** from the Start menu for the graphical interface ([tutorial 18](18-gui.md)), or **ReSrijan command prompt** for the commands used in these tutorials. **ReSrijan - troubleshoot** runs the same check as `resrijan doctor` below. Windows is slower than Linux; see [Limitations](../../README.md#limitations) for an antivirus exclusion that helps.

## Install on Linux (Ubuntu 22.04 / 24.04)

```bash
git clone https://github.com/rbiswasgroup/resrijan.git
cd resrijan
./install.sh
```

`install.sh` installs the system tools with `apt`: Tesseract (OCR), Ghostscript (EPS/PS), librsvg (SVG fall-back) and the Liberation fonts, which have the same metrics as Arial and Times. It then puts ReSrijan into a private virtual environment and links the `resrijan` command into `~/.local/bin`.

To install it by hand instead:

```bash
sudo apt install tesseract-ocr ghostscript librsvg2-bin fonts-liberation
python3 -m venv ~/.venvs/resrijan && source ~/.venvs/resrijan/bin/activate
pip install .            # or: pip install -e ".[dev]" for development
```

For real Arial and Times New Roman in exported figures, also run `sudo apt install ttf-mscorefonts-installer`.

## Check the setup

```bash
resrijan --version
resrijan doctor
resrijan templates
```

`resrijan doctor` checks everything ReSrijan needs (the Python libraries, Tesseract, Ghostscript and a test window) and ends with "Everything needed works" or lists what is missing.

`resrijan templates` lists every journal style and shows which font your system will actually use for it.

## Your first extraction

```bash
cd examples/01_line_plot
resrijan digitize line_multi.png
```

```text
  p1_a     line        raster          4 series               warnings: 0  errors: 0

Report: line_multi_resrijan/line_multi_report.html
```

Every panel found gets an id: `p1_a` means page 1, first panel. The folder `line_multi_resrijan/` now contains:

| file | what it is |
|---|---|
| `line_multi_report.html` | **open this first**: the original with the extracted data drawn on top, the calibration, any warnings, the replot |
| `line_multi_p1_a_data.csv` | the data, one row per point: `series,x,y,yerr_minus,yerr_plus,kind,source` |
| `line_multi_p1_a_meta.json` | axis calibrations, labels used, residuals, resolution and every note |
| `line_multi_p1_a_overlay.png` | the verification picture on its own |
| `line_multi_p1_a_replot.{pdf,svg,png}` | the figure rebuilt from the extracted numbers in the chosen journal style |

## Useful options

| option | meaning |
|---|---|
| `-o DIR` | output folder |
| `-t natchem` | replot template (`acs`, `aps`, `jcp`, `science`, `pnas`, `rsc`, `presentation`, or a YAML file) |
| `--width single\|double\|<mm>` | replot width |
| `-f pdf,svg,eps,png,tiff` | replot formats |
| `--page 3` | only page 3 of a PDF |
| `--region x0,y0,x1,y1` | only part of the page (pixels, or 0–1 page fractions) |
| `--type auto\|line\|scatter\|bar\|heatmap\|contourf\|micrograph` | force the figure type |
| `--xlabel` / `--ylabel` | axis titles for the replot |
| `-v` | print every note (information, warnings, errors) |

Next: [1 · Line plots](01-line-plots.md)
