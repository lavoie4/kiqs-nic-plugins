"""Page Doll — decorative transparent character image in the private-chats pane.

Concept: Tumblr-style "page dolls" — a transparent PNG or animated GIF that sits
in the Private Chat pane as a decorative layer in a corner. The user controls the
doll's exact width and height and its position.

GTK 4 is required for animated GIF support and overlay layering. On GTK 3 the
plugin logs a notice and does nothing (no crash).

The doll is added as the TOP overlay layer above the private-chat notebook, so it
is always visible. It carries no event controllers/gestures, so pointer input
passes straight through to the widgets underneath.
"""

import os

from pynicotine.pluginsystem import BasePlugin

# Target widget: the "Private Chat" tab's session-list container.
PRIVATE_CONTENT_ID = "private_content"

DEFAULT_WIDTH = 160
DEFAULT_HEIGHT = 240
MIN_SIZE = 1
# No practical size cap: generous ceilings only so spin buttons stay usable.
MAX_WIDTH = 10000
MAX_HEIGHT = 10000
ALLOWED_EXTENSIONS = (".png", ".gif")
DOLL_MARGIN = 12
POLL_INTERVAL_MS = 1000

POSITION_ALIGN = {
    "bottom-right": ("END", "END"),
    "bottom-left": ("START", "END"),
    "top-right": ("END", "START"),
    "top-left": ("START", "START"),
    "center": ("CENTER", "CENTER"),
}


