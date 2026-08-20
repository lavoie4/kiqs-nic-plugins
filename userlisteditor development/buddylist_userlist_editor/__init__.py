"""Buddy List / User List Editor — a standalone plugin that owns the buddy-list
sidebar and the room user list (member list), with width sliders, hide toggles,
and a drag-resizable room user list.

It is built to run ALONGSIDE Theme Customizer. The two don't collide because:

- This plugin only touches the buddy-list pane and the room user list, and finds
  them by Gtk.Builder id from the full window tree each time, so it works no
  matter how Theme Customizer re-wraps the window in its background overlay.
- Every operation is idempotent and re-applied on a short poll, so if Theme
  Customizer rebuilds its overlay, this plugin re-finds and re-applies on its own.

Important: leave Theme Customizer's own buddy-list / room-user-list options OFF
(they are superseded by this plugin) so there is a single owner.

The buddy list sits in a native horizontal Gtk.Paned, so it resizes by moving the
divider (paned.set_position). The room user list does NOT sit in a paned — it is a
fixed-width Gtk.Box next to the vertical chat paned. This plugin rips it out and
rebuilds that row as a horizontal Gtk.Paned (chat = start, user list = end), so the
native divider gives drag-resize for free, exactly like the buddy list.
"""

from pynicotine.pluginsystem import BasePlugin

USERLIST_CONTAINER_ID = "users_container"
BUDDY_LIST_END_IDS = {"buddy_list_container", "chatrooms_buddy_list_container"}

DEFAULT_USERLIST_WIDTH = 180
DEFAULT_BUDDY_WIDTH = 200
BUDDY_MIN_WIDTH = 50
BUDDY_MAX_WIDTH = 1200
USERLIST_MIN_WIDTH = 40
USERLIST_MAX_WIDTH = 1600

POLL_INTERVAL_MS = 750


