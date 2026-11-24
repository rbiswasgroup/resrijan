"""Generate the image-figure examples (synthetic, with ground truth).

    python tools/make_image_examples.py

examples/12_hrtem_insets/hrtem_insets.pdf (+ .png)
    A 640×480 HRTEM-like image (0.05 nm/px) of crystalline TiO2-like grains with known
    lattice spacings, a microscope info strip and burnt-in 5 nm bar that the figure clips
    away, the figure's own vector 5 nm bar, phase labels, dashed boxes, and four ×4 insets
    with d-spacing labels – one of them deliberately wrong (0.27 nm printed, 0.248 nm true).
examples/13_timelapse/timelapse.svg (+ .png)
    Five optical frames (0–40 min) of a layer growing on a substrate, red lines on the
    interface and the growth front, blue arrows measuring the layer, titles "0 min"….
truth.json in each folder holds the true values.
"""
import json
from pathlib import Path

import cv2
import matplotlib
import matplotlib.ticker  # noqa: F401
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import ndimage as ndi  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
rng = np.random.default_rng(7)
plt.rcParams.update({"pdf.fonttype": 42, "svg.fonttype": "none", "font.family": "DejaVu Sans"})


# ───────────────────────── HRTEM ─────────────────────────
def hrtem():
    out = ROOT / "examples" / "12_hrtem_insets"
    out.mkdir(parents=True, exist_ok=True)
    H, W, nm = 480, 640, 0.05
    y, x = np.mgrid[0:H, 0:W].astype(float)
    # grains: Voronoi cells, each with one or two fringe sets
    seeds = np.array([[90, 120], [300, 90], [520, 140], [140, 330], [360, 300], [560, 380], [250, 440], [450, 200]], float)
    d_list = [0.352, 0.325, 0.248, 0.238, 0.352, 0.219, 0.325, 0.189]
    lab = np.argmin([(x - sx) ** 2 + (y - sy) ** 2 for sx, sy in seeds], axis=0)
    img = np.zeros((H, W))
    grains = []
    for k, (d, (sx, sy)) in enumerate(zip(d_list, seeds)):
        th = rng.uniform(0, np.pi)
        p = d / nm
        u = x * np.cos(th) + y * np.sin(th)
        f = np.cos(2 * np.pi * u / p)
        if k % 3 == 0:  # second, weaker set
            th2 = th + np.radians(rng.uniform(50, 70))
            f += 0.45 * np.cos(2 * np.pi * (x * np.cos(th2) + y * np.sin(th2)) / (p * 1.12))
        amp = np.clip(1 - ((x - sx) ** 2 + (y - sy) ** 2) / (150 ** 2), 0.25, 1)
        img[lab == k] = (f * amp)[lab == k]
        grains.append({"seed_px": [sx, sy], "d_nm": d, "period_px": p, "normal_angle_deg": float(np.degrees(th) % 180)})
    # grain boundaries amorphous, thickness variation, noise
    edge = ndi.morphological_gradient(lab, size=7) > 0
    img[edge] = 0
    img = 120 + 38 * img + 25 * np.sin(x / 140) * np.cos(y / 170)
    img = ndi.gaussian_filter(img, 0.7) + rng.normal(0, 14, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    # microscope overlay in the bottom strip: info text + white box with a 5 nm bar (100 px)
    img[446:, :] = np.clip(img[446:, :].astype(int) - 20, 0, 255)
    cv2.putText(img, "1200000 x", (8, 462), cv2.FONT_HERSHEY_SIMPLEX, 0.45, 255, 1, cv2.LINE_AA)
    cv2.putText(img, "200 kV", (8, 476), cv2.FONT_HERSHEY_SIMPLEX, 0.45, 255, 1, cv2.LINE_AA)
    img[450:478, 520:636] = 255
    img[454:460, 528:628] = 0
    cv2.putText(img, "5 nm", (553, 475), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1, cv2.LINE_AA)
    rgb = np.dstack([img] * 3)
    visible = 446          # the figure shows rows 0–445 only (the strip is clipped)

    # insets: ×4 crops (cubic) of four grains, the third one mislabelled
    def crop_at(k):     # 60×50 px source box centred on grain k
        sx, sy = seeds[k]
        return (int(sx) - 30, int(sy) - 25, int(sx) + 30, int(sy) + 25)
    insets = [   # the third label is deliberately wrong (true d = 0.248 nm)
        {"src": crop_at(0), "label": "d = 0.352 nm\n(101)", "true_d": d_list[0], "pos": (0.02, 0.43), "col": "#1b7837"},
        {"src": crop_at(3), "label": "d = 0.238 nm\n(004)", "true_d": d_list[3], "pos": (0.36, 0.40), "col": "#ffd92f"},
        {"src": crop_at(2), "label": "d = 0.27 nm\n(111)", "true_d": d_list[2], "pos": (0.70, 0.62), "col": "#ffffff"},
        {"src": crop_at(1), "label": "d = 0.325 nm\n(110)", "true_d": d_list[1], "pos": (0.05, 0.04), "col": "#4dac26"},
    ]
    fig = plt.figure(figsize=(6.4, 4.46), dpi=100)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.patch.set_alpha(0)
    ax.set_xlim(0, W); ax.set_ylim(visible, 0); ax.set_axis_off()
    # the figure's own scale bar: 5 nm = 100 px
    ax.plot([520, 620], [425, 425], color="w", lw=4, solid_capstyle="butt")
    ax.text(570, 418, "5 nm", color="w", ha="center", va="bottom", fontsize=15, fontweight="bold")
    truth_insets = []
    for k, ins in enumerate(insets):
        x0, y0, x1, y1 = ins["src"]
        crop = img[y0:y1, x0:x1]
        big = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        iax = fig.add_axes([ins["pos"][0], ins["pos"][1], 0.25, 0.25 * (H / visible) * big.shape[0] / big.shape[1] * W / H])
        iax.imshow(np.dstack([big] * 3), interpolation="none")
        iax.set_axis_off()
        iax.text(0.5, 0.97, ins["label"], transform=iax.transAxes, color="w", ha="center", va="top",
                 fontsize=10, fontweight="bold", linespacing=0.95)
        # fringe markers (two short bars parallel to the fringes, one period apart)
        ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec=ins["col"], lw=2.2, ls=(0, (3, 2))))
        truth_insets.append({"label": ins["label"].replace("\n", " "), "true_d_nm": ins["true_d"],
                             "source_box_px": [x0, y0, x1, y1], "magnification": 4.0,
                             "nm_per_px": nm / 4, "label_correct": abs(float(ins["label"].split()[2]) - ins["true_d"]) < 0.006})
    for name, (px, py) in {"anatase": (330, 40), "rutile": (560, 222), "TiO$_2$": (290, 335)}.items():
        ax.text(px, py, name, color="w", fontsize=12, fontweight="bold", ha="center")
    fig.savefig(out / "_overlay.pdf", transparent=True)
    plt.close(fig)
    # the whole 640×480 bitmap goes underneath, clipped to the rows the figure shows
    # (as Inkscape/cairo do for cropped photos)
    import pymupdf as fitz
    src = fitz.open()
    sp = src.new_page(width=W, height=H)
    ok, buf = cv2.imencode(".png", rgb)
    sp.insert_image(sp.rect, stream=buf.tobytes())
    doc = fitz.open(out / "_overlay.pdf")
    pg = doc[0]
    pg.show_pdf_page(pg.rect, src, 0, clip=fitz.Rect(0, 0, W, visible), overlay=False, keep_proportion=False)
    doc.save(out / "hrtem_insets.pdf", garbage=3, deflate=True)
    doc.close()
    (out / "_overlay.pdf").unlink()
    pix = fitz.open(out / "hrtem_insets.pdf")[0].get_pixmap(dpi=200)
    pix.save(out / "hrtem_insets.png")
    (out / "truth.json").write_text(json.dumps({
        "nm_per_px": nm, "scale_bar": {"value_nm": 5, "length_px": 100}, "visible_rows": visible,
        "grains": grains, "insets": truth_insets}, indent=1))


