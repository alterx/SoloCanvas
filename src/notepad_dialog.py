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

"""NotepadDialog – WYSIWYG Markdown notepad with tab support."""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import markdown as _md_lib
from markdownify import markdownify as _html_to_md_raw

from PyQt6.QtCore import QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QAction, QDragEnterEvent, QDropEvent,
    QFont, QFontDatabase, QKeySequence,
    QShortcut, QTextBlockFormat, QTextCharFormat, QTextCursor,
)
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import (
    QDialog, QFileDialog,
    QLabel, QMenuBar,
    QMessageBox, QSizePolicy, QTabWidget, QTextEdit, QToolBar,
    QToolButton, QVBoxLayout,
)

# ──────────────────────────────────────────────────────────────────────────────
# Markdown ↔ HTML helpers  (unchanged)
# ──────────────────────────────────────────────────────────────────────────────

_MD_EXT = ["extra", "nl2br", "sane_lists"]

_CB_UNCHECKED = "☐"
_CB_CHECKED   = "☑"


def _preprocess_md(text: str) -> str:
    text = re.sub(r"^(\s*[-*+]\s)\[ \]", rf"\1{_CB_UNCHECKED}", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*[-*+]\s)\[x\]", rf"\1{_CB_CHECKED}",   text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*[-*+]\s)\[X\]", rf"\1{_CB_CHECKED}",   text, flags=re.MULTILINE)
    return text


def _postprocess_md(text: str) -> str:
    text = re.sub(rf"^(\s*[-*+]\s){_CB_UNCHECKED}", r"\1[ ]", text, flags=re.MULTILINE)
    text = re.sub(rf"^(\s*[-*+]\s){_CB_CHECKED}",   r"\1[x]", text, flags=re.MULTILINE)
    return text


def md_to_html(md_text: str, base_dir: Path) -> str:
    preprocessed = _preprocess_md(md_text)
    html = _md_lib.markdown(preprocessed, extensions=_MD_EXT)
    def _resolve_img(m: re.Match) -> str:
        src = m.group(1)
        if not src.startswith(("http://", "https://", "file://")):
            abs_path = (base_dir / src).resolve()
            src = abs_path.as_uri()
        return f'src="{src}"'
    html = re.sub(r'src="([^"]+)"', _resolve_img, html)
    return html


