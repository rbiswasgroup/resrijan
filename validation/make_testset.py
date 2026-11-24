"""Generate a ground-truth test set of scientific figures in many file formats.

Every figure is drawn from known data, saved as PNG/JPG/TIFF/PDF/EPS/PS, and the data
is written to ``truth/<name>.json`` so the digitiser's output can be scored exactly.
"""
import json
import os
import sys

import shutil as _sh

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "testset")
os.makedirs(os.path.join(OUT, "truth"), exist_ok=True)
rng = np.random.default_rng(7)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})


def save(fig, name, fmts, dpi=300):
    for f in fmts:
        if f == "svgtext":       # SVG with real <text> elements (Inkscape/Illustrator style)
            with plt.rc_context({"svg.fonttype": "none"}):
                fig.savefig(os.path.join(OUT, f"{name}_text.svg"))
            continue
        kw = {}
        if f in ("png", "jpg", "tif"):
            kw["dpi"] = dpi if not isinstance(dpi, dict) else dpi.get(f, 300)
        if f == "jpg":
            kw["pil_kwargs"] = {"quality": 80}
        fig.savefig(os.path.join(OUT, f"{name}.{f}"), **kw)
    plt.close(fig)


def truth(name, d):
    with open(os.path.join(OUT, "truth", name + ".json"), "w") as fh:
        json.dump(d, fh)


# 1 ── multi-series line plot, framed axes, legend, dashed black line
x = np.linspace(0, 10, 400)
ys = {
    "damped": 1.6 * np.exp(-x / 4) * np.cos(2.1 * x),
    "gauss": 1.2 * np.exp(-(x - 6.5) ** 2 / 0.8) - 0.3,
    "sigmoid": 1.5 / (1 + np.exp(-(x - 3) * 2)) - 1.0,
    "ramp": 0.12 * x - 0.6,
}
fig, ax = plt.subplots(figsize=(3.6, 2.7))
ax.plot(x, ys["damped"], color="#1f77b4", lw=1.2, label="damped")
ax.plot(x, ys["gauss"], color="#d62728", lw=1.2, label="gauss")
ax.plot(x, ys["sigmoid"], color="#2ca02c", lw=1.2, label="sigmoid")
ax.plot(x, ys["ramp"], color="k", lw=1.0, ls="--", label="ramp")
ax.set_xlim(0, 10); ax.set_ylim(-1.5, 2.0)
ax.set_xlabel("Time (ps)"); ax.set_ylabel("Signal (a.u.)")
ax.legend(loc="upper right", fontsize=7, frameon=False)
fig.tight_layout()
save(fig, "line_multi", ["png", "jpg", "pdf", "eps", "ps", "svg", "svgtext"])
truth("line_multi", {"type": "line", "xlim": [0, 10], "ylim": [-1.5, 2.0], "xscale": "linear", "yscale": "linear",
                     "series": {k: {"x": x.tolist(), "y": v.tolist()} for k, v in ys.items()}})
# low-resolution screenshot of the same figure
fig, ax = plt.subplots(figsize=(3.6, 2.7))
for k, c, ls in (("damped", "#1f77b4", "-"), ("gauss", "#d62728", "-"), ("sigmoid", "#2ca02c", "-"), ("ramp", "k", "--")):
    ax.plot(x, ys[k], color=c, lw=1.2, ls=ls, label=k)
ax.set_xlim(0, 10); ax.set_ylim(-1.5, 2.0)
ax.set_xlabel("Time (ps)"); ax.set_ylabel("Signal (a.u.)")
ax.legend(loc="upper right", fontsize=7, frameon=False)
fig.tight_layout()
save(fig, "line_lowres", ["png"], dpi=110)
truth("line_lowres", json.load(open(os.path.join(OUT, "truth", "line_multi.json"))))

# 2 ── IR spectrum, reversed wavenumber axis, open (L-shaped) axes, sharp peaks
wn = np.linspace(400, 4000, 3600)
def lor(x0, g, a):
    return a * g ** 2 / ((wn - x0) ** 2 + g ** 2)
A = (lor(3400, 120, 0.55) + lor(2950, 18, 0.35) + lor(2870, 14, 0.22) + lor(1715, 9, 0.9)
     + lor(1640, 25, 0.3) + lor(1450, 10, 0.25) + lor(1250, 14, 0.4) + lor(1050, 20, 0.5) + 0.03)
