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

"""PDFBookmarksManager — user-defined PDF bookmarks stored in pdfbookmarks.json.

Kept separate from settings.json because bookmarks are content data that grow
over time, not configuration. This lets them be backed up or cleared independently
without touching application preferences.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


class PDFBookmarksManager:
    """
    Persists user bookmarks in:
        %APPDATA%/SoloCanvas/pdfbookmarks.json  (Windows)
        ~/.local/share/SoloCanvas/pdfbookmarks.json  (Linux)

    Structure:
        {
          "version": 1,
          "bookmarks": {
            "/abs/path/to/file.pdf": [
              {"page": 3,  "label": "Character Creation"},
              {"page": 47, "label": "Combat Rules"}
            ]
          }
        }
    """

    VERSION = 1

    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / "pdfbookmarks.json"
        self._data: Dict[str, Any] = {
            "version": self.VERSION,
            "bookmarks": {},
        }
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._data["bookmarks"] = raw.get("bookmarks", {})
        except Exception:
            pass

    def save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Return bookmark list for *pdf_path* (empty list if none)."""
        return list(self._data["bookmarks"].get(pdf_path, []))

    def add(self, pdf_path: str, page: int, label: str) -> None:
        """Add a bookmark; silently ignores duplicate page numbers."""
        entries: List[Dict[str, Any]] = self._data["bookmarks"].setdefault(pdf_path, [])
        if any(e["page"] == page for e in entries):
            return
        entries.append({"page": page, "label": label})
        entries.sort(key=lambda e: e["page"])
        self.save()

    def remove(self, pdf_path: str, index: int) -> None:
        """Remove bookmark at *index* for *pdf_path*."""
        entries = self._data["bookmarks"].get(pdf_path, [])
        if 0 <= index < len(entries):
            entries.pop(index)
            self.save()

    def rename(self, pdf_path: str, index: int, new_label: str) -> None:
        """Rename bookmark at *index* for *pdf_path*."""
        entries = self._data["bookmarks"].get(pdf_path, [])
        if 0 <= index < len(entries):
            entries[index]["label"] = new_label
            self.save()

    # ------------------------------------------------------------------
    # One-time migration from settings.json
    # ------------------------------------------------------------------

    def migrate_from_settings(self, old_bm_dict: Dict[str, Any]) -> None:
        """Copy legacy bookmarks from settings.json into this manager.

        Called once on first load when settings.json still has a non-empty
        ``pdf.user_bookmarks`` key.  Existing entries are preserved; the
        caller is responsible for clearing the old key afterwards.
        """
        if not old_bm_dict:
            return
        changed = False
        for path, entries in old_bm_dict.items():
            if path not in self._data["bookmarks"]:
                self._data["bookmarks"][path] = list(entries)
                changed = True
        if changed:
            self.save()
