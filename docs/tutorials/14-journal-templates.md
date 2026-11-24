# 14 · Journal templates

```bash
resrijan templates
```

| key | journal(s) | widths (mm) | lettering | panel label |
|---|---|---|---|---|
| `natchem` | Nature Chemistry, Nature Portfolio | 89 / 120 / 183, max height 170 | Arial/Helvetica 5–7 pt | **a** |
| `acs` (`jacs`, `jpcl`, `jpcb` …) | ACS journals | 82.6 / 120 / 177.8 | Arial/Helvetica 7–8 pt | **(a)** |
| `aps` (`prl`, `prb` …) | Physical Review | 86 / 120 / 178 | Times 8–9 pt, STIX maths | (a) |
| `jcp` (`aip`) | J. Chem. Phys. and other AIP journals | 85 / 120 / 170, max height 211 | Arial ≥ 8 pt | (a) |
| `science` | Science, Science Advances | 57 / 121 / 184 | Helvetica/Myriad 6–7 pt | **A** |
| `pnas` | PNAS | 87 / 114 / 178, max height 225 | Arial 6.5–7.5 pt | **A** |
| `rsc` (`pccp`, `chemsci`) | RSC journals | 83 / 171 | Arial 7 pt | **(a)** |
| `presentation` | slides, posters | 120 / 240 | 12–14 pt | a |

The widths come from each publisher's author guidelines. Guidelines change, so check the current ones before submission.

## Writing your own template

A template is a small YAML file. Copy one of [`resrijan/templates/`](../../resrijan/templates) into `~/.config/resrijan/templates/` (or a folder named in `$RESRIJAN_TEMPLATES`) and edit it:

```yaml
name: My group style
key: mygroup                     # use with -t mygroup
aliases: [group]
widths_mm: {single: 85, double: 175}
max_height_mm: 220
font:
  family: sans-serif             # or serif
  names: [Arial, Helvetica, Liberation Sans, DejaVu Sans]   # first installed one is used
  size: 8
  tick: 7
  label: 8
  legend: 7
mathtext: dejavusans             # stix for Times-like maths
panel_label: {format: "({})", case: lower, weight: bold, size: 9}
axes: {linewidth: 0.75, tick_direction: in, tick_length: 3.5, minor_length: 2,
       tick_width: 0.75, spines: [left, bottom, top, right], mirror_ticks: true}
lines: {linewidth: 1.2, markersize: 4, capsize: 2, errorbar_lw: 0.75}
palette: ["#000000", "#D62728", "#1F77B4", "#2CA02C", "#FF7F0E", "#9467BD"]
cmap: {sequential: viridis, diverging: RdBu_r}
export: {dpi: 600}
```

You can also pass a path directly: `-t ./mygroup.yaml`.

## Fonts on Ubuntu

Arial, Helvetica and Times are not installed on Ubuntu by default. ReSrijan uses the first font in `names` that is installed, so Liberation Sans or Liberation Serif stand in; they have identical metrics, so the text takes up exactly the same space. Exported SVGs still name *Arial, Helvetica, …* first, so the intended font is used wherever the file is opened. For the real fonts: `sudo apt install ttf-mscorefonts-installer`.

Next: [15 · Python API](15-python-api.md)