# ───────────────────────── optical time-lapse ─────────────────────────
def timelapse():
    out = ROOT / "examples" / "13_timelapse"
    out.mkdir(parents=True, exist_ok=True)
    H, W = 1100, 360
    times = [0, 10, 20, 30, 40]
    rate = 3.0                          # layer thickness grows 3 px per minute (native px)
    slope = 0.08                        # interface leans: x = x0 + slope·(H − y)
    x_if = 120
    truth = []
    fig = plt.figure(figsize=(10, 6.6), dpi=100)
    for k, t in enumerate(times):
        y, x = np.mgrid[0:H, 0:W].astype(float)
        xi = x_if + slope * (H - y)                  # interface (electrode | layer)
        thick = rate * t
        xf = xi + thick                              # growth front (layer | electrolyte)
        tex = ndi.gaussian_filter(rng.normal(0, 1, (H, W)), 2.5)
        electrode = np.dstack([110 + 25 * tex, 135 + 25 * tex, 120 + 25 * tex])
        layer = np.dstack([70 + 40 * tex, 80 + 40 * tex, 70 + 40 * tex])
        sol = np.dstack([235 + 6 * tex, 200 + 6 * tex, 225 + 6 * tex])
        # rough front: small wiggle on the layer boundary
        wig = 3 * np.sin(y / 23 + k) + 2 * np.sin(y / 7.3)
        im = np.where((x < xi)[..., None], electrode, np.where((x < xf + wig * (t > 0))[..., None], layer, sol))
        im = np.clip(im + rng.normal(0, 4, im.shape), 0, 255).astype(np.uint8)
        left = 0.02 + k * 0.196
        ax = fig.add_axes([left, 0.04, 0.16, 0.86])
        ax.imshow(im, interpolation="none")
        ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.set_axis_off()
        ax.set_title(f"{t} min", fontsize=11, pad=4)
        # red lines: interface, and growth front (when there is a layer)
        ax.plot([x_if + slope * H, x_if], [0, H], color="red", lw=1.0)
        rec = {"time_min": t, "thickness_px": thick, "perpendicular_px": thick / np.hypot(1, slope)}
        if t > 0:
            ax.plot([x_if + slope * H + thick, x_if + thick], [0, H], color="red", lw=1.0)
            arrows = []
            for yy in (250, 550, 900):
                xa = x_if + slope * (H - yy)
                ax.annotate("", xy=(xa + thick, yy), xytext=(xa, yy),
                            arrowprops=dict(arrowstyle="-|>", color="#5b9bd5", lw=1.4, shrinkA=0, shrinkB=0,
                                            mutation_scale=12))
                arrows.append(thick)
            rec["arrow_px"] = arrows
        truth.append(rec)
    fig.text(0.02, 0.965, "Film A", fontsize=14)
    fig.savefig(out / "timelapse.svg")
    fig.savefig(out / "timelapse.png", dpi=110)
    plt.close(fig)
    (out / "truth.json").write_text(json.dumps({"rate_px_per_min": rate, "frames": truth,
                                                "note": "native image px; perpendicular = horizontal / sqrt(1+slope^2)"},
                                               indent=1))


# ───────────────────────── tricky plots ─────────────────────────
def tricky():
    out = ROOT / "examples" / "14_tricky_axes"
    out.mkdir(parents=True, exist_ok=True)
    truth = {}
    # 1 · parity plot: negative ticks (mathtext minus bars), one marker per species + direct labels
    #     ("Mg" and "Ca" touch: two labels in different colours must stay apart)
    pts = {"Li": (-6.2, -5.4, "o", "#7b3294"), "Na": (-9.4, -10.1, "^", "#2c7bb6"), "K": (-7.3, -8.9, "o", "#d7191c"),
           "Mg": (-12.6, -12.2, "D", "#e66101"), "Ca": (-11.9, -13.4, "s", "#1a9641")}
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    ax.plot([-16, -4], [-16, -4], "--", color="0.5", lw=1)
    for name, (x, y, m, c) in pts.items():
        ax.plot([x], [y], m, ms=11, mfc=c, mec="k", mew=1.5)
        ax.text(x + 0.45, y, name, color=c, va="center", fontweight="bold", fontsize=12)
    ax.set_xlim(-16, -4); ax.set_ylim(-16, -4)
    ax.grid(ls="--", color="0.85")
    ax.set_xlabel(r"$E^{\mathrm{calc}}_{\mathrm{b-1}}$ (kJ/mol)")
    ax.set_ylabel(r"$E^{\mathrm{ref}}_{\mathrm{b-1}}$ (kJ/mol)")
    fig.tight_layout(); fig.savefig(out / "parity_plot.pdf"); plt.close(fig)
    truth["parity_plot"] = {k: v[:2] for k, v in pts.items()}
    # 2 · stacked spectra: x axis only, reversed ppm, coloured trace labels
    x = np.linspace(-25, 25, 1500)
    fig, ax = plt.subplots(figsize=(4.2, 3.4))
    traces = [("Neat", "#b35806", 1.0, 0.8), ("Dilute", "#5aae61", 2.6, 1.4), ("Mixed", "#2166ac", 5.1, 2.1), ("Gel", "#c51b7d", 3.8, 0.6)]
    truth["stacked_spectra"] = {}
    for k, (name, c, pos, wid) in enumerate(traces):
        yk = 1.2 * k + np.exp(-((x - pos) / wid) ** 2) + 0.4 * np.exp(-(x / 0.6) ** 2) + rng.normal(0, 0.01, x.size)
        ax.plot(x, yk, color=c, lw=1)
        ax.text(-16, 1.2 * k + 0.25, name, color=c, fontweight="bold")
        truth["stacked_spectra"][name] = {"peak_ppm": pos, "offset": 1.2 * k}
    ax.set_xlim(20, -20)
    for sp in ("left", "right", "top"):
        ax.spines[sp].set_visible(False)
    ax.set_yticks([]); ax.set_xlabel("[ppm]")
    fig.tight_layout(); fig.savefig(out / "stacked_spectra.pdf"); plt.close(fig)
    # 3 · decay curves on a y axis without numbers + inset bar chart with printed values
    t = np.array([0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2, 3, 4, 5, 6, 7.5])
    a = 0.25 + 0.50 * np.exp(-t / 1.8); b = 0.12 + 0.50 * np.exp(-t / 3.5)
    fig, ax = plt.subplots(figsize=(4.6, 3.6))
    tt = np.linspace(0.2, 7.5, 200)
    ax.plot(tt, 0.25 + 0.50 * np.exp(-tt / 1.8), "-.", color="k"); ax.plot(tt, 0.12 + 0.50 * np.exp(-tt / 3.5), "-.", color="#d95f02")
    ax.plot(t, a, "o", color="k", label="Liquid"); ax.plot(t, b, "o", color="#d95f02", label="Glass")
    ax.set_xlim(0, 8); ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xlabel(r"$t_{\mathrm{d}}$ (ps)"); ax.set_ylabel("C(t)"); ax.legend(frameon=False, loc="upper right")
    ins = ax.inset_axes([0.5, 0.42, 0.4, 0.3])
    vals = [38.2, 15.6]
    ins.bar([0, 1], vals, color=["k", "#d95f02"], width=0.6)
    for i, v in enumerate(vals):
        ins.text(i, v + 1.5, f"{v:g}", ha="center", fontsize=6)
    ins.set_xticks([]); ins.yaxis.set_major_formatter(matplotlib.ticker.NullFormatter()); ins.set_ylim(0, 55)
    ins.set_ylabel(r"$\tau_1$ (ps)", fontsize=7)
    ins.bar([0], [0], color="k", label="Liquid"); ins.bar([0], [0], color="#d95f02", label="Glass")
    ins.legend(fontsize=5, frameon=False, loc="upper right")
    fig.tight_layout(); fig.savefig(out / "unnumbered_inset.pdf"); plt.close(fig)
    truth["unnumbered_inset"] = {"t": t.tolist(), "Liquid": a.tolist(), "Glass": b.tolist(), "bars": vals}
    # 4 · paired contour panels sharing a right-hand y axis
    fig, axs = plt.subplots(1, 2, figsize=(4.4, 2.4), sharey=True)
    yy, xx = np.mgrid[2.4:4.0:240j, 4.35:4.55:240j]
    peaks = [[(4.47, 2.75), (4.47, 3.1)], [(4.41, 2.75), (4.42, 3.45), (4.42, 3.7)]]
    truth["contour_pairs"] = peaks
    for ax, pk, col in zip(axs, peaks, ("#762a83", "#1b7837")):
        z = sum(np.exp(-((xx - px) / 0.025) ** 2 - ((yy - py) / 0.06) ** 2) for px, py in pk)
        ax.contour(xx, yy, z, levels=np.geomspace(0.08, 0.9, 9), colors=col, linewidths=0.7)
        ax.set_xlim(4.55, 4.35); ax.set_ylim(4.0, 2.4); ax.set_xticks([4.5, 4.4])
    axs[1].yaxis.tick_right(); axs[1].set_yticks([2.6, 3.0, 3.4, 3.8]); axs[1].tick_params(labelright=True)
    axs[0].tick_params(labelleft=False)
    fig.suptitle("Sample A", fontweight="bold")
    fig.savefig(out / "contour_pairs.pdf"); plt.close(fig)
    (out / "truth.json").write_text(json.dumps(truth, indent=1))


if __name__ == "__main__":
    hrtem()
    timelapse()
    tricky()
    print("written examples/12_hrtem_insets, 13_timelapse and 14_tricky_axes")
