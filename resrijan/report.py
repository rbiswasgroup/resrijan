"""Verification overlays and the HTML report."""
from __future__ import annotations

import html as _h
import os
from typing import List

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _crop_bounds(p, margin=0.18):
    H, W = p.page.rgb.shape[:2]
    b = p.box
    x0 = max(0, int(b.x0 - margin * b.w)); x1 = min(W, int(b.x1 + margin * b.w))
    y0 = max(0, int(b.y0 - 0.08 * b.h)); y1 = min(H, int(b.y1 + margin * b.h))
    if p.colorbar is not None:
        x1 = min(W, int(max(x1, p.colorbar.x1 + 0.15 * b.w)))
    return x0, y0, x1, y1


def _frame_overlay(p, path: str) -> str:
    """Native image with every measured annotation, the scale bar, insets' source
    regions and the strongest lattice periods."""
    fr = p.frame
    img = fr.rgb
    H, W = img.shape[:2]
    fig, ax = plt.subplots(figsize=(6, 6 * H / W + 0.4), dpi=150)
    ax.imshow(img, interpolation="none")
    for k, a in enumerate([a for a in fr.annotations if a.kind != "head"], 1):
        q = a.pts
        if a.kind == "rect":
            q = np.vstack([q, q[:1]])
        ax.plot(q[:, 0], q[:, 1], color="#00ffff", lw=1.0, alpha=0.9)
        if a.kind == "arrow":
            ax.plot(*q[-1], marker="o", ms=3, color="#00ffff")
        ax.text(q[:, 0].mean(), q[:, 1].mean(), f"{k}:{a.length_px:.0f}", color="#ffff00", fontsize=5,
                ha="left", va="bottom", bbox=dict(fc="k", ec="none", alpha=0.45, pad=0.5))
    if fr.bar is not None:
        ax.plot([fr.bar.x0, fr.bar.x1], [fr.bar.y + 1.5 * max(fr.bar.thickness, 2)] * 2, color="#ff00ff", lw=1.5)
        ax.text(0.5 * (fr.bar.x0 + fr.bar.x1), fr.bar.y + 3 * max(fr.bar.thickness, 2),
                f"{fr.bar.length_px:.1f} px = {fr.bar.value} {fr.bar.unit}", color="#ff00ff", ha="center", va="top", fontsize=6)
    for b in fr.unlabelled_bars:
        ax.plot(b.pts[:, 0], b.pts[:, 1] + 3, color="#ff8800", lw=1.2)
    if p.frames:
        for c in fr.children:
            reg = getattr(p.frames[c], "registration", None)
            if reg:
                x0, y0, x1, y1 = reg["box"]
                ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec="#00ff00", lw=0.9, ls="--"))
                ax.text(x0, y0 - 2, f"inset ×{reg['mag']:.2f}", color="#00ff00", fontsize=5, va="bottom")
    lines = []
    if fr.title:
        lines.append(f"title: {fr.title}")
    for pk in fr.lattice[:3]:
        d = f" = {pk['d_nm']:.3f} nm" if pk.get("d_nm") else ""
        lines.append(f"fringes {pk['period_px']:.2f} px{d} ({pk['angle_deg']:.0f}°)")
    for d in fr.dlabels:
        if d.get("measured_nm"):
            lines.append(f"printed d {d['d']:g} {d['unit']} {d['hkl']} → measured {d['measured_nm']:.3f} nm")
    if lines:
        ax.text(0.01, 0.99, "\n".join(lines), transform=ax.transAxes, color="w", fontsize=6, va="top",
                bbox=dict(fc="k", ec="none", alpha=0.55, pad=1.5))
    ax.set_axis_off()
    fig.savefig(path, bbox_inches="tight"); plt.close(fig)
    return path


