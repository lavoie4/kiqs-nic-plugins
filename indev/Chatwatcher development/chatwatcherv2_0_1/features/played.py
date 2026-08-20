"""Played/now-playing collection and JSONL storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path


@dataclass
class PlayedEntry:
    timestamp: str
    user: str
    message: str
    source: str
    is_self: bool = False


class PlayedFeature:
    def __init__(self, config, log_dir: str | Path = "logs"):
        self.config = config
        self.log_dir = Path(log_dir) / "listenings"
        self.now_playing_log: list[PlayedEntry] = []
        self.blocked_users = {
            str(user).casefold()
            for user in config.get_setting("played", "hidden_users", [])
        }

    def capture_now_playing(self, user, message, source="unknown", is_self=False):
        if not self.is_now_playing(message) or user.casefold() in self.blocked_users:
            return False
        entry = PlayedEntry(
            datetime.now().isoformat(timespec="seconds"), user, message, source, is_self
        )
        self.now_playing_log.insert(0, entry)
        self.log_now_playing(entry)
        return True

    def is_now_playing(self, message):
        markers = self.config.get_setting("played", "now_playing_markers", [])
        text = message.casefold()
        return bool(message.strip()) and any(str(marker).casefold() in text for marker in markers)

    def log_now_playing(self, entry):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        date = datetime.now().strftime("%Y-%m-%d")
        path = self.log_dir / f"log1[{date}].log"
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def block_user(self, user):
        self.blocked_users.add(user)
        self._save_hidden_users()

    def unblock_user(self, user):
        self.blocked_users.discard(user)
        self._save_hidden_users()

    def get_now_playing_log(self):
        return self.now_playing_log

    def clear_log(self):
        self.now_playing_log.clear()

    def _save_hidden_users(self):
        self.config.set_setting("played", "hidden_users", sorted(self.blocked_users))
        self.config.save_config()