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

"""StickyNoteItem – an editable sticky note placed on the canvas."""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPen, QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect, QGraphicsItem, QGraphicsObject,
    QGraphicsProxyWidget, QMenu, QTextEdit,
)

_PROXY_INSET = 2   # px gap between outer border and the embedded editor


class _NoteProxy(QGraphicsProxyWidget):
    """Proxy that forwards context-menu events to the parent StickyNoteItem.

    Qt's scene only sends contextMenuEvent to the single topmost item; it does
    not propagate on ignore().  We must manually forward to the parent.
    """

    def contextMenuEvent(self, event) -> None:
        parent = self.parentItem()
        if parent is not None:
            parent.contextMenuEvent(event)
        else:
            event.ignore()


# Default colours (matching app palette)
_DEFAULT_NOTE_COLOR  = "#1f1f2c"
_DEFAULT_FONT_FAMILY = "Arial"
_DEFAULT_FONT_SIZE   = 12
_DEFAULT_FONT_COLOR  = "#ffffff"
_DEFAULT_TEXT        = "Write Here"

# Z range shared with ImageItems / cards
_NORMAL_MIN_Z = 0.0


class _NoteTextEdit(QTextEdit):
    """QTextEdit that ignores Tab and signals when focus is lost."""

    editing_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Tab:
            event.ignore()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.editing_finished.emit()