def overlay(p, path: str) -> str:
    rgb = p.page.rgb
    if getattr(p, "frame", None) is not None:
        return _frame_overlay(p, path)
    if p.mode == "derived" and getattr(p, "frames", None):
        fig, ax = plt.subplots(figsize=(6, 6 * rgb.shape[0] / rgb.shape[1]), dpi=130)
        ax.imshow(rgb, interpolation="none")
        for fr in p.frames:
            x0, y0, x1, y1 = fr.box
            ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec="#00c000", lw=0.8))
            if fr.title:
                ax.text(x0, y0, fr.title, color="#00a000", fontsize=6, va="bottom")
        ax.set_axis_off(); fig.savefig(path, bbox_inches="tight"); plt.close(fig)
        return path
    if p.kind == "micrograph":
        r = p.micro
        fig, ax = plt.subplots(figsize=(6, 6 * rgb.shape[0] / rgb.shape[1]), dpi=150)
        ax.imshow(rgb, interpolation="none")
        if r.particles:
            from skimage.segmentation import find_boundaries
            bnd = find_boundaries(r.particles["labels"], mode="outer")
            ov = np.zeros(bnd.shape + (4,)); ov[bnd] = (0, 1, 1, 0.9)
            ax.imshow(ov, interpolation="none")
        if r.bar is not None:
            ax.plot([r.bar.x0, r.bar.x1], [r.bar.y + 2.5 * r.bar.thickness] * 2, color="#ff00ff", lw=1.5)
            ax.text(0.5 * (r.bar.x0 + r.bar.x1), r.bar.y + 3.5 * r.bar.thickness,
                    f"{r.bar.length_px:.1f} px = {r.bar.value} {r.bar.unit}", color="#ff00ff", ha="center", va="top", fontsize=7)
            x0, y0, x1, y1 = r.bar.panel_box
            ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec="yellow", lw=0.8, ls="--"))
        ax.set_axis_off()
        fig.savefig(path, bbox_inches="tight"); plt.close(fig)
        return path
    if p.box is None:
        fig, ax = plt.subplots(figsize=(5, 4), dpi=120)
        ax.imshow(rgb); ax.set_axis_off(); fig.savefig(path); plt.close(fig)
        return path
    x0, y0, x1, y1 = _crop_bounds(p)
    crop = rgb[y0:y1, x0:x1]
    b = p.box
    ncols = 2 if p.grid is not None else 1
    w = 7.5 if ncols == 2 else 5.5
    fig, axs = plt.subplots(1, ncols, figsize=(w, w / ncols * crop.shape[0] / crop.shape[1] + 0.3), dpi=170, squeeze=False)
    ax = axs[0, 0]
    ext = (x0, x1, y1, y0)
    ax.imshow(crop, extent=ext, interpolation="none", alpha=0.55 if p.series else 1.0)
    ax.add_patch(plt.Rectangle((b.x0, b.y0), b.w, b.h, fill=False, ec="#00a000", lw=0.6, ls=":"))
    for t in b.xticks:
        ax.plot([t, t], [b.y1 - 6, b.y1 + 6], color="#00c000", lw=0.6)
    for t in b.yticks:
        ax.plot([b.x0 - 6, b.x0 + 6], [t, t], color="#00c000", lw=0.6)
    for cal, labs in ((b.xcal, b.xlabels), (b.ycal, b.ylabels)):
        if cal is None:
            continue
        for l in labs:
            ax.add_patch(plt.Rectangle((l.bbox[0], l.bbox[1]), l.bbox[2] - l.bbox[0], l.bbox[3] - l.bbox[1],
                                       fill=False, ec="#0060ff", lw=0.4))
    for bar in p.bars:
        ax.plot([bar.x0, bar.x1], [bar.top, bar.top], color="#ff00ff", lw=1.2)
        ax.text(bar.cx, bar.top - 0.02 * b.h, f"{bar.value:.4g}", color="#ff00ff", ha="center", va="bottom", fontsize=6)
    for s in p.series:
        np.array(s.color_rgb) / 255
        inv = "#ff00ff" if s.color_rgb == (0, 0, 0) or max(s.color_rgb) < 60 else "k"
        if s.kind == "markers":
            ax.plot(s.px, s.py, "+", color=inv, ms=5, mew=0.8)
            if s.yerr_lo is not None:
                lo = b.ycal.to_pos(np.asarray(s.y) - np.nan_to_num(s.yerr_lo))
                hi = b.ycal.to_pos(np.asarray(s.y) + np.nan_to_num(s.yerr_hi))
                for xx, a_, c_ in zip(s.px, lo, hi):
                    ax.plot([xx + 3, xx + 3], [a_, c_], color=inv, lw=0.5)
        else:
            ax.plot(s.px, s.py, ".", color=inv, ms=0.6, mew=0)
    ax.set_xlim(x0, x1); ax.set_ylim(y1, y0)
    ax.set_title(f"{p.id}: original (faded) + extracted ({p.mode})", fontsize=7)
    ax.tick_params(labelsize=5)
    if p.grid is not None:
        ax2 = axs[0, 1]
        from .pipeline import _cmap_from_colorbar
        cmap = _cmap_from_colorbar(p.colorbar)
        g = p.grid
        v = p.colorbar.cal.to_data(np.array([p.colorbar.lut_pos[0], p.colorbar.lut_pos[-1]]))
        z = np.where(np.isfinite(g.z), g.z, np.nan)
        ax2.pcolormesh(g.x, g.y, z, cmap=cmap, vmin=min(v), vmax=max(v), shading="auto", rasterized=True)
        if g.filled.any():
            m = np.ma.masked_where(~g.filled, np.ones_like(g.z))
            ax2.pcolormesh(g.x, g.y, m, cmap="gray", alpha=0.25, shading="auto")
        if p.xlim: ax2.set_xlim(*p.xlim)
        if p.ylim: ax2.set_ylim(*p.ylim)
        ax2.set_title("reconstructed from extracted values (grey = interpolated)", fontsize=7)
        ax2.tick_params(labelsize=5)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1d2330}
