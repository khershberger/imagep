"""Application preferences management.

Provides a singleton-style Preferences object responsible for loading and
persisting user settings to a JSON file located in the OS specific config
location using QStandardPaths.

Schema (version 1):
{
    "version": 1,
    "default_zoom": 1.0,                 # float zoom multiplier (1.0 = 100%)
    "background_color": "#000000",       # CSS style color string
    "show_grid": true,                   # bool grid visibility
    "recent_files_max": 10,              # int maximum number of recent files
    "recent_files": [],                  # list[str] MRU list (most recent first)
    "annotation_defaults": {             # default properties when creating new annotations
        "text_color": "#0000FF",        # color string
        "font_size": 18                  # int font size
    }
}

Usage:
    prefs = get_preferences()
    zoom = prefs.default_zoom
    prefs.background_color = "#222222"
    prefs.save()

Signals:
    changed(str key, object value) -- emitted when a preference value changes.

Edge cases handled:
    - Missing or corrupt JSON -> fall back to defaults and write fresh file.
    - Invalid color strings -> fallback to previous valid value.
    - Duplicate recent file entries -> dedup preserving order.
    - Recent file list exceeds max -> truncated automatically.

"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import QObject, Signal, QStandardPaths

__all__ = ["Preferences", "get_preferences"]

_DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "default_zoom": 1.0,
    "background_color": "#000000",
    "show_grid": True,
    "recent_files_max": 10,
    "recent_files": [],
    "annotation_defaults": {
        "text_color": "#0000FF",
        "font_size": 18,
    },
}


def _config_path() -> Path:
    """Return the canonical JSON preferences file path for this application.

    Uses QStandardPaths.AppConfigLocation which typically maps to:
        Windows: %APPDATA%/<AppName>
        Linux:   ~/.config/<AppName>
        macOS:   ~/Library/Application Support/<AppName>
    """
    base_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "preferences.json"


class Preferences(QObject):
    """Preference manager with load/save and change notification.

    Access through the module level `get_preferences()` to reuse instance.
    """

    changed = Signal(str, object)  # key, value

    def __init__(self):
        super().__init__()
        self._path = _config_path()
        self._data: Dict[str, Any] = {}
        self.load()

    # --- Core persistence -------------------------------------------------
    def load(self) -> None:
        """Load preferences from disk or initialize defaults on failure."""
        if self._path.exists():
            try:
                with self._path.open("rt", encoding="utf-8") as fin:
                    self._data = json.load(fin)
            except Exception:
                # Backup corrupt file
                try:
                    corrupt_path = self._path.with_suffix(".corrupt")
                    self._path.rename(corrupt_path)
                except Exception:
                    pass
                self._data = json.loads(json.dumps(_DEFAULTS))
        else:
            self._data = json.loads(json.dumps(_DEFAULTS))
        # Ensure all defaults present (forward compat/migrations)
        for k, v in _DEFAULTS.items():
            if k not in self._data:
                self._data[k] = json.loads(json.dumps(v)) if isinstance(v, dict) else v

    def save(self) -> None:
        """Persist current preferences to disk."""
        try:
            with self._path.open("wt", encoding="utf-8") as fout:
                json.dump(self._data, fout, indent=4)
        except Exception:
            pass  # Silently ignore for now; could log

    # --- Helpers & Validation ---------------------------------------------
    @staticmethod
    def _valid_color(value: str) -> bool:
        if not isinstance(value, str):
            return False
        if value.startswith("#") and len(value) in {4, 7}:
            hex_part = value[1:]
            return all(c in "0123456789abcdefABCDEF" for c in hex_part)
        # Allow simple named colors (basic)
        return value.lower() in {
            "black",
            "white",
            "red",
            "green",
            "blue",
            "gray",
            "grey",
        }

    def _set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.changed.emit(key, value)

    # --- Public properties -------------------------------------------------
    @property
    def default_zoom(self) -> float:
        return float(self._data.get("default_zoom", _DEFAULTS["default_zoom"]))

    @default_zoom.setter
    def default_zoom(self, value: float) -> None:
        try:
            v = float(value)
            if v <= 0:
                return
            self._set("default_zoom", v)
        except (TypeError, ValueError):
            return

    @property
    def background_color(self) -> str:
        return self._data.get("background_color", _DEFAULTS["background_color"])  # type: ignore

    @background_color.setter
    def background_color(self, value: str) -> None:
        if self._valid_color(value):
            self._set("background_color", value)

    @property
    def show_grid(self) -> bool:
        return bool(self._data.get("show_grid", _DEFAULTS["show_grid"]))

    @show_grid.setter
    def show_grid(self, value: bool) -> None:
        self._set("show_grid", bool(value))

    @property
    def recent_files_max(self) -> int:
        return int(self._data.get("recent_files_max", _DEFAULTS["recent_files_max"]))

    @recent_files_max.setter
    def recent_files_max(self, value: int) -> None:
        try:
            v = int(value)
            if v <= 0:
                return
            self._set("recent_files_max", v)
            self._trim_recent_files()
        except (TypeError, ValueError):
            return

    @property
    def recent_files(self) -> List[str]:
        return list(self._data.get("recent_files", []))

    def add_recent_file(self, path: str) -> None:
        path = os.path.abspath(path)
        files = self.recent_files
        if path in files:
            files.remove(path)
        files.insert(0, path)
        self._data["recent_files"] = files
        self._trim_recent_files()
        self.changed.emit("recent_files", self.recent_files)

    def _trim_recent_files(self) -> None:
        max_len = self.recent_files_max
        files = self._data.get("recent_files", [])
        if len(files) > max_len:
            self._data["recent_files"] = files[:max_len]

    @property
    def annotation_defaults(self) -> Dict[str, Any]:
        defaults = self._data.get(
            "annotation_defaults", _DEFAULTS["annotation_defaults"]
        )
        # Defensive copy
        return {
            "text_color": defaults.get(
                "text_color", _DEFAULTS["annotation_defaults"]["text_color"]
            ),
            "font_size": defaults.get(
                "font_size", _DEFAULTS["annotation_defaults"]["font_size"]
            ),
        }

    def set_annotation_default(self, key: str, value: Any) -> None:
        if key not in {"text_color", "font_size"}:
            return
        ann = self._data.setdefault("annotation_defaults", {})
        if key == "text_color":
            if not self._valid_color(value):
                return
        if key == "font_size":
            try:
                v = int(value)
                if v <= 0:
                    return
                value = v
            except (TypeError, ValueError):
                return
        ann[key] = value
        self.changed.emit("annotation_defaults", self.annotation_defaults)


# --- Singleton accessor ----------------------------------------------------
_singleton: Preferences | None = None


def get_preferences() -> Preferences:
    """Return singleton preferences instance."""
    global _singleton
    if _singleton is None:
        _singleton = Preferences()
    return _singleton


if __name__ == "__main__":  # basic sanity test
    p = get_preferences()
    print("Loaded preferences from", p._path)
    p.add_recent_file("/tmp/example.json")
    p.background_color = "#222222"
    p.default_zoom = 2.0
    p.set_annotation_default("font_size", 24)
    p.save()
    print(json.dumps(p._data, indent=2))
