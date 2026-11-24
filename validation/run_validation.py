"""End-to-end validation: digitise every test figure and score it against ground truth.

    python validation/make_testset.py  testset/
    python validation/run_validation.py testset/  results/

Writes results/validation.md, results/validation.json and the full ReSrijan output
(CSV, replots, overlays, HTML report) for every file under results/<file>/.
"""
import json
import os
import sys
import time

import numpy as np
from scipy.interpolate import RegularGridInterpolator

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from score import match_series, point_errors  # noqa: E402
from resrijan.pipeline import digitize, write_outputs  # noqa: E402
from resrijan.extract.curves import densify  # noqa: E402

TS = sys.argv[1] if len(sys.argv) > 1 else "testset"
OUT = sys.argv[2] if len(sys.argv) > 2 else "results"
os.makedirs(OUT, exist_ok=True)

CASES = [
    "line_multi.png", "line_multi.jpg", "line_lowres.png", "line_multi.pdf", "line_multi.eps", "line_multi.ps",
    "ir_spectrum.png", "ir_spectrum.jpg", "ir_spectrum.pdf",
    "log_decay.png", "log_decay.pdf", "log_decay.eps",
    "scatter_err.png", "scatter_err.pdf",
    "heatmap_2dir.png", "heatmap_2dir.jpg", "heatmap_2dir.pdf",
    "contourf_pes.png", "contourf_pes.pdf",
    "micrograph_tem.png", "micrograph_tem.jpg", "micrograph_tem.tif",
    "multipanel_page.pdf", "multipanel_page.png",
    "origin_style.png", "origin_style.jpg", "origin_style.pdf",
    "line_multi.svg", "line_multi_text.svg", "log_decay.svg", "log_decay_text.svg",
    "scatter_err.svg", "scatter_err_text.svg", "heatmap_2dir.svg", "contourf_pes_text.svg",
    "bar_err.png", "bar_err.jpg", "bar_err.pdf", "bar_err.svg",
]

if os.environ.get("CASES"):
    CASES = [c for c in CASES if any(k in c for k in os.environ["CASES"].split(","))]


def series_xy(p, s):
    px, py = s.px, s.py
    if s.kind == "line" and s.source == "vector":
        px, py = densify(px, py, 1.0, s.style.get("segments"))
    return p.box.xcal.to_data(px), p.box.ycal.to_data(py)


def score_lines(p, t):
    ext = [(s.name,) + series_xy(p, s) for s in p.series]
    res = match_series(ext, t["series"], t["xlim"], t["ylim"], t.get("xscale", "linear"), t.get("yscale", "linear"))
    worst = max((v["rms_pct"] for v in res.values() if v), default=np.nan)
    p95 = max((v["p95_pct"] for v in res.values() if v), default=np.nan)
    cov = min((v["coverage_pct"] for v in res.values() if v), default=0)
    found = sum(v is not None for v in res.values())
    names = sum(1 for k, v in res.items() if v and v["matched"] == k)
    return {"series_found": f"{found}/{len(res)}", "names_from_legend": f"{names}/{len(res)}",
            "rms_pct": worst, "p95_pct": p95, "coverage_pct": cov}


def score_points(p, t):
    out = {"recall": [], "rms": [], "err": []}
    for k, tv in t["series"].items():
        best = None
        for s in p.series:
            e = point_errors(s.x, s.y, tv["x"], tv["y"], t["xlim"], t["ylim"])
            if e and (best is None or e["recall_pct"] > best[1]["recall_pct"]):
                best = (s, e)
        if best is None:
            out["recall"].append(0); continue
        s, e = best
        out["recall"].append(e["recall_pct"]); out["rms"].append(e["rms_pct"] or np.nan)
        if "yerr" in tv and s.yerr_hi is not None:
            idx = e["idx"][e["found"]]
            te = np.asarray(tv["yerr"])[e["found"]]
            d = np.abs(np.asarray(s.yerr_hi)[idx] - te) / (t["ylim"][1] - t["ylim"][0]) * 100
            out["err"].append(np.nanmean(d))
    r = {"points_recall_pct": min(out["recall"]), "rms_pct": max(out["rms"]) if out["rms"] else np.nan}
    if out["err"]:
        r["errorbar_err_pct"] = max(out["err"])
    return r