fig, ax = plt.subplots(figsize=(3.6, 2.4))
ax.plot(wn, A, color="k", lw=0.9)
ax.set_xlim(4000, 400); ax.set_ylim(0, 1.0)
ax.spines[["top", "right"]].set_visible(False)
ax.set_xlabel("Wavenumber (cm$^{-1}$)"); ax.set_ylabel("Absorbance")
fig.tight_layout()
save(fig, "ir_spectrum", ["png", "pdf", "jpg"])
truth("ir_spectrum", {"type": "line", "xlim": [4000, 400], "ylim": [0, 1], "xscale": "linear", "yscale": "linear",
                      "series": {"spectrum": {"x": wn.tolist(), "y": A.tolist()}}})

# 3 ── log-y decay
t = np.linspace(0, 20, 300)
d1 = 0.7 * np.exp(-t / 1.5) + 0.3 * np.exp(-t / 9.0)
d2 = np.exp(-t / 3.2)
fig, ax = plt.subplots(figsize=(3.4, 2.6))
ax.semilogy(t, d1, color="#9467bd", lw=1.3, label="biexp")
ax.semilogy(t, d2, color="#ff7f0e", lw=1.3, label="mono")
ax.set_xlim(0, 20); ax.set_ylim(1e-3, 1.2)
ax.set_xlabel("t (ps)"); ax.set_ylabel("C(t)")
ax.legend(fontsize=7, frameon=False, loc="lower left")
fig.tight_layout()
save(fig, "log_decay", ["png", "pdf", "eps", "svg", "svgtext"])
truth("log_decay", {"type": "line", "xlim": [0, 20], "ylim": [1e-3, 1.2], "xscale": "linear", "yscale": "log",
                    "series": {"biexp": {"x": t.tolist(), "y": d1.tolist()},
                               "mono": {"x": t.tolist(), "y": d2.tolist()}}})

# 4 ── scatter with error bars
xs = np.arange(1, 13) * 25.0
s1 = 2.0 + 0.015 * xs + rng.normal(0, 0.25, xs.size)
s2 = 6.5 - 0.012 * xs + rng.normal(0, 0.25, xs.size)
e1 = rng.uniform(0.2, 0.5, xs.size); e2 = rng.uniform(0.2, 0.5, xs.size)
fig, ax = plt.subplots(figsize=(3.4, 2.6))
ax.errorbar(xs, s1, yerr=e1, fmt="o", color="#1f77b4", ms=4, capsize=2, lw=0.8, label="sample A")
ax.errorbar(xs, s2, yerr=e2, fmt="s", color="#d62728", ms=4, capsize=2, lw=0.8, label="sample B")
ax.set_xlim(0, 325); ax.set_ylim(0, 9)
ax.set_xlabel("Temperature (K)"); ax.set_ylabel("D (10$^{-9}$ m$^2$ s$^{-1}$)")
ax.legend(fontsize=7, frameon=False, loc="upper right")
fig.tight_layout()
save(fig, "scatter_err", ["png", "pdf", "svg", "svgtext"])
truth("scatter_err", {"type": "scatter", "xlim": [0, 325], "ylim": [0, 9], "xscale": "linear", "yscale": "linear",
                      "series": {"sample A": {"x": xs.tolist(), "y": s1.tolist(), "yerr": e1.tolist()},
                                 "sample B": {"x": xs.tolist(), "y": s2.tolist(), "yerr": e2.tolist()}}})

# 5 ── 2D-IR-like map with colour bar (smooth pcolormesh + contour lines)
w1 = np.linspace(1600, 1700, 201); w3 = np.linspace(1600, 1700, 201)
W1, W3 = np.meshgrid(w1, w3)
def g2(c1, c3, s1, s3, rho=0.0):
    a = (W1 - c1) / s1; b = (W3 - c3) / s3
    return np.exp(-(a * a - 2 * rho * a * b + b * b) / (2 * (1 - rho ** 2)))
Z = (g2(1640, 1640, 8, 8, 0.6) - g2(1640, 1625, 8, 8, 0.6) + 0.45 * g2(1675, 1675, 6, 6, 0.3)
     - 0.45 * g2(1675, 1662, 6, 6, 0.3))
fig, ax = plt.subplots(figsize=(3.2, 2.8))
m = ax.pcolormesh(W1, W3, Z, cmap="RdBu_r", vmin=-1, vmax=1, shading="auto", rasterized=True)
ax.contour(W1, W3, Z, levels=[-0.6, -0.3, 0.3, 0.6], colors="k", linewidths=0.4)
ax.plot([1600, 1700], [1600, 1700], color="k", lw=0.5)
ax.set_xlabel(r"$\omega_1$ (cm$^{-1}$)"); ax.set_ylabel(r"$\omega_3$ (cm$^{-1}$)")
cb = fig.colorbar(m, ax=ax); cb.set_label("ΔOD (norm.)")
fig.tight_layout()
save(fig, "heatmap_2dir", ["png", "pdf", "jpg", "svg", "svgtext"])
truth("heatmap_2dir", {"type": "heatmap", "x": w1.tolist(), "y": w3.tolist(), "z": Z.tolist(),
                       "vmin": -1, "vmax": 1})

