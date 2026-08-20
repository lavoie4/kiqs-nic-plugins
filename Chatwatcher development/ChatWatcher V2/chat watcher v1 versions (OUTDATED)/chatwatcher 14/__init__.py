# SPDX-License-Identifier: GPL-3.0-or-later
"""Chat watcher v1 — Played + Keywords + Shitlist, merged.

A single Nicotine+ plugin that keeps every feature of the three plugins it
replaces, namespaced so the settings, logs and chat commands never collide:

1. **Played**  — collect other users' ``/nowplaying`` (``/me``) output into
   a "Played" tab, with retention and user blocking.
2. **Keywords** — collect other users' messages that mention your keywords
   into a "Keywords" tab, in public rooms and private chat.
3. **Shitlist**  — ban+ignore users who say keywords, add a temporary
   "Ignore for…" menu to the user right-click menu, a managed Shitlisted Users
   list, and a "show messages from ignored users" whitelist.

See README.md for full usage instructions.
"""

import json
import os
import re
import time

from pynicotine.events import events
from pynicotine.pluginsystem import BasePlugin


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

LISTENINGS_TAB_NAME = "Played"
LISTENINGS_TAB_ID = "listenings"
LISTENINGS_LOG_FILENAME = "listenings.log"

KEYWORDWATCH_TAB_NAME = "Keywords"
KEYWORDWATCH_TAB_ID = "keywordwatch"
KEYWORDWATCH_LOG_FILENAME = "keywordwatch.log"

SHITLIST_TAB_NAME = "Shitlist"
SHITLIST_TAB_ID = "shitlist"
SHITLIST_LOG_FILENAME = "shitlist.log"

LOG_SUBFOLDER = "logs"
LOG_DATE_FORMAT = "%Y-%m-%d"

RETENTION_SECONDS = {
    "20 min": 20 * 60,
    "1 hr": 60 * 60,
    "12 hr": 12 * 60 * 60,
    "1 day": 24 * 60 * 60,
    "3 days": 3 * 24 * 60 * 60,
    "7 days": 7 * 24 * 60 * 60,
}

# Substrings that mark an auto "now playing" /me announcement. A song/artist
# title can itself contain a keyword, so Shitlist must NOT ban on these; the
# Played tab uses them to filter out stray /me emote lines. User-editable.
DEFAULT_NOW_PLAYING_MARKERS = [
    "np:",
    "is now listening to",
    "now listening to",
    "is now playing",
    "now playing:",
]


