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

"""HandWidget – floating card-hand panel centred at the bottom of the canvas."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QPointF, QPropertyAnimation,
    QRect, QRectF, QSize, Qt, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDrag, QFont, QMouseEvent, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QMenu, QWidget


HAND_PADDING_V      = 8
HAND_PADDING_H      = 12
MAX_OVERLAP         = 0.40    # cards may overlap up to 40% before compressing
_HAND_MARGIN_BOTTOM = 12      # px gap between widget bottom and parent bottom
_HAND_RADIUS        = 10      # corner radius
_C_BG               = QColor("#292A35")
_C_BORDER           = QColor("#4B4D63")


@dataclass
class HandCardState:
    card_data: object
    face_up:   bool  = True
    rotation:  float = 0.0
    _front_pix: Optional[QPixmap] = field(default=None, repr=False)
    _back_pix:  Optional[QPixmap] = field(default=None, repr=False)

    def front_pixmap(self) -> Optional[QPixmap]:
        if self._front_pix is None and self.card_data.image_path:
            if Path(self.card_data.image_path).exists():
                self._front_pix = QPixmap(self.card_data.image_path)
        return self._front_pix

    def back_pixmap(self) -> Optional[QPixmap]:
        if self._back_pix is None and self.card_data.back_path:
            if Path(self.card_data.back_path).exists():
                self._back_pix = QPixmap(self.card_data.back_path)
        return self._back_pix

    def current_pixmap(self) -> Optional[QPixmap]:
        return self.front_pixmap() if self.face_up else self.back_pixmap()


class HandWidget(QWidget):
    """
    Floating card-hand panel centred at the bottom of the canvas.

    Width starts at 33 % of parent and expands dynamically (up to 75 %) to
    accommodate cards; beyond 75 % cards overlap more via the existing
    scale-down logic.

    Toggle visibility with toggle_visible().  The panel animates horizontally
    toward/from its centre on show/hide.
    """

    # Signals (unchanged public interface)
    send_to_canvas            = pyqtSignal(object, object)
    return_to_deck            = pyqtSignal(object)
    request_canvas_pos        = pyqtSignal()
    stack_to_canvas_requested = pyqtSignal(list)
    request_undo_snapshot     = pyqtSignal()
    hand_card_hovered         = pyqtSignal(object)
    hand_card_unhovered       = pyqtSignal()

    # New signals
    visibility_changed      = pyqtSignal(bool)  # True = shown, False = hidden
    hand_card_count_changed = pyqtSignal(int)   # emitted after every card-list change

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings  = settings
        self.hand_cards: List[HandCardState] = []
        self._selected:  Set[int]            = set()

        self._max_cw: int = settings.display("max_hand_card_width")
        self._max_ch: int = int(self._max_cw * 168 / 120)
        self._visible: bool = True
        self._animating_toggle: bool = False
        self._current_w: int = 0      # set properly below

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        # Drop shadow (disabled during animation to prevent artefacts)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(18)
        self._shadow.setOffset(0, 4)
        self._shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(self._shadow)

        # Horizontal width animation (shrink/expand toward centre)
        self._anim = QPropertyAnimation(self, b"hand_w")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)

        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._drop_highlight: bool = False

        # Mouse interaction state
        self._drag_start_idx: Optional[int]    = None
        self._drag_start_pos: Optional[QPointF] = None
        self._hovered_idx:     Optional[int]   = None
        self._last_clicked_idx: Optional[int]  = None
        self._pending_deselect: bool            = False

        # Reorder drag state
        self._reorder_mode:       bool          = False
        self._reorder_drag_idx:   Optional[int] = None
        self._reorder_insert_pos: Optional[int] = None

        # Rubber-band selection state
        self._rubber_active: bool           = False
        self._rubber_origin: Optional[QPointF] = None
        self._rubber_rect:   Optional[QRect]   = None

        # Initial size and position
        self._current_w = self._target_width()
        self.setFixedWidth(max(1, self._current_w))
        self.setFixedHeight(self._hand_height())
        if parent is not None:
            self.reposition(parent.width(), parent.height())

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _hand_height(self) -> int:
        return 2 * HAND_PADDING_V + self._max_ch

    def _target_width(self) -> int:
        """Ideal widget width: 33–75 % of parent, expanding to fit cards."""
        p = self.parent()
        pw = p.width() if p else 800
        min_w = max(100, int(pw * 0.33))
        max_w = int(pw * 0.75)

        n = len(self.hand_cards)
        if n == 0:
            return min_w

        ch = self._max_ch
        nat_widths = []
        for hs in self.hand_cards:
            pix = hs.current_pixmap()
            if pix and not pix.isNull() and pix.height() > 0:
                w = int(ch * pix.width() / pix.height())
            else:
                w = self._max_cw
            nat_widths.append(w)

        if n > 1:
            total_nat = int(
                sum(w * (1 - MAX_OVERLAP) for w in nat_widths[:-1])
                + nat_widths[-1]
                + 2 * HAND_PADDING_H
            )
        else:
            total_nat = nat_widths[0] + 2 * HAND_PADDING_H

        return max(min_w, min(total_nat, max_w))

    def reposition(self, parent_w: int, parent_h: int) -> None:
        """Called by MainWindow on resize to keep the panel centred at bottom."""
        h = self._hand_height()
        if self.height() != h:
            self.setFixedHeight(h)

        if self._visible and not self._animating_toggle:
            target_w = self._target_width()
            if target_w != self._current_w:
                self._current_w = target_w
                self.setFixedWidth(max(1, target_w))

        y = parent_h - self._hand_height() - _HAND_MARGIN_BOTTOM
        cx = parent_w // 2
        self.move(cx - self._current_w // 2, y)

    def _snap_to_target_width(self) -> None:
        """Instantly resize width to match current card count (no animation)."""
        if not self._visible or self._animating_toggle:
            return
        target = self._target_width()
        if target == self._current_w:
            return
        self._current_w = target
        self.setFixedWidth(max(1, target))
        p = self.parent()
        if p:
            cx = p.width() // 2
            y = p.height() - self._hand_height() - _HAND_MARGIN_BOTTOM
            self.move(cx - target // 2, y)

    # ------------------------------------------------------------------
    # Animated hand_w pyqtProperty
    # ------------------------------------------------------------------

    def _get_hand_w(self) -> int:
        return self._current_w

    def _set_hand_w(self, v: int) -> None:
        self._current_w = v
        self.setFixedWidth(max(1, v))
        p = self.parent()
        if p:
            cx = p.width() // 2
            y = p.height() - self._hand_height() - _HAND_MARGIN_BOTTOM
            self.move(cx - v // 2, y)
            p.update()  # clear stale shadow pixels left in parent by previous frame
        self.update()

    hand_w = pyqtProperty(int, _get_hand_w, _set_hand_w)

    def _on_anim_finished(self) -> None:
        self._animating_toggle = False
        self._shadow.setEnabled(True)
        if not self._visible:
            self.hide()

    # ------------------------------------------------------------------
    # Toggle visibility
    # ------------------------------------------------------------------

    def toggle_visible(self) -> None:
        self._visible = not self._visible
        self._animating_toggle = True
        self._shadow.setEnabled(False)
        if self._visible:
            target_w = self._target_width()
            self._current_w = 0
            self.setFixedWidth(1)
            p = self.parent()
            if p:
                cx = p.width() // 2
                y = p.height() - self._hand_height() - _HAND_MARGIN_BOTTOM
                self.move(cx, y)
            self.show()
            self._anim.stop()
            self._anim.setStartValue(0)
            self._anim.setEndValue(target_w)
            self._anim.start()
            self.visibility_changed.emit(True)
        else:
            self._anim.stop()
            self._anim.setStartValue(self._current_w)
            self._anim.setEndValue(0)
            self._anim.start()
            self.visibility_changed.emit(False)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        return QSize(self._current_w, self._hand_height())

    def set_drop_highlight(self, active: bool) -> None:
        if not self._visible:
            return
        if active != self._drop_highlight:
            self._drop_highlight = active
            self.update()

    def add_card(self, card_data, face_up: bool = True, rotation: float = 0.0) -> None:
        self.hand_cards.append(HandCardState(card_data, face_up, rotation))
        self._after_cards_changed()
        self.update()

    def remove_card_by_id(self, card_id: str) -> Optional[HandCardState]:
        for i, hs in enumerate(self.hand_cards):
            if hs.card_data.id == card_id:
                self._selected.discard(i)
                self._selected = {j if j < i else j - 1 for j in self._selected if j != i}
                result = self.hand_cards.pop(i)
                self._after_cards_changed()
                return result
        return None

    def remove_card_by_image_path(self, path: str) -> Optional[HandCardState]:
        for i, hs in enumerate(self.hand_cards):
            if hs.card_data.image_path == path:
                self._selected.discard(i)
                self._selected = {j if j < i else j - 1 for j in self._selected if j != i}
                result = self.hand_cards.pop(i)
                self._after_cards_changed()
                return result
        return None

    def clear(self) -> List[HandCardState]:
        removed = list(self.hand_cards)
        self.hand_cards.clear()
        self._selected.clear()
        self._after_cards_changed()
        self.update()
        return removed

    def set_max_card_width(self, w: int) -> None:
        self._max_cw = max(40, w)
        self._max_ch = int(self._max_cw * 168 / 120)
        self.setFixedHeight(self._hand_height())
        self._snap_to_target_width()
        self.update()

    def _after_cards_changed(self) -> None:
        self._snap_to_target_width()
        self.hand_card_count_changed.emit(len(self.hand_cards))

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _card_rects(self) -> List[QRect]:
        n = len(self.hand_cards)
        if n == 0:
            return []

        ch = self._max_ch
        cy = (self.height() - ch) // 2        # vertically centred in the widget
        avail = self.width() - 2 * HAND_PADDING_H

        nat_widths = []
        for hs in self.hand_cards:
            pix = hs.current_pixmap()
            if pix and not pix.isNull() and pix.height() > 0:
                w = int(ch * pix.width() / pix.height())
            else:
                w = self._max_cw
            nat_widths.append(w)

        if n > 1:
            total_nat = sum(w * (1 - MAX_OVERLAP) for w in nat_widths[:-1]) + nat_widths[-1]
        else:
            total_nat = nat_widths[0]

        scale  = min(1.0, avail / total_nat) if total_nat > 0 else 1.0
        widths = [max(1, int(w * scale)) for w in nat_widths]

        if n > 1:
            total_w = sum(w * (1 - MAX_OVERLAP) for w in widths[:-1]) + widths[-1]
        else:
            total_w = widths[0]
        x = HAND_PADDING_H + max(0, int((avail - total_w) / 2))

        rects = []
        for i, w in enumerate(widths):
            rects.append(QRect(x, cy, w, ch))
            if i < n - 1:
                x += int(w * (1 - MAX_OVERLAP))
        return rects

    def _index_at(self, pos: QPointF) -> Optional[int]:
        rects = self._card_rects()
        for i in range(len(rects) - 1, -1, -1):
            if rects[i].contains(pos.toPoint()):
                return i
        return None

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Rounded floating panel background
        bg_rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(bg_rect, _HAND_RADIUS, _HAND_RADIUS)
        painter.fillPath(path, _C_BG)
        painter.setPen(QPen(_C_BORDER, 1))
        painter.drawPath(path)

        # "Hand" watermark — rendered behind cards
        painter.setPen(QColor(0, 0, 0, 128))
        painter.setFont(QFont("Arial", int(self.height() * 0.35), QFont.Weight.Bold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Hand")

        if self._drop_highlight:
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(self.rect(), QColor(80, 180, 255, 35))
            for thickness, alpha in ((8, 30), (5, 60), (3, 110), (2, 180), (1, 255)):
                painter.setPen(QPen(QColor(100, 200, 255, alpha), thickness))
                painter.drawPath(path)
            painter.setPen(QColor(180, 230, 255, 220))
            painter.setFont(QFont("Arial", 13, QFont.Weight.Bold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "↓  Drop to Hand")
            painter.restore()
        else:
            rects = self._card_rects()
            n = len(rects)

            ghost_rect = None
            ghost_ins  = None
            if (self._reorder_mode and self._reorder_insert_pos is not None
                    and self._reorder_drag_idx is not None
                    and 0 <= self._reorder_drag_idx < n):
                drag_rect = rects[self._reorder_drag_idx]
                gw, gh = drag_rect.width(), drag_rect.height()
                ins = self._reorder_insert_pos
                if ins == 0:
                    gcx = rects[0].left() - gw // 2
                elif ins >= n:
                    gcx = rects[-1].right() + gw // 2
                else:
                    gcx = (rects[ins - 1].right() + rects[ins].left()) // 2
                ghost_rect = QRect(gcx - gw // 2, drag_rect.top(), gw, gh)
                ghost_ins  = ins

            for i, (hs, rect) in enumerate(zip(self.hand_cards, rects)):
                if ghost_rect is not None and i == ghost_ins:
                    painter.save()
                    painter.setOpacity(0.55)
                    painter.setBrush(QBrush(QColor(70, 130, 255)))
                    painter.setPen(QPen(QColor(140, 190, 255), 2))
                    painter.drawRoundedRect(ghost_rect, 5, 5)
                    painter.restore()
                    ghost_rect = None
                self._draw_card(painter, hs, rect, i in self._selected, i == self._hovered_idx)

            if ghost_rect is not None:
                painter.save()
                painter.setOpacity(0.55)
                painter.setBrush(QBrush(QColor(70, 130, 255)))
                painter.setPen(QPen(QColor(140, 190, 255), 2))
                painter.drawRoundedRect(ghost_rect, 5, 5)
                painter.restore()

        if self._rubber_rect and not self._rubber_rect.isNull():
            painter.setPen(QPen(QColor(100, 180, 255, 220), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(100, 180, 255, 35)))
            painter.drawRect(self._rubber_rect)

        painter.end()

    def _draw_card(
        self, painter: QPainter, hs: HandCardState,
        rect: QRect, selected: bool, hovered: bool,
    ) -> None:
        cx = rect.center().x()
        cy = rect.center().y()

        painter.save()
        painter.translate(cx, cy)
        if hs.rotation:
            painter.rotate(hs.rotation)
        painter.translate(-rect.width() // 2, -rect.height() // 2)

        draw_rect = QRect(0, 0, rect.width(), rect.height())
        pix = hs.current_pixmap()
        if pix and not pix.isNull():
            painter.drawPixmap(draw_rect, pix)
        else:
            color = QColor(45, 85, 200) if hs.face_up else QColor(160, 35, 35)
            painter.fillRect(draw_rect, color)
            painter.setPen(QColor(255, 255, 255, 180))
            painter.setFont(QFont("Arial", 7))
            painter.drawText(draw_rect, Qt.AlignmentFlag.AlignCenter,
                             hs.card_data.name[:20])

        r = 5
        if selected:
            pen = QPen(QColor(255, 215, 0), 2)
        elif hovered:
            pen = QPen(QColor(150, 200, 255), 1)
        else:
            pen = QPen(QColor(0, 0, 0, 80), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(draw_rect, r, r)
        painter.restore()

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        idx = self._index_at(event.position())
        if event.button() == Qt.MouseButton.LeftButton:
            if idx is not None:
                mods = event.modifiers()
                if mods & Qt.KeyboardModifier.ShiftModifier and self._last_clicked_idx is not None:
                    lo = min(self._last_clicked_idx, idx)
                    hi = max(self._last_clicked_idx, idx)
                    self._selected.update(range(lo, hi + 1))
                elif mods & Qt.KeyboardModifier.ControlModifier:
                    if idx in self._selected:
                        self._selected.discard(idx)
                    else:
                        self._selected.add(idx)
                    self._last_clicked_idx = idx
                else:
                    if idx in self._selected and len(self._selected) > 1:
                        self._pending_deselect = True
                    else:
                        self._selected = {idx}
                        self._pending_deselect = False
                    self._last_clicked_idx = idx
                self._drag_start_idx = idx
                self._drag_start_pos = event.position()
            else:
                self._selected.clear()
                self._last_clicked_idx = None
                self._drag_start_idx = None
                self._rubber_active = True
                self._rubber_origin = event.position()
                self._rubber_rect = None
            self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            if idx is not None and idx not in self._selected:
                self._selected = {idx}
                self.update()
            self._show_context_menu(idx, event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        old_idx = self._hovered_idx
        self._hovered_idx = self._index_at(event.position())
        if self._hovered_idx != old_idx:
            if self._hovered_idx is not None and self._hovered_idx < len(self.hand_cards):
                self.hand_card_hovered.emit(self.hand_cards[self._hovered_idx].card_data)
            else:
                self.hand_card_unhovered.emit()
        self.update()

        # Rubber-band selection
        if self._rubber_active and self._rubber_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            o = self._rubber_origin.toPoint()
            p = event.pos()
            self._rubber_rect = QRect(o, p).normalized()
            rects = self._card_rects()
            self._selected.clear()
            for i, r in enumerate(rects):
                if r.intersects(self._rubber_rect):
                    self._selected.add(i)
            self.update()
            return

        # Reorder mode
        if self._reorder_mode and event.buttons() & Qt.MouseButton.LeftButton:
            if event.position().y() < 0:
                # Dragged above panel — switch to canvas drag
                self._reorder_mode = False
                self._reorder_insert_pos = None
                idx = self._reorder_drag_idx
                self._reorder_drag_idx = None
                self._drag_start_idx = None
                self._drag_start_pos = None
                if idx is not None:
                    self._start_drag(idx)
            else:
                self._update_reorder_insert_pos(event.position().x())
            return

        # Drag initiation
        if (self._drag_start_idx is not None
                and self._drag_start_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            dist = (event.position() - self._drag_start_pos).manhattanLength()
            if dist > 8:
                self._pending_deselect = False
                if event.position().y() >= 0:
                    # Still over panel — enter reorder mode
                    self._reorder_mode = True
                    self._reorder_drag_idx = self._drag_start_idx
                    self._drag_start_idx = None
                    self._drag_start_pos = None
                    self._update_reorder_insert_pos(event.position().x())
                else:
                    # Dragged above panel — canvas drag
                    self._start_drag(self._drag_start_idx)
                    self._drag_start_idx = None
                    self._drag_start_pos = None

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._reorder_mode:
                self._do_reorder()
                self._reorder_mode = False
                self._reorder_drag_idx = None
                self._reorder_insert_pos = None
            elif self._rubber_active:
                self._rubber_active = False
                self._rubber_rect = None
                self._rubber_origin = None
            elif self._pending_deselect and self._drag_start_idx is not None:
                self._selected = {self._drag_start_idx}
                self._last_clicked_idx = self._drag_start_idx
                self._pending_deselect = False
        self._drag_start_idx = None
        self._drag_start_pos = None
        self.update()

    def leaveEvent(self, event) -> None:
        had_hover = self._hovered_idx is not None
        self._hovered_idx = None
        if had_hover:
            self.hand_card_unhovered.emit()
        if self._rubber_active:
            self._rubber_active = False
            self._rubber_rect = None
            self._rubber_origin = None
        self.update()

    def clear_selection(self) -> None:
        if self._selected:
            self._selected.clear()
            self._last_clicked_idx = None
            self.update()

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        key_str = _hk(event)
        settings = self._settings
        if key_str == settings.hotkey("flip"):
            self._flip_selected()
        elif key_str == settings.hotkey("rotate_cw"):
            self._rotate_selected(settings.display("rotation_step"))
        elif key_str == settings.hotkey("rotate_ccw"):
            self._rotate_selected(-settings.display("rotation_step"))
        elif key_str == settings.hotkey("delete_selected"):
            self._remove_selected()
        elif key_str == "Ctrl+G" and len(self._selected) >= 2:
            self._stack_selected_emit()
        else:
            super().keyPressEvent(event)

    def _stack_selected_emit(self) -> None:
        indices = sorted(self._selected)
        cards = [
            (self.hand_cards[i].card_data, self.hand_cards[i].face_up)
            for i in indices if 0 <= i < len(self.hand_cards)
        ]
        if len(cards) < 2:
            return
        self.request_undo_snapshot.emit()
        for i in sorted(indices, reverse=True):
            if 0 <= i < len(self.hand_cards):
                self.hand_cards.pop(i)
        self._selected.clear()
        self._last_clicked_idx = None
        self._after_cards_changed()
        self.update()
        self.stack_to_canvas_requested.emit(cards)

    def _flip_selected(self) -> None:
        for i in self._selected:
            if 0 <= i < len(self.hand_cards):
                self.hand_cards[i].face_up = not self.hand_cards[i].face_up
        self.update()

    def _rotate_selected(self, degrees: float) -> None:
        for i in self._selected:
            if 0 <= i < len(self.hand_cards):
                self.hand_cards[i].rotation = (self.hand_cards[i].rotation + degrees) % 360
        self.update()

    def _remove_selected(self) -> None:
        indices = sorted(self._selected, reverse=True)
        for i in indices:
            if 0 <= i < len(self.hand_cards):
                hs = self.hand_cards.pop(i)
                self.return_to_deck.emit(hs.card_data)
        self._selected.clear()
        self._after_cards_changed()
        self.update()

    # ------------------------------------------------------------------
    # Reorder helpers
    # ------------------------------------------------------------------

    def _update_reorder_insert_pos(self, x: float) -> None:
        rects = self._card_rects()
        n = len(rects)
        insert = n
        for i, r in enumerate(rects):
            if x < r.center().x():
                insert = i
                break
        self._reorder_insert_pos = insert
        self.update()

    def _do_reorder(self) -> None:
        insert   = self._reorder_insert_pos
        drag_idx = self._reorder_drag_idx
        if insert is None or drag_idx is None or drag_idx >= len(self.hand_cards):
            return
        is_multi     = len(self._selected) > 1 and drag_idx in self._selected
        moving_indices = sorted(self._selected) if is_multi else [drag_idx]
        moving_cards = [self.hand_cards[i] for i in moving_indices if 0 <= i < len(self.hand_cards)]
        moving_set   = set(moving_indices)
        remaining    = [c for i, c in enumerate(self.hand_cards) if i not in moving_set]
        adj_insert   = max(0, min(insert - sum(1 for i in moving_indices if i < insert), len(remaining)))
        self.hand_cards = remaining[:adj_insert] + moving_cards + remaining[adj_insert:]
        self._selected = set(range(adj_insert, adj_insert + len(moving_cards)))
        self._last_clicked_idx = adj_insert
        self.update()

    # ------------------------------------------------------------------
    # Drag from hand to canvas
    # ------------------------------------------------------------------

    def _start_drag(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.hand_cards):
            return
        hs = self.hand_cards[idx]
        is_multi = len(self._selected) > 1 and idx in self._selected
        mime = QMimeData()

        if is_multi:
            selected_states = [
                self.hand_cards[i] for i in sorted(self._selected)
                if 0 <= i < len(self.hand_cards)
            ]
            cards_list = [
                {"image_path": h.card_data.image_path, "deck_id": h.card_data.deck_id,
                 "face_up": h.face_up, "rotation": h.rotation}
                for h in selected_states
            ]
            mime.setData("application/x-solocanvas-cards",
                         json.dumps(cards_list).encode("utf-8"))
        else:
            card_dict = {
                "image_path": hs.card_data.image_path,
                "deck_id":    hs.card_data.deck_id,
                "face_up":    hs.face_up,
                "rotation":   hs.rotation,
            }
            mime.setData("application/x-solocanvas-card",
                         json.dumps(card_dict).encode("utf-8"))

        pix  = hs.current_pixmap()
        drag = QDrag(self)
        drag.setMimeData(mime)
        if pix and not pix.isNull():
            thumb = pix.scaled(60, 84, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            drag.setPixmap(thumb)
            drag.setHotSpot(thumb.rect().center())

        result = drag.exec(Qt.DropAction.MoveAction)
        if result == Qt.DropAction.MoveAction:
            if is_multi:
                for i in sorted(self._selected, reverse=True):
                    if 0 <= i < len(self.hand_cards):
                        self.hand_cards.pop(i)
                self._selected.clear()
                self._last_clicked_idx = None
            else:
                self.remove_card_by_image_path(hs.card_data.image_path)
            self._after_cards_changed()
            self.update()

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, idx: Optional[int], global_pos) -> None:
        menu = QMenu()
        n_sel = len(self._selected)

        if idx is not None and 0 <= idx < len(self.hand_cards):
            menu.addAction("Flip",       lambda: self._flip_one(idx))
            menu.addAction("Rotate CW",  lambda: self._rotate_one(idx, 45))
            menu.addAction("Rotate CCW", lambda: self._rotate_one(idx, -45))
            menu.addSeparator()
            menu.addAction("Send to Canvas", lambda: self._send_to_canvas(idx))
            menu.addAction("Return to Deck", lambda: self._return_one_to_deck(idx))

            if n_sel > 1:
                menu.addSeparator()
                lbl = f"{n_sel} Selected Cards"
                menu.addAction(f"Flip {lbl}",           self._flip_selected)
                menu.addAction(f"Send {lbl} to Canvas", self._send_selected_to_canvas)
                menu.addAction(f"Return {lbl} to Deck", self._return_selected_to_deck)

        menu.exec(global_pos)

    def _flip_one(self, idx: int) -> None:
        self.hand_cards[idx].face_up = not self.hand_cards[idx].face_up
        self.update()

    def _rotate_one(self, idx: int, deg: float) -> None:
        self.hand_cards[idx].rotation = (self.hand_cards[idx].rotation + deg) % 360
        self.update()

    def _send_to_canvas(self, idx: int) -> None:
        hs = self.hand_cards.pop(idx)
        self._selected.discard(idx)
        self._selected = {j if j < idx else j - 1 for j in self._selected if j != idx}
        self.send_to_canvas.emit(hs.card_data, QPointF(0, 0))
        self._after_cards_changed()
        self.update()

    def _return_one_to_deck(self, idx: int) -> None:
        if 0 <= idx < len(self.hand_cards):
            hs = self.hand_cards.pop(idx)
            self._selected.discard(idx)
            self.return_to_deck.emit(hs.card_data)
            self._after_cards_changed()
            self.update()

    def _send_selected_to_canvas(self) -> None:
        for i in sorted(self._selected, reverse=True):
            if 0 <= i < len(self.hand_cards):
                hs = self.hand_cards.pop(i)
                self.send_to_canvas.emit(hs.card_data, QPointF(0, 0))
        self._selected.clear()
        self._last_clicked_idx = None
        self._after_cards_changed()
        self.update()

    def _return_selected_to_deck(self) -> None:
        for i in sorted(self._selected, reverse=True):
            if 0 <= i < len(self.hand_cards):
                hs = self.hand_cards.pop(i)
                self.return_to_deck.emit(hs.card_data)
        self._selected.clear()
        self._last_clicked_idx = None
        self._after_cards_changed()
        self.update()

    # ------------------------------------------------------------------
    # Drop from canvas to hand
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-solocanvas-card"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat("application/x-solocanvas-card"):
            event.ignore()
            return
        # MainWindow handles actual card movement via items_dropped_on_hand signal
        event.acceptProposedAction()

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update()


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _hk(event) -> str:
    from .canvas_view import _key_event_to_str
    return _key_event_to_str(event)
