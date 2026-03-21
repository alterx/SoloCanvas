# Copyright © 2026 Geoffrey Osterberg
#
# SoloCanvas is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Persist user-saved custom decks (virtual decks) for the Deck Library."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

STORE_VERSION = 1

_CANVAS_KEYS = frozenset({
    "canvas_x", "canvas_y", "rotation", "face_up", "is_stack",
    "reversal_enabled", "grid_snap",
})


def strip_canvas_meta(deck: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in deck.items() if k not in _CANVAS_KEYS}


def load_entries(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("entries", []))
    except Exception:
        return []


def save_entries(path: Path, entries: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": STORE_VERSION, "entries": entries}, f, indent=2)


def add_entry(path: Path, display_name: str, deck_model_dict: Dict[str, Any]) -> str:
    entries = load_entries(path)
    entry_id = str(uuid.uuid4())
    deck = strip_canvas_meta(dict(deck_model_dict))
    deck["name"] = display_name.strip() or deck.get("name") or "Custom deck"
    entries.append({
        "entry_id": entry_id,
        "name": deck["name"],
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "deck": deck,
    })
    save_entries(path, entries)
    return entry_id


def delete_entry(path: Path, entry_id: str) -> bool:
    entries = load_entries(path)
    n = len(entries)
    entries = [e for e in entries if e.get("entry_id") != entry_id]
    if len(entries) == n:
        return False
    save_entries(path, entries)
    return True


def rename_entry(path: Path, entry_id: str, new_name: str) -> bool:
    new_name = new_name.strip()
    if not new_name:
        return False
    entries = load_entries(path)
    for e in entries:
        if e.get("entry_id") == entry_id:
            e["name"] = new_name
            if isinstance(e.get("deck"), dict):
                e["deck"]["name"] = new_name
            save_entries(path, entries)
            return True
    return False


def get_entry(path: Path, entry_id: str) -> Optional[Dict[str, Any]]:
    for e in load_entries(path):
        if e.get("entry_id") == entry_id:
            return e
    return None