header{background:#1d2330;color:#fff;padding:18px 28px}header h1{margin:0;font-size:20px}
header p{margin:4px 0 0;color:#b9c0cf;font-size:13px}
main{max-width:1150px;margin:0 auto;padding:20px}
section{background:#fff;border:1px solid #e1e4ea;border-radius:8px;padding:18px 20px;margin:0 0 18px}
h2{font-size:16px;margin:0 0 10px}.badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;
background:#eef1f6;margin-right:6px;color:#334}
.grid{display:grid;grid-template-columns:1.3fr 1fr;gap:16px;align-items:start}
img{max-width:100%;border:1px solid #eee;border-radius:4px}
table{border-collapse:collapse;font-size:12.5px;width:100%;margin:6px 0}
td,th{border-bottom:1px solid #eee;padding:4px 6px;text-align:left}th{color:#667;font-weight:600}
ul.notes{list-style:none;padding:0;margin:8px 0;font-size:12.5px}
ul.notes li{padding:4px 8px;margin:3px 0;border-radius:4px;border-left:3px solid}
li.error{background:#fdecec;border-color:#d33}li.warn{background:#fff6e5;border-color:#e8a200}
li.info{background:#eef4ff;border-color:#5b8def}
a{color:#2457c5}.files a{margin-right:10px;font-size:12.5px}
"""


def _rel(path, base):
    return os.path.relpath(path, os.path.dirname(base))


def html(panels: List, path: str, combined=None, template="natchem") -> str:
    src = panels[0].page.source if panels else ""
    out = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>ReSrijan report – {_h.escape(os.path.basename(src))}</title>"
           f"<style>{CSS}</style></head><body><header><h1>ReSrijan extraction report</h1>"
           f"<p>{_h.escape(src)} · {len(panels)} panel(s) · replot template: {_h.escape(template)}</p></header><main>"]
    if combined:
        png = [c for c in combined if c.endswith(".png")]
        out.append("<section><h2>Combined replot</h2>")
        if png:
            out.append(f"<img src='{_rel(png[0], path)}'>")
        out.append("<div class='files'>" + "".join(f"<a href='{_rel(c, path)}'>{os.path.basename(c)}</a>" for c in combined) + "</div></section>")
    for p in panels:
        out.append(f"<section><h2>Panel {p.id}</h2><span class='badge'>{p.kind}</span><span class='badge'>{p.mode}</span>")
        if p.xlabel or p.ylabel:
            out.append(f"<span class='badge'>x: {_h.escape(p.xlabel or '?')}</span><span class='badge'>y: {_h.escape(p.ylabel or '?')}</span>")
        out.append("<div class='grid'><div>")
        if p.files.get("overlay"):
            out.append(f"<img src='{_rel(p.files['overlay'], path)}'>")
        out.append("</div><div>")
        rep = [f for f in p.files.get("replot", []) if f.endswith(".png")]
        if rep:
            out.append(f"<img src='{_rel(rep[0], path)}'>")
        out.append("</div></div>")
        if p.box is not None and (p.box.xcal or p.box.ycal):
            out.append("<table><tr><th>axis</th><th>scale</th><th>labels used</th><th>source</th><th>tick residual (px)</th>"
                       "<th>range</th><th>1 px =</th></tr>")
            for cal, lim in ((p.box.xcal, p.xlim), (p.box.ycal, p.ylim)):
                if cal is None or lim is None:
                    continue
                out.append(f"<tr><td>{cal.axis}</td><td>{cal.scale}{' (reversed)' if cal.reversed else ''}</td>"
                           f"<td>{cal.n_used}: {', '.join(f'{v:g}' for v in cal.values)}</td><td>{cal.source}</td>"
                           f"<td>{cal.rms_px:.3f}</td><td>{lim[0]:.5g} – {lim[1]:.5g}</td><td>{cal.unit_per_px:.3g}</td></tr>")
            out.append("</table>")
        if p.series:
            out.append("<table><tr><th>series</th><th>type</th><th>points</th><th>colour</th><th>x range</th><th>source</th></tr>")
            for s in p.series:
                col = "#%02x%02x%02x" % tuple(s.color_rgb)
                out.append(f"<tr><td>{_h.escape(s.name)}</td><td>{s.kind}{' (dashed)' if s.dashed else ''}</td><td>{len(s.x)}</td>"
                           f"<td><span style='display:inline-block;width:28px;height:10px;background:{col}'></span></td>"
                           f"<td>{np.nanmin(s.x):.5g} – {np.nanmax(s.x):.5g}</td><td>{s.source}</td></tr>")
            out.append("</table>")
        if p.bars:
            out.append("<table><tr><th>category</th><th>value</th><th>printed label</th><th>colour</th><th>slices</th></tr>")
            for bar in p.bars:
                col = "#%02x%02x%02x" % tuple(bar.color)
                out.append(f"<tr><td>{_h.escape(bar.category)}</td><td>{bar.value:.5g}</td>"
                           f"<td>{'' if bar.annotated is None else f'{bar.annotated:g}'}</td>"
                           f"<td><span style='display:inline-block;width:28px;height:10px;background:{col}'></span></td>"
                           f"<td>{bar.n_parts}</td></tr>")
            out.append("</table>")
        if p.micro is not None and p.micro.particles and p.micro.particles.get("stats"):
            st = p.micro.particles["stats"]
            out.append(f"<table><tr><th>particles (not touching edges)</th><th>mean</th><th>s.d.</th><th>median</th><th>PDI</th></tr>"
                       f"<tr><td>{st['n']}</td><td>{st['mean']:.4g} {st['unit']}</td><td>{st['sd']:.3g}</td>"
                       f"<td>{st['median']:.4g}</td><td>{st['polydispersity_pct']:.1f}%</td></tr></table>")
        fr = getattr(p, "frame", None)
        if fr is not None and (fr.lattice or fr.dlabels or fr.title):
            out.append("<table><tr><th>title</th><th>native size</th><th>nm/px</th><th>fringe periods (px → nm)</th>"
                       "<th>printed d</th><th>measured d</th></tr>")
            per = "; ".join(f"{pk['period_px']:.2f}" + (f" → {pk['d_nm']:.3f}" if pk.get("d_nm") else "") for pk in fr.lattice[:3])
            pd = "; ".join(f"{d['d']:g} {d['unit']} {d['hkl']}" for d in fr.dlabels)
            md = "; ".join(f"{d['measured_nm']:.3f} nm" for d in fr.dlabels if d.get("measured_nm"))
            out.append(f"<tr><td>{_h.escape(fr.title)}</td><td>{fr.rgb.shape[1]}×{fr.rgb.shape[0]}</td>"
                       f"<td>{'' if not fr.nm_per_px else f'{fr.nm_per_px:.4g}'}</td><td>{per}</td>"
                       f"<td>{_h.escape(pd)}</td><td>{md}</td></tr></table>")
        if p.notes:
            seen = set()
            out.append("<ul class='notes'>")
            for n in sorted(p.notes, key=lambda n: {"error": 0, "warn": 1, "info": 2}.get(n["level"], 3)):
                if n["msg"] in seen:
                    continue
                seen.add(n["msg"])
                out.append(f"<li class='{n['level']}'><b>{n['level']}</b> · {_h.escape(n['msg'])}</li>")
            out.append("</ul>")
        files = [(k, v) for k, v in p.files.items() if k not in ("overlay",)]
        links = []
        for k, v in files:
            for f in (v if isinstance(v, list) else [v]):
                links.append(f"<a href='{_rel(f, path)}'>{os.path.basename(f)}</a>")
        out.append("<div class='files'>" + "".join(links) + "</div></section>")
    out.append("</main></body></html>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    return path
