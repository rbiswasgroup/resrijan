"""Import, validate, duplicate and delete journal templates (user folder: $RESRIJAN_TEMPLATES,
%APPDATA%\\resrijan\\templates on Windows, ~/.config/resrijan/templates elsewhere)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..plot import templates as T

REQUIRED = ["key", "name", "widths_mm", "max_height_mm", "font", "panel_label", "axes", "lines", "palette"]
FONT_KEYS = ["family", "names", "size", "tick", "label", "legend"]
AXES_KEYS = ["linewidth", "tick_direction", "tick_length", "minor_length", "tick_width", "spines"]
LINE_KEYS = ["linewidth", "markersize", "capsize", "errorbar_lw"]


def user_dir() -> Path:
    return T.user_template_dir()


def builtin_keys() -> set:
    return {p.stem for p in T.TEMPLATE_DIR.glob("*.yaml")}


def is_user_template(t) -> bool:
    try:
        return Path(t.path).resolve().parent == user_dir().resolve()
    except OSError:
        return False


def validate(text: str) -> dict:
    """Parse and check a template; raises ValueError with a readable message. Also renders a
    tiny figure with it, so a template that matplotlib cannot use is caught here."""
    try:
        y = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Not valid YAML: {exc}") from None
    if not isinstance(y, dict):
        raise ValueError("A template is a YAML mapping (key: value lines).")
    missing = [k for k in REQUIRED if k not in y]
    if missing:
        raise ValueError("Missing entries: " + ", ".join(missing))
    if not re.fullmatch(r"[a-z0-9][a-z0-9_\-]*", str(y["key"])):
        raise ValueError("'key' must be lower-case letters, digits, '-' or '_' (it becomes the file name).")
    for sect, keys in (("font", FONT_KEYS), ("axes", AXES_KEYS), ("lines", LINE_KEYS)):
        if not isinstance(y[sect], dict):
            raise ValueError(f"'{sect}' must be a mapping.")
        miss = [k for k in keys if k not in y[sect]]
        if miss:
            raise ValueError(f"'{sect}' is missing: " + ", ".join(miss))
    if not isinstance(y["widths_mm"], dict) or not y["widths_mm"]:
        raise ValueError("'widths_mm' must map names (single, double …) to widths in mm.")
    if not isinstance(y["palette"], list) or not y["palette"]:
        raise ValueError("'palette' must be a list of colours.")
    tpl = T.Template(key=y["key"], name=y["name"], widths_mm=y["widths_mm"], max_height_mm=y["max_height_mm"],
                     font=y["font"], panel_label=y["panel_label"], axes=y["axes"], lines=y["lines"],
                     palette=y["palette"], cmap=y.get("cmap", {}), export=y.get("export", {}),
                     mathtext=y.get("mathtext", "dejavusans"), aliases=y.get("aliases", []))
    try:
        import matplotlib.pyplot as plt
        with plt.rc_context(tpl.rc()):
            fig = plt.figure(figsize=(1, 1))
            fig.add_subplot().plot([0, 1], [0, 1])
            fig.canvas.draw()
            plt.close(fig)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"matplotlib cannot use this template: {exc}") from None
    return y


def target_path(key: str) -> Path:
    return user_dir() / f"{key}.yaml"


def save_template(text: str, overwrite: bool = False) -> Path:
    """Validate ``text`` and write it to the user folder as <key>.yaml."""
    y = validate(text)
    p = target_path(y["key"])
    if p.exists() and not overwrite:
        raise FileExistsError(str(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    reload()
    return p


def import_file(path: str, overwrite: bool = False) -> Path:
    return save_template(Path(path).read_text(encoding="utf-8"), overwrite=overwrite)


def duplicate_text(src_path: str, new_key: str, new_name: str) -> str:
    """Copy of a template's YAML with a new key, name and no aliases (comments kept)."""
    text = Path(src_path).read_text(encoding="utf-8")
    text = re.sub(r"(?m)^key:.*$", f"key: {new_key}", text)
    text = re.sub(r"(?m)^name:.*$", f"name: {new_name}", text)
    text = re.sub(r"(?m)^aliases:.*$", "aliases: []", text)
    return text


def delete(key: str):
    p = target_path(key)
    if p.exists():
        p.unlink()
    reload()


def reload():
    T._all.cache_clear()
