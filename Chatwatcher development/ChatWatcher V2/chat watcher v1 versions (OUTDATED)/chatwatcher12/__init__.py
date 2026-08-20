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
import time

from pynicotine.events import events
from pynicotine.pluginsystem import BasePlugin, returncode


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

LISTENINGS_TAB_NAME = "Played"
LISTENINGS_TAB_ID = "listenings"
LISTENINGS_LOG_FILENAME = "listenings.log"

KEYWORDWATCH_TAB_NAME = "Keywords"
KEYWORDWATCH_TAB_ID = "keywordwatch"
KEYWORDWATCH_LOG_FILENAME = "keywordwatch.log"

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
            "listenings_blocked_users": [],
            "listenings_retention": "1 day",
            # Keyword Watch
            "kw_keywords": [],
            "kw_case_sensitive": False,
            "kw_blocked_users": [],
            "kw_retention": "1 day",
            # Shitlist
            "shitlist_enabled": True,
            "shitlist_keywords": [],
            "shitlist_users": [],
            "shitlist_show_messages": [],
            # log rotation bookkeeping (first day each feature started logging)
            "listenings_log_start": "",
            "kw_log_start": "",
            "shitlist_log_start": "",
        }

        self.metasettings = {
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
                "description": "Keywords — hide these users (one username per line)",
                "group": "Keywords",
                "type": "list string",
            },
            "kw_retention": {
                "description": "Keywords — keep entries for",
                "group": "Keywords",
                "type": "dropdown",
                "options": tuple(RETENTION_SECONDS.keys()),
            },
            "shitlist_enabled": {
                "description": "Shitlist — auto-ban+ignore users who say a keyword",
                "group": "Shitlist",
                "type": "bool",
            },
            "shitlist_keywords": {
                "description": "Shitlist — words that get the sender banned+ignored (one per line; quote multi-word phrases)",
                "group": "Shitlist",
                "type": "list string",
            },
            "shitlist_show_messages": {
                "description": "Public chat msg whitelist\nIgnored users whose messages still show in public rooms (they can't DM you). One username per line.",
                "group": "Public chat msg whitelist",
                "type": "list string",
            },
            "shitlist_users": {
                "description": "Currently banned+ignored — add a name to ban+ignore it, remove to unban+unignore",
                "group": "Shitlist: Shitlisted Users",
                "type": "list string",
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
        self._shitlist_original_is_user_ignored = None
        self._shitlist_original_is_user_ip_ignored = None
        self._shitlist_ignore_filter_patched = False

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
        }

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def init(self):
        self._migrate_legacy_logs()
        self._listenings_load()
        self._listenings_prune()
        self._kw_load()
        self._kw_prune()
        self._kw_seed_default_keywords()
        self._start_timers()
        self._schedule_build("listenings")
        self._schedule_build("keywordwatch")

    def disable(self):
        self._stop_timers()
        self._remove_tab("listenings")
        self._remove_tab("keywordwatch")
        self._shitlist_enabled = False
        self._shitlist_restore_user_menu()
        self._shitlist_restore_ignore_filter()
        self._shitlist_ignore_timers.clear()
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
        self._shitlist_patch_ignore_filter()
        self._shitlist_patch_user_menu()

    # ------------------------------------------------------------------ #
    # Chat hooks — Played (Listenings): /me (now-playing) capture
    #
    # Public-room /me messages are caught in public_room_message_notification()
    # further down (so they work in every joined room, not just the focused
    # one). Private-chat /me and the user's own /me use the hooks below.
    # ------------------------------------------------------------------ #

    def incoming_private_chat_event(self, user, line):
        # Whitelisted users (Shitlist "Public chat msg whitelist") are ignored
        # users whose messages show in PUBLIC rooms only — hard-block their DMs
        # here, since the whitelist exception on the ignore filter would
        # otherwise let private messages slip through.
        if self._shitlist_is_whitelisted(user):
            return returncode["zap"]

        if line.startswith("/me "):
            self._listenings_add_entry(user, line[4:].strip(), context="pm")

        return None

    def outgoing_public_chat_event(self, room, line):
        if line.startswith("/me "):
            self._listenings_add_entry(
                self.core.users.login_username, line[4:].strip(), is_self=True, context=room
            )

        return None

    def outgoing_private_chat_event(self, user, line):
        if line.startswith("/me "):
            self._listenings_add_entry(
                self.core.users.login_username, line[4:].strip(), is_self=True, context="pm"
            )

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
    # whitelist patches NetworkFilter.is_user_ignored / is_user_ip_ignored to
    # return False for those names, so their messages flow through to the other
    # feeds too.
    # ------------------------------------------------------------------ #

    def public_room_message_notification(self, room, user, line):
        if not user or not line:
            return

        is_ignored = False

        if user != "server":
            if self.core.network_filter.is_user_ignored(user):
                is_ignored = True
            elif self.core.network_filter.is_user_ip_ignored(user):
                is_ignored = True

        # Keywords: collect keyword hits from *everyone*, bypassing the user's
        # ignore/ban preferences. Ignored users' room messages still arrive here
        # via the #Public (global-room) feed, which skips Nicotine+'s ignore
        # filter.
        self._kw_check_keywords(user, room or "", line)

        if is_ignored:
            return

        # Played: catch /me (now-playing) actions, rendered as "* <user> <text>"
        prefix = f"* {user} "
        if line.startswith(prefix):
            self._listenings_add_entry(user, line[len(prefix):].strip(), context=room)

        # Shitlist
        self._shitlist_check_keywords(user, line)

    def incoming_private_chat_notification(self, user, line):
        self._kw_check_keywords(user, "", line)
        self._shitlist_check_keywords(user, line)

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
            entry = {
                "ts": float(item["ts"]),
                "user": str(item["user"]),
                "text": str(item["text"]),
            }

            if item.get("self"):
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

    def _kw_add_entry(self, user, room, text, keywords):
        feed = self._feeds["keywordwatch"]
        feed["entries"].insert(0, {
            "ts": time.time(),
            "user": user,
            "room": room,
            "text": text,
            "keywords": keywords,
        })
        self._kw_prune()
        self._kw_save()
        self._kw_render()

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
            feed["entries"].append({
                "ts": float(item["ts"]),
                "user": str(item["user"]),
                "room": str(item.get("room", "")),
                "text": str(item["text"]),
                "keywords": [str(k) for k in item.get("keywords", [])],
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
        source = entry.get("room") or "private"
        keywords = entry.get("keywords") or []
        suffix = "  [kw: %s]" % ", ".join(keywords) if keywords else ""
        return f"{stamp} [{source}] <{entry['user']}> {entry['text']}{suffix}"

    # ------------------------------------------------------------------ #
    # Shitlist logic
    # ------------------------------------------------------------------ #

    def _shitlist_check_keywords(self, user, line):
        if not self.settings.get("shitlist_enabled", True):
            return

        if not user or user == self.core.users.login_username:
            return

        lowered = line.lower()

        for raw_keyword in self.settings.get("shitlist_keywords", []):
            keyword = self._normalize_keyword(raw_keyword)

            if not keyword:
                continue

            if keyword.lower() in lowered:
                self._shitlist_ban(user, keyword)
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

    def _shitlist_sync_show_messages_set(self):
        self._shitlist_show_messages_set = {
            self._shitlist_normalize_username(username)
            for username in self.settings.get("shitlist_show_messages", [])
        }
        self._shitlist_show_messages_set.discard("")

    def _shitlist_patch_ignore_filter(self):
        if self._shitlist_ignore_filter_patched:
            return

        network_filter = self.core.network_filter
        network_filter_class = type(network_filter)
        plugin = self

        original_user = network_filter_class.is_user_ignored
        original_ip = network_filter_class.is_user_ip_ignored

        def _is_whitelisted(username):
            return plugin._shitlist_is_whitelisted(username)

        def patched_is_user_ignored(nf_self, username):
            if _is_whitelisted(username):
                return False

            return original_user(nf_self, username)

        def patched_is_user_ip_ignored(nf_self, username=None, ip_address=None):
            if _is_whitelisted(username):
                return False

            return original_ip(nf_self, username, ip_address)

        network_filter_class.is_user_ignored = patched_is_user_ignored
        network_filter_class.is_user_ip_ignored = patched_is_user_ip_ignored

        self._shitlist_original_is_user_ignored = original_user
        self._shitlist_original_is_user_ip_ignored = original_ip
        self._shitlist_ignore_filter_patched = True

    def _shitlist_restore_ignore_filter(self):
        if not self._shitlist_ignore_filter_patched:
            return

        network_filter_class = type(self.core.network_filter)

        if self._shitlist_original_is_user_ignored is not None:
            network_filter_class.is_user_ignored = self._shitlist_original_is_user_ignored

        if self._shitlist_original_is_user_ip_ignored is not None:
            network_filter_class.is_user_ip_ignored = self._shitlist_original_is_user_ip_ignored

        self._shitlist_original_is_user_ignored = None
        self._shitlist_original_is_user_ip_ignored = None
        self._shitlist_ignore_filter_patched = False

    def _shitlist_is_actually_ignored(self, username):
        if self._shitlist_original_is_user_ignored is not None:
            return self._shitlist_original_is_user_ignored(self.core.network_filter, username)

        return self.core.network_filter.is_user_ignored(username)

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

    def _shitlist_ban(self, user, keyword):
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

            self._shitlist_log_ban(user, ip, keyword)

    def _shitlist_log_ban(self, user, ip, keyword):
        entry = {
            "ts": int(time.time()),
            "user": user,
            "ip": ip or "?",
            "keyword": keyword or "",
        }

        try:
            os.makedirs(self._shitlist_log_dir(), exist_ok=True)

            with open(self._shitlist_daily_path(), "a", encoding="utf-8") as file_handle:
                file_handle.write(json.dumps(entry) + "\n")
        except Exception as error:
            self.log("Failed to write the Shitlist ban log: %s", (error,))

    def _shitlist_log_path(self):
        return os.path.join(self._shitlist_log_dir(), SHITLIST_LOG_FILENAME)

    def _shitlist_daily_path(self):
        return os.path.join(
            self._shitlist_log_dir(),
            self._daily_filename(self._shitlist_log_dir(), "shitlist_log_start", self._date_key()),
        )

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

        except OSError as error:
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
        l_retention = self.settings.get("listenings_retention", "1 day")
        l_blocked = len(self.settings.get("listenings_blocked_users", []))

        kw_keywords = self.settings.get("kw_keywords", [])
        kw_case = bool(self.settings.get("kw_case_sensitive", False))
        kw_retention = self.settings.get("kw_retention", "1 day")
        kw_blocked = len(self.settings.get("kw_blocked_users", []))

        s_enabled = bool(self.settings.get("shitlist_enabled", True))
        s_keywords = self.settings.get("shitlist_keywords", [])
        s_show = len(self.settings.get("shitlist_show_messages", []))
        s_users = len(self.settings.get("shitlist_users", []))

        self.output("Chat watcher v1 status:")
        self.output("  Played:        retention=%s, hidden users=%d" % (l_retention, l_blocked))
        self.output("  Keywords:      %d keyword(s), case-sensitive=%s, retention=%s, hidden users=%d"
                    % (len(kw_keywords), "yes" if kw_case else "no", kw_retention, kw_blocked))
        self.output("  Shitlist:      banning=%s, %d keyword(s), %d message exception(s), %d banned+ignored"
                    % ("on" if s_enabled else "off", len(s_keywords), s_show, s_users))
        self.output("")
        self.output("Use /cw to open the settings dialog; /played, /kw and /shitlist for the three features.")
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
            else:
                page = self._build_keywordwatch_page(feed)

            page.id = feed["tab_id"]  # Nicotine+ expects every main tab page to have an id

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
            else:
                self._kw_render()

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

        for entry in feed["entries"]:
            row = self._listenings_build_entry_row(entry)
            self._listbox_append(listbox, row)
            feed["rows"].append(row)

        self._update_status(feed)

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

    def _listenings_on_entry_right_pressed_gtk4(self, gesture, _n_press, _x, _y, entry):
        self._listenings_show_menu_gtk4(gesture.get_widget(), entry)

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

    def _listenings_show_menu_gtk4(self, button, entry):
        from gi.repository import Gtk

        popover = Gtk.Popover()
        popover.set_parent(button)
        popover.set_has_arrow(False)

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

        # Toolbar row: clear + open folder buttons, and the entry counter
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        clear_button = self._make_toolbar_button("edit-clear", "Clear Log")
        clear_button.set_tooltip_text("Delete all entries from the Keywords log")
        clear_button.connect("clicked", self._on_kw_clear_clicked)

        open_folder_button = self._make_toolbar_button("folder-open", "Open Log Folder")
        open_folder_button.set_tooltip_text("Open the folder where the Keywords log is stored")
        open_folder_button.connect("clicked", self._open_kw_logs_clicked)

        status_label = Gtk.Label()
        status_label.set_halign(Gtk.Align.END)
        status_label.set_hexpand(True)
        feed["status_label"] = status_label

        self._box_add(toolbar, clear_button)
        self._box_add(toolbar, open_folder_button)

        if self._is_gtk4():
            toolbar.append(status_label)
        else:
            toolbar.pack_start(status_label, True, True, 0)

        self._box_add(box, toolbar)

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

    def _kw_render(self):
        feed = self._feeds["keywordwatch"]

        if not feed["built"]:
            return

        entries_box = feed["list_widget"]
        self._box_clear(entries_box)

        for entry in feed["entries"]:  # newest first
            button = self._kw_make_entry_button(entry)

            if self._is_gtk4():
                entries_box.append(button)
            else:
                entries_box.pack_start(button, True, True, 0)

        self._show_all(entries_box)
        self._update_status(feed)

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
            self._kw_show_entry_menu(widget, entry)

    def _kw_show_entry_menu(self, widget, entry):
        from gi.repository import Gtk

        popover = Gtk.Popover()

        if self._is_gtk4():
            popover.set_parent(widget)
        else:
            popover.set_relative_to(widget)

        try:
            popover.set_autohide(True)
        except Exception:
            pass

        copy_button = Gtk.Button.new_with_label("Copy")
        copy_button.set_tooltip_text("Copy this entry to the clipboard")

        remove_button = Gtk.Button.new_with_label("Remove")
        remove_button.set_tooltip_text("Remove this entry")

        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        if self._is_gtk4():
            copy_button.set_has_frame(False)
            remove_button.set_has_frame(False)
            menu_box.append(copy_button)
            menu_box.append(remove_button)
            popover.set_child(menu_box)
        else:
            copy_button.set_relief(Gtk.ReliefStyle.NONE)
            remove_button.set_relief(Gtk.ReliefStyle.NONE)
            menu_box.pack_start(copy_button, False, False, 0)
            menu_box.pack_start(remove_button, False, False, 0)
            popover.add(menu_box)
            popover.show_all()

        copy_button.connect("clicked", self._kw_on_copy_entry_clicked, entry, popover)
        remove_button.connect("clicked", self._kw_on_remove_entry_clicked, entry, popover)
        popover.popup()

    def _kw_on_copy_entry_clicked(self, _button, entry, popover):
        popover.popdown()
        self._copy_to_clipboard(self._kw_format_entry(entry))

    def _kw_on_remove_entry_clicked(self, _button, entry, popover):
        popover.popdown()
        self._kw_remove_entry(entry)

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
