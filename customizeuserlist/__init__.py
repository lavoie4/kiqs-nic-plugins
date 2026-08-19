"""Nicotine+ Customize User List plugin.

Customizes the two side lists in Nicotine+:

    * Buddy list  ("sliding buddy frame") — resized by moving Nicotine+'s own
      horizontal Gtk.Paned divider (ui/mainwindow.ui: "horizontal_paned" and
      "chatrooms_paned"); no widgets are created, wrapped or reparented.
    * Room user list (the per-room member list, "users_container") — resized via
      the plain `set_width_request()` property and hidden via `set_visible()`.
      This list has no native paned, so a property change (not reparenting) is
      the correct, clean way to control it.

Both lists are controlled independently. Works on GTK 3 and GTK 4.
"""

from pynicotine.pluginsystem import BasePlugin


POLL_INTERVAL_MS = 1000

DEFAULT_BUDDY_WIDTH = 200
DEFAULT_USERLIST_WIDTH = 180

MIN_WIDTH = 50
MAX_WIDTH = 1200

# End-child container ids of Nicotine+'s two native buddy-list panes (loaded
# from ui/mainwindow.ui). Used to tell the buddy-list containers apart from the
# per-room member list and from any third-party panes (e.g. the synthetic
# horizontal paned that theme_customizer builds for its "Drag-resizable user
# list" feature).
BUDDY_LIST_END_IDS = {"buddy_list_container", "chatrooms_buddy_list_container"}

# Gtk.Builder id of the per-room member list (ui/chatrooms.ui).
USERLIST_CONTAINER_ID = "users_container"


