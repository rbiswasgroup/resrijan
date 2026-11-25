"""Small line icons (drawn here as SVG, 24×24, stroke-only) tinted to the theme."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    # frame corners + rising line: digitise a figure
    "digitize": '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><path d="M7 15l3-3 3 2 4-5"/>',
    # axes + curve: plot data
    "plot": '<path d="M4 4v16h16"/><path d="M7 16c3-1 4-8 7-9 2-.6 3 1 5 0"/>',
    # stacked panels: compose
    "compose": '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/>'
               '<rect x="3" y="13" width="18" height="8" rx="1.5"/>',
    # page with corner fold: templates
    "templates": '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/><path d="M9 12h7M9 16h5"/>',
    # magnifier: inspect
    "inspect": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5.5 5.5"/><path d="M8 10.5h5M10.5 8v5"/>',
    # sliders: settings
    "settings": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h7V3M8 21v-7h8v7"/>',
    "run": '<path d="M7 4l12 8-12 8z"/>',
    "region": '<rect x="4" y="6" width="16" height="12" rx="1" stroke-dasharray="3 2"/>',
    "pickx": '<path d="M3 18h18"/><path d="M7 18v-4M17 18v-4"/><circle cx="7" cy="9" r="2"/>',
    "picky": '<path d="M6 3v18"/><path d="M6 7h4M6 17h4"/><circle cx="15" cy="7" r="2"/>',
    "clear": '<path d="M6 6l12 12M18 6L6 18"/>',
    "fit": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "zoomin": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5.5 5.5M8 10.5h5M10.5 8v5"/>',
    "zoomout": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5.5 5.5M8 10.5h5"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "report": '<path d="M6 3h9l4 4v14H6z"/><path d="M9 17v-3M12 17v-6M15 17v-4"/>',
    "import": '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v3h16v-3"/>',
    "duplicate": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M4 16V5a1 1 0 0 1 1-1h11"/><path d="M14 11v6M11 14h6"/>',
    "delete": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    # peaks under a fitted envelope: analyze
    "analyze": '<path d="M3 20h18"/><path d="M3 18c3 0 3.5-11 6-11s2.5 9 4.5 9 2-6 3.5-6 2 8 4 8"/>',
    # crosshair on a peak: place a peak
    "peak": '<path d="M4 19c4 0 5-13 8-13s4 13 8 13"/><path d="M12 2v6M9 5h6"/>',
    # points with a fitted curve: the Fit page
    "curvefit": '<path d="M4 4v16h16"/><path d="M6 7c3 6 7 9 14 10"/><circle cx="8" cy="10.5" r="1"/><circle cx="12" cy="14" r="1"/><circle cx="16.5" cy="16" r="1"/>',
    # pencil: edit data
    "edit": '<path d="M4 20l1-5L16 4l4 4L9 19z"/><path d="M13 7l4 4"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
}


@lru_cache(maxsize=None)
def icon(name: str, color: str = "#8a96b0", size: int = 22) -> QIcon:
    body = _P.get(name, _P["open"])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    ic = QIcon()
    for s in (size, size * 2):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        r.render(p, QRectF(0, 0, s, s))
        p.end()
        ic.addPixmap(pm)
    return ic


def nav_icon(name: str) -> QIcon:
    """Sidebar icon: muted normally, teal when checked."""
    ic = QIcon()
    for mode_color, state in (("#8a96b0", QIcon.Off), ("#5ef2df", QIcon.On)):
        base = icon(name, mode_color, 22)
        for s in (22, 44):
            ic.addPixmap(base.pixmap(s, s), QIcon.Normal, state)
    return ic