# 6 ── filled contour (discrete levels) of a potential-energy surface
q1 = np.linspace(-2, 2, 241); q2 = np.linspace(-1.5, 2.5, 241)
Q1, Q2 = np.meshgrid(q1, q2)
V = (Q1 ** 2 - 1) ** 2 + 1.5 * (Q2 - 0.4 * Q1 ** 2) ** 2 * 0.8
fig, ax = plt.subplots(figsize=(3.2, 2.8))
cs = ax.contourf(Q1, Q2, V, levels=np.linspace(0, 4, 17), cmap="viridis", extend="max")
fig.colorbar(cs, ax=ax, label="E (kcal/mol)")
ax.set_xlabel("q$_1$ (Å)"); ax.set_ylabel("q$_2$ (Å)")
fig.tight_layout()
save(fig, "contourf_pes", ["png", "pdf", "svg", "svgtext"])
truth("contourf_pes", {"type": "contourf", "x": q1.tolist(), "y": q2.tolist(), "z": V.tolist(),
                       "levels": np.linspace(0, 4, 17).tolist()})

# 7 ── synthetic TEM micrograph with scale bar (1024 x 1024, 0.5 nm / px)
N = 1024; px_nm = 0.5
img = np.full((N, N), 175.0)
yy, xx = np.mgrid[0:N, 0:N]
parts = []
placed = 0
while placed < 60:
    r_nm = rng.normal(14, 2.2)
    r = r_nm / px_nm
    cx, cy = rng.uniform(r + 5, N - r - 5), rng.uniform(r + 5, N - 160 - r)
    if any((cx - p[0]) ** 2 + (cy - p[1]) ** 2 < (r + p[2] + 6) ** 2 for p in parts):
        continue
    parts.append((cx, cy, r))
    placed += 1
for cx, cy, r in parts:
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    img -= 95 * np.clip(r + 0.5 - d, 0, 1)
img = img + rng.normal(0, 9, img.shape)
img = gaussian_filter(img, 1.0)
img = np.clip(img, 0, 255).astype(np.uint8)
pim = Image.fromarray(img).convert("RGB")
dr = ImageDraw.Draw(pim)
bar_nm = 50; bar_px = bar_nm / px_nm
dr.rectangle([N - 60 - bar_px - 20, N - 110, N - 40, N - 30], fill=(0, 0, 0))
dr.rectangle([N - 50 - bar_px, N - 60, N - 50 - 1, N - 48], fill=(255, 255, 255))  # exactly bar_px wide
try:
    font = ImageFont.truetype("DejaVuSans.ttf", 34)
except Exception:
    font = ImageFont.load_default()
dr.text((N - 50 - bar_px / 2, N - 70), "50 nm", fill=(255, 255, 255), font=font, anchor="ms")
pim.save(os.path.join(OUT, "micrograph_tem.png"))
pim.save(os.path.join(OUT, "micrograph_tem.jpg"), quality=85)
pim.save(os.path.join(OUT, "micrograph_tem.tif"))
truth("micrograph_tem", {"type": "micrograph", "px_nm": px_nm, "bar_nm": bar_nm, "bar_px": bar_px,
                         "diam_nm": [2 * p[2] * px_nm for p in parts]})

# 8 ── a journal-like multi-panel page (vector PDF) + a 200-dpi scan of it
fig = plt.figure(figsize=(7.0, 5.2))
gs = fig.add_gridspec(2, 2, hspace=0.45, wspace=0.35)
a = fig.add_subplot(gs[0, 0]); b = fig.add_subplot(gs[0, 1]); c = fig.add_subplot(gs[1, 0]); d = fig.add_subplot(gs[1, 1])
a.plot(x, ys["damped"], color="#1f77b4", lw=1.1); a.plot(x, ys["gauss"], color="#d62728", lw=1.1)
a.set_xlim(0, 10); a.set_ylim(-1.5, 2.0); a.set_xlabel("Time (ps)"); a.set_ylabel("Signal")
b.semilogy(t, d1, color="#9467bd", lw=1.2); b.set_xlim(0, 20); b.set_ylim(1e-3, 1.2); b.set_xlabel("t (ps)"); b.set_ylabel("C(t)")
c.errorbar(xs, s1, yerr=e1, fmt="o", color="#1f77b4", ms=3.5, capsize=2, lw=0.8)
c.set_xlim(0, 325); c.set_ylim(0, 9); c.set_xlabel("T (K)"); c.set_ylabel("D")
d.plot(wn, A, color="k", lw=0.8); d.set_xlim(4000, 400); d.set_ylim(0, 1.0); d.set_xlabel("Wavenumber"); d.set_ylabel("Abs.")
for axx, l in zip((a, b, c, d), "abcd"):
    axx.text(-0.22, 1.05, l, transform=axx.transAxes, fontweight="bold", fontsize=11)
