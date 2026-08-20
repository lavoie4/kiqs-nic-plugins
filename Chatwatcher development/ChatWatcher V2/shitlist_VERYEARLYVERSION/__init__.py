# SPDX-License-Identifier: GPL-3.0-or-later

"""Shitlist — ban users who say keywords, plus a temporary "Ignore for..." menu.

Features
--------
1. Ban users who say any keyword on the Shitlist. Matching is case-insensitive
   substring matching, exactly like Nicotine+'s built-in chat censor feature.
2. A user-friendly keyword editor (the standard plugin settings dialog), opened
   from Preferences -> Plugins -> Shitlist -> Settings, or via the /shitlist
   command.
3. A temporary "Ignore for..." submenu (20 min / 1 hr / 12 hr / 1 day / 3 days /
   7 days) added to the user right-click context menu.

See README.md for full usage instructions.
"""

from pynicotine.events import events
from pynicotine.pluginsystem import BasePlugin


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

        self.settings = {
            "enabled": True,
            "keywords": [],
        }
        self.metasettings = {
            "enabled": {
                "description": "Enable banning users who say keywords",
                "group": "Shitlist",
                "type": "bool",
            },
            "keywords": {
                "description": (
                    "Ban users who say these words. One word per line. "
                    "Wrap multi-word phrases in double quotes, e.g. \"no thanks\"."
                ),
                "group": "Shitlist",
                "type": "list string",
            },
        }

        self.commands = {
            "shitlist": {
                "callback": self.shitlist_command,
                "description": "Manage Shitlist keywords and open the settings editor",
                "parameters": ["[add|remove|list]", "[keyword]"],
            }
        }

        self._ignore_timers = {}
        self._menu_patched = False
        self._original_setup_user_menu = None
        self._enabled = True

    # ------------------------------------------------------------------ lifecycle

    def loaded_notification(self):
        self._patch_user_menu()

    def disable(self):
        self._enabled = False
        self._restore_user_menu()
        self._ignore_timers.clear()

    # ------------------------------------------------------------------ keyword banning

    def incoming_public_chat_notification(self, room, user, line):
        self._check_keywords(user, line)

    def incoming_private_chat_notification(self, user, line):
        self._check_keywords(user, line)

    def _check_keywords(self, user, line):

        if not self.settings.get("enabled", True):
            return

        if not user or user == self.core.users.login_username:
            return

        lowered = line.lower()

        for raw_keyword in self.settings.get("keywords", []):
            keyword = self._normalize_keyword(raw_keyword)

            if not keyword:
                continue

            if keyword.lower() in lowered:
                self._ban(user, keyword)
                break

    @staticmethod
    def _normalize_keyword(keyword):
        """Strip surrounding quotes and whitespace from a keyword."""

        keyword = keyword.strip()

        if len(keyword) >= 2 and keyword[0] == keyword[-1] and keyword[0] in ('"', "'"):
            keyword = keyword[1:-1]

        return keyword.strip()

    def _ban(self, user, keyword):

        banned = self.core.network_filter.is_user_banned(user)
        ignored = self.core.network_filter.is_user_ignored(user)

        if not banned:
            self.core.network_filter.ban_user(user)

        if not ignored:
            self.core.network_filter.ignore_user(user)

        if not banned or not ignored:
            self.log("Banned and ignored user '%s' for saying keyword '%s'", (user, keyword))

    # ------------------------------------------------------------------ temporary ignore

    def ignore_for(self, username, seconds):

        if not self._enabled or not username:
            return

        already_ignored = self.core.network_filter.is_user_ignored(username)
        self.core.network_filter.ignore_user(username)

        previous_timer = self._ignore_timers.pop(username, None)

        if previous_timer is not None:
            events.cancel_scheduled(previous_timer)

        if already_ignored:
            # Respect an existing (permanent) ignore: don't auto-remove it.
            self.log("User '%s' was already ignored; keeping the ignore without auto-expiry", (username,))
            return

        event_id = events.schedule(seconds, self._unignore_user, (username,))
        self._ignore_timers[username] = event_id
        self.log("Ignoring user '%s' for %s seconds", (username, seconds))

    def _unignore_user(self, username):

        self._ignore_timers.pop(username, None)

        if self.core.network_filter.is_user_ignored(username):
            self.core.network_filter.unignore_user(username)
            self.log("Temporary ignore of user '%s' expired", (username,))

    # ------------------------------------------------------------------ command

    def shitlist_command(self, args, user=None, room=None):

        args = args.strip()

        if not args:
            return self._open_settings()

        action, _separator, rest = args.partition(" ")
        action = action.lower()
        keyword = rest.strip()

        if action == "add":
            return self._add_keyword(keyword)

        if action == "remove":
            return self._remove_keyword(keyword)

        if action == "list":
            return self._list_keywords()

        self.output("Usage: /shitlist [add <word> | remove <word> | list]")
        return False

    def _add_keyword(self, keyword):

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

        for existing in self.settings["keywords"]:
            if self._normalize_keyword(existing) == keyword:
                self.output("Keyword '%s' is already on the list." % keyword)
                return False

        self.settings["keywords"].append(keyword)
        self.config.write_configuration()
        self.output("Added keyword '%s'. %s keyword(s) total." % (keyword, len(self.settings["keywords"])))
        return True

    def _remove_keyword(self, keyword):

        keyword = keyword.strip()

        if not keyword:
            self.output("Usage: /shitlist remove <word>")
            return False

        keyword = self._normalize_keyword(keyword)

        for existing in list(self.settings["keywords"]):
            if self._normalize_keyword(existing) == keyword:
                self.settings["keywords"].remove(existing)
                self.config.write_configuration()
                self.output("Removed keyword '%s'." % keyword)
                return True

        self.output("Keyword '%s' is not on the list." % keyword)
        return False

    def _list_keywords(self):

        keywords = self.settings.get("keywords", [])

        if not keywords:
            self.output("No keywords on the Shitlist.")
            return True

        self.output("Shitlist keywords (%s):" % len(keywords))

        for keyword in keywords:
            self.output("  - %s" % keyword)

        return True

    # ------------------------------------------------------------------ settings dialog

    def _open_settings(self):

        application = self._get_application()

        if application is None:
            self._list_keywords()
            self.output("(Open Preferences -> Plugins -> Shitlist -> Settings for the keyword editor.)")
            return False

        try:
            if application.preferences is None:
                from pynicotine.gtkgui.dialogs.preferences import Preferences
                application.preferences = Preferences(application)

            dialog = getattr(application, "_shitlist_settings_dialog", None)

            if dialog is None:
                from pynicotine.gtkgui.dialogs.pluginsettings import PluginSettings
                dialog = PluginSettings(application)
                application._shitlist_settings_dialog = dialog

            dialog.load_options(self.internal_name, self.metasettings)
            dialog.present()
            return True

        except Exception as error:
            self.log("Failed to open settings dialog: %s", (error,))
            self._list_keywords()
            self.output("Failed to open the settings window (%s)." % error)
            return False

    @staticmethod
    def _get_application():
        """Locate the singleton GUI Application wrapper.

        Nicotine+ does not expose the Application object to plugins, so we find
        the single live instance via the garbage collector. Returns None in
        headless mode (no GUI) or if the window cannot be reached.
        """

        try:
            import gc
            from pynicotine.gtkgui.application import Application
        except Exception:
            return None

        for obj in gc.get_objects():
            if isinstance(obj, Application):
                return obj

        return None

    # ------------------------------------------------------------------ user menu patch

    def _patch_user_menu(self):

        if self._menu_patched:
            return

        try:
            from pynicotine.gtkgui.widgets.popupmenu import PopupMenu, UserPopupMenu
        except Exception as error:
            self.log("Could not patch the user menu (\"Ignore for...\" will be unavailable): %s", (error,))
            return

        plugin = self
        original = UserPopupMenu.setup_user_menu

        def ignore_for_callback(menu_self, action, parameter, seconds):
            plugin.ignore_for(menu_self.username, seconds)

        def patched_setup_user_menu(menu_self, username):
            original(menu_self, username)

            submenu = PopupMenu(menu_self.application, connect_events=False)

            for label, seconds in plugin.IGNORE_DURATIONS:
                submenu.add_items(("#" + label, menu_self._shitlist_ignore_for, seconds))

            menu_self.add_items((">" + "Ignore for...", submenu))

        UserPopupMenu._shitlist_ignore_for = ignore_for_callback
        UserPopupMenu.setup_user_menu = patched_setup_user_menu

        self._menu_patched = True
        self._original_setup_user_menu = original

    def _restore_user_menu(self):

        if not self._menu_patched:
            return

        try:
            from pynicotine.gtkgui.widgets.popupmenu import UserPopupMenu
        except Exception:
            return

        if self._original_setup_user_menu is not None:
            UserPopupMenu.setup_user_menu = self._original_setup_user_menu

        if hasattr(UserPopupMenu, "_shitlist_ignore_for"):
            del UserPopupMenu._shitlist_ignore_for

        self._menu_patched = False
        self._original_setup_user_menu = None
