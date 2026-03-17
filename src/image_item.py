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

"""ImageItem – a freeform image placed on the canvas."""
from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QCursor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect, QGraphicsItem, QGraphicsObject, QMenu,
)


_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.tif', '.webp'}

# Z-order constants
_ANCHOR_MAX_Z = -1.001   # anchors stay below GridLayer at Z=-1
_NORMAL_MIN_Z = 0.0      # non-anchor ImageItems start here (below cards at 1.0)


def _is_image_path(p: str) -> bool:
    return Path(p).suffix.lower() in _IMAGE_EXTS


def _is_image_url(url) -> bool:
    return url.isLocalFile() and _is_image_path(url.toLocalFile())


# ---------------------------------------------------------------------------
# Movement measurement overlay
# ---------------------------------------------------------------------------

class _MoveMeasureOverlay(QGraphicsItem):
    """Temporary scene-level overlay drawn while an ImageItem is being dragged
    with Measure Movement enabled.  Lives at scene origin (pos 0,0) so its
    local coordinate system == scene coordinate system."""

    _LINE_COLOR = QColor(100, 220, 255, 200)
    _DOT_COLOR  = QColor(255, 230, 80,  230)
    _LABEL_BG   = QColor(20,  20,  30,  210)
    _LABEL_FG   = QColor(255, 255, 255)
    _MARGIN     = 100   # bounding-rect padding to include label

    def __init__(self):
        super().__init__()
        self._waypoints: list[QPointF] = []
        self._current: QPointF = QPointF()
        self._grid_size: int  = 40
        self._cell_value: int = 5
        self._cell_unit: str  = "ft"
        self._decimals: bool  = False
        self.setZValue(10000)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable,    False)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)

    def set_data(
        self,
        waypoints:  list[QPointF],
        current:    QPointF,
        grid_size:  int,
        cell_value: int,
        cell_unit:  str,
        decimals:   bool = False,
    ) -> None:
        self._waypoints  = list(waypoints)
        self._current    = current
        self._grid_size  = grid_size
        self._cell_value = cell_value
        self._cell_unit  = cell_unit
        self._decimals   = decimals
        self.prepareGeometryChange()
        self.update()

    # -- geometry ------------------------------------------------------------

    def _all_points(self) -> list[QPointF]:
        return self._waypoints + [self._current]

    def boundingRect(self) -> QRectF:
        pts = self._all_points()
        if not pts:
            return QRectF()
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        m  = self._MARGIN
        return QRectF(
            min(xs) - m, min(ys) - m,
            max(xs) - min(xs) + 2 * m,
            max(ys) - min(ys) + 2 * m,
        )

    # -- helpers -------------------------------------------------------------

    def _total_dist_text(self) -> str:
        pts = self._all_points()
        if len(pts) < 2:
            return f"0 {self._cell_unit}"
        total_px = sum(
            math.hypot(pts[i + 1].x() - pts[i].x(), pts[i + 1].y() - pts[i].y())
            for i in range(len(pts) - 1)
        )
        dist = (total_px / self._grid_size) * self._cell_value
        fmt = ".1f" if self._decimals else ".0f"
        return f"{dist:{fmt}} {self._cell_unit}"

    # -- paint ---------------------------------------------------------------

    def paint(self, painter: QPainter, option, widget) -> None:
        pts = self._all_points()
        if len(pts) < 2:
            return

        # Path line
        pen = QPen(self._LINE_COLOR, 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(len(pts) - 1):
            painter.drawLine(pts[i], pts[i + 1])

        # Waypoint dots (skip the origin — it's under the item itself)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._DOT_COLOR))
        for pt in self._waypoints[1:]:
            painter.drawEllipse(pt, 4.5, 4.5)

        # Distance label near cursor
        label = self._total_dist_text()
        font  = QFont("Arial", 9, QFont.Weight.Bold)
        fm    = QFontMetrics(font)
        pad   = 4
        tr    = fm.boundingRect(label)
        lx    = self._current.x() + 14
        ly    = self._current.y() - 8
        bg    = QRectF(
            lx - pad,
            ly - tr.height() - pad,
            tr.width() + pad * 2 + 2,
            tr.height() + pad * 2,
        )
        painter.setBrush(QBrush(self._LABEL_BG))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bg, 3, 3)
        painter.setFont(font)
        painter.setPen(QPen(self._LABEL_FG))
        painter.drawText(QPointF(lx, ly), label)


