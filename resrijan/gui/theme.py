"""Dark theme: colours from the ReSrijan logo (navy, teal, saffron) as a Qt palette + stylesheet."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

C = {
    "bg": "#0b1120",          # window
    "surface": "#121a2c",     # cards, inputs
    "surface2": "#18223a",    # hover, headers
    "border": "#25314d",
    "text": "#e6ebf5",
    "muted": "#8a96b0",
    "accent": "#19c3b1",      # teal (logo "Srijan")
    "accent2": "#5ef2df",
    "accent_dark": "#0e8f83",
    "saffron": "#ff9a2e",     # warnings (logo स)
    "green": "#3cb44b",       # ok
    "red": "#ff5a5f",         # errors
    "sel": "#1d3b4f",
}


def palette() -> QPalette:
    p = QPalette()
    q = lambda k: QColor(C[k])  # noqa: E731
    p.setColor(QPalette.Window, q("bg"))
    p.setColor(QPalette.WindowText, q("text"))
    p.setColor(QPalette.Base, q("surface"))
    p.setColor(QPalette.AlternateBase, q("surface2"))
    p.setColor(QPalette.ToolTipBase, q("surface2"))
    p.setColor(QPalette.ToolTipText, q("text"))
    p.setColor(QPalette.Text, q("text"))
    p.setColor(QPalette.Button, q("surface"))
    p.setColor(QPalette.ButtonText, q("text"))
    p.setColor(QPalette.BrightText, q("accent2"))
    p.setColor(QPalette.Highlight, q("accent_dark"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Link, q("accent"))
    p.setColor(QPalette.PlaceholderText, q("muted"))
    for grp in (QPalette.Disabled,):
        p.setColor(grp, QPalette.Text, q("muted"))
        p.setColor(grp, QPalette.ButtonText, q("muted"))
        p.setColor(grp, QPalette.WindowText, q("muted"))
    return p


STYLESHEET = """
* { font-size: 13px; }
QMainWindow, QDialog { background: %(bg)s; }
QWidget { color: %(text)s; }
QToolTip { background: %(surface2)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px 6px; border-radius: 6px; }

/* sidebar */
#Sidebar { background: #080d19; border-right: 1px solid %(border)s; }
#Sidebar QPushButton { text-align: left; padding: 10px 14px; margin: 2px 8px; border: none; border-radius: 10px;
                       color: %(muted)s; background: transparent; font-size: 14px; }
#Sidebar QPushButton:hover { background: %(surface)s; color: %(text)s; }
#Sidebar QPushButton:checked { background: %(sel)s; color: %(accent2)s; font-weight: 600; }
#Brand { padding: 14px 10px 6px 10px; }
#Version { color: %(muted)s; font-size: 11px; padding: 0 16px 12px 16px; }

/* page header */
#PageTitle { font-size: 22px; font-weight: 700; color: %(text)s; }
#PageSubtitle { color: %(muted)s; font-size: 13px; }

/* cards / group boxes */
QGroupBox { background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px; margin-top: 18px;
            padding: 14px 10px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; top: 2px; padding: 0 4px; color: %(accent2)s; }
#Card { background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px; }

/* inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
    background: #0e1627; border: 1px solid %(border)s; border-radius: 8px; padding: 5px 8px;
    selection-background-color: %(accent_dark)s; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid %(accent)s; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: %(muted)s; background: %(surface)s; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url(@ASSETS@/down.svg); width: 12px; height: 12px; }
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; width: 20px; border: none; background: transparent; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: %(surface2)s; border-radius: 4px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(@ASSETS@/up.svg); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(@ASSETS@/down.svg); width: 10px; height: 10px; }
QComboBox QAbstractItemView { background: %(surface)s; border: 1px solid %(border)s; selection-background-color: %(sel)s;
                              outline: none; padding: 4px; }
QPlainTextEdit#Code, QTextEdit#Code { font-family: "DejaVu Sans Mono", "Liberation Mono", monospace; font-size: 12px; }

/* buttons */
QPushButton { background: %(surface2)s; border: 1px solid %(border)s; border-radius: 8px; padding: 6px 14px; }
QPushButton:hover { border-color: %(accent)s; }
QPushButton:pressed { background: %(sel)s; }
QPushButton:disabled { color: %(muted)s; border-color: %(surface2)s; }
QPushButton#Primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 %(accent)s, stop:1 %(accent_dark)s);
                      color: #04201d; font-weight: 700; border: none; padding: 9px 20px; font-size: 14px; }
QPushButton#Primary:hover { background: %(accent2)s; }
QPushButton#Primary:disabled { background: %(surface2)s; color: %(muted)s; }
QPushButton#Danger { color: %(red)s; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px; }
QToolButton:hover { background: %(surface2)s; border-color: %(border)s; }
QToolButton:checked { background: %(sel)s; border-color: %(accent)s; }

QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid %(border)s; background: #0e1627; }
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: %(accent)s; border-color: %(accent)s; }

/* tabs */
QTabWidget::pane { border: 1px solid %(border)s; border-radius: 10px; top: -1px; background: %(surface)s; }
QTabBar::tab { background: transparent; color: %(muted)s; padding: 7px 14px; margin-right: 2px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: %(accent2)s; border-bottom: 2px solid %(accent)s; }
QTabBar::tab:hover { color: %(text)s; }

/* lists / tables */
QTreeWidget, QTableWidget, QListWidget, QTableView, QTreeView {
    background: %(surface)s; alternate-background-color: #141d31; border: 1px solid %(border)s; border-radius: 10px;
    gridline-color: %(border)s; outline: none; }
QTreeWidget::item, QListWidget::item { padding: 4px; }
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {
    background: %(sel)s; color: %(accent2)s; }
QHeaderView::section { background: %(surface2)s; color: %(muted)s; border: none; border-right: 1px solid %(border)s;
                       padding: 5px 8px; font-weight: 600; }

/* scroll bars */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: %(border)s; border-radius: 4px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: %(muted)s; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QSplitter::handle { background: %(bg)s; }
QSplitter::handle:hover { background: %(border)s; }
QStatusBar { background: #080d19; color: %(muted)s; border-top: 1px solid %(border)s; }
QProgressBar { background: %(surface)s; border: 1px solid %(border)s; border-radius: 6px; height: 10px; text-align: center; }
QProgressBar::chunk { background: %(accent)s; border-radius: 5px; }
QMenu { background: %(surface)s; border: 1px solid %(border)s; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: %(sel)s; }
QGraphicsView { background: #070b15; border: 1px solid %(border)s; border-radius: 10px; }
QLabel#Muted { color: %(muted)s; }
QLabel#Badge { border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600; }
QFrame#Drop { border: 2px dashed %(border)s; border-radius: 12px; background: #0d1526; }
QFrame#Drop[hover="true"] { border-color: %(accent)s; background: #0f1e2c; }
""" % C


def apply(app):
    from pathlib import Path
    assets = (Path(__file__).resolve().parent / "assets").as_posix()
    app.setStyle("Fusion")
    app.setPalette(palette())
    app.setStyleSheet(STYLESHEET.replace("@ASSETS@", assets))
