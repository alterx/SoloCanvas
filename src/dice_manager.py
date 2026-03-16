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

"""DiceSetsManager – manages dice colour sets and PNG face rendering."""
from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).parent.parent

DICE_DIR = _BASE / "Dice"

# ---------------------------------------------------------------------------
# Die type definitions
# ---------------------------------------------------------------------------

DIE_TYPES = ["d2", "d4", "d6", "d8", "d10", "d12", "d20", "d100"]

DIE_MAX = {
    "d2":  2,
    "d4":  4,
    "d6":  6,
    "d8":  8,
    "d10": 10,
    "d12": 12,
    "d20": 20,
    "d100": 100,
}

# Scale factors applied when painting die faces.
# D2/D4/D6 fill their full PNG bounds so they render slightly smaller to balance
# against the rounder D8–D100 shapes. D8–D100 are scaled up to compensate for
# their extra transparent padding (derived from bounding-box fill analysis).
_DIE_PAINT_SCALE: Dict[str, float] = {
    "d2":   0.92,
    "d4":   0.92,
    "d6":   0.92,
    "d8":   1.024,
    "d10":  1.065,
    "d12":  1.036,
    "d20":  1.106,
    "d100": 1.065,
}

# Subfolder name inside DICE_DIR for each die type's face PNGs
_DIE_FOLDER: Dict[str, str] = {
    "d2":  "D2",
    "d4":  "D4",
    "d6":  "D6",
    "d8":  "D8",
    "d10": "D10",
    "d12": "D12",
    "d20": "D20",
    "d100": "D100",
}


# ---------------------------------------------------------------------------
# Face helpers
# ---------------------------------------------------------------------------

