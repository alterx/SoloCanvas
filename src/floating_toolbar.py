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

"""Floating tool bar that hovers over the canvas, anchored to the top-right."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional

import qtawesome as qta

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QRectF,
    QSize, Qt, QTimer, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QToolTip, QWidget


# ---------------------------------------------------------------------------
# Dimensions & palette constants
# ---------------------------------------------------------------------------

_TB_WIDTH    = 52    # total widget width (px)
_TB_PAD      = 8     # inner padding around buttons
_TB_BTN_SIZE = 36    # button square size (px)
_TB_GAP      = 6     # vertical gap between regular buttons
_TB_COLL_H   = 28    # height of the collapse/expand toggle strip at top
_TB_RADIUS   = 10    # corner radius of the toolbar background
_TB_MARGIN   = 10    # distance from the right/top edge of the parent

# Sub-drawer (measurement tools) constants
_TB_SUB_BTN  = 24    # sub-button height (px)
_TB_SUB_W    = 36    # sub-button width  (px) — same as _TB_BTN_SIZE
_TB_SUB_GAP  = 3     # gap between sub-buttons
_TB_SUB_SEP  = 6     # extra spacing between mode-row and type-row

_ICON_SIZE     = QSize(_TB_BTN_SIZE - 14, _TB_BTN_SIZE - 14)  # 22 × 22
_ICON_SIZE_SUB = QSize(_TB_SUB_BTN - 8, _TB_SUB_BTN - 8)     # 16 × 16

_C_BG         = QColor("#292A35")
_C_BORDER     = QColor("#4B4D63")
_C_BTN        = QColor("#3B3C4F")
_C_BTN_ACTIVE = QColor("#524E48")   # active/selected button state
_C_HOV_BG     = QColor("#BFA381")
_C_GHOST      = QColor("#4B4D63")
_C_ICON       = "#9E886C"
_C_ICON_HOV   = "#1F1F27"
_C_ICON_ACT   = "#BFA381"           # icon colour when button is 'active'
_C_SEP        = QColor("#4B4D63")
_C_INSET_BG   = QColor(15, 15, 20, 180)   # inset button background (darker)
_C_INSET_BDR  = QColor("#4B4D63")
_C_INSET_SEL  = QColor("#524E48")         # selected inset button

_LONG_PRESS_MS   = 500   # ms before drag mode activates
_WIGGLE_INTERVAL = 16    # ms per wiggle frame (~60 fps)
_WIGGLE_SPEED    = 0.45  # radians per frame
_WIGGLE_AMP      = 3     # px of horizontal wiggle


# ---------------------------------------------------------------------------
# Button registry  (id, qtawesome icon, tooltip label)
# ---------------------------------------------------------------------------

BUTTONS: List[tuple] = [
    ("hand",     "svg:resources/images/cards.svg", "Hand"),
    ("lib",      "fa5s.layer-group",    "Deck Library"),
    ("rcl",      "fa5s.undo-alt",       "Recall Cards"),
    ("img_lib",  "fa5s.images",         "Image Library"),
    ("dice",     "fa5s.dice",           "Dice Library"),
    ("log",      "fa5s.scroll",         "Roll Log"),
    ("notepad",  "fa5s.book-open",      "Notepad"),
    ("measure",  "fa5s.ruler-combined", "Measure"),
    ("draw",     "fa5s.pencil-alt",     "Draw"),
    ("pdf",      "fa5s.file-pdf",       "PDF Viewer"),
]
_ALL_IDS = [b[0] for b in BUTTONS]

# Measure sub-drawer buttons: (id, icon, tooltip, group)
# group "mode" = Grid/Free radio  |  group "type" = Line/Area/Cone selector
_SUB_BUTTONS: List[tuple] = [
    ("sub_grid",  "fa5s.th",           "Grid Mode",  "mode"),
    ("sub_free",  "fa5s.arrows-alt",   "Free Mode",  "mode"),
    ("sub_line",  "fa5s.ruler",        "Line",       "type"),
    ("sub_area",  "fa5s.circle",       "Area",       "type"),
    ("sub_cone",  "fa5s.play",         "Cone",       "type"),
]

# Draw sub-drawer buttons: (id, icon, tooltip)  — single column, no groups
_DRAW_SUB_BUTTONS: List[tuple] = [
    ("sub_draw_freehand", "fa5s.paint-brush", "Freehand"),
    ("sub_draw_circle",   "fa5s.circle",      "Circle"),
    ("sub_draw_square",   "fa5s.square",      "Square"),
    ("sub_draw_eraser",   "fa5s.eraser",      "Eraser"),
    ("sub_draw_trash",    "fa5s.trash",       "Clear All Drawings"),
]

# Fixed buttons above the reorderable list (not reorderable, not hideable via menu)
_POINTER_BTN = ("pointer", "fa5s.mouse-pointer", "Pointer (deactivate tool)")


# ---------------------------------------------------------------------------
# FloatingToolbar
# ---------------------------------------------------------------------------

class FloatingToolbar(QWidget):
    """Floating vertical toolbar anchored to the top-right of its parent."""

    # One signal per reorderable action button
    hand_clicked    = pyqtSignal()   # toggles hand widget visibility
    lib_clicked     = pyqtSignal()
    rcl_clicked     = pyqtSignal()
    img_lib_clicked = pyqtSignal()
    dice_clicked    = pyqtSignal()
    log_clicked     = pyqtSignal()
    notepad_clicked = pyqtSignal()
    pdf_clicked     = pyqtSignal()
    measure_clicked = pyqtSignal()   # toggles measure mode on/off

    # Tool / sub-option signals
    tool_changed          = pyqtSignal(str)   # "pointer" | "measure" | "draw"
    measure_mode_changed  = pyqtSignal(str)   # "grid"    | "free"
    measure_type_changed  = pyqtSignal(str)   # "line"    | "area"    | "cone"
    draw_tool_changed     = pyqtSignal(str)   # "freehand" | "circle" | "square" | "eraser"
    draw_trash_requested  = pyqtSignal()      # clear all drawings

    _SIGNAL_MAP: Dict[str, str] = {
        "hand":    "hand_clicked",
        "lib":     "lib_clicked",
        "rcl":     "rcl_clicked",
        "img_lib": "img_lib_clicked",
        "dice":    "dice_clicked",
        "log":     "log_clicked",
        "notepad": "notepad_clicked",
        "pdf":     "pdf_clicked",
    }

    def __init__(self, settings, parent: QWidget) -> None:
        super().__init__(parent)
        self._settings = settings

        # --- Load persisted state ---
        self._order: List[str] = list(settings.toolbar("button_order"))
        self._vis: Dict[str, bool] = dict(settings.toolbar("button_visibility"))
        self._collapsed: bool = bool(settings.toolbar("collapsed"))

        # Ensure all IDs present (handles additions after save)
        for bid in _ALL_IDS:
            if bid not in self._order:
                self._order.append(bid)
        self._order = [b for b in self._order if b in _ALL_IDS]
        for bid in _ALL_IDS:
            self._vis.setdefault(bid, True)

        # --- Tool state ---
        self._active_tool: str = "pointer"      # "pointer" | "measure" | "draw"
        self._measure_mode: str = settings.measurement("mode")    # "grid" | "free"
        self._measure_type: str = settings.measurement("measure_type")  # "line"|"area"|"cone"
        self._draw_sub_tool: str = settings.drawing("sub_tool")   # "freehand"|"circle"|"square"|"eraser"

        # --- Hand widget state ---
        self._hand_visible: bool = True
        self._hand_card_count: int = 0

        # --- Widget attributes ---
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFixedWidth(_TB_WIDTH)

        # --- Animated height ---
        self._current_h: int = _TB_WIDTH if self._collapsed else self._calc_expanded_h()
        self.setFixedHeight(self._current_h)

        self._expand_anim = QPropertyAnimation(self, b"toolbar_h")
        self._expand_anim.setDuration(200)
        self._expand_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # --- Drop shadow ---
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(shadow)

        # --- Long-press timer ---
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.setInterval(_LONG_PRESS_MS)
        self._long_press_timer.timeout.connect(self._on_long_press)

        # --- Wiggle timer ---
        self._wiggle_timer = QTimer(self)
        self._wiggle_timer.setInterval(_WIGGLE_INTERVAL)
        self._wiggle_timer.timeout.connect(self._wiggle_step)
        self._wiggle_phase: float = 0.0

        # --- Interaction state ---
        self._hovered: Optional[str] = None      # bid or "__toggle__"
        self._pressed_bid: Optional[str] = None  # button under press (before long-press fires)
        self._press_y: int = 0
        self._drag_bid: Optional[str] = None     # button currently being drag-reordered
        self._drag_y: int = 0
        self._drag_insert: int = 0               # insert position in visible list

        # --- Icon pixmap cache ---
        self._icon_cache: Dict[tuple, QPixmap] = {}

        self._reposition()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _subdrawer_height(self) -> int:
        """Height of the Measure sub-drawer."""
        n = len(_SUB_BUTTONS)  # 5
        return (n - 1) * (_TB_SUB_BTN + _TB_SUB_GAP) + _TB_SUB_SEP + _TB_SUB_BTN + _TB_GAP

    def _draw_subdrawer_height(self) -> int:
        """Height of the Draw sub-drawer (single column, no separator)."""
        n = len(_DRAW_SUB_BUTTONS)  # 5
        return (n - 1) * (_TB_SUB_BTN + _TB_SUB_GAP) + _TB_SUB_BTN + _TB_GAP

    def _measure_btn_vis_idx(self) -> int:
        """Index of 'measure' in the visible list, or -1 if not visible."""
        visible = self._visible_order()
        try:
            return visible.index("measure")
        except ValueError:
            return -1

    def _draw_btn_vis_idx(self) -> int:
        """Index of 'draw' in the visible list, or -1 if not visible."""
        visible = self._visible_order()
        try:
            return visible.index("draw")
        except ValueError:
            return -1

    def _calc_expanded_h(self) -> int:
        h = _TB_COLL_H + _TB_PAD          # collapse strip + top padding
        h += _TB_BTN_SIZE + _TB_GAP       # Pointer button + gap
        n = sum(1 for bid in self._order if self._vis.get(bid, True))
        if n > 0:
            h += n * _TB_BTN_SIZE + max(0, n - 1) * _TB_GAP
            if self._active_tool == "measure" and self._measure_btn_vis_idx() >= 0:
                h += self._subdrawer_height()
            if self._active_tool == "draw" and self._draw_btn_vis_idx() >= 0:
                h += self._draw_subdrawer_height()
        h += _TB_PAD
        return h

    def _reposition(self) -> None:
        p = self.parent()
        if p is None:
            return
        x = p.width() - _TB_WIDTH - _TB_MARGIN
        self.move(x, _TB_MARGIN)

    # ------------------------------------------------------------------
    # Animated height property (target for QPropertyAnimation)
    # ------------------------------------------------------------------

    def _get_toolbar_h(self) -> int:
        return self._current_h

    def _set_toolbar_h(self, v: int) -> None:
        self._current_h = v
        self.setFixedHeight(v)
        if self.parent():
            self.parent().update()  # clear stale shadow pixels left in parent by previous frame
        self.update()

    toolbar_h = pyqtProperty(int, _get_toolbar_h, _set_toolbar_h)

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        target = _TB_WIDTH if self._collapsed else self._calc_expanded_h()
        self._expand_anim.stop()
        self._expand_anim.setStartValue(self._current_h)
        self._expand_anim.setEndValue(target)
        self._expand_anim.start()
        self._settings.set_toolbar("collapsed", self._collapsed)
        self._settings.save()

    # ------------------------------------------------------------------
    # Button visibility (called from menu bar)
    # ------------------------------------------------------------------

    def set_button_visible(self, bid: str, visible: bool) -> None:
        self._vis[bid] = visible
        self._settings.set_toolbar("button_visibility", dict(self._vis))
        self._settings.save()
        if not self._collapsed:
            target = self._calc_expanded_h()
            self._expand_anim.stop()
            self._expand_anim.setStartValue(self._current_h)
            self._expand_anim.setEndValue(target)
            self._expand_anim.start()
        self.update()

    def button_visible(self, bid: str) -> bool:
        return self._vis.get(bid, True)

    # ------------------------------------------------------------------
    # Tool activation (called from toolbar clicks and MainWindow)
    # ------------------------------------------------------------------

    def set_active_tool(self, tool: str) -> None:
        """Set the active tool externally: 'pointer' | 'measure' | 'draw'."""
        if tool == self._active_tool:
            return
        self._active_tool = tool
        if not self._collapsed:
            target = self._calc_expanded_h()
            self._expand_anim.stop()
            self._expand_anim.setStartValue(self._current_h)
            self._expand_anim.setEndValue(target)
            self._expand_anim.start()
        self.update()

    def active_tool(self) -> str:
        return self._active_tool

    def set_measure_mode(self, mode: str) -> None:
        self._measure_mode = mode
        self._settings.set_measurement("mode", mode)
        self._settings.save()
        self.update()

    def set_measure_type(self, mtype: str) -> None:
        self._measure_type = mtype
        self._settings.set_measurement("measure_type", mtype)
        self._settings.save()
        self.update()

    def set_hand_visible(self, visible: bool) -> None:
        self._hand_visible = visible
        self.update()

    def set_hand_card_count(self, count: int) -> None:
        self._hand_card_count = count
        self.update()

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _visible_order(self) -> List[str]:
        return [bid for bid in self._order if self._vis.get(bid, True)]

    def _toggle_rect(self) -> QRect:
        return QRect(0, 0, _TB_WIDTH, _TB_COLL_H)

    def _pointer_rect(self) -> QRect:
        """Rect for the fixed Pointer button (always at top of button area)."""
        y = _TB_COLL_H + _TB_PAD
        return QRect(_TB_PAD, y, _TB_BTN_SIZE, _TB_BTN_SIZE)

    def _regular_btn_rect(self, vis_idx: int) -> QRect:
        """Rect for the vis_idx-th visible regular button, accounting for
        sub-drawers inserted after Measure and Draw buttons."""
        y = _TB_COLL_H + _TB_PAD + _TB_BTN_SIZE + _TB_GAP
        measure_vi = self._measure_btn_vis_idx()
        draw_vi    = self._draw_btn_vis_idx()
        for i in range(vis_idx):
            y += _TB_BTN_SIZE + _TB_GAP
            if i == measure_vi and self._active_tool == "measure":
                y += self._subdrawer_height()
            if i == draw_vi and self._active_tool == "draw":
                y += self._draw_subdrawer_height()
        return QRect(_TB_PAD, y, _TB_BTN_SIZE, _TB_BTN_SIZE)

    def _sub_btn_rect(self, sub_idx: int) -> QRect:
        """Rect for a Measure sub-drawer button (0=Grid … 4=Cone)."""
        measure_vi = self._measure_btn_vis_idx()
        if measure_vi < 0:
            return QRect()
        measure_r = self._regular_btn_rect(measure_vi)
        y = measure_r.bottom() + _TB_GAP
        if sub_idx >= 2:
            y += _TB_SUB_SEP
        y += sub_idx * (_TB_SUB_BTN + _TB_SUB_GAP)
        return QRect(_TB_PAD, y, _TB_SUB_W, _TB_SUB_BTN)

    def _draw_sub_btn_rect(self, sub_idx: int) -> QRect:
        """Rect for a Draw sub-drawer button (0=Freehand … 4=Trash)."""
        draw_vi = self._draw_btn_vis_idx()
        if draw_vi < 0:
            return QRect()
        draw_r = self._regular_btn_rect(draw_vi)
        y = draw_r.bottom() + _TB_GAP
        y += sub_idx * (_TB_SUB_BTN + _TB_SUB_GAP)
        return QRect(_TB_PAD, y, _TB_SUB_W, _TB_SUB_BTN)

    def _bid_at(self, pos: QPoint) -> Optional[str]:
        """Return the button id under pos, or special strings, or None."""
        if self._toggle_rect().contains(pos):
            return "__toggle__"
        if self._collapsed:
            return None
        if self._pointer_rect().contains(pos):
            return "__pointer__"
        if self._active_tool == "measure":
            for i, (sid, *_) in enumerate(_SUB_BUTTONS):
                if self._sub_btn_rect(i).contains(pos):
                    return sid
        if self._active_tool == "draw":
            for i, (sid, *_) in enumerate(_DRAW_SUB_BUTTONS):
                if self._draw_sub_btn_rect(i).contains(pos):
                    return sid
        for vi, bid in enumerate(self._visible_order()):
            if self._regular_btn_rect(vi).contains(pos):
                return bid
        return None

    # ------------------------------------------------------------------
    # Icon helper
    # ------------------------------------------------------------------

    def _icon_pixmap(self, icon_name: str, color: str, size: QSize = None) -> QPixmap:
        if size is None:
            size = _ICON_SIZE
        key = (icon_name, color, size.width(), size.height())
        if key not in self._icon_cache:
            if icon_name.startswith("svg:"):
                self._icon_cache[key] = self._load_svg_pixmap(icon_name[4:], color, size)
            else:
                self._icon_cache[key] = qta.icon(icon_name, color=color).pixmap(size)
        return self._icon_cache[key]

    def _load_svg_pixmap(self, rel_path: str, color: str, size: QSize) -> QPixmap:
        """Load an SVG from a project-relative path and tint it to the given color."""
        from PyQt6.QtSvg import QSvgRenderer
        from PyQt6.QtGui import QImage
        import sys as _sys
        _base = Path(_sys.executable).parent if getattr(_sys, "frozen", False) else Path(__file__).parent.parent
        svg_path = _base / rel_path
        renderer = QSvgRenderer(str(svg_path))
        # Render SVG into a QImage with explicit alpha channel (QPixmap has no alpha on Windows)
        mask_img = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        mask_img.fill(0)  # fully transparent
        p = QPainter(mask_img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p)
        p.end()
        # Create solid-color image, then mask it with the SVG's alpha channel
        tinted = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        tinted.fill(QColor(color))
        p2 = QPainter(tinted)
        p2.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        p2.drawImage(0, 0, mask_img)
        p2.end()
        return QPixmap.fromImage(tinted)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        h = self.height()

        # Background rounded rect
        bg_rect = QRectF(0.5, 0.5, _TB_WIDTH - 1, h - 1)
        path = QPainterPath()
        path.addRoundedRect(bg_rect, _TB_RADIUS, _TB_RADIUS)
        painter.fillPath(path, _C_BG)

        # Toggle strip hover highlight
        if self._hovered == "__toggle__":
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(self._toggle_rect(), _C_BTN)
            painter.restore()

        # Border
        painter.setPen(QPen(_C_BORDER, 1))
        painter.drawPath(path)

        # Toggle icon
        tog_hov  = (self._hovered == "__toggle__")
        icon_col = _C_ICON_HOV if tog_hov else _C_ICON
        cx = _TB_WIDTH // 2
        cy = _TB_COLL_H // 2
        if self._collapsed:
            pix = self._icon_pixmap("fa5s.wrench", icon_col)
        else:
            pix = self._icon_pixmap("fa5s.chevron-up", icon_col)
        painter.drawPixmap(
            cx - _ICON_SIZE.width() // 2,
            cy - _ICON_SIZE.height() // 2,
            pix,
        )

        if self._collapsed:
            return

        # Separator below toggle
        painter.setPen(QPen(_C_SEP, 1))
        painter.drawLine(_TB_PAD, _TB_COLL_H, _TB_WIDTH - _TB_PAD, _TB_COLL_H)

        # --- Pointer button (fixed, inset style) ---
        ptr_rect = self._pointer_rect()
        ptr_hov  = (self._hovered == "__pointer__")
        ptr_active = (self._active_tool == "pointer")
        self._draw_inset_button(
            painter, ptr_rect,
            icon="fa5s.mouse-pointer",
            hovered=ptr_hov,
            selected=ptr_active,
        )

        # Thin separator below pointer button
        sep_y = ptr_rect.bottom() + _TB_GAP // 2
        painter.setPen(QPen(_C_SEP, 1))
        painter.drawLine(_TB_PAD, sep_y, _TB_WIDTH - _TB_PAD, sep_y)

        # --- Reorderable buttons (sub-drawer is interleaved after Measure) ---
        visible = self._visible_order()
        measure_vi = self._measure_btn_vis_idx()

        if self._drag_bid is not None:
            others    = [bid for bid in visible if bid != self._drag_bid]
            ins       = min(self._drag_insert, len(others))
            draw_list: List[Optional[str]] = others[:ins] + [None] + others[ins:]

            for i, bid in enumerate(draw_list):
                r = self._regular_btn_rect(i)
                if r.top() > h:
                    break
                if bid is None:
                    painter.setPen(QPen(_C_GHOST, 1, Qt.PenStyle.DashLine))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(QRectF(r).adjusted(2, 2, -2, -2), 6, 6)
                    painter.setPen(Qt.PenStyle.SolidLine)
                else:
                    self._draw_regular_button(painter, bid, r, hovered=(bid == self._hovered))

            # Dragged button floating at cursor
            wiggle_x = int(math.sin(self._wiggle_phase) * _WIGGLE_AMP)
            reg0_top = self._regular_btn_rect(0).top()
            drag_y   = max(reg0_top, min(h - _TB_BTN_SIZE - _TB_PAD, self._drag_y - _TB_BTN_SIZE // 2))
            drag_rect = QRect(_TB_PAD + wiggle_x, drag_y, _TB_BTN_SIZE, _TB_BTN_SIZE)
            painter.setBrush(QBrush(_C_HOV_BG))
            painter.setPen(QPen(_C_BORDER, 1))
            painter.drawRoundedRect(QRectF(drag_rect), 7, 7)
            icon_name = next(b[1] for b in BUTTONS if b[0] == self._drag_bid)
            pix = self._icon_pixmap(icon_name, _C_ICON_HOV)
            painter.drawPixmap(
                drag_rect.center().x() - _ICON_SIZE.width() // 2,
                drag_rect.center().y() - _ICON_SIZE.height() // 2,
                pix,
            )
        else:
            for vi, bid in enumerate(visible):
                r = self._regular_btn_rect(vi)
                if r.top() > h:
                    break
                is_active = (
                    (bid == "measure" and self._active_tool == "measure") or
                    (bid == "draw"    and self._active_tool == "draw")    or
                    (bid == "hand"    and self._hand_visible)
                )
                self._draw_regular_button(
                    painter, bid, r,
                    hovered=(bid == self._hovered),
                    active=is_active,
                )
                # Badge on hand button when hidden with cards
                if bid == "hand" and not self._hand_visible and self._hand_card_count > 0:
                    self._draw_badge(painter, r, self._hand_card_count)
                # Sub-drawers immediately after their parent button
                if bid == "measure" and self._active_tool == "measure":
                    self._paint_subdrawer(painter, h)
                if bid == "draw" and self._active_tool == "draw":
                    self._paint_draw_subdrawer(painter, h)

    def _paint_subdrawer(self, painter: QPainter, h: int) -> None:
        """Draw the 5 sub-buttons (Grid, Free, Line, Area, Cone) in their computed positions."""
        for i, (sid, icon_name, label, group) in enumerate(_SUB_BUTTONS):
            r = self._sub_btn_rect(i)
            if r.top() > h or r.isEmpty():
                break
            if group == "mode":
                sel = (sid == "sub_grid") == (self._measure_mode == "grid")
            else:
                sel = (
                    (sid == "sub_line" and self._measure_type == "line") or
                    (sid == "sub_area" and self._measure_type == "area") or
                    (sid == "sub_cone" and self._measure_type == "cone")
                )
            self._draw_inset_button(
                painter, r,
                icon=icon_name,
                hovered=(self._hovered == sid),
                selected=sel,
                small=True,
            )

    def _paint_draw_subdrawer(self, painter: QPainter, h: int) -> None:
        """Draw the 5 draw sub-buttons (single column, no groups)."""
        for i, (sid, icon_name, label) in enumerate(_DRAW_SUB_BUTTONS):
            r = self._draw_sub_btn_rect(i)
            if r.top() > h or r.isEmpty():
                break
            sel = (sid == f"sub_draw_{self._draw_sub_tool}")
            self._draw_inset_button(
                painter, r,
                icon=icon_name,
                hovered=(self._hovered == sid),
                selected=sel,
                small=True,
            )

    def _draw_badge(self, painter: QPainter, rect: QRect, count: int) -> None:
        """Draw a small card-count badge in the top-right corner of a button."""
        from PyQt6.QtGui import QFont as _QFont
        text = str(min(count, 99))
        r = 7  # badge radius
        bx = rect.right() - r + 2
        by = rect.top() + r - 2
        painter.setBrush(QBrush(QColor("#BFA381")))
        painter.setPen(QPen(QColor(15, 15, 20, 200), 1))
        painter.drawEllipse(bx - r, by - r, r * 2, r * 2)
        painter.setFont(_QFont("Arial", 7, _QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#1F1F27")))
        painter.drawText(QRect(bx - r, by - r, r * 2, r * 2),
                         Qt.AlignmentFlag.AlignCenter, text)

    def _draw_inset_button(
        self,
        painter: QPainter,
        rect: QRect,
        *,
        icon: str,
        hovered: bool,
        selected: bool,
        small: bool = False,
    ) -> None:
        """Draw an inset-style button (Pointer / sub-drawer items)."""
        if selected:
            bg = _C_INSET_SEL
        elif hovered:
            bg = QColor(80, 78, 72, 200)
        else:
            bg = _C_INSET_BG

        icon_col = _C_ICON_ACT if selected else (_C_ICON_HOV if hovered else _C_ICON)

        # Inner shadow effect: slightly lighter inner border
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(_C_INSET_BDR, 1))
        painter.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), 5, 5)

        # Inner highlight line (top edge — inverted shadow look)
        shadow_color = QColor(0, 0, 0, 80)
        painter.setPen(QPen(shadow_color, 1))
        painter.drawLine(rect.left() + 4, rect.top() + 2, rect.right() - 4, rect.top() + 2)

        icon_size = _ICON_SIZE_SUB if small else _ICON_SIZE
        pix = self._icon_pixmap(icon, icon_col, icon_size)
        cx  = rect.center().x() - icon_size.width() // 2
        cy  = rect.center().y() - icon_size.height() // 2
        painter.drawPixmap(cx, cy, pix)

    def _draw_regular_button(
        self,
        painter: QPainter,
        bid: str,
        rect: QRect,
        hovered: bool,
        active: bool = False,
    ) -> None:
        if active:
            bg       = _C_BTN_ACTIVE
            icon_col = _C_ICON_ACT
        elif hovered:
            bg       = _C_HOV_BG
            icon_col = _C_ICON_HOV
        else:
            bg       = _C_BTN
            icon_col = _C_ICON
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(_C_BORDER, 1))
        painter.drawRoundedRect(QRectF(rect), 7, 7)
        icon_name = next(b[1] for b in BUTTONS if b[0] == bid)
        pix = self._icon_pixmap(icon_name, icon_col)
        painter.drawPixmap(
            rect.center().x() - _ICON_SIZE.width() // 2,
            rect.center().y() - _ICON_SIZE.height() // 2,
            pix,
        )

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.pos()
        bid = self._bid_at(pos)

        if bid == "__toggle__":
            self._toggle_collapse()
            return

        if bid == "__pointer__":
            self._activate_pointer()
            return

        if bid is not None and bid.startswith("sub_"):
            self._handle_sub_click(bid)
            return

        if bid is not None:
            self._pressed_bid = bid
            self._press_y     = pos.y()
            self._long_press_timer.start()

        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.pos()

        if self._drag_bid is not None:
            self._drag_y = pos.y()
            self._calc_drag_insert()
            self.update()
            return

        new_hov = self._bid_at(pos)
        if new_hov != self._hovered:
            self._hovered = new_hov
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._long_press_timer.isActive():
            self._long_press_timer.stop()
            bid = self._pressed_bid
            self._pressed_bid = None
            if bid:
                self._emit_btn(bid)
            return

        if self._drag_bid is not None:
            self._commit_reorder()
            self._wiggle_timer.stop()
            self._wiggle_phase = 0.0
            self._drag_bid = None
            self.unsetCursor()
            self.update()

    def leaveEvent(self, event) -> None:
        self._hovered = None
        self.update()

    # ------------------------------------------------------------------
    # Sub-drawer interaction
    # ------------------------------------------------------------------

    def _activate_pointer(self) -> None:
        if self._active_tool == "pointer":
            return
        self._active_tool = "pointer"
        target = self._calc_expanded_h()
        self._expand_anim.stop()
        self._expand_anim.setStartValue(self._current_h)
        self._expand_anim.setEndValue(target)
        self._expand_anim.start()
        self.tool_changed.emit("pointer")
        self.update()

    def _handle_sub_click(self, sid: str) -> None:
        if sid == "sub_grid":
            self._measure_mode = "grid"
            self._settings.set_measurement("mode", "grid")
            self._settings.save()
            self.measure_mode_changed.emit("grid")
        elif sid == "sub_free":
            self._measure_mode = "free"
            self._settings.set_measurement("mode", "free")
            self._settings.save()
            self.measure_mode_changed.emit("free")
        elif sid == "sub_line":
            self._measure_type = "line"
            self._settings.set_measurement("measure_type", "line")
            self._settings.save()
            self.measure_type_changed.emit("line")
        elif sid == "sub_area":
            self._measure_type = "area"
            self._settings.set_measurement("measure_type", "area")
            self._settings.save()
            self.measure_type_changed.emit("area")
        elif sid == "sub_cone":
            self._measure_type = "cone"
            self._settings.set_measurement("measure_type", "cone")
            self._settings.save()
            self.measure_type_changed.emit("cone")
        elif sid in ("sub_draw_freehand", "sub_draw_circle", "sub_draw_square", "sub_draw_eraser"):
            sub = sid[len("sub_draw_"):]
            self._draw_sub_tool = sub
            self._settings.set_drawing("sub_tool", sub)
            self._settings.save()
            self.draw_tool_changed.emit(sub)
        elif sid == "sub_draw_trash":
            self.draw_trash_requested.emit()
        self.update()

    # ------------------------------------------------------------------
    # Long press → drag mode
    # ------------------------------------------------------------------

    def _on_long_press(self) -> None:
        if self._pressed_bid is None:
            return
        self._drag_bid = self._pressed_bid
        self._pressed_bid = None
        self._drag_y = self._press_y
        self._calc_drag_insert()
        self._wiggle_timer.start()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.update()

    def _wiggle_step(self) -> None:
        self._wiggle_phase += _WIGGLE_SPEED
        self.update()

    # ------------------------------------------------------------------
    # Drag reorder
    # ------------------------------------------------------------------

    def _calc_drag_insert(self) -> None:
        others = [bid for bid in self._visible_order() if bid != self._drag_bid]
        for i in range(len(others)):
            mid_y = (
                self._regular_btn_rect(i).top()
                + _TB_BTN_SIZE // 2
            )
            if self._drag_y < mid_y:
                self._drag_insert = i
                return
        self._drag_insert = len(others)

    def _commit_reorder(self) -> None:
        if self._drag_bid is None:
            return
        bid = self._drag_bid
        new_order = [b for b in self._order if b != bid]
        vis_others = [b for b in new_order if self._vis.get(b, True)]
        ins = min(self._drag_insert, len(vis_others))

        if ins >= len(vis_others):
            if vis_others:
                last_idx = max(new_order.index(b) for b in vis_others)
                new_order.insert(last_idx + 1, bid)
            else:
                new_order.append(bid)
        else:
            ref_idx = new_order.index(vis_others[ins])
            new_order.insert(ref_idx, bid)

        self._order = new_order
        self._settings.set_toolbar("button_order", self._order)
        self._settings.save()
        self.update()

    # ------------------------------------------------------------------
    # Emit signal for a button id
    # ------------------------------------------------------------------

    def _emit_btn(self, bid: str) -> None:
        if bid in ("measure", "draw"):
            if self._active_tool == bid:
                self._activate_pointer()
            else:
                self._active_tool = bid
                target = self._calc_expanded_h()
                self._expand_anim.stop()
                self._expand_anim.setStartValue(self._current_h)
                self._expand_anim.setEndValue(target)
                self._expand_anim.start()
                self.tool_changed.emit(bid)
                self.update()
        else:
            sig_name = self._SIGNAL_MAP.get(bid)
            if sig_name:
                getattr(self, sig_name).emit()

    # ------------------------------------------------------------------
    # Tooltip
    # ------------------------------------------------------------------

    def event(self, ev) -> bool:
        if ev.type() == QEvent.Type.ToolTip:
            bid = self._bid_at(ev.pos())
            if bid == "__toggle__":
                label = "Collapse" if not self._collapsed else "Expand"
                QToolTip.showText(ev.globalPos(), label, self)
            elif bid == "__pointer__":
                QToolTip.showText(ev.globalPos(), _POINTER_BTN[2], self)
            elif bid is not None and bid.startswith("sub_draw_"):
                label = next((b[2] for b in _DRAW_SUB_BUTTONS if b[0] == bid), "")
                QToolTip.showText(ev.globalPos(), label, self)
            elif bid is not None and bid.startswith("sub_"):
                label = next((b[2] for b in _SUB_BUTTONS if b[0] == bid), "")
                QToolTip.showText(ev.globalPos(), label, self)
            elif bid is not None:
                label = next((b[2] for b in BUTTONS if b[0] == bid), "")
                QToolTip.showText(ev.globalPos(), label, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)