def score_grid(p, t):
    g = p.grid
    Z = np.array(t["z"]); X = np.array(t["x"]); Y = np.array(t["y"])
    f = RegularGridInterpolator((Y, X), Z, bounds_error=False, fill_value=np.nan)
    YY, XX = np.meshgrid(g.y, g.x, indexing="ij")
    zt = f(np.c_[YY.ravel(), XX.ravel()]).reshape(YY.shape)
    ok = np.isfinite(zt)
    if "levels" in t:
        lv = np.asarray(t["levels"]); step = lv[1] - lv[0]
        zt_c = np.clip(zt, lv[0], lv[-1] + 1e-9)
        lt = np.floor((zt_c - lv[0]) / step + 1e-9)
        le = np.floor((np.where(np.isfinite(g.lo), g.lo, lv[-1]) - lv[0]) / step + 1e-6)
        agree = (lt == le)[ok]
        near = (np.abs(lt - le) <= 1)[ok]
        return {"level_exact_pct": 100 * agree.mean(), "level_within1_pct": 100 * near.mean(),
                "interpolated_pct": 100 * g.filled.mean()}
    rng = t.get("vmax", np.nanmax(Z)) - t.get("vmin", np.nanmin(Z))
    e = np.abs(g.z - zt)[ok] / rng * 100
    return {"rms_pct": float(np.sqrt(np.mean(e ** 2))), "p95_pct": float(np.percentile(e, 95)),
            "p99_pct": float(np.percentile(e, 99)), "interpolated_pct": 100 * g.filled.mean(),
            "grid": f"{g.z.shape[1]}x{g.z.shape[0]}"}


def score_bars(p, t):
    rng = t["ylim"][1] - t["ylim"][0]
    vals = np.array([b.value for b in p.bars])
    tv = np.array(t["values"])
    if len(vals) != len(tv):
        return {"bars_found": f"{len(vals)}/{len(tv)}"}
    cats_ok = sum(b.category == c for b, c in zip(p.bars, t["categories"]))
    e = np.abs(vals - tv) / rng * 100
    ee = [abs((b.err_plus or np.nan) - te) / rng * 100 for b, te in zip(p.bars, t["errors"])]
    return {"bars_found": f"{len(vals)}/{len(tv)}", "categories": f"{cats_ok}/{len(tv)}",
            "max_err_pct": float(e.max()), "errbar_max_err_pct": float(np.nanmax(ee)) if np.isfinite(ee).any() else np.nan}


def score_micro(p, t):
    r = p.micro
    td = np.array(t["diam_nm"])
    st = r.particles["stats"] if r.particles else {}
    return {"nm_per_px": r.nm_per_px, "scale_err_pct": 100 * (r.nm_per_px / t["px_nm"] - 1) if r.nm_per_px else np.nan,
            "particles": f"{st.get('n', 0)}/{len(td)}",
            "mean_diam_err_pct": 100 * (st["mean"] / td.mean() - 1) if st else np.nan,
            "sd_diam_err_pct": 100 * (st["sd"] / td.std(ddof=1) - 1) if st else np.nan}