def face_values(die_type: str) -> list:
    """Return all valid face values for a die type (used for roll animation cycling)."""
    if die_type == "d100":
        return [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    if die_type == "d10":
        # Files are 0–9; we use values 1–10 where 10 maps to "0.png"
        return list(range(1, 11))
    return list(range(1, DIE_MAX.get(die_type, 6) + 1))


def roll_value(die_type: str) -> int:
    """Return a random roll result for the given die type."""
    if die_type == "d100":
        return random.choice([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
    return random.randint(1, DIE_MAX.get(die_type, 6))


def _face_filename(die_type: str, value: int) -> str:
    """Return the PNG filename (without folder) for a given face value."""
    if die_type == "d100":
        # Files named: d10_white_00.png, d10_white_10.png, … d10_white_90.png
        face = "00" if value == 100 else str(value)
        return f"d10_white_{face}.png"
    if die_type == "d10":
        # Files named 0.png–9.png; value 10 maps to "0.png"
        return "0.png" if value == 10 else f"{value}.png"
    return f"{value}.png"


# ---------------------------------------------------------------------------
# Colour spec helpers
# ---------------------------------------------------------------------------

def _normalise_spec(raw) -> dict:
    """Convert a stored colour value (str or dict) to a canonical spec dict."""
    if isinstance(raw, str):
        return {"type": "solid", "color1": raw, "color2": "#000000", "center": 0.5}
    return {
        "type":   raw.get("type",   "solid"),
        "color1": raw.get("color1", "#ffffff"),
        "color2": raw.get("color2", "#000000"),
        "center": float(raw.get("center", 0.5)),
    }


def _is_white_solid(spec: dict) -> bool:
    return spec["type"] == "solid" and spec["color1"].lower() == "#ffffff"


def _apply_overlay(pix: QPixmap, spec: dict) -> QPixmap:
    """Apply a solid/radial/vertical colour overlay to *pix*, respecting alpha."""
    from PyQt6.QtGui import QBrush, QLinearGradient, QRadialGradient

    w = pix.width()
    h = pix.height()
    mode   = spec["type"]
    color1 = QColor(spec["color1"])
    color2 = QColor(spec["color2"])
    center = max(0.0, min(1.0, spec["center"]))

    # Build the fill brush
    if mode == "radial":
        cx   = w / 2.0
        cy   = h / 2.0
        r    = min(w, h) * 0.65
        fx   = cx - w * 0.10
        fy   = cy - h * 0.15
        grad = QRadialGradient(fx, fy, r)
        grad.setColorAt(center * 0.8, color1)
        grad.setColorAt(1.0, color2)
        brush = QBrush(grad)
    elif mode == "vertical":
        y1   = (center - 0.5) * h
        y2   = (center + 0.5) * h
        grad = QLinearGradient(0, y1, 0, y2)
        grad.setColorAt(0.0, color1)
        grad.setColorAt(1.0, color2)
        brush = QBrush(grad)
    else:  # solid
        c = QColor(color1)
        c.setAlpha(242)   # 95% opacity
        brush = QBrush(c)

    # Build colour layer with die's alpha, then multiply-blend onto base
    color_layer = QPixmap(pix.size())
    color_layer.fill(Qt.GlobalColor.transparent)
    cp = QPainter(color_layer)
    cp.drawPixmap(0, 0, pix)                                     # copy alpha
    cp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    if mode == "solid":
        cp.fillRect(color_layer.rect(), brush)
    else:
        # Gradient brushes need alpha=242 for the 95% opacity effect
        cp.setOpacity(242 / 255)
        cp.fillRect(color_layer.rect(), brush)
        cp.setOpacity(1.0)
    cp.end()

    result = QPixmap(pix.size())
    result.fill(Qt.GlobalColor.transparent)
    p = QPainter(result)
    p.drawPixmap(0, 0, pix)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
    p.drawPixmap(0, 0, color_layer)
    # Second pass: multiply the original shading back in.
    # base² × color deepens shadows while keeping highlights close to the custom colour.
    p.drawPixmap(0, 0, pix)
    p.end()
    return result


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DiceSet:
    name: str
    colors: Dict[str, str]   # die_type → "#rrggbb"
    is_builtin: bool = False

    def to_dict(self) -> dict:
        return {
            "name":       self.name,
            "colors":     dict(self.colors),
            "is_builtin": self.is_builtin,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DiceSet":
        raw_colors = d.get("colors", {})
        colors = {}
        for die_type, val in raw_colors.items():
            if isinstance(val, str):
                colors[die_type] = val
            elif isinstance(val, dict):
                # Preserve full gradient spec; plain string was the old format
                colors[die_type] = dict(val)
        return cls(
            name=d.get("name", "Unnamed"),
            colors=colors,
            is_builtin=bool(d.get("is_builtin", False)),
        )


_BUILTIN_WHITE = DiceSet(
    name="White",
    colors={t: "#ffffff" for t in DIE_TYPES},
    is_builtin=True,
)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class DiceSetsManager:
    """Loads/saves dice colour sets and renders die face PNGs as QPixmaps."""

    def __init__(self) -> None:
        self._sets: Dict[str, DiceSet] = {}
        # Cache key: (die_type, face_value, color_hex, size_px)
        self._cache: Dict[Tuple[str, int, str, int], QPixmap] = {}
        self.load_sets()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_path(self) -> Path:
        import os
        appdata = Path(os.environ.get("APPDATA", Path.home()))
        return appdata / "SoloCanvas" / "dice_sets.json"

    def load_sets(self) -> None:
        self._sets.clear()
        self._sets[_BUILTIN_WHITE.name] = _BUILTIN_WHITE

        path = self._save_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for entry in data:
                    ds = DiceSet.from_dict(entry)
                    if not ds.is_builtin:
                        self._sets[ds.name] = ds
            except Exception:
                pass

    def save_sets(self) -> None:
        path = self._save_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [ds.to_dict() for ds in self._sets.values() if not ds.is_builtin]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ------------------------------------------------------------------
    # Set management
    # ------------------------------------------------------------------

    def set_names(self) -> list:
        return list(self._sets.keys())

    def get_set(self, name: str) -> Optional[DiceSet]:
        return self._sets.get(name)

    def add_or_replace_set(self, dice_set: DiceSet) -> None:
        if dice_set.is_builtin:
            return
        self._sets[dice_set.name] = dice_set
        keys_to_remove = [k for k in self._cache if k[1] == dice_set.name]
        for k in keys_to_remove:
            del self._cache[k]
        self.save_sets()

    def delete_set(self, name: str) -> bool:
        ds = self._sets.get(name)
        if ds is None or ds.is_builtin:
            return False
        del self._sets[name]
        keys_to_remove = [k for k in self._cache if k[1] == name]
        for k in keys_to_remove:
            del self._cache[k]
        self.save_sets()
        return True

    # ------------------------------------------------------------------
    # Pixmap rendering
    # ------------------------------------------------------------------

    def get_face_pixmap(
        self,
        die_type: str,
        face_value: int,
        set_name: str,
        size_px: int,
    ) -> QPixmap:
        """Return a QPixmap of the given die face at size_px × size_px, cached.

        Applies a multiply colour overlay for non-white sets.
        """
        ds = self._sets.get(set_name) or _BUILTIN_WHITE
        # Fall back to first colour in set if this die type isn't defined
        # (handles sets saved before d2/d100 were added)
        raw = ds.colors.get(die_type) or next(iter(ds.colors.values()), "#ffffff")
        spec = _normalise_spec(raw)

        spec_key = f"{spec['type']}{spec['color1']}{spec['color2']}{spec['center']}"
        key = (die_type, face_value, spec_key, size_px)
        if key in self._cache:
            return self._cache[key]

        pix = self._load_base(die_type, face_value, size_px)
        if not pix.isNull() and not _is_white_solid(spec):
            pix = _apply_overlay(pix, spec)

        self._cache[key] = pix
        return pix

    def get_preview_pixmap(self, die_type: str, set_name: str, size_px: int) -> QPixmap:
        """Return the max-face pixmap for use as a library preview icon."""
        max_val = DIE_MAX.get(die_type, 6)
        return self.get_face_pixmap(die_type, max_val, set_name, size_px)

    def get_face_pixmap_for_preview(
        self, die_type: str, spec: dict, size_px: int
    ) -> QPixmap:
        """Render a face with a spec dict directly — used by DiceColorDialog preview."""
        max_val = DIE_MAX.get(die_type, 6)
        pix = self._load_base(die_type, max_val, size_px)
        if not pix.isNull() and not _is_white_solid(spec):
            pix = _apply_overlay(pix, spec)
        return pix

    def _load_base(self, die_type: str, face_value: int, size_px: int) -> QPixmap:
        folder   = _DIE_FOLDER.get(die_type, die_type.upper())
        filename = _face_filename(die_type, face_value)
        png_path = DICE_DIR / folder / filename
        pix = QPixmap(str(png_path))
        if pix.isNull():
            pix = QPixmap(size_px, size_px)
            pix.fill(QColor("#888888"))
            return pix

        scale = _DIE_PAINT_SCALE.get(die_type, 1.0)
        if scale == 1.0:
            return pix.scaled(
                size_px, size_px,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        # Scale die up slightly and center-clip into size_px canvas so it
        # appears larger without changing the item's bounding rect.
        big_size = round(size_px * scale)
        big_pix  = pix.scaled(
            big_size, big_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        result = QPixmap(size_px, size_px)
        result.fill(Qt.GlobalColor.transparent)
        p = QPainter(result)
        offset_x = (size_px - big_pix.width())  // 2
        offset_y = (size_px - big_pix.height()) // 2
        p.drawPixmap(offset_x, offset_y, big_pix)
        p.end()
        return result
