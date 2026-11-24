"""User preferences (defaults for every page), stored with QSettings in ~/.config/ReSrijan/."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

DEFAULTS = {
    "template": "natchem",
    "width": "single",
    "formats": "pdf,svg,png",
    "dpi": 600.0,
    "preview_dpi": 110.0,
    "out_mode": "next",          # next: <file>_resrijan next to the input | folder: inside out_folder
    "out_folder": str(Path.home() / "ReSrijan"),
    "open_report": False,
    "max_series": 12,
    "auto_preview": True,
}


class Prefs:
    def __init__(self):
        self.s = QSettings("ReSrijan", "ReSrijan")

    def get(self, key: str):
        d = DEFAULTS[key]
        v = self.s.value(key, d)
        if isinstance(d, bool):
            return v in (True, "true", "1", 1)
        if isinstance(d, float):
            return float(v)
        if isinstance(d, int):
            return int(v)
        return str(v)

    def set(self, key: str, value):
        self.s.setValue(key, value)

    def reset(self):
        for k in DEFAULTS:
            self.s.remove(k)

    def recent(self) -> list:
        v = self.s.value("recent", [])
        return [p for p in (v if isinstance(v, list) else [v] if v else []) if Path(p).exists()][:10]

    def add_recent(self, path: str):
        r = [p for p in self.recent() if p != path]
        self.s.setValue("recent", [path] + r[:9])

    def output_dir(self, input_path: str) -> str:
        """Default output folder for a digitised file (the CLI's default is <stem>_resrijan)."""
        p = Path(input_path)
        if self.get("out_mode") == "folder":
            return str(Path(self.get("out_folder")) / f"{p.stem}_resrijan")
        return str(p.with_name(f"{p.stem}_resrijan"))
