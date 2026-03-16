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

"""PDF viewer window — persistent, non-modal, themed to match the app."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import qtawesome as qta

from PyQt6.QtCore import (
    QModelIndex, QObject, QPointF, QRunnable, QSize, Qt,
    QThreadPool, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
    QSplitter, QStackedWidget, QStyledItemDelegate, QStyleOptionViewItem,
    QToolButton, QTreeView, QVBoxLayout, QWidget,
)

try:
    from PyQt6.QtPdf import QPdfBookmarkModel, QPdfDocument, QPdfSearchModel
    from PyQt6.QtPdfWidgets import QPdfView
    _PDF_OK = True
except ImportError:
    _PDF_OK = False


# ---------------------------------------------------------------------------
# Theme constants  (mirror the floating toolbar palette)
# ---------------------------------------------------------------------------

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
QLineEdit, QSpinBox {
    background-color: #1E1F28;
    color: #D4C5AE;
    border: 1px solid #4B4D63;
    border-radius: 4px;
    padding: 3px 6px;
    font-size: 12px;
}
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
"""

_C_ICON   = "#9E886C"
_C_ACCENT = "#BFA381"
_THUMB_W  = 140   # sidebar thumbnail width (px)
_RECENT_W = 110   # recent-dialog thumbnail width (px)
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
        # Serve from disk cache if available
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
# Thumbnail list item delegate
# ---------------------------------------------------------------------------

_ROLE_PAGE = Qt.ItemDataRole.UserRole
_ROLE_PIX  = Qt.ItemDataRole.UserRole + 1


