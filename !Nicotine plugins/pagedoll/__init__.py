"""Page Doll — decorative transparent character image in Nicotine+ panes.

Concept: Tumblr-style "page dolls" — a transparent PNG or animated GIF that sits
in a pane as a decorative layer in a corner. The user controls the doll's exact
width and height and its position.

Two panes are supported:

* Private Chat — the doll is layered ON TOP of the chat notebook (it floats above
  the chat text). Clicks pass through to the chat underneath.
* Downloads — the doll is layered BEHIND the downloads list (the list text stays
  readable on top of the doll).

GTK 4 is required. On GTK 3 the plugin logs a notice and does nothing (no crash).
"""

import os

from pynicotine.pluginsystem import BasePlugin

PRIVATE_CONTENT_ID = "private_content"
DOWNLOADS_TREE_ID = "tree_container"
DOWNLOADS_CSS_CLASS = "pagedoll-downloads"

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

# Pane registry. "mode" controls how the doll is layered relative to the pane's
# content: "on_top" floats the doll above the content, "behind_text" puts the
# content above the doll (used for the Downloads list).
PANES = [
    {
        "key": "chat",
        "label": "Private Chat",
        "container_id": PRIVATE_CONTENT_ID,
        "prefix": "",
        "mode": "on_top",
    },
    {
        "key": "downloads",
        "label": "Downloads",
        "container_id": DOWNLOADS_TREE_ID,
        "prefix": "downloads_",
        "mode": "behind_text",
    },
]