class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.settings = {
            "enabled": True,
            "image_path": "",
            "width": DEFAULT_WIDTH,
            "height": DEFAULT_HEIGHT,
            "position": "bottom-right",
        }

        self.metasettings = {
            "enabled": {
                "description": "Show the page doll",
                "type": "bool",
            },
            "image_path": {
                "description": "Page doll image (.png or .gif)",
                "type": "file",
                "chooser": "image",
            },
            "width": {
                "description": "Page doll width in pixels",
                "type": "integer",
                "minimum": MIN_SIZE,
            },
            "height": {
                "description": "Page doll height in pixels",
                "type": "integer",
                "minimum": MIN_SIZE,
            },
            "position": {
                "description": "Page doll position in the pane",
                "type": "dropdown",
                "options": list(POSITION_ALIGN.keys()),
            },
        }

        self.commands = {
            "pagedoll": {
                "callback": self.pagedoll_command,
                "description": "Page doll: settings | on | off | refresh",
                "parameters": ["[settings|on|off|refresh]"],
                "group": "Page Doll",
            },
            "pd": {
                "callback": self.pagedoll_command,
                "description": "Short alias for /pagedoll",
                "parameters": ["[settings|on|off|refresh]"],
                "group": "Page Doll",
            },
        }

        self._gtk = None
        self._poll_id = None
        self._window = None
        self._content = None
        self._overlay = None
        self._doll_box = None
        self._doll = None
        self._signature = None

        # GIF animation state
        self._gif_timeout = None
        self._gif_iter = None
        self._gif_picture = None

        # Settings window
        self._settings_window = None
        self._path_entry = None
        self._width_spin = None
        self._height_spin = None
        self._position_combo = None
        self._enabled_switch = None

    # --- lifecycle -----------------------------------------------------------

    def init(self):
        gtk = self._get_gtk()

        if not gtk:
            return

        self._refresh(gtk)
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

        gtk = self._get_gtk()

        if gtk:
            self._teardown(gtk)

        self._stop_gif()
        self._gtk = None

    # --- gtk plumbing ---------------------------------------------------------

    def _get_gtk(self):

        if self._gtk is not None:
            return self._gtk

        try:
            import gi  # noqa: F401  pylint: disable=import-error
            from gi.repository import Gdk
            from gi.repository import GdkPixbuf
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

        self._gtk = {"Gdk": Gdk, "GdkPixbuf": GdkPixbuf, "GLib": GLib, "Gtk": Gtk}
        return self._gtk

    def _find_main_window(self, Gtk):

        try:
            toplevels = Gtk.Window.list_toplevels()
        except Exception:
            return None

        for window in toplevels:
            if isinstance(window, Gtk.ApplicationWindow):
                return window

        for window in toplevels:
            try:
                if window.get_visible():
                    return window
            except Exception:
                continue

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

    def _find_private_content(self, Gtk, window):

        if window is None:
            return None

        for widget in self._walk(Gtk, window):
            try:
                if self._widget_id(widget) == PRIVATE_CONTENT_ID:
                    return widget
            except Exception:
                continue

        return None

    @staticmethod
    def _clean_path(value):
        value = (value or "").strip()

        if not value:
            return ""

        return os.path.expanduser(value)

    @staticmethod
    def _clamp_size(value, minimum, maximum):

        try:
            value = int(value)
        except (TypeError, ValueError):
            value = minimum

        return max(minimum, min(maximum, value))

    def _current_signature(self):

        path = self._clean_path(self.settings.get("image_path", ""))
        width = self._clamp_size(self.settings.get("width", DEFAULT_WIDTH), MIN_SIZE, MAX_WIDTH)
        height = self._clamp_size(self.settings.get("height", DEFAULT_HEIGHT), MIN_SIZE, MAX_HEIGHT)
        position = self.settings.get("position", "bottom-right")

        if position not in POSITION_ALIGN:
            position = "bottom-right"

        return (
            bool(self.settings.get("enabled", True)),
            path,
            width,
            height,
            position,
        )

    # --- apply / restore --------------------------------------------------------

    def _refresh(self, gtk):
        """Tear down any existing wrap and rebuild it to match current state."""

        Gtk = gtk["Gtk"]

        self._teardown(gtk)

        self._window = self._find_main_window(Gtk)
        self._content = self._find_private_content(Gtk, self._window)
        self._signature = self._current_signature()

        if self._window is None:
            self.log("Page doll: main window not found yet.")
            return

        if self._content is None:
            self.log("Page doll: 'private_content' container not found in the window tree.")
            return

        if Gtk.get_major_version() < 4:
            self.log("Page doll requires GTK 4 (animated GIF + overlay layering). GTK 3 is a no-op.")
            return

        if not self.settings.get("enabled", True):
            return

        path = self._clean_path(self.settings.get("image_path", ""))

        if not path:
            self.log("Page doll: no image set. Use /pagedoll settings to choose a .png or .gif.")
            return

        if not os.path.isfile(path):
            self.log("Page doll: image not found: %s", (path,))
            return

        extension = os.path.splitext(path)[1].lower()

        if extension not in ALLOWED_EXTENSIONS:
            self.log("Page doll: unsupported image type %s (use .png or .gif)", (extension,))
            return

        width = self._clamp_size(self.settings.get("width", DEFAULT_WIDTH), MIN_SIZE, MAX_WIDTH)
        height = self._clamp_size(self.settings.get("height", DEFAULT_HEIGHT), MIN_SIZE, MAX_HEIGHT)
        position = self.settings.get("position", "bottom-right")

        if position not in POSITION_ALIGN:
            position = "bottom-right"

        overlay = Gtk.Overlay()

        # Move the existing content (the private-chat notebook) into the overlay
        # base layer. private_content keeps its place in the tree.
        for child in list(self._iter_children(Gtk, self._content)):
            try:
                self._content.remove(child)
            except Exception:
                continue

            overlay.add_overlay(child)

        # The doll goes on TOP so it is always visible. It carries no event
        # controllers, so pointer input passes through to the widgets below.
        doll_box = Gtk.Box(hexpand=True, vexpand=True, visible=True)
        doll = self._make_picture(gtk, path, width, height)

        halign_name, valign_name = POSITION_ALIGN[position]
        doll.set_halign(getattr(Gtk.Align, halign_name))
        doll.set_valign(getattr(Gtk.Align, valign_name))
        doll.set_margin_start(DOLL_MARGIN)
        doll.set_margin_end(DOLL_MARGIN)
        doll.set_margin_top(DOLL_MARGIN)
        doll.set_margin_bottom(DOLL_MARGIN)

        doll_box.append(doll)
        overlay.add_overlay(doll_box)

        self._content.append(overlay)

        self._overlay = overlay
        self._doll_box = doll_box
        self._doll = doll

        self.log("Page doll shown (%dx%d, %s, %s).", (width, height, position, path))

    def _teardown(self, gtk):
        """Undo the overlay wrap and any GIF animation."""

        self._stop_gif()

        overlay = self._overlay
        content = self._content
        doll_box = self._doll_box

        self._overlay = None
        self._content = None
        self._doll_box = None
        self._doll = None

        if overlay is None or content is None:
            return

        Gtk = gtk["Gtk"]

        try:
            for child in list(self._iter_children(Gtk, overlay)):
                if child is doll_box:
                    continue

                try:
                    overlay.remove(child)
                except Exception:
                    pass

                try:
                    content.append(child)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            content.remove(overlay)
        except Exception:
            pass

    def _poll(self):

        gtk = self._get_gtk()

        if not gtk:
            return True

        if self._signature != self._current_signature():
            self._refresh(gtk)
            return True

        if self._overlay is not None:
            try:
                if self._overlay.get_parent() is not self._content:
                    self._refresh(gtk)
            except Exception:
                self._refresh(gtk)

        return True

    # --- image rendering -------------------------------------------------------

    def _make_picture(self, gtk, path, width, height):

        Gtk = gtk["Gtk"]
        Gdk = gtk["Gdk"]
        GdkPixbuf = gtk["GdkPixbuf"]

        picture = Gtk.Picture()
        picture.set_can_shrink(True)
        picture.set_size_request(width, height)
        picture.set_content_fit(Gtk.ContentFit.FILL)

        extension = os.path.splitext(path)[1].lower()

        if extension == ".gif":
            try:
                animation = GdkPixbuf.PixbufAnimation.new_from_file(path)
                self._start_gif(gtk, picture, animation)
            except Exception as exc:
                self.log("Page doll: could not load GIF: %s", (exc,))
        else:
            try:
                texture = Gdk.Texture.new_from_file(path)

                if texture is None:
                    self.log("Page doll: could not load image (unsupported or corrupt): %s", (path,))
                else:
                    picture.set_paintable(texture)
            except Exception as exc:
                self.log("Page doll: could not load image: %s", (exc,))

        return picture

    def _start_gif(self, gtk, picture, animation):

        GLib = gtk["GLib"]

        self._gif_picture = picture

        try:
            self._gif_iter = animation.get_iter(None)
        except Exception as exc:
            self._gif_iter = None
            self.log("Page doll: GIF animation not started: %s", (exc,))
            return

        self._gif_show_frame(gtk)
        self._gif_timeout = GLib.timeout_add(self._gif_delay(), self._gif_tick)

    def _gif_tick(self):

        if self._gtk is None or self._gif_iter is None:
            return False

        GLib = self._gtk["GLib"]

        try:
            try:
                self._gif_iter.advance()
            except TypeError:
                self._gif_iter.advance(GLib.get_real_time() // 1000)

            self._gif_show_frame(self._gtk)
            delay = self._gif_delay()
        except Exception as exc:
            self.log("Page doll: GIF animation stopped: %s", (exc,))
            return False

        self._gif_timeout = GLib.timeout_add(delay, self._gif_tick)
        return False

    def _gif_show_frame(self, gtk):

        Gdk = gtk["Gdk"]
        pixbuf = self._gif_iter.get_pixbuf()

        if pixbuf is not None and self._gif_picture is not None:
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self._gif_picture.set_paintable(texture)
            self._gif_picture.queue_draw()

    def _gif_delay(self):

        delay = self._gif_iter.get_delay_time()

        if not delay or delay < 10:
            return 100

        return delay

    def _stop_gif(self):

        if self._gif_timeout is not None and self._gtk:
            try:
                self._gtk["GLib"].source_remove(self._gif_timeout)
            except Exception:
                pass

        if self._gif_picture is not None:
            try:
                self._gif_picture.set_paintable(None)
            except Exception:
                pass

        self._gif_timeout = None
        self._gif_iter = None
        self._gif_picture = None

    # --- settings window ---------------------------------------------------------

    def _open_settings_window(self):

        gtk = self._get_gtk()

        if not gtk:
            self.output("Page doll settings require a running GTK session.")
            return

        Gtk = gtk["Gtk"]

        if Gtk.get_major_version() < 4:
            self.output("Page doll settings require GTK 4.")
            return

        if self._settings_window is not None:
            try:
                self._settings_window.present()
                return
            except Exception:
                self._settings_window = None

        self._build_settings_window(Gtk)

        try:
            self._settings_window.present()
        except Exception:
            pass

    def _close_settings_window(self):

        if self._settings_window is not None:
            try:
                self._settings_window.destroy()
            except Exception:
                pass

            self._settings_window = None

        self._path_entry = None
        self._width_spin = None
        self._height_spin = None
        self._position_combo = None
        self._enabled_switch = None

    def _big_title(self, Gtk, text):

        label = Gtk.Label(xalign=0.0, visible=True)
        label.set_markup(f'<span size="x-large" weight="bold">{text}</span>')
        label.set_margin_top(10)
        label.set_margin_bottom(6)
        return label

    def _build_settings_window(self, Gtk):

        window = Gtk.Window(title="Page Doll Settings")
        window.set_default_size(480, 420)
        window.set_resizable(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=True)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        box.append(self._big_title(Gtk, "Page Doll"))

        self._enabled_switch = Gtk.Switch(active=bool(self.settings.get("enabled", True)), visible=True)
        self._enabled_switch.set_halign(Gtk.Align.START)
        box.append(self._row(Gtk, "Enabled", self._enabled_switch))

        self._path_entry = Gtk.Entry(visible=True, hexpand=True)
        self._path_entry.set_text(self.settings.get("image_path", ""))
        browse = Gtk.Button(label="Browse…", visible=True)
        browse.connect("clicked", self._on_browse)
        path_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, visible=True)
        path_row.append(self._path_entry)
        path_row.append(browse)
        box.append(self._row(Gtk, "Image (.png / .gif)", path_row))

        self._width_spin = self._make_spin(
            Gtk, self._clamp_size(self.settings.get("width", DEFAULT_WIDTH), MIN_SIZE, MAX_WIDTH)
        )
        box.append(self._row(Gtk, "Width (px)", self._width_spin))

        self._height_spin = self._make_spin(
            Gtk, self._clamp_size(self.settings.get("height", DEFAULT_HEIGHT), MIN_SIZE, MAX_HEIGHT)
        )
        box.append(self._row(Gtk, "Height (px)", self._height_spin))

        self._position_combo = Gtk.DropDown(visible=True)
        self._build_position_dropdown()
        box.append(self._row(Gtk, "Position", self._position_combo))

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, visible=True)
        button_row.set_halign(Gtk.Align.END)
        button_row.set_margin_top(12)

        apply_button = Gtk.Button(label="Apply", visible=True)
        apply_button.connect("clicked", self._on_apply)

        close_button = Gtk.Button(label="Close", visible=True)
        close_button.connect("clicked", lambda *a: self._close_settings_window())

        button_row.append(apply_button)
        button_row.append(close_button)
        box.append(button_row)

        window.set_child(box)
        self._settings_window = window

    def _row(self, Gtk, caption, control):

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, visible=True)

        label = Gtk.Label(label=caption, xalign=0.0, visible=True)
        label.set_halign(Gtk.Align.START)
        label.set_size_request(150, -1)

        row.append(label)
        row.append(control)

        return row

    def _make_spin(self, Gtk, value):

        adjustment = Gtk.Adjustment(
            value=float(value), lower=float(MIN_SIZE), upper=float(MAX_WIDTH), step_increment=1.0,
            page_increment=10.0, page_size=0.0
        )
        spin = Gtk.SpinButton(adjustment=adjustment, visible=True)
        spin.set_numeric(True)
        spin.set_digits(0)
        spin.set_value(value)
        return spin

    def _build_position_dropdown(self):

        if self._position_combo is None:
            return

        options = list(POSITION_ALIGN.keys())
        current = self.settings.get("position", "bottom-right")

        if current not in options:
            current = "bottom-right"

        self._position_combo.set_model(self._string_list_model(options))
        self._position_combo.set_selected(options.index(current))

    def _string_list_model(self, items):

        gtk = self._get_gtk()

        if gtk:
            Gtk = gtk["Gtk"]

            try:
                return Gtk.StringList.new(items)
            except Exception:
                pass

        return None

    def _on_browse(self, _button):

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]

        chooser = Gtk.FileChooserNative(
            title="Choose a page doll image", action=Gtk.FileChooserAction.OPEN,
            accept_label="Open", cancel_label="Cancel"
        )

        file_filter = Gtk.FileFilter()
        file_filter.set_name("Page doll images (PNG, GIF)")
        file_filter.add_mime_type("image/png")
        file_filter.add_mime_type("image/gif")
        chooser.add_filter(file_filter)

        chooser.set_transient_for(self._settings_window)

        def on_response(_dialog, response_id):
            try:
                if response_id == Gtk.ResponseType.ACCEPT:
                    file = chooser.get_file()

                    if file is not None:
                        path = file.get_path()

                        if path and self._path_entry is not None:
                            self._path_entry.set_text(path)
            finally:
                chooser.destroy()

        chooser.connect("response", on_response)
        chooser.show()

    def _on_apply(self, _button):

        if self._path_entry is not None:
            self.settings["image_path"] = self._path_entry.get_text().strip()

        if self._width_spin is not None:
            self.settings["width"] = int(self._width_spin.get_value())

        if self._height_spin is not None:
            self.settings["height"] = int(self._height_spin.get_value())

        if self._position_combo is not None:
            options = list(POSITION_ALIGN.keys())
            selected = self._position_combo.get_selected()

            if 0 <= selected < len(options):
                self.settings["position"] = options[selected]

        if self._enabled_switch is not None:
            self.settings["enabled"] = self._enabled_switch.get_active()

        gtk = self._get_gtk()

        if gtk:
            self._refresh(gtk)

        self.output("Page doll settings applied.")

    # --- command -----------------------------------------------------------------

    def pagedoll_command(self, args):

        action = (args.lstrip() or "settings").strip().lower()

        if action in {"settings", "set"}:
            self._open_settings_window()
            return True

        if action == "on":
            self.settings["enabled"] = True
            gtk = self._get_gtk()

            if gtk:
                self._refresh(gtk)

            self.output("Page doll enabled.")
            return True

        if action == "off":
            self.settings["enabled"] = False
            gtk = self._get_gtk()

            if gtk:
                self._refresh(gtk)

            self.output("Page doll disabled.")
            return True

        if action == "refresh":
            gtk = self._get_gtk()

            if gtk:
                self._refresh(gtk)

            self.output("Page doll refreshed.")
            return True

        self.output("Usage: /pagedoll [settings|on|off|refresh]")
        return True
