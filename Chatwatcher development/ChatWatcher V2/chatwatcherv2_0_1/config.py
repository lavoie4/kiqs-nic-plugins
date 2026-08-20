"""Namespaced ChatWatcher settings with JSON persistence."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


DEFAULT_SETTINGS = {
    "played": {
        "enabled": True,
        "retention": "1 day",
        "hidden_users": [],
        "now_playing_markers": [
            "np:",
            "now playing",
            "is now listening to",
            "is having an eargasm to",
        ],
    },
    "keywords": {"enabled": True, "keywords": [], "case_sensitive": False},
    "shitlist": {"enabled": False, "mode": "automatic", "keywords": []},
}


class Config:
    def __init__(self, file_path: str | Path | None = None):
        self.file_path = Path(file_path) if file_path else None
        self.settings = deepcopy(DEFAULT_SETTINGS)
        if self.file_path:
            self.load_config(self.file_path)

    def load_config(self, file_path: str | Path | None = None):
        path = Path(file_path or self.file_path)
        if not path or not path.is_file():
            return
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for feature, values in loaded.items():
            if feature in self.settings and isinstance(values, dict):
                self.settings[feature].update(values)

    def save_config(self, file_path: str | Path | None = None):
        path = Path(file_path or self.file_path)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")

    def get_setting(self, feature, setting, default=None):
        return self.settings.get(feature, {}).get(setting, default)

    def set_setting(self, feature, setting, value):
        if feature not in self.settings:
            raise KeyError(f"Unknown feature: {feature}")
        self.settings[feature][setting] = value