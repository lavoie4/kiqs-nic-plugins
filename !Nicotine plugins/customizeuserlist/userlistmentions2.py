######################################################################

USERLIST COMMANDS DICTIONARY:

        self.commands = {
            "userlist": {
                "callback": self.userlist_command,
                "description": "Open the Customize User List settings window, or quickly hide/show the buddy-list sidebar",
                "parameters": ["[settings|hide|show]"],
                "group": "Customize User List",
            },
            "cul": {
                "callback": self.userlist_command,
                "description": "Short alias for /userlist",
                "parameters": ["[settings|hide|show]"],
                "group": "Customize User List",
            },
        }

######################################################################

USERLIST COMMAND HANDLER:

    def userlist_command(self, args, **_unused):

        action = (args or "").strip().lower()

        if action in {"", "settings", "gui", "options", "open"}:
            self._open_settings()
            return

        if action in {"hide", "on", "true"}:
            self.settings["hidden"] = True
            self._applied_width = set()
            self._apply()
            return "Buddy-list sidebar hidden."

        if action in {"show", "off", "false"}:
            self.settings["hidden"] = False
            self._applied_width = set()
            self._apply()
            return "Buddy-list sidebar shown."

        return "Usage: /userlist [settings|hide|show]"

######################################################################

USERLIST SETTINGS WINDOW TITLE AND INITIALIZATION:

        window = Gtk.Window(title="Customize User List")
        window.set_default_size(460, 260)
        window.set_resizable(True)

######################################################################

USERLIST SETTINGS: ENABLED CHECKBOX:

        enabled = Gtk.CheckButton()
        enabled.set_label("Enable buddy/user-list pane customization")
        enabled.set_active(bool(self.settings.get("enabled", True)))
        enabled.connect("toggled", self._on_enabled_toggled)
        self._settings_widgets["enabled"] = enabled
        self._box_append(content, enabled)

######################################################################

USERLIST SETTINGS: WIDTH LABEL:

        width_label = Gtk.Label(label="Buddy list width (px)", xalign=0, hexpand=True)

######################################################################

USERLIST SETTINGS: HIDDEN CHECKBOX:

        hidden = Gtk.CheckButton()
        hidden.set_label("Hide the buddy-list sidebar")
        hidden.set_active(bool(self.settings.get("hidden", DEFAULT_HIDDEN)))
        hidden.connect("toggled", self._on_hidden_toggled)
        self._settings_widgets["hidden"] = hidden
        self._box_append(content, hidden)

######################################################################

USERLIST SETTINGS: HINT TEXT:

        hint = Gtk.Label(xalign=0)
        hint.set_markup(
            "<small>Resizing is native — drag the divider between the chat area "
            "and the buddy list. This plugin only sets its width and hides/shows "
            "it, so the built-in drag handle keeps working.</small>"
        )
        hint.set_wrap(True)
        self._box_append(content, hint)

######################################################################