class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.settings = {}
        self.metasettings = {}

        for pane in PANES:
            prefix = pane["prefix"]

            self.settings[prefix + "enabled"] = True
            self.settings[prefix + "image_path"] = ""
            self.settings[prefix + "width"] = DEFAULT_WIDTH
            self.settings[prefix + "height"] = DEFAULT_HEIGHT
            self.settings[prefix + "position"] = "bottom-right"

            self.metasettings[prefix + "enabled"] = {
                "description": "Show the page doll in %s" % pane["label"],
                "type": "bool",
            }
            self.metasettings[prefix + "image_path"] = {
                "description": "Page doll image for %s (.png or .gif)" % pane["label"],
                "type": "file",
                "chooser": "image",
            }
            self.metasettings[prefix + "width"] = {
                "description": "Page doll width for %s (pixels)" % pane["label"],
                "type": "integer",
                "minimum": MIN_SIZE,
            }
            self.metasettings[prefix + "height"] = {
                "description": "Page doll height for %s (pixels)" % pane["label"],
                "type": "integer",
                "minimum": MIN_SIZE,
            }
            self.metasettings[prefix + "position"] = {
                "description": "Page doll position for %s" % pane["label"],
                "type": "dropdown",
                "options": list(POSITION_ALIGN.keys()),
            }

        self.commands = {
            "pagedoll": {
                "callback": self.pagedoll_command,
                "description": "Page doll: settings | on | off | downloads on|off | refresh",
                "parameters": ["[settings|on|off|downloads|refresh]"],
                "group": "Page Doll",
            },
            "pd": {
                "callback": self.pagedoll_command,
                "description": "Short alias for /pagedoll",
                "parameters": ["[settings|on|off|downloads|refresh]"],
                "group": "Page Doll",
            },
        }

        self._gtk = None
        self._poll_id = None

        # Per-pane runtime state.
        self._panes = {pane["key"]: self._new_pane_state() for pane in PANES}

        self._css_provider = None

        # Settings window
        self._settings_window = None
        self._ui = {}

    @staticmethod
    def _new_pane_state():
        return {
            "content": None,
            "mount_parent": None,
            "overlay": None,
            "doll_box": None,
            "doll": None,
            "main_child": None,
            "tree": None,
            "signature": None,
            "gif_timeout": None,
            "gif_iter": None,
            "gif_picture": None,
        }

    @staticmethod
    def _pane_by_key(key):
        for pane in PANES:
            if pane["key"] == key:
                return pane

        return PANES[0]

    # --- lifecycle -----------------------------------------------------------

    def init(self):
        gtk = self._get_gtk()

        if not gtk:
            return

        self._ensure_css(gtk)
        self._refresh_all(gtk)
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
            for pane in PANES:
                self._teardown(pane, gtk)

        self._gtk = None
        self._css_provider = None

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

    def _find_widget_by_id(self, Gtk, window, widget_id):

        if window is None:
            return None

        for widget in self._walk(Gtk, window):
            try:
                if self._widget_id(widget) == widget_id:
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

    def _pane_signature(self, pane):

        prefix = pane["prefix"]
        path = self._clean_path(self.settings.get(prefix + "image_path", ""))
        width = self._clamp_size(self.settings.get(prefix + "width", DEFAULT_WIDTH), MIN_SIZE, MAX_WIDTH)
        height = self._clamp_size(self.settings.get(prefix + "height", DEFAULT_HEIGHT), MIN_SIZE, MAX_HEIGHT)
        position = self.settings.get(prefix + "position", "bottom-right")

        if position not in POSITION_ALIGN:
            position = "bottom-right"

        return (
            bool(self.settings.get(prefix + "enabled", True)),
            path,
            width,
            height,
            position,
        )

    # --- apply / restore --------------------------------------------------------

    def _refresh_all(self, gtk):
        for pane in PANES:
            self._refresh(pane, gtk)

    def _refresh(self, pane, gtk):
        if pane["mode"] == "on_top":
            self._refresh_on_top(pane, gtk)
        else:
            self._refresh_behind_text(pane, gtk)

    def _teardown(self, pane, gtk):
        if pane["mode"] == "on_top":
            self._teardown_on_top(pane, gtk)
        else:
            self._teardown_behind_text(pane, gtk)

    def _refresh_on_top(self, pane, gtk):
        """Wrap the pane's content in an overlay and float the doll above it."""

        Gtk = gtk["Gtk"]
        state = self._panes[pane["key"]]
        prefix = pane["prefix"]

        self._teardown_on_top(pane, gtk)

        state["content"] = self._find_widget_by_id(Gtk, self._find_main_window(Gtk), pane["container_id"])
        state["signature"] = self._pane_signature(pane)

        if state["content"] is None:
            self.log("(%s): '%s' container not found in the window tree.", (pane["label"], pane["container_id"]))
            return

        if Gtk.get_major_version() < 4:
            self.log("Requires GTK 4. GTK 3 is a no-op.")
            return

        if not self.settings.get(prefix + "enabled", True):
            return

        path = self._clean_path(self.settings.get(prefix + "image_path", ""))

        if not path:
            self.log("(%s): no image set. Use /pagedoll settings.", (pane["label"],))
            return

        if not os.path.isfile(path):
            self.log("(%s): image not found: %s", (pane["label"], path))
            return

        extension = os.path.splitext(path)[1].lower()

        if extension not in ALLOWED_EXTENSIONS:
            self.log("(%s): unsupported image type %s (use .png or .gif)", (pane["label"], extension))
            return

        width = self._clamp_size(self.settings.get(prefix + "width", DEFAULT_WIDTH), MIN_SIZE, MAX_WIDTH)
        height = self._clamp_size(self.settings.get(prefix + "height", DEFAULT_HEIGHT), MIN_SIZE, MAX_HEIGHT)
        position = self.settings.get(prefix + "position", "bottom-right")

        if position not in POSITION_ALIGN:
            position = "bottom-right"

        # Gtk.Overlay has exactly ONE main child (set via set_child), which it
        # measures and allocates to fill. Overlay layers go on top via
        # add_overlay(). We must not add the content with add_overlay(), or the
        # overlay ends up with no main child and collapses to 0x0.
        children = list(self._iter_children(Gtk, state["content"]))

        if not children:
            self.log("(%s): container has no children to wrap.", (pane["label"],))
            return

        if len(children) > 1:
            self.log("(%s): container has %d children (expected 1); skipping wrap.", (pane["label"], len(children)))
            return

        main_child = children[0]

        overlay = Gtk.Overlay(visible=True)

        # Preserve the content's effective expansion inside the container.
        overlay.set_halign(main_child.get_halign())
        overlay.set_valign(main_child.get_valign())

        try:
            if main_child.get_hexpand_set():
                overlay.set_hexpand(main_child.get_hexpand())

            if main_child.get_vexpand_set():
                overlay.set_vexpand(main_child.get_vexpand())
        except Exception:
            pass

        try:
            state["content"].remove(main_child)
        except Exception:
            self.log("(%s): could not remove content from its container.", (pane["label"],))
            return

        overlay.set_child(main_child)

        # The doll goes on TOP. Gtk.Picture/Gtk.Box install no event controllers
        # and are not input targets by default, so clicks pass through.
        doll_box = Gtk.Box(hexpand=True, vexpand=True, visible=True)
        doll_box.set_halign(Gtk.Align.FILL)
        doll_box.set_valign(Gtk.Align.FILL)

        doll = self._make_picture(gtk, path, width, height, state)

        halign_name, valign_name = POSITION_ALIGN[position]
        doll.set_halign(getattr(Gtk.Align, halign_name))
        doll.set_valign(getattr(Gtk.Align, valign_name))
        doll.set_margin_start(DOLL_MARGIN)
        doll.set_margin_end(DOLL_MARGIN)
        doll.set_margin_top(DOLL_MARGIN)
        doll.set_margin_bottom(DOLL_MARGIN)

        doll_box.append(doll)
        overlay.add_overlay(doll_box)

        state["content"].append(overlay)

        state["overlay"] = overlay
        state["mount_parent"] = state["content"]
        state["main_child"] = main_child
        state["doll_box"] = doll_box
        state["doll"] = doll

        self.log("(%s) shown (%dx%d, %s).", (pane["label"], width, height, position))

    def _teardown_on_top(self, pane, gtk):

        state = self._panes[pane["key"]]

        self._stop_gif(state)

        overlay = state["overlay"]
        content = state["content"]
        doll_box = state["doll_box"]
        main_child = state["main_child"]

        state["overlay"] = None
        state["content"] = None
        state["mount_parent"] = None
        state["doll_box"] = None
        state["doll"] = None
        state["main_child"] = None

        if overlay is None or content is None:
            return

        # 1. Detach the doll layer (unparent, do not destroy).
        if doll_box is not None:
            try:
                if doll_box.get_parent() is overlay:
                    overlay.remove_overlay(doll_box)
            except Exception:
                pass

        # 2. Resolve the content (the overlay's main child) and detach it.
        if main_child is None:
            try:
                main_child = overlay.get_child()
            except Exception:
                main_child = None

        try:
            overlay.set_child(None)
        except Exception:
            pass

        # 3. Remove the now-empty overlay from the container.
        try:
            if overlay.get_parent() is content:
                content.remove(overlay)
        except Exception:
            pass

        # 4. Restore the content as the container's child.
        if main_child is not None:
            try:
                content.append(main_child)
            except Exception:
                self.log("(%s): failed to restore the pane content.", (pane["label"],))

    def _refresh_behind_text(self, pane, gtk):
        """Layer the doll BEHIND the Downloads list (treeview) via an overlay."""

        Gtk = gtk["Gtk"]
        state = self._panes[pane["key"]]
        prefix = pane["prefix"]

        self._teardown_behind_text(pane, gtk)

        tree_container = self._find_widget_by_id(Gtk, self._find_main_window(Gtk), pane["container_id"])
        state["content"] = tree_container
        state["signature"] = self._pane_signature(pane)

        if tree_container is None:
            self.log("(%s): '%s' container not found in the window tree.", (pane["label"], pane["container_id"]))
            return

        if Gtk.get_major_version() < 4:
            self.log("Requires GTK 4. GTK 3 is a no-op.")
            return

        if not self.settings.get(prefix + "enabled", True):
            return

        path = self._clean_path(self.settings.get(prefix + "image_path", ""))

        if not path:
            self.log("(%s): no image set. Use /pagedoll settings.", (pane["label"],))
            return

        if not os.path.isfile(path):
            self.log("(%s): image not found: %s", (pane["label"], path))
            return

        extension = os.path.splitext(path)[1].lower()

        if extension not in ALLOWED_EXTENSIONS:
            self.log("(%s): unsupported image type %s (use .png or .gif)", (pane["label"], extension))
            return

        width = self._clamp_size(self.settings.get(prefix + "width", DEFAULT_WIDTH), MIN_SIZE, MAX_WIDTH)
        height = self._clamp_size(self.settings.get(prefix + "height", DEFAULT_HEIGHT), MIN_SIZE, MAX_HEIGHT)
        position = self.settings.get(prefix + "position", "bottom-right")

        if position not in POSITION_ALIGN:
            position = "bottom-right"

        tree_parent = tree_container.get_parent()

        if tree_parent is None:
            self.log("(%s): downloads tree has no parent to wrap.", (pane["label"],))
            return

        tree = None

        try:
            tree = tree_container.get_child()
        except Exception:
            tree = None

        overlay = Gtk.Overlay(visible=True)

        # The doll is the overlay's MAIN child (drawn first, at the bottom), so
        # it sits BEHIND the tree. The tree is an overlay layer on top, so the
        # list text stays readable above the doll.
        doll_box = Gtk.Box(hexpand=True, vexpand=True, visible=True)
        doll_box.set_halign(Gtk.Align.FILL)
        doll_box.set_valign(Gtk.Align.FILL)

        doll = self._make_picture(gtk, path, width, height, state)

        halign_name, valign_name = POSITION_ALIGN[position]
        doll.set_halign(getattr(Gtk.Align, halign_name))
        doll.set_valign(getattr(Gtk.Align, valign_name))
        doll.set_margin_start(DOLL_MARGIN)
        doll.set_margin_end(DOLL_MARGIN)
        doll.set_margin_top(DOLL_MARGIN)
        doll.set_margin_bottom(DOLL_MARGIN)

        doll_box.append(doll)
        overlay.set_child(doll_box)

        # Preserve the tree's expansion inside its parent box.
        overlay.set_halign(tree_container.get_halign())
        overlay.set_valign(tree_container.get_valign())

        try:
            if tree_container.get_hexpand_set():
                overlay.set_hexpand(tree_container.get_hexpand())

            if tree_container.get_vexpand_set():
                overlay.set_vexpand(tree_container.get_vexpand())
        except Exception:
            pass

        try:
            tree_parent.remove(tree_container)
        except Exception:
            self.log("(%s): could not remove the downloads tree from its parent.", (pane["label"],))
            return

        overlay.add_overlay(tree_container)
        # Size the overlay to the tree (the doll is small and must not dictate
        # the pane size).
        overlay.set_measure_overlay(tree_container, True)

        tree_parent.append(overlay)

        # Make the tree area transparent so the doll shows through behind the text.
        self._ensure_css(gtk)
        tree_container.add_css_class(DOWNLOADS_CSS_CLASS)

        if tree is not None:
            tree.add_css_class(DOWNLOADS_CSS_CLASS)

        state["overlay"] = overlay
        state["mount_parent"] = tree_parent
        state["main_child"] = tree_container
        state["tree"] = tree
        state["doll_box"] = doll_box
        state["doll"] = doll

        self.log("(%s) shown behind text (%dx%d, %s).", (pane["label"], width, height, position))

    def _teardown_behind_text(self, pane, gtk):

        state = self._panes[pane["key"]]

        self._stop_gif(state)

        overlay = state["overlay"]
        tree_container = state["main_child"]
        tree_parent = state["mount_parent"]
        tree = state["tree"]

        state["overlay"] = None
        state["content"] = None
        state["mount_parent"] = None
        state["doll_box"] = None
        state["doll"] = None
        state["main_child"] = None
        state["tree"] = None

        if overlay is None or tree_container is None or tree_parent is None:
            return

        # 1. Detach the tree from the overlay.
        try:
            if tree_container.get_parent() is overlay:
                overlay.remove_overlay(tree_container)
        except Exception:
            pass

        # 2. Detach the doll (main child).
        try:
            overlay.set_child(None)
        except Exception:
            pass

        # 3. Remove the empty overlay from the tree's parent box.
        try:
            if overlay.get_parent() is tree_parent:
                tree_parent.remove(overlay)
        except Exception:
            pass

        # 4. Restore the tree as the box's child.
        try:
            if tree_container.get_parent() is None:
                tree_parent.append(tree_container)
        except Exception:
            self.log("(%s): failed to restore the downloads tree.", (pane["label"],))

        # 5. Remove the transparency class.
        try:
            tree_container.remove_css_class(DOWNLOADS_CSS_CLASS)
        except Exception:
            pass

        if tree is not None:
            try:
                tree.remove_css_class(DOWNLOADS_CSS_CLASS)
            except Exception:
                pass

    def _poll(self):

        gtk = self._get_gtk()

        if not gtk:
            return True

        for pane in PANES:
            state = self._panes[pane["key"]]

            if state["signature"] != self._pane_signature(pane):
                self._refresh(pane, gtk)
                continue

            if state["overlay"] is not None:
                try:
                    if state["overlay"].get_parent() is not state["mount_parent"]:
                        self._refresh(pane, gtk)
                except Exception:
                    self._refresh(pane, gtk)

        return True

    # --- image rendering -------------------------------------------------------

    def _make_picture(self, gtk, path, width, height, state):

        Gtk = gtk["Gtk"]
        Gdk = gtk["Gdk"]
        GdkPixbuf = gtk["GdkPixbuf"]

        picture = Gtk.Picture(visible=True)
        picture.set_can_shrink(True)
        picture.set_size_request(width, height)

        state["gif_size"] = (width, height)

        extension = os.path.splitext(path)[1].lower()

        if extension == ".gif":
            try:
                animation = GdkPixbuf.PixbufAnimation.new_from_file(path)
                self._start_gif(picture, animation, state)
            except Exception as exc:
                self.log("Could not load GIF: %s", (exc,))
        else:
            # GdkPixbuf accepts a plain file path (Gdk.Texture.new_from_file
            # expects a Gio.File), and scaling here pins the doll to the exact
            # configured size instead of the image's native resolution.
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)

                if pixbuf is None:
                    self.log("Could not load image (unsupported or corrupt): %s", (path,))
                else:
                    pixbuf = self._scale_pixbuf(pixbuf, width, height, GdkPixbuf)
                    texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                    picture.set_paintable(texture)
            except Exception as exc:
                self.log("Could not load image: %s", (exc,))

        return picture

    @staticmethod
    def _scale_pixbuf(pixbuf, width, height, GdkPixbuf):
        if pixbuf.get_width() == width and pixbuf.get_height() == height:
            return pixbuf

        return pixbuf.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)

    def _start_gif(self, picture, animation, state):

        gtk = self._get_gtk()

        if not gtk:
            return

        GLib = gtk["GLib"]

        state["gif_picture"] = picture

        try:
            state["gif_iter"] = animation.get_iter(None)
        except Exception as exc:
            state["gif_iter"] = None
            self.log("GIF animation not started: %s", (exc,))
            return

        self._gif_show_frame(state)
        state["gif_timeout"] = GLib.timeout_add(self._gif_delay(state), self._gif_tick, state)

    def _gif_tick(self, state):

        if self._gtk is None or state["gif_iter"] is None:
            return False

        GLib = self._gtk["GLib"]

        try:
            try:
                state["gif_iter"].advance()
            except TypeError:
                state["gif_iter"].advance(GLib.get_real_time() // 1000)

            self._gif_show_frame(state)
            delay = self._gif_delay(state)
        except Exception as exc:
            self.log("GIF animation stopped: %s", (exc,))
            return False

        state["gif_timeout"] = GLib.timeout_add(delay, self._gif_tick, state)
        return False

    def _gif_show_frame(self, state):

        if self._gtk is None or state["gif_iter"] is None:
            return

        pixbuf = state["gif_iter"].get_pixbuf()
        picture = state["gif_picture"]

        if pixbuf is not None and picture is not None:
            Gdk = self._gtk["Gdk"]
            GdkPixbuf = self._gtk["GdkPixbuf"]

            gif_size = state.get("gif_size")

            if gif_size:
                width, height = gif_size

                if pixbuf.get_width() != width or pixbuf.get_height() != height:
                    pixbuf = pixbuf.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)

            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            picture.set_paintable(texture)
            picture.queue_draw()

    def _gif_delay(self, state):

        delay = state["gif_iter"].get_delay_time()

        if not delay or delay < 10:
            return 100

        return delay

    def _stop_gif(self, state):

        if state["gif_timeout"] is not None and self._gtk:
            try:
                self._gtk["GLib"].source_remove(state["gif_timeout"])
            except Exception:
                pass

        if state["gif_picture"] is not None:
            try:
                state["gif_picture"].set_paintable(None)
            except Exception:
                pass

        state["gif_timeout"] = None
        state["gif_iter"] = None
        state["gif_picture"] = None

    # --- css ---------------------------------------------------------------------

    def _ensure_css(self, gtk):

        if self._css_provider is not None:
            return

        Gtk = gtk["Gtk"]
        Gdk = gtk["Gdk"]

        try:
            provider = Gtk.CssProvider()
            css = (
                "treeview.%s, scrolledwindow.%s { background-color: transparent; }"
                % (DOWNLOADS_CSS_CLASS, DOWNLOADS_CSS_CLASS)
            )
            provider.load_from_data(css.encode("utf-8"))

            display = Gdk.Display.get_default()

            if display is not None:
                priority = getattr(Gtk, "STYLE_PROVIDER_PRIORITY_APPLICATION", 600)
                Gtk.StyleContext.add_provider_for_display(display, provider, priority)

            self._css_provider = provider
        except Exception as exc:
            self.log("could not install downloads CSS: %s", (exc,))

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

        self._ui = {}

    def _big_title(self, Gtk, text):

        label = Gtk.Label(xalign=0.0, visible=True)
        label.set_markup(f'<span size="x-large" weight="bold">{text}</span>')
        label.set_margin_top(10)
        label.set_margin_bottom(6)
        return label

    def _build_settings_window(self, Gtk):

        window = Gtk.Window(title="Page Doll Settings")
        window.set_default_size(540, 520)
        window.set_resizable(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=True)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        box.append(self._big_title(Gtk, "Page Doll"))

        for pane in PANES:
            prefix = pane["prefix"]
            ui = self._ui[pane["key"]] = {}

            box.append(self._big_title(Gtk, pane["label"]))

            ui["enabled"] = Gtk.Switch(active=bool(self.settings.get(prefix + "enabled", True)), visible=True)
            ui["enabled"].set_halign(Gtk.Align.START)
            box.append(self._row(Gtk, "Enabled", ui["enabled"]))

            ui["path"] = Gtk.Entry(visible=True, hexpand=True)
            ui["path"].set_text(self.settings.get(prefix + "image_path", ""))
            browse = Gtk.Button(label="Browse…", visible=True)
            browse.connect("clicked", self._on_browse, pane["key"])
            path_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, visible=True)
            path_row.append(ui["path"])
            path_row.append(browse)
            box.append(self._row(Gtk, "Image (.png / .gif)", path_row))

            ui["width"] = self._make_spin(
                Gtk, self._clamp_size(self.settings.get(prefix + "width", DEFAULT_WIDTH), MIN_SIZE, MAX_WIDTH), MAX_WIDTH
            )
            box.append(self._row(Gtk, "Width (px)", ui["width"]))

            ui["height"] = self._make_spin(
                Gtk, self._clamp_size(self.settings.get(prefix + "height", DEFAULT_HEIGHT), MIN_SIZE, MAX_HEIGHT), MAX_HEIGHT
            )
            box.append(self._row(Gtk, "Height (px)", ui["height"]))

            ui["position"] = Gtk.DropDown(visible=True)
            box.append(self._row(Gtk, "Position", ui["position"]))

        for pane in PANES:
            self._build_position_dropdown(pane["key"])

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

        scrolled = Gtk.ScrolledWindow(visible=True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(box)

        window.set_child(scrolled)
        self._settings_window = window

    def _row(self, Gtk, caption, control):

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, visible=True)

        label = Gtk.Label(label=caption, xalign=0.0, visible=True)
        label.set_halign(Gtk.Align.START)
        label.set_size_request(150, -1)

        row.append(label)
        row.append(control)

        return row

    def _make_spin(self, Gtk, value, maximum):

        adjustment = Gtk.Adjustment(
            value=float(value), lower=float(MIN_SIZE), upper=float(maximum), step_increment=1.0,
            page_increment=10.0, page_size=0.0
        )
        spin = Gtk.SpinButton(adjustment=adjustment, visible=True)
        spin.set_numeric(True)
        spin.set_digits(0)
        spin.set_value(value)
        return spin

    def _build_position_dropdown(self, pane_key):

        combo = self._ui.get(pane_key, {}).get("position")

        if combo is None:
            return

        pane = self._pane_by_key(pane_key)
        options = list(POSITION_ALIGN.keys())
        current = self.settings.get(pane["prefix"] + "position", "bottom-right")

        if current not in options:
            current = "bottom-right"

        combo.set_model(self._string_list_model(options))
        combo.set_selected(options.index(current))

    def _string_list_model(self, items):

        gtk = self._get_gtk()

        if gtk:
            Gtk = gtk["Gtk"]

            try:
                return Gtk.StringList.new(items)
            except Exception:
                pass

        return None

    def _on_browse(self, _button, pane_key):

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
                        entry = self._ui.get(pane_key, {}).get("path")

                        if path and entry is not None:
                            entry.set_text(path)
            finally:
                chooser.destroy()

        chooser.connect("response", on_response)
        chooser.show()

    def _on_apply(self, _button):

        for pane in PANES:
            prefix = pane["prefix"]
            ui = self._ui.get(pane["key"], {})

            if ui.get("path") is not None:
                self.settings[prefix + "image_path"] = ui["path"].get_text().strip()

            if ui.get("width") is not None:
                self.settings[prefix + "width"] = int(ui["width"].get_value())

            if ui.get("height") is not None:
                self.settings[prefix + "height"] = int(ui["height"].get_value())

            if ui.get("position") is not None:
                options = list(POSITION_ALIGN.keys())
                selected = ui["position"].get_selected()

                if 0 <= selected < len(options):
                    self.settings[prefix + "position"] = options[selected]

            if ui.get("enabled") is not None:
                self.settings[prefix + "enabled"] = ui["enabled"].get_active()

        gtk = self._get_gtk()

        if gtk:
            self._refresh_all(gtk)

        self.output("Page doll settings applied.")

    # --- command -----------------------------------------------------------------

    def pagedoll_command(self, args):

        action = (args.lstrip() or "settings").strip().lower()
        parts = action.split()

        pane_key = None

        if parts and parts[0] == "downloads":
            pane_key = "downloads"
            parts = parts[1:]
        elif parts and parts[0] in {"chat", "private", "privatechat"}:
            pane_key = "chat"
            parts = parts[1:]

        sub = parts[0] if parts else "settings"

        if sub in {"settings", "set"}:
            self._open_settings_window()
            return True

        if sub == "refresh":
            gtk = self._get_gtk()

            if gtk:
                self._refresh_all(gtk)

            self.output("Page doll refreshed.")
            return True

        if sub == "on":
            self._set_enabled(pane_key or "chat", True)
            return True

        if sub == "off":
            self._set_enabled(pane_key or "chat", False)
            return True

        self.output("Usage: /pagedoll [settings|on|off|refresh] | /pagedoll downloads [on|off|settings]")
        return True

    def _set_enabled(self, pane_key, value):

        pane = self._pane_by_key(pane_key)
        self.settings[pane["prefix"] + "enabled"] = value

        gtk = self._get_gtk()

        if gtk:
            self._refresh(pane, gtk)

        self.output("Page doll (%s) %s." % (pane["label"], "enabled" if value else "disabled"))
