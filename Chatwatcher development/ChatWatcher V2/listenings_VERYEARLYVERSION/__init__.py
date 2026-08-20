# SPDX-License-Identifier: GPL-3.0-or-later
"""Listenings — collect other users' /nowplaying output into a tab.

Nicotine+ renders a "/me" action as  ``* <user> <text>``  in chat, which is
exactly the shape most clients (and custom ``npformat`` strings such as
``/me is having an eargasm to: $n``) use for /nowplaying announcements.

This plugin hooks ``incoming_public_chat_event`` (which fires *before* the
``/me `` prefix is stripped) to detect those action messages, logs them to a
file, and shows them in a "Listenings" tab in the main window.
"""

import json
import os
import time

from pynicotine.pluginsystem import BasePlugin


TAB_NAME = "Listenings"
LOG_FILENAME = "listenings.log"

RETENTION_SECONDS = {
    "20 min": 20 * 60,
    "1 hr": 60 * 60,
    "12 hr": 12 * 60 * 60,
    "1 day": 24 * 60 * 60,
    "3 days": 3 * 24 * 60 * 60,
    "7 days": 7 * 24 * 60 * 60,
}


class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # --- user-facing settings (shown in Settings → Plugins) ---
        self.settings = {
            "clear_log": False,
            "blocked_users": [],
            "retention": "1 day",
        }

        self.metasettings = {
            "clear_log": {
                "description": "Clear the Listenings log now",
                "type": "bool",
            },
            "blocked_users": {
                "description": "Users to hide (one per entry):",
                "type": "list string",
            },
            "retention": {
                "description": "Keep entries for:",
                "type": "dropdown",
                "options": tuple(RETENTION_SECONDS.keys()),
            },
        }

        # --- runtime state ---
        self.entries = []          # newest first: [{"ts", "user", "text"}, ...]
        self._notebook = None      # main Gtk.Notebook we attach to
        self._page = None          # our tab content widget
        self._buffer = None        # Gtk.TextBuffer backing the log view
        self._status_label = None  # "N entries" counter
        self._built = False
        self._build_attempts = 0
        self._build_id = None      # GLib source id for the tab-build retry
        self._poll_id = None       # GLib source id for the "clear log" setting poll
        self._prune_id = None      # GLib source id for periodic retention pruning

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def init(self):
        self._load()
        self._prune()
        self._start_timers()
        self._schedule_build()

    def disable(self):
        self._stop_timers()
        self._remove_tab()

    def loaded_notification(self):
        self.log("Logging /nowplaying (/me) messages into the '%s' tab.", TAB_NAME)

    # ------------------------------------------------------------------ #
    # Chat hook
    # ------------------------------------------------------------------ #

    def incoming_public_chat_event(self, room, user, line):
        """Fired before Nicotine+ strips the '/me ' prefix.

        A now-playing announcement sent as an action shows up here with
        ``line`` still starting with ``/me ``. We log it and pass through
        unchanged (returning None means "don't modify, keep processing").
        """

        if line.startswith("/me "):
            self._add_entry(user, line[4:].strip())

        return None

    def _add_entry(self, user, text):
        if not user or not text:
            return

        login = self.core.users.login_username
        if login and user.lower() == login.lower():
            return  # only collect *other* users' output

        blocked = {u.lower() for u in self.settings.get("blocked_users", [])}
        if user.lower() in blocked:
            return

        self.entries.insert(0, {"ts": time.time(), "user": user, "text": text})
        self._prune()
        self._save()
        self._render()

    # ------------------------------------------------------------------ #
    # Log persistence
    # ------------------------------------------------------------------ #

    def _log_path(self):
        return os.path.join(self.path or "", LOG_FILENAME)

    def _load(self):
        """Load entries from disk (oldest-first on disk → newest-first in memory)."""

        self.entries = []

        try:
            with open(self._log_path(), "r", encoding="utf-8") as file_handle:
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

                    if not all(key in item for key in ("ts", "user", "text")):
                        continue

                    self.entries.append({
                        "ts": float(item["ts"]),
                        "user": str(item["user"]),
                        "text": str(item["text"]),
                    })
        except OSError:
            pass  # no log file yet

        self.entries.reverse()

    def _save(self):
        try:
            with open(self._log_path(), "w", encoding="utf-8") as file_handle:
                for item in reversed(self.entries):  # oldest first on disk
                    file_handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        except OSError as error:
            self.log("Could not write log file: %s", error)

    def _prune(self):
        """Drop entries older than the configured retention. Returns True if changed."""

        retention = RETENTION_SECONDS.get(self.settings.get("retention"))

        if not retention:
            return False

        cutoff = time.time() - retention
        new_entries = [entry for entry in self.entries if entry["ts"] >= cutoff]

        if len(new_entries) == len(self.entries):
            return False

        self.entries = new_entries
        return True

    def _clear(self):
        self.entries = []
        self._save()
        self._render()
        self.log("Listenings log cleared.")

    # ------------------------------------------------------------------ #
    # Timers
    # ------------------------------------------------------------------ #

    def _start_timers(self):
        from gi.repository import GLib

        if self._poll_id is None:
            self._poll_id = GLib.timeout_add(1000, self._poll_clear_setting)

        if self._prune_id is None:
            self._prune_id = GLib.timeout_add(60000, self._prune_tick)

    def _stop_timers(self):
        from gi.repository import GLib

        for attr in ("_build_id", "_poll_id", "_prune_id"):
            source_id = getattr(self, attr)

            if source_id is not None:
                GLib.source_remove(source_id)
                setattr(self, attr, None)

    def _poll_clear_setting(self):
        """The 'clear log' setting is a checkbox; poll it and act on a toggle."""

        if self.settings.get("clear_log"):
            self.settings["clear_log"] = False
            self._clear()

        return True  # keep polling

    def _prune_tick(self):
        if self._prune():
            self._save()
            self._render()

        return True  # keep polling

    # ------------------------------------------------------------------ #
    # GUI: main-window tab
    # ------------------------------------------------------------------ #

    def _schedule_build(self):
        from gi.repository import GLib

        self._build_attempts = 0

        if self._build_id is None:
            # Poll instead of idle_add: the window may not be mapped yet when
            # Nicotine+ starts hidden (tray mode), and idle_add would spin.
            self._build_id = GLib.timeout_add(500, self._build_tab)

    def _build_tab(self):
        if self._built:
            self._build_id = None
            return False

        self._build_attempts += 1

        if self._build_attempts > 7200:  # ~1 hour at 500 ms
            self.log("Could not find the main window; '%s' tab was not added.", TAB_NAME)
            self._build_id = None
            return False

        try:
            window = self._get_window_widget()
            notebook = self._find_main_notebook(window)

            if notebook is None:
                return True  # window not ready yet, retry on the next idle cycle

            page = self._build_page()
            label = self._build_tab_label()

            self._finalize_widgets(page, label)
            notebook.append_page(page, label)

            try:
                notebook.set_tab_reorderable(page, True)
            except Exception:
                pass

            self._notebook = notebook
            self._page = page
            self._built = True
            self._render()
            self._build_id = None
            return False

        except Exception as error:
            self.log("Failed to create '%s' tab: %s", (TAB_NAME, error))
            self._build_id = None
            return False

    def _get_window_widget(self):
        from gi.repository import Gio

        app = Gio.Application.get_default()

        if app is None:
            return None

        windows = app.get_windows()
        return windows[0] if windows else None

    def _find_main_notebook(self, root):
        """Breadth-first search for the first (top-level) Gtk.Notebook.

        Secondary notebooks (chat rooms, private chat, …) live *inside* the
        main notebook's pages, so the shallowest notebook is the main one.
        """

        from collections import deque

        from gi.repository import Gtk

        if root is None:
            return None

        queue = deque([root])

        while queue:
            widget = queue.popleft()

            if isinstance(widget, Gtk.Notebook):
                return widget

            queue.extend(self._iter_children(widget))

        return None

    @staticmethod
    def _iter_children(widget):
        # GTK 4
        get_first_child = getattr(widget, "get_first_child", None)

        if callable(get_first_child):
            child = get_first_child()

            while child is not None:
                yield child
                child = child.get_next_sibling()

            return

        # GTK 3
        get_children = getattr(widget, "get_children", None)

        if callable(get_children):
            for child in get_children():
                yield child

    def _build_page(self):
        from gi.repository import Gtk

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        # Top row: clear button + entry counter
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        clear_button = Gtk.Button.new_with_label("Clear Log")
        clear_button.set_tooltip_text("Delete all entries from the Listenings log")
        clear_button.connect("clicked", self._on_clear_clicked)

        self._status_label = Gtk.Label()
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_hexpand(True)

        self._box_add(toolbar, clear_button)
        self._box_add(toolbar, self._status_label)
        self._box_add(box, toolbar)

        # Scrollable, read-only log view
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_cursor_visible(False)
        textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._set_monospace(textview)
        self._buffer = textview.get_buffer()

        self._set_scrolled_child(scrolled, textview)
        self._box_add(box, scrolled)

        return box

    @staticmethod
    def _build_tab_label():
        from gi.repository import Gtk

        return Gtk.Label(label=TAB_NAME)

    def _on_clear_clicked(self, *_args):
        self._clear()

    def _render(self):
        if not self._built:
            return

        lines = []

        for item in self.entries:  # newest first
            stamp = time.strftime("%I:%M:%S %p", time.localtime(item["ts"]))
            lines.append(f"{stamp} * {item['user']} {item['text']}")

        text = "\n".join(lines)
        if lines:
            text += "\n"

        if self._buffer is not None:
            self._buffer.set_text(text)

        self._update_status()

    def _update_status(self):
        if self._status_label is None:
            return

        count = len(self.entries)
        suffix = "entry" if count == 1 else "entries"
        self._status_label.set_text(f"{count} {suffix}")

    def _remove_tab(self):
        if self._notebook is not None and self._page is not None:
            try:
                page_num = self._notebook.page_num(self._page)

                if page_num != -1:
                    self._notebook.remove_page(page_num)
            except Exception:
                pass

        self._notebook = None
        self._page = None
        self._buffer = None
        self._status_label = None
        self._built = False

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
    def _set_scrolled_child(cls, scrolled, child):
        if cls._is_gtk4():
            scrolled.set_child(child)
        else:
            scrolled.add(child)

    @classmethod
    def _set_monospace(cls, textview):
        if cls._is_gtk4():
            textview.set_monospace(True)
        else:
            from gi.repository import Pango

            textview.override_font(Pango.FontDescription("monospace"))

    @classmethod
    def _finalize_widgets(cls, page, label):
        """Show widgets explicitly on GTK 3 (GTK 4 widgets are visible by default)."""

        if cls._is_gtk4():
            return

        label.show()
        page.show_all()