rows = []
for case in CASES:
    path = os.path.join(TS, case)
    name = case.split(".")[0]
    t = json.load(open(os.path.join(TS, "truth", name + ".json")))
    t0 = time.time()
    panels = digitize(path)
    dt = time.time() - t0
    write_outputs(panels, os.path.join(OUT, case.replace(".", "_")), template="natchem", formats=["png", "pdf", "svg"],
                  stem=name)
    t = dict(t)
    if t["type"] == "multipanel":
        keys = sorted(t["panels"])
        for k, p in zip(keys, panels):
            tp = dict(t["panels"][k]); tp.setdefault("xscale", "linear")
            sc = score_points(p, tp) if tp.get("type") == "scatter" else score_lines(p, tp)
            rows.append({"file": case, "panel": k, "type": p.kind, "mode": p.mode, "time_s": dt / len(panels), **sc})
        if len(panels) != len(keys):
            rows.append({"file": case, "panel": "-", "type": "error", "mode": "", "note": f"{len(panels)} panels found"})
        continue
    p = panels[0]
    if t["type"] == "line":
        sc = score_lines(p, t)
    elif t["type"] == "scatter":
        sc = score_points(p, t)
    elif t["type"] in ("heatmap", "contourf"):
        sc = score_grid(p, t)
    elif t["type"] == "bar":
        sc = score_bars(p, t)
    else:
        sc = score_micro(p, t)
    rows.append({"file": case, "panel": "a", "type": p.kind, "mode": p.mode, "time_s": dt, **sc})
    print(case, p.kind, p.mode, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in sc.items()}, f"{dt:.1f}s",
          flush=True)

json.dump(rows, open(os.path.join(OUT, "validation.json"), "w"), indent=1, default=float)


def f(v, d=3):
    return f"{v:.{d}f}" if isinstance(v, (float, np.floating)) and np.isfinite(v) else str(v)


md = ["# ReSrijan validation against ground truth", "",
      "Errors are in % of the full axis range (lines: perpendicular distance to the true curve; "
      "maps: |z − z_true| / colour range). Worst series per panel is reported.", ""]
md += ["## Line and scatter plots", "",
       "| file | panel | mode | series found | legend names | RMS % | p95 % | coverage % | time s |",
       "|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    if "series_found" in r:
        md.append(f"| {r['file']} | {r['panel']} | {r['mode']} | {r['series_found']} | {r['names_from_legend']} | "
                  f"{f(r['rms_pct'])} | {f(r['p95_pct'])} | {f(r['coverage_pct'], 0)} | {f(r['time_s'], 1)} |")
md += ["", "| file | panel | mode | points recalled % | RMS % | error-bar error % |", "|---|---|---|---|---|---|"]
for r in rows:
    if "points_recall_pct" in r:
        md.append(f"| {r['file']} | {r['panel']} | {r['mode']} | {f(r['points_recall_pct'], 0)} | {f(r['rms_pct'])} | "
                  f"{f(r.get('errorbar_err_pct', float('nan')))} |")
md += ["", "## Heat maps / 2D spectra / filled contours", "",
       "| file | mode | grid | RMS % | p95 % | p99 % | level exact % | level ±1 % | interpolated % |",
       "|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    if "interpolated_pct" in r:
        md.append(f"| {r['file']} | {r['mode']} | {r.get('grid', '')} | {f(r.get('rms_pct', ''))} | {f(r.get('p95_pct', ''))} | "
                  f"{f(r.get('p99_pct', ''))} | {f(r.get('level_exact_pct', ''), 1)} | {f(r.get('level_within1_pct', ''), 2)} | "
                  f"{f(r['interpolated_pct'], 1)} |")
md += ["", "## Bar charts", "", "| file | mode | bars | categories | max value error % | max error-bar error % |",
       "|---|---|---|---|---|---|"]
for r in rows:
    if "bars_found" in r:
        md.append(f"| {r['file']} | {r['mode']} | {r['bars_found']} | {r.get('categories', '')} | "
                  f"{f(r.get('max_err_pct', ''))} | {f(r.get('errbar_max_err_pct', ''))} |")
md += ["", "## Micrographs", "", "| file | nm/px | scale error % | particles | mean diameter error % | s.d. error % |",
       "|---|---|---|---|---|---|"]
for r in rows:
    if "scale_err_pct" in r:
        md.append(f"| {r['file']} | {f(r['nm_per_px'], 4)} | {f(r['scale_err_pct'])} | {r['particles']} | "
                  f"{f(r['mean_diam_err_pct'], 2)} | {f(r['sd_diam_err_pct'], 2)} |")
open(os.path.join(OUT, "validation.md"), "w").write("\n".join(md) + "\n")
print("\n".join(md))
