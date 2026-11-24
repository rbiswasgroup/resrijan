"""Journal style templates (YAML) → matplotlib rcParams."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Union

import yaml
from matplotlib import font_manager

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
MM = 1 / 25.4


@dataclass
class Template:
    key: str
    name: str
    widths_mm: Dict[str, float]
    max_height_mm: float
    font: dict
    panel_label: dict
    axes: dict
    lines: dict
    palette: List[str]
    cmap: dict
    export: dict
    mathtext: str = "dejavusans"
    aliases: List[str] = field(default_factory=list)
    path: str = ""

    def width_mm(self, width: Union[str, float, None]) -> float:
        if width is None:
            return self.widths_mm.get("double", max(self.widths_mm.values()))
        if isinstance(width, (int, float)):
            return float(width)
        w = str(width).lower().replace("-", "").replace("_", "")
        alias = {"1": "single", "one": "single", "1col": "single", "column": "single",
                 "2": "double", "two": "double", "2col": "double", "page": "double", "full": "double",
                 "1.5": "onehalf", "onehalfcol": "onehalf", "1.5col": "onehalf"}
        w = alias.get(w, w)
        if w in self.widths_mm:
            return float(self.widths_mm[w])
        if w == "full" and "full" in self.widths_mm:
            return float(self.widths_mm["full"])
        try:
            return float(w.replace("mm", ""))
        except ValueError:
            raise ValueError(f"Unknown width '{width}' for template {self.key}: {list(self.widths_mm)}")

    def resolved_font(self) -> str:
        avail = {f.name for f in font_manager.fontManager.ttflist}
        for n in self.font["names"]:
            if n in avail:
                return n
        return "DejaVu Sans" if self.font["family"] == "sans-serif" else "DejaVu Serif"

    def rc(self) -> dict:
        f, a, l = self.font, self.axes, self.lines
        fam = f["family"]
        rc = {
            "font.family": fam,
            f"font.{fam}": [self.resolved_font()] + list(f["names"]),
            "font.size": f["size"],
            "axes.labelsize": f["label"],
            "axes.titlesize": f["label"],
            "xtick.labelsize": f["tick"],
            "ytick.labelsize": f["tick"],
            "legend.fontsize": f["legend"],
            "legend.frameon": False,
            "legend.handlelength": 1.6,
            "legend.borderaxespad": 0.3,
            "mathtext.fontset": self.mathtext if self.mathtext in ("dejavusans", "dejavuserif", "cm", "stix", "stixsans") else "custom",
            "mathtext.default": "regular",
            "axes.linewidth": a["linewidth"],
            "axes.labelpad": 2.0,
            "xtick.direction": a["tick_direction"],
            "ytick.direction": a["tick_direction"],
            "xtick.major.size": a["tick_length"],
            "ytick.major.size": a["tick_length"],
            "xtick.minor.size": a["minor_length"],
            "ytick.minor.size": a["minor_length"],
            "xtick.major.width": a["tick_width"],
            "ytick.major.width": a["tick_width"],
            "xtick.minor.width": 0.75 * a["tick_width"],
            "ytick.minor.width": 0.75 * a["tick_width"],
            "xtick.major.pad": 2.0,
            "ytick.major.pad": 2.0,
            "xtick.top": a.get("mirror_ticks", False),
            "ytick.right": a.get("mirror_ticks", False),
            "axes.spines.top": "top" in a["spines"],
            "axes.spines.right": "right" in a["spines"],
            "lines.linewidth": l["linewidth"],
            "lines.markersize": l["markersize"],
            "errorbar.capsize": l["capsize"],
            "axes.prop_cycle": __import__("cycler").cycler(color=self.palette),
            "image.cmap": self.cmap.get("sequential", "viridis"),
            "savefig.dpi": self.export.get("dpi", 600),
            "figure.dpi": 150,
            "pdf.fonttype": 42,        # TrueType: text stays editable in Illustrator/Inkscape
            "ps.fonttype": 42,
            "svg.fonttype": "none",    # real <text> elements in SVG
            "axes.unicode_minus": True,
            "figure.constrained_layout.use": False,
        }
        return rc

    def label(self, i: int) -> str:
        c = "abcdefghijklmnopqrstuvwxyz"[i % 26]
        c = c.upper() if self.panel_label.get("case") == "upper" else c
        return self.panel_label.get("format", "{}").format(c)


@lru_cache(maxsize=None)
def _all() -> Dict[str, Template]:
    out = {}
    dirs = [TEMPLATE_DIR]
    user = os.environ.get("RESRIJAN_TEMPLATES") or os.path.expanduser("~/.config/resrijan/templates")
    if os.path.isdir(user):
        dirs.append(Path(user))
    for d in dirs:
        for p in sorted(Path(d).glob("*.yaml")):
            y = yaml.safe_load(open(p))
            t = Template(key=y["key"], name=y["name"], widths_mm=y["widths_mm"], max_height_mm=y["max_height_mm"],
                         font=y["font"], panel_label=y["panel_label"], axes=y["axes"], lines=y["lines"],
                         palette=y["palette"], cmap=y.get("cmap", {}), export=y.get("export", {}),
                         mathtext=y.get("mathtext", "dejavusans"), aliases=y.get("aliases", []), path=str(p))
            out[t.key] = t
    return out


def get(name: str) -> Template:
    n = name.lower().strip()
    allt = _all()
    if n in allt:
        return allt[n]
    for t in allt.values():
        if n in [a.lower() for a in t.aliases]:
            return t
    if os.path.isfile(name):
        y = yaml.safe_load(open(name))
        return Template(key=y["key"], name=y["name"], widths_mm=y["widths_mm"], max_height_mm=y["max_height_mm"],
                        font=y["font"], panel_label=y["panel_label"], axes=y["axes"], lines=y["lines"],
                        palette=y["palette"], cmap=y.get("cmap", {}), export=y.get("export", {}),
                        mathtext=y.get("mathtext", "dejavusans"), path=name)
    raise KeyError(f"Unknown template '{name}'. Available: {', '.join(sorted(allt))}")


def available() -> List[Template]:
    return list(_all().values())