class StickyNoteItem(QGraphicsObject):
    """An editable sticky note placed on the canvas."""

    delete_requested          = pyqtSignal(object)  # self
    delete_selected_requested = pyqtSignal()        # delete all selected items
    resize_requested   = pyqtSignal(object)   # self
    settings_requested = pyqtSignal()         # open Sticky Notes settings tab
    copy_requested     = pyqtSignal()
    paste_requested    = pyqtSignal()

    def __init__(
        self,
        w_cells: float = 3.0,
        h_cells: float = 3.0,
        grid_size: int = 40,
        note_color: str = _DEFAULT_NOTE_COLOR,
        font_family: str = _DEFAULT_FONT_FAMILY,
        font_size: int = _DEFAULT_FONT_SIZE,
        font_color: str = _DEFAULT_FONT_COLOR,
        text_html: str = "",
        parent=None,
    ):
        super().__init__(parent)

        self.grid_size: int   = grid_size
        self.grid_snap: bool  = True
        self.locked: bool     = False
        self._base_z: float   = _NORMAL_MIN_Z

        self._w_cells: float = max(0.5, w_cells)
        self._h_cells: float = max(0.5, h_cells)

        self._note_color: str  = note_color
        self._font_family: str = font_family
        self._font_size: int   = font_size
        self._font_color: str  = font_color

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges,
        )
        self.setAcceptHoverEvents(True)

        # ── Embedded QTextEdit via proxy ───────────────────────────────
        self._editor = _NoteTextEdit()
        self._editor.setReadOnly(False)
        self._apply_editor_style()
        if text_html:
            self._editor.setHtml(text_html)
        else:
            self._editor.setPlainText(_DEFAULT_TEXT)

        self._proxy = _NoteProxy(self)
        self._proxy.setWidget(self._editor)
        self._proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self._proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self._proxy.setPos(0, 0)
        self._sync_proxy_geometry()

        # Connect focus-out → exit editing
        self._editor.editing_finished.connect(lambda: self._set_editing(False))

        # Editing starts disabled; double-click enables
        self._set_editing(False)

        self._update_transform_origin()

        # Drop shadow
        self._shadow = QGraphicsDropShadowEffect()
        self._shadow.setBlurRadius(14)
        self._shadow.setOffset(4, 6)
        self._shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(self._shadow)

        self.setZValue(self._base_z)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _px_w(self) -> float:
        return self._w_cells * self.grid_size

    def _px_h(self) -> float:
        return self._h_cells * self.grid_size

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._px_w(), self._px_h())

    def _update_transform_origin(self) -> None:
        self.setTransformOriginPoint(self._px_w() / 2, self._px_h() / 2)

    def _sync_proxy_geometry(self) -> None:
        """Resize the embedded QTextEdit to fill the note area (inset by _PROXY_INSET)."""
        i = _PROXY_INSET
        self._proxy.setGeometry(QRectF(i, i, self._px_w() - 2 * i, self._px_h() - 2 * i))

    # ------------------------------------------------------------------
    # Styling helpers
    # ------------------------------------------------------------------

    def _apply_editor_style(self) -> None:
        """Apply background/font/color to the QTextEdit."""
        self._editor.setStyleSheet(
            f"QTextEdit {{"
            f"  background-color: {self._note_color};"
            f"  color: {self._font_color};"
            f"  border: none;"
            f"  padding: 4px;"
            f"}}"
            f"QScrollBar:vertical {{"
            f"  width: 8px;"
            f"  background: rgba(0,0,0,20);"
            f"}}"
        )
        font = QFont(self._font_family, self._font_size)
        self._editor.setFont(font)
        # Apply font family, size, AND color to ALL existing text.
        # Use individual property setters — setFont() alone does not mark
        # each property as "resolved", so mergeCharFormat ignores them.
        cursor = self._editor.textCursor()
        cursor.select(cursor.SelectionType.Document)
        fmt = QTextCharFormat()
        fmt.setFontFamilies([self._font_family])
        fmt.setFontPointSize(float(self._font_size))
        fmt.setForeground(QBrush(QColor(self._font_color)))
        cursor.mergeCharFormat(fmt)
        cursor.clearSelection()
        self._editor.setTextCursor(cursor)
        self._editor.setTextColor(QColor(self._font_color))

    def _set_editing(self, enabled: bool) -> None:
        """Enable or disable text editing."""
        self._proxy.setEnabled(enabled)
        if enabled:
            self._proxy.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)
            self._editor.setFocus()
        else:
            # NoButton makes the proxy transparent to mouse events so clicks
            # reach the parent StickyNoteItem for selection / context menu.
            self._proxy.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    # ------------------------------------------------------------------
    # Snap
    # ------------------------------------------------------------------

    def itemChange(self, change, value):
        if (change == QGraphicsItem.GraphicsItemChange.ItemPositionChange
                and self.grid_snap and self.scene()):
            g = self.grid_size
            mode = getattr(self.scene(), 'snap_mode', 'centered')
            hw = self._px_w() / 2
            hh = self._px_h() / 2
            cx = value.x() + hw
            cy = value.y() + hh
            if mode == 'centered':
                snapped_cx = math.floor(cx / g) * g + g / 2
                snapped_cy = math.floor(cy / g) * g + g / 2
            else:
                snapped_cx = round(cx / g) * g
                snapped_cy = round(cy / g) * g
            return QPointF(snapped_cx - hw, snapped_cy - hh)
        return super().itemChange(change, value)

    # ------------------------------------------------------------------
    # Z-Order
    # ------------------------------------------------------------------

    def _raise_to_top(self) -> None:
        scene = self.scene()
        if not scene:
            return
        from .card_item import CardItem
        from .deck_item import DeckItem
        from .die_item import DieItem
        from .image_item import ImageItem
        all_normal = [it for it in scene.items()
                      if isinstance(it, (CardItem, DeckItem, ImageItem, DieItem, StickyNoteItem))
                      and not getattr(it, 'is_anchor', False)
                      and it is not self]
        max_z = max((it.zValue() for it in all_normal), default=_NORMAL_MIN_Z)
        self._base_z = max_z + 1
        self.setZValue(self._base_z)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paint(self, painter: QPainter, option, widget) -> None:
        rect = self.boundingRect()

        # Fill full background — proxy is inset by _PROXY_INSET so the
        # outer strip is always visible and not painted over by the child.
        painter.fillRect(rect, QColor(self._note_color))

        # Selection highlight — drawn in the outer strip, never covered by proxy
        from PyQt6.QtWidgets import QStyle
        if bool(option.state & QStyle.StateFlag.State_Selected):
            painter.setPen(QPen(QColor(255, 215, 0), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))


    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.locked:
                event.ignore()
                return
            self._raise_to_top()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.locked:
            self._set_editing(True)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event) -> None:
        # Option A: right-clicking an unselected item clears the selection
        if not self.isSelected():
            self.scene().clearSelection()
            self.setSelected(True)

        views = self.scene().views() if self.scene() else []
        parent = views[0] if views else None
        menu = QMenu(parent)

        sel_notes = [i for i in self.scene().selectedItems()
                     if isinstance(i, StickyNoteItem)]
        multi = len(sel_notes) > 1

        # Rotate
        cw_label  = f"Rotate CW ({len(sel_notes)})"  if multi else "Rotate CW"
        ccw_label = f"Rotate CCW ({len(sel_notes)})" if multi else "Rotate CCW"
        menu.addAction(cw_label,  lambda: [i.rotate_cw()  for i in sel_notes if not i.locked])
        menu.addAction(ccw_label, lambda: [i.rotate_ccw() for i in sel_notes if not i.locked])
        menu.addSeparator()

        # Color pickers apply to all selected notes
        menu.addAction("Note Color…", self._pick_note_color)
        menu.addAction("Font Color…", self._pick_font_color)
        if not multi:
            menu.addAction("Sticky Note Settings…", lambda: self.settings_requested.emit())
        menu.addSeparator()

        snap_label = "✓ Snap to Grid" if self.grid_snap else "Snap to Grid"
        menu.addAction(snap_label, self._toggle_snap)
        if not multi:
            menu.addAction("Resize…", lambda: self.resize_requested.emit(self))
        menu.addSeparator()

        menu.addAction("Copy",  self.copy_requested.emit)
        menu.addAction("Paste", self.paste_requested.emit)
        menu.addSeparator()

        # Lock — majority state when multi
        majority_locked = sum(1 for i in sel_notes if i.locked) > len(sel_notes) / 2
        lock_label = "✓ Lock" if majority_locked else "Lock"
        def _toggle_lock_all():
            target = not majority_locked
            for i in sel_notes:
                if i.locked != target:
                    i._toggle_lock()
        menu.addAction(lock_label, _toggle_lock_all if multi else self._toggle_lock)
        menu.addSeparator()

        del_label = f"Delete ({len(sel_notes)})" if multi else "Delete"
        menu.addAction(del_label, self.delete_selected_requested.emit)

        from PyQt6.QtGui import QCursor
        menu.exec(QCursor.pos())

    # ------------------------------------------------------------------
    # Context menu actions
    # ------------------------------------------------------------------

    def rotate_cw(self, step: int = 45) -> None:
        cur = round(self.rotation() / step) * step
        self.setRotation((cur + step) % 360)

    def rotate_ccw(self, step: int = 45) -> None:
        cur = round(self.rotation() / step) * step
        self.setRotation((cur - step) % 360)

    def _toggle_snap(self) -> None:
        self.grid_snap = not self.grid_snap

    def _toggle_lock(self) -> None:
        self.locked = not self.locked
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not self.locked)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not self.locked)
        if self.locked:
            self.setSelected(False)
            self._set_editing(False)

    def _pick_note_color(self) -> None:
        from PyQt6.QtWidgets import QColorDialog
        parent = self.scene().views()[0] if self.scene() and self.scene().views() else None
        color = QColorDialog.getColor(QColor(self._note_color), parent, "Note Color")
        if color.isValid():
            targets = [i for i in self.scene().selectedItems()
                       if isinstance(i, StickyNoteItem)] or [self]
            for note in targets:
                note._note_color = color.name()
                note._apply_editor_style()
                note.update()

    def _pick_font_color(self) -> None:
        from PyQt6.QtWidgets import QColorDialog
        parent = self.scene().views()[0] if self.scene() and self.scene().views() else None
        color = QColorDialog.getColor(QColor(self._font_color), parent, "Font Color")
        if color.isValid():
            targets = [i for i in self.scene().selectedItems()
                       if isinstance(i, StickyNoteItem)] or [self]
            for note in targets:
                note._font_color = color.name()
                note._apply_editor_style()
                note.update()

    # ------------------------------------------------------------------
    # Public mutators
    # ------------------------------------------------------------------

    def resize(self, w_cells: float, h_cells: float) -> None:
        self.prepareGeometryChange()
        self._w_cells = max(0.5, w_cells)
        self._h_cells = max(0.5, h_cells)
        self._update_transform_origin()
        self._sync_proxy_geometry()
        self.update()

    def update_grid_size(self, new_size: int) -> None:
        self.prepareGeometryChange()
        self.grid_size = new_size
        self._update_transform_origin()
        self._sync_proxy_geometry()
        self.update()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_state_dict(self) -> dict:
        return {
            "x":           self.pos().x(),
            "y":           self.pos().y(),
            "w_cells":     self._w_cells,
            "h_cells":     self._h_cells,
            "rotation":    self.rotation(),
            "z":           self.zValue(),
            "grid_snap":   self.grid_snap,
            "locked":      self.locked,
            "note_color":  self._note_color,
            "font_family": self._font_family,
            "font_size":   self._font_size,
            "font_color":  self._font_color,
            "text_html":   self._editor.toHtml(),
        }

    @classmethod
    def from_state_dict(cls, d: dict, grid_size: int) -> "StickyNoteItem":
        item = cls(
            w_cells     = d.get("w_cells",     3.0),
            h_cells     = d.get("h_cells",     3.0),
            grid_size   = grid_size,
            note_color  = d.get("note_color",  _DEFAULT_NOTE_COLOR),
            font_family = d.get("font_family", _DEFAULT_FONT_FAMILY),
            font_size   = d.get("font_size",   _DEFAULT_FONT_SIZE),
            font_color  = d.get("font_color",  _DEFAULT_FONT_COLOR),
            text_html   = d.get("text_html",   ""),
        )
        item.setPos(d.get("x", 0), d.get("y", 0))
        item.setRotation(d.get("rotation", 0))
        item._base_z = d.get("z", _NORMAL_MIN_Z)
        item.setZValue(item._base_z)
        item.grid_snap = d.get("grid_snap", True)
        locked = d.get("locked", False)
        if locked:
            item.locked = True
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        return item