class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.settings = {
            "buddy_width": DEFAULT_BUDDY_WIDTH,
            "buddy_hidden": False,
            "userlist_width": DEFAULT_USERLIST_WIDTH,
            "userlist_resizable": True,
            "userlist_hidden": False,
        }

        self.metasettings = {
            "buddy_width": {
                "description": "Buddy list width in pixels",
                "type": "integer",
                "minimum": BUDDY_MIN_WIDTH,
                "maximum": BUDDY_MAX_WIDTH,
            },
            "buddy_hidden": {
                "description": "Hide the buddy-list sidebar",
                "type": "bool",
            },
            "userlist_width": {
                "description": "Room user list width in pixels",
                "type": "integer",
                "minimum": USERLIST_MIN_WIDTH,
                "maximum": USERLIST_MAX_WIDTH,
            },
            "userlist_resizable": {
                "description": "Make the room user list drag-resizable",
                "type": "bool",
            },
            "userlist_hidden": {
                "description": "Hide the room user list",
                "type": "bool",
            },
        }

        self.commands = {
            "buddylist": {
                "callback": self.command,
                "description": "Buddy List / User List Editor: hide/show or open settings",
                "parameters": ["[settings|hide-buddy|show-buddy|hide-users|show-users]"],
                "group": "Buddy List / User List Editor",
            },
            "bul": {
                "callback": self.command,
                "description": "Short alias for /buddylist",
                "parameters": ["[settings|hide-buddy|show-buddy|hide-users|show-users]"],
                "group": "Buddy List / User List Editor",
            },
        }

        self._gtk = None
        self._poll_id = None
        self._window = None
        self._applied_buddy_width = set()
        self._last_buddy_signature = None
        self._converted_panes = set()   # panes awaiting position set
        self._positioned_panes = {}     # paned -> applied width (stops the snap-back)
        self._sync_handlers = {}        # paned -> notify::position handler id
        self._applying_position = False  # guard so our own set_position isn't re-synced
        self._width_scales = {}
        self._settings_window = None

    # --- lifecycle -----------------------------------------------------------

    def init(self):
        gtk = self._get_gtk()

        if not gtk:
            return

        self._apply_all(gtk)
        self._poll_id = gtk["GLib"].timeout_add(POLL_INTERVAL_MS, self._poll)

    def disable(self):
        self._close_settings_window()

        if self._poll_id is not None:
            gtk = self._get_gtk()

            if gtk:
                try:
                    gtk["GLib"].source_remove(self._poll_id)
                except Exception:
                    pass

            self._poll_id = None

        self._disconnect_sync()
        self._restore_all()
        self._gtk = None

    # --- gtk plumbing ---------------------------------------------------------

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
            if isinstance(window, Gtk.ApplicationWindow):
                return window

        return None

    @staticmethod
    def _widget_id(widget):

        try:
            bid = widget.get_buildable_id()

            if bid:
                return bid
        except Exception:
            pass

        try:
            return widget.get_name()
        except Exception:
            return None

    @staticmethod
    def _iter_children(Gtk, widget):

        if Gtk.get_major_version() >= 4:
            child = widget.get_first_child()

            while child is not None:
                yield child
                child = child.get_next_sibling()
        else:
            try:
                children = widget.get_children()
            except (AttributeError, TypeError):
                return

            for child in children:
                yield child

    def _walk(self, Gtk, widget):

        stack = list(self._iter_children(Gtk, widget))

        while stack:
            current = stack.pop()
            yield current
            stack.extend(self._iter_children(Gtk, current))

    def _iter_horizontal_paned(self, Gtk, window):

        for widget in self._walk(Gtk, window):
            if isinstance(widget, Gtk.Paned):
                try:
                    if widget.get_orientation() == Gtk.Orientation.HORIZONTAL:
                        yield widget
                except Exception:
                    continue

    @staticmethod
    def _end_child(paned):

        get_end = getattr(paned, "get_end_child", None)

        if get_end is not None:
            try:
                return get_end()
            except Exception:
                return None

        get_child2 = getattr(paned, "get_child2", None)

        if get_child2 is not None:
            try:
                return get_child2()
            except Exception:
                return None

        return None

    def _has_visible_child(self, Gtk, container):

        if container is None:
            return False

        try:
            for child in self._iter_children(Gtk, container):
                try:
                    if child.get_visible():
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        return False

    def _iter_userlist_containers(self, Gtk, window):

        for widget in self._walk(Gtk, window):
            if self._widget_id(widget) == USERLIST_CONTAINER_ID:
                yield widget

    # --- apply ----------------------------------------------------------------

    def _apply_all(self, gtk):

        Gtk = gtk["Gtk"]
        window = self._find_main_window(Gtk)

        if window is None:
            return

        self._window = window
        self._apply_buddy_list(gtk)
        self._apply_userlist(gtk)
        self._flush_converted_panes(Gtk)

    def _apply_buddy_list(self, gtk):

        Gtk = gtk["Gtk"]
        window = self._window

        if window is None:
            return

        hidden = bool(self.settings.get("buddy_hidden", False))
        width = int(self.settings.get("buddy_width", DEFAULT_BUDDY_WIDTH))

        for paned in self._iter_horizontal_paned(Gtk, window):
            end = self._end_child(paned)

            if end is None:
                continue

            tag = self._widget_id(end)

            if tag not in BUDDY_LIST_END_IDS:
                continue

            if hidden:
                try:
                    end.set_visible(False)
                except Exception:
                    pass
                continue

            if not self._has_visible_child(Gtk, end):
                continue

            try:
                end.set_visible(True)
            except Exception:
                pass

            self._connect_position_sync(paned)

            if tag in self._applied_buddy_width:
                continue

            if self._set_paned_end_width(paned, width, BUDDY_MIN_WIDTH, BUDDY_MAX_WIDTH):
                self._applied_buddy_width.add(tag)
                self.log("Buddy List / User List Editor: buddy list set to %d px.", (width,))

    def _set_paned_end_width(self, paned, width, minimum, maximum):

        try:
            total = paned.get_allocated_width()
        except Exception:
            return False

        if total <= 0:
            return False

        width = max(minimum, min(int(width), maximum, total - 1))
        position = total - width

        if position < 0:
            position = 0

        self._applying_position = True

        try:
            paned.set_position(position)
            return True
        except Exception:
            return False
        finally:
            self._applying_position = False

    def _connect_position_sync(self, paned):
        """Watch the divider so the width setting tracks where the user leaves it."""

        if paned in self._sync_handlers:
            return

        try:
            handler_id = paned.connect("notify::position", self._on_position_changed)
        except Exception:
            return

        self._sync_handlers[paned] = handler_id

    def _on_position_changed(self, paned, _pspec):

        if self._applying_position:
            return

        end = self._end_child(paned)
        tag = self._widget_id(end) if end is not None else None

        if tag in BUDDY_LIST_END_IDS:
            key = "buddy_width"
            minimum, maximum = BUDDY_MIN_WIDTH, BUDDY_MAX_WIDTH
        elif tag == USERLIST_CONTAINER_ID:
            key = "userlist_width"
            minimum, maximum = USERLIST_MIN_WIDTH, USERLIST_MAX_WIDTH
        else:
            return

        try:
            total = paned.get_allocated_width()
            position = paned.get_position()
        except Exception:
            return

        if total <= 0:
            return

        width = max(1, total - position)
        width = max(minimum, min(width, maximum))
        self.settings[key] = width

    def _disconnect_sync(self):

        for paned, handler_id in list(self._sync_handlers.items()):
            try:
                paned.disconnect(handler_id)
            except Exception:
                pass

        self._sync_handlers = {}

    def _apply_userlist(self, gtk):

        Gtk = gtk["Gtk"]
        window = self._window

        if window is None:
            return

        hidden = bool(self.settings.get("userlist_hidden", False))
        resizable = bool(self.settings.get("userlist_resizable", False))
        width = int(self.settings.get("userlist_width", DEFAULT_USERLIST_WIDTH))

        for container in self._iter_userlist_containers(Gtk, window):
            if hidden:
                try:
                    container.set_visible(False)
                except Exception:
                    pass
                continue

            try:
                container.set_visible(True)
            except Exception:
                pass

            if resizable:
                paned = self._nuclear_convert(Gtk, container)

                if paned is not None:
                    self._converted_panes.add(paned)
            else:
                try:
                    container.set_width_request(width)
                except Exception:
                    pass

    def _nuclear_convert(self, Gtk, users_container):
        """Rip the user list out of its plain box and rebuild it as the end child
        of a horizontal Gtk.Paned, copying the buddy list's layout."""

        try:
            parent = users_container.get_parent()
            chat_paned = users_container.get_prev_sibling()
        except Exception:
            return None

        if parent is None or chat_paned is None:
            return None

        # Already converted (or already inside some paned): nothing to do.
        if isinstance(parent, Gtk.Paned):
            return parent

        if not isinstance(parent, Gtk.Box) or not isinstance(chat_paned, Gtk.Paned):
            return None

        try:
            grandparent = parent.get_parent()
        except Exception:
            return None

        if grandparent is None or not isinstance(grandparent, Gtk.Box):
            return None

        try:
            # Nuclear teardown: completely detach the row.
            parent.remove(chat_paned)
            parent.remove(users_container)
            grandparent.remove(parent)

            # Let the paned own the width; drop the fixed 180px request.
            try:
                users_container.set_width_request(-1)
            except Exception:
                pass

            # Rebuild: a fresh horizontal paned, buddy-list style.
            paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
            paned.set_hexpand(True)
            paned.set_vexpand(True)
            paned.set_visible(True)

            if Gtk.get_major_version() >= 4:
                paned.set_start_child(chat_paned)
                paned.set_end_child(users_container)
            else:
                paned.pack1(chat_paned, resize=True, shrink=False)
                paned.pack2(users_container, resize=False, shrink=True)

            paned.set_resize_start_child(True)
            paned.set_shrink_start_child(False)
            paned.set_resize_end_child(False)
            paned.set_shrink_end_child(True)

            grandparent.append(paned)
            self.log("Buddy List / User List Editor: rebuilt room user list as a drag-resizable paned.")
            return paned
        except Exception as exc:
            self.log("Buddy List / User List Editor: rebuild failed: %s", (exc,))
            return None

    def _flush_converted_panes(self, Gtk):

        width = int(self.settings.get("userlist_width", DEFAULT_USERLIST_WIDTH))
        pending = set()

        for paned in self._converted_panes:
            try:
                if paned.get_parent() is None:
                    self._positioned_panes.pop(paned, None)
                    continue
            except Exception:
                continue

            self._connect_position_sync(paned)

            # Only (re)apply when the width actually changed. This stops the
            # divider from snapping back to the stored width after the user drags
            # it: the native paned keeps whatever position the user set.
            if self._positioned_panes.get(paned) == width:
                continue

            if self._set_paned_end_width(paned, width, USERLIST_MIN_WIDTH, USERLIST_MAX_WIDTH):
                self._positioned_panes[paned] = width
            else:
                pending.add(paned)

        self._converted_panes = pending

    # --- restore ----------------------------------------------------------------

    def _restore_all(self):

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]
        window = self._find_main_window(Gtk)

        if window is None:
            return

        for paned in self._iter_horizontal_paned(Gtk, window):
            end = self._end_child(paned)

            if end is not None and self._has_visible_child(Gtk, end):
                try:
                    end.set_visible(True)
                except Exception:
                    pass

        for container in self._iter_userlist_containers(Gtk, window):
            try:
                container.set_visible(True)
            except Exception:
                pass

        self._applied_buddy_width = set()
        self._converted_panes = set()
        self._positioned_panes = {}

    # --- poll -------------------------------------------------------------------

    def _poll(self):

        gtk = self._get_gtk()

        if not gtk:
            return True

        buddy_signature = (
            int(self.settings.get("buddy_width", DEFAULT_BUDDY_WIDTH)),
            bool(self.settings.get("buddy_hidden", False)),
        )

        if buddy_signature != self._last_buddy_signature:
            self._applied_buddy_width = set()
            self._last_buddy_signature = buddy_signature

        self._apply_all(gtk)
        return True

    # --- settings window ---------------------------------------------------------

    def _open_settings(self):

        gtk = self._get_gtk()

        if not gtk:
            self.output("Buddy List / User List Editor settings require a graphical session.")
            return True

        Gtk = gtk["Gtk"]

        if Gtk.get_major_version() < 4:
            self.output("Buddy List / User List Editor settings require GTK 4.")
            return True

        if self._settings_window is not None:
            try:
                self._settings_window.present()
            except Exception:
                self._close_settings_window()
            else:
                return True

        self._build_settings_window(Gtk)
        return True

    def _close_settings_window(self):

        if self._settings_window is not None:
            try:
                self._settings_window.destroy()
            except Exception:
                pass

            self._settings_window = None

        self._width_scales = {}

    def _big_title(self, Gtk, text):

        label = Gtk.Label(xalign=0.0, visible=True)
        label.set_markup(f'<span size="x-large" weight="bold">{text}</span>')
        label.set_margin_top(10)
        label.set_margin_bottom(6)
        return label

    def _row(self, Gtk, caption, control):

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, visible=True)
        label = Gtk.Label(label=caption, xalign=0.0, visible=True)
        label.set_halign(Gtk.Align.START)
        label.set_size_request(190, -1)
        row.append(label)
        row.append(control)
        return row

    def _make_width_control(self, Gtk, value, minimum, maximum, key):
        """A resize slider + spin + live px label, synced together."""

        box = Gtk.Box(spacing=8, visible=True)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, float(minimum), float(maximum), 10)
        scale.set_digits(0)
        scale.set_hexpand(True)
        scale.set_value(float(value))

        spin = Gtk.SpinButton.new_with_range(minimum, maximum, 10)
        spin.set_digits(0)
        spin.set_width_chars(5)
        spin.set_value(value)

        label = Gtk.Label(label=f"{int(value)}px", width_chars=5, xalign=1, visible=True)

        def sync_from_scale(s, s_spin=spin, s_label=label):
            v = int(round(s.get_value()))

            if s_spin.get_value_as_int() != v:
                s_spin.set_value(v)

            s_label.set_text(f"{v}px")

        def sync_from_spin(sp, sp_scale=scale, sp_label=label):
            v = sp.get_value_as_int()

            if int(round(sp_scale.get_value())) != v:
                sp_scale.set_value(v)

            sp_label.set_text(f"{v}px")

        scale.connect("value-changed", sync_from_scale)
        spin.connect("value-changed", sync_from_spin)

        box.append(scale)
        box.append(spin)
        box.append(label)

        self._width_scales[key] = scale
        return box

    def _switch(self, Gtk, active):

        switch = Gtk.Switch(active=bool(active), visible=True)
        switch.set_halign(Gtk.Align.START)
        return switch

    def _build_settings_window(self, Gtk):

        window = Gtk.Window(title="Buddy List / User List Editor")
        window.set_default_size(560, 440)
        window.set_resizable(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=True)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        box.append(self._big_title(Gtk, "Buddy List"))

        buddy_width = self._make_width_control(
            Gtk, int(self.settings.get("buddy_width", DEFAULT_BUDDY_WIDTH)),
            BUDDY_MIN_WIDTH, BUDDY_MAX_WIDTH, "buddy_width"
        )
        box.append(self._row(Gtk, "Buddy list width", buddy_width))

        buddy_hidden = self._switch(Gtk, self.settings.get("buddy_hidden", False))
        box.append(self._row(Gtk, "Hide buddy list", buddy_hidden))

        box.append(self._big_title(Gtk, "Room User List"))

        userlist_width = self._make_width_control(
            Gtk, int(self.settings.get("userlist_width", DEFAULT_USERLIST_WIDTH)),
            USERLIST_MIN_WIDTH, USERLIST_MAX_WIDTH, "userlist_width"
        )
        box.append(self._row(Gtk, "User list width", userlist_width))

        userlist_resizable = self._switch(Gtk, self.settings.get("userlist_resizable", True))
        box.append(self._row(Gtk, "Drag-resizable user list", userlist_resizable))

        userlist_hidden = self._switch(Gtk, self.settings.get("userlist_hidden", False))
        box.append(self._row(Gtk, "Hide user list", userlist_hidden))

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, visible=True)
        button_row.set_halign(Gtk.Align.END)
        button_row.set_margin_top(12)

        apply_button = Gtk.Button(label="Apply", visible=True)
        apply_button.connect(
            "clicked",
            lambda _b: self._apply_from_widgets(buddy_hidden, userlist_resizable, userlist_hidden)
        )

        close_button = Gtk.Button(label="Close", visible=True)
        close_button.connect("clicked", lambda *a: self._close_settings_window())

        button_row.append(apply_button)
        button_row.append(close_button)
        box.append(button_row)

        hint = Gtk.Label(
            label="Open a chat room to see the room user list. The buddy list is the "
                  "left sidebar (main window and Chatrooms tab).",
            xalign=0, wrap=True
        )
        hint.add_css_class("dim-label")
        box.append(hint)

        compat = Gtk.Label(
            label="Runs alongside Theme Customizer. Leave Theme Customizer's own "
                  "buddy-list / room-user-list options OFF so this plugin is the "
                  "single owner of those controls.",
            xalign=0, wrap=True
        )
        compat.add_css_class("dim-label")
        box.append(compat)

        window.set_child(box)
        self._settings_window = window
        window.present()

    def _apply_from_widgets(self, buddy_hidden, userlist_resizable, userlist_hidden):

        if "buddy_width" in self._width_scales:
            self.settings["buddy_width"] = int(round(self._width_scales["buddy_width"].get_value()))

        if "userlist_width" in self._width_scales:
            self.settings["userlist_width"] = int(round(self._width_scales["userlist_width"].get_value()))

        self.settings["buddy_hidden"] = bool(buddy_hidden.get_active())
        self.settings["userlist_resizable"] = bool(userlist_resizable.get_active())
        self.settings["userlist_hidden"] = bool(userlist_hidden.get_active())

        self._applied_buddy_width = set()
        self._last_buddy_signature = None

        gtk = self._get_gtk()

        if gtk:
            self._apply_all(gtk)

        self.output("Buddy List / User List Editor settings applied.")

    # --- command -----------------------------------------------------------------

    def command(self, args, **_unused):

        action = (args or "").strip().lower()

        if action in {"", "settings", "gui", "options", "open"}:
            return self._open_settings()

        gtk = self._get_gtk()

        if action in {"hide-buddy", "hide-buddies"}:
            self.settings["buddy_hidden"] = True
            self._applied_buddy_width = set()

            if gtk:
                self._apply_all(gtk)

            self.output("Buddy-list sidebar hidden.")
            return True

        if action in {"show-buddy", "show-buddies"}:
            self.settings["buddy_hidden"] = False
            self._applied_buddy_width = set()

            if gtk:
                self._apply_all(gtk)

            self.output("Buddy-list sidebar shown.")
            return True

        if action in {"hide-users", "hide-userlist"}:
            self.settings["userlist_hidden"] = True

            if gtk:
                self._apply_all(gtk)

            self.output("Room user list hidden.")
            return True

        if action in {"show-users", "show-userlist"}:
            self.settings["userlist_hidden"] = False

            if gtk:
                self._apply_all(gtk)

            self.output("Room user list shown.")
            return True

        self.output("Usage: /buddylist [settings|hide-buddy|show-buddy|hide-users|show-users]")
        return True