class ImageItem(QGraphicsObject):
    """A freeform image placed on the canvas, sized in grid cells."""

    delete_requested          = pyqtSignal(object)  # self
    delete_selected_requested = pyqtSignal()        # delete all selected items
    duplicate_requested = pyqtSignal(object)   # self
    localize_requested  = pyqtSignal(object)   # self
    resize_requested    = pyqtSignal(object)   # self
    image_hovered       = pyqtSignal(str)      # image_path
    image_unhovered     = pyqtSignal()
    minimap_requested   = pyqtSignal(object)   # self

    def __init__(
        self,
        image_path: str,
        w_cells: float | None = None,
        h_cells: float = 1.2,
        grid_size: int = 40,
        parent=None,
    ):
        super().__init__(parent)

        self._image_path: str = image_path
        self.grid_size: int   = grid_size
        self.grid_snap: bool  = True
        self.hover_preview: bool = True
        self.locked: bool     = False
        self.is_anchor: bool  = False
        self._base_z: float   = _NORMAL_MIN_Z

        self._pixmap: QPixmap = QPixmap(image_path) if image_path else QPixmap()
        self._aspect_ratio: float = self._compute_aspect_ratio()

        # If width not specified, derive it from aspect ratio so height=h_cells
        if w_cells is None:
            w_cells = h_cells * self._aspect_ratio

        self._h_cells: float      = max(0.25, h_cells)
        self._w_cells: float      = max(0.25, w_cells)
        self._orig_w_cells: float = self._w_cells
        self._orig_h_cells: float = self._h_cells

        # Pre-scaled pixmap at display resolution — avoids per-frame scaling in paint()
        self._display_pixmap: QPixmap = QPixmap()
        self._build_display_pixmap()

        # Resize drag state
        self._resize_mode: bool       = False
        self._resizing: bool          = False
        self._resize_start_pos: QPointF = QPointF()
        self._resize_start_w: float   = self._w_cells
        self._resize_start_h: float   = self._h_cells

        # Mini map
        self.minimap: bool            = False
        self.minimap_geo: list | None = None   # [x, y, w, h] — updated before save

        # Move-measure state
        self.measure_movement: bool   = False
        self._cell_value: int         = 5
        self._cell_unit: str          = "ft"
        self._decimals: bool          = False
        self._mm_dragging: bool       = False
        self._mm_waypoints: list[QPointF] = []
        self._mm_current: QPointF     = QPointF()
        self._mm_overlay: _MoveMeasureOverlay | None = None

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges,
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(self._base_z)

        self._update_transform_origin()

        # Drop shadow (same as CardItem; disabled when anchor)
        self._shadow = QGraphicsDropShadowEffect()
        self._shadow.setBlurRadius(12)
        self._shadow.setOffset(4, 6)
        self._shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(self._shadow)

    def _build_display_pixmap(self) -> None:
        """Pre-scale source pixmap to display resolution so paint() never scales."""
        if self._pixmap.isNull():
            self._display_pixmap = self._pixmap
            return
        w = max(1, round(self._w_cells * self.grid_size))
        h = max(1, round(self._h_cells * self.grid_size))
        if self._pixmap.width() == w and self._pixmap.height() == h:
            self._display_pixmap = self._pixmap
        else:
            self._display_pixmap = self._pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

    def _compute_aspect_ratio(self) -> float:
        if not self._pixmap.isNull() and self._pixmap.height() > 0:
            return self._pixmap.width() / self._pixmap.height()
        return self._w_cells / self._h_cells if self._h_cells > 0 else 1.0

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._w_cells * self.grid_size, self._h_cells * self.grid_size)

    def _update_transform_origin(self) -> None:
        """Keep rotation pivot at the visual center of the image."""
        cx = self._w_cells * self.grid_size / 2
        cy = self._h_cells * self.grid_size / 2
        self.setTransformOriginPoint(cx, cy)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paint(self, painter: QPainter, option, widget) -> None:
        rect = self.boundingRect()

        if not self._display_pixmap.isNull():
            painter.drawPixmap(rect.toRect(), self._display_pixmap)
        else:
            painter.fillRect(rect, QColor(70, 70, 70, 200))
            painter.setPen(QColor(220, 100, 100))
            font_size = max(8, int(min(rect.width(), rect.height()) / 6))
            painter.setFont(QFont("Arial", font_size))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "⚠  Image not found")

        # Selection highlight
        from PyQt6.QtWidgets import QStyle
        if bool(option.state & QStyle.StateFlag.State_Selected):
            painter.setPen(QPen(QColor(255, 215, 0), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

        # Resize mode indicator
        if self._resize_mode:
            pen = QPen(QColor(100, 180, 255), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(2, 2, -2, -2))

    # ------------------------------------------------------------------
    # Snap
    # ------------------------------------------------------------------

    def itemChange(self, change, value):
        if (change == QGraphicsItem.GraphicsItemChange.ItemPositionChange
                and self.grid_snap and self.scene()):
            g = self.grid_size
            mode = getattr(self.scene(), 'snap_mode', 'centered')
            br = self.boundingRect()
            hw = br.width() / 2
            hh = br.height() / 2
            cx = value.x() + hw
            cy = value.y() + hh
            if mode == 'centered':
                snapped_cx = math.floor(cx / g) * g + g / 2
                snapped_cy = math.floor(cy / g) * g + g / 2
            else:  # 'lines'
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
        if self.is_anchor:
            anchors = [it for it in scene.items()
                       if isinstance(it, ImageItem) and it.is_anchor and it is not self]
            if anchors:
                max_z = max(it.zValue() for it in anchors)
                self._base_z = min(max_z + 1, _ANCHOR_MAX_Z)
            else:
                self._base_z = _ANCHOR_MAX_Z
        else:
            all_normal = [it for it in scene.items()
                          if isinstance(it, (CardItem, DeckItem, ImageItem, DieItem))
                          and not getattr(it, 'is_anchor', False)
                          and it is not self]
            max_z = max((it.zValue() for it in all_normal), default=_NORMAL_MIN_Z)
            self._base_z = max_z + 1
        self.setZValue(self._base_z)

    # ------------------------------------------------------------------
    # Public mutators
    # ------------------------------------------------------------------

    def rotate_cw(self, step: int = 45) -> None:
        cur = round(self.rotation() / step) * step
        self.setRotation((cur + step) % 360)

    def rotate_ccw(self, step: int = 45) -> None:
        cur = round(self.rotation() / step) * step
        self.setRotation((cur - step) % 360)

    def update_grid_size(self, new_size: int) -> None:
        """Called by MainWindow when the global grid size changes."""
        self.prepareGeometryChange()
        self.grid_size = new_size
        self._update_transform_origin()
        self._build_display_pixmap()
        self.update()

    def resize(self, w_cells: float, h_cells: float) -> None:
        self.prepareGeometryChange()
        self._w_cells = max(0.25, w_cells)
        self._h_cells = max(0.25, h_cells)
        self._update_transform_origin()
        self._build_display_pixmap()
        self.update()

    def reload_image(self) -> None:
        """Reload pixmap from _image_path (called after localize)."""
        self._pixmap = QPixmap(self._image_path) if self._image_path else QPixmap()
        self._aspect_ratio = self._compute_aspect_ratio()
        self._build_display_pixmap()
        self.update()

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.locked:
                event.ignore()
                return
            if self._resize_mode:
                self._resizing = True
                self._resize_start_pos = event.scenePos()
                self._resize_start_w = self._w_cells
                self._resize_start_h = self._h_cells
                event.accept()
                return
            self._raise_to_top()
            if self.measure_movement and not self._mm_dragging:
                self._mm_start_measure()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            delta = event.scenePos() - self._resize_start_pos
            # Use the larger-magnitude axis for scale
            pixel_delta = delta.x() if abs(delta.x()) >= abs(delta.y()) else delta.y()
            cell_delta = pixel_delta / self.grid_size
            new_w = max(0.25, self._resize_start_w + cell_delta)
            new_h = new_w / self._aspect_ratio if self._aspect_ratio > 0 else new_w
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                new_w = max(1.0, round(new_w))
                new_h = new_w / self._aspect_ratio if self._aspect_ratio > 0 else new_w
            self.prepareGeometryChange()
            self._w_cells = new_w
            self._h_cells = max(0.25, new_h)
            self._update_transform_origin()
            self._build_display_pixmap()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)
        if self._mm_dragging and self._mm_overlay:
            self._mm_current = self._item_center_scene()
            self._mm_overlay.set_data(
                self._mm_waypoints, self._mm_current,
                self.grid_size, self._cell_value, self._cell_unit, self._decimals,
            )

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing and event.button() == Qt.MouseButton.LeftButton:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self._mm_dragging and event.button() == Qt.MouseButton.LeftButton:
            self._mm_stop_measure()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.locked:
            self._resize_mode = not self._resize_mode
            if self._resize_mode:
                self._aspect_ratio = self._compute_aspect_ratio()
                self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
            else:
                self._resizing = False
                self.unsetCursor()
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    # Hover
    # ------------------------------------------------------------------

    def hoverEnterEvent(self, event) -> None:
        if self.hover_preview and not self.locked and self._image_path:
            self.image_hovered.emit(self._image_path)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        if self.hover_preview and not self.locked:
            self.image_unhovered.emit()
        super().hoverLeaveEvent(event)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event) -> None:
        # Exit resize mode on right-click
        if self._resize_mode:
            self._resize_mode = False
            self._resizing = False
            self.unsetCursor()
            self.update()

        # Option A: right-clicking an unselected item clears the selection
        if not self.isSelected():
            self.scene().clearSelection()
            self.setSelected(True)

        views = self.scene().views() if self.scene() else []
        parent = views[0] if views else None
        menu = QMenu(parent)

        sel_imgs = [i for i in self.scene().selectedItems() if isinstance(i, ImageItem)
                    and not getattr(i, 'is_anchor', False)]
        multi = len(sel_imgs) > 1

        # Rotate
        cw_label  = f"Rotate CW ({len(sel_imgs)})"  if multi else "Rotate CW"
        ccw_label = f"Rotate CCW ({len(sel_imgs)})" if multi else "Rotate CCW"
        menu.addAction(cw_label,  lambda: [i.rotate_cw()  for i in sel_imgs if not i.locked])
        menu.addAction(ccw_label, lambda: [i.rotate_ccw() for i in sel_imgs if not i.locked])

        # Single-item only actions
        if not multi:
            menu.addAction("Duplicate", lambda: self.duplicate_requested.emit(self))
            menu.addSeparator()
            snap_label = "✓ Snap to Grid" if self.grid_snap else "Snap to Grid"
            menu.addAction(snap_label, self._toggle_snap)
            menu.addAction("Resize…",    lambda: self.resize_requested.emit(self))
            menu.addAction("Reset Size", self._reset_size)
            menu.addAction("Localize",   lambda: self.localize_requested.emit(self))
        else:
            menu.addSeparator()
            snap_label = "✓ Snap to Grid" if self.grid_snap else "Snap to Grid"
            menu.addAction(snap_label, self._toggle_snap)

        menu.addSeparator()
        if not multi:
            anchor_label = "✓ Anchor" if self.is_anchor else "Anchor"
            menu.addAction(anchor_label, self._toggle_anchor)

        # Lock — majority state when multi
        majority_locked = sum(1 for i in sel_imgs if i.locked) > len(sel_imgs) / 2
        lock_label = "✓ Lock" if majority_locked else "Lock"
        def _toggle_lock_all():
            target = not majority_locked
            for i in sel_imgs:
                if i.locked != target:
                    i._toggle_lock()
        menu.addAction(lock_label, _toggle_lock_all if multi else self._toggle_lock)

        if not multi:
            preview_label = "Preview: On" if self.hover_preview else "Preview: Off"
            menu.addAction(preview_label, self._toggle_hover_preview)
            mm_label = "✓ Measure Movement" if self.measure_movement else "Measure Movement"
            menu.addAction(mm_label, self._toggle_measure_movement)
            minimap_label = "✓ Mini Map" if self.minimap else "Mini Map"
            menu.addAction(minimap_label, self._toggle_minimap)

        menu.addSeparator()
        del_label = f"Delete ({len(sel_imgs)})" if multi else "Delete"
        menu.addAction(del_label, self.delete_selected_requested.emit)

        from PyQt6.QtGui import QCursor
        menu.exec(QCursor.pos())

    def _toggle_snap(self) -> None:
        new_val = not self.grid_snap
        self.grid_snap = new_val
        if self.scene() and self.isSelected():
            for item in self.scene().selectedItems():
                if item is not self and hasattr(item, 'grid_snap'):
                    item.grid_snap = new_val

    def _toggle_lock(self) -> None:
        new_val = not self.locked
        self._apply_lock(new_val)
        if self.scene():
            for item in self.scene().selectedItems():
                if item is not self and hasattr(item, '_apply_lock'):
                    item._apply_lock(new_val)

    def _apply_lock(self, val: bool) -> None:
        self.locked = val
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not val)
        if not self.is_anchor:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not val)
        if val:
            self.setSelected(False)

    def _toggle_hover_preview(self) -> None:
        new_val = not self.hover_preview
        self.hover_preview = new_val
        if self.scene() and self.isSelected():
            for item in self.scene().selectedItems():
                if item is not self and hasattr(item, 'hover_preview'):
                    item.hover_preview = new_val

    def _toggle_anchor(self) -> None:
        self.is_anchor = not self.is_anchor
        scene = self.scene()
        if self.is_anchor:
            # Move into anchor Z range (below GridLayer at Z=-1)
            if scene:
                other_anchors = [it for it in scene.items()
                                 if isinstance(it, ImageItem) and it.is_anchor and it is not self]
                if other_anchors:
                    max_z = max(it.zValue() for it in other_anchors)
                    self._base_z = min(max_z + 1, _ANCHOR_MAX_Z)
                else:
                    self._base_z = _ANCHOR_MAX_Z
            else:
                self._base_z = _ANCHOR_MAX_Z
            self.setZValue(self._base_z)
            self._shadow.setEnabled(False)
            # Anchors are not rubber-band selectable
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
            self.setSelected(False)
        else:
            # Return to normal item range
            if scene:
                from .card_item import CardItem
                from .deck_item import DeckItem
                from .die_item import DieItem
                all_normal = [it for it in scene.items()
                              if isinstance(it, (CardItem, DeckItem, ImageItem, DieItem))
                              and not getattr(it, 'is_anchor', False)
                              and it is not self]
                self._base_z = max((it.zValue() for it in all_normal), default=_NORMAL_MIN_Z) + 1
            else:
                self._base_z = _NORMAL_MIN_Z
            self.setZValue(self._base_z)
            self._shadow.setEnabled(True)
            if not self.locked:
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def _reset_size(self) -> None:
        self.prepareGeometryChange()
        self._w_cells = self._orig_w_cells
        self._h_cells = self._orig_h_cells
        self._update_transform_origin()
        self._build_display_pixmap()
        self.update()

    def _toggle_minimap(self) -> None:
        self.minimap = not self.minimap
        self.minimap_requested.emit(self)

    def _toggle_measure_movement(self) -> None:
        new_val = not self.measure_movement
        self.measure_movement = new_val
        if self.scene() and self.isSelected():
            for item in self.scene().selectedItems():
                if item is not self and isinstance(item, ImageItem):
                    item.measure_movement = new_val

    # ------------------------------------------------------------------
    # Move-measure helpers
    # ------------------------------------------------------------------

    def _item_center_scene(self) -> QPointF:
        hw = self._w_cells * self.grid_size / 2
        hh = self._h_cells * self.grid_size / 2
        return self.mapToScene(QPointF(hw, hh))

    def _mm_start_measure(self) -> None:
        scene = self.scene()
        if not scene:
            return
        self._mm_dragging = True
        origin = self._item_center_scene()
        self._mm_waypoints = [origin]
        self._mm_current   = origin
        overlay = _MoveMeasureOverlay()
        self._mm_overlay = overlay
        scene.addItem(overlay)
        overlay.set_data(
            self._mm_waypoints, origin,
            self.grid_size, self._cell_value, self._cell_unit, self._decimals,
        )

    def _mm_stop_measure(self) -> None:
        self._mm_dragging = False
        if self._mm_overlay:
            if self._mm_overlay.scene():
                self._mm_overlay.scene().removeItem(self._mm_overlay)
            self._mm_overlay = None
        self._mm_waypoints = []
        self._mm_current   = QPointF()

    def add_move_waypoint(self) -> None:
        """Called from CanvasView when Space is pressed during a move-measure drag."""
        if not self._mm_dragging:
            return
        self._mm_waypoints.append(self._mm_current)
        if self._mm_overlay:
            self._mm_overlay.set_data(
                self._mm_waypoints, self._mm_current,
                self.grid_size, self._cell_value, self._cell_unit, self._decimals,
            )

    def update_measure_settings(self, cell_value: int, cell_unit: str, decimals: bool = False) -> None:
        self._cell_value = cell_value
        self._cell_unit  = cell_unit
        self._decimals   = decimals

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_state_dict(self) -> dict:
        return {
            "path":             self._image_path,
            "x":                self.pos().x(),
            "y":                self.pos().y(),
            "w_cells":          self._w_cells,
            "h_cells":          self._h_cells,
            "orig_w_cells":     self._orig_w_cells,
            "orig_h_cells":     self._orig_h_cells,
            "grid_snap":        self.grid_snap,
            "locked":           self.locked,
            "is_anchor":        self.is_anchor,
            "rotation":         self.rotation(),
            "z":                self.zValue(),
            "measure_movement": self.measure_movement,
            "minimap":          self.minimap,
            "minimap_geo":      self.minimap_geo,
        }