save(fig, "multipanel_page", ["pdf", "png"], dpi=200)
truth("multipanel_page", {"type": "multipanel", "panels": {
    "a": {"xlim": [0, 10], "ylim": [-1.5, 2], "yscale": "linear",
          "series": {"damped": {"x": x.tolist(), "y": ys["damped"].tolist()},
                     "gauss": {"x": x.tolist(), "y": ys["gauss"].tolist()}}},
    "b": {"xlim": [0, 20], "ylim": [1e-3, 1.2], "yscale": "log",
          "series": {"biexp": {"x": t.tolist(), "y": d1.tolist()}}},
    "c": {"xlim": [0, 325], "ylim": [0, 9], "yscale": "linear", "type": "scatter",
          "series": {"sample A": {"x": xs.tolist(), "y": s1.tolist()}}},
    "d": {"xlim": [4000, 400], "ylim": [0, 1], "yscale": "linear",
          "series": {"spectrum": {"x": wn.tolist(), "y": A.tolist()}}}}})
# 9 ── "Origin-style" figure: serif font, inward mirrored ticks, thick frame, line+symbol,
#       framed legend, light grid – a different look from matplotlib defaults
T_ = np.linspace(280, 360, 9)
k1 = 1e-3 * np.exp(-4200 * (1 / T_ - 1 / 300)); k2 = 0.6e-3 * np.exp(-5600 * (1 / T_ - 1 / 300))
with plt.rc_context({"font.family": "DejaVu Serif", "xtick.direction": "in", "ytick.direction": "in",
                     "xtick.top": True, "ytick.right": True, "axes.linewidth": 1.5,
                     "xtick.major.width": 1.3, "ytick.major.width": 1.3, "xtick.major.size": 5, "ytick.major.size": 5}):
    fig, ax = plt.subplots(figsize=(3.4, 2.8))
    ax.grid(color="0.85", lw=0.6)
    ax.plot(T_, k1 * 1e3, "-o", color="#000080", ms=6, mfc="white", mew=1.5, lw=1.5, label="Urea")
    ax.plot(T_, k2 * 1e3, "-s", color="#B22222", ms=6, lw=1.5, label="TMAO")
    ax.set_xlim(275, 365); ax.set_ylim(0, 25)
    ax.set_xlabel("Temperature (K)"); ax.set_ylabel("k (10$^{-3}$ s$^{-1}$)")
    ax.legend(loc="upper left", frameon=True, edgecolor="k", fancybox=False)
    fig.tight_layout()
    save(fig, "origin_style", ["png", "pdf", "jpg"], dpi=250)
truth("origin_style", {"type": "scatter", "xlim": [275, 365], "ylim": [0, 25], "xscale": "linear", "yscale": "linear",
                       "series": {"Urea": {"x": T_.tolist(), "y": (k1 * 1e3).tolist()},
                                  "TMAO": {"x": T_.tolist(), "y": (k2 * 1e3).tolist()}}})
# 10 ── bar chart with error bars and value labels (categorical x)
cats = ["Pt", "Pd", "Ni", "Co", "Fe", "Cu"]
vals = np.array([2.4, 5.8, 9.35, 10.7, 6.9, 1.6]); errs = np.array([0.3, 0.5, 0.6, 0.4, 0.5, 0.2])
fig, ax = plt.subplots(figsize=(3.6, 2.7))
ax.bar(range(6), vals, yerr=errs, capsize=3, color=["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02"])
for i, v in enumerate(vals):
    ax.text(i, v + errs[i] + 0.2, f"{v:g}", ha="center", fontsize=7)
ax.set_xticks(range(6), cats); ax.set_ylim(0, 15); ax.set_ylabel("Rate (mmol h$^{-1}$)")
fig.tight_layout()
save(fig, "bar_err", ["png", "pdf", "jpg", "svg"])
truth("bar_err", {"type": "bar", "categories": cats, "values": vals.tolist(), "errors": errs.tolist(), "ylim": [0, 15]})

for _n in ("line_multi", "log_decay", "scatter_err", "heatmap_2dir", "contourf_pes"):
    _sh.copy(os.path.join(OUT, "truth", _n + ".json"), os.path.join(OUT, "truth", _n + "_text.json"))
print("test set written to", OUT)