def _semantify_qt_html(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for span in list(soup.find_all("span")):
        raw_style = span.get("style", "")
        style = raw_style.replace(" ", "").lower()
        wrappers = []
        if "font-weight:600" in style or "font-weight:bold" in style or "font-weight:700" in style:
            wrappers.append("strong")
        if "font-style:italic" in style:
            wrappers.append("em")
        if "text-decoration:underline" in style:
            wrappers.append("u")
        if "text-decoration:line-through" in style:
            wrappers.append("s")
        if wrappers:
            outer = soup.new_tag(wrappers[0])
            inner = outer
            for tag_name in wrappers[1:]:
                child_tag = soup.new_tag(tag_name)
                inner.append(child_tag)
                inner = child_tag
            for child in list(span.children):
                inner.append(child.extract())
            span.replace_with(outer)
    return str(soup)


def html_to_md(html: str, base_dir: Path) -> str:
    html = _semantify_qt_html(html)
    def _unresolve_img(m: re.Match) -> str:
        src = m.group(1)
        if src.startswith("file:///"):
            try:
                abs_path = Path(QUrl(src).toLocalFile())
                rel = abs_path.relative_to(base_dir)
                src = rel.as_posix()
            except (ValueError, Exception):
                pass
        return f'src="{src}"'
    html = re.sub(r'src="([^"]+)"', _unresolve_img, html)
    md = _html_to_md_raw(html, heading_style="ATX", bullets="-")
    md = _postprocess_md(md)
    return md.strip() + "\n"


# ──────────────────────────────────────────────────────────────────────────────
# WYSIWYG editor  (unchanged)
# ──────────────────────────────────────────────────────────────────────────────

class _Editor(QTextEdit):
    def __init__(self, notes_dir: Path, parent=None):
        super().__init__(parent)
        self._notes_dir = notes_dir
        self.setAcceptDrops(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            cursor = self.cursorForPosition(event.pos())
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            word = cursor.selectedText()
            if word in (_CB_UNCHECKED, _CB_CHECKED):
                cursor.insertText(_CB_CHECKED if word == _CB_UNCHECKED else _CB_UNCHECKED)
                return
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            _IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff"}
            if any(
                Path(u.toLocalFile()).suffix.lower() in _IMG_EXT
                for u in event.mimeData().urls() if u.isLocalFile()
            ):
                event.acceptProposedAction()
                return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            _IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff"}
            images_dir = self._notes_dir / "Images"
            images_dir.mkdir(parents=True, exist_ok=True)
            for url in event.mimeData().urls():
                if not url.isLocalFile():
                    continue
                src = Path(url.toLocalFile())
                if src.suffix.lower() not in _IMG_EXT:
                    continue
                dest = images_dir / src.name
                counter = 1
                while dest.exists():
                    dest = images_dir / f"{src.stem}_{counter}{src.suffix}"
                    counter += 1
                shutil.copy2(src, dest)
                self.textCursor().insertHtml(
                    f'<img src="{dest.as_uri()}" alt="{dest.name}"/>'
                )
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def keyPressEvent(self, event):
        event.accept()
        super().keyPressEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Per-tab state container
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _NoteTab:
    """Companion state for one editor tab. The editor widget itself is the
    QTabWidget child; this dataclass tracks file/dirty state alongside it."""
    editor:       _Editor
    current_file: Optional[Path] = None
    dirty:        bool           = False


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_FONT_FAMILY = "Segoe UI"
_DEFAULT_FONT_SIZE   = 11

_TOOLBAR_STYLE = """
QToolBar { spacing: 2px; padding: 2px; }
QToolButton { padding: 2px 4px; }
"""

_OPEN_FILTER  = "Notes (*.md *.html *.txt);;Markdown (*.md);;HTML (*.html);;Text (*.txt);;All Files (*)"
_SAVE_FILTER  = "Markdown (*.md);;HTML (*.html);;Text (*.txt);;All Files (*)"

_HEADING_SCALE = {1: 2.0, 2: 1.5, 3: 1.25}

def _tab_stylesheet() -> str:
    """Build the QTabWidget stylesheet, injecting the absolute path to the close icon."""
    import sys
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    icon = (base / "resources" / "images" / "tab_close.svg").as_posix()
    return f"""
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: #1E1F28;
    color: #7A7890;
    padding: 4px 10px 4px 10px;
    border: 1px solid #3B3C4F;
    border-bottom: none;
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
    font-size: 11px;
}}
QTabBar::tab:selected {{
    background: #292A35;
    color: #D4C5AE;
    border-bottom: 1px solid #292A35;
}}
QTabBar::tab:hover:!selected {{ background: #252632; }}
QTabBar::close-button {{
    image: url("{icon}");
    subcontrol-position: right;
    width: 10px;
    height: 10px;
    margin-left: 4px;
    border-radius: 2px;
}}
QTabBar::close-button:hover {{
    background: #524E48;
}}
"""


# ──────────────────────────────────────────────────────────────────────────────
# Main dialog
# ──────────────────────────────────────────────────────────────────────────────

class NotepadDialog(QDialog):
    """Floating, resizable Markdown notepad with multi-tab support."""

    def __init__(self, notes_dir: Path, config_path: Path, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Notepad")
        self.resize(900, 600)

        self._notes_dir   = notes_dir
        self._config_path = config_path

        # Tab tracking
        self._tabs: List[_NoteTab] = []
        self._prev_tab_index: int  = -1

        # Global font settings (shared across all tabs)
        self._font_family:       str  = _DEFAULT_FONT_FAMILY
        self._font_size:         int  = _DEFAULT_FONT_SIZE
        self._heading_underline: bool = True

        self._build_ui()
        self._load_state()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._menu_bar = QMenuBar(self)
        self._build_menus()
        self._menu_bar.setSizePolicy(
            self._menu_bar.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Fixed,
        )
        root.addWidget(self._menu_bar, 0)

        self._toolbar = self._build_toolbar()
        root.addWidget(self._toolbar, 0)

        # Tab widget
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.setStyleSheet(_tab_stylesheet())
        self._tab_widget.tabCloseRequested.connect(self._close_tab)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tab_widget, 1)

        # Status bar
        self._status = QLabel("  Untitled")
        self._status.setStyleSheet("color: gray; font-size: 10px; padding: 2px 6px;")
        root.addWidget(self._status, 0)

        # Window-level shortcuts (Ctrl+T and Ctrl+W are already defined via QAction in the
        # File menu — registering them again as QShortcut causes PyQt6 ambiguity and neither fires)
        QShortcut(QKeySequence("Ctrl+1"), self).activated.connect(lambda: self._insert_heading(1))
        QShortcut(QKeySequence("Ctrl+2"), self).activated.connect(lambda: self._insert_heading(2))
        QShortcut(QKeySequence("Ctrl+3"), self).activated.connect(lambda: self._insert_heading(3))
        QShortcut(QKeySequence("Ctrl+Tab"),        self).activated.connect(self._next_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"),  self).activated.connect(self._prev_tab)

    def _build_menus(self):
        file_menu = self._menu_bar.addMenu("File")
        _a(file_menu, "New Tab",       self._action_new_tab,   "Ctrl+T")
        _a(file_menu, "New Note",      self._new_note_in_tab,  "Ctrl+N")
        file_menu.addSeparator()
        _a(file_menu, "Open…",         self._open_note,        "Ctrl+O")
        file_menu.addSeparator()
        _a(file_menu, "Save",          self._save_current,     "Ctrl+S")
        _a(file_menu, "Save As…",      self._save_as,          "Ctrl+Shift+S")
        file_menu.addSeparator()
        _a(file_menu, "Close Tab",     lambda: self._close_tab(self._tab_widget.currentIndex()), "Ctrl+W")
        file_menu.addSeparator()
        _a(file_menu, "Export to PDF", self._export_pdf)

        edit_menu = self._menu_bar.addMenu("Edit")
        _a(edit_menu, "Undo",      self._undo,             "Ctrl+Z")
        _a(edit_menu, "Redo",      self._redo,             "Ctrl+Y")
        edit_menu.addSeparator()
        _a(edit_menu, "Cut",       self._cut,              "Ctrl+X")
        _a(edit_menu, "Copy",      self._copy,             "Ctrl+C")
        _a(edit_menu, "Paste",     self._paste,            "Ctrl+V")
        edit_menu.addSeparator()
        _a(edit_menu, "Bold",      self._toggle_bold,      "Ctrl+B")
        _a(edit_menu, "Italic",    self._toggle_italic,    "Ctrl+I")
        _a(edit_menu, "Underline", self._toggle_underline, "Ctrl+U")
        edit_menu.addSeparator()
        self._heading_underline_act = QAction("Heading Underline", self)
        self._heading_underline_act.setCheckable(True)
        self._heading_underline_act.setChecked(self._heading_underline)
        self._heading_underline_act.toggled.connect(self._toggle_heading_underline)
        edit_menu.addAction(self._heading_underline_act)

        self._font_menu = self._menu_bar.addMenu(f"Font: {self._font_family}")
        self._font_actions: dict[str, QAction] = {}
        for family in sorted(set(QFontDatabase.families())):
            act = QAction(family, self)
            act.setFont(QFont(family, 11))
            act.setCheckable(True)
            act.triggered.connect(lambda checked, f=family: self._set_font_family(f))
            self._font_menu.addAction(act)
            self._font_actions[family] = act

        self._size_menu = self._menu_bar.addMenu(f"Size: {self._font_size}")
        self._size_actions: dict[int, QAction] = {}
        for size in (8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 24, 28, 32):
            act = QAction(str(size), self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, s=size: self._set_font_size(s))
            self._size_menu.addAction(act)
            self._size_actions[size] = act

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setStyleSheet(_TOOLBAR_STYLE)
        tb.setIconSize(QSize(16, 16))

        def _btn(label, tip, slot):
            b = QToolButton()
            b.setText(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            tb.addWidget(b)

        _btn("B",  "Bold (Ctrl+B)",      self._toggle_bold)
        _btn("I",  "Italic (Ctrl+I)",    self._toggle_italic)
        _btn("U̲",  "Underline (Ctrl+U)", self._toggle_underline)
        tb.addSeparator()
        _btn("H1", "Heading 1 (Ctrl+1)", lambda: self._insert_heading(1))
        _btn("H2", "Heading 2 (Ctrl+2)", lambda: self._insert_heading(2))
        _btn("H3", "Heading 3 (Ctrl+3)", lambda: self._insert_heading(3))
        tb.addSeparator()
        _btn("☐", "Insert checkbox", self._insert_checkbox)
        _btn("•",  "Bullet list",    self._insert_bullet)
        return tb

    # ── Tab management ───────────────────────────────────────────────────────

    @property
    def _current_note(self) -> Optional[_NoteTab]:
        idx = self._tab_widget.currentIndex()
        if 0 <= idx < len(self._tabs):
            return self._tabs[idx]
        return None

    def _new_tab(self) -> _NoteTab:
        """Create a new blank tab, add it to the widget, return the _NoteTab."""
        editor = _Editor(self._notes_dir)
        editor.setFont(QFont(self._font_family, self._font_size))
        editor.document().setDefaultFont(QFont(self._font_family, self._font_size))
        editor.document().contentsChanged.connect(
            lambda ed=editor: self._on_content_changed(ed))
        note = _NoteTab(editor=editor)
        self._tabs.append(note)
        idx = self._tab_widget.addTab(editor, "Untitled")
        self._tab_widget.setCurrentIndex(idx)
        return note

    def _action_new_tab(self):
        """Ctrl+T / File > New Tab: open a fresh blank tab."""
        self._new_tab()
        self._update_ui_for_current_tab()

    def _new_note_in_tab(self):
        """File > New Note: clear current tab if blank, else open new tab."""
        note = self._current_note
        if note and note.current_file is None and not note.dirty:
            # Already blank — just ensure editor is cleared
            note.editor.clear()
            note.editor.document().setDefaultFont(
                QFont(self._font_family, self._font_size))
        else:
            self._new_tab()
        self._update_ui_for_current_tab()

    def _close_tab(self, index: int) -> None:
        if index < 0 or index >= len(self._tabs):
            return
        # Save (with possible Untitled prompt) before closing
        self._save_tab(index)
        note = self._tabs[index]
        note.editor.deleteLater()
        self._tabs.pop(index)
        # Adjust prev index tracking
        if self._prev_tab_index >= index:
            self._prev_tab_index = max(-1, self._prev_tab_index - 1)
        self._tab_widget.removeTab(index)
        # Always keep at least one tab
        if self._tab_widget.count() == 0:
            self._new_tab()
        self._update_ui_for_current_tab()

    def _on_tab_changed(self, new_index: int) -> None:
        prev = self._prev_tab_index
        self._prev_tab_index = new_index
        # Defer save so the tab switch renders first, then the save/prompt fires
        if prev >= 0 and prev < len(self._tabs) and prev != new_index:
            QTimer.singleShot(0, lambda idx=prev: self._save_tab(idx))
        self._update_ui_for_current_tab()

    def _next_tab(self):
        n = self._tab_widget.count()
        if n > 1:
            self._tab_widget.setCurrentIndex(
                (self._tab_widget.currentIndex() + 1) % n)

    def _prev_tab(self):
        n = self._tab_widget.count()
        if n > 1:
            self._tab_widget.setCurrentIndex(
                (self._tab_widget.currentIndex() - 1) % n)

    def _update_tab_title(self, index: int) -> None:
        if index < 0 or index >= len(self._tabs):
            return
        note = self._tabs[index]
        name  = note.current_file.stem if note.current_file else "Untitled"
        label = f"[m] {name}" if note.dirty else name
        self._tab_widget.setTabText(index, label)

    def _update_ui_for_current_tab(self) -> None:
        note = self._current_note
        if note is None:
            self._status.setText("")
            self.setWindowTitle("Notepad")
            return
        if note.current_file:
            self._status.setText(f"  {note.current_file}")
            self.setWindowTitle(f"Notepad — {note.current_file.name}")
        else:
            self._status.setText("  Untitled")
            self.setWindowTitle("Notepad — Untitled")

    # ── Save logic ───────────────────────────────────────────────────────────

    def _save_tab(self, index: int) -> None:
        """Save the tab at *index*.  For Untitled dirty tabs, prompts the user."""
        if index < 0 or index >= len(self._tabs):
            return
        note = self._tabs[index]
        if not note.dirty:
            return
        if note.current_file is None:
            self._prompt_save_untitled(index)
        else:
            self._write_tab_file(index, note.current_file)

    def _prompt_save_untitled(self, index: int) -> None:
        note = self._tabs[index]
        if note.editor.toPlainText().strip() == "":
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Unsaved Note")
        msg.setText("This note has unsaved changes. Save it?")
        msg.setStandardButtons(
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Save)
        if msg.exec() == QMessageBox.StandardButton.Save:
            path_str, _ = QFileDialog.getSaveFileName(
                self, "Save Note As", str(self._notes_dir), _SAVE_FILTER)
            if path_str:
                path = Path(path_str)
                if not path.suffix:
                    path = path.with_suffix(".md")
                note.current_file = path
                self._write_tab_file(index, path)
                self._update_tab_title(index)
                self._update_ui_for_current_tab()

    def _write_tab_file(self, index: int, path: Path) -> None:
        note = self._tabs[index]
        suffix = path.suffix.lower()
        try:
            if suffix == ".html":
                content = note.editor.toHtml()
            elif suffix == ".txt":
                content = note.editor.toPlainText()
            else:
                content = html_to_md(note.editor.toHtml(), path.parent)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, path)
            note.dirty = False
            self._update_tab_title(index)
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))

    # ── Content change tracking ──────────────────────────────────────────────

    def _on_content_changed(self, editor: _Editor) -> None:
        for i, note in enumerate(self._tabs):
            if note.editor is editor and not note.dirty:
                note.dirty = True
                self._update_tab_title(i)
                break

    # ── File operations ──────────────────────────────────────────────────────

    def _open_note(self):
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open Note", str(self._notes_dir), _OPEN_FILTER)
        if path_str:
            self._open_file(Path(path_str))

    def _open_file(self, path: Path):
        # Switch to existing tab if already open
        for i, note in enumerate(self._tabs):
            if note.current_file == path:
                self._tab_widget.setCurrentIndex(i)
                return
        # Reuse current tab if it's blank and clean
        note = self._current_note
        idx  = self._tab_widget.currentIndex()
        if note and note.current_file is None and not note.dirty:
            self._load_file_into_tab(idx, path)
        else:
            self._new_tab()
            self._load_file_into_tab(self._tab_widget.currentIndex(), path)

    def _load_file_into_tab(self, index: int, path: Path) -> None:
        note = self._tabs[index]
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            text = ""
        suffix = path.suffix.lower()
        note.editor.document().contentsChanged.disconnect()
        if suffix == ".html":
            note.editor.setHtml(text)
        elif suffix == ".txt":
            note.editor.setPlainText(text)
        else:
            note.editor.setHtml(md_to_html(text, path.parent))
        note.editor.document().setDefaultFont(QFont(self._font_family, self._font_size))
        self._apply_heading_styles(note.editor)
        c = QTextCursor(note.editor.document())
        c.movePosition(QTextCursor.MoveOperation.Start)
        note.editor.setTextCursor(c)
        note.editor.document().contentsChanged.connect(
            lambda ed=note.editor: self._on_content_changed(ed))
        note.current_file = path
        note.dirty        = False
        self._update_tab_title(index)
        self._update_ui_for_current_tab()

    def _save_current(self):
        note = self._current_note
        if note is None:
            return
        idx = self._tab_widget.currentIndex()
        if note.current_file is None:
            self._save_as()
        else:
            self._write_tab_file(idx, note.current_file)

    def _save_as(self):
        note = self._current_note
        if note is None:
            return
        start = str(note.current_file or self._notes_dir)
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save Note As", start, _SAVE_FILTER)
        if not path_str:
            return
        path = Path(path_str)
        if not path.suffix:
            path = path.with_suffix(".md")
        note.current_file = path
        self._write_tab_file(self._tab_widget.currentIndex(), path)
        self._update_ui_for_current_tab()
        self._save_state()

    # ── Edit actions (route to current tab's editor) ─────────────────────────

    def _undo(self):
        if self._current_note:
            self._current_note.editor.undo()

    def _redo(self):
        if self._current_note:
            self._current_note.editor.redo()

    def _cut(self):
        if self._current_note:
            self._current_note.editor.cut()

    def _copy(self):
        if self._current_note:
            self._current_note.editor.copy()

    def _paste(self):
        if self._current_note:
            self._current_note.editor.paste()

    # ── Formatting actions ───────────────────────────────────────────────────

    def _editor(self) -> Optional[_Editor]:
        n = self._current_note
        return n.editor if n else None

    def _toggle_bold(self):
        ed = self._editor()
        if not ed:
            return
        fmt = QTextCharFormat()
        cur = ed.textCursor()
        current_weight = cur.charFormat().fontWeight()
        fmt.setFontWeight(
            QFont.Weight.Normal if current_weight == QFont.Weight.Bold else QFont.Weight.Bold
        )
        cur.mergeCharFormat(fmt)
        ed.mergeCurrentCharFormat(fmt)

    def _toggle_italic(self):
        ed = self._editor()
        if not ed:
            return
        fmt = QTextCharFormat()
        fmt.setFontItalic(not ed.currentCharFormat().fontItalic())
        ed.mergeCurrentCharFormat(fmt)

    def _toggle_underline(self):
        ed = self._editor()
        if not ed:
            return
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not ed.currentCharFormat().fontUnderline())
        ed.mergeCurrentCharFormat(fmt)

    def _insert_heading(self, level: int):
        ed = self._editor()
        if not ed:
            return
        cursor = ed.textCursor()
        doc = ed.document()
        sel_start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        sel_end   = cursor.selectionEnd()   if cursor.hasSelection() else cursor.position()
        first_block = doc.findBlock(sel_start)
        toggle_off  = (first_block.blockFormat().headingLevel() == level)
        cursor.beginEditBlock()
        block = first_block
        while block.isValid() and block.position() <= sel_end:
            bc = QTextCursor(block)
            bc.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            bc.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
            blk_fmt  = QTextBlockFormat()
            char_fmt = QTextCharFormat()
            if toggle_off:
                blk_fmt.setHeadingLevel(0)
                char_fmt.setFontPointSize(self._font_size)
                char_fmt.setFontWeight(QFont.Weight.Normal)
                char_fmt.setFontUnderline(False)
            else:
                blk_fmt.setHeadingLevel(level)
                scale = _HEADING_SCALE[level]
                char_fmt.setFontPointSize(round(self._font_size * scale))
                char_fmt.setFontWeight(QFont.Weight.Bold)
                char_fmt.setFontUnderline(self._heading_underline)
            bc.mergeBlockFormat(blk_fmt)
            bc.mergeCharFormat(char_fmt)
            block = block.next()
        cursor.endEditBlock()

    def _toggle_heading_underline(self, checked: bool):
        self._heading_underline = checked
        for note in self._tabs:
            self._apply_heading_styles(note.editor)
        self._save_state()

    def _apply_heading_styles(self, editor: _Editor) -> None:
        """Re-apply heading sizes/bold/underline to *editor*'s document."""
        doc = editor.document()
        saved_pos = editor.textCursor().position()
        block = doc.begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            if level in _HEADING_SCALE:
                bc = QTextCursor(block)
                bc.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                bc.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                QTextCursor.MoveMode.KeepAnchor)
                char_fmt = QTextCharFormat()
                char_fmt.setFontPointSize(round(self._font_size * _HEADING_SCALE[level]))
                char_fmt.setFontWeight(QFont.Weight.Bold)
                char_fmt.setFontUnderline(self._heading_underline)
                bc.mergeCharFormat(char_fmt)
            block = block.next()
        restore = QTextCursor(doc)
        restore.setPosition(min(saved_pos, max(0, doc.characterCount() - 1)))
        editor.setTextCursor(restore)

    def _insert_checkbox(self):
        ed = self._editor()
        if ed:
            ed.textCursor().insertText(f"- {_CB_UNCHECKED} ")

    def _insert_bullet(self):
        ed = self._editor()
        if ed:
            ed.textCursor().insertText("- ")

    def _set_font_family(self, family: str):
        self._font_family = family
        font = QFont(family, self._font_size)
        for note in self._tabs:
            note.editor.setFont(font)
            note.editor.document().setDefaultFont(font)
            self._apply_heading_styles(note.editor)
        for f, act in self._font_actions.items():
            act.setChecked(f == family)
        self._font_menu.setTitle(f"Font: {family}")
        self._save_state()

    def _set_font_size(self, size: int):
        self._font_size = size
        font = QFont(self._font_family, size)
        for note in self._tabs:
            note.editor.setFont(font)
            note.editor.document().setDefaultFont(font)
            self._apply_heading_styles(note.editor)
        for s, act in self._size_actions.items():
            act.setChecked(s == size)
        self._size_menu.setTitle(f"Size: {size}")
        self._save_state()

    # ── Export ───────────────────────────────────────────────────────────────

    def _export_pdf(self):
        note = self._current_note
        if note is None:
            return
        if note.current_file is None:
            QMessageBox.information(self, "Export PDF", "Save the note first.")
            return
        default_name = note.current_file.with_suffix(".pdf").name
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export to PDF", str(Path.home() / default_name), "PDF Files (*.pdf)")
        if not dest:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(dest)
        note.editor.document().print(printer)

    # ── State persistence ────────────────────────────────────────────────────

    def _load_state(self):
        try:
            state = json.loads(self._config_path.read_text(encoding="utf-8")) \
                if self._config_path.exists() else {}
        except Exception:
            state = {}

        family = state.get("font_family", _DEFAULT_FONT_FAMILY)
        size   = int(state.get("font_size", _DEFAULT_FONT_SIZE))
        self._font_family        = family
        self._font_size          = size
        self._heading_underline  = bool(state.get("heading_underline", True))
        self._heading_underline_act.setChecked(self._heading_underline)
        font = QFont(family, size)
        for f, act in self._font_actions.items():
            act.setChecked(f == family)
        self._font_menu.setTitle(f"Font: {family}")
        for s, act in self._size_actions.items():
            act.setChecked(s == size)
        self._size_menu.setTitle(f"Size: {size}")

        # Restore open tabs
        open_tabs  = state.get("open_tabs", [])
        active_tab = int(state.get("active_tab", 0))

        # Fall back to legacy single-file key
        if not open_tabs:
            last = state.get("last_file")
            if last:
                open_tabs = [last]

        if open_tabs:
            for path_str in open_tabs:
                p = Path(path_str)
                if p.exists() and p.is_file():
                    self._open_file(p)
            # Set active tab
            if 0 <= active_tab < self._tab_widget.count():
                self._tab_widget.setCurrentIndex(active_tab)
        else:
            # No files to restore — start with one blank tab
            if not self._tabs:
                self._new_tab()

        self._update_ui_for_current_tab()

    def _save_state(self):
        open_tabs = [
            str(note.current_file)
            for note in self._tabs
            if note.current_file is not None
        ]
        state = {
            "open_tabs":         open_tabs,
            "active_tab":        self._tab_widget.currentIndex(),
            "font_family":       self._font_family,
            "font_size":         self._font_size,
            "heading_underline": self._heading_underline,
            "was_open":          True,
            # Legacy key — keep for downgrade compatibility
            "last_file": str(self._current_note.current_file)
                         if self._current_note and self._current_note.current_file
                         else None,
        }
        try:
            self._config_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def mark_closed(self):
        try:
            state = json.loads(self._config_path.read_text(encoding="utf-8")) \
                if self._config_path.exists() else {}
        except Exception:
            state = {}
        state["was_open"] = False
        try:
            self._config_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ── Qt overrides ─────────────────────────────────────────────────────────

    def closeEvent(self, event):
        # Save all tabs before closing
        for i in range(len(self._tabs)):
            self._save_tab(i)
        self._save_state()
        self.mark_closed()
        event.accept()

    def hideEvent(self, event):
        for i in range(len(self._tabs)):
            note = self._tabs[i]
            if note.dirty and note.current_file is not None:
                self._write_tab_file(i, note.current_file)
        self._save_state()
        self.mark_closed()
        super().hideEvent(event)

    def showEvent(self, event):
        try:
            state = json.loads(self._config_path.read_text(encoding="utf-8")) \
                if self._config_path.exists() else {}
        except Exception:
            state = {}
        state["was_open"] = True
        try:
            self._config_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass
        super().showEvent(event)

    def keyPressEvent(self, event):
        event.accept()

    # ── Public API ───────────────────────────────────────────────────────────

    def save_and_close(self):
        """Called by MainWindow on app exit."""
        for i in range(len(self._tabs)):
            note = self._tabs[i]
            if note.dirty and note.current_file is not None:
                self._write_tab_file(i, note.current_file)
        self._save_state()
        self.mark_closed()

    def apply_theme(self, canvas_hex) -> None:
        for note in self._tabs:
            note.editor.setStyleSheet(
                "QTextEdit { background-color: #292A35; color: #FFFFFF; "
                "border: 1px solid #4B4D63; }"
            )
        self._status.setStyleSheet(
            "color: #8C8D9B; font-size: 10px; padding: 2px 6px;"
        )


# ── Helper ────────────────────────────────────────────────────────────────────

def _a(menu, label: str, slot, shortcut: str = "") -> QAction:
    act = QAction(label, menu)
    if shortcut:
        act.setShortcut(QKeySequence(shortcut))
    act.triggered.connect(slot)
    menu.addAction(act)
    return act
