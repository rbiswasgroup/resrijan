# 10 · SVG, EPS and PS files

All three are vector formats, so ReSrijan reads the exact drawing coordinates, just as with PDF.

| format | how it is opened | needs |
|---|---|---|
| PDF | directly (PyMuPDF) | — |
| EPS, EPSI, EPSF, PS | converted to PDF with Ghostscript (bounding box respected, vectors kept) | `ghostscript` |
| SVG, SVGZ | converted to PDF with MuPDF; falls back to `rsvg-convert`, then Inkscape | `librsvg2-bin` (only for the fall-back) |

```bash
resrijan digitize figure.svg
resrijan digitize figure.svgz
resrijan digitize figure.eps
resrijan digitize figure.ps --page 2
```

## Real text vs. outlined text

The two ways a vector file can store its lettering behave differently.

* **Real text** (Inkscape and Illustrator by default; matplotlib with `svg.fonttype: none`): tick labels, legends and titles are read exactly.
* **Text converted to outlines** (matplotlib's default SVG; "Convert text to paths" in Inkscape; many publisher PDFs): the letters are just shapes. ReSrijan groups the small filled shapes into words and reads them by OCR on a high-resolution rendering. The report then says: *"Tick labels are not stored as text in this file; read by OCR."* The data themselves are still exact.

In the validation set, SVG files of both kinds give results identical to the PDF versions: 0.011–0.026 % RMS for lines, exact values for symbols and bars.

## Inkscape figures

Figures assembled or retouched in Inkscape are often nested in groups with transforms, made of many separate slices, or contain stray objects. ReSrijan flattens all the transforms. It merges bars built from slices, and it reports shapes that do not fit the chart (see the *stray shape* warning in [tutorial 5](05-bar-charts.md)), which is useful for spotting editing accidents before submission.

Next: [11 · When automatic reading fails](11-manual-calibration.md)
