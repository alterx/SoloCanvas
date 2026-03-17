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

"""MiniMapDialog – live read-only secondary view of the canvas for an ImageItem."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsView, QVBoxLayout,
)


class _MiniMapView(QGraphicsView):
    """QGraphicsView that suppresses the scene grid."""

    no_grid: bool = True   # read by GridLayer.paint() to skip grid for this view

    def drawBackground(self, painter: QPainter, rect) -> None:
        # Fill with the canvas background colour only — no grid.
        scene = self.scene()
        color = QColor(getattr(scene, "bg_color", "#55557f"))
        painter.fillRect(rect, color)


class MiniMapDialog(QDialog):
    """Non-modal, live, read-only view of the canvas framed around one ImageItem.

    The window aspect ratio is locked to the framed scene region so that
    resizing only changes the width — height follows automatically.
    """

    closed = pyqtSignal()

    _INITIAL_W_FRAC = 0.20   # starting width = 20% of primary screen width

    def __init__(self, scene, item, geometry=None, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle(f"Mini Map — {Path(item._image_path).name}")

        # ── Scene rect to frame (exact image bounds, no margin) ───────────
        self._scene_rect: QRectF = item.mapToScene(item.boundingRect()).boundingRect()
        self._aspect_ratio: float = (
            self._scene_rect.width() / max(self._scene_rect.height(), 1.0)
        )
        self._adjusting: bool = False

        # ── Graphics view ──────────────────────────────────────────────────
        self._view = _MiniMapView(scene)
        self._view.setInteractive(False)
        self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._view.setStyleSheet("background: #1A1B26;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        self.setStyleSheet("QDialog { background: #1A1B26; }")

        # ── Initial geometry ───────────────────────────────────────────────
        if geometry:
            self.setGeometry(geometry[0], geometry[1], geometry[2], geometry[3])
        else:
            screen = QApplication.primaryScreen()
            w = round(screen.geometry().width() * self._INITIAL_W_FRAC)
            h = round(w / self._aspect_ratio)
            self.resize(w, h)

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refit_view()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._adjusting:
            # Second call triggered by our own self.resize() — just refit.
            self._refit_view()
            return
        self._adjusting = True
        w = self.width()
        h = round(w / self._aspect_ratio)
        self.resize(w, h)
        self._adjusting = False

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        self.closed.emit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refit_view(self) -> None:
        self._view.fitInView(self._scene_rect, Qt.AspectRatioMode.KeepAspectRatio)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def geometry_list(self) -> list[int]:
        """Return current window geometry as [x, y, w, h] for serialisation."""
        g = self.geometry()
        return [g.x(), g.y(), g.width(), g.height()]
