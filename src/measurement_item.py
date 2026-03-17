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

"""MeasurementItem – QGraphicsObject for line/area/cone measurement overlays."""
from __future__ import annotations

import math
from typing import List, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsObject

# ---------------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------------

_C_LINE     = QColor("#7A6448")            # line/border colour (dark golden brown)
_C_FILL     = QColor(122, 100, 72, 60)     # area/cone fill (semi-transparent)
_C_ENDPOINT = QColor("#7A6448")
_C_GRID_FILL = QColor(122, 100, 72, 60)    # individual cell highlight
_C_DIM_BG    = QColor(15, 15, 25, 210)     # dimension label background
_C_DIM_TEXT  = QColor("#FFFFFF")

_LINE_W   = 2.0      # line stroke width (active)
_ENDPT_R  = 5.0      # endpoint dot radius
_MARGIN   = 30       # bounding-rect safety margin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snap_to_grid_center(pos: QPointF, grid_size: int) -> QPointF:
    """Return the nearest grid-square centre to *pos*."""
    g = grid_size
    col = round((pos.x() - g / 2) / g)
    row = round((pos.y() - g / 2) / g)
    return QPointF(col * g + g / 2, row * g + g / 2)


def _cell_of(pos: QPointF, grid_size: int) -> Tuple[int, int]:
    """Return (col, row) of the grid square that contains *pos*."""
    g = grid_size
    col = int(math.floor(pos.x() / g))
    row = int(math.floor(pos.y() / g))
    return col, row


def _cell_center(col: int, row: int, g: int) -> QPointF:
    return QPointF(col * g + g / 2, row * g + g / 2)


def _angle_diff(a: float, b: float) -> float:
    """Smallest signed angle difference between two radians, in [−π, π]."""
    d = (a - b) % (2 * math.pi)
    if d > math.pi:
        d -= 2 * math.pi
    return d


def _triangle_rect_intersect(
    p0: QPointF, p1: QPointF, p2: QPointF,
    rx: float, ry: float, g: float,
) -> bool:
    """
    Return True if triangle (p0, p1, p2) intersects axis-aligned rectangle
    [rx, ry, rx+g, ry+g], using the Separating Axis Theorem.
    The AABB quick-reject covers the two axis-aligned normals; then we test
    the three triangle edge normals.
    """
    # AABB quick reject
    tri_min_x = min(p0.x(), p1.x(), p2.x())
    tri_max_x = max(p0.x(), p1.x(), p2.x())
    tri_min_y = min(p0.y(), p1.y(), p2.y())
    tri_max_y = max(p0.y(), p1.y(), p2.y())
    if tri_max_x < rx or tri_min_x > rx + g or tri_max_y < ry or tri_min_y > ry + g:
        return False

    # SAT: test 3 triangle edge normals
    verts = [(p0.x(), p0.y()), (p1.x(), p1.y()), (p2.x(), p2.y())]
    rect_corners = [(rx, ry), (rx + g, ry), (rx + g, ry + g), (rx, ry + g)]
    for i in range(3):
        ax, ay = verts[i]
        bx, by = verts[(i + 1) % 3]
        # Perpendicular to edge a→b
        nx, ny = -(by - ay), (bx - ax)
        t_projs = [nx * vx + ny * vy for vx, vy in verts]
        r_projs = [nx * cx + ny * cy for cx, cy in rect_corners]
        if max(t_projs) < min(r_projs) or max(r_projs) < min(t_projs):
            return False

    return True


# ---------------------------------------------------------------------------
# MeasurementItem
# ---------------------------------------------------------------------------

class MeasurementItem(QGraphicsObject):
    """
    A single measurement overlay (Line, Area, or Cone).

    While *active* (being drawn): Z = 1000, not selectable/movable.
    When *frozen* (released): Z = −0.5, selectable + movable.

    Signals
    -------
    delete_requested  emitted when user selects "Delete" from the context menu.
    """

    delete_requested = pyqtSignal()

    def __init__(
        self,
        origin:       QPointF,
        measure_type: str,   # "line" | "area" | "cone"
        mode:         str,   # "grid"  | "free"
        grid_size:    int,
        cell_value:   int,
        cell_unit:    str,
        cone_angle:   float,
        decimals:     bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._measure_type = measure_type
        self._mode         = mode
        self._grid_size    = grid_size
        self._cell_value   = cell_value
        self._cell_unit    = cell_unit
        self._cone_angle   = float(cone_angle)
        self._decimals     = decimals
        self._active       = True

        # Snap origin when in grid mode
        if mode == "grid":
            self._origin = _snap_to_grid_center(origin, grid_size)
        else:
            self._origin = QPointF(origin)

        self._end = QPointF(self._origin)
        self._waypoints: List[QPointF] = []

        # Active: very high Z, transparent to mouse
        self.setZValue(1000)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_end(self, pos: QPointF) -> None:
        """Update the measurement endpoint (call while dragging)."""
        self.prepareGeometryChange()
        if self._mode == "grid":
            self._end = _snap_to_grid_center(pos, self._grid_size)
        else:
            self._end = QPointF(pos)
        self.update()

    def freeze(self) -> None:
        """Finalise the measurement: lower Z, make selectable/movable."""
        self._active = False
        self.setZValue(-0.5)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)
        self.update()

    def add_waypoint(self) -> None:
        """Pin the current endpoint as a waypoint; line measurement continues from there."""
        if self._measure_type != "line":
            return
        self.prepareGeometryChange()
        self._waypoints.append(QPointF(self._end))
        self.update()

    def dimension_text(self) -> str:
        """Human-readable measurement string, e.g. '15 ft'."""
        g  = self._grid_size
        dx = self._end.x() - self._origin.x()
        dy = self._end.y() - self._origin.y()

        if self._measure_type == "line":
            points = [self._origin] + self._waypoints + [self._end]
            total = 0.0
            for i in range(len(points) - 1):
                seg_dx = points[i + 1].x() - points[i].x()
                seg_dy = points[i + 1].y() - points[i].y()
                if self._mode == "grid":
                    total += max(abs(round(seg_dx / g)), abs(round(seg_dy / g)))
                else:
                    total += math.hypot(seg_dx, seg_dy) / g
            dist = total * self._cell_value
            fmt = ".1f" if self._decimals else ".0f"
            return f"{dist:{fmt}} {self._cell_unit}"

        elif self._measure_type == "area":
            if self._mode == "grid":
                dc = abs(round(dx / g))
                dr = abs(round(dy / g))
                radius_cells = max(dc, dr)
            else:
                radius_cells = math.hypot(dx, dy) / g
            radius = radius_cells * self._cell_value
            fmt = ".1f" if self._decimals else ".0f"
            return f"{radius:{fmt}} {self._cell_unit} radius"

        else:  # cone
            dist_px = math.hypot(dx, dy)
            if self._mode == "grid":
                cells = max(abs(round(dx / g)), abs(round(dy / g)))
            else:
                cells = dist_px / g
            length = cells * self._cell_value
            fmt = ".1f" if self._decimals else ".0f"
            return f"{length:{fmt}} {self._cell_unit} cone"

    # ------------------------------------------------------------------
    # QGraphicsItem interface
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        ox, oy = self._origin.x(), self._origin.y()
        ex, ey = self._end.x(), self._end.y()
        g      = self._grid_size

        if self._measure_type == "line":
            pts = [self._origin] + self._waypoints + [self._end]
            xs = [p.x() for p in pts]
            ys = [p.y() for p in pts]
            x = min(xs) - _MARGIN
            y = min(ys) - _MARGIN
            w = max(xs) - min(xs) + _MARGIN * 2
            h = max(ys) - min(ys) + _MARGIN * 2
            return QRectF(x, y, max(w, 40), max(h, 40))

        elif self._measure_type == "area":
            dx = ex - ox
            dy = ey - oy
            if self._mode == "grid":
                r = max(abs(round(dx / g)), abs(round(dy / g))) * g
            else:
                r = math.hypot(dx, dy)
            r += g + _MARGIN
            return QRectF(ox - r, oy - r, r * 2, r * 2)

        else:  # cone
            dist = math.hypot(ex - ox, ey - oy)
            half = math.radians(self._cone_angle / 2)
            r = dist + g + _MARGIN
            return QRectF(ox - r, oy - r, r * 2, r * 2)

    def shape(self) -> QPainterPath:
        if not self._active:
            # Frozen items: use bounding rect as hit area
            path = QPainterPath()
            path.addRect(self.boundingRect())
            return path
        return QPainterPath()  # Active items: no hit testing

    def paint(self, painter: QPainter, option, widget) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._measure_type == "line":
            self._paint_line(painter, _C_LINE)
        elif self._measure_type == "area":
            self._paint_area(painter, _C_LINE, _C_FILL)
        else:
            self._paint_cone(painter, _C_LINE, _C_FILL)

        # Dimension label only on frozen items (active ones use the bubble widget)
        if not self._active:
            self._paint_label(painter)

    # ------------------------------------------------------------------
    # Paint helpers
    # ------------------------------------------------------------------

    def _paint_line(self, painter: QPainter, color: QColor) -> None:
        points = [self._origin] + self._waypoints + [self._end]

        pen = QPen(color, _LINE_W)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        for i in range(len(points) - 1):
            if self._mode == "grid":
                self._draw_chebyshev_segment(painter, color, points[i], points[i + 1])
            else:
                painter.drawLine(points[i], points[i + 1])

        # All points (endpoints + waypoints) get a dot
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        for pt in points:
            painter.drawEllipse(pt, _ENDPT_R, _ENDPT_R)

    def _draw_chebyshev_segment(
        self, painter: QPainter, color: QColor,
        seg_start: QPointF, seg_end: QPointF,
    ) -> None:
        """Draw one diagonal+straight Chebyshev segment (DnD 5E style)."""
        g  = self._grid_size
        ox = seg_start.x()
        oy = seg_start.y()
        ex = seg_end.x()
        ey = seg_end.y()
        dx = round((ex - ox) / g)
        dy = round((ey - oy) / g)

        sx = int(math.copysign(1, dx)) if dx != 0 else 0
        sy = int(math.copysign(1, dy)) if dy != 0 else 0

        diag = min(abs(dx), abs(dy))
        straight_x = abs(dx) - diag
        straight_y = abs(dy) - diag

        path = QPainterPath()
        path.moveTo(ox, oy)

        cx, cy = ox, oy
        if diag:
            cx += sx * diag * g
            cy += sy * diag * g
            path.lineTo(cx, cy)
        if straight_x:
            cx += sx * straight_x * g
            path.lineTo(cx, cy)
        if straight_y:
            cy += sy * straight_y * g
            path.lineTo(cx, cy)

        pen = QPen(color, _LINE_W)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _paint_area(self, painter: QPainter, color: QColor, fill: QColor) -> None:
        g  = self._grid_size
        ox = self._origin.x()
        oy = self._origin.y()
        dx = self._end.x() - ox
        dy = self._end.y() - oy

        if self._mode == "grid":
            dc = abs(round(dx / g))
            dr = abs(round(dy / g))
            radius_cells = max(dc, dr)
            radius_px    = radius_cells * g

            # Highlight grid squares within radius (Euclidean, DnD 5E circle)
            orig_col, orig_row = _cell_of(self._origin, g)
            for col in range(orig_col - radius_cells - 1, orig_col + radius_cells + 2):
                for row in range(orig_row - radius_cells - 1, orig_row + radius_cells + 2):
                    cx = col * g + g / 2
                    cy = row * g + g / 2
                    if math.hypot(cx - ox, cy - oy) <= radius_px + g * 0.5:
                        painter.fillRect(
                            QRectF(col * g, row * g, g, g),
                            QBrush(fill),
                        )

            # Circle outline
            pen = QPen(color, _LINE_W)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self._origin, radius_px, radius_px)
        else:
            radius_px = math.hypot(dx, dy)
            painter.setBrush(QBrush(fill))
            pen = QPen(color, _LINE_W)
            painter.setPen(pen)
            painter.drawEllipse(self._origin, radius_px, radius_px)

        # Centre dot
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self._origin, _ENDPT_R, _ENDPT_R)

    def _paint_cone(self, painter: QPainter, color: QColor, fill: QColor) -> None:
        g      = self._grid_size
        ox     = self._origin.x()
        oy     = self._origin.y()
        dx     = self._end.x() - ox
        dy     = self._end.y() - oy
        dist   = math.hypot(dx, dy)
        if dist < 1:
            return

        direction = math.atan2(dy, dx)
        half_cone  = math.radians(self._cone_angle / 2)

        if self._mode == "grid":
            dc = abs(round(dx / g))
            dr = abs(round(dy / g))
            length_cells = max(dc, dr)
            length_px    = length_cells * g
        else:
            length_px = dist

        if length_px < 1:
            return

        # Cone outline points (used for both fill and outline drawing)
        p_left  = QPointF(
            ox + length_px * math.cos(direction - half_cone),
            oy + length_px * math.sin(direction - half_cone),
        )
        p_right = QPointF(
            ox + length_px * math.cos(direction + half_cone),
            oy + length_px * math.sin(direction + half_cone),
        )

        if self._mode == "grid":
            # SAT-based cell fill: shade every cell that the triangle touches
            tri_xs = [ox, p_left.x(), p_right.x()]
            tri_ys = [oy, p_left.y(), p_right.y()]
            min_col = int(math.floor(min(tri_xs) / g))
            max_col = int(math.ceil(max(tri_xs) / g))
            min_row = int(math.floor(min(tri_ys) / g))
            max_row = int(math.ceil(max(tri_ys) / g))
            for col in range(min_col, max_col + 1):
                for row in range(min_row, max_row + 1):
                    rx, ry = col * g, row * g
                    if _triangle_rect_intersect(self._origin, p_left, p_right, rx, ry, g):
                        painter.fillRect(QRectF(rx, ry, g, g), QBrush(fill))

        if self._mode == "free":
            # Triangle fill: apex → left edge → right edge
            tri_path = QPainterPath()
            tri_path.moveTo(ox, oy)
            tri_path.lineTo(p_left.x(), p_left.y())
            tri_path.lineTo(p_right.x(), p_right.y())
            tri_path.closeSubpath()
            painter.fillPath(tri_path, QBrush(fill))
            painter.setPen(QPen(color, _LINE_W))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(tri_path)
        else:
            # Grid mode: draw triangle outline (cells already filled above)
            painter.setPen(QPen(color, _LINE_W))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(self._origin, p_left)
            painter.drawLine(self._origin, p_right)
            painter.drawLine(p_left, p_right)

        # Apex dot
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self._origin, _ENDPT_R, _ENDPT_R)

    def _paint_label(self, painter: QPainter) -> None:
        """Draw the dimension label below the measurement's bounding rect."""
        text = self.dimension_text()
        font = QFont("Arial", 9, QFont.Weight.Bold)
        fm   = QFontMetrics(font)
        tw   = fm.horizontalAdvance(text)
        th   = fm.height()

        # Position label near the end point
        ex, ey = self._end.x(), self._end.y()
        lx = ex - tw / 2
        ly = ey + 12

        # Background pill
        pad = 4
        bg_rect = QRectF(lx - pad, ly - th + 2, tw + pad * 2, th + pad)
        painter.setBrush(QBrush(_C_DIM_BG))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bg_rect, 4, 4)

        # Text
        painter.setFont(font)
        painter.setPen(QPen(_C_DIM_TEXT))
        painter.drawText(QPointF(lx, ly + 2), text)

    # ------------------------------------------------------------------
    # Session persistence helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "measure_type": self._measure_type,
            "mode":         self._mode,
            "grid_size":    self._grid_size,
            "cell_value":   self._cell_value,
            "cell_unit":    self._cell_unit,
            "cone_angle":   self._cone_angle,
            "decimals":     self._decimals,
            "origin":       [self._origin.x(), self._origin.y()],
            "waypoints":    [[p.x(), p.y()] for p in self._waypoints],
            "end":          [self._end.x(),    self._end.y()],
            "pos":          [self.x(), self.y()],
            "rotation":     self.rotation(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MeasurementItem":
        item = cls(
            origin       = QPointF(d["origin"][0], d["origin"][1]),
            measure_type = d["measure_type"],
            mode         = d["mode"],
            grid_size    = d["grid_size"],
            cell_value   = d["cell_value"],
            cell_unit    = d["cell_unit"],
            cone_angle   = d["cone_angle"],
            decimals     = d.get("decimals", False),
        )
        item._end = QPointF(d["end"][0], d["end"][1])
        item._waypoints = [QPointF(p[0], p[1]) for p in d.get("waypoints", [])]
        item.freeze()
        item.setPos(d.get("pos", [0, 0])[0], d.get("pos", [0, 0])[1])
        item.setRotation(d.get("rotation", 0))
        return item