class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.settings = {
            "enabled": True,
            "buddy_width": DEFAULT_BUDDY_WIDTH,
            "buddy_hidden": False,
            "userlist_width": DEFAULT_USERLIST_WIDTH,
            "userlist_hidden": False,
        }

        self.metasettings = {
            "enabled": {
                "description": "Enable user-list customization",
                "type": "bool",
            },
            "buddy_width": {
                "description": "Buddy list width in pixels (moves the native divider)",
                "type": "integer",
                "minimum": MIN_WIDTH,
                "maximum": MAX_WIDTH,
            },
            "buddy_hidden": {
                "description": "Hide the buddy-list sidebar",
                "type": "bool",
            },
            "userlist_width": {
                "description": "Room user list width in pixels",
                "type": "integer",
                "minimum": MIN_WIDTH,
                "maximum": MAX_WIDTH,
            },
            "userlist_hidden": {
                "description": "Hide the room user list (member list)",
                "type": "bool",
            },
        }

        self.commands = {
            "userlist": {
                "callback": self.userlist_command,
                "description": "Open the user-list settings window, or quickly hide/show the buddy list or room user list",
                "parameters": ["[settings|hide-buddy|show-buddy|hide-users|show-users]"],
                "group": "Customize User List",
            },
            "cul": {
                "callback": self.userlist_command,
                "description": "Short alias for /userlist",
                "parameters": ["[settings|hide-buddy|show-buddy|hide-users|show-users]"],
                "group": "Customize User List",
            },
        }

        self._gtk = None              # cached {"Gdk","GLib","Gtk"} or False
        self._poll_id = None          # GLib timeout source id
        self._applied_width = set()   # buddy-pane end ids already sized (don't fight drag)
        self._applying = False        # re-entrancy guard
        self._settings_window = None
        self._settings_widgets = {}

    # --- lifecycle -----------------------------------------------------------

    def init(self):

        self._migrate_settings()
        self._apply()

        gtk = self._get_gtk()

        if gtk:
            self._poll_id = gtk["GLib"].timeout_add(POLL_INTERVAL_MS, self._poll)

    def disable(self):

        self._close_settings_window()

        if self._poll_id is not None:
            gtk = self._get_gtk()

            if gtk:
                gtk["GLib"].source_remove(self._poll_id)

            self._poll_id = None

        self._restore()
        self._applied_width = set()

    def _migrate_settings(self):
        """v1.0 used "width"/"hidden" for the buddy list; renamed for clarity."""

        if "width" in self.settings:
            self.settings["buddy_width"] = self.settings.pop("width")

        if "hidden" in self.settings:
            self.settings["buddy_hidden"] = self.settings.pop("hidden")

    # --- command -------------------------------------------------------------

    def userlist_command(self, args, **_unused):

        action = (args or "").strip().lower()

        if action in {"", "settings", "gui", "options", "open"}:
            self._open_settings()
            return

        if action in {"hide-buddy", "hide-buddies"}:
            self.settings["buddy_hidden"] = True
            self._applied_width = set()
            self._apply()
            return "Buddy-list sidebar hidden."

        if action in {"show-buddy", "show-buddies"}:
            self.settings["buddy_hidden"] = False
            self._applied_width = set()
            self._apply()
            return "Buddy-list sidebar shown."

        if action in {"hide-users", "hide-userlist"}:
            self.settings["userlist_hidden"] = True
            self._apply()
            return "Room user list hidden."

        if action in {"show-users", "show-userlist"}:
            self.settings["userlist_hidden"] = False
            self._restore_userlist_visibility()
            self._apply()
            return "Room user list shown."

        # Backwards-compatible shorthand: hide/show the buddy list.
        if action in {"hide", "on", "true"}:
            self.settings["buddy_hidden"] = True
            self._applied_width = set()
            self._apply()
            return "Buddy-list sidebar hidden."

        if action in {"show", "off", "false"}:
            self.settings["buddy_hidden"] = False
            self._applied_width = set()
            self._apply()
            return "Buddy-list sidebar shown."

        return "Usage: /userlist [settings|hide-buddy|show-buddy|hide-users|show-users]"

    # --- GTK helpers ---------------------------------------------------------

    def _get_gtk(self):

        if self._gtk is not None:
            return self._gtk

        try:
            import gi  # noqa: F401  pylint: disable=import-error
            from gi.repository import Gdk
            from gi.repository import GLib
            from gi.repository import Gtk
        except Exception:
            self._gtk = False
            return False

        try:
            if Gdk.Display.get_default() is None:
                # Headless mode: no window to adjust.
                self._gtk = False
                return False
        except Exception:
            pass

        self._gtk = {"Gdk": Gdk, "GLib": GLib, "Gtk": Gtk}
        return self._gtk

    def _find_main_window(self, Gtk):

        try:
            toplevels = Gtk.Window.list_toplevels()
        except Exception:
            return None

        for window in toplevels:
            try:
                if isinstance(window, Gtk.ApplicationWindow):
                    return window
            except Exception:
                continue

        for window in toplevels:
            try:
                if window.get_visible():
                    return window
            except Exception:
                continue

        return None

    @staticmethod
    def _widget_id(widget):
        """Return a widget's Gtk.Builder id (portable across GTK 3 and 4)."""

        for attr in ("get_buildable_id", "get_name"):
            fn = getattr(widget, attr, None)

            if fn is not None:
                try:
                    value = fn()

                    if value:
                        return value
                except Exception:
                    continue

        return None

    @staticmethod
    def _iter_children(widget):
        """Yield direct children of a widget (portable across GTK 3 and 4)."""

        get_first = getattr(widget, "get_first_child", None)  # GTK 4

        if get_first is not None:
            child = get_first()

            while child is not None:
                yield child
                next_fn = getattr(child, "get_next_sibling", None)
                child = next_fn() if next_fn else None

            return

        get_children = getattr(widget, "get_children", None)  # GTK 3

        if get_children is not None:
            for child in get_children():
                yield child

    def _iter_descendants(self, widget):

        yield widget

        try:
            for child in self._iter_children(widget):
                yield from self._iter_descendants(child)
        except Exception:
            pass

    def _iter_horizontal_paned(self, window, Gtk):

        for widget in self._iter_descendants(window):
            if isinstance(widget, Gtk.Paned):
                try:
                    if widget.get_orientation() == Gtk.Orientation.HORIZONTAL:
                        yield widget
                except Exception:
                    continue

    def _iter_userlist_containers(self, window):

        for widget in self._iter_descendants(window):
            if self._widget_id(widget) == USERLIST_CONTAINER_ID:
                yield widget

    @staticmethod
    def _end_child(paned):

        get_end = getattr(paned, "get_end_child", None)  # GTK 4

        if get_end is not None:
            try:
                return get_end()
            except Exception:
                return None

        get_child2 = getattr(paned, "get_child2", None)  # GTK 3

        if get_child2 is not None:
            try:
                return get_child2()
            except Exception:
                return None

        return None

    def _has_visible_child(self, container):

        if container is None:
            return False

        try:
            for child in self._iter_children(container):
                try:
                    if child.get_visible():
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        return False

    # --- apply ---------------------------------------------------------------

    def _poll(self):

        self._apply()
        return True  # keep the timeout alive

    def _apply(self):

        if self._applying:
            return

        if not self.settings.get("enabled", True):
            return

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]
        window = self._find_main_window(Gtk)

        if window is None:
            return

        self._applying = True

        try:
            for paned in self._iter_horizontal_paned(window, Gtk):
                self._apply_buddy_paned(paned)

            for container in self._iter_userlist_containers(window):
                self._apply_userlist(container)
        finally:
            self._applying = False

    def _apply_buddy_paned(self, paned):

        hidden = bool(self.settings.get("buddy_hidden", False))
        width = int(self.settings.get("buddy_width", DEFAULT_BUDDY_WIDTH))

        end = self._end_child(paned)

        if end is None:
            return

        # Only touch the two native buddy-list containers. Anything else — the
        # per-room member list, or a third-party synthetic paned such as
        # theme_customizer's "drag-resizable user list" — is left alone, so the
        # two plugins can run side by side.
        tag = self._widget_id(end)

        if tag not in BUDDY_LIST_END_IDS:
            return

        if hidden:
            try:
                end.set_visible(False)
            except Exception:
                pass
            return

        # Only manage the container that actually holds the buddy list right
        # now; leave Nicotine+'s own state alone for empty containers.
        if not self._has_visible_child(end):
            return

        try:
            end.set_visible(True)
        except Exception:
            pass

        if tag in self._applied_width:
            return

        if self._set_buddy_width(paned, width):
            self._applied_width.add(tag)

    def _set_buddy_width(self, paned, width):

        try:
            total = paned.get_allocated_width()
        except Exception:
            return False

        if total <= 0:
            # Not allocated yet (e.g. Chatrooms tab never opened). Retry later.
            return False

        width = max(MIN_WIDTH, min(int(width), MAX_WIDTH, total - 1))
        position = total - width  # horizontal paned: position == start-child width

        if position < 0:
            position = 0

        try:
            paned.set_position(position)
            return True
        except Exception:
            return False

    def _apply_userlist(self, container):

        hidden = bool(self.settings.get("userlist_hidden", False))
        width = int(self.settings.get("userlist_width", DEFAULT_USERLIST_WIDTH))

        if hidden:
            try:
                container.set_visible(False)
            except Exception:
                pass
            return

        # The member list has no native paned; its width is a plain property.
        try:
            container.set_width_request(max(MIN_WIDTH, min(int(width), MAX_WIDTH)))
        except Exception:
            pass

    def _restore_userlist_visibility(self):

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]
        window = self._find_main_window(Gtk)

        if window is None:
            return

        for container in self._iter_userlist_containers(window):
            try:
                container.set_visible(True)
            except Exception:
                pass

    def _restore(self):
        """Un-hide anything the plugin had hidden on disable/unload."""

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]
        window = self._find_main_window(Gtk)

        if window is None:
            return

        for paned in self._iter_horizontal_paned(window, Gtk):
            end = self._end_child(paned)

            if end is not None and self._has_visible_child(end):
                try:
                    end.set_visible(True)
                except Exception:
                    pass

        for container in self._iter_userlist_containers(window):
            try:
                container.set_visible(True)
            except Exception:
                pass

    # --- settings window -----------------------------------------------------

    def _open_settings(self):

        gtk = self._get_gtk()

        if not gtk:
            return

        if self._settings_window is not None:
            try:
                self._settings_window.present()
            except Exception:
                pass
            return

        self._build_settings_window(gtk)

    def _close_settings_window(self):

        if self._settings_window is not None:
            try:
                self._settings_window.destroy()
            except Exception:
                pass

            self._settings_window = None
            self._settings_widgets = {}

    @staticmethod
    def _window_set_child(window, child):
        """Portable window.add / window.set_child."""

        set_child = getattr(window, "set_child", None)  # GTK 4

        if set_child is not None:
            set_child(child)
        else:
            window.add(child)  # GTK 3

    @staticmethod
    def _box_append(box, child):
        """Portable box.append / box.pack_start."""

        append = getattr(box, "append", None)  # GTK 4

        if append is not None:
            append(child)
        else:
            box.pack_start(child, False, False, 0)  # GTK 3

    def _build_settings_window(self, gtk):

        Gtk = gtk["Gtk"]

        main_window = self._find_main_window(Gtk)

        window = Gtk.Window(title="Customize User List")
        window.set_default_size(500, 360)
        window.set_resizable(True)

        if main_window is not None:
            try:
                window.set_transient_for(main_window)
            except Exception:
                pass

        self._settings_window = window
        self._settings_widgets = {}

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=10,
            margin_top=16, margin_bottom=16, margin_start=16, margin_end=16
        )
        self._window_set_child(window, content)

        enabled = Gtk.CheckButton()
        enabled.set_label("Enable user-list customization")
        enabled.set_active(bool(self.settings.get("enabled", True)))
        enabled.connect("toggled", self._on_enabled_toggled)
        self._settings_widgets["enabled"] = enabled
        self._box_append(content, enabled)

        # --- Buddy list ---
        buddy_title = Gtk.Label(xalign=0)
        buddy_title.set_markup("<b>Buddy list (sliding frame)</b>")
        self._box_append(content, buddy_title)

        buddy_width_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buddy_width_label = Gtk.Label(label="Width (px)", xalign=0, hexpand=True)
        buddy_width_spin = Gtk.SpinButton.new_with_range(MIN_WIDTH, MAX_WIDTH, 10)
        buddy_width_spin.set_value(int(self.settings.get("buddy_width", DEFAULT_BUDDY_WIDTH)))
        buddy_width_spin.connect("value-changed", self._on_buddy_width_changed)
        self._settings_widgets["buddy_width"] = buddy_width_spin
        self._box_append(buddy_width_row, buddy_width_label)
        self._box_append(buddy_width_row, buddy_width_spin)
        self._box_append(content, buddy_width_row)

        buddy_hidden = Gtk.CheckButton()
        buddy_hidden.set_label("Hide the buddy-list sidebar")
        buddy_hidden.set_active(bool(self.settings.get("buddy_hidden", False)))
        buddy_hidden.connect("toggled", self._on_buddy_hidden_toggled)
        self._settings_widgets["buddy_hidden"] = buddy_hidden
        self._box_append(content, buddy_hidden)

        # --- Room user list ---
        userlist_title = Gtk.Label(xalign=0)
        userlist_title.set_markup("<b>Room user list (member list)</b>")
        self._box_append(content, userlist_title)

        userlist_width_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        userlist_width_label = Gtk.Label(label="Width (px)", xalign=0, hexpand=True)
        userlist_width_spin = Gtk.SpinButton.new_with_range(MIN_WIDTH, MAX_WIDTH, 10)
        userlist_width_spin.set_value(int(self.settings.get("userlist_width", DEFAULT_USERLIST_WIDTH)))
        userlist_width_spin.connect("value-changed", self._on_userlist_width_changed)
        self._settings_widgets["userlist_width"] = userlist_width_spin
        self._box_append(userlist_width_row, userlist_width_label)
        self._box_append(userlist_width_row, userlist_width_spin)
        self._box_append(content, userlist_width_row)

        userlist_hidden = Gtk.CheckButton()
        userlist_hidden.set_label("Hide the room user list")
        userlist_hidden.set_active(bool(self.settings.get("userlist_hidden", False)))
        userlist_hidden.connect("toggled", self._on_userlist_hidden_toggled)
        self._settings_widgets["userlist_hidden"] = userlist_hidden
        self._box_append(content, userlist_hidden)

        hint = Gtk.Label(xalign=0)
        hint.set_markup(
            "<small>The buddy list is resized by moving Nicotine+'s native divider "
            "(you can still drag it). The room user list has no native divider, so "
            "its width is set directly. Changes apply immediately.</small>"
        )
        hint.set_wrap(True)
        self._box_append(content, hint)

        close_button = Gtk.Button()
        close_button.set_label("Close")
        close_button.set_halign(Gtk.Align.END)
        close_button.connect("clicked", self._on_close_clicked)
        self._box_append(content, close_button)

        window.connect("destroy", self._on_settings_destroyed)
        window.present()

    def _on_enabled_toggled(self, button):

        try:
            self.settings["enabled"] = bool(button.get_active())
        except Exception:
            pass

        self._applied_width = set()
        self._apply()

    def _on_buddy_hidden_toggled(self, button):

        try:
            self.settings["buddy_hidden"] = bool(button.get_active())
        except Exception:
            pass

        self._applied_width = set()
        self._apply()

    def _on_buddy_width_changed(self, spin):

        try:
            self.settings["buddy_width"] = int(spin.get_value_as_int())
        except Exception:
            pass

        self._applied_width = set()
        self._apply()

    def _on_userlist_hidden_toggled(self, button):

        try:
            self.settings["userlist_hidden"] = bool(button.get_active())
        except Exception:
            pass

        if not self.settings["userlist_hidden"]:
            self._restore_userlist_visibility()

        self._apply()

    def _on_userlist_width_changed(self, spin):

        try:
            self.settings["userlist_width"] = int(spin.get_value_as_int())
        except Exception:
            pass

        self._apply()

    def _on_close_clicked(self, _button):

        self._close_settings_window()

    def _on_settings_destroyed(self, _window):

        self._settings_window = None
        self._settings_widgets = {}