class Plugin(BasePlugin):

    # (label, seconds) for the temporary "Ignore for..." context menu.
    IGNORE_DURATIONS = (
        ("20 min", 20 * 60),
        ("1 hr", 60 * 60),
        ("12 hr", 12 * 60 * 60),
        ("1 day", 24 * 60 * 60),
        ("3 days", 3 * 24 * 60 * 60),
        ("7 days", 7 * 24 * 60 * 60),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # --- user-facing settings (shown in Settings -> Plugins) ---
        # Every key is namespaced so the three feature sets stay independent.
        self.settings = {
            # Listenings
            "listenings_enabled": True,
            "listenings_blocked_users": [],
            "listenings_retention": "1 day",
            "nowplaying_markers": list(DEFAULT_NOW_PLAYING_MARKERS),
            # Keyword Watch
            "kw_enabled": True,
            "kw_keywords": [],
            "kw_case_sensitive": False,
            "kw_blocked_users": [],
            "kw_retention": "1 day",
            # Shitlist
            "shitlist_enabled": True,
            "shitlist_manual_review": False,
            "shitlist_keywords": [],
            "shitlist_users": [],
            "shitlist_show_messages": [],
            "shitlist_whitelist_users": [],
            "shitlist_retention": "7 days",
            # log rotation bookkeeping (first day each feature started logging)
            "listenings_log_start": "",
            "kw_log_start": "",
            "shitlist_log_start": "",
        }

        self.metasettings = {
            "listenings_enabled": {
                "description": "Played — show the Played tab\nDisabling this turns the whole /nowplaying feature off.",
                "group": "Played (/nowplaying)",
                "type": "bool",
            },
            "listenings_blocked_users": {
                "description": "Played — hide these users (one username per line)",
                "group": "Played (/nowplaying)",
                "type": "list string",
            },
            "listenings_retention": {
                "description": "Played — keep entries for",
                "group": "Played (/nowplaying)",
                "type": "dropdown",
                "options": tuple(RETENTION_SECONDS.keys()),
            },
            "nowplaying_markers": {
                "description": "Now-playing markers — a /me line containing any of these is treated as an auto 'now playing' announcement (shown in Played; ignored by Shitlist so song titles don't trigger keyword bans). One per line.",
                "group": "Played (/nowplaying)",
                "type": "list string",
            },
            "kw_enabled": {
                "description": "Keywords — show the Keywords tab\nDisabling this turns the whole keyword-watch feature off.",
                "group": "Keywords",
                "type": "bool",
            },
            "kw_keywords": {
                "description": "Keywords — words to look for (one per line; leave empty to watch your username)",
                "group": "Keywords",
                "type": "list string",
            },
            "kw_case_sensitive": {
                "description": "Keywords — match keywords case-sensitively",
                "group": "Keywords",
                "type": "bool",
            },
            "kw_blocked_users": {
                "description": "Keywords — hide these users\nTheir messages, profile views and downloads won't show in the Keywords tab (one username per line).",
                "group": "Keywords",
                "type": "list string",
            },
            "kw_retention": {
                "description": "Keywords — keep entries for",
                "group": "Keywords",
                "type": "dropdown",
                "options": tuple(RETENTION_SECONDS.keys()),
            },
        }

        self.commands = {
            "chatwatcher": {
                "callback": self._chatwatcher_command,
                "description": "Open Chat watcher settings (or /cw status|help)",
                "parameters": ["[settings|status|help]"],
            },
            "cw": {
                "callback": self._chatwatcher_command,
                "description": "Shorthand for /chatwatcher",
                "parameters": ["[settings|status|help]"],
            },
            "kw": {
                "callback": self._kw_command,
                "description": "Manage the Keywords list (add/remove/list)",
                "parameters": ["[add|remove|list]", "[keyword]"],
            },
            "shitlist": {
                "callback": self._shitlist_command,
                "description": "Manage Shitlist keywords and open the settings editor",
                "parameters": ["[add|remove|list]", "[keyword]"],
            },
            "played": {
                "callback": self._played_command,
                "description": "Manage the Played tab (clear log, hide/unhide users, list)",
                "parameters": ["[clear|hide|unhide|list]", "[user]"],
            },
        }

        # --- per-feed tab state (Listenings and Keyword Watch) ---
        self._feeds = {
            "listenings": self._new_feed(LISTENINGS_TAB_NAME, LISTENINGS_TAB_ID, LISTENINGS_LOG_FILENAME),
            "keywordwatch": self._new_feed(KEYWORDWATCH_TAB_NAME, KEYWORDWATCH_TAB_ID, KEYWORDWATCH_LOG_FILENAME),
            "shitlist": self._new_feed(SHITLIST_TAB_NAME, SHITLIST_TAB_ID, SHITLIST_LOG_FILENAME),
        }

        # --- header-bar patch state (single MainWindow, both tabs) ---
        self._header_bar_patched = False
        self._original_set_active_header_bar = None
        self._patched_main_window_class = None

        # --- shared timers ---
        self._prune_id = None      # periodic retention pruning

        # --- Shitlist runtime state ---
        self._shitlist_ignore_timers = {}
        self._shitlist_menu_patched = False
        self._shitlist_original_setup_user_menu = None
        self._shitlist_enabled = True
        self._shitlist_show_messages_set = set()

        # --- Keywords runtime state ---
        self._kw_profile_view_times = {}
        self._kw_profile_view_hooked = False

        # --- Import file-dialog keep-alive ---
        self._active_file_dialog = None

    @staticmethod
    def _new_feed(tab_name, tab_id, log_filename):
        return {
            "tab_name": tab_name,
            "tab_id": tab_id,
            "log_filename": log_filename,
            "entries": [],
            "notebook": None,
            "page": None,
            "list_widget": None,
            "rows": [],
            "status_label": None,
            "built": False,
            "build_attempts": 0,
            "build_id": None,
            "active_popover": None,
            "filter": "All",
            "imported_entries": None,
            "imported_path": None,
            "import_button": None,
            "close_button": None,
            "search_bar": None,
            "search_entry": None,
            "search_query": "",
        }

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def init(self):
        self._migrate_legacy_logs()

        # Each feature loads independently so one malformed log line can't abort
        # init() and stop the other tabs from building (the cause of the
        # "banning works but panes don't update" regression).
        if self.settings.get("listenings_enabled", True):
            try:
                self._listenings_load()
                self._listenings_prune()
            except Exception as error:
                self.log("Could not load Played log: %s", (error,))

            self._schedule_build("listenings")

        if self.settings.get("kw_enabled", True):
            try:
                self._kw_load()
                self._kw_prune()
                self._kw_seed_default_keywords()
            except Exception as error:
                self.log("Could not load Keywords log: %s", (error,))

            self._schedule_build("keywordwatch")

        try:
            self._shitlist_load()
            self._shitlist_prune()
        except Exception as error:
            self.log("Could not load Shitlist log: %s", (error,))

        self._schedule_build("shitlist")
        self._start_timers()

    def disable(self):
        self._stop_timers()
        self._remove_tab("listenings")
        self._remove_tab("keywordwatch")
        self._remove_tab("shitlist")
        self._shitlist_enabled = False
        self._shitlist_restore_user_menu()
        self._shitlist_ignore_timers.clear()
        self._kw_unhook_profile_views()
        self._kw_profile_view_times.clear()
        self._restore_header_bar()

    def loaded_notification(self):
        # Listenings
        self.log("Chat watcher v1: logging /nowplaying (/me) messages into the '%s' tab.", LISTENINGS_TAB_NAME)

        # Keyword Watch
        keywords = self.settings.get("kw_keywords", [])

        if keywords:
            self.log("Watching for %d keyword(s) in the '%s' tab.", (len(keywords), KEYWORDWATCH_TAB_NAME))
        else:
            self.log(
                "Keywords has no keywords yet. Add some (e.g. your username) in "
                "Settings -> Plugins -> Chat watcher v1, or type /kw add <word>."
            )

        # Shitlist (patches happen here, matching the original Shitlist plugin)
        self._shitlist_sync_show_messages_set()
        self._shitlist_patch_user_menu()

        # Keywords: profile-view logging via the internal events bus
        self._kw_hook_profile_views()

    # ------------------------------------------------------------------ #
    # Chat hooks — Played (Listenings): /me (now-playing) capture
    #
    # Public-room /me messages are caught in public_room_message_notification()
    # further down (so they work in every joined room, not just the focused
    # one). Private-chat /me and the user's own /me use the hooks below.
    # ------------------------------------------------------------------ #

    def incoming_private_chat_event(self, user, line):
        if self.settings.get("listenings_enabled", True) and line.startswith("/me "):
            text = line[4:].strip()

            if self._is_now_playing(text):
                self._listenings_add_entry(user, text, context="pm")

        return None

    def outgoing_public_chat_event(self, room, line):
        if self.settings.get("listenings_enabled", True) and line.startswith("/me "):
            text = line[4:].strip()

            if self._is_now_playing(text):
                self._listenings_add_entry(self.core.users.login_username, text, is_self=True, context=room)

        return None

    def outgoing_private_chat_event(self, user, line):
        if self.settings.get("listenings_enabled", True) and line.startswith("/me "):
            text = line[4:].strip()

            if self._is_now_playing(text):
                self._listenings_add_entry(self.core.users.login_username, text, is_self=True, context="pm")

        return None

    # ------------------------------------------------------------------ #
    # Chat hooks — Keywords + Shitlist (global "Public" feed + private)
    #
    # public_room_message_notification fires ONLY for the global "Public" room
    # (server code 152, the network-wide public-chat feed). It does NOT fire for
    # individual joined rooms — those take a separate path (server code 13) and
    # fire incoming_public_chat_notification, which this plugin does not hook.
    #
    # The global feed bypasses Nicotine+'s ignore filter (the joined-room path
    # checks is_user_ignored/is_user_ip_ignored, but the global path does not),
    # so we re-apply it here for Played and Shitlist to keep genuinely-ignored
    # users hidden. Keyword Watch is the exception: it intentionally collects
    # keyword hits from ignored/banned users, because their messages still arrive
    # on this feed (#Public). Shitlist's "show messages from ignored users"
    # whitelist is applied locally below (the ignore re-check is skipped for
    # those names), so their messages flow through to the other feeds too.
    # ------------------------------------------------------------------ #

    def public_room_message_notification(self, room, user, line):
        if not user or not line:
            return

        is_ignored = False

        if user != "server" and not self._shitlist_is_whitelisted(user):
            if self.core.network_filter.is_user_ignored(user):
                is_ignored = True
            elif self.core.network_filter.is_user_ip_ignored(user):
                is_ignored = True

        # Keywords: collect keyword hits from *everyone*, bypassing the user's
        # ignore/ban preferences. Ignored users' room messages still arrive here
        # via the #Public (global-room) feed, which skips Nicotine+'s ignore
        # filter.
        if self.settings.get("kw_enabled", True):
            self._kw_check_keywords(user, room or "", line)

        if is_ignored:
            return

        # Played: catch /me (now-playing) actions, rendered as "* <user> <text>"
        if self.settings.get("listenings_enabled", True):
            prefix = f"* {user} "
            if line.startswith(prefix):
                text = line[len(prefix):].strip()

                if self._is_now_playing(text):
                    self._listenings_add_entry(user, text, context=room)

        # Shitlist
        self._shitlist_check_keywords(user, line, room or "")

    def incoming_private_chat_notification(self, user, line):
        if self.settings.get("kw_enabled", True):
            self._kw_check_keywords(user, "", line)

        self._shitlist_check_keywords(user, line, "")

    def upload_finished_notification(self, user, virtual_path, real_path):
        """Someone finished downloading a file from our shares."""

        if not self.settings.get("kw_enabled", True):
            return

        if not user:
            return

        self._kw_add_download(user, virtual_path)

    def _kw_hook_profile_views(self):
        if self._kw_profile_view_hooked:
            return

        try:
            from pynicotine.events import events

            self._kw_profile_view_callback = self._kw_on_user_info_request
            events.connect("user-info-request", self._kw_profile_view_callback)
            self._kw_profile_view_hooked = True
        except Exception:
            pass

    def _kw_unhook_profile_views(self):
        if not self._kw_profile_view_hooked:
            return

        try:
            from pynicotine.events import events

            callback = getattr(self, "_kw_profile_view_callback", None)

            if callback is not None:
                events.disconnect("user-info-request", callback)
        except Exception:
            pass

        self._kw_profile_view_callback = None
        self._kw_profile_view_hooked = False

    def _kw_on_user_info_request(self, msg):
        """Someone requested our user info (viewed our profile)."""

        if not self.settings.get("kw_enabled", True):
            return

        username = getattr(msg, "username", None)

        if not username:
            return

        now = time.monotonic()

        if now < self._kw_profile_view_times.get(username, 0) + 1.0:
            return  # collapse rapid re-requests into one entry

        self._kw_profile_view_times[username] = now
        self._kw_add_profile_view(username)

    # ------------------------------------------------------------------ #
    # Listenings logic
    # ------------------------------------------------------------------ #

    def _listenings_add_entry(self, user, text, is_self=False, context=None):
        if not user or not text:
            return

        if not is_self:
            login = self.core.users.login_username

            if login and user.lower() == login.lower():
                return

            blocked = {u.lower() for u in self.settings.get("listenings_blocked_users", [])}
            if user.lower() in blocked:
                return

        entry = {"ts": time.time(), "user": user, "text": text}

        if is_self:
            entry["self"] = True

        if context:
            entry["context"] = str(context)

        feed = self._feeds["listenings"]
        feed["entries"].insert(0, entry)
        self._listenings_prune()
        self._listenings_save()
        self._listenings_render()

    def _listenings_log_path(self):
        return os.path.join(self._listenings_log_dir(), LISTENINGS_LOG_FILENAME)

    def _migrate_legacy_logs(self):
        """Move old logs (plugin folder and the flat logs/ location) into each
        feature's own logs subfolder."""

        if not self.path:
            return

        base = self._logs_dir()

        migrations = (
            (
                os.path.join(self.path, LISTENINGS_LOG_FILENAME),
                os.path.join(base, LISTENINGS_LOG_FILENAME),
                self._listenings_log_path(),
            ),
            (
                os.path.join(self.path, KEYWORDWATCH_LOG_FILENAME),
                os.path.join(base, KEYWORDWATCH_LOG_FILENAME),
                self._kw_log_path(),
            ),
            (
                os.path.join(self.path, SHITLIST_LOG_FILENAME),
                os.path.join(base, SHITLIST_LOG_FILENAME),
                self._shitlist_log_path(),
            ),
        )

        for old_plugin_path, old_logs_path, new_path in migrations:
            for old_path in (old_plugin_path, old_logs_path):
                if os.path.isfile(old_path) and not os.path.exists(new_path):
                    try:
                        os.makedirs(os.path.dirname(new_path), exist_ok=True)
                        os.replace(old_path, new_path)
                        break
                    except OSError as error:
                        self.log("Could not migrate log file %s: %s", (old_path, error))

    def _listenings_load(self):
        feed = self._feeds["listenings"]
        feed["entries"] = []

        for item in self._load_daily_log(self._listenings_log_dir(), ("ts", "user", "text")):
            ts = self._safe_float(item.get("ts"))

            if not ts:
                continue

            entry = {
                "ts": ts,
                "user": str(item.get("user") or ""),
                "text": str(item.get("text") or ""),
            }

            if self._to_bool(item.get("self")):
                entry["self"] = True

            if item.get("context"):
                entry["context"] = str(item["context"])

            feed["entries"].append(entry)

        feed["entries"].sort(key=lambda entry: entry["ts"], reverse=True)

    def _listenings_save(self):
        self._save_daily_log(
            self._feeds["listenings"]["entries"],
            self._listenings_log_dir(),
            "listenings_log_start",
            "Played",
        )

    def _listenings_prune(self):
        retention = RETENTION_SECONDS.get(self.settings.get("listenings_retention"))

        if not retention:
            return False

        cutoff = time.time() - retention
        feed = self._feeds["listenings"]
        new_entries = [entry for entry in feed["entries"] if entry["ts"] >= cutoff]

        if len(new_entries) == len(feed["entries"]):
            return False

        feed["entries"] = new_entries
        return True

    def _listenings_clear(self):
        self._feeds["listenings"]["entries"] = []
        self._listenings_save()
        self._listenings_render()
        self.log("Played log cleared.")

    def _listenings_remove_entry(self, entry):
        feed = self._feeds["listenings"]
        feed["entries"] = [item for item in feed["entries"] if item is not entry]
        self._listenings_save()
        self._listenings_render()

    def _listenings_copy_entry(self, entry):
        text = self._listenings_format_entry(entry)
        self._copy_to_clipboard(text)
        self.log("Copied entry to clipboard: %s", text)

    def _listenings_format_entry(self, item):
        stamp = time.strftime("%I:%M:%S %p", time.localtime(item["ts"]))
        who = item["user"]

        if item.get("self"):
            who += " (you)"

        if item.get("context") == "pm":
            who += " [pm]"

        return f"{stamp} * {who} {item['text']}"

    # ------------------------------------------------------------------ #
    # Keyword Watch logic
    # ------------------------------------------------------------------ #

    def _kw_check_keywords(self, user, room, line):
        if not user or not line:
            return

        # Seed defaults lazily in case the username wasn't known yet at init().
        self._kw_seed_default_keywords()

        login = self.core.users.login_username
        if login and user.lower() == login.lower():
            return  # only collect *other* users' messages

        blocked = {u.lower() for u in self.settings.get("kw_blocked_users", [])}
        if user.lower() in blocked:
            return

        keywords = [self._normalize_keyword(k) for k in self.settings.get("kw_keywords", [])]
        keywords = [k for k in keywords if k]

        if not keywords:
            return

        case_sensitive = bool(self.settings.get("kw_case_sensitive", False))
        haystack = line if case_sensitive else line.lower()

        matched = []

        for keyword in keywords:
            needle = keyword if case_sensitive else keyword.lower()

            if needle in haystack:
                matched.append(keyword)

        if not matched:
            return

        self._kw_add_entry(user, room, line, matched)

    def _kw_add_entry(self, user, room, text, keywords, kind="kw"):
        feed = self._feeds["keywordwatch"]
        feed["entries"].insert(0, {
            "ts": time.time(),
            "user": user,
            "room": room,
            "text": text,
            "keywords": keywords,
            "kind": kind,
        })
        self._kw_prune()
        self._kw_save()
        self._kw_render()

    def _kw_user_is_blocked(self, user):
        if not user:
            return True

        login = self.core.users.login_username

        if login and user.lower() == login.lower():
            return True

        blocked = {u.lower() for u in self.settings.get("kw_blocked_users", [])}
        return user.lower() in blocked

    def _kw_add_profile_view(self, user):
        if self._kw_user_is_blocked(user):
            return

        self._kw_add_entry(user, "", "viewed your profile", [], kind="profile")

    def _kw_add_download(self, user, virtual_path):
        if self._kw_user_is_blocked(user):
            return

        self._kw_add_entry(user, "", virtual_path or "", [], kind="download")

    def _kw_seed_default_keywords(self):
        if self.settings.get("kw_keywords"):
            return

        login = self.core.users.login_username

        if not login:
            return

        self.settings["kw_keywords"] = [login]

        try:
            self.config.write_configuration()
        except Exception:
            pass

        self.log("No keywords configured; watching for your username '%s'.", (login,))

    def _kw_log_path(self):
        return os.path.join(self._kw_log_dir(), KEYWORDWATCH_LOG_FILENAME)

    def _kw_load(self):
        feed = self._feeds["keywordwatch"]
        feed["entries"] = []

        for item in self._load_daily_log(self._kw_log_dir(), ("ts", "user", "text")):
            ts = self._safe_float(item.get("ts"))

            if not ts:
                continue

            feed["entries"].append({
                "ts": ts,
                "user": str(item.get("user") or ""),
                "room": str(item.get("room", "") or ""),
                "text": str(item.get("text") or ""),
                "keywords": [str(k) for k in item.get("keywords", []) if k is not None],
                "kind": item.get("kind", "kw") or "kw",
            })

        feed["entries"].sort(key=lambda entry: entry["ts"], reverse=True)

    def _kw_save(self):
        self._save_daily_log(
            self._feeds["keywordwatch"]["entries"],
            self._kw_log_dir(),
            "kw_log_start",
            "Keywords",
        )

    def _kw_prune(self):
        retention = RETENTION_SECONDS.get(self.settings.get("kw_retention"))

        if not retention:
            return False

        cutoff = time.time() - retention
        feed = self._feeds["keywordwatch"]
        new_entries = [entry for entry in feed["entries"] if entry["ts"] >= cutoff]

        if len(new_entries) == len(feed["entries"]):
            return False

        feed["entries"] = new_entries
        return True

    def _kw_clear(self):
        self._feeds["keywordwatch"]["entries"] = []
        self._kw_save()
        self._kw_render()
        self.log("Keywords log cleared.")

    def _kw_remove_entry(self, entry):
        feed = self._feeds["keywordwatch"]

        for i, existing in enumerate(feed["entries"]):
            if existing is entry:
                del feed["entries"][i]
                self._kw_save()
                self._kw_render()
                return

    def _kw_format_entry(self, entry):
        stamp = time.strftime("%I:%M:%S %p", time.localtime(entry["ts"]))
        user = entry.get("user") or "?"
        kind = entry.get("kind") or "kw"

        if kind == "profile":
            return f"{stamp}  {user} viewed your profile"

        if kind == "download":
            return f"{stamp}  {user} downloaded: {entry.get('text') or ''}"

        source = entry.get("room") or "private"
        keywords = entry.get("keywords") or []
        suffix = "  [kw: %s]" % ", ".join(keywords) if keywords else ""
        return f"{stamp} [{source}] <{user}> {entry.get('text') or ''}{suffix}"

    # ------------------------------------------------------------------ #
    # Shitlist logic
    # ------------------------------------------------------------------ #

    def _shitlist_check_keywords(self, user, line, room=""):
        if not self.settings.get("shitlist_enabled", True):
            return

        if not user or user == self.core.users.login_username:
            return

        if self._shitlist_is_whitelisted_user(user):
            return

        # Auto "now playing" /me (e.g. "* user is now listening to...") can carry a
        # keyword inside the song/artist title — don't treat that as abuse. Manual
        # /me abuse ("* user <slur>") has no marker and still matches below.
        if line.startswith("* ") and self._is_now_playing(line):
            return

        lowered = line.lower()

        for raw_keyword in self.settings.get("shitlist_keywords", []):
            keyword = self._normalize_keyword(raw_keyword)

            if not keyword:
                continue

            if keyword.lower() in lowered:
                if self.settings.get("shitlist_manual_review", False):
                    # Manual review: only log the hit, don't ban+ignore.
                    self._shitlist_log_hit(user, room, line, keyword, banned=False, ip=None)
                else:
                    self._shitlist_ban_and_log(user, room, line, keyword)

                break

    @staticmethod
    def _shitlist_normalize_username(username):
        """Normalize a Soulseek username to lowercase."""

        return username.strip().lower()

    def _shitlist_normalize_users_list(self):
        seen = set()
        normalized = []

        for username in self.settings.get("shitlist_users", []):
            username = self._shitlist_normalize_username(username)

            if username and username not in seen:
                seen.add(username)
                normalized.append(username)

        self.settings["shitlist_users"] = normalized

    def _shitlist_is_whitelisted(self, username):
        return (
            isinstance(username, str)
            and self._shitlist_normalize_username(username) in self._shitlist_show_messages_set
        )

    def _shitlist_is_whitelisted_user(self, user):
        """True if `user` is on the Shitlist whitelist (never flagged for keywords)."""

        if not user:
            return False

        normalized = self._shitlist_normalize_username(user)

        for username in self.settings.get("shitlist_whitelist_users", []):
            if self._shitlist_normalize_username(username) == normalized:
                return True

        return False

    def _shitlist_sync_show_messages_set(self):
        self._shitlist_show_messages_set = {
            self._shitlist_normalize_username(username)
            for username in self.settings.get("shitlist_show_messages", [])
        }
        self._shitlist_show_messages_set.discard("")

    def _shitlist_get_user_ip(self, user):
        """Return the user's current IP address, or None if unknown/offline."""

        try:
            addresses = self.core.users.addresses

            address = addresses.get(user)

            if address:
                return address[0]

            # Soulseek usernames are case-insensitive; fall back to a scan.
            lowered = user.lower()

            for username, address in addresses.items():
                if username.lower() == lowered:
                    return address[0]
        except Exception:
            pass

        return None

    def _shitlist_ban_and_ignore(self, user):
        """Ban and ignore a user by name (soft) AND by IP (hard). Returns (changed, ip)."""

        user = self._shitlist_normalize_username(user)

        if not user:
            return False, None

        ip = self._shitlist_get_user_ip(user)

        banned = self.core.network_filter.is_user_banned(user)
        ignored = self.core.network_filter.is_user_ignored(user)
        ip_banned = self.core.network_filter.is_user_ip_banned(user)
        ip_ignored = self.core.network_filter.is_user_ip_ignored(user)

        changed = False
        log_ip = ip or "?"

        if not banned:
            try:
                self.core.network_filter.ban_user(user)
                changed = True
            except Exception as error:
                self.log("Failed to ban '%s' by name: %s", (user, error))

        if not ignored:
            try:
                self.core.network_filter.ignore_user(user)
                changed = True
            except Exception as error:
                self.log("Failed to ignore '%s' by name: %s", (user, error))

        if not ip_banned:
            try:
                result_ip = self.core.network_filter.ban_user_ip(user, ip_address=ip)

                if result_ip:
                    log_ip = result_ip

                changed = True
            except Exception as error:
                self.log("Failed to ban '%s' by IP: %s", (user, error))

        if not ip_ignored:
            try:
                self.core.network_filter.ignore_user_ip(user, ip_address=ip)
                changed = True
            except Exception as error:
                self.log("Failed to ignore '%s' by IP: %s", (user, error))

        return changed, log_ip

    def _shitlist_ban_and_log(self, user, room, line, keyword):
        """Ban+ignore the user (name + IP), then record the hit in the pane log."""

        user = self._shitlist_normalize_username(user)

        if not user:
            return

        changed, ip = self._shitlist_ban_and_ignore(user)

        if changed:
            if ip and str(ip).startswith("?"):
                self.log(
                    "Banned and ignored user '%s' (by name; IP resolving) for saying keyword '%s'",
                    (user, keyword),
                )
            else:
                self.log("Banned and ignored user '%s' (name + IP %s) for saying keyword '%s'", (user, ip, keyword))

        self._shitlist_log_hit(user, room, line, keyword, banned=changed, ip=(ip if changed else None))

    def _shitlist_log_hit(self, user, room, line, keyword, banned=False, ip=None):
        """Record a keyword hit in the Shitlist feed (pane log) and persist it."""

        feed = self._feeds["shitlist"]
        feed["entries"].insert(0, {
            "ts": time.time(),
            "user": user,
            "room": room or "",
            "text": line,
            "keyword": keyword,
            "banned": bool(banned),
            "ip": ip,
        })
        self._shitlist_prune()
        self._shitlist_save()
        self._shitlist_render()

    def _shitlist_log_path(self):
        return os.path.join(self._shitlist_log_dir(), SHITLIST_LOG_FILENAME)

    def _shitlist_unban(self, user):
        user = self._shitlist_normalize_username(user)

        if not user:
            return

        timer = self._shitlist_ignore_timers.pop(user, None)

        if timer is not None:
            events.cancel_scheduled(timer)

        changed = False

        if self.core.network_filter.is_user_banned(user):
            self.core.network_filter.unban_user(user)
            changed = True

        if self.core.network_filter.is_user_ignored(user):
            self.core.network_filter.unignore_user(user)
            changed = True

        if self.core.network_filter.is_user_ip_banned(user):
            self.core.network_filter.unban_user_ip(user)
            changed = True

        if self.core.network_filter.is_user_ip_ignored(user):
            self.core.network_filter.unignore_user_ip(user)
            changed = True

        if changed:
            self.log("Unbanned and unignored user '%s'", (user,))

    def _shitlist_ignore_for(self, username, seconds):
        if not self._shitlist_enabled or not username:
            return

        username = self._shitlist_normalize_username(username)

        if not username:
            return

        already_ignored = self.core.network_filter.is_user_ignored(username)
        self.core.network_filter.ignore_user(username)

        previous_timer = self._shitlist_ignore_timers.pop(username, None)

        if previous_timer is not None:
            events.cancel_scheduled(previous_timer)

        if already_ignored:
            # Respect an existing (permanent) ignore: don't auto-remove it.
            self.log("User '%s' was already ignored; keeping the ignore without auto-expiry", (username,))
            return

        event_id = events.schedule(seconds, self._shitlist_unignore_user, (username,))
        self._shitlist_ignore_timers[username] = event_id
        self.log("Ignoring user '%s' for %s seconds", (username, seconds))

    def _shitlist_unignore_user(self, username):
        self._shitlist_ignore_timers.pop(username, None)

        username = self._shitlist_normalize_username(username)

        if self.core.network_filter.is_user_banned(username):
            # The user was permanently banned+ignored in the meantime; keep the ignore.
            return

        if self.core.network_filter.is_user_ignored(username):
            self.core.network_filter.unignore_user(username)
            self.log("Temporary ignore of user '%s' expired", (username,))

    def _shitlist_patch_user_menu(self):
        if self._shitlist_menu_patched:
            return

        try:
            from pynicotine.gtkgui.widgets.popupmenu import PopupMenu, UserPopupMenu
        except Exception as error:
            self.log("Could not patch the user menu (\"Ignore for...\" will be unavailable): %s", (error,))
            return

        plugin = self
        original = UserPopupMenu.setup_user_menu

        def ignore_for_callback(menu_self, action, parameter, seconds):
            plugin._shitlist_ignore_for(menu_self.username, seconds)

        def patched_setup_user_menu(menu_self, username):
            original(menu_self, username)

            submenu = PopupMenu(menu_self.application, connect_events=False)

            for label, seconds in plugin.IGNORE_DURATIONS:
                submenu.add_items(("#" + label, menu_self._chatwatcher_ignore_for, seconds))

            menu_self.add_items((">" + "Ignore for...", submenu))

        UserPopupMenu._chatwatcher_ignore_for = ignore_for_callback
        UserPopupMenu.setup_user_menu = patched_setup_user_menu

        self._shitlist_menu_patched = True
        self._shitlist_original_setup_user_menu = original

    def _shitlist_restore_user_menu(self):
        if not self._shitlist_menu_patched:
            return

        try:
            from pynicotine.gtkgui.widgets.popupmenu import UserPopupMenu
        except Exception:
            return

        if self._shitlist_original_setup_user_menu is not None:
            UserPopupMenu.setup_user_menu = self._shitlist_original_setup_user_menu

        if hasattr(UserPopupMenu, "_chatwatcher_ignore_for"):
            del UserPopupMenu._chatwatcher_ignore_for

        self._shitlist_menu_patched = False
        self._shitlist_original_setup_user_menu = None

    # ------------------------------------------------------------------ #
    # Shared persistence helpers
    # ------------------------------------------------------------------ #

    def _logs_dir(self):
        return os.path.join(self.path or "", LOG_SUBFOLDER)

    def _listenings_log_dir(self):
        return os.path.join(self._logs_dir(), "listenings")

    def _kw_log_dir(self):
        return os.path.join(self._logs_dir(), "keywordwatch")

    def _shitlist_log_dir(self):
        return os.path.join(self._logs_dir(), "shitlist")

    # --- daily log rotation ------------------------------------------- #

    @staticmethod
    def _date_key(ts=None):
        """'YYYY-MM-DD' for the given epoch (default: now), in local time."""
        return time.strftime(LOG_DATE_FORMAT, time.localtime(time.time() if ts is None else ts))

    @staticmethod
    def _days_between(start_day, end_day):
        """Whole days between two 'YYYY-MM-DD' date keys (end - start)."""
        try:
            start_t = time.mktime(time.strptime(start_day, LOG_DATE_FORMAT))
            end_t = time.mktime(time.strptime(end_day, LOG_DATE_FORMAT))
            return int(round((end_t - start_t) / 86400.0))
        except (ValueError, OverflowError):
            return 0

    @staticmethod
    def _day_from_log_name(name):
        """'log3[2026-08-18].log' -> '2026-08-18' ('' if it doesn't match)."""
        if "[" in name and "]" in name:
            return name.split("[", 1)[1].split("]", 1)[0]

        return ""

    def _ensure_start_date(self, folder, start_key):
        """Return the day-1 date for a feature, deriving it from existing daily
        files (or today) the first time so numbering stays stable across restarts."""
        start = self.settings.get(start_key) or ""

        if start:
            return start

        days = []

        if os.path.isdir(folder):
            for name in os.listdir(folder):
                day = self._day_from_log_name(name)

                if day:
                    days.append(day)

        start = min(days) if days else self._date_key()
        self.settings[start_key] = start
        return start

    def _daily_filename(self, folder, start_key, day):
        start = self._ensure_start_date(folder, start_key)
        return f"log{self._days_between(start, day) + 1}[{day}].log"

    @staticmethod
    def _read_log_file(path, entries, required):
        try:
            with open(path, "r", encoding="utf-8") as file_handle:
                for line in file_handle:
                    line = line.strip()

                    if not line:
                        continue

                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue

                    if not isinstance(item, dict):
                        continue

                    if not all(key in item for key in required):
                        continue

                    entries.append(item)
        except OSError:
            pass

    def _load_daily_log(self, folder, required):
        """Read every logN[date].log in `folder` (oldest day first) into a flat list."""
        entries = []

        if not os.path.isdir(folder):
            return entries

        names = [name for name in os.listdir(folder) if name.startswith("log") and name.endswith(".log")]
        names.sort(key=self._day_from_log_name)

        for name in names:
            self._read_log_file(os.path.join(folder, name), entries, required)

        return entries

    def _save_daily_log(self, feed, folder, start_key, label):
        """Write each entry to its own day's logN[date].log file, truncating stale
        daily files so the folder always mirrors the current in-memory feed."""
        try:
            os.makedirs(folder, exist_ok=True)

            by_day = {}

            for entry in feed:
                ts = entry.get("ts")

                if ts is None:
                    continue

                day = self._date_key(float(ts))
                by_day.setdefault(day, []).append(entry)

            # Truncate every existing daily file first so removed/pruned entries
            # don't linger on disk.
            if os.path.isdir(folder):
                for name in os.listdir(folder):
                    if name.startswith("log") and name.endswith(".log"):
                        try:
                            with open(os.path.join(folder, name), "w", encoding="utf-8"):
                                pass
                        except OSError:
                            pass

            if by_day:
                earliest = min(by_day)
                start = self.settings.get(start_key) or ""

                if not start or earliest < start:
                    self.settings[start_key] = earliest

                for day, day_entries in by_day.items():
                    path = os.path.join(folder, self._daily_filename(folder, start_key, day))

                    with open(path, "w", encoding="utf-8") as file_handle:
                        for item in reversed(day_entries):  # oldest first on disk
                            file_handle.write(json.dumps(item, ensure_ascii=False) + "\n")

        except Exception as error:
            self.log("Could not write %s log: %s", (label, error))

    @staticmethod
    def _normalize_keyword(keyword):
        """Strip surrounding quotes and whitespace from a keyword."""

        keyword = keyword.strip()

        if len(keyword) >= 2 and keyword[0] == keyword[-1] and keyword[0] in ('"', "'"):
            keyword = keyword[1:-1]

        return keyword.strip()

    # ------------------------------------------------------------------ #
    # Timers
    # ------------------------------------------------------------------ #

    def _start_timers(self):
        from gi.repository import GLib

        if self._prune_id is None:
            self._prune_id = GLib.timeout_add(60000, self._prune_tick)

    def _stop_timers(self):
        from gi.repository import GLib

        for feed in self._feeds.values():
            if feed["build_id"] is not None:
                GLib.source_remove(feed["build_id"])
                feed["build_id"] = None

        if self._prune_id is not None:
            GLib.source_remove(self._prune_id)
            self._prune_id = None

    def _prune_tick(self):
        if self._listenings_prune():
            self._listenings_save()
            self._listenings_render()

        if self._kw_prune():
            self._kw_save()
            self._kw_render()

        if self._shitlist_prune():
            self._shitlist_save()
            self._shitlist_render()

        return True  # keep polling

    # ------------------------------------------------------------------ #
    # Commands: /kw
    # ------------------------------------------------------------------ #

    def _kw_command(self, args, user=None, room=None):
        args = args.strip()

        if not args:
            return self._open_kw_settings()

        action, _separator, rest = args.partition(" ")
        action = action.lower()
        keyword = rest.strip()

        if action == "add":
            return self._kw_add_keyword(keyword)

        if action == "remove":
            return self._kw_remove_keyword(keyword)

        if action == "list":
            return self._kw_list_keywords()

        self.output("Usage: /kw [add <word> | remove <word> | list]")
        return False

    def _kw_add_keyword(self, keyword):
        keyword = self._normalize_keyword(keyword)

        if not keyword:
            self.output("Usage: /kw add <word>")
            return False

        for existing in self.settings["kw_keywords"]:
            if self._normalize_keyword(existing) == keyword:
                self.output("Keyword '%s' is already on the list." % keyword)
                return False

        self.settings["kw_keywords"].append(keyword)
        self.config.write_configuration()
        self.output("Added keyword '%s'. %s keyword(s) total." % (keyword, len(self.settings["kw_keywords"])))
        return True

    def _kw_remove_keyword(self, keyword):
        keyword = self._normalize_keyword(keyword)

        if not keyword:
            self.output("Usage: /kw remove <word>")
            return False

        for existing in list(self.settings["kw_keywords"]):
            if self._normalize_keyword(existing) == keyword:
                self.settings["kw_keywords"].remove(existing)
                self.config.write_configuration()
                self.output("Removed keyword '%s'." % keyword)
                return True

        self.output("Keyword '%s' is not on the list." % keyword)
        return False

    def _kw_list_keywords(self):
        keywords = self.settings.get("kw_keywords", [])

        if not keywords:
            self.output("No keywords on the Keywords list.")
            return True

        self.output("Keywords list (%s):" % len(keywords))

        for keyword in keywords:
            self.output("  - %s" % keyword)

        return True

    def _open_kw_settings(self):
        return self._open_plugin_settings()

    # ------------------------------------------------------------------ #
    # Commands: /shitlist
    # ------------------------------------------------------------------ #

    def _shitlist_command(self, args, user=None, room=None):
        args = args.strip()

        if not args:
            return self._open_plugin_settings()

        action, _separator, rest = args.partition(" ")
        action = action.lower()
        keyword = rest.strip()

        if action == "add":
            return self._shitlist_add_keyword(keyword)

        if action == "remove":
            return self._shitlist_remove_keyword(keyword)

        if action == "list":
            return self._shitlist_list_keywords()

        self.output("Usage: /shitlist [add <word> | remove <word> | list]")
        return False

    def _shitlist_add_keyword(self, keyword):
        keyword = keyword.strip()

        if not keyword:
            self.output("Usage: /shitlist add <word>  (wrap multi-word phrases in double quotes)")
            return False

        quoted = (
            len(keyword) >= 2
            and keyword[0] == keyword[-1]
            and keyword[0] in ('"', "'")
        )

        if " " in keyword and not quoted:
            self.output("Multi-word keywords must be wrapped in double quotes, e.g. /shitlist add \"no thanks\".")
            return False

        keyword = self._normalize_keyword(keyword)

        if not keyword:
            return False

        for existing in self.settings["shitlist_keywords"]:
            if self._normalize_keyword(existing) == keyword:
                self.output("Keyword '%s' is already on the list." % keyword)
                return False

        self.settings["shitlist_keywords"].append(keyword)
        self.config.write_configuration()
        self.output("Added keyword '%s'. %s keyword(s) total." % (keyword, len(self.settings["shitlist_keywords"])))
        return True

    def _shitlist_remove_keyword(self, keyword):
        keyword = keyword.strip()

        if not keyword:
            self.output("Usage: /shitlist remove <word>")
            return False

        keyword = self._normalize_keyword(keyword)

        for existing in list(self.settings["shitlist_keywords"]):
            if self._normalize_keyword(existing) == keyword:
                self.settings["shitlist_keywords"].remove(existing)
                self.config.write_configuration()
                self.output("Removed keyword '%s'." % keyword)
                return True

        self.output("Keyword '%s' is not on the list." % keyword)
        return False

    def _shitlist_list_keywords(self):
        keywords = self.settings.get("shitlist_keywords", [])

        if not keywords:
            self.output("No keywords on the Shitlist.")
            return True

        self.output("Shitlist keywords (%s):" % len(keywords))

        for keyword in keywords:
            self.output("  - %s" % keyword)

        return True

    def _open_plugin_settings(self):
        application = self._get_application()

        if application is None:
            self.output(
                "No GUI available. Edit options in Preferences -> Plugins -> Chat watcher v1 -> Settings, "
                "or use /played, /kw and /shitlist to manage each feature from chat."
            )
            return False

        try:
            if application.preferences is None:
                from pynicotine.gtkgui.dialogs.preferences import Preferences
                application.preferences = Preferences(application)

            from pynicotine.gtkgui.dialogs.pluginsettings import PluginSettings

            dialog = getattr(application, "_chatwatcher_settings_dialog", None)

            if dialog is None:
                plugin = self

                class ChatWatcherSettingsDialog(PluginSettings):

                    def update_settings(self_, plugin_id, plugin_settings):
                        super().update_settings(plugin_id, plugin_settings)
                        self_._add_open_logs_buttons()

                    def _add_open_logs_buttons(self_):
                        # One-click "Clear log" buttons (replaces the old
                        # tick-to-clear checkboxes).
                        for label, handler in (
                            ("Clear Played Log", plugin._listenings_clear),
                            ("Clear Keywords Log", plugin._kw_clear),
                        ):
                            button = plugin._make_toolbar_button(
                                "edit-clear-all-symbolic", label,
                                "Wipe this feature's log now"
                            )
                            button.connect("clicked", lambda _button, handler=handler: handler())
                            plugin._box_add(self_.primary_container, button)

                        for label, handler in (
                            ("Open Played Log Folder", plugin._open_listenings_logs_clicked),
                            ("Open Keywords Log Folder", plugin._open_kw_logs_clicked),
                            ("Open Shitlist Log Folder", plugin._open_shitlist_logs_clicked),
                        ):
                            button = plugin._make_toolbar_button(
                                "folder-open-symbolic", label,
                                "Open the folder where this feature's log is stored"
                            )
                            button.connect("clicked", handler)
                            plugin._box_add(self_.primary_container, button)

                    def on_ok(self_, *_args):
                        plugin._shitlist_normalize_users_list()
                        old_users = set(plugin.settings.get("shitlist_users", []))

                        PluginSettings.on_ok(self_)

                        plugin._shitlist_sync_show_messages_set()
                        plugin._shitlist_normalize_users_list()
                        new_users = set(plugin.settings.get("shitlist_users", []))

                        for username in sorted(new_users - old_users):
                            changed, _ip = plugin._shitlist_ban_and_ignore(username)

                            if changed:
                                plugin.log("Banned and ignored user '%s' (added in settings)", (username,))

                        for username in sorted(old_users - new_users):
                            plugin._shitlist_unban(username)

                        plugin.config.write_configuration()

                dialog = ChatWatcherSettingsDialog(application)
                application._chatwatcher_settings_dialog = dialog

            dialog.update_settings(plugin_id=self.internal_name, plugin_settings=self.metasettings)
            dialog.present()
            return True

        except Exception as error:
            self.log("Failed to open settings dialog: %s", (error,))
            self.output("Failed to open the settings window (%s)." % error)
            return False

    # ------------------------------------------------------------------ #
    # Commands: /played
    # ------------------------------------------------------------------ #

    def _played_command(self, args, user=None, room=None):
        args = args.strip()

        if not args:
            return self._open_played_settings()

        action, _separator, rest = args.partition(" ")
        action = action.lower()
        target = rest.strip()

        if action == "clear":
            return self._played_clear()

        if action == "hide":
            return self._played_hide(target)

        if action == "unhide":
            return self._played_unhide(target)

        if action == "list":
            return self._played_list()

        self.output("Usage: /played [clear | hide <user> | unhide <user> | list]")
        return False

    def _played_clear(self):
        self._listenings_clear()
        self.output("Cleared the Played log.")
        return True

    def _played_hide(self, user):
        user = (user or "").strip()

        if not user:
            self.output("Usage: /played hide <user>")
            return False

        hidden = self.settings.get("listenings_blocked_users", [])
        lowered = {u.lower() for u in hidden}

        if user.lower() in lowered:
            self.output("User '%s' is already hidden." % user)
            return False

        hidden.append(user)
        self.config.write_configuration()
        self.output("Hidden user '%s' from the Played tab." % user)
        return True

    def _played_unhide(self, user):
        user = (user or "").strip()

        if not user:
            self.output("Usage: /played unhide <user>")
            return False

        hidden = self.settings.get("listenings_blocked_users", [])

        for existing in list(hidden):
            if existing.lower() == user.lower():
                hidden.remove(existing)
                self.config.write_configuration()
                self.output("Un-hidden user '%s'." % user)
                return True

        self.output("User '%s' is not hidden." % user)
        return False

    def _played_list(self):
        hidden = self.settings.get("listenings_blocked_users", [])
        retention = self.settings.get("listenings_retention", "1 day")

        self.output("Played tab:")

        if hidden:
            self.output("  Hidden users (%d):" % len(hidden))
            for username in hidden:
                self.output("    - %s" % username)
        else:
            self.output("  Hidden users: none")

        self.output("  Keep entries for: %s" % retention)
        return True

    def _open_played_settings(self):
        return self._open_plugin_settings()

    # ------------------------------------------------------------------ #
    # Command: /chatwatcher (/cw)
    # ------------------------------------------------------------------ #

    def _chatwatcher_command(self, args, user=None, room=None):
        action = args.strip().lower()

        if action in ("", "settings"):
            # /cw (and /cw settings) opens the settings dialog directly.
            return self._open_plugin_settings()

        if action == "status":
            return self._chatwatcher_status()

        if action == "help":
            return self._chatwatcher_help()

        self.output("Usage: /chatwatcher [/cw] [settings | status | help]")
        return False

    def _chatwatcher_help(self):
        self.output("Chat watcher v1 — merged Played + Keywords + Shitlist")
        self.output("")
        self.output("  Played        logs /nowplaying (/me) messages to a 'Played' tab")
        self.output("  Keywords      logs messages mentioning your keywords to a 'Keywords' tab")
        self.output("  Shitlist      IP-bans+IP-ignores keyword users; logs every ban with the IP")
        self.output("")
        self.output("Commands:")
        self.output("  /cw [settings|status|help]         open settings (default) or show status/help")
        self.output("  /played [clear|hide|unhide|list]   manage the Played tab")
        self.output("  /kw [add|remove|list] <word>      manage the Keywords list")
        self.output("  /shitlist [add|remove|list] <word> manage Shitlist keywords")
        return True

    def _chatwatcher_status(self):
        l_enabled = bool(self.settings.get("listenings_enabled", True))
        l_retention = self.settings.get("listenings_retention", "1 day")
        l_blocked = len(self.settings.get("listenings_blocked_users", []))

        kw_enabled = bool(self.settings.get("kw_enabled", True))
        kw_keywords = self.settings.get("kw_keywords", [])
        kw_case = bool(self.settings.get("kw_case_sensitive", False))
        kw_retention = self.settings.get("kw_retention", "1 day")
        kw_blocked = len(self.settings.get("kw_blocked_users", []))

        s_enabled = bool(self.settings.get("shitlist_enabled", True))
        s_review = bool(self.settings.get("shitlist_manual_review", False))
        s_keywords = self.settings.get("shitlist_keywords", [])
        s_show = len(self.settings.get("shitlist_show_messages", []))
        s_whitelist = len(self.settings.get("shitlist_whitelist_users", []))
        s_users = len(self.settings.get("shitlist_users", []))

        self.output("Chat watcher v1 status:")
        self.output("  Played:        %s, retention=%s, hidden users=%d"
                    % ("on" if l_enabled else "off", l_retention, l_blocked))
        self.output("  Keywords:      %s, %d keyword(s), case-sensitive=%s, retention=%s, hidden users=%d"
                    % ("on" if kw_enabled else "off", len(kw_keywords), "yes" if kw_case else "no", kw_retention, kw_blocked))
        self.output("  Shitlist:      %s, %s, %d keyword(s), %d whitelisted, %d message exception(s), %d banned+ignored"
                    % ("on" if s_enabled else "off", "Manual review mode" if s_review else "Automatic mode", len(s_keywords), s_whitelist, s_show, s_users))
        self.output("")
        self.output("Use /cw to open the settings dialog (Played + Keywords). Shitlist settings live in the Shitlist pane.")
        return True

    @staticmethod
    def _get_application():
        """Locate the singleton GUI Application wrapper."""

        try:
            import gc
            from pynicotine.gtkgui.application import Application
        except Exception:
            return None

        for obj in gc.get_objects():
            if isinstance(obj, Application):
                return obj

        return None

    # ------------------------------------------------------------------ #
    # GUI: main-window tabs
    # ------------------------------------------------------------------ #

    def _schedule_build(self, feed_key):
        from gi.repository import GLib

        feed = self._feeds[feed_key]
        feed["build_attempts"] = 0

        if feed["build_id"] is None:
            # Poll instead of idle_add: the window may not be mapped yet when
            # Nicotine+ starts hidden (tray mode), and idle_add would spin.
            feed["build_id"] = GLib.timeout_add(500, self._build_tab, feed_key)

    def _build_tab(self, feed_key):
        feed = self._feeds[feed_key]

        if feed["built"]:
            feed["build_id"] = None
            return False

        feed["build_attempts"] += 1

        if feed["build_attempts"] > 7200:  # ~1 hour at 500 ms
            self.log("Could not find the main window; '%s' tab was not added.", feed["tab_name"])
            feed["build_id"] = None
            return False

        try:
            window = self._get_main_window()
            notebook = getattr(window, "notebook", None)

            if notebook is None:
                return True  # window not ready yet, retry on the next cycle

            if feed_key == "listenings":
                page = self._build_listenings_page(feed)
            elif feed_key == "keywordwatch":
                page = self._build_keywordwatch_page(feed)
            else:
                page = self._build_shitlist_page(feed)

            page.id = feed["tab_id"]  # Nicotine+ expects every main tab page to have an id

            self._wire_find_shortcuts(page, feed_key)

            self._patch_header_bar(window)
            self._finalize_page(page)

            # Use Nicotine+'s IconNotebook API so the tab is registered in its
            # internal tab-label bookkeeping (get_tab_label, remove_page, etc.).
            notebook.append_page(page, feed["tab_name"])

            # Nicotine+ hides a page's first child on insert; re-show our
            # content so the tab isn't blank when revealed without a switch.
            try:
                first_child = next(iter(page))
            except StopIteration:
                first_child = None

            if first_child is not None:
                first_child.set_visible(True)

            feed["notebook"] = notebook
            feed["page"] = page
            feed["built"] = True

            if feed_key == "listenings":
                self._listenings_render()
            elif feed_key == "keywordwatch":
                self._kw_render()
            else:
                self._shitlist_render()

            feed["build_id"] = None
            return False

        except Exception as error:
            self.log("Failed to create '%s' tab: %s", (feed["tab_name"], error))
            feed["build_id"] = None
            return False

    def _get_main_window(self):
        """Return Nicotine+'s MainWindow wrapper (holds ``notebook`` and ``tabs``)."""

        import gc

        from gi.repository import Gio

        app = Gio.Application.get_default()

        if app is None:
            return None

        windows = app.get_windows()

        if not windows:
            return None

        widget = windows[0]

        for candidate in gc.get_objects():
            if type(candidate).__name__ == "MainWindow" and getattr(candidate, "widget", None) is widget:
                return candidate

        return None

    def _patch_header_bar(self, window):
        """Make MainWindow.set_active_header_bar a no-op for our plugin tabs.

        Nicotine+ raises ``KeyError('<tab id>')`` when switching to a plugin
        tab, because ``set_active_header_bar(page.id)`` looks the tab up in
        ``window.tabs`` (which only holds Nicotine+'s own tabs) via
        ``show_header_bar`` / ``show_toolbar``.

        The old approach -- wrapping ``notebook.switch_page_callback`` -- could
        be bypassed (for example after a disable/re-enable cycle), which is
        exactly the crash this replaces. Patching the method directly is
        robust: ``set_active_header_bar`` is looked up fresh on every call, so
        a class-level patch reliably takes effect and stops the KeyError at the
        source.
        """

        if self._header_bar_patched:
            return

        main_window_class = type(window)
        original = getattr(main_window_class, "set_active_header_bar", None)

        if original is None:
            return

        plugin = self
        plugin_tab_ids = {feed["tab_id"] for feed in self._feeds.values()}

        def patched_set_active_header_bar(mw_self, page_id):
            if page_id in plugin_tab_ids:
                return

            original(mw_self, page_id)

        main_window_class.set_active_header_bar = patched_set_active_header_bar

        self._header_bar_patched = True
        self._original_set_active_header_bar = original
        self._patched_main_window_class = main_window_class

    def _restore_header_bar(self):
        if not self._header_bar_patched:
            return

        if self._original_set_active_header_bar is not None and self._patched_main_window_class is not None:
            self._patched_main_window_class.set_active_header_bar = self._original_set_active_header_bar

        self._header_bar_patched = False
        self._original_set_active_header_bar = None
        self._patched_main_window_class = None

    def _remove_tab(self, feed_key):
        feed = self._feeds[feed_key]

        if feed["notebook"] is not None and feed["page"] is not None:
            try:
                feed["notebook"].remove_page(feed["page"])
            except Exception:
                pass

        feed["notebook"] = None
        feed["page"] = None
        feed["built"] = False
        feed["list_widget"] = None
        feed["status_label"] = None
        feed["list_widget"] = None
        feed["rows"] = []
        feed["active_popover"] = None
        feed["status_label"] = None
        feed["built"] = False

    # ------------------------------------------------------------------ #
    # Listenings page + render
    # ------------------------------------------------------------------ #

    def _build_listenings_page(self, feed):
        from gi.repository import Gtk

        # Nicotine+ toggles a page's *first* child visibility on switch, so
        # wrap the whole UI in a single child container.
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        # Top row: a toolbar-style "Clear Log" button + entry counter
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        clear_button = self._make_toolbar_button(
            "edit-clear-symbolic", "Clear Log",
            "Delete all entries from the Played log"
        )
        clear_button.connect("clicked", self._on_listenings_clear_clicked)

        open_folder_button = self._make_toolbar_button(
            "folder-open-symbolic", "Open Logs Folder",
            "Open the folder where the Played log is stored"
        )
        open_folder_button.connect("clicked", self._open_listenings_logs_clicked)

        status_label = Gtk.Label()
        status_label.set_halign(Gtk.Align.START)
        status_label.set_hexpand(True)
        feed["status_label"] = status_label

        self._box_add(toolbar, clear_button)
        self._box_add(toolbar, open_folder_button)
        self._box_add(toolbar, status_label)
        self._box_add(box, toolbar)

        self._box_add(box, self._make_find_entry(feed, "listenings"))

        # Scrollable list of entries (one flat button per entry)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.set_hexpand(True)
        listbox.set_vexpand(True)

        self._set_scrolled_child(scrolled, listbox)
        feed["list_widget"] = listbox

        self._box_add(box, scrolled)
        self._box_add(page, box)

        return page

    def _on_listenings_clear_clicked(self, *_args):
        self._listenings_clear()

    def _listenings_render(self):
        feed = self._feeds["listenings"]

        if not feed["built"]:
            return

        listbox = feed["list_widget"]

        for row in feed["rows"]:
            listbox.remove(row)

        feed["rows"] = []

        query = (feed.get("search_query") or "").strip().lower()
        shown = 0

        for entry in feed["entries"]:
            if query:
                txt = self._listenings_format_entry(entry).lower()
                if query not in txt:
                    continue
            shown += 1
            row = self._listenings_build_entry_row(entry)
            self._listbox_append(listbox, row)
            feed["rows"].append(row)

        self._show_all(listbox)
        self._update_status(feed)
        if query:
            label = feed.get("status_label")
            if label is not None:
                label.set_text(f"{shown} of {len(feed['entries'])} entries")

    def _listenings_build_entry_row(self, entry):
        from gi.repository import Gtk

        button = Gtk.Button()
        label = Gtk.Label(label=self._listenings_format_entry(entry))
        label.set_halign(Gtk.Align.FILL)
        label.set_hexpand(True)
        label.set_xalign(0.0)
        label.set_wrap(True)
        label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

        if self._is_gtk4():
            button.set_child(label)
            button.set_has_frame(False)
        else:
            button.add(label)
            button.set_relief(Gtk.ReliefStyle.NONE)

        button.set_halign(Gtk.Align.FILL)
        button.set_hexpand(True)
        button.set_tooltip_text("Right-click to copy or remove this entry")

        self._listenings_connect_entry_menu(button, entry)

        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)

        if self._is_gtk4():
            row.set_child(button)
        else:
            row.add(button)

        return row

    def _listenings_connect_entry_menu(self, button, entry):
        from gi.repository import Gtk

        if self._is_gtk4():
            gesture = Gtk.GestureClick()
            gesture.set_button(3)  # right mouse button
            gesture.connect("pressed", self._listenings_on_entry_right_pressed_gtk4, entry)
            button.add_controller(gesture)
        else:
            button.connect("button-press-event", self._listenings_on_entry_button_press_gtk3, entry)

    def _listenings_on_entry_button_press_gtk3(self, button, event, entry):
        if event.button != 3:
            return False

        self._listenings_show_menu_gtk3(button, event, entry)
        return True

    def _listenings_on_entry_right_pressed_gtk4(self, gesture, _n_press, x, y, entry):
        self._listenings_show_menu_gtk4(gesture.get_widget(), entry, x, y)

    def _listenings_show_menu_gtk3(self, _button, event, entry):
        from gi.repository import Gtk

        menu = Gtk.Menu()

        copy_item = Gtk.MenuItem(label="Copy")
        copy_item.connect("activate", lambda *_args: self._listenings_copy_entry(entry))
        menu.append(copy_item)

        remove_item = Gtk.MenuItem(label="Remove")
        remove_item.connect("activate", lambda *_args: self._listenings_remove_entry(entry))
        menu.append(remove_item)

        menu.show_all()
        menu.popup_at_pointer(event)

    def _listenings_show_menu_gtk4(self, button, entry, x=None, y=None):
        from gi.repository import Gdk, Gtk

        popover = Gtk.Popover()
        popover.set_parent(button)
        popover.set_has_arrow(False)

        if x is not None and y is not None:
            try:
                rect = Gdk.Rectangle()
                rect.x = int(x)
                rect.y = int(y)
                rect.width = 1
                rect.height = 1
                popover.set_pointing_to(rect)
            except Exception:
                pass

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        copy_button = Gtk.Button.new_with_label("Copy")
        copy_button.connect("clicked", self._listenings_on_copy_clicked_gtk4, entry, popover)
        box.append(copy_button)

        remove_button = Gtk.Button.new_with_label("Remove")
        remove_button.connect("clicked", self._listenings_on_remove_clicked_gtk4, entry, popover)
        box.append(remove_button)

        popover.set_child(box)
        popover.popup()

        self._feeds["listenings"]["active_popover"] = popover  # keep a ref so it isn't garbage collected

    def _listenings_on_copy_clicked_gtk4(self, _button, entry, popover):
        popover.popdown()
        self._listenings_copy_entry(entry)

    def _listenings_on_remove_clicked_gtk4(self, _button, entry, popover):
        popover.popdown()
        self._listenings_remove_entry(entry)

    # ------------------------------------------------------------------ #
    # Keyword Watch page + render
    # ------------------------------------------------------------------ #

    def _build_keywordwatch_page(self, feed):
        from gi.repository import Gtk

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        # Toolbar row: clear + open folder buttons, filter dropdown, counter
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        clear_button = self._make_toolbar_button("edit-clear", "Clear Log")
        clear_button.set_tooltip_text("Delete all entries from the Keywords log")
        clear_button.connect("clicked", self._on_kw_clear_clicked)

        open_folder_button = self._make_toolbar_button("folder-open", "Open Log Folder")
        open_folder_button.set_tooltip_text("Open the folder where the Keywords log is stored")
        open_folder_button.connect("clicked", self._open_kw_logs_clicked)

        filter_combo = Gtk.ComboBoxText()

        for label in ("All", "Keywords", "Profile views", "Downloads"):
            filter_combo.append_text(label)

        filter_combo.set_active(0)
        filter_combo.set_tooltip_text("Filter entries by type")
        filter_combo.connect("changed", self._on_kw_filter_changed)
        feed["filter_combo"] = filter_combo

        status_label = Gtk.Label()
        status_label.set_halign(Gtk.Align.END)
        status_label.set_hexpand(True)
        feed["status_label"] = status_label

        self._box_add(toolbar, clear_button)
        self._box_add(toolbar, open_folder_button)
        self._box_add(toolbar, filter_combo)

        if self._is_gtk4():
            toolbar.append(status_label)
        else:
            toolbar.pack_start(status_label, True, True, 0)

        self._box_add(box, toolbar)

        # Hide-users expander
        hide_expander = Gtk.Expander(label="Hide users")
        hide_expander.set_expanded(False)

        hide_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hide_box.set_margin_start(12)
        hide_box.set_margin_end(12)
        hide_box.set_margin_bottom(4)

        hint = Gtk.Label()
        hint.set_markup("<small>One username per line — their keyword mentions, profile views and downloads won't show in this tab.</small>")
        hint.set_halign(Gtk.Align.START)
        hint.set_xalign(0.0)
        hint.set_wrap(True)
        self._box_add(hide_box, hint)

        self._kw_hide_users_view = self._make_text_view("\n".join(self.settings.get("kw_blocked_users", [])))
        hide_editor = self._make_scrolled_editor(self._kw_hide_users_view, 90)
        self._box_add_fill(hide_box, hide_editor)

        hide_apply = Gtk.Button.new_with_label("Apply hidden users")
        hide_apply.connect("clicked", self._on_kw_hide_users_apply)
        self._box_add(hide_box, hide_apply)

        if self._is_gtk4():
            hide_expander.set_child(hide_box)
        else:
            hide_expander.add(hide_box)

        self._box_add(box, hide_expander)

        self._box_add(box, self._make_find_entry(feed, "keywordwatch"))

        # Scrollable list of per-entry buttons
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        entries_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._set_scrolled_child(scrolled, entries_box)
        feed["list_widget"] = entries_box

        self._box_add(box, scrolled)
        self._box_add(page, box)

        return page

    def _on_kw_clear_clicked(self, *_args):
        self._kw_clear()

    def _on_kw_filter_changed(self, combo):
        self._feeds["keywordwatch"]["filter"] = combo.get_active_text() or "All"
        self._kw_render()

    def _on_kw_hide_users_apply(self, *_args):
        self.settings["kw_blocked_users"] = self._parse_lines(self._read_text_view(self._kw_hide_users_view))
        self._write_config_safe()
        self.log("Keywords hidden users updated (%d).", (len(self.settings["kw_blocked_users"]),))
        self._kw_render()

    @staticmethod
    def _kw_matches_filter(entry, mode):
        kind = entry.get("kind") or "kw"

        if mode == "Keywords":
            return kind == "kw"

        if mode == "Profile views":
            return kind == "profile"

        if mode == "Downloads":
            return kind == "download"

        return True  # "All"

    def _kw_render(self):
        feed = self._feeds["keywordwatch"]

        if not feed["built"]:
            return

        entries_box = feed["list_widget"]
        self._box_clear(entries_box)

        filter_mode = feed.get("filter") or "All"
        shown = 0

        query = (feed.get("search_query") or "").strip().lower()

        for entry in feed["entries"]:  # newest first
            if not self._kw_matches_filter(entry, filter_mode):
                continue
            if query:
                txt = self._kw_format_entry(entry).lower()
                if query not in txt:
                    continue

            shown += 1
            button = self._kw_make_entry_button(entry)

            if self._is_gtk4():
                entries_box.append(button)
            else:
                entries_box.pack_start(button, True, True, 0)

        self._show_all(entries_box)

        label = feed["status_label"]

        if label is not None:
            suffix = "entry" if shown == 1 else "entries"
            parts = [f"{shown} {suffix}"]
            if filter_mode != "All":
                parts.append(filter_mode)
            if query:
                parts.append("match")
            label.set_text(" (".join(parts) + (")" * (len(parts) - 1)))

    def _kw_make_entry_button(self, entry):
        from gi.repository import Gtk

        button = Gtk.Button()
        button.set_hexpand(True)
        button.set_halign(Gtk.Align.FILL)

        label = Gtk.Label(label=self._kw_format_entry(entry))
        label.set_xalign(0.0)
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        label.set_wrap(True)
        label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

        if self._is_gtk4():
            button.set_has_frame(False)
            button.set_child(label)

            gesture = Gtk.GestureClick()
            gesture.set_button(3)  # right button
            gesture.connect("pressed", self._kw_on_entry_right_click, entry)
            button.add_controller(gesture)
        else:
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.add(label)
            button.connect("button-press-event", self._kw_on_entry_button_press, entry)

        return button

    def _kw_on_entry_button_press(self, button, event, entry):
        if event.button != 3:  # right button
            return False

        self._kw_show_entry_menu(button, entry)
        return True

    def _kw_on_entry_right_click(self, gesture, n_press, x, y, entry):
        widget = gesture.get_widget()

        if widget is not None:
            self._kw_show_entry_menu(widget, entry, x, y)

    def _kw_show_entry_menu(self, widget, entry, x=None, y=None):
        from gi.repository import Gdk, Gtk

        popover = Gtk.Popover()

        if self._is_gtk4():
            popover.set_parent(widget)
        else:
            popover.set_relative_to(widget)

        try:
            popover.set_autohide(True)
        except Exception:
            pass

        # Anchor at the click point so the menu isn't clipped at the window edge.
        if x is not None and y is not None:
            try:
                rect = Gdk.Rectangle()
                rect.x = int(x)
                rect.y = int(y)
                rect.width = 1
                rect.height = 1
                popover.set_pointing_to(rect)
            except Exception:
                pass

        copy_button = Gtk.Button.new_with_label("Copy")
        copy_button.set_tooltip_text("Copy this entry to the clipboard")

        remove_button = Gtk.Button.new_with_label("Remove")
        remove_button.set_tooltip_text("Remove this entry")

        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        buttons = [copy_button]
        go_to_room_button = None

        if (entry.get("room") or "").strip():
            go_to_room_button = Gtk.Button.new_with_label("Go to room")
            go_to_room_button.set_tooltip_text("Open this room and switch to it")
            buttons.append(go_to_room_button)

        buttons.append(remove_button)

        if self._is_gtk4():
            for button in buttons:
                button.set_has_frame(False)
                menu_box.append(button)

            popover.set_child(menu_box)
        else:
            for button in buttons:
                button.set_relief(Gtk.ReliefStyle.NONE)
                menu_box.pack_start(button, False, False, 0)

            popover.add(menu_box)
            popover.show_all()

        copy_button.connect("clicked", self._kw_on_copy_entry_clicked, entry, popover)

        if go_to_room_button is not None:
            go_to_room_button.connect("clicked", self._kw_on_go_to_room_clicked, entry, popover)

        remove_button.connect("clicked", self._kw_on_remove_entry_clicked, entry, popover)
        popover.popup()

    def _kw_on_copy_entry_clicked(self, _button, entry, popover):
        popover.popdown()
        self._copy_to_clipboard(self._kw_format_entry(entry))

    def _kw_on_remove_entry_clicked(self, _button, entry, popover):
        popover.popdown()
        self._kw_remove_entry(entry)

    def _kw_on_go_to_room_clicked(self, _button, entry, popover):
        popover.popdown()

        room = (entry.get("room") or "").strip()

        if not room:
            return

        chatrooms = getattr(self.core, "chatrooms", None)

        if chatrooms is None:
            return

        try:
            room = chatrooms.sanitize_room_name(room)

            if not room:
                return

            chatrooms.show_room(room)
            self.log("Switched to room '%s'.", (room,))
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Shitlist pane (log + settings) and feed logic
    # ------------------------------------------------------------------ #

    def _shitlist_load(self):
        feed = self._feeds["shitlist"]
        feed["entries"] = []

        # Accept both the current rich format (with "text"/"room") and the
        # legacy compact format ({"ts", "user", "ip", "keyword"}) so historical
        # entries are never silently dropped on load.
        for item in self._load_daily_log(self._shitlist_log_dir(), ("ts", "user")):
            ts = self._safe_float(item.get("ts"))

            if not ts:
                continue

            feed["entries"].append({
                "ts": ts,
                "user": str(item.get("user") or ""),
                "room": str(item.get("room", "") or ""),
                "text": str(item.get("text", "") or ""),
                "keyword": str(item.get("keyword", "") or ""),
                "banned": self._to_bool(item.get("banned", False)),
                "ip": item.get("ip"),
            })

        feed["entries"].sort(key=lambda entry: entry["ts"], reverse=True)

    def _shitlist_save(self):
        self._save_daily_log(
            self._feeds["shitlist"]["entries"],
            self._shitlist_log_dir(),
            "shitlist_log_start",
            "Shitlist",
        )

    def _shitlist_prune(self):
        retention = RETENTION_SECONDS.get(self.settings.get("shitlist_retention"))

        if not retention:
            return False

        cutoff = time.time() - retention
        feed = self._feeds["shitlist"]
        new_entries = [entry for entry in feed["entries"] if entry["ts"] >= cutoff]

        if len(new_entries) == len(feed["entries"]):
            return False

        feed["entries"] = new_entries
        return True

    def _shitlist_clear(self):
        self._feeds["shitlist"]["entries"] = []
        self._shitlist_save()
        self._shitlist_render()
        self.log("Shitlist log cleared.")

    def _shitlist_remove_entry(self, entry):
        feed = self._feeds["shitlist"]
        imported = feed.get("imported_entries")

        if imported is not None:
            try:
                imported.remove(entry)
            except ValueError:
                pass

            self._shitlist_render()
            return

        for i, existing in enumerate(feed["entries"]):
            if existing is entry:
                del feed["entries"][i]
                self._shitlist_save()
                self._shitlist_render()
                return

    def _shitlist_format_entry(self, entry):
        ts = entry.get("ts") or 0
        stamp = self._format_timestamp(ts)
        room = entry.get("room") or "private"
        user = entry.get("user") or "?"
        text = str(entry.get("text") or "")
        keyword = entry.get("keyword") or ""
        suffix = " [kw:%s]" % keyword if keyword else ""

        return f"{stamp} [{room}] [{user}]: {text}{suffix}"

    def _on_shitlist_clear_clicked(self, *_args):
        self._shitlist_clear()

    def _import_shitlist_log_clicked(self, *_args):
        from gi.repository import GLib, Gtk

        def load_from_path(path):
            if path:
                self._shitlist_show_imported_log(path)

        try:
            # GTK 4.10+
            dialog = Gtk.FileDialog(title="Import Shitlist log", modal=True)

            def on_open(_dialog, result):
                self._active_file_dialog = None

                try:
                    gfile = dialog.open_finish(result)
                except GLib.GError:
                    return

                load_from_path(gfile.get_path() if gfile else None)

            self._active_file_dialog = dialog
            dialog.open(None, None, on_open)
        except (AttributeError, TypeError):
            # GTK 3 / GTK 4 < 4.10
            dialog = Gtk.FileChooserNative(
                title="Import Shitlist log",
                action=Gtk.FileChooserAction.OPEN,
            )

            def on_response(_dialog, response_id):
                self._active_file_dialog = None

                if response_id == Gtk.ResponseType.ACCEPT:
                    gfile = _dialog.get_file()
                    load_from_path(gfile.get_path() if gfile else None)

                _dialog.destroy()

            dialog.connect("response", on_response)
            self._active_file_dialog = dialog
            dialog.show()

    def _shitlist_close_imported_log(self, *_args):
        feed = self._feeds["shitlist"]
        feed["imported_entries"] = None
        feed["imported_path"] = None

        if feed.get("import_button") is not None:
            feed["import_button"].set_visible(True)

        if feed.get("close_button") is not None:
            feed["close_button"].set_visible(False)

        self._shitlist_render()

    def _shitlist_show_imported_log(self, path):
        entries = self._shitlist_parse_import_file(path)

        feed = self._feeds["shitlist"]
        feed["imported_entries"] = entries
        feed["imported_path"] = path

        if feed.get("import_button") is not None:
            feed["import_button"].set_visible(False)

        if feed.get("close_button") is not None:
            feed["close_button"].set_visible(True)

        self._shitlist_render()
        self.log("Imported %d Shitlist entry(ies) from '%s'.", (len(entries), path))

    def _shitlist_parse_import_file(self, path):
        import json

        entries = []

        try:
            with open(path, "r", encoding="utf-8") as file_handle:
                for line in file_handle:
                    line = line.strip()

                    if not line:
                        continue

                    try:
                        item = json.loads(line)
                    except ValueError:
                        item = None

                    if isinstance(item, dict) and "user" in item and "text" in item:
                        entry = {
                            "ts": float(item.get("ts", 0)),
                            "user": str(item.get("user", "")),
                            "room": str(item.get("room", "")),
                            "text": str(item.get("text", "")),
                            "keyword": str(item.get("keyword", "")),
                            "banned": bool(item.get("banned", False)),
                            "ip": item.get("ip"),
                        }
                    else:
                        start = line.find("<")
                        end = line.find(">", start + 1) if start != -1 else -1
                        user = line[start + 1:end].strip() if start != -1 and end != -1 else ""

                        entry = {
                            "ts": 0,
                            "user": user,
                            "room": "",
                            "text": line,
                            "keyword": "",
                            "banned": False,
                            "ip": None,
                        }

                    entries.append(entry)
        except OSError as error:
            self.log("Could not read imported log: %s", error)

        entries.sort(key=lambda e: e["ts"], reverse=True)
        return entries

    def _build_shitlist_page(self, feed):
        from gi.repository import Gtk

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_margin_top(6)
        split.set_margin_bottom(6)
        split.set_margin_start(6)
        split.set_margin_end(6)

        # ---- Left: log view ----
        log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        log_box.set_hexpand(True)
        log_box.set_vexpand(True)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        clear_button = self._make_toolbar_button("edit-clear", "Clear Log", "Delete all entries from the Shitlist log")
        clear_button.connect("clicked", self._on_shitlist_clear_clicked)

        open_folder_button = self._make_toolbar_button("folder-open", "Open Log Folder", "Open the folder where the Shitlist log is stored")
        open_folder_button.connect("clicked", self._open_shitlist_logs_clicked)

        import_button = self._make_toolbar_button("document-open", "Import Log", "Open a saved log file to view it temporarily")
        import_button.connect("clicked", self._import_shitlist_log_clicked)
        feed["import_button"] = import_button

        close_button = self._make_toolbar_button("window-close", "Close Log", "Return to the live Shitlist log")
        close_button.connect("clicked", self._shitlist_close_imported_log)
        close_button.set_visible(False)
        feed["close_button"] = close_button

        status_label = Gtk.Label()
        status_label.set_halign(Gtk.Align.END)
        status_label.set_hexpand(True)
        feed["status_label"] = status_label

        self._box_add(toolbar, clear_button)
        self._box_add(toolbar, open_folder_button)
        self._box_add(toolbar, import_button)
        self._box_add(toolbar, close_button)

        if self._is_gtk4():
            toolbar.append(status_label)
        else:
            toolbar.pack_start(status_label, True, True, 0)

        self._box_add(log_box, toolbar)

        self._box_add(log_box, self._make_find_entry(feed, "shitlist"))

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        entries_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._set_scrolled_child(scrolled, entries_box)
        feed["list_widget"] = entries_box

        self._box_add(log_box, scrolled)

        # ---- Right: settings (scrollable) ----
        settings_box = self._build_shitlist_settings()

        settings_scroll = Gtk.ScrolledWindow()
        settings_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        settings_scroll.set_size_request(320, -1)
        self._set_scrolled_child(settings_scroll, settings_box)

        self._box_add(split, log_box)
        self._box_add(split, settings_scroll)
        self._box_add(page, split)

        return page

    def _build_shitlist_settings(self):
        from gi.repository import Gtk

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_hexpand(True)
        box.set_margin_start(12)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_end(12)

        title = Gtk.Label()
        title.set_markup("<b>Shitlist settings</b>")
        title.set_halign(Gtk.Align.START)
        self._box_add(box, title)

        self._shitlist_enable_check = Gtk.CheckButton.new_with_label("Enable Shitlist")
        self._shitlist_enable_check.set_active(bool(self.settings.get("shitlist_enabled", True)))
        self._shitlist_enable_check.connect("toggled", self._on_shitlist_enable_toggled)
        self._box_add(box, self._shitlist_enable_check)

        mode_label = Gtk.Label(label="Mode")
        mode_label.set_halign(Gtk.Align.START)
        self._box_add(box, mode_label)

        self._shitlist_mode_combo = Gtk.ComboBoxText()
        self._shitlist_mode_combo.append_text("Automatic mode")
        self._shitlist_mode_combo.append_text("Manual review mode")
        self._shitlist_mode_combo.set_active(1 if self.settings.get("shitlist_manual_review", False) else 0)
        self._shitlist_mode_combo.connect("changed", self._on_shitlist_mode_changed)
        self._box_add(box, self._shitlist_mode_combo)

        hint = Gtk.Label()
        hint.set_markup("<small>Automatic mode bans + ignores users who say a keyword.\nManual review mode only logs them (no ban or ignore).</small>")
        hint.set_halign(Gtk.Align.START)
        hint.set_wrap(True)
        hint.set_xalign(0.0)
        self._box_add(box, hint)

        kw_label = Gtk.Label(label="Keywords (one per line)")
        kw_label.set_halign(Gtk.Align.START)
        self._box_add(box, kw_label)

        self._shitlist_keywords_view = self._make_text_view("\n".join(self.settings.get("shitlist_keywords", [])))
        self._box_add(box, self._make_scrolled_editor(self._shitlist_keywords_view, 90))

        kw_apply = Gtk.Button.new_with_label("Apply keywords")
        kw_apply.connect("clicked", self._on_shitlist_keywords_apply)
        self._box_add(box, kw_apply)

        wl_label = Gtk.Label(label="Whitelist — usernames to never flag (one per line)")
        wl_label.set_halign(Gtk.Align.START)
        wl_label.set_wrap(True)
        wl_label.set_xalign(0.0)
        self._box_add(box, wl_label)

        self._shitlist_whitelist_view = self._make_text_view("\n".join(self.settings.get("shitlist_whitelist_users", [])))
        self._box_add(box, self._make_scrolled_editor(self._shitlist_whitelist_view, 90))

        wl_apply = Gtk.Button.new_with_label("Apply whitelist")
        wl_apply.connect("clicked", self._on_shitlist_whitelist_apply)
        self._box_add(box, wl_apply)

        show_label = Gtk.Label(label="Public chat msg whitelist — ignored users whose messages still show in public rooms (one username per line)")
        show_label.set_halign(Gtk.Align.START)
        show_label.set_wrap(True)
        show_label.set_xalign(0.0)
        self._box_add(box, show_label)

        self._shitlist_show_messages_view = self._make_text_view("\n".join(self.settings.get("shitlist_show_messages", [])))
        self._box_add(box, self._make_scrolled_editor(self._shitlist_show_messages_view, 90))

        show_apply = Gtk.Button.new_with_label("Apply message whitelist")
        show_apply.connect("clicked", self._on_shitlist_show_messages_apply)
        self._box_add(box, show_apply)

        users_label = Gtk.Label(label="Shitlisted Users — add a name to ban+ignore (name + IP); remove a name to unban+unignore (one username per line)")
        users_label.set_halign(Gtk.Align.START)
        users_label.set_wrap(True)
        users_label.set_xalign(0.0)
        self._box_add(box, users_label)

        self._shitlist_users_view = self._make_text_view("\n".join(self.settings.get("shitlist_users", [])))
        self._box_add(box, self._make_scrolled_editor(self._shitlist_users_view, 90))

        users_apply = Gtk.Button.new_with_label("Apply shitlisted users")
        users_apply.connect("clicked", self._on_shitlist_users_apply)
        self._box_add(box, users_apply)

        ret_label = Gtk.Label(label="Keep entries for")
        ret_label.set_halign(Gtk.Align.START)
        self._box_add(box, ret_label)

        self._shitlist_retention_combo = Gtk.ComboBoxText()
        labels = list(RETENTION_SECONDS.keys())

        for label in labels:
            self._shitlist_retention_combo.append_text(label)

        current = self.settings.get("shitlist_retention", "7 days")

        if current in labels:
            self._shitlist_retention_combo.set_active(labels.index(current))
        else:
            self._shitlist_retention_combo.set_active(labels.index("7 days"))

        self._shitlist_retention_combo.connect("changed", self._on_shitlist_retention_changed)
        self._box_add(box, self._shitlist_retention_combo)

        # ---- Slur counter stats ----
        stats_title = Gtk.Label()
        stats_title.set_markup("<b>Slur counter — users</b>")
        stats_title.set_halign(Gtk.Align.START)
        stats_title.set_margin_top(12)
        self._box_add(box, stats_title)

        stats_hint = Gtk.Label()
        stats_hint.set_markup("<small>Users dropped if last swear + last seen >30 days ago.</small>")
        stats_hint.set_halign(Gtk.Align.START)
        stats_hint.set_wrap(True)
        stats_hint.set_xalign(0.0)
        self._box_add(box, stats_hint)

        sort_combo = Gtk.ComboBoxText()
        sort_combo.append_text("Most triggers")
        sort_combo.append_text("Most recent")
        sort_combo.set_active(0)
        sort_combo.connect("changed", lambda c: self._shitlist_render_stats(self._feeds["shitlist"]))
        feed["stats_sort_combo"] = sort_combo
        self._box_add(box, sort_combo)

        stats_scroll = Gtk.ScrolledWindow()
        stats_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        stats_scroll.set_size_request(-1, 160)
        stats_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self._set_scrolled_child(stats_scroll, stats_list)
        feed["stats_widget"] = stats_list
        feed["stats_scroll"] = stats_scroll
        self._box_add(box, stats_scroll)

        return box

    @staticmethod
    def _make_text_view(initial_text):
        from gi.repository import Gtk

        view = Gtk.TextView()
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(initial_text)
        return view

    @classmethod
    def _make_scrolled_editor(cls, view, height):
        from gi.repository import Gtk

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_size_request(-1, height)
        cls._set_scrolled_child(scrolled, view)
        return scrolled

    @staticmethod
    def _read_text_view(view):
        buffer = view.get_buffer()
        start, end = buffer.get_bounds()
        return buffer.get_text(start, end, False)

    @staticmethod
    def _parse_lines(text):
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _write_config_safe(self):
        try:
            self.config.write_configuration()
        except Exception:
            pass

    def _on_shitlist_enable_toggled(self, check):
        self.settings["shitlist_enabled"] = bool(check.get_active())
        self._write_config_safe()

    def _on_shitlist_mode_changed(self, combo):
        mode = combo.get_active_text()
        self.settings["shitlist_manual_review"] = (mode == "Manual review mode")
        self._write_config_safe()

    def _on_shitlist_keywords_apply(self, *_args):
        self.settings["shitlist_keywords"] = self._parse_lines(self._read_text_view(self._shitlist_keywords_view))
        self._write_config_safe()
        self.log("Shitlist keywords updated (%d).", (len(self.settings["shitlist_keywords"]),))

    def _on_shitlist_whitelist_apply(self, *_args):
        self.settings["shitlist_whitelist_users"] = self._parse_lines(self._read_text_view(self._shitlist_whitelist_view))
        self._write_config_safe()
        self.log("Shitlist whitelist updated (%d).", (len(self.settings["shitlist_whitelist_users"]),))

    def _on_shitlist_retention_changed(self, combo):
        self.settings["shitlist_retention"] = combo.get_active_text() or "7 days"
        self._write_config_safe()

    def _on_shitlist_show_messages_apply(self, *_args):
        self.settings["shitlist_show_messages"] = self._parse_lines(self._read_text_view(self._shitlist_show_messages_view))
        self._shitlist_sync_show_messages_set()
        self._write_config_safe()
        self.log("Public chat msg whitelist updated (%d).", (len(self.settings["shitlist_show_messages"]),))

    def _on_shitlist_users_apply(self, *_args):
        new_users = self._parse_lines(self._read_text_view(self._shitlist_users_view))

        seen = set()
        normalized = []

        for username in new_users:
            username = self._shitlist_normalize_username(username)

            if username and username not in seen:
                seen.add(username)
                normalized.append(username)

        old_users = set(self.settings.get("shitlist_users", []))

        for username in sorted(set(normalized) - old_users):
            changed, _ip = self._shitlist_ban_and_ignore(username)

            if changed:
                self.log("Banned and ignored user '%s' (added in Shitlist pane)", (username,))

        for username in sorted(old_users - set(normalized)):
            self._shitlist_unban(username)

        self.settings["shitlist_users"] = normalized
        self._write_config_safe()
        self.log("Shitlisted users updated (%d).", (len(normalized),))

    def _shitlist_render(self):
        feed = self._feeds["shitlist"]

        if not feed["built"]:
            return

        entries_box = feed["list_widget"]
        self._box_clear(entries_box)

        imported = feed.get("imported_entries")
        display = imported if imported is not None else feed["entries"]

        query = (feed.get("search_query") or "").strip().lower()
        shown = 0

        for entry in display:  # newest first
            if query:
                txt = self._shitlist_format_entry(entry).lower()
                if query not in txt:
                    continue
            shown += 1
            button = self._shitlist_make_entry_button(entry)

            if self._is_gtk4():
                entries_box.append(button)
            else:
                entries_box.pack_start(button, True, True, 0)

        self._show_all(entries_box)

        label = feed["status_label"]

        if label is not None:
            total = len(display)
            suffix = "entry" if total == 1 else "entries"
            if query:
                label.set_text(f"{shown}/{total} {suffix}")
            elif imported is not None:
                label.set_text(f"(imported) {total} {suffix}")
            else:
                label.set_text(f"{total} {suffix}")

        self._shitlist_render_stats(feed)

    def _shitlist_render_stats(self, feed):
        from gi.repository import Gtk
        stats_list = feed.get("stats_widget")
        if stats_list is None:
            return
        self._box_clear(stats_list)
        entries = feed.get("entries")
        if not entries:
            lbl = Gtk.Label(label="No data yet")
            lbl.set_xalign(0.0)
            self._box_add(stats_list, lbl)
            self._show_all(stats_list)
            return
        now = time.time()
        cutoff = 30 * 86400
        users = {}
        for e in entries:
            u = e.get("user", "")
            if not u:
                continue
            ts = self._safe_float(e.get("ts"), 0)
            rec = users.get(u)
            if rec is None:
                users[u] = [1, ts, ts]
            else:
                rec[0] += 1
                if ts > rec[1]:
                    rec[1] = ts
                if ts > rec[2]:
                    rec[2] = ts
        active = []
        for u, (cnt, last_swore, last_seen) in users.items():
            if (now - last_swore > cutoff) and (now - last_seen > cutoff):
                continue
            active.append((u, cnt, last_swore))
        sort_combo = feed.get("stats_sort_combo")
        by_recent = False
        if sort_combo is not None and sort_combo.get_active() == 1:
            by_recent = True
            active.sort(key=lambda x: x[2], reverse=True)
        else:
            active.sort(key=lambda x: x[1], reverse=True)
        if not active:
            lbl = Gtk.Label(label="No active offenders")
            lbl.set_xalign(0.0)
            self._box_add(stats_list, lbl)
            self._show_all(stats_list)
            return
        for u, cnt, last_ts in active:
            ago = self._format_ago(now - last_ts)
            line = f"{u}  —  {cnt}x  ({ago})"
            lbl = Gtk.Label(label=line)
            lbl.set_xalign(0.0)
            lbl.set_wrap(True)
            lbl.set_hexpand(True)
            lbl.set_margin_start(4)
            self._box_add(stats_list, lbl)
        self._show_all(stats_list)

    @staticmethod
    def _format_ago(seconds):
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return "%dm ago" % int(seconds / 60)
        if seconds < 86400:
            return "%dh ago" % int(seconds / 3600)
        days = int(seconds / 86400)
        return "%dd ago" % days

    def _shitlist_make_entry_button(self, entry):
        from gi.repository import Gtk

        button = Gtk.Button()
        button.set_hexpand(True)
        button.set_halign(Gtk.Align.FILL)

        label = Gtk.Label(label=self._shitlist_format_entry(entry))
        label.set_xalign(0.0)
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        label.set_wrap(True)
        label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

        if self._is_gtk4():
            button.set_has_frame(False)
            button.set_child(label)

            gesture = Gtk.GestureClick()
            gesture.set_button(3)  # right button
            gesture.connect("pressed", self._shitlist_on_entry_right_click, entry)
            button.add_controller(gesture)
        else:
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.add(label)
            button.connect("button-press-event", self._shitlist_on_entry_button_press, entry)

        return button

    def _shitlist_on_entry_button_press(self, button, event, entry):
        if event.button != 3:  # right button
            return False

        self._shitlist_show_entry_menu(button, entry, event.x, event.y)
        return True

    def _shitlist_on_entry_right_click(self, gesture, _n_press, x, y, entry):
        widget = gesture.get_widget()

        if widget is not None:
            self._shitlist_show_entry_menu(widget, entry, x, y)

    def _shitlist_show_entry_menu(self, widget, entry, x=None, y=None):
        from gi.repository import Gdk, Gtk

        popover = Gtk.Popover()

        if self._is_gtk4():
            popover.set_parent(widget)
        else:
            popover.set_relative_to(widget)

        try:
            popover.set_autohide(True)
        except Exception:
            pass

        # Anchor the popover at the click point so it isn't clipped at the
        # window edge (default anchoring can push it off-screen in fullscreen).
        if x is not None and y is not None:
            try:
                rect = Gdk.Rectangle()
                rect.x = int(x)
                rect.y = int(y)
                rect.width = 1
                rect.height = 1
                popover.set_pointing_to(rect)
            except Exception:
                pass

        remove_button = Gtk.Button.new_with_label("Remove entry")
        block_button = Gtk.Button.new_with_label("Block + ignore user")
        whitelist_button = Gtk.Button.new_with_label("Whitelist user")

        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        for b in (remove_button, block_button, whitelist_button):
            if self._is_gtk4():
                b.set_has_frame(False)
                menu_box.append(b)
            else:
                b.set_relief(Gtk.ReliefStyle.NONE)
                menu_box.pack_start(b, False, False, 0)

        if self._is_gtk4():
            popover.set_child(menu_box)
        else:
            popover.add(menu_box)
            popover.show_all()

        remove_button.connect("clicked", self._shitlist_on_remove_entry_clicked, entry, popover)
        block_button.connect("clicked", self._shitlist_on_block_clicked, entry, popover)
        whitelist_button.connect("clicked", self._shitlist_on_whitelist_clicked, entry, popover)
        popover.popup()

    def _shitlist_on_remove_entry_clicked(self, _button, entry, popover):
        popover.popdown()
        self._shitlist_remove_entry(entry)

    def _shitlist_on_block_clicked(self, _button, entry, popover):
        popover.popdown()
        user = entry.get("user")

        if user:
            self._shitlist_ban_and_ignore(user)
            self.log("Blocked + ignored user '%s' (from Shitlist log).", (user,))

    def _shitlist_on_whitelist_clicked(self, _button, entry, popover):
        popover.popdown()
        user = entry.get("user")

        if not user:
            return

        whitelist = list(self.settings.get("shitlist_whitelist_users", []))
        normalized = self._shitlist_normalize_username(user)

        if any(self._shitlist_normalize_username(u) == normalized for u in whitelist):
            self.log("User '%s' is already whitelisted.", (user,))
            return

        whitelist.append(user)
        self.settings["shitlist_whitelist_users"] = whitelist
        self._write_config_safe()

        if getattr(self, "_shitlist_whitelist_view", None) is not None:
            self._shitlist_whitelist_view.get_buffer().set_text("\n".join(whitelist))

        self.log("Whitelisted user '%s' (they won't be flagged anymore).", (user,))

    # ------------------------------------------------------------------ #
    # Shared GUI helpers
    # ------------------------------------------------------------------ #

    def _open_listenings_logs_clicked(self, *_args):
        self._open_logs_folder(self._listenings_log_dir())

    def _open_kw_logs_clicked(self, *_args):
        self._open_logs_folder(self._kw_log_dir())

    def _open_shitlist_logs_clicked(self, *_args):
        self._open_logs_folder(self._shitlist_log_dir())

    def _open_logs_folder(self, folder):
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass

        try:
            self._open_folder(folder)
        except OSError as error:
            self.log("Could not open logs folder: %s", error)

    @staticmethod
    def _open_folder(path):
        """Open a folder in the platform's file manager."""

        import subprocess
        import sys

        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _copy_to_clipboard(self, text):
        """Put text on the system clipboard via Nicotine+'s own clipboard helper
        (handles both GTK 3 and GTK 4 correctly)."""

        from pynicotine.gtkgui.widgets import clipboard

        clipboard.copy_text(text)

    def _update_status(self, feed):
        if feed["status_label"] is None:
            return

        count = len(feed["entries"])
        suffix = "entry" if count == 1 else "entries"
        feed["status_label"].set_text(f"{count} {suffix}")

    def _make_toolbar_button(self, icon_name, label_text, tooltip=None):
        """Build a flat icon+label button like Nicotine+'s toolbar buttons."""

        from gi.repository import Gtk

        button = Gtk.Button()

        if self._is_gtk4():
            button.set_has_frame(False)

            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            content.append(Gtk.Image.new_from_icon_name(icon_name))
            content.append(Gtk.Label(label=label_text))
            button.set_child(content)
        else:
            button.set_relief(Gtk.ReliefStyle.NONE)

            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            content.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON), False, False, 0)
            content.pack_start(Gtk.Label(label=label_text), False, False, 0)
            button.add(content)

        if tooltip:
            button.set_tooltip_text(tooltip)

        return button

    # ------------------------------------------------------------------ #
    # Shared helpers
    # ------------------------------------------------------------------ #

    def _is_now_playing(self, text):
        """True if `text` looks like an auto 'now playing' /me announcement."""

        if not text:
            return False

        lowered = text.lower()
        markers = self.settings.get("nowplaying_markers") or DEFAULT_NOW_PLAYING_MARKERS

        for marker in markers:
            marker = (marker or "").strip()

            if marker and marker.lower() in lowered:
                return True

        return False

    @staticmethod
    def _safe_float(value, default=0.0):
        """Coerce a value to float, returning `default` on failure (never raises)."""

        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(value):
        """Coerce stored JSON scalars to bool without the 'false' -> True trap."""

        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")

        return bool(value)

    @staticmethod
    def _format_timestamp(ts):
        """Portable, locale-independent 'M/D/YYYY H:MM:SS AM' (no %# directives)."""

        if not ts:
            return "--:--:--"

        try:
            local = time.localtime(ts)
            hour = local.tm_hour % 12 or 12
            return "%d/%d/%d %d:%02d:%02d %s" % (
                local.tm_mon, local.tm_mday, local.tm_year,
                hour, local.tm_min, local.tm_sec, time.strftime("%p", local),
            )
        except (OverflowError, ValueError, OSError):
            return "--:--:--"

    def _render_feed(self, feed_key):
        if feed_key == "listenings":
            self._listenings_render()
        elif feed_key == "keywordwatch":
            self._kw_render()
        elif feed_key == "shitlist":
            self._shitlist_render()

    def _make_find_entry(self, feed, feed_key):
        from gi.repository import Gtk

        search_entry = Gtk.SearchEntry()
        search_entry.set_placeholder_text("Find in log… (Ctrl+F)")
        search_entry.set_hexpand(True)
        search_entry.connect("search-changed", self._on_find_changed, feed_key)
        search_entry.connect("stop-search", self._on_find_stop_search, feed_key)

        feed["search_entry"] = search_entry
        return search_entry

    def _wire_find_shortcuts(self, page, feed_key):
        try:
            from pynicotine.gtkgui.widgets.accelerator import Accelerator

            Accelerator("<Primary>f", page, self._on_find_show, feed_key)
            Accelerator("Escape", page, self._on_find_hide, feed_key)
        except Exception:
            pass

    def _on_find_show(self, _widget, _args, feed_key):
        feed = self._feeds.get(feed_key)

        if feed:
            entry = feed.get("search_entry")

            if entry is not None:
                entry.grab_focus()

        return True

    def _on_find_hide(self, _widget, _args, feed_key):
        feed = self._feeds.get(feed_key)

        if feed:
            entry = feed.get("search_entry")

            if entry is not None:
                entry.set_text("")

            feed["search_query"] = ""
            self._render_feed(feed_key)

        return True

    def _on_find_changed(self, entry, feed_key):
        feed = self._feeds.get(feed_key)

        if feed:
            feed["search_query"] = entry.get_text() or ""
            self._render_feed(feed_key)

    def _on_find_stop_search(self, _entry, feed_key):
        feed = self._feeds.get(feed_key)

        if feed:
            feed["search_query"] = ""
            self._render_feed(feed_key)

    # ------------------------------------------------------------------ #
    # GTK 3 / GTK 4 compatibility helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_gtk4():
        from gi.repository import Gtk

        return Gtk.get_major_version() >= 4

    @classmethod
    def _box_add(cls, box, child):
        if cls._is_gtk4():
            box.append(child)
        else:
            box.pack_start(child, False, False, 0)

    @classmethod
    def _box_add_fill(cls, box, child):
        if cls._is_gtk4():
            child.set_hexpand(True)
            box.append(child)
        else:
            box.pack_start(child, True, True, 0)

    @classmethod
    def _box_clear(cls, box):
        if cls._is_gtk4():
            child = box.get_first_child()

            while child is not None:
                next_child = child.get_next_sibling()
                box.remove(child)
                child = next_child
        else:
            for child in box.get_children():
                box.remove(child)

    @classmethod
    def _set_scrolled_child(cls, scrolled, child):
        if cls._is_gtk4():
            scrolled.set_child(child)
        else:
            scrolled.add(child)

    @classmethod
    def _show_all(cls, widget):
        if not cls._is_gtk4():
            widget.show_all()

    @classmethod
    def _listbox_append(cls, listbox, row):
        if cls._is_gtk4():
            listbox.append(row)
        else:
            listbox.add(row)

    @classmethod
    def _finalize_page(cls, page):
        """Show the page explicitly on GTK 3 (GTK 4 widgets are visible by default)."""

        if cls._is_gtk4():
            return

        page.show_all()
