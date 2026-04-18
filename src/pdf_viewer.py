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

"""PDF viewer window — persistent, non-modal, tabbed, themed to match the app."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import qtawesome as qta

from PyQt6.QtCore import (
    QBuffer, QByteArray, QEvent, QIODevice, QModelIndex, QObject, QPointF,
    QRect, QRunnable, QSize, Qt, QThreadPool, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap,
)
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QStyledItemDelegate, QStyleOptionViewItem, QTabWidget, QTextEdit,
    QToolButton, QTreeView, QVBoxLayout, QWidget,
)

try:
    from PyQt6.QtPdf import QPdfBookmarkModel, QPdfDocument, QPdfSearchModel
    from PyQt6.QtPdfWidgets import QPdfView
    _PDF_OK = True
except ImportError:
    _PDF_OK = False

try:
    import pymupdf as fitz
    _FITZ_OK = True
except ImportError:
    try:
        import fitz  # type: ignore
        _FITZ_OK = True
    except ImportError:
        _FITZ_OK = False

from src.pdf_bookmarks import PDFBookmarksManager

# ---------------------------------------------------------------------------
# PDF last-page persistence (dedicated JSON, independent of settings lifecycle)
# ---------------------------------------------------------------------------

def _read_pdf_pages(settings) -> Dict[str, int]:
    """Return {normalised_path: page} from the dedicated JSON file."""
    try:
        p = settings.pdf_pages_path()
        if p.exists():
            import json as _json
            data = _json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_pdf_pages(settings, pages: Dict[str, int]) -> None:
    """Persist {normalised_path: page} to the dedicated JSON file."""
    try:
        import json as _json
        settings.pdf_pages_path().write_text(
            _json.dumps(pages, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Theme constants
# ---------------------------------------------------------------------------

def _tab_close_icon_path() -> str:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    return (base / "resources" / "images" / "tab_close.svg").as_posix()


_SS = """
QDialog, QWidget#pdf_root {
    background-color: #292A35;
    color: #D4C5AE;
}
QPushButton, QToolButton {
    background-color: #3B3C4F;
    color: #D4C5AE;
    border: 1px solid #4B4D63;
    border-radius: 4px;
    padding: 3px 7px;
    font-size: 12px;
}
QPushButton:hover, QToolButton:hover {
    background-color: #4B4D63;
}
QPushButton:pressed, QToolButton:pressed,
QPushButton:checked, QToolButton:checked {
    background-color: #524E48;
    color: #BFA381;
    border-color: #BFA381;
}
QPushButton:disabled, QToolButton:disabled {
    color: #5A586A;
    border-color: #3B3C4F;
}
QLineEdit, QSpinBox, QComboBox {
    background-color: #1E1F28;
    color: #D4C5AE;
    border: 1px solid #4B4D63;
    border-radius: 4px;
    padding: 3px 6px;
    font-size: 12px;
}
QComboBox::drop-down { border: none; }
QCheckBox { color: #D4C5AE; font-size: 12px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #4B4D63; border-radius: 2px;
    background: #1E1F28;
}
QCheckBox::indicator:checked { background: #BFA381; }
QTreeView, QListWidget {
    background-color: #1E1F28;
    color: #D4C5AE;
    border: 1px solid #4B4D63;
    border-radius: 4px;
    font-size: 12px;
    outline: none;
}
QTreeView::item, QListWidget::item {
    padding: 3px 4px;
}
QTreeView::item:hover, QListWidget::item:hover {
    background-color: #3B3C4F;
}
QTreeView::item:selected, QListWidget::item:selected {
    background-color: #524E48;
    color: #BFA381;
}
QScrollBar:vertical {
    background: #1E1F28; width: 8px; border-radius: 4px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #4B4D63; border-radius: 4px; min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #1E1F28; height: 8px; border-radius: 4px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: #4B4D63; border-radius: 4px; min-width: 24px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle { background: #4B4D63; }
QLabel { background: transparent; color: #D4C5AE; font-size: 12px; }
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: #1E1F28; color: #7A7890;
    padding: 4px 10px;
    border: 1px solid #3B3C4F; border-bottom: none;
    border-top-left-radius: 3px; border-top-right-radius: 3px;
    font-size: 11px;
}
QTabBar::tab:selected { background: #292A35; color: #D4C5AE; }
QTabBar::tab:hover:!selected { background: #252632; }
"""

_C_ICON   = "#9E886C"
_C_ACCENT = "#BFA381"
_THUMB_W  = 140
_RECENT_W = 110
_MAX_RECENT = 20


def _icon(name: str, color: str = _C_ICON) -> QIcon:
    return qta.icon(name, color=color)


def _thumb_cache_key(path: str, page: int, width: int) -> str:
    h = hashlib.md5(f"{path}:{os.path.getmtime(path):.0f}".encode()).hexdigest()[:12]
    return f"{h}_p{page}_w{width}.png"


# ---------------------------------------------------------------------------
# Background thumbnail worker
# ---------------------------------------------------------------------------

class _ThumbSignals(QObject):
    ready = pyqtSignal(str, int, QPixmap)   # doc_path, page, pixmap


class _ThumbnailWorker(QRunnable):
    def __init__(self, path: str, page: int, width: int, cache_path: str):
        super().__init__()
        self.path       = path
        self.page       = page
        self.width      = width
        self.cache_path = cache_path
        self.signals    = _ThumbSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        cached = QPixmap(self.cache_path)
        if not cached.isNull():
            self.signals.ready.emit(self.path, self.page, cached)
            return
        if not _PDF_OK:
            return
        try:
            doc = QPdfDocument(None)
            if doc.load(self.path) != QPdfDocument.Error.None_:
                return
            page_sz = doc.pagePointSize(self.page)
            if page_sz.isEmpty():
                return
            h   = max(1, int(self.width * page_sz.height() / page_sz.width()))
            img = doc.render(self.page, QSize(self.width, h))
            doc.close()
            if not img.isNull():
                img.save(self.cache_path)
                self.signals.ready.emit(self.path, self.page, QPixmap.fromImage(img))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Thumbnail delegate
# ---------------------------------------------------------------------------

_ROLE_PAGE = Qt.ItemDataRole.UserRole
_ROLE_PIX  = Qt.ItemDataRole.UserRole + 1


class _ThumbDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        pix: Optional[QPixmap] = index.data(_ROLE_PIX)
        if pix and not pix.isNull():
            return QSize(_THUMB_W + 12, pix.height() + 20)
        return QSize(_THUMB_W + 12, int(_THUMB_W * 1.414) + 20)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        from PyQt6.QtWidgets import QStyle
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#524E48"))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor("#3B3C4F"))
        else:
            painter.fillRect(option.rect, QColor("#1E1F28"))
        page: int = index.data(_ROLE_PAGE) or 0
        pix: Optional[QPixmap] = index.data(_ROLE_PIX)
        r   = option.rect
        pad = 6
        img_x = r.x() + pad
        img_y = r.y() + pad
        img_w = r.width() - pad * 2
        if pix and not pix.isNull():
            img_h = pix.height()
            painter.drawPixmap(img_x, img_y, pix.scaledToWidth(
                img_w, Qt.TransformationMode.SmoothTransformation))
        else:
            img_h = int(img_w * 1.414)
            painter.fillRect(img_x, img_y, img_w, img_h, QColor("#3B3C4F"))
            painter.setPen(QColor(_C_ICON))
            painter.drawText(img_x, img_y, img_w, img_h,
                             Qt.AlignmentFlag.AlignCenter, "…")
        badge = str(page + 1)
        painter.setPen(QColor(_C_ACCENT))
        painter.setFont(QFont("Arial", 9))
        painter.drawText(r.x(), img_y + img_h + 2, r.width() - pad,
                         14, Qt.AlignmentFlag.AlignHCenter, badge)
        painter.restore()


# ---------------------------------------------------------------------------
# Recent PDFs dialog
# ---------------------------------------------------------------------------

class _RecentDialog(QDialog):
    pdf_chosen = pyqtSignal(str)

    def __init__(self, entries: List[Dict[str, Any]], thumbs_dir: Path,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Recent PDFs")
        self.setMinimumSize(560, 400)
        self.setStyleSheet(_SS)
        self.setObjectName("pdf_root")
        self._entries    = entries
        self._thumbs_dir = thumbs_dir
        self._pool       = QThreadPool.globalInstance()
        self._build_ui()
        self._load_thumbs()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lbl = QLabel("Recently Opened PDFs")
        lbl.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#BFA381;")
        lay.addWidget(lbl)
        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(_RECENT_W, int(_RECENT_W * 1.414)))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setGridSize(QSize(_RECENT_W + 20, int(_RECENT_W * 1.414) + 36))
        self._list.setSpacing(6)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.itemDoubleClicked.connect(self._on_choose)
        lay.addWidget(self._list)
        for i, e in enumerate(self._entries):
            item = QListWidgetItem(Path(e["path"]).stem)
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setSizeHint(QSize(_RECENT_W + 20, int(_RECENT_W * 1.414) + 36))
            self._list.addItem(item)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        open_btn = QPushButton("Open Selected")
        open_btn.clicked.connect(self._on_choose)
        close_btn = QPushButton("Cancel")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

    def _load_thumbs(self) -> None:
        for i, e in enumerate(self._entries):
            path = e["path"]
            if not Path(path).exists():
                continue
            try:
                cache = str(self._thumbs_dir / _thumb_cache_key(path, 0, _RECENT_W))
            except OSError:
                continue
            w = _ThumbnailWorker(path, 0, _RECENT_W, cache)
            w.signals.ready.connect(lambda p, pg, pix, idx=i: self._on_thumb(idx, pix))
            self._pool.start(w)

    def _on_thumb(self, idx: int, pix: QPixmap) -> None:
        item = self._list.item(idx)
        if item:
            item.setIcon(QIcon(pix))

    def _on_choose(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return
        idx  = items[0].data(Qt.ItemDataRole.UserRole)
        path = self._entries[idx]["path"]
        if Path(path).exists():
            self.pdf_chosen.emit(path)
            self.accept()


# ---------------------------------------------------------------------------
# Form overlay — interactive form-field widgets over the PDF view
# ---------------------------------------------------------------------------

class _FormOverlay(QWidget):
    """Transparent overlay on top of QPdfView.viewport().

    Positions QLineEdit / QCheckBox / QComboBox widgets exactly over the
    PDF's AcroForm fields so the user can fill them in by clicking directly
    on the PDF.
    """

    # page, name, new_value, old_value, ftype
    field_committed  = pyqtSignal(int, str, object, object, str)
    # fired on every keystroke in any text field (for dirty tracking)
    any_field_modified = pyqtSignal()

    _FIELD_SS = (
        "background: rgba(220, 235, 255, 210);"
        "border: 1px solid #4A90D9;"
        "border-radius: 2px;"
        "color: #000000;"
        # font-size is set dynamically in update_positions() via setFont()
    )

    def __init__(self, view: "QPdfView", doc: "QPdfDocument") -> None:
        super().__init__(view.viewport())
        self._view   = view
        self._doc    = doc
        self._fields: List[Dict[str, Any]] = []
        self._initial_text_values: Dict[str, str] = {}

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        # WA_NoSystemBackground stops Qt from filling our background before
        # paintEvent — since paintEvent does nothing, the viewport (PDF) shows
        # through.  Do NOT set WA_TranslucentBackground: on Windows it cascades
        # to child widgets and makes all QLineEdit/QCheckBox children invisible.
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        # Single debounced timer so every trigger funnels through one path.
        # 0 ms = fire in the next event-loop pass, after Qt finishes the
        # synchronous work that triggered the update (layout, scroll, zoom).
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(0)
        self._update_timer.timeout.connect(self._do_update)

        view.viewport().installEventFilter(self)
        view.verticalScrollBar().valueChanged.connect(self._schedule_update)
        view.horizontalScrollBar().valueChanged.connect(self._schedule_update)
        # zoomFactorChanged fires after QPdfView recomputes FitToWidth / FitInView.
        view.zoomFactorChanged.connect(self._schedule_update)
        # zoomModeChanged fires when the user switches zoom mode.
        try:
            view.zoomModeChanged.connect(self._schedule_update)
        except AttributeError:
            pass

        self.resize(view.viewport().size())
        self.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_fields(self, fitz_doc: Any) -> None:
        """Build overlay widgets for all AcroForm fields in *fitz_doc*."""
        self._clear_widgets()
        if fitz_doc is None:
            return
        # Use fitz constants so we stay correct across pymupdf versions
        _CB  = getattr(fitz, "PDF_WIDGET_TYPE_CHECKBOX",   2)
        _RB  = getattr(fitz, "PDF_WIDGET_TYPE_RADIOBUTTON", 5)
        _CMB = getattr(fitz, "PDF_WIDGET_TYPE_COMBOBOX",   3)
        _LB  = getattr(fitz, "PDF_WIDGET_TYPE_LISTBOX",    4)
        _TXT = getattr(fitz, "PDF_WIDGET_TYPE_TEXT",       7)

        for page_idx in range(len(fitz_doc)):
            try:
                fitz_page = fitz_doc[page_idx]
            except Exception:
                continue
            for w in fitz_page.widgets():
                ftype_int = w.field_type
                if ftype_int == _CB or ftype_int == _RB:
                    ftype = "checkbox"
                elif ftype_int == _CMB:
                    ftype = "combobox"
                elif ftype_int == _LB:
                    ftype = "listbox"
                elif ftype_int == _TXT:
                    ftype = "text"
                else:
                    continue  # button, signature, unknown → skip
                choices: List[str] = []
                try:
                    choices = list(w.choice_values or [])
                except Exception:
                    pass
                field_info: Dict[str, Any] = {
                    "page":          page_idx,
                    "name":          w.field_name or "",
                    "type":          ftype,
                    "value":         w.field_value or "",
                    "initial_value": w.field_value or "",
                    "choices":       choices,
                    "rect":          w.rect,   # fitz.Rect, top-left origin, PDF pts
                    "qwidget":       None,
                }
                field_info["qwidget"] = self._make_widget(field_info)
                self._fields.append(field_info)
        self.update_positions()
        if self._fields:
            self.show()
            self.raise_()

    def clear(self) -> None:
        self._clear_widgets()
        self._initial_text_values.clear()
        self.hide()

    def _schedule_update(self, *_args) -> None:
        """Funnel all signals through the debounced timer.
        Calling start() on an already-pending timer restarts it, so rapid-fire
        signals collapse into a single update."""
        self._update_timer.start()

    def _do_update(self) -> None:
        """Timer callback — runs after the current event-loop pass completes,
        so QPdfView's layout / scroll-bar ranges are already up-to-date."""
        self.update_positions()
        self.raise_()

    def _derive_scale(self) -> float:
        """Return the actual pixels-per-point scale QPdfView is using.

        Primary method: back-calculate from the vertical scroll bar range,
        which is set by QPdfView *after* layout — so it's always up-to-date
        by the time our deferred timer fires.

        Formula:
            total_content_height = top_margin + bottom_margin
                                   + Σ round(pts_h[i] * scale)
                                   + spacing * (n − 1)
        Rearranged (approximating Σ round(...) ≈ total_pts * scale):
            scale ≈ (total_px − margins − spacing*(n−1)) / total_pts

        The error from per-page rounding is ≤ n/2 px in total content height,
        which translates to < 0.1 % scale error for typical page counts.

        Fallback: use view.zoomFactor() when the document fits entirely in the
        viewport (vsb.maximum() == 0) or if the arithmetic fails.
        """
        view = self._view
        doc  = self._doc
        n    = doc.pageCount() if doc else 0

        if n > 0:
            vsb = view.verticalScrollBar()
            if vsb.maximum() > 0:
                try:
                    dm          = view.documentMargins()
                    top_margin  = dm.top()
                    bot_margin  = dm.bottom()
                except Exception:
                    top_margin = bot_margin = 6
                try:
                    spacing = view.pageSpacing()
                except Exception:
                    spacing = 3

                total_content_px = vsb.maximum() + view.viewport().height()
                total_pts = sum(doc.pagePointSize(p).height() for p in range(n))
                net_px = total_content_px - top_margin - bot_margin - spacing * (n - 1)
                if total_pts > 0 and net_px > 0:
                    return net_px / total_pts

        # Fallback: derive from zoomFactor property.
        # Use viewport().logicalDpiX() to match QPdfView's internal m_dpiX.
        dpi  = view.viewport().logicalDpiX()
        zoom = max(0.01, view.zoomFactor())
        return (dpi / 72.0) * zoom

    def update_positions(self) -> None:
        """Recalculate all widget positions from current scroll/zoom state."""
        if not self._fields or not _PDF_OK:
            return

        view  = self._view
        doc   = self._doc
        scale = self._derive_scale()

        # Document margins and page spacing
        try:
            dm  = view.documentMargins()
            top_margin  = dm.top()
            left_margin = dm.left()
        except Exception:
            top_margin  = 6
            left_margin = 6
        try:
            spacing = view.pageSpacing()
        except Exception:
            spacing = 3

        sv   = view.verticalScrollBar().value()
        sh   = view.horizontalScrollBar().value()
        vp_w = view.viewport().width()
        vp_h = view.viewport().height()

        # Cumulative top of each page in scroll-space.
        # Round each page height to the nearest integer to match Qt's own
        # integer layout arithmetic (.toSize()), preventing Y-drift on
        # multi-page documents where floating-point errors accumulate.
        page_tops: Dict[int, int] = {}
        y = top_margin
        n = doc.pageCount() if doc else 0
        for p in range(n):
            page_tops[p] = y
            ph_px = round(doc.pagePointSize(p).height() * scale)
            y += ph_px + spacing

        for fi in self._fields:
            qw = fi.get("qwidget")
            if qw is None:
                continue
            p = fi["page"]
            r = fi["rect"]   # fitz.Rect: x0, y0, x1, y1 in PDF pts, top-left origin
            if p not in page_tops:
                qw.hide()
                continue

            # Horizontal offset: match Qt's centering logic exactly.
            # Qt centers the page when pageSize.width() < viewport.width().
            pw_px = round(doc.pagePointSize(p).width() * scale)
            x_off = (vp_w - pw_px) / 2.0 if pw_px < vp_w else float(left_margin)

            sx  = x_off + r.x0 * scale - sh
            sy  = page_tops[p] + r.y0 * scale - sv
            sw  = max(10, (r.x1 - r.x0) * scale)
            sh2 = max(10, (r.y1 - r.y0) * scale)

            qw.setGeometry(QRect(round(sx), round(sy), round(sw), round(sh2)))

            # Scale font / indicator to match the rendered field height.
            # 65 % of field height gives a comfortable fit; clamped to [8, 48] px.
            font_px = max(8, min(16, round(sh2 * 0.65)))
            if isinstance(qw, QCheckBox):
                ind_px = max(8, round(sh2 - 4))
                qw.setStyleSheet(self._cb_stylesheet(ind_px))
            else:
                font = QFont()
                font.setPixelSize(font_px)
                qw.setFont(font)

            vis = (sy + sh2 > 0 and sy < vp_h and sx + sw > 0 and sx < vp_w)
            qw.setVisible(vis)

    def update_field_value(self, name: str, value: Any) -> None:
        """Refresh a widget's display after undo/redo (no signal emitted)."""
        for fi in self._fields:
            if fi["name"] != name:
                continue
            qw = fi.get("qwidget")
            if qw is None:
                continue
            fi["value"]         = value
            fi["initial_value"] = value
            qw.blockSignals(True)
            if isinstance(qw, QCheckBox):
                qw.setChecked(bool(value) and
                              str(value).lower() not in ("off", "false", "0", ""))
            elif isinstance(qw, QComboBox):
                qw.setCurrentText(str(value))
            elif isinstance(qw, QTextEdit):
                qw.setPlainText(str(value) if value else "")
            qw.blockSignals(False)
            break

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _cb_stylesheet(indicator_px: int) -> str:
        """Checkbox stylesheet with a scaled indicator square."""
        return (
            f"QCheckBox {{ background: rgba(220,235,255,210); "
            f"border: 1px solid #4A90D9; border-radius: 2px; padding: 2px; }}"
            f"QCheckBox::indicator {{ width: {indicator_px}px; height: {indicator_px}px; "
            f"border: 1px solid #4A90D9; background: white; }}"
            f"QCheckBox::indicator:checked {{ background: #4A90D9; }}"
        )

    def _make_widget(self, fi: Dict[str, Any]) -> QWidget:
        ftype = fi["type"]
        if ftype == "checkbox":
            w = QCheckBox(self)
            w.setStyleSheet(self._cb_stylesheet(12))   # initial size; rescaled in update_positions
            w.setChecked(bool(fi["value"]) and
                         str(fi["value"]).lower() not in ("off", "false", "0", ""))
            w.stateChanged.connect(
                lambda state, f=fi: self._cb_changed(f, state))
        elif ftype in ("combobox", "listbox"):
            w = QComboBox(self)
            w.setStyleSheet(self._FIELD_SS)
            for ch in fi["choices"]:
                w.addItem(ch)
            if fi["value"] in fi["choices"]:
                w.setCurrentText(fi["value"])
            w.currentTextChanged.connect(
                lambda v, f=fi: self._combo_changed(f, v))
        else:
            w = QTextEdit(self)
            w.setStyleSheet(self._FIELD_SS)
            # Qt won't propagate background on QAbstractScrollArea to its
            # internal viewport — set it explicitly so the field is visible.
            w.viewport().setStyleSheet("background: rgba(220, 235, 255, 210);")
            w.setPlainText(str(fi["value"]) if fi["value"] else "")
            w.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            w.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            w.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            w.setFrameShape(QFrame.Shape.NoFrame)
            w.document().setDocumentMargin(2)
            # Install on both outer widget and viewport — on Windows/PyQt6
            # FocusOut fires on the outer QTextEdit, not the viewport.
            w.installEventFilter(self)
            w.viewport().installEventFilter(self)
            w.textChanged.connect(self.any_field_modified.emit)
        w.show()
        return w

    def _clear_widgets(self) -> None:
        for fi in self._fields:
            qw = fi.get("qwidget")
            if qw:
                qw.deleteLater()
        self._fields = []

    def _cb_changed(self, fi: Dict[str, Any], state: int) -> None:
        old = fi["value"]
        new = "Yes" if state else "Off"
        fi["value"]         = new
        fi["initial_value"] = new
        self.field_committed.emit(fi["page"], fi["name"], new, old, "checkbox")

    def _combo_changed(self, fi: Dict[str, Any], value: str) -> None:
        old = fi["value"]
        fi["value"]         = value
        fi["initial_value"] = value
        self.field_committed.emit(fi["page"], fi["name"], value, old, fi["type"])

    def _text_finished(self, fi: Dict[str, Any], editor: QTextEdit) -> None:
        new = editor.toPlainText()
        old = self._initial_text_values.pop(fi["name"], fi["initial_value"])
        if new != old:
            fi["value"]         = new
            fi["initial_value"] = new
            self.field_committed.emit(fi["page"], fi["name"], new, old, "text")

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # Viewport resize → resize overlay immediately, then schedule a deferred
        # position recalc.  Our filter runs BEFORE QPdfView handles the event, so
        # the layout (and FitToWidth zoom) hasn't been recalculated yet.  The
        # timer fires in the next event-loop pass, after QPdfView's synchronous
        # layout is done and the scroll-bar ranges are up-to-date.
        if obj is self._view.viewport():
            if event.type() == QEvent.Type.Resize:
                self.resize(event.size())
                self._schedule_update()
            return False
        # FocusIn/Out may arrive on the outer QTextEdit or its viewport
        # depending on the platform; check both.
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            for fi in self._fields:
                qw = fi.get("qwidget")
                if isinstance(qw, QTextEdit) and obj in (qw, qw.viewport()):
                    if event.type() == QEvent.Type.FocusIn:
                        self._initial_text_values.setdefault(fi["name"], qw.toPlainText())
                    else:
                        self._text_finished(fi, qw)
                    break
        return False

    def flush_text_fields(self) -> None:
        """Force-commit any text field whose displayed value differs from the
        last committed value. Call this before saving so edits in an active
        (still-focused) field are not missed."""
        for fi in self._fields:
            qw = fi.get("qwidget")
            if not isinstance(qw, QTextEdit):
                continue
            current = qw.toPlainText()
            if current != str(fi.get("value", "") or ""):
                self._text_finished(fi, qw)

    def paintEvent(self, event) -> None:
        pass   # fully transparent


# ---------------------------------------------------------------------------
# Per-tab document widget
# ---------------------------------------------------------------------------

class _PDFTabWidget(QWidget):
    """One tab in the PDF viewer.

    Owns its own QPdfDocument (loaded from a QBuffer — no file handle),
    QPdfView, QPdfSearchModel, QPdfBookmarkModel, and optionally a
    fitz.Document for form fill / annotation support.
    """

    page_changed   = pyqtSignal(int, int)   # current_page (0-based), page_count
    forms_detected = pyqtSignal(bool)
    undo_changed   = pyqtSignal(bool, bool) # can_undo, can_redo
    thumb_ready    = pyqtSignal(int, QPixmap)
    write_error    = pyqtSignal(str)        # emitted when _write_pdf_to_path fails

    def __init__(self, settings, thumbs_dir: Path, pool: QThreadPool,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._settings   = settings
        self._thumbs_dir = thumbs_dir
        self._pool       = pool

        self.path:       str  = ""
        self._has_forms: bool = False

        # Undo stack: list of {page, name, old, new, ftype}
        self._undo_stack: List[Dict[str, Any]] = []
        self._undo_index: int = -1
        self._last_write_error: Optional[Exception] = None
        # True once any field is committed this session; cleared only on
        # close_document() or a fresh load() — used for the tab dot and
        # the close-prompt in Phase 4.
        self._dirty: bool = False

        # Thumbnail cache
        self._thumb_pixmaps: Dict[int, QPixmap] = {}
        self._thumb_pending: set = set()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        if _PDF_OK:
            self._doc            = QPdfDocument(self)
            self._bookmark_model = QPdfBookmarkModel(self)
            self._search_model   = QPdfSearchModel(self)
            self._search_model.setDocument(self._doc)
            self._bookmark_model.setDocument(self._doc)

            self._view = QPdfView(self)
            self._view.setDocument(self._doc)
            self._view.setPageMode(QPdfView.PageMode.MultiPage)
            if hasattr(self._view, "setTextSelectionEnabled"):
                self._view.setTextSelectionEnabled(True)
            if hasattr(self._view, "setSearchModel"):
                self._view.setSearchModel(self._search_model)
            self._view.pageNavigator().currentPageChanged.connect(
                self._on_page_changed)
            lay.addWidget(self._view)

            # Form overlay (always created; only shown for form PDFs)
            self._overlay = _FormOverlay(self._view, self._doc)
            self._overlay.field_committed.connect(self._on_field_committed)
            self._overlay.any_field_modified.connect(self._on_any_field_modified)
        else:
            lbl = QLabel("PDF support requires PyQt6 6.4+.\n\nRun:  pip install PyQt6>=6.4.0")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color:#7A7890; font-size:14px;")
            lay.addWidget(lbl)
            self._overlay = None

        self._buf: Optional[QBuffer] = None
        self._fitz_doc: Optional[Any] = None
        self._pending_restore_page: int = 0

    # ------------------------------------------------------------------
    # Load / close
    # ------------------------------------------------------------------

    def load(self, path: str) -> bool:
        if not _PDF_OK or not Path(path).exists():
            return False

        # Read saved page BEFORE loading — doc.load fires currentPageChanged(0)
        # synchronously which would call _on_page_changed and overwrite the
        # in-memory value.  Read from the dedicated JSON instead of settings
        # so the lookup is always from disk and unaffected by lifecycle timing.
        norm_path  = path.replace("\\", "/")
        _pages     = _read_pdf_pages(self._settings)
        saved_page = _pages.get(norm_path, _pages.get(path, 0))

        try:
            raw = Path(path).read_bytes()
        except OSError:
            return False

        self._buf = QBuffer(self)
        self._buf.setData(QByteArray(raw))
        self._buf.open(QIODevice.OpenModeFlag.ReadOnly)
        self._doc.load(self._buf)
        if self._doc.pageCount() == 0:
            self._buf.close()
            return False

        self.path = path
        self._dirty = False
        self._bookmark_model.setDocument(self._doc)
        self._search_model.setDocument(self._doc)

        # Open fitz for form support
        self._has_forms = False
        if _FITZ_OK:
            try:
                self._fitz_doc = fitz.open(path)
                _interactive = {
                    getattr(fitz, "PDF_WIDGET_TYPE_TEXT",       7),
                    getattr(fitz, "PDF_WIDGET_TYPE_CHECKBOX",   2),
                    getattr(fitz, "PDF_WIDGET_TYPE_RADIOBUTTON",5),
                    getattr(fitz, "PDF_WIDGET_TYPE_COMBOBOX",   3),
                    getattr(fitz, "PDF_WIDGET_TYPE_LISTBOX",    4),
                }
                self._has_forms = any(
                    w.field_type in _interactive
                    for pg in self._fitz_doc
                    for w in pg.widgets()
                )
            except Exception:
                self._fitz_doc = None

        self.forms_detected.emit(self._has_forms)

        # Load overlay widgets after a short delay so QPdfView is sized first
        if self._has_forms and self._overlay is not None:
            QTimer.singleShot(200, lambda: self._overlay.load_fields(self._fitz_doc))

        # Store the page to restore and schedule an attempt.  The timer only
        # fires the jump when this tab is visible (i.e. it is the active tab).
        # If the tab is hidden (background tab in a multi-tab restore), the
        # timer leaves _pending_restore_page intact so _on_tab_changed can
        # restore it the first time the user switches to this tab.
        self._pending_restore_page = saved_page
        if saved_page:
            QTimer.singleShot(150, self._try_restore_pending_page)

        return True

    def _try_restore_pending_page(self) -> None:
        """Jump to the pending restore page only when this tab is visible."""
        if self._pending_restore_page <= 0:
            return
        if not self.isVisible():
            return  # Background tab — leave pending for _on_tab_changed
        pg = self._pending_restore_page
        self._pending_restore_page = 0
        self._jump_to(pg)

    def _jump_to(self, page: int) -> None:
        if not _PDF_OK or not self.path:
            return
        page = max(0, min(page, self._doc.pageCount() - 1))
        self._view.pageNavigator().jump(page, QPointF())

    def close_document(self) -> None:
        if self._overlay is not None:
            self._overlay.clear()
        if self._fitz_doc is not None:
            try:
                self._fitz_doc.close()
            except Exception:
                pass
            self._fitz_doc = None
        if _PDF_OK:
            self._doc.close()
        if self._buf:
            self._buf.close()
            self._buf = None
        self.path = ""
        self._dirty = False
        self._has_forms = False
        self._pending_restore_page = 0
        self._undo_stack.clear()
        self._undo_index = -1
        self._thumb_pixmaps.clear()
        self._thumb_pending.clear()

    # ------------------------------------------------------------------
    # Page navigation
    # ------------------------------------------------------------------

    def go_to_page(self, page: int) -> None:
        if not _PDF_OK or not self.path:
            return
        page = max(0, min(page, self._doc.pageCount() - 1))
        self._view.pageNavigator().jump(page, QPointF())

    def current_page(self) -> int:
        if not _PDF_OK or not self.path:
            return 0
        return self._view.pageNavigator().currentPage()

    def page_count(self) -> int:
        if not _PDF_OK or not self.path:
            return 0
        return self._doc.pageCount()

    def _on_page_changed(self, page: int) -> None:
        if not self.path:
            return
        count = self._doc.pageCount()
        self.page_changed.emit(page, count)
        # Persist to the dedicated JSON immediately — normalise to forward
        # slashes so paths written on Windows match regardless of how the
        # path string was originally obtained.
        _pages = _read_pdf_pages(self._settings)
        _pages[self.path.replace("\\", "/")] = page
        _write_pdf_pages(self._settings, _pages)
        # Ensure overlay stays on top when page changes
        if self._overlay is not None and self._overlay.isVisible():
            self._overlay.raise_()

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def set_zoom_mode(self, mode: str, spin_value: int = 100) -> None:
        if not _PDF_OK:
            return
        if mode == "width":
            self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        elif mode == "page":
            self._view.setZoomMode(QPdfView.ZoomMode.FitInView)
        elif mode == "auto":
            self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        elif mode == "height":
            self._apply_fit_height()
        elif mode == "custom":
            self._view.setZoomMode(QPdfView.ZoomMode.Custom)
            self._view.setZoomFactor(spin_value / 100.0)
        # For Custom zoom and FitHeight, zoomFactorChanged fires synchronously
        # after setZoomFactor, so the overlay's _on_zoom_changed handles it.
        # For FitToWidth / FitInView, zoomFactorChanged fires after layout.

    def _apply_fit_height(self) -> None:
        if not _PDF_OK or not self.path:
            return
        page    = self._view.pageNavigator().currentPage()
        page_sz = self._doc.pagePointSize(page)
        if page_sz.isEmpty():
            return
        view_h = self._view.viewport().height()
        factor = view_h / (page_sz.height() * 96 / 72)
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(factor)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def set_search_string(self, text: str) -> None:
        if _PDF_OK:
            self._search_model.setSearchString(text)

    def navigate_search(self, direction: int, reset: bool = False) -> tuple:
        if not _PDF_OK:
            return (0, 0, None)
        count = self._search_model.rowCount(QModelIndex())
        if not count:
            return (0, 0, None)
        if reset:
            self._search_idx = 0
        else:
            if not hasattr(self, "_search_idx"):
                self._search_idx = 0
            self._search_idx = (self._search_idx + direction) % count
        idx  = self._search_model.index(self._search_idx, 0)
        link = idx.data(QPdfSearchModel.Role.ResultLink)
        if link:
            self._view.pageNavigator().jump(link.page(), link.location())
        return (self._search_idx, count, link)

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------

    def populate_thumb_list(self, thumb_list: QListWidget) -> None:
        thumb_list.clear()
        if not _PDF_OK or not self.path:
            return
        count = self._doc.pageCount()
        for p in range(count):
            item = QListWidgetItem()
            item.setData(_ROLE_PAGE, p)
            item.setData(_ROLE_PIX, self._thumb_pixmaps.get(p))
            thumb_list.addItem(item)
        self.load_visible_thumbs(thumb_list)

    def load_visible_thumbs(self, thumb_list: QListWidget) -> None:
        if not self.path:
            return
        vr  = thumb_list.viewport().rect()
        top = thumb_list.indexAt(vr.topLeft())
        bot = thumb_list.indexAt(vr.bottomRight())
        t   = top.row() if top.isValid() else 0
        b   = bot.row() if bot.isValid() else min(t + 8, thumb_list.count() - 1)
        for p in range(max(0, t - 2), min(thumb_list.count(), b + 4)):
            self._request_thumb(p)

    def _request_thumb(self, page: int) -> None:
        if page in self._thumb_pixmaps or page in self._thumb_pending:
            return
        if not self.path:
            return
        try:
            cache_file = str(
                self._thumbs_dir / _thumb_cache_key(self.path, page, _THUMB_W))
        except OSError:
            return
        self._thumb_pending.add(page)
        w = _ThumbnailWorker(self.path, page, _THUMB_W, cache_file)
        w.signals.ready.connect(self._on_thumb_ready)
        self._pool.start(w)

    def _on_thumb_ready(self, path: str, page: int, pix: QPixmap) -> None:
        if path != self.path:
            return
        self._thumb_pixmaps[page] = pix
        self._thumb_pending.discard(page)
        self.thumb_ready.emit(page, pix)

    # ------------------------------------------------------------------
    # Form fill — overlay-driven
    # ------------------------------------------------------------------

    def set_overlay_visible(self, visible: bool) -> None:
        if self._overlay is None:
            return
        if visible and self._has_forms:
            self._overlay.show()
            self._overlay.raise_()
            self._overlay.update_positions()
        else:
            self._overlay.hide()

    def _on_field_committed(self, page: int, name: str,
                             new_val: Any, old_val: Any, ftype: str) -> None:
        """Slot: a form field was edited in the overlay."""
        if not _FITZ_OK or self._fitz_doc is None:
            return
        try:
            fitz_page = self._fitz_doc[page]
            for widget in fitz_page.widgets():
                if widget.field_name == name:
                    widget.field_value = new_val
                    widget.update()
                    break
        except Exception as exc:
            self._last_write_error = exc
            self.write_error.emit(f"Could not update field '{name}': {exc}")
            return

        # Push undo entry
        self._undo_stack = self._undo_stack[:self._undo_index + 1]
        self._undo_stack.append({
            "page": page, "name": name,
            "old": old_val, "new": new_val, "ftype": ftype,
        })
        self._undo_index = len(self._undo_stack) - 1
        self._dirty = True
        self.undo_changed.emit(self.can_undo(), self.can_redo())

    def _on_any_field_modified(self) -> None:
        """Fired on every keystroke in a text field — sets dirty immediately."""
        if not self._dirty:
            self._dirty = True
            self.undo_changed.emit(self.can_undo(), self.can_redo())

    def _write_pdf_to_path(self, dest_path: str) -> bool:
        """Write the current fitz document to *dest_path* and reload the display.

        Uses fitz_doc.save() to a file (more reliable than tobytes() for
        capturing in-memory widget modifications on all pymupdf versions).
        For overwrites, saves to a temp file first then os.replace() to avoid
        the Windows file-handle conflict.

        Returns True on success. On failure stores the exception in
        self._last_write_error, emits write_error(str), and returns False.
        """
        if not _FITZ_OK or self._fitz_doc is None or not self.path:
            return False
        try:
            same_file = Path(dest_path).resolve() == Path(self.path).resolve()

            if same_file:
                # Can't write to the file fitz already has open on Windows.
                # garbage=2 (compact xref) is safe for form PDFs; garbage=4
                # (remove duplicates) is too aggressive and can produce files
                # that cause pymupdf to hang on reload.
                tmp = Path(dest_path + ".tmp")
                self._fitz_doc.save(str(tmp), garbage=2, deflate=True)
                # Close to release the Windows file handle.  Set to None
                # immediately so any exception below leaves the doc recoverable.
                self._fitz_doc.close()
                self._fitz_doc = None
                # Write bytes directly to the destination.  os.replace /
                # MoveFileExW fails with WinError 5 when Windows Explorer's
                # preview pane holds the file without FILE_SHARE_DELETE.
                # write_bytes only requires write access and works in that case.
                try:
                    Path(dest_path).write_bytes(tmp.read_bytes())
                except Exception:
                    # Write failed — reopen original so the tab stays usable
                    try:
                        self._fitz_doc = fitz.open(dest_path)
                    except Exception:
                        pass
                    raise
                finally:
                    try:
                        tmp.unlink(missing_ok=True)
                    except Exception:
                        pass
                self._fitz_doc = fitz.open(dest_path)
            else:
                # Different destination — no handle conflict.
                self._fitz_doc.save(dest_path, garbage=2, deflate=True)

            # Read back the written bytes for the QPdfDocument display layer.
            raw = Path(dest_path).read_bytes()

            saved_page = self.current_page()
            saved_sv   = self._view.verticalScrollBar().value()
            saved_sh   = self._view.horizontalScrollBar().value()

            self._doc.close()
            if self._buf is not None:
                self._buf.close()
            self._buf = QBuffer(self)
            self._buf.setData(QByteArray(raw))
            self._buf.open(QIODevice.OpenModeFlag.ReadOnly)
            self._doc.load(self._buf)
            self._view.pageNavigator().jump(saved_page, QPointF())

            def _restore_scroll() -> None:
                self._view.verticalScrollBar().setValue(saved_sv)
                self._view.horizontalScrollBar().setValue(saved_sh)
                if self._overlay is not None:
                    self._overlay.update_positions()

            QTimer.singleShot(0, _restore_scroll)
            self._last_write_error = None
            return True

        except Exception as exc:
            self._last_write_error = exc
            self.write_error.emit(str(exc))
            return False


    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------

    def can_undo(self) -> bool:
        return self._undo_index >= 0

    def can_redo(self) -> bool:
        return self._undo_index < len(self._undo_stack) - 1

    def is_dirty(self) -> bool:
        """True if any field was committed since this document was loaded."""
        return self._dirty

    def has_unsaved_changes(self) -> bool:
        """True if a close-prompt should be shown for this tab."""
        return self._dirty

    def undo(self) -> None:
        if not self.can_undo():
            return
        entry = self._undo_stack[self._undo_index]
        self._undo_index -= 1
        self._apply_field_value(entry["page"], entry["name"], entry["old"])
        self.undo_changed.emit(self.can_undo(), self.can_redo())

    def redo(self) -> None:
        if not self.can_redo():
            return
        self._undo_index += 1
        entry = self._undo_stack[self._undo_index]
        self._apply_field_value(entry["page"], entry["name"], entry["new"])
        self.undo_changed.emit(self.can_undo(), self.can_redo())

    def _apply_field_value(self, page: int, name: str, value: Any) -> None:
        """Write *value* to fitz + overlay without adding a new undo entry."""
        if not _FITZ_OK or self._fitz_doc is None:
            return
        try:
            fitz_page = self._fitz_doc[page]
            for widget in fitz_page.widgets():
                if widget.field_name == name:
                    widget.field_value = value
                    widget.update()
                    break
        except Exception as exc:
            self._last_write_error = exc
            self.write_error.emit(f"Could not apply field value for '{name}': {exc}")
            return
        if self._overlay is not None:
            self._overlay.update_field_value(name, value)


# ---------------------------------------------------------------------------
# Main PDF viewer window
# ---------------------------------------------------------------------------

class PDFViewerWindow(QDialog):
    """Persistent non-modal PDF viewer with tabs, sidebar, and form fill overlay."""

    def __init__(self, settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings  = settings
        self._pool      = QThreadPool.globalInstance()

        from pathlib import Path as _Path
        config_dir = _Path(settings.pdf_bookmarks_path()).parent
        self._bm_manager = PDFBookmarksManager(config_dir)
        legacy = settings.pdf("user_bookmarks") or {}
        if legacy:
            self._bm_manager.migrate_from_settings(legacy)
            settings.set_pdf("user_bookmarks", {})
            settings.save()

        self.setWindowTitle("PDF Viewer")
        self.setMinimumSize(500, 360)
        self.setWindowModality(Qt.WindowModality.NonModal)
        icon = _tab_close_icon_path()
        self.setStyleSheet(_SS + f"""
QTabBar::close-button {{
    image: url("{icon}");
    subcontrol-position: right;
    width: 10px; height: 10px;
    margin-left: 4px;
    border-radius: 2px;
}}
QTabBar::close-button:hover {{ background: #524E48; }}
""")
        self.setObjectName("pdf_root")

        self._build_ui()
        self._restore_state()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        self._search_bar = self._build_search_bar()
        self._search_bar.setVisible(False)
        root.addWidget(self._search_bar)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(3)
        self._splitter.addWidget(self._build_sidebar())

        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.tabCloseRequested.connect(self._close_tab)
        self._prev_tab_index:   int  = 0
        self._tab_switch_guard: bool = False
        self._tab_widget.currentChanged.connect(self._on_tab_about_to_change)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._splitter.addWidget(self._tab_widget)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        root.addWidget(self._splitter)

        root.addWidget(self._build_status_bar())

        self._tab_widget.addTab(self._make_blank_tab(), "New Tab")

        from PyQt6.QtGui import QShortcut
        QShortcut(QKeySequence("Ctrl+F"),         self).activated.connect(self._toggle_search)
        QShortcut(QKeySequence("Ctrl+O"),         self).activated.connect(self._open_file_dialog)
        QShortcut(QKeySequence("Escape"),         self).activated.connect(self._on_escape)
        QShortcut(QKeySequence("Ctrl+T"),         self).activated.connect(self._new_blank_tab)
        QShortcut(QKeySequence("Ctrl+W"),         self).activated.connect(
            lambda: self._close_tab(self._tab_widget.currentIndex()))
        QShortcut(QKeySequence("Ctrl+Tab"),       self).activated.connect(self._next_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self).activated.connect(self._prev_tab)
        QShortcut(QKeySequence("Ctrl+Z"),         self).activated.connect(self._undo)
        QShortcut(QKeySequence("Ctrl+Y"),         self).activated.connect(self._redo)
        QShortcut(QKeySequence("Ctrl+S"),         self).activated.connect(self._save_as)
        QShortcut(QKeySequence("Ctrl+Shift+S"),   self).activated.connect(self._save_overwrite)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet("background:#1E1F28; border-bottom:1px solid #4B4D63;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)

        def tb(icon_name: str, tip: str, checkable: bool = False) -> QToolButton:
            b = QToolButton()
            b.setIcon(_icon(icon_name))
            b.setToolTip(tip)
            b.setFixedSize(32, 32)
            b.setCheckable(checkable)
            return b

        def sep() -> QFrame:
            f = QFrame()
            f.setFrameShape(QFrame.Shape.VLine)
            f.setStyleSheet("color:#4B4D63;")
            return f

        self._btn_open   = tb("fa5s.folder-open", "Open PDF (Ctrl+O)")
        self._btn_recent = tb("fa5s.history",      "Recent PDFs")
        self._btn_open.clicked.connect(self._open_file_dialog)
        self._btn_recent.clicked.connect(self._show_recent)
        lay.addWidget(self._btn_open)
        lay.addWidget(self._btn_recent)
        lay.addWidget(sep())

        self._btn_prev   = tb("fa5s.chevron-up",   "Previous Page")
        self._btn_next   = tb("fa5s.chevron-down", "Next Page")
        self._page_label = QLabel("— / —")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setFixedWidth(72)
        self._btn_prev.clicked.connect(self._prev_page)
        self._btn_next.clicked.connect(self._next_page)
        lay.addWidget(self._btn_prev)
        lay.addWidget(self._page_label)
        lay.addWidget(self._btn_next)
        lay.addWidget(sep())

        self._zoom_btns: Dict[str, QToolButton] = {}
        for mode, icon_name, tip in [
            ("width",  "fa5s.arrows-alt-h",      "Fit to Width"),
            ("height", "fa5s.arrows-alt-v",      "Fit to Height"),
            ("page",   "fa5s.compress-alt",      "Fit Page"),
            ("auto",   "fa5s.expand-arrows-alt", "Auto Scale"),
        ]:
            b = tb(icon_name, tip, checkable=True)
            b.clicked.connect(lambda _, m=mode: self._set_zoom_mode(m))
            self._zoom_btns[mode] = b
            lay.addWidget(b)

        lay.addWidget(sep())
        self._zoom_spin = _make_spin(25, 500, 100, "%")
        self._zoom_spin.setFixedWidth(72)
        self._zoom_spin.setToolTip("Zoom percentage")
        self._zoom_spin.valueChanged.connect(self._on_zoom_spin)
        lay.addWidget(self._zoom_spin)
        lay.addWidget(sep())

        self._btn_undo = tb("fa5s.undo", "Undo (Ctrl+Z)")
        self._btn_redo = tb("fa5s.redo", "Redo (Ctrl+Y)")
        self._btn_undo.clicked.connect(self._undo)
        self._btn_redo.clicked.connect(self._redo)
        self._btn_undo.setEnabled(False)
        self._btn_redo.setEnabled(False)
        lay.addWidget(self._btn_undo)
        lay.addWidget(self._btn_redo)
        lay.addWidget(sep())

        self._btn_save = tb("fa5s.save", "Save As… (Ctrl+S)")
        self._btn_save.clicked.connect(self._save_as)
        self._btn_save.setEnabled(False)
        lay.addWidget(self._btn_save)
        lay.addWidget(sep())

        # Search / Sidebar / Form-fill overlay toggle
        self._btn_search   = tb("fa5s.search",         "Search (Ctrl+F)", checkable=True)
        self._btn_sidebar  = tb("fa5s.columns",        "Toggle Sidebar",  checkable=True)
        self._btn_formfill = tb("fa5s.clipboard-list", "Toggle Form Fields Overlay",
                                checkable=True)
        self._btn_search.clicked.connect(self._toggle_search)   # single connection
        self._btn_sidebar.setChecked(True)
        self._btn_sidebar.clicked.connect(self._toggle_sidebar)
        self._btn_formfill.clicked.connect(self._toggle_overlay)
        self._btn_formfill.setVisible(False)
        lay.addWidget(self._btn_search)
        lay.addWidget(self._btn_sidebar)
        lay.addWidget(self._btn_formfill)

        lay.addStretch()
        self._title_label = QLabel("")
        self._title_label.setStyleSheet("color:#7A7890; font-size:11px;")
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._title_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._title_label)
        return bar

    def _build_sidebar(self) -> QWidget:
        self._sidebar = QWidget()
        self._sidebar.setObjectName("pdf_root")
        self._sidebar.setMinimumWidth(0)
        self._sidebar.setStyleSheet("background:#1E1F28;")

        outer = QVBoxLayout(self._sidebar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        toggle_row = QWidget()
        toggle_row.setFixedHeight(36)
        toggle_row.setStyleSheet(
            "background:#292A35; border-bottom:1px solid #4B4D63;")
        tr_lay = QHBoxLayout(toggle_row)
        tr_lay.setContentsMargins(4, 3, 4, 3)
        tr_lay.setSpacing(2)

        self._panel_btns: Dict[str, QToolButton] = {}
        for panel, icon_name, tip in [
            ("outlines",   "fa5s.list-alt", "Document Outline"),
            ("bookmarks",  "fa5s.bookmark", "My Bookmarks"),
            ("thumbnails", "fa5s.th-large", "Page Thumbnails"),
        ]:
            b = QToolButton()
            b.setIcon(_icon(icon_name))
            b.setToolTip(tip)
            b.setFixedSize(28, 28)
            b.setCheckable(True)
            b.clicked.connect(lambda _, p=panel: self._switch_panel(p))
            self._panel_btns[panel] = b
            tr_lay.addWidget(b)

        tr_lay.addStretch()
        self._btn_collapse = QToolButton()
        self._btn_collapse.setIcon(_icon("fa5s.chevron-left"))
        self._btn_collapse.setToolTip("Collapse sidebar")
        self._btn_collapse.setFixedSize(24, 28)
        self._btn_collapse.clicked.connect(self._toggle_sidebar)
        tr_lay.addWidget(self._btn_collapse)
        outer.addWidget(toggle_row)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # 0: Outlines
        self._outline_view = QTreeView()
        self._outline_view.setHeaderHidden(True)
        self._outline_view.activated.connect(self._on_outline_activated)
        self._stack.addWidget(self._outline_view)

        # 1: User bookmarks
        bm_widget = QWidget()
        bm_widget.setObjectName("pdf_root")
        bm_lay = QVBoxLayout(bm_widget)
        bm_lay.setContentsMargins(4, 4, 4, 4)
        bm_lay.setSpacing(4)
        self._bm_list = QListWidget()
        self._bm_list.itemDoubleClicked.connect(self._on_user_bm_activated)
        self._bm_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bm_list.customContextMenuRequested.connect(self._on_bm_context_menu)
        bm_lay.addWidget(self._bm_list)
        bm_btn_row = QHBoxLayout()
        add_bm = QPushButton(_icon("fa5s.plus"),  "Add")
        del_bm = QPushButton(_icon("fa5s.trash"), "Remove")
        add_bm.clicked.connect(self._add_user_bookmark)
        del_bm.clicked.connect(self._remove_user_bookmark)
        bm_btn_row.addWidget(add_bm)
        bm_btn_row.addWidget(del_bm)
        bm_lay.addLayout(bm_btn_row)
        self._stack.addWidget(bm_widget)

        # 2: Thumbnails
        self._thumb_list = QListWidget()
        self._thumb_list.setItemDelegate(_ThumbDelegate())
        self._thumb_list.setSpacing(4)
        self._thumb_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._thumb_list.itemClicked.connect(self._on_thumb_clicked)
        self._thumb_list.verticalScrollBar().valueChanged.connect(
            self._on_thumb_scroll)
        self._stack.addWidget(self._thumb_list)

        self._panel_idx = {"outlines": 0, "bookmarks": 1, "thumbnails": 2}
        return self._sidebar

    def _build_search_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background:#1E1F28; border-bottom:1px solid #4B4D63;")
        bar.setFixedHeight(40)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search…")
        self._search_input.setFixedWidth(220)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_input.returnPressed.connect(lambda: self._navigate_search(1))

        self._search_count = QLabel("")
        self._search_count.setStyleSheet("color:#7A7890;")
        self._search_count.setFixedWidth(80)

        btn_prev  = QPushButton(_icon("fa5s.chevron-up"),   "")
        btn_next  = QPushButton(_icon("fa5s.chevron-down"), "")
        btn_close = QPushButton(_icon("fa5s.times"),        "")
        for b in (btn_prev, btn_next, btn_close):
            b.setFixedSize(28, 28)
        btn_prev.setToolTip("Previous result")
        btn_next.setToolTip("Next result")
        btn_close.setToolTip("Close search (Esc)")
        btn_prev.clicked.connect(lambda: self._navigate_search(-1))
        btn_next.clicked.connect(lambda: self._navigate_search(1))
        btn_close.clicked.connect(self._close_search)

        lay.addWidget(QLabel("Find:"))
        lay.addWidget(self._search_input)
        lay.addWidget(btn_prev)
        lay.addWidget(btn_next)
        lay.addWidget(self._search_count)
        lay.addStretch()
        lay.addWidget(btn_close)
        return bar

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(24)
        bar.setStyleSheet("background:#1E1F28; border-top:1px solid #4B4D63;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color:#7A7890; font-size:11px;")
        lay.addWidget(self._status_label)
        lay.addStretch()
        return bar

    # ------------------------------------------------------------------
    # Tab helpers
    # ------------------------------------------------------------------

    @property
    def _current_tab(self) -> Optional[_PDFTabWidget]:
        w = self._tab_widget.currentWidget()
        return w if isinstance(w, _PDFTabWidget) else None

    def _is_blank_tab(self, index: int) -> bool:
        return not isinstance(self._tab_widget.widget(index), _PDFTabWidget)

    def _make_blank_tab(self) -> QWidget:
        w = QWidget()
        w.setObjectName("pdf_root")
        w.setStyleSheet("background:#1E1F28;")
        lay = QVBoxLayout(w)
        lbl = QLabel(
            "Open a PDF to get started\n\n"
            "Ctrl+O  —  Open file\n"
            "Ctrl+T  —  New tab"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color:#3B3C4F; font-size:14px;")
        lay.addWidget(lbl)
        return w

    def _new_blank_tab(self) -> None:
        idx = self._tab_widget.addTab(self._make_blank_tab(), "New Tab")
        self._tab_widget.setCurrentIndex(idx)

    def _close_tab(self, index: int) -> None:
        w = self._tab_widget.widget(index)
        if isinstance(w, _PDFTabWidget) and w.has_unsaved_changes():
            self._tab_widget.setCurrentIndex(index)
            if not self._prompt_save_tab(w):
                return  # user cancelled — leave tab open
        if isinstance(w, _PDFTabWidget):
            w.close_document()
            w.deleteLater()
        self._tab_widget.removeTab(index)
        if self._tab_widget.count() == 0:
            self._tab_widget.addTab(self._make_blank_tab(), "New Tab")

    def _on_tab_about_to_change(self, new_index: int) -> None:
        """Fires on currentChanged — prompts to save if the previous tab is dirty."""
        if self._tab_switch_guard:
            return
        prev = self._prev_tab_index
        self._prev_tab_index = new_index
        if prev == new_index:
            return
        prev_tab = self._tab_widget.widget(prev)
        if not isinstance(prev_tab, _PDFTabWidget):
            return
        if not prev_tab.has_unsaved_changes():
            return
        if not self._prompt_save_tab(prev_tab):
            # User cancelled — revert to the previous tab
            self._tab_switch_guard = True
            self._tab_widget.setCurrentIndex(prev)
            self._tab_switch_guard = False
            self._prev_tab_index = prev

    def _on_tab_changed(self, index: int) -> None:
        self._refresh_sidebar_for_current_tab()
        self._update_toolbar_for_current_tab()
        # Restore any pending page for the tab that just became visible.
        # This handles background tabs whose 150ms timer fired while hidden.
        tab = self._current_tab
        if tab is not None and tab._pending_restore_page > 0:
            pg = tab._pending_restore_page
            tab._pending_restore_page = 0
            QTimer.singleShot(100, lambda p=pg, t=tab: t._jump_to(p))
        # Re-route search model signals to the newly active tab
        tab = self._current_tab
        if tab is not None:
            try:
                tab._search_model.rowsInserted.disconnect(self._on_search_results_changed)
                tab._search_model.modelReset.disconnect(self._on_search_results_changed)
            except Exception:
                pass
            tab._search_model.rowsInserted.connect(self._on_search_results_changed)
            tab._search_model.modelReset.connect(self._on_search_results_changed)

    def _next_tab(self) -> None:
        n = self._tab_widget.count()
        if n > 1:
            self._tab_widget.setCurrentIndex(
                (self._tab_widget.currentIndex() + 1) % n)

    def _prev_tab(self) -> None:
        n = self._tab_widget.count()
        if n > 1:
            self._tab_widget.setCurrentIndex(
                (self._tab_widget.currentIndex() - 1) % n)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _open_file_dialog(self) -> None:
        tab = self._current_tab
        start = str(Path(tab.path).parent) if (tab and tab.path) else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", start, "PDF Files (*.pdf)")
        if path:
            self._load_pdf(path)

    def _load_pdf(self, path: str) -> None:
        if not Path(path).exists():
            return

        # Switch to existing tab if already open
        for i in range(self._tab_widget.count()):
            w = self._tab_widget.widget(i)
            if isinstance(w, _PDFTabWidget) and w.path == path:
                self._tab_widget.setCurrentIndex(i)
                return

        # Reuse current blank tab or create new tab
        current_idx = self._tab_widget.currentIndex()
        if self._is_blank_tab(current_idx):
            tab = _PDFTabWidget(self._settings,
                                self._settings.pdf_thumbs_dir(),
                                self._pool, self)
            self._tab_widget.removeTab(current_idx)
            self._tab_widget.insertTab(current_idx, tab, "Loading…")
            self._tab_widget.setCurrentIndex(current_idx)
        else:
            tab = _PDFTabWidget(self._settings,
                                self._settings.pdf_thumbs_dir(),
                                self._pool, self)
            idx = self._tab_widget.addTab(tab, "Loading…")
            self._tab_widget.setCurrentIndex(idx)

        tab.page_changed.connect(self._on_page_changed)
        tab.forms_detected.connect(self._on_forms_detected)
        tab.undo_changed.connect(self._on_undo_changed)
        tab.thumb_ready.connect(self._on_thumb_ready_from_tab)
        tab.write_error.connect(
            lambda msg: self._status_label.setText(f"Save error: {msg}"))
        tab._search_model.rowsInserted.connect(self._on_search_results_changed)
        tab._search_model.modelReset.connect(self._on_search_results_changed)

        if tab.load(path):
            self._refresh_tab_title(tab)   # uses tab.is_dirty() — always False on fresh load
            title = Path(path).stem
            self._title_label.setText(title)
            count = tab.page_count()
            self._page_label.setText(f"1 / {count}")
            self._status_label.setText(f"{count} pages  •  {Path(path).name}")
            self._add_to_recently_used(path, title)
            self._settings.set_pdf("last_path", path)
            self._settings.save()
            self._set_zoom_mode(self._settings.pdf("zoom_mode") or "auto")
            self._refresh_sidebar_for_current_tab()
            # Enable toolbar buttons now that the document is loaded
            self._update_toolbar_for_current_tab()
        else:
            self._tab_widget.removeTab(self._tab_widget.indexOf(tab))
            tab.deleteLater()
            self._status_label.setText(f"Failed to open: {Path(path).name}")

    # ------------------------------------------------------------------
    # Save operations
    # ------------------------------------------------------------------

    def _prompt_save_tab(self, tab: "_PDFTabWidget") -> bool:
        """Ask the user what to do with unsaved edits in *tab*.

        Returns True  — safe to proceed (saved or discarded).
        Returns False — user cancelled (caller must abort its action).
        """
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Unsaved Changes")
        msg.setText(f"\"{Path(tab.path).name}\" has unsaved form edits.")
        msg.setIcon(QMessageBox.Icon.Question)

        btn_save    = msg.addButton("Save",            QMessageBox.ButtonRole.AcceptRole)
        btn_save_as = msg.addButton("Save As…",        QMessageBox.ButtonRole.ActionRole)
        btn_discard = msg.addButton("Discard Changes", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel  = msg.addButton("Cancel",          QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(btn_save)
        msg.setEscapeButton(btn_cancel)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked is btn_save:
            return self._save_for_tab(tab, overwrite=True)
        if clicked is btn_save_as:
            return self._save_as_for_tab(tab)
        if clicked is btn_discard:
            confirm = QMessageBox.question(
                self, "Confirm Discard",
                "Your edits will be permanently lost. Discard them?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            return confirm == QMessageBox.StandardButton.Discard
        return False   # Cancel or dialog closed via Escape

    def _save_as(self) -> None:
        """Open Save As dialog for the current tab (Ctrl+S)."""
        tab = self._current_tab
        if tab is None or not tab.path:
            return
        self._save_as_for_tab(tab)

    def _save_overwrite(self) -> None:
        """Overwrite the current file without a dialog (Ctrl+Shift+S)."""
        tab = self._current_tab
        if tab is None or not tab.path:
            return
        self._save_for_tab(tab, overwrite=True)

    def _save_as_for_tab(self, tab: "_PDFTabWidget") -> bool:
        """Open Save As dialog for *tab*. Returns True if the user saved."""
        start_dir  = str(Path(tab.path).parent)
        start_name = Path(tab.path).name
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save PDF As",
            str(Path(start_dir) / start_name),
            "PDF Files (*.pdf)",
        )
        if not dest:
            return False
        return self._save_for_tab(tab, dest=dest, overwrite=(dest == tab.path))

    def _save_for_tab(self, tab: "_PDFTabWidget", dest: str = "",
                      overwrite: bool = False) -> bool:
        """Write *tab* to *dest* (defaults to tab.path when overwrite=True).

        Updates tab state on success. Shows an error dialog on failure.
        Returns True on success, False on failure or cancel.
        """
        if not dest:
            dest = tab.path
        # Flush any text field that is still active so its value reaches fitz
        # before the document is written (guards against Ctrl+S mid-edit).
        if tab._overlay is not None:
            tab._overlay.flush_text_fields()
        ok = tab._write_pdf_to_path(dest)
        if not ok:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Save Failed",
                f"Could not save '{Path(dest).name}':\n{tab._last_write_error}",
            )
            return False

        # Update tab path if saved to a new location
        if dest != tab.path:
            tab.path = dest

        # Clear dirty flag — explicit save
        tab._dirty = False
        self._refresh_tab_title(tab)
        self._add_to_recently_used(dest, Path(dest).stem)
        self._settings.set_pdf("last_path", dest)
        self._settings.save()
        self._status_label.setText(f"Saved: {Path(dest).name}")
        return True

    # ------------------------------------------------------------------
    # Recently used
    # ------------------------------------------------------------------

    def _add_to_recently_used(self, path: str, title: str) -> None:
        recent: List[Dict] = list(self._settings.pdf("recently_used") or [])
        recent = [r for r in recent if r.get("path") != path]
        recent.insert(0, {"path": path, "title": title})
        recent = recent[:_MAX_RECENT]
        self._settings.set_pdf("recently_used", recent)

    def _show_recent(self) -> None:
        recent = self._settings.pdf("recently_used") or []
        if not recent:
            return
        dlg = _RecentDialog(recent, self._settings.pdf_thumbs_dir(), self)
        dlg.pdf_chosen.connect(self._load_pdf)
        dlg.exec()

    # ------------------------------------------------------------------
    # Page navigation
    # ------------------------------------------------------------------

    def _prev_page(self) -> None:
        tab = self._current_tab
        if tab:
            tab.go_to_page(tab.current_page() - 1)

    def _next_page(self) -> None:
        tab = self._current_tab
        if tab:
            tab.go_to_page(tab.current_page() + 1)

    def _on_page_changed(self, page: int, count: int) -> None:
        self._page_label.setText(f"{page + 1} / {count}")
        if self._thumb_list.count() > page:
            self._thumb_list.setCurrentRow(page)
            self._thumb_list.scrollToItem(
                self._thumb_list.item(page),
                QListWidget.ScrollHint.EnsureVisible)

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def _set_zoom_mode(self, mode: str) -> None:
        for m, b in self._zoom_btns.items():
            b.setChecked(m == mode)
        self._settings.set_pdf("zoom_mode", mode)
        spin_enabled = mode == "custom"
        self._zoom_spin.setEnabled(spin_enabled)
        tab = self._current_tab
        if tab:
            tab.set_zoom_mode(mode, self._zoom_spin.value())

    def _on_zoom_spin(self, value: int) -> None:
        for b in self._zoom_btns.values():
            b.setChecked(False)
        self._settings.set_pdf("zoom_mode",   "custom")
        self._settings.set_pdf("zoom_factor", value / 100.0)
        tab = self._current_tab
        if tab:
            tab.set_zoom_mode("custom", value)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _toggle_search(self) -> None:
        visible = not self._search_bar.isVisible()
        self._search_bar.setVisible(visible)
        self._btn_search.setChecked(visible)
        if visible:
            self._search_input.setFocus()
            self._search_input.selectAll()

    def _close_search(self) -> None:
        self._search_bar.setVisible(False)
        self._btn_search.setChecked(False)
        tab = self._current_tab
        if tab:
            tab.set_search_string("")
        self._search_count.setText("")

    def _on_search_text_changed(self, text: str) -> None:
        tab = self._current_tab
        if not tab:
            return
        tab.set_search_string(text)
        if not text:
            self._search_count.setText("")

    def _on_search_results_changed(self) -> None:
        tab = self._current_tab
        if not tab:
            return
        text = self._search_input.text()
        if not text:
            self._search_count.setText("")
            return
        count = tab._search_model.rowCount(QModelIndex())
        if count == 0:
            self._search_count.setText("No results")
        else:
            idx, _, _ = tab.navigate_search(0, reset=True)
            self._search_count.setText(f"1 / {count}")

    def _navigate_search(self, direction: int) -> None:
        tab = self._current_tab
        if not tab:
            return
        count = tab._search_model.rowCount(QModelIndex())
        if not count:
            return
        idx, total, _ = tab.navigate_search(direction)
        self._search_count.setText(f"{idx + 1} / {total}")

    def _on_escape(self) -> None:
        if self._search_bar.isVisible():
            self._close_search()

    # ------------------------------------------------------------------
    # Sidebar / panels
    # ------------------------------------------------------------------

    def _switch_panel(self, panel: str) -> None:
        for p, b in self._panel_btns.items():
            b.setChecked(p == panel)
        self._stack.setCurrentIndex(self._panel_idx[panel])
        self._settings.set_pdf("sidebar_panel", panel)
        if panel == "thumbnails":
            tab = self._current_tab
            if tab:
                tab.load_visible_thumbs(self._thumb_list)

    def _toggle_sidebar(self) -> None:
        collapsed = self._sidebar.width() > 10
        if collapsed:
            self._settings.set_pdf("sidebar_width", self._sidebar.width())
            sizes = self._splitter.sizes()
            self._splitter.setSizes([0, sum(sizes)])
            self._btn_collapse.setIcon(_icon("fa5s.chevron-right"))
            self._btn_collapse.setToolTip("Expand sidebar")
        else:
            saved = self._settings.pdf("sidebar_width") or 220
            total = sum(self._splitter.sizes())
            self._splitter.setSizes([saved, total - saved])
            self._btn_collapse.setIcon(_icon("fa5s.chevron-left"))
            self._btn_collapse.setToolTip("Collapse sidebar")
        self._settings.set_pdf("sidebar_collapsed", collapsed)
        self._btn_sidebar.setChecked(not collapsed)

    def _toggle_overlay(self) -> None:
        tab = self._current_tab
        if tab:
            tab.set_overlay_visible(self._btn_formfill.isChecked())

    def _refresh_sidebar_for_current_tab(self) -> None:
        tab = self._current_tab
        if tab is None:
            self._page_label.setText("— / —")
            self._title_label.setText("")
            self._status_label.setText("")
            self._bm_list.clear()
            self._thumb_list.clear()
            return

        self._outline_view.setModel(tab._bookmark_model)
        self._refresh_user_bookmarks()
        tab.populate_thumb_list(self._thumb_list)

        count = tab.page_count()
        page  = tab.current_page()
        self._page_label.setText(f"{page + 1} / {count}")
        self._title_label.setText(Path(tab.path).stem if tab.path else "")
        self._status_label.setText(
            f"{count} pages  •  {Path(tab.path).name}" if tab.path else "")

    def _refresh_tab_title(self, tab: Optional["_PDFTabWidget"]) -> None:
        """Update the tab label to show a • prefix when the tab is dirty."""
        if tab is None:
            return
        idx  = self._tab_widget.indexOf(tab)
        if idx < 0:
            return
        name = Path(tab.path).stem if tab.path else "New Tab"
        self._tab_widget.setTabText(idx, f"• {name}" if tab.is_dirty() else name)

    def _update_toolbar_for_current_tab(self) -> None:
        tab = self._current_tab
        has_doc = tab is not None and bool(tab.path)
        for b in [self._btn_prev, self._btn_next, self._btn_search]:
            b.setEnabled(has_doc)
        for b in self._zoom_btns.values():
            b.setEnabled(has_doc)
        self._zoom_spin.setEnabled(
            has_doc and (self._settings.pdf("zoom_mode") == "custom"))
        self._btn_undo.setEnabled(bool(tab and tab.can_undo()))
        self._btn_redo.setEnabled(bool(tab and tab.can_redo()))
        self._btn_save.setEnabled(has_doc)
        if not has_doc:
            self._page_label.setText("— / —")
            self._title_label.setText("")
        # Show/hide form fill toggle based on whether current PDF has forms
        has_forms = bool(tab and tab._has_forms)
        self._btn_formfill.setVisible(has_forms)
        if has_forms and tab is not None:
            self._btn_formfill.setChecked(
                tab._overlay is not None and tab._overlay.isVisible())

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------

    def _undo(self) -> None:
        tab = self._current_tab
        if tab and tab.can_undo():
            tab.undo()

    def _redo(self) -> None:
        tab = self._current_tab
        if tab and tab.can_redo():
            tab.redo()

    def _on_undo_changed(self, can_undo: bool, can_redo: bool) -> None:
        self._btn_undo.setEnabled(can_undo)
        self._btn_redo.setEnabled(can_redo)
        self._refresh_tab_title(self._current_tab)

    # ------------------------------------------------------------------
    # Sidebar: outlines
    # ------------------------------------------------------------------

    def _on_outline_activated(self, index: QModelIndex) -> None:
        if not _PDF_OK:
            return
        page = index.data(QPdfBookmarkModel.Role.Page)
        if page is not None:
            tab = self._current_tab
            if tab:
                tab.go_to_page(page)

    # ------------------------------------------------------------------
    # Sidebar: user bookmarks
    # ------------------------------------------------------------------

    def _add_user_bookmark(self) -> None:
        tab = self._current_tab
        if not tab or not tab.path:
            return
        page  = tab.current_page()
        label = f"Page {page + 1}"
        self._bm_manager.add(tab.path, page, label)
        self._refresh_user_bookmarks()

    def _remove_user_bookmark(self) -> None:
        tab = self._current_tab
        if not tab or not tab.path:
            return
        row = self._bm_list.currentRow()
        if row < 0:
            return
        self._bm_manager.remove(tab.path, row)
        self._refresh_user_bookmarks()

    def _refresh_user_bookmarks(self) -> None:
        self._bm_list.clear()
        tab = self._current_tab
        if not tab or not tab.path:
            return
        for e in self._bm_manager.get(tab.path):
            item = QListWidgetItem(f"  pg {e['page'] + 1}  —  {e['label']}")
            item.setData(Qt.ItemDataRole.UserRole, e["page"])
            self._bm_list.addItem(item)

    def _on_user_bm_activated(self, item: QListWidgetItem) -> None:
        page = item.data(Qt.ItemDataRole.UserRole)
        if page is not None:
            tab = self._current_tab
            if tab:
                tab.go_to_page(page)

    def _on_bm_context_menu(self, pos) -> None:
        item = self._bm_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        menu.setStyleSheet(_SS)
        act_rename = menu.addAction("Rename")
        act_remove = menu.addAction("Remove")
        chosen = menu.exec(self._bm_list.mapToGlobal(pos))
        if chosen is act_rename:
            self._rename_bookmark_at(self._bm_list.row(item))
        elif chosen is act_remove:
            self._bm_list.setCurrentItem(item)
            self._remove_user_bookmark()

    def _rename_bookmark_at(self, index: int) -> None:
        tab = self._current_tab
        if not tab or not tab.path:
            return
        entries = self._bm_manager.get(tab.path)
        if index >= len(entries):
            return
        current_label = entries[index]["label"]
        new_label, ok = QInputDialog.getText(
            self, "Rename Bookmark", "Name:", text=current_label)
        if ok and new_label.strip():
            self._bm_manager.rename(tab.path, index, new_label.strip())
            self._refresh_user_bookmarks()

    # ------------------------------------------------------------------
    # Sidebar: thumbnails
    # ------------------------------------------------------------------

    def _on_thumb_scroll(self) -> None:
        tab = self._current_tab
        if tab:
            tab.load_visible_thumbs(self._thumb_list)

    def _on_thumb_clicked(self, item: QListWidgetItem) -> None:
        page = item.data(_ROLE_PAGE)
        if page is not None:
            tab = self._current_tab
            if tab:
                tab.go_to_page(page)

    def _on_thumb_ready_from_tab(self, page: int, pix: QPixmap) -> None:
        if page < self._thumb_list.count():
            item = self._thumb_list.item(page)
            if item:
                item.setData(_ROLE_PIX, pix)
                self._thumb_list.update(
                    self._thumb_list.model().index(page, 0))

    # ------------------------------------------------------------------
    # Form fill
    # ------------------------------------------------------------------

    def _on_forms_detected(self, has_forms: bool) -> None:
        self._btn_formfill.setVisible(has_forms)
        if has_forms:
            # Auto-enable overlay when a form PDF is opened
            self._btn_formfill.setChecked(True)
            tab = self._current_tab
            if tab:
                tab.set_overlay_visible(True)

    # ------------------------------------------------------------------
    # State save / restore
    # ------------------------------------------------------------------

    def _restore_state(self) -> None:
        geom = self._settings.pdf("window_geometry")
        if geom and len(geom) == 4:
            from PyQt6.QtCore import QRect as _QRect
            self.setGeometry(_QRect(geom[0], geom[1], geom[2], geom[3]))

        panel     = self._settings.pdf("sidebar_panel") or "thumbnails"
        # Guard: panel might be "forms" from an older save — fall back
        if panel not in self._panel_idx:
            panel = "thumbnails"
        collapsed = self._settings.pdf("sidebar_collapsed") or False
        width     = self._settings.pdf("sidebar_width") or 220
        self._switch_panel(panel)
        if collapsed:
            self._splitter.setSizes([0, 9000])
            self._btn_collapse.setIcon(_icon("fa5s.chevron-right"))
            self._btn_sidebar.setChecked(False)
        else:
            self._splitter.setSizes([width, 9000 - width])
            self._btn_sidebar.setChecked(True)

        open_tabs  = self._settings.pdf("open_tabs") or []
        active_tab = int(self._settings.pdf("active_tab") or 0)

        if not open_tabs:
            last = self._settings.pdf("last_path") or ""
            if last and Path(last).exists():
                open_tabs = [last]

        # Crash-guard: if a previous load hung or crashed, the flag will still
        # be set. Skip auto-load this time and clear the problematic paths so
        # the app doesn't hang on every subsequent launch.
        if self._settings.pdf("load_in_progress"):
            self._settings.set_pdf("load_in_progress", False)
            self._settings.set_pdf("open_tabs", [])
            self._settings.set_pdf("last_path", "")
            self._settings.save()
            self._status_label.setText(
                "Previous session load did not complete — tab restore skipped.")
            return

        self._settings.set_pdf("load_in_progress", True)
        self._settings.save()

        for path in open_tabs:
            if Path(path).exists():
                self._load_pdf(path)

        self._settings.set_pdf("load_in_progress", False)
        self._settings.save()

        if 0 <= active_tab < self._tab_widget.count():
            self._tab_widget.setCurrentIndex(active_tab)

    def closeEvent(self, event) -> None:
        # Prompt for every dirty tab before closing
        for i in range(self._tab_widget.count()):
            w = self._tab_widget.widget(i)
            if isinstance(w, _PDFTabWidget) and w.has_unsaved_changes():
                self._tab_widget.setCurrentIndex(i)
                if not self._prompt_save_tab(w):
                    event.ignore()
                    return

        open_tabs = []
        for i in range(self._tab_widget.count()):
            w = self._tab_widget.widget(i)
            if isinstance(w, _PDFTabWidget) and w.path:
                open_tabs.append(w.path)

        self._settings.set_pdf("open_tabs",  open_tabs)
        self._settings.set_pdf("active_tab", self._tab_widget.currentIndex())

        sizes = self._splitter.sizes()
        if sizes[0] > 10:
            self._settings.set_pdf("sidebar_width", sizes[0])
        g = self.geometry()
        self._settings.set_pdf("window_geometry",
                               [g.x(), g.y(), g.width(), g.height()])
        self._settings.save()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_spin(min_: int, max_: int, default: int, suffix: str) -> "QSpinBox":
    from PyQt6.QtWidgets import QSpinBox
    s = QSpinBox()
    s.setRange(min_, max_)
    s.setValue(default)
    s.setSuffix(suffix)
    return s
