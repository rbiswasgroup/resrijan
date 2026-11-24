"""Project files (*.resrijan): the state of every page in one JSON file, so a session can be
reopened later – figure, region, clicked calibration, options, styling, analysis and data edits.

Paths are stored relative to the project file when they are inside its folder (projects can be
moved together with their data) and absolute otherwise."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .. import __version__

FORMAT = "resrijan-project"
EXT = ".resrijan"
PATH_KEYS = {"data", "file", "out", "spec", "edited", "source"}


def set_combo(cb, value):
    """Select the item whose data (or text) is ``value``; leave the combo alone when absent."""
    if value is None:
        return
    i = cb.findData(value)
    if i < 0:
        i = cb.findText(str(value))
    if i >= 0:
        cb.setCurrentIndex(i)


def _map_paths(obj: Any, fn) -> Any:
    if isinstance(obj, dict):
        return {k: (fn(v) if k in PATH_KEYS and isinstance(v, str) and v else _map_paths(v, fn)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_map_paths(v, fn) for v in obj]
    return obj


def to_relative(state: dict, project_path: str) -> dict:
    base = Path(project_path).resolve().parent

    def rel(p: str) -> str:
        try:
            q = Path(p).resolve()
            return os.path.relpath(q, base) if base in q.parents or q.parent == base else str(q)
        except (OSError, ValueError):
            return p
    return _map_paths(state, rel)


def to_absolute(state: dict, project_path: str) -> dict:
    base = Path(project_path).resolve().parent

    def ab(p: str) -> str:
        return p if os.path.isabs(p) else str((base / p).resolve())
    return _map_paths(state, ab)


def save(path: str, pages: dict, current: str) -> str:
    """Write the project; ``pages`` maps page key → state dict."""
    if not path.endswith(EXT):
        path += EXT
    doc = {"format": FORMAT, "version": 1, "resrijan": __version__, "current_page": current,
           "pages": to_relative(pages, path)}
    Path(path).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def load(path: str) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("format") != FORMAT:
        raise ValueError(f"{Path(path).name} is not a ReSrijan project file")
    if int(doc.get("version", 1)) > 1:
        raise ValueError(f"{Path(path).name} was saved by a newer ReSrijan ({doc.get('resrijan')}); please update")
    doc["pages"] = to_absolute(doc.get("pages", {}), path)
    return doc