class _ThumbDelegate(QStyledItemDelegate):
    """Renders a page thumbnail + number badge in the sidebar list."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        pix: Optional[QPixmap] = index.data(_ROLE_PIX)
        if pix and not pix.isNull():
            return QSize(_THUMB_W + 12, pix.height() + 20)
        return QSize(_THUMB_W + 12, int(_THUMB_W * 1.414) + 20)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        from PyQt6.QtWidgets import QStyle
        painter.save()

        # Background
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#524E48"))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor("#3B3C4F"))
        else:
            painter.fillRect(option.rect, QColor("#1E1F28"))

        page: int = index.data(_ROLE_PAGE) or 0
        pix: Optional[QPixmap] = index.data(_ROLE_PIX)

        r = option.rect
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

        # Page number badge
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
        self._pixmaps: Dict[int, QPixmap] = {}
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
        idx   = items[0].data(Qt.ItemDataRole.UserRole)
        path  = self._entries[idx]["path"]
        if Path(path).exists():
            self.pdf_chosen.emit(path)
            self.accept()


# ---------------------------------------------------------------------------
# Main PDF viewer window
# ---------------------------------------------------------------------------

class PDFViewerWindow(QDialog):
    """Persistent non-modal PDF viewer with sidebar, search, and zoom controls."""

    def __init__(self, settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings    = settings
        self._current_path = ""
        self._search_idx   = 0
        self._pool         = QThreadPool.globalInstance()
        self._thumb_pixmaps: Dict[int, QPixmap] = {}   # page → pixmap
        self._thumb_pending: set = set()                # pages in flight

        if _PDF_OK:
            self._doc            = QPdfDocument(self)
            self._bookmark_model = QPdfBookmarkModel(self)
            self._search_model   = QPdfSearchModel(self)
            self._search_model.setDocument(self._doc)

        self.setWindowTitle("PDF Viewer")
        self.setMinimumSize(450, 325)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setStyleSheet(_SS)
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

        # Search bar (hidden until Ctrl+F)
        self._search_bar = self._build_search_bar()
        self._search_bar.setVisible(False)
        root.addWidget(self._search_bar)

        # Splitter: sidebar | PDF view
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(3)
        self._splitter.addWidget(self._build_sidebar())
        self._splitter.addWidget(self._build_view_area())
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        root.addWidget(self._splitter)

        root.addWidget(self._build_status_bar())

        # Keyboard shortcuts
        QKeySequence("Ctrl+F").swap(QKeySequence())   # placeholder
        from PyQt6.QtGui import QShortcut
        QShortcut(QKeySequence("Ctrl+F"),  self).activated.connect(self._toggle_search)
        QShortcut(QKeySequence("Ctrl+O"),  self).activated.connect(self._open_file_dialog)
        QShortcut(QKeySequence("Escape"),  self).activated.connect(self._on_escape)

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

        # Open / Recent
        self._btn_open   = tb("fa5s.folder-open", "Open PDF (Ctrl+O)")
        self._btn_recent = tb("fa5s.history",      "Recent PDFs")
        self._btn_open.clicked.connect(self._open_file_dialog)
        self._btn_recent.clicked.connect(self._show_recent)
        lay.addWidget(self._btn_open)
        lay.addWidget(self._btn_recent)
        lay.addWidget(sep())

        # Page navigation
        self._btn_prev = tb("fa5s.chevron-up",   "Previous Page")
        self._btn_next = tb("fa5s.chevron-down", "Next Page")
        self._page_label = QLabel("— / —")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setFixedWidth(72)
        self._btn_prev.clicked.connect(self._prev_page)
        self._btn_next.clicked.connect(self._next_page)
        lay.addWidget(self._btn_prev)
        lay.addWidget(self._page_label)
        lay.addWidget(self._btn_next)
        lay.addWidget(sep())

        # Zoom mode buttons
        self._zoom_btns: Dict[str, QToolButton] = {}
        for mode, icon_name, tip in [
            ("width",  "fa5s.arrows-alt-h", "Fit to Width"),
            ("height", "fa5s.arrows-alt-v", "Fit to Height"),
            ("page",   "fa5s.compress-alt", "Fit Page"),
            ("auto",   "fa5s.expand-arrows-alt", "Auto Scale (tracks window)"),
        ]:
            b = tb(icon_name, tip, checkable=True)
            b.clicked.connect(lambda _, m=mode: self._set_zoom_mode(m))
            self._zoom_btns[mode] = b
            lay.addWidget(b)

        lay.addWidget(sep())

        # Custom zoom spinbox
        self._zoom_spin = _make_spin(25, 500, 100, "%")
        self._zoom_spin.setFixedWidth(72)
        self._zoom_spin.setToolTip("Zoom percentage")
        self._zoom_spin.valueChanged.connect(self._on_zoom_spin)
        lay.addWidget(self._zoom_spin)
        lay.addWidget(sep())

        # Search toggle
        self._btn_search = tb("fa5s.search", "Search (Ctrl+F)", checkable=True)
        self._btn_search.clicked.connect(self._toggle_search)
        lay.addWidget(self._btn_search)

        # Sidebar toggle
        self._btn_sidebar = tb("fa5s.columns", "Toggle Sidebar", checkable=True)
        self._btn_sidebar.setChecked(True)
        self._btn_sidebar.clicked.connect(self._toggle_sidebar)
        lay.addWidget(self._btn_sidebar)

        lay.addStretch()

        # Title label
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

        # Panel toggle row
        toggle_row = QWidget()
        toggle_row.setFixedHeight(36)
        toggle_row.setStyleSheet(
            "background:#292A35; border-bottom:1px solid #4B4D63;")
        tr_lay = QHBoxLayout(toggle_row)
        tr_lay.setContentsMargins(4, 3, 4, 3)
        tr_lay.setSpacing(2)

        self._panel_btns: Dict[str, QToolButton] = {}
        for panel, icon_name, tip in [
            ("outlines",   "fa5s.list-alt",  "Document Outline"),
            ("bookmarks",  "fa5s.bookmark",  "My Bookmarks"),
            ("thumbnails", "fa5s.th-large",  "Page Thumbnails"),
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

        # Collapse button
        self._btn_collapse = QToolButton()
        self._btn_collapse.setIcon(_icon("fa5s.chevron-left"))
        self._btn_collapse.setToolTip("Collapse sidebar")
        self._btn_collapse.setFixedSize(24, 28)
        self._btn_collapse.clicked.connect(self._toggle_sidebar)
        tr_lay.addWidget(self._btn_collapse)

        outer.addWidget(toggle_row)

        # Stacked panels
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Outlines panel
        self._outline_view = QTreeView()
        self._outline_view.setHeaderHidden(True)
        self._outline_view.activated.connect(self._on_outline_activated)
        if _PDF_OK:
            self._bookmark_model.setDocument(self._doc)
            self._outline_view.setModel(self._bookmark_model)
        self._stack.addWidget(self._outline_view)

        # User bookmarks panel
        bm_widget = QWidget()
        bm_widget.setObjectName("pdf_root")
        bm_lay = QVBoxLayout(bm_widget)
        bm_lay.setContentsMargins(4, 4, 4, 4)
        bm_lay.setSpacing(4)
        self._bm_list = QListWidget()
        self._bm_list.itemDoubleClicked.connect(self._on_user_bm_activated)
        bm_lay.addWidget(self._bm_list)
        bm_btn_row = QHBoxLayout()
        add_bm = QPushButton(_icon("fa5s.plus"), "Add")
        del_bm = QPushButton(_icon("fa5s.trash"), "Remove")
        add_bm.clicked.connect(self._add_user_bookmark)
        del_bm.clicked.connect(self._remove_user_bookmark)
        bm_btn_row.addWidget(add_bm)
        bm_btn_row.addWidget(del_bm)
        bm_lay.addLayout(bm_btn_row)
        self._stack.addWidget(bm_widget)

        # Thumbnails panel
        self._thumb_list = QListWidget()
        self._thumb_list.setItemDelegate(_ThumbDelegate())
        self._thumb_list.setSpacing(4)
        self._thumb_list.setVerticalScrollMode(
            QListWidget.ScrollMode.ScrollPerPixel)
        self._thumb_list.itemClicked.connect(self._on_thumb_clicked)
        self._thumb_list.verticalScrollBar().valueChanged.connect(
            self._on_thumb_scroll)
        self._stack.addWidget(self._thumb_list)

        # Map panel names to stack indices
        self._panel_idx = {"outlines": 0, "bookmarks": 1, "thumbnails": 2}

        return self._sidebar

    def _build_view_area(self) -> QWidget:
        container = QWidget()
        container.setObjectName("pdf_root")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        if _PDF_OK:
            self._view = QPdfView(container)
            self._view.setDocument(self._doc)
            self._view.setPageMode(QPdfView.PageMode.MultiPage)
            if hasattr(self._view, "setTextSelectionEnabled"):
                self._view.setTextSelectionEnabled(True)
            self._view.pageNavigator().currentPageChanged.connect(
                self._on_page_changed)
            self._view.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu)
            self._view.customContextMenuRequested.connect(
                self._on_view_context_menu)
            lay.addWidget(self._view)
        else:
            lbl = QLabel(
                "PDF support requires PyQt6 6.4+.\n\n"
                "Run:  pip install PyQt6>=6.4.0"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color:#7A7890; font-size:14px;")
            lay.addWidget(lbl)

        return container

    def _build_search_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(
            "background:#1E1F28; border-bottom:1px solid #4B4D63;")
        bar.setFixedHeight(40)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search…")
        self._search_input.setFixedWidth(220)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_input.returnPressed.connect(
            lambda: self._navigate_search(1))

        self._search_count = QLabel("")
        self._search_count.setStyleSheet("color:#7A7890;")
        self._search_count.setFixedWidth(80)

        btn_prev = QPushButton(_icon("fa5s.chevron-up"),   "")
        btn_next = QPushButton(_icon("fa5s.chevron-down"), "")
        btn_prev.setFixedSize(28, 28)
        btn_next.setFixedSize(28, 28)
        btn_prev.setToolTip("Previous result")
        btn_next.setToolTip("Next result")
        btn_prev.clicked.connect(lambda: self._navigate_search(-1))
        btn_next.clicked.connect(lambda: self._navigate_search(1))

        btn_close = QPushButton(_icon("fa5s.times"), "")
        btn_close.setFixedSize(28, 28)
        btn_close.setToolTip("Close search (Esc)")
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
        bar.setStyleSheet(
            "background:#1E1F28; border-top:1px solid #4B4D63;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color:#7A7890; font-size:11px;")
        lay.addWidget(self._status_label)
        lay.addStretch()
        return bar

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _open_file_dialog(self) -> None:
        start = str(Path(self._current_path).parent) if self._current_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", start, "PDF Files (*.pdf)")
        if path:
            self._load_pdf(path)

    def _load_pdf(self, path: str) -> None:
        if not Path(path).exists():
            return
        if not _PDF_OK:
            return

        self._current_path = path
        self._thumb_pixmaps.clear()
        self._thumb_pending.clear()

        status = self._doc.load(path)
        if status != QPdfDocument.Error.None_:
            self._status_label.setText(f"Failed to open: {Path(path).name}")
            return

        title = self._doc.metaData(QPdfDocument.MetaDataField.Title) or Path(path).stem
        self.setWindowTitle(f"PDF — {Path(path).name}")
        self._title_label.setText(title)

        count = self._doc.pageCount()
        self._page_label.setText(f"1 / {count}")
        self._status_label.setText(f"{count} pages  •  {Path(path).name}")

        # Restore bookmark model
        self._bookmark_model.setDocument(self._doc)

        # Populate thumbnails
        self._populate_thumb_list()

        # Restore last page
        last_pages = self._settings.pdf("last_pages") or {}
        page = last_pages.get(path, 0)
        if page and _PDF_OK:
            self._view.pageNavigator().jump(page, QPointF())

        # Add to recently used
        self._add_to_recently_used(path, title)
        self._settings.set_pdf("last_path", path)
        self._settings.save()

        # Apply current zoom mode
        self._set_zoom_mode(self._settings.pdf("zoom_mode") or "auto")

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
        thumbs_dir = self._settings.pdf_thumbs_dir()
        dlg = _RecentDialog(recent, thumbs_dir, self)
        dlg.pdf_chosen.connect(self._load_pdf)
        dlg.exec()

    # ------------------------------------------------------------------
    # Page navigation
    # ------------------------------------------------------------------

    def _go_to_page(self, page: int) -> None:
        if not _PDF_OK or not self._current_path:
            return
        page = max(0, min(page, self._doc.pageCount() - 1))
        self._view.pageNavigator().jump(page, QPointF())

    def _prev_page(self) -> None:
        if _PDF_OK and self._current_path:
            self._go_to_page(self._view.pageNavigator().currentPage() - 1)

    def _next_page(self) -> None:
        if _PDF_OK and self._current_path:
            self._go_to_page(self._view.pageNavigator().currentPage() + 1)

    def _on_page_changed(self, page: int) -> None:
        if not _PDF_OK:
            return
        count = self._doc.pageCount()
        self._page_label.setText(f"{page + 1} / {count}")

        # Highlight current thumbnail
        if self._thumb_list.count() > page:
            self._thumb_list.setCurrentRow(page)
            self._thumb_list.scrollToItem(
                self._thumb_list.item(page),
                QListWidget.ScrollHint.EnsureVisible,
            )

        # Save last page
        if self._current_path:
            last_pages = dict(self._settings.pdf("last_pages") or {})
            last_pages[self._current_path] = page
            self._settings.set_pdf("last_pages", last_pages)

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def _set_zoom_mode(self, mode: str) -> None:
        if not _PDF_OK:
            return

        # Update button states
        for m, b in self._zoom_btns.items():
            b.setChecked(m == mode)

        self._settings.set_pdf("zoom_mode", mode)

        if mode == "width":
            self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self._zoom_spin.setEnabled(False)
        elif mode == "page":
            self._view.setZoomMode(QPdfView.ZoomMode.FitInView)
            self._zoom_spin.setEnabled(False)
        elif mode == "auto":
            self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self._zoom_spin.setEnabled(False)
        elif mode == "height":
            self._apply_fit_height()
            self._zoom_spin.setEnabled(False)
        elif mode == "custom":
            self._view.setZoomMode(QPdfView.ZoomMode.Custom)
            self._zoom_spin.setEnabled(True)

    def _apply_fit_height(self) -> None:
        """Compute a zoom factor so the current page height fills the viewport."""
        if not _PDF_OK or not self._current_path:
            return
        page     = self._view.pageNavigator().currentPage()
        page_sz  = self._doc.pagePointSize(page)
        if page_sz.isEmpty():
            return
        view_h   = self._view.viewport().height()
        pts_h    = page_sz.height()
        factor   = view_h / (pts_h * 96 / 72)
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(factor)
        self._zoom_spin.blockSignals(True)
        self._zoom_spin.setValue(int(factor * 100))
        self._zoom_spin.blockSignals(False)

    def _on_zoom_spin(self, value: int) -> None:
        if not _PDF_OK:
            return
        for b in self._zoom_btns.values():
            b.setChecked(False)
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(value / 100.0)
        self._settings.set_pdf("zoom_mode",   "custom")
        self._settings.set_pdf("zoom_factor", value / 100.0)

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
        if _PDF_OK:
            self._search_model.setSearchString("")
        self._search_count.setText("")

    def _on_search_text_changed(self, text: str) -> None:
        if not _PDF_OK:
            return
        self._search_idx = 0
        self._search_model.setSearchString(text)
        count = self._search_model.rowCount(QModelIndex())
        if text:
            self._search_count.setText(
                f"0 / {count}" if count else "No results")
            if count:
                self._navigate_search(0, reset=True)
        else:
            self._search_count.setText("")

    def _navigate_search(self, direction: int, reset: bool = False) -> None:
        if not _PDF_OK:
            return
        count = self._search_model.rowCount(QModelIndex())
        if not count:
            return
        if reset:
            self._search_idx = 0
        else:
            self._search_idx = (self._search_idx + direction) % count

        self._search_count.setText(f"{self._search_idx + 1} / {count}")
        idx  = self._search_model.index(self._search_idx, 0)
        link = idx.data(QPdfSearchModel.Role.ResultLink)
        if link:
            self._view.pageNavigator().jump(link.page(), link.location())

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

        # Kick off thumbnail loading when thumbnails panel becomes visible
        if panel == "thumbnails" and self._current_path:
            self._load_visible_thumbs()

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

    # ------------------------------------------------------------------
    # Sidebar: outlines
    # ------------------------------------------------------------------

    def _on_outline_activated(self, index: QModelIndex) -> None:
        if not _PDF_OK:
            return
        page = index.data(QPdfBookmarkModel.Role.Page)
        if page is not None:
            self._go_to_page(page)

    # ------------------------------------------------------------------
    # Sidebar: user bookmarks
    # ------------------------------------------------------------------

    def _add_user_bookmark(self) -> None:
        if not _PDF_OK or not self._current_path:
            return
        page    = self._view.pageNavigator().currentPage()
        label   = f"Page {page + 1}"
        bms     = dict(self._settings.pdf("user_bookmarks") or {})
        entries = list(bms.get(self._current_path, []))
        # Avoid duplicates on same page
        if any(e["page"] == page for e in entries):
            return
        entries.append({"page": page, "label": label})
        entries.sort(key=lambda e: e["page"])
        bms[self._current_path] = entries
        self._settings.set_pdf("user_bookmarks", bms)
        self._settings.save()
        self._refresh_user_bookmarks()

    def _remove_user_bookmark(self) -> None:
        row = self._bm_list.currentRow()
        if row < 0 or not self._current_path:
            return
        bms     = dict(self._settings.pdf("user_bookmarks") or {})
        entries = list(bms.get(self._current_path, []))
        if row < len(entries):
            entries.pop(row)
        bms[self._current_path] = entries
        self._settings.set_pdf("user_bookmarks", bms)
        self._settings.save()
        self._refresh_user_bookmarks()

    def _refresh_user_bookmarks(self) -> None:
        self._bm_list.clear()
        if not self._current_path:
            return
        bms     = self._settings.pdf("user_bookmarks") or {}
        entries = bms.get(self._current_path, [])
        for e in entries:
            item = QListWidgetItem(
                f"  pg {e['page'] + 1}  —  {e['label']}")
            item.setData(Qt.ItemDataRole.UserRole, e["page"])
            self._bm_list.addItem(item)

    def _on_user_bm_activated(self, item: QListWidgetItem) -> None:
        page = item.data(Qt.ItemDataRole.UserRole)
        if page is not None:
            self._go_to_page(page)

    # ------------------------------------------------------------------
    # Sidebar: thumbnails
    # ------------------------------------------------------------------

    def _populate_thumb_list(self) -> None:
        self._thumb_list.clear()
        self._thumb_pixmaps.clear()
        self._thumb_pending.clear()
        if not _PDF_OK or not self._current_path:
            return
        count = self._doc.pageCount()
        for p in range(count):
            item = QListWidgetItem()
            item.setData(_ROLE_PAGE, p)
            item.setData(_ROLE_PIX,  None)
            self._thumb_list.addItem(item)
        self._load_visible_thumbs()

    def _load_visible_thumbs(self) -> None:
        """Queue thumbnail renders for pages visible in the sidebar list."""
        if not self._current_path:
            return
        vr   = self._thumb_list.viewport().rect()
        top  = self._thumb_list.indexAt(vr.topLeft())
        bot  = self._thumb_list.indexAt(vr.bottomRight())
        t    = top.row()   if top.isValid()  else 0
        b    = bot.row()   if bot.isValid()  else min(t + 8, self._thumb_list.count() - 1)
        # Pad a few pages above/below
        for p in range(max(0, t - 2), min(self._thumb_list.count(), b + 4)):
            self._request_thumb(p)

    def _request_thumb(self, page: int) -> None:
        if page in self._thumb_pixmaps or page in self._thumb_pending:
            return
        if not self._current_path:
            return
        try:
            cache_file = str(
                self._settings.pdf_thumbs_dir() /
                _thumb_cache_key(self._current_path, page, _THUMB_W)
            )
        except OSError:
            return
        self._thumb_pending.add(page)
        w = _ThumbnailWorker(self._current_path, page, _THUMB_W, cache_file)
        w.signals.ready.connect(self._on_thumb_ready)
        self._pool.start(w)

    def _on_thumb_ready(self, path: str, page: int, pix: QPixmap) -> None:
        if path != self._current_path:
            return
        self._thumb_pixmaps[page] = pix
        self._thumb_pending.discard(page)
        item = self._thumb_list.item(page)
        if item:
            item.setData(_ROLE_PIX, pix)
            self._thumb_list.update(
                self._thumb_list.model().index(page, 0))

    def _on_thumb_scroll(self) -> None:
        self._load_visible_thumbs()

    def _on_thumb_clicked(self, item: QListWidgetItem) -> None:
        page = item.data(_ROLE_PAGE)
        if page is not None:
            self._go_to_page(page)

    # ------------------------------------------------------------------
    # PDF view context menu
    # ------------------------------------------------------------------

    def _on_view_context_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu
        import subprocess, sys
        menu = QMenu(self)
        menu.setStyleSheet(_SS)
        act_show = menu.addAction("Show in File Explorer")
        act_show.setEnabled(
            bool(self._current_path and Path(self._current_path).exists()))
        chosen = menu.exec(self._view.mapToGlobal(pos))
        if chosen is act_show and self._current_path:
            if sys.platform == "win32":
                subprocess.Popen(
                    f'explorer /select,"{self._current_path}"', shell=True)
            else:
                import os
                os.startfile(str(Path(self._current_path).parent))

    # ------------------------------------------------------------------
    # State save / restore
    # ------------------------------------------------------------------

    def _restore_state(self) -> None:
        # Window geometry
        geom = self._settings.pdf("window_geometry")
        if geom and len(geom) == 4:
            from PyQt6.QtCore import QRect
            self.setGeometry(QRect(geom[0], geom[1], geom[2], geom[3]))

        # Sidebar
        panel     = self._settings.pdf("sidebar_panel") or "thumbnails"
        collapsed = self._settings.pdf("sidebar_collapsed") or False
        width     = self._settings.pdf("sidebar_width") or 220
        self._switch_panel(panel)
        if collapsed:
            self._splitter.setSizes([0, 9000])
            self._btn_collapse.setIcon(_icon("fa5s.chevron-right"))
            self._btn_collapse.setToolTip("Expand sidebar")
            self._btn_sidebar.setChecked(False)
        else:
            self._splitter.setSizes([width, 9000 - width])
            self._btn_sidebar.setChecked(True)

        # Re-open last PDF
        last = self._settings.pdf("last_path") or ""
        if last and Path(last).exists():
            self._load_pdf(last)

    def closeEvent(self, event) -> None:
        if _PDF_OK and self._current_path:
            # Save last page
            page = self._view.pageNavigator().currentPage()
            last_pages = dict(self._settings.pdf("last_pages") or {})
            last_pages[self._current_path] = page
            self._settings.set_pdf("last_pages", last_pages)
        # Save sidebar width
        sizes = self._splitter.sizes()
        if sizes[0] > 10:
            self._settings.set_pdf("sidebar_width", sizes[0])
        # Save window geometry
        g = self.geometry()
        self._settings.set_pdf("window_geometry", [g.x(), g.y(), g.width(), g.height()])
        self._settings.save()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spin(min_: int, max_: int, default: int, suffix: str) -> "QSpinBox":
    from PyQt6.QtWidgets import QSpinBox
    s = QSpinBox()
    s.setRange(min_, max_)
    s.setValue(default)
    s.setSuffix(suffix)
    return s
