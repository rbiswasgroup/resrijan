# ReSrijan validation against ground truth

Errors are in % of the full axis range (lines: perpendicular distance to the true curve; maps: |z − z_true| / colour range). Worst series per panel is reported.

## Line and scatter plots

| file | panel | mode | series found | legend names | RMS % | p95 % | coverage % | time s |
|---|---|---|---|---|---|---|---|---|
| line_multi.png | a | raster | 4/4 | 4/4 | 0.112 | 0.181 | 99 | 5.7 |
| line_multi.jpg | a | raster | 4/4 | 4/4 | 0.122 | 0.194 | 99 | 4.3 |
| line_lowres.png | a | raster | 4/4 | 4/4 | 0.324 | 0.420 | 94 | 3.3 |
| line_multi.pdf | a | vector | 4/4 | 4/4 | 0.026 | 0.058 | 100 | 1.3 |
| line_multi.eps | a | vector | 4/4 | 4/4 | 0.026 | 0.058 | 100 | 1.2 |
| line_multi.ps | a | vector | 4/4 | 4/4 | 0.026 | 0.058 | 100 | 6.4 |
| ir_spectrum.png | a | raster | 1/1 | 0/1 | 0.084 | 0.148 | 100 | 3.6 |
| ir_spectrum.jpg | a | raster | 1/1 | 0/1 | 0.084 | 0.147 | 100 | 3.0 |
| ir_spectrum.pdf | a | vector | 1/1 | 0/1 | 0.040 | 0.090 | 100 | 1.1 |
| log_decay.png | a | raster | 2/2 | 2/2 | 0.108 | 0.137 | 100 | 3.4 |
| log_decay.pdf | a | vector | 2/2 | 2/2 | 0.011 | 0.018 | 100 | 1.1 |
| log_decay.eps | a | vector | 2/2 | 2/2 | 0.011 | 0.019 | 100 | 1.1 |
| multipanel_page.pdf | a | vector | 2/2 | 0/2 | 0.031 | 0.068 | 100 | 4.6 |
| multipanel_page.pdf | b | vector | 1/1 | 0/1 | 0.012 | 0.020 | 100 | 4.6 |
| multipanel_page.pdf | d | vector | 1/1 | 0/1 | 0.042 | 0.095 | 100 | 4.6 |
| multipanel_page.png | a | raster | 2/2 | 0/2 | 0.043 | 0.067 | 100 | 2.7 |
| multipanel_page.png | b | raster | 1/1 | 0/1 | 0.020 | 0.032 | 100 | 2.7 |
| multipanel_page.png | d | raster | 1/1 | 0/1 | 0.115 | 0.313 | 100 | 2.7 |
| line_multi.svg | a | vector | 4/4 | 4/4 | 0.026 | 0.059 | 100 | 6.5 |
| line_multi_text.svg | a | vector | 4/4 | 4/4 | 0.026 | 0.059 | 100 | 0.9 |
| log_decay.svg | a | vector | 2/2 | 2/2 | 0.011 | 0.019 | 100 | 3.6 |
| log_decay_text.svg | a | vector | 2/2 | 2/2 | 0.011 | 0.019 | 100 | 0.9 |

| file | panel | mode | points recalled % | RMS % | error-bar error % |
|---|---|---|---|---|---|
| scatter_err.png | a | raster | 100 | 0.125 | 0.360 |
| scatter_err.pdf | a | vector | 100 | 0.000 | 0.000 |
| multipanel_page.pdf | c | vector | 100 | 0.000 | nan |
| multipanel_page.png | c | raster | 100 | 0.258 | nan |
| origin_style.png | a | raster | 89 | 1.672 | nan |
| origin_style.jpg | a | raster | 89 | 1.650 | nan |
| origin_style.pdf | a | vector | 100 | 0.000 | nan |
| scatter_err.svg | a | vector | 100 | 0.001 | 0.001 |
| scatter_err_text.svg | a | vector | 100 | 0.001 | 0.001 |

## Heat maps / 2D spectra / filled contours

| file | mode | grid | RMS % | p95 % | p99 % | level exact % | level ±1 % | interpolated % |
|---|---|---|---|---|---|---|---|---|
| heatmap_2dir.png | raster | 452x609 | 0.427 | 0.826 | 1.835 |  |  | 4.5 |
| heatmap_2dir.jpg | raster | 452x609 | 0.747 | 1.072 | 2.251 |  |  | 4.4 |
| heatmap_2dir.pdf | embedded-image | 306x411 | 0.276 | 0.559 | 1.149 |  |  | 0.0 |
| contourf_pes.png | raster |  |  |  |  | 95.6 | 100.00 | 0.0 |
| contourf_pes.pdf | vector |  |  |  |  | 98.8 | 100.00 | 2.0 |
| heatmap_2dir.svg | embedded-image | 306x410 | 0.344 | 0.563 | 1.141 |  |  | 0.0 |
| contourf_pes_text.svg | vector |  |  |  |  | 98.8 | 100.00 | 2.0 |

## Bar charts

| file | mode | bars | categories | max value error % | max error-bar error % |
|---|---|---|---|---|---|
| bar_err.png | raster | 6/6 | 6/6 | 0.148 | 0.302 |
| bar_err.jpg | raster | 6/6 | 6/6 | 0.191 | 0.320 |
| bar_err.pdf | vector | 6/6 | 6/6 | 0.000 | 0.000 |
| bar_err.svg | vector | 6/6 | 6/6 | 0.001 | 0.001 |

## Micrographs

| file | nm/px | scale error % | particles | mean diameter error % | s.d. error % |
|---|---|---|---|---|---|
| micrograph_tem.png | 0.5000 | 0.000 | 60/60 | 0.06 | 0.17 |
| micrograph_tem.jpg | 0.5000 | 0.000 | 60/60 | 0.06 | 0.16 |
| micrograph_tem.tif | 0.5000 | 0.000 | 60/60 | 0.06 | 0.17 |
