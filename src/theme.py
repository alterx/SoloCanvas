# Copyright © 2026 Geoffrey Osterberg
#
# SoloCanvas is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SoloCanvas is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Static UI palette and canvas-item theming for SoloCanvas.

Core UI Palette
───────────────
  Primary Surface:   #1F1F27   Deep base layer
  Secondary Surface: #292A35   Panels, dialogs, editors
  Buttons / Inputs:  #3B3C4F
  Borders:           #4B4D63
  Brand / Accent:    #9E886C
  Hover:             #BFA381
  Active / Pressed:  #524E48
  Primary Text:      #FFFFFF
  Secondary Text:    #8C8D9B
"""
from __future__ import annotations

from PyQt6.QtGui import QColor


# ---------------------------------------------------------------------------
# Static application stylesheet
# ---------------------------------------------------------------------------

APP_STYLESHEET = """
/* ── Base ── */
QWidget {
    background-color: #1F1F27;
    color: #FFFFFF;
}
QMainWindow, QDialog {
    background-color: #1F1F27;
}

/* ── Menu bar ── */
QMenuBar {
    background-color: #292A35;
    color: #FFFFFF;
    border-bottom: 1px solid #4B4D63;
    padding: 2px 0;
    font-size: 13px;
}
QMenuBar::item { padding: 4px 10px; border-radius: 4px; }
QMenuBar::item:selected { background-color: #3B3C4F; }

/* ── Drop-down menus ── */
QMenu {
    background-color: #292A35;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    padding: 4px 0;
    font-size: 13px;
}
QMenu::item { padding: 5px 24px 5px 12px; border-radius: 4px; }
QMenu::item:selected { background-color: #3B3C4F; }
QMenu::item:disabled { color: #8C8D9B; }
QMenu::separator { height: 1px; background: #4B4D63; margin: 3px 8px; }

/* ── Push buttons ── */
QPushButton {
    background-color: #3B3C4F;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    border-radius: 5px;
    padding: 5px 14px;
    font-size: 13px;
}
QPushButton:hover   { background-color: #BFA381; color: #1F1F27; }
QPushButton:pressed { background-color: #524E48; }
QPushButton:disabled { color: #8C8D9B; border-color: #1F1F27; }

/* ── Tool buttons ── */
QToolButton {
    background-color: #3B3C4F;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    padding: 3px 7px;
    border-radius: 3px;
}
QToolButton:hover   { background-color: #BFA381; color: #1F1F27; }
QToolButton:pressed { background-color: #524E48; }

/* ── Toolbar ── */
QToolBar {
    background-color: #1F1F27;
    border: none;
    spacing: 2px;
    padding: 2px;
}

/* ── Status bar ── */
QStatusBar {
    background-color: #1F1F27;
    color: #8C8D9B;
    border-top: 1px solid #4B4D63;
    font-size: 11px;
}

/* ── Labels ── */
QLabel {
    background-color: transparent;
    color: #FFFFFF;
}

/* ── Line / spin / combo inputs ── */
QLineEdit {
    background-color: #3B3C4F;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    padding: 3px 5px;
    border-radius: 3px;
}
QSpinBox, QDoubleSpinBox {
    background-color: #3B3C4F;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    padding: 2px 4px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background-color: #4B4D63;
    border: 1px solid #4B4D63;
    width: 16px;
}
QComboBox {
    background-color: #3B3C4F;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    padding: 3px 8px;
    border-radius: 3px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #292A35;
    color: #FFFFFF;
    selection-background-color: #3B3C4F;
    border: 1px solid #4B4D63;
}

/* ── Tabs ── */
QTabWidget::pane {
    background-color: #292A35;
    border: 1px solid #4B4D63;
}
QTabBar::tab {
    background-color: #3B3C4F;
    color: #FFFFFF;
    padding: 5px 14px;
    border: 1px solid #4B4D63;
    border-bottom: none;
    border-radius: 3px 3px 0 0;
}
QTabBar::tab:selected { background-color: #292A35; }
QTabBar::tab:hover    { background-color: #BFA381; color: #1F1F27; }

/* ── Group boxes ── */
QGroupBox {
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #FFFFFF;
}

/* ── Checkboxes / radio buttons ── */
QCheckBox { color: #FFFFFF; }
QCheckBox::indicator {
    background-color: #3B3C4F;
    border: 1px solid #4B4D63;
    border-radius: 3px;
    width: 13px;
    height: 13px;
}
QCheckBox::indicator:checked {
    background-color: #524E48;
    border-color: #9E886C;
}
QRadioButton { color: #FFFFFF; }
QRadioButton::indicator {
    background-color: #3B3C4F;
    border: 1px solid #4B4D63;
    border-radius: 7px;
    width: 13px;
    height: 13px;
}
QRadioButton::indicator:checked { background-color: #9E886C; }

/* ── Sliders ── */
QSlider::groove:horizontal {
    background: #3B3C4F;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #9E886C;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}

/* ── Scrollbars ── */
QScrollBar:vertical {
    background: #1F1F27;
    width: 8px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #3B3C4F;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #4B4D63; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical,  QScrollBar::sub-page:vertical  { background: none; }
QScrollBar:horizontal {
    background: #1F1F27;
    height: 8px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #3B3C4F;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #4B4D63; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }

/* ── Trees / lists ── */
QTreeView, QListWidget, QListView {
    background-color: #292A35;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    alternate-background-color: #1F1F27;
}
QTreeView::item:selected, QListWidget::item:selected {
    background-color: #3B3C4F;
    color: #FFFFFF;
}
QTreeView::item:hover, QListWidget::item:hover { background-color: #3B3C4F; }

/* ── Tables ── */
QTableWidget, QTableView {
    background-color: #292A35;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    gridline-color: #4B4D63;
}
QTableWidget::item, QTableView::item { padding: 2px; }
QTableWidget::item:selected, QTableView::item:selected {
    background-color: #3B3C4F;
    color: #FFFFFF;
}

/* ── Text / plain-text editors ── */
QTextEdit, QPlainTextEdit {
    background-color: #292A35;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
}

/* ── Splitter handles ── */
QSplitter::handle { background-color: #4B4D63; }

/* ── Header views ── */
QHeaderView::section {
    background-color: #3B3C4F;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    padding: 4px;
}

/* ── Tooltips ── */
QToolTip {
    background-color: #292A35;
    color: #FFFFFF;
    border: 1px solid #4B4D63;
    padding: 4px 8px;
    font-size: 12px;
}
"""


# ---------------------------------------------------------------------------
# Canvas-item helpers (still dynamic — canvas bg remains user-configurable)
# ---------------------------------------------------------------------------

def text_color(bg: QColor) -> QColor:
    """Light text on dark backgrounds; dark text on light backgrounds."""
    lum = 0.299 * bg.redF() + 0.587 * bg.greenF() + 0.114 * bg.blueF()
    return QColor(230, 232, 235) if lum < 0.5 else QColor(22, 22, 28)


def _adj(c: QColor, v_factor: float, s_factor: float = 1.0) -> QColor:
    h, s, v, _ = c.getHsvF()
    out = QColor()
    out.setHsvF(h, min(1.0, max(0.0, s * s_factor)),
                min(1.0, max(0.0, v * v_factor)))
    return out


def build_canvas_item_stylesheet(canvas_hex: str) -> tuple[str, str, str, str]:
    """
    Returns (bg_css, text_hex, border_hex, sel_hex) for widgets that should
    use the canvas colour (e.g. the Notepad editor).
    """
    bg  = QColor(canvas_hex)
    txt = text_color(bg)
    brd = _adj(bg, 1.4) if bg.valueF() < 0.5 else _adj(bg, 0.7)
    sel = _adj(bg, 1.5) if bg.valueF() < 0.5 else _adj(bg, 0.75)
    return bg.name(), txt.name(), brd.name(), sel.name()
