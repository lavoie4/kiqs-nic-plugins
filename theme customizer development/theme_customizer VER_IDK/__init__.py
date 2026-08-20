"""Nicotine+ Theme Customizer plugin.

Adds a settings menu (Edit -> Plugins -> Theme Customizer -> Settings) that
lets the user customize the theme:

    * Background type: image (static picture), color (solid fill) or gif
      (animated, GTK 4 only).
    * Placement modes for image/gif backgrounds: fit, fill, tile.
    * A colored overlay with adjustable opacity, so the background stays
      readable behind the sidebar, chat, log pane and header/search bar.

The static background and overlay are applied with a GTK CSS provider, so they
work on both the GTK 3 and GTK 4 builds. Animated GIFs use a Gtk.Picture
background layer and therefore require GTK 4.
"""

import os
from pathlib import Path

from pynicotine.pluginsystem import BasePlugin


CSS_CLASS_BG = "nplus-theme-background"
CSS_CLASS_TRANSPARENT = "nplus-theme-background-transparent"
CSS_CLASS_OVERLAY = "nplus-theme-background-overlay"
CSS_CLASS_HEADER = "nplus-theme-header-overlay"

POLL_INTERVAL_MS = 1000

DEFAULT_COLOR = "#1a1a2e"
DEFAULT_OVERLAY_COLOR = "#000000"
DEFAULT_OVERLAY_OPACITY = 0.45
DEFAULT_HEADER_OVERLAY_OPACITY = 0.6
DEFAULT_ACCENT_COLOR = "#5B3368"
DEFAULT_BACKGROUND_EFFECT = "none"
DEFAULT_BLUR_STRENGTH = 8
DEFAULT_OVERLAY_TYPE = "color"
DEFAULT_USERLIST_WIDTH = 180


class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.settings = {
            "enabled": True,
            "background_type": "image",
            "image_path": "",
            "color": DEFAULT_COLOR,
            "mode": "fill",
            "overlay_color": DEFAULT_OVERLAY_COLOR,
            "overlay_opacity": DEFAULT_OVERLAY_OPACITY,
            "header_overlay_opacity": DEFAULT_HEADER_OVERLAY_OPACITY,
            "accent_color": DEFAULT_ACCENT_COLOR,
            "background_effect": DEFAULT_BACKGROUND_EFFECT,
            "blur_strength": DEFAULT_BLUR_STRENGTH,
            "overlay_type": DEFAULT_OVERLAY_TYPE,
            "overlay_image_path": "",
            "header_image_path": "",
            "userlist_width": DEFAULT_USERLIST_WIDTH,
            "userlist_resizable": False,
            "overlay_buddy": True,
            "overlay_chat": True,
            "overlay_browse": True,
        }
        self.metasettings = {
            "enabled": {
                "description": "Enable custom background",
                "type": "bool",
            },
            "background_type": {
                "description": "Background type",
                "type": "dropdown",
                "options": ["image", "color", "gif", "webm"],
            },
            "image_path": {
                "description": "Background image (image/gif)",
                "type": "file",
                "chooser": "image",
            },
            "color": {
                "description": "Background color (color type, #RRGGBB)",
                "type": "str",
            },
            "mode": {
                "description": "Background mode (image/gif)",
                "type": "dropdown",
                "options": ["fit", "fill", "tile"],
            },
            "overlay_color": {
                "description": "Overlay color (#RRGGBB)",
                "type": "str",
            },
            "overlay_opacity": {
                "description": "Overlay opacity (0 = none, 1 = solid)",
                "type": "float",
                "minimum": 0.0,
                "maximum": 1.0,
                "stepsize": 0.05,
            },
            "header_overlay_opacity": {
                "description": "Header/title bar overlay opacity (0 = none, 1 = solid)",
                "type": "float",
                "minimum": 0.0,
                "maximum": 1.0,
                "stepsize": 0.05,
            },
            "accent_color": {
                "description": "Accent color (selections, switches, links, buttons)",
                "type": "str",
            },
            "background_effect": {
                "description": "Background effect (none/blur/grayscale/sepia/saturate/hue-rotate/invert)",
                "type": "dropdown",
                "options": ["none", "blur", "grayscale", "sepia", "saturate", "hue-rotate", "invert"],
            },
            "blur_strength": {
                "description": "Blur strength in pixels (blur effect only)",
                "type": "integer",
                "minimum": 0,
                "maximum": 50,
            },
            "overlay_type": {
                "description": "Overlay type (color tint or image)",
                "type": "dropdown",
                "options": ["color", "image"],
            },
            "overlay_image_path": {
                "description": "Overlay image (overlay type = image)",
                "type": "file",
                "chooser": "image",
            },
            "header_image_path": {
                "description": "Title bar background image",
                "type": "file",
                "chooser": "image",
            },
            "userlist_width": {
                "description": "Room user list width in pixels",
                "type": "integer",
                "minimum": 120,
                "maximum": 400,
            },
            "userlist_resizable": {
                "description": "Make the room user list drag-resizable (experimental)",
                "type": "bool",
            },
            "overlay_buddy": {
                "description": "Apply overlay tint to the buddy list",
                "type": "bool",
            },
            "overlay_chat": {
                "description": "Apply overlay tint to chat rooms",
                "type": "bool",
            },
            "overlay_browse": {
                "description": "Apply overlay tint to browse/user info",
                "type": "bool",
            },
        }
        self.commands = {
            "theme": {
                "callback": self.theme_command,
                "description": "Apply, refresh or disable the custom theme background, or open the settings window",
                "parameters": ["[on|off|refresh|settings]"],
                "group": "Theme Customizer",
            },
        }

        self._gtk = None           # cached dict of gi modules, or False when unavailable
        self._provider = None      # active Gtk.CssProvider
        self._tagged = []          # [(widget, css_class), ...] widgets we currently style
        self._signature = None     # last successfully applied settings signature
        self._poll_id = None       # GLib poll source id

        # widget-based background state (animated GIF/WebM path)
        self._window = None
        self._root = None
        self._overlay = None
        self._gif_timeout = None
        self._gif_picture = None
        self._gif_animation = None
        self._gif_iter = None
        self._webm_stream = None

        # custom settings dialog state
        self._settings_window = None
        self._settings_widgets = {}
        self._chooser_key = "image_path"

    # --- lifecycle -----------------------------------------------------------

    def init(self):
        """Settings have loaded; apply the theme and start watching for changes."""

        self._apply_theme()

        gtk = self._get_gtk()

        if gtk:
            self._poll_id = gtk["GLib"].timeout_add(POLL_INTERVAL_MS, self._poll_settings)

    def disable(self):
        """Plugin is unloading; restore the default appearance."""

        self._close_settings_window()

        if self._poll_id is not None:
            gtk = self._get_gtk()

            if gtk:
                gtk["GLib"].source_remove(self._poll_id)

            self._poll_id = None

        self._clear_theme()

    # --- command -------------------------------------------------------------

    def theme_command(self, args, **_unused):

        action = (args or "").strip().lower()

        if action in {"", "settings", "gui", "options"}:
            return self._open_settings()

        if action == "on":
            self.settings["enabled"] = True
        elif action == "off":
            self.settings["enabled"] = False
        elif action in {"refresh", "apply"}:
            pass
        else:
            self.output("Usage: /theme [on|off|refresh|settings]")
            return False

        self._apply_theme()

        if self.settings["enabled"]:
            self.output("Theme background enabled (%s)" % self.settings.get("background_type", "image"))
        else:
            self.output("Theme background disabled")

        return True

    # --- settings watcher ----------------------------------------------------

    def _current_signature(self):
        return (
            bool(self.settings.get("enabled", True)),
            self.settings.get("background_type", "image") or "image",
            self.settings.get("image_path", "") or "",
            self.settings.get("color", DEFAULT_COLOR) or "",
            self.settings.get("mode", "fill") or "fill",
            self.settings.get("overlay_color", DEFAULT_OVERLAY_COLOR) or "",
            float(self.settings.get("overlay_opacity", DEFAULT_OVERLAY_OPACITY) or 0.0),
            float(self.settings.get("header_overlay_opacity", DEFAULT_HEADER_OVERLAY_OPACITY) or 0.0),
            self.settings.get("accent_color", DEFAULT_ACCENT_COLOR) or "",
            self.settings.get("background_effect", DEFAULT_BACKGROUND_EFFECT) or "none",
            int(self.settings.get("blur_strength", DEFAULT_BLUR_STRENGTH) or 0),
            self.settings.get("overlay_type", DEFAULT_OVERLAY_TYPE) or "color",
            self.settings.get("overlay_image_path", "") or "",
            self.settings.get("header_image_path", "") or "",
            int(self.settings.get("userlist_width", DEFAULT_USERLIST_WIDTH) or 0),
            bool(self.settings.get("userlist_resizable", False)),
            bool(self.settings.get("overlay_buddy", True)),
            bool(self.settings.get("overlay_chat", True)),
            bool(self.settings.get("overlay_browse", True)),
        )

    def _poll_settings(self):

        signature = self._current_signature()

        if signature != self._signature:
            self._apply_theme()
        else:
            # Keep newly-created widgets (opened profiles, new rooms) tagged.
            self._refresh_tagging()

        return True

    def _refresh_tagging(self):

        if self._provider is None or self._window is None:
            return

        gtk = self._get_gtk()

        if not gtk:
            return

        self._tag_assets(gtk)
        self._tag_header(gtk)
        self._apply_userlist_width(gtk)

    # --- GTK access ----------------------------------------------------------

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
                # Headless mode: no window to theme.
                self._gtk = False
                return False
        except Exception:
            pass

        self._gtk = {"Gdk": Gdk, "GLib": GLib, "Gtk": Gtk}
        return self._gtk

    # --- theme application ----------------------------------------------------

    def _apply_theme(self):

        gtk = self._get_gtk()

        if not gtk:
            self._signature = None
            return False

        self._clear_theme(gtk)

        signature = self._current_signature()

        enabled = bool(self.settings.get("enabled", True))
        background_type = self.settings.get("background_type", "image") or "image"
        image_path = self._clean_path(self.settings.get("image_path", ""))

        if not enabled:
            self._signature = signature
            return True

        if background_type in {"image", "gif", "webm"}:
            if not image_path:
                self._signature = signature
                return True

            expanded = os.path.expanduser(image_path)

            if not os.path.isfile(expanded):
                self.log("Background image not found: %s", (expanded,))
                self._signature = signature
                return True

        window = self._find_main_window(gtk["Gtk"])

        if window is None:
            # Main window not available yet; keep retrying from the poll timer.
            self._signature = None
            return False

        self._window = window
        self._root = self._get_root(window)

        # Auto-detect animated media selected while the type is still "image".
        if background_type == "image" and image_path:
            lower = image_path.lower()

            if lower.endswith(".gif"):
                background_type = "gif"
            elif lower.endswith((".webm", ".mp4", ".ogv", ".mkv")):
                background_type = "webm"

        config = self._build_config()
        config["type"] = background_type
        self._add_provider(gtk, self._build_css(config))

        if background_type == "gif":
            self._setup_gif_background(gtk, window, config)
        elif background_type == "webm":
            self._setup_webm_background(gtk, window, config)
        else:
            self._tag_background(gtk, config)

        self._tag_assets(gtk)
        self._tag_header(gtk)
        self._apply_userlist_width(gtk)

        self._signature = signature
        self.log("Applied theme background (%s)", (background_type,))
        return True

    def _build_config(self):

        background_type = self.settings.get("background_type", "image") or "image"
        image_path = self._clean_path(self.settings.get("image_path", ""))
        color = self.settings.get("color", DEFAULT_COLOR) or ""
        mode = self.settings.get("mode", "fill") or "fill"
        overlay_color = self.settings.get("overlay_color", DEFAULT_OVERLAY_COLOR) or ""
        overlay_opacity = float(self.settings.get("overlay_opacity", DEFAULT_OVERLAY_OPACITY) or 0.0)
        header_overlay_opacity = float(self.settings.get("header_overlay_opacity", DEFAULT_HEADER_OVERLAY_OPACITY) or 0.0)
        accent_color = self.settings.get("accent_color", DEFAULT_ACCENT_COLOR) or ""

        config = {
            "type": background_type,
            "mode": mode,
            "overlay_color": overlay_color,
            "overlay_opacity": overlay_opacity,
            "header_overlay_opacity": header_overlay_opacity,
            "accent_color": self._parse_hex_color(accent_color, DEFAULT_ACCENT_COLOR),
            "background_effect": self.settings.get("background_effect", DEFAULT_BACKGROUND_EFFECT) or "none",
            "blur_strength": int(self.settings.get("blur_strength", DEFAULT_BLUR_STRENGTH) or 0),
            "overlay_type": self.settings.get("overlay_type", DEFAULT_OVERLAY_TYPE) or "color",
            "overlay_image_path": self._clean_path(self.settings.get("overlay_image_path", "")),
            "header_image_path": self._clean_path(self.settings.get("header_image_path", "")),
        }

        if background_type == "color":
            config["bg_color"] = self._parse_hex_color(color, DEFAULT_COLOR)
        else:
            config["image_path"] = os.path.expanduser(image_path)
            config["uri"] = self._path_to_uri(image_path)

        if config["overlay_image_path"]:
            config["overlay_uri"] = self._path_to_uri(config["overlay_image_path"])

        if config["header_image_path"]:
            config["header_uri"] = self._path_to_uri(config["header_image_path"])

        return config

    def _clear_theme(self, gtk=None):

        if gtk is None:
            gtk = self._get_gtk()

            if not gtk:
                self._reset_gui_state()
                return

        Gtk = gtk["Gtk"]

        self._stop_gif_animation()
        self._stop_webm()

        # Restore the original window content if we wrapped it in an overlay.
        if self._overlay is not None and self._window is not None and self._root is not None:
            try:
                if Gtk.get_major_version() >= 4:
                    self._window.set_child(None)

                    try:
                        self._overlay.remove_overlay(self._root)
                    except Exception:
                        pass

                    self._window.set_child(self._root)
                else:
                    self._window.remove(self._overlay)
                    self._window.add(self._root)
            except Exception:
                pass

            try:
                self._overlay.destroy()
            except Exception:
                pass

        # Remove CSS classes from every widget we styled.
        for widget, css_class in self._tagged:
            try:
                self._remove_class(Gtk, widget, css_class)
            except Exception:
                pass

        self._tagged = []

        if self._provider is not None:
            self._remove_provider(gtk)
            self._provider = None

        self._window = None
        self._root = None
        self._overlay = None

    def _reset_gui_state(self):

        self._window = None
        self._root = None
        self._overlay = None
        self._tagged = []
        self._provider = None
        self._gif_timeout = None
        self._gif_picture = None
        self._gif_animation = None
        self._gif_iter = None
        self._webm_stream = None

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

    def _get_root(self, window):

        try:
            return window.get_child()
        except Exception:
            return None

    # --- tagging -------------------------------------------------------------

    def _tag_background(self, gtk, config):
        """Paint the CSS background (image or solid color) on window + root."""

        Gtk = gtk["Gtk"]

        for widget in (self._window, self._root):
            if widget is None:
                continue

            try:
                self._add_class(Gtk, widget, CSS_CLASS_BG)
                self._tagged.append((widget, CSS_CLASS_BG))
            except Exception:
                pass

    def _tag_assets(self, gtk):
        """Make structural containers transparent and tint content surfaces."""

        Gtk = gtk["Gtk"]
        root = self._root

        if root is None:
            return

        container_types = self._container_types(Gtk)
        surface_types = self._surface_types(Gtk)
        area_roots = self._area_roots()

        for widget in self._walk(Gtk, root):
            try:
                if isinstance(widget, surface_types):
                    area = self._area_of(widget, area_roots)

                    if area and not self.settings.get(f"overlay_{area}", True):
                        self._tag_once(Gtk, widget, CSS_CLASS_TRANSPARENT)
                    else:
                        self._tag_once(Gtk, widget, CSS_CLASS_OVERLAY)
                elif isinstance(widget, container_types):
                    self._tag_once(Gtk, widget, CSS_CLASS_TRANSPARENT)
            except Exception:
                pass

    def _tag_header(self, gtk):
        """Theme the window title bar (GTK 4 header bar)."""

        Gtk = gtk["Gtk"]

        if self._window is None:
            return

        titlebar = self._get_titlebar(Gtk, self._window)

        if titlebar is None:
            return

        self._tag_once(Gtk, titlebar, CSS_CLASS_HEADER)

    def _get_titlebar(self, Gtk, window):

        try:
            if Gtk.get_major_version() >= 4:
                return window.get_titlebar()
        except Exception:
            pass

        return None

    def _area_roots(self):

        roots = {"buddy": [], "chat": [], "browse": []}

        try:
            window = getattr(self.core, "window", None)
        except Exception:
            window = None

        if window is None:
            return roots

        mapping = (
            ("buddy", ("buddy_list_container", "chatrooms_buddy_list_container")),
            ("chat", ("chatrooms_container", "chatrooms_content")),
            ("browse", ("userbrowse_page", "userbrowse_content", "userinfo_page", "userinfo_content")),
        )

        for area, attrs in mapping:
            for attr in attrs:
                try:
                    widget = getattr(window, attr, None)
                except Exception:
                    widget = None

                if widget is not None:
                    roots[area].append(widget)

        return roots

    def _area_of(self, widget, roots):

        for area, root_widgets in roots.items():
            for root in root_widgets:
                try:
                    if root is widget or widget.is_ancestor(root):
                        return area
                except Exception:
                    continue

        return None

    def _apply_userlist_width(self, gtk):

        Gtk = gtk["Gtk"]
        width = int(self.settings.get("userlist_width", DEFAULT_USERLIST_WIDTH) or 0)
        resizable = bool(self.settings.get("userlist_resizable", False))

        for container in self._find_userlist_containers(Gtk):
            if resizable:
                self._ensure_userlist_paned(Gtk, container, width)
            else:
                try:
                    container.set_width_request(width)
                except Exception:
                    pass

    def _ensure_userlist_paned(self, Gtk, users_container, width):

        try:
            parent = users_container.get_parent()
            chat_paned = users_container.get_prev_sibling()
        except Exception:
            return

        # The room user list sits in a plain Gtk.Box next to a Gtk.Paned (the
        # chat view). After conversion its parent is a Gtk.Paned, so these
        # checks also keep the operation idempotent.
        if parent is None or chat_paned is None:
            return

        if not isinstance(parent, Gtk.Box) or not isinstance(chat_paned, Gtk.Paned):
            return

        try:
            grandparent = parent.get_parent()
        except Exception:
            return

        if grandparent is None or not isinstance(grandparent, Gtk.Box):
            return

        try:
            users_container.set_width_request(width)

            paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)

            if Gtk.get_major_version() >= 4:
                parent.remove(chat_paned)
                parent.remove(users_container)
                grandparent.remove(parent)

                paned.set_start_child(chat_paned)
                paned.set_end_child(users_container)
                paned.set_resize_start_child(True)
                paned.set_shrink_start_child(False)
                paned.set_resize_end_child(False)
                paned.set_shrink_end_child(True)

                grandparent.append(paned)
            else:
                parent.remove(chat_paned)
                parent.remove(users_container)
                grandparent.remove(parent)

                paned.pack1(chat_paned, resize=True, shrink=False)
                paned.pack2(users_container, resize=False, shrink=True)

                grandparent.add(paned)

            paned.set_visible(True)

            try:
                total = grandparent.get_allocated_width()
            except Exception:
                try:
                    total = grandparent.get_width()
                except Exception:
                    total = 0

            if total and total > width:
                paned.set_position(total - width)

            self.log("Made a room user list drag-resizable")
        except Exception as exc:
            self.log("User list resize conversion failed: %s", (exc,))

    def _find_userlist_containers(self, Gtk):

        containers = []

        try:
            window = getattr(self.core, "window", None)
        except Exception:
            window = None

        roots = []

        if window is not None:
            for attr in ("chatrooms_content", "chatrooms_container"):
                try:
                    widget = getattr(window, attr, None)
                except Exception:
                    widget = None

                if widget is not None:
                    roots.append(widget)

        seen = set()

        for root in roots:
            for widget in self._walk(Gtk, root):
                if id(widget) in seen:
                    continue

                seen.add(id(widget))

                try:
                    if (isinstance(widget, Gtk.Box)
                            and not widget.get_hexpand()
                            and widget.get_width_request() > 0):
                        containers.append(widget)
                except Exception:
                    continue

        return containers

    # --- GIF background (GTK 4) ----------------------------------------------

    def _setup_gif_background(self, gtk, window, config):

        Gtk = gtk["Gtk"]
        root = self._root

        if root is None or Gtk.get_major_version() < 4:
            # GTK 3 (or no root): fall back to a static CSS background.
            self._tag_background(gtk, config)
            return

        try:
            from gi.repository import GdkPixbuf  # pylint: disable=import-error

            animation = GdkPixbuf.PixbufAnimation.new_from_file(config["image_path"])
        except Exception:
            self._tag_background(gtk, config)
            return

        try:
            picture = Gtk.Picture(visible=True, can_shrink=False)
            picture.set_content_fit(self._content_fit(config["mode"]))

            overlay = Gtk.Overlay(visible=True)
            overlay.set_child(picture)

            window.set_child(None)          # detach the original content
            overlay.add_overlay(root)       # put content on top of the picture
            window.set_child(overlay)

            self._overlay = overlay

            # The content root must be transparent so the picture shows through.
            self._add_class(Gtk, root, CSS_CLASS_TRANSPARENT)
            self._tagged.append((root, CSS_CLASS_TRANSPARENT))

            self._start_gif_animation(gtk, picture, animation)

        except Exception:
            # Restore and fall back to a static CSS background.
            try:
                window.set_child(None)
                window.set_child(root)
            except Exception:
                pass

            self._tag_background(gtk, config)

    def _setup_webm_background(self, gtk, window, config):

        Gtk = gtk["Gtk"]
        root = self._root

        if root is None or Gtk.get_major_version() < 4:
            # GTK 3 (or no root): fall back to a static CSS background.
            self._tag_background(gtk, config)
            return

        try:
            media = Gtk.MediaFile.new_for_filename(config["image_path"])
            video = Gtk.Video(visible=True)
            video.set_media_stream(media)
        except Exception as exc:
            self.log("WebM background not available: %s", (exc,))
            self._tag_background(gtk, config)
            return

        try:
            overlay = Gtk.Overlay(visible=True)
            overlay.set_child(video)

            window.set_child(None)          # detach the original content
            overlay.add_overlay(root)       # put content on top of the video
            window.set_child(overlay)

            self._overlay = overlay
            self._webm_stream = media

            # The content root must be transparent so the video shows through.
            self._add_class(Gtk, root, CSS_CLASS_TRANSPARENT)
            self._tagged.append((root, CSS_CLASS_TRANSPARENT))

            media.set_loop(True)
            media.play()
            self.log("WebM background started")

        except Exception as exc:
            self.log("WebM background setup failed: %s", (exc,))

            try:
                window.set_child(None)
                window.set_child(root)
            except Exception:
                pass

            self._webm_stream = None
            self._tag_background(gtk, config)

    def _content_fit(self, mode):

        Gtk = self._gtk["Gtk"]

        if mode == "fit":
            return Gtk.ContentFit.CONTAIN

        # fill and tile both use cover (tiling an animation isn't practical).
        return Gtk.ContentFit.COVER

    def _start_gif_animation(self, gtk, picture, animation):

        GLib = gtk["GLib"]

        self._gif_picture = picture
        self._gif_animation = animation

        try:
            self._gif_iter = animation.get_iter(None)
        except Exception as exc:
            self._gif_iter = None
            self.log("GIF animation not started: %s", (exc,))
            return

        # Show the first frame immediately, then schedule the next tick.
        self._gif_show_current_frame()
        self._gif_timeout = GLib.timeout_add(self._gif_current_delay(), self._gif_tick)
        self.log("GIF animation started")

    def _gif_tick(self):

        if self._gtk is None or self._gif_picture is None or self._gif_iter is None:
            return False

        GLib = self._gtk["GLib"]

        try:
            # Advance to the next frame. The PyGObject binding accepts a
            # no-argument advance() (using the current wall-clock time); fall
            # back to an explicit millisecond value on older bindings.
            try:
                self._gif_iter.advance()
            except TypeError:
                self._gif_iter.advance(GLib.get_real_time() // 1000)

            self._gif_show_current_frame()
            delay = self._gif_current_delay()
        except Exception as exc:
            self.log("GIF animation stopped: %s", (exc,))
            return False

        self._gif_timeout = GLib.timeout_add(delay, self._gif_tick)
        return False

    def _gif_show_current_frame(self):

        Gdk = self._gtk["Gdk"]
        pixbuf = self._gif_iter.get_pixbuf()

        if pixbuf is not None:
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self._gif_picture.set_paintable(texture)
            self._gif_picture.queue_draw()

    def _gif_current_delay(self):

        delay = self._gif_iter.get_delay_time()

        if not delay or delay < 10:
            return 100

        return delay

    def _stop_gif_animation(self):

        if self._gif_timeout is not None and self._gtk:
            try:
                self._gtk["GLib"].source_remove(self._gif_timeout)
            except Exception:
                pass

        self._gif_timeout = None
        self._gif_picture = None
        self._gif_animation = None
        self._gif_iter = None

    def _stop_webm(self):

        if self._webm_stream is not None:
            try:
                self._webm_stream.set_playing(False)
            except Exception:
                pass

        self._webm_stream = None

    # --- settings dialog -------------------------------------------------------

    def _close_settings_window(self):

        if self._settings_window is not None:
            try:
                self._settings_window.destroy()
            except Exception:
                pass

        self._settings_window = None
        self._settings_widgets = {}

    def _open_settings(self):

        gtk = self._get_gtk()

        if not gtk:
            self.output("Theme settings require a graphical session.")
            return False

        Gtk = gtk["Gtk"]

        if Gtk.get_major_version() < 4:
            self.output("Theme settings window requires GTK 4; use Edit > Plugins > Settings instead.")
            return False

        if self._settings_window is not None:
            try:
                self._settings_window.present()
            except Exception:
                self._close_settings_window()
            else:
                return True

        self._build_settings_window(gtk)
        return True

    def _build_settings_window(self, gtk):

        Gtk = gtk["Gtk"]

        main_window = self._find_main_window(Gtk)

        window = Gtk.Window(title="Theme Customizer Settings")
        window.set_default_size(560, 420)

        if main_window is not None:
            try:
                window.set_transient_for(main_window)
            except Exception:
                pass

        self._settings_window = window
        self._settings_widgets = {}

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        window.set_child(content)

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        stack.add_titled(self._build_background_page(Gtk, gtk["Gdk"]), "background", "Background")
        stack.add_titled(self._build_overlay_page(Gtk, gtk["Gdk"]), "overlay", "Overlay")
        stack.add_titled(self._build_titlebar_page(Gtk, gtk["Gdk"]), "titlebar", "Title bar")
        stack.add_titled(self._build_accent_page(Gtk, gtk["Gdk"]), "accent", "Accent")
        stack.add_titled(self._build_layout_page(Gtk, gtk["Gdk"]), "layout", "Layout")

        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(stack)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_size_request(170, -1)
        sidebar_scroll.set_child(sidebar)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.set_hexpand(True)
        body.set_vexpand(True)
        body.append(sidebar_scroll)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        body.append(stack)
        content.append(body)

        action_bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
            margin_top=12, margin_bottom=12, margin_start=12, margin_end=12
        )

        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", self._on_settings_cancel)

        apply_button = Gtk.Button(label="Apply")
        apply_button.connect("clicked", self._on_settings_apply)

        ok_button = Gtk.Button(label="OK")
        ok_button.add_css_class("suggested-action")
        ok_button.connect("clicked", self._on_settings_ok)

        action_bar.append(cancel_button)
        action_bar.append(Gtk.Label(hexpand=True))
        action_bar.append(apply_button)
        action_bar.append(ok_button)
        content.append(action_bar)

        window.connect("close-request", self._on_settings_closed)
        window.present()

    def _build_background_page(self, Gtk, Gdk):

        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=18, margin_bottom=18, margin_start=18, margin_end=18
        )

        enable_switch = Gtk.Switch(active=bool(self.settings.get("enabled", True)), valign=Gtk.Align.CENTER)
        self._add_row(Gtk, page, "Enable custom background", enable_switch)

        type_dropdown = self._make_dropdown(
            Gtk, ["image", "color", "gif", "webm"], self.settings.get("background_type", "image")
        )
        self._add_row(Gtk, page, "Background type", type_dropdown)

        self._add_path_row(Gtk, page, "Background image", self.settings.get("image_path", ""), "image_path")

        bg_color_button = self._add_color_control(
            Gtk, Gdk, page, "Background color", self.settings.get("color", DEFAULT_COLOR), "bg_color"
        )

        mode_dropdown = self._make_dropdown(
            Gtk, ["fit", "fill", "tile"], self.settings.get("mode", "fill")
        )
        self._add_row(Gtk, page, "Background mode", mode_dropdown)

        effect_dropdown = self._make_dropdown(
            Gtk, ["none", "blur", "grayscale", "sepia", "saturate", "hue-rotate", "invert"],
            self.settings.get("background_effect", DEFAULT_BACKGROUND_EFFECT)
        )
        self._add_row(Gtk, page, "Background effect", effect_dropdown)

        blur_control = self._make_blur_control(Gtk, int(self.settings.get("blur_strength", DEFAULT_BLUR_STRENGTH)))
        self._add_row(Gtk, page, "Blur strength (px)", blur_control)

        self._settings_widgets["enable_switch"] = enable_switch
        self._settings_widgets["type_dropdown"] = type_dropdown
        self._settings_widgets["mode_dropdown"] = mode_dropdown
        self._settings_widgets["effect_dropdown"] = effect_dropdown

        return page

    def _build_overlay_page(self, Gtk, Gdk):

        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=18, margin_bottom=18, margin_start=18, margin_end=18
        )

        overlay_type_dropdown = self._make_dropdown(
            Gtk, ["color", "image"], self.settings.get("overlay_type", DEFAULT_OVERLAY_TYPE)
        )
        self._add_row(Gtk, page, "Overlay type", overlay_type_dropdown)

        overlay_color_button = self._add_color_control(
            Gtk, Gdk, page, "Overlay color", self.settings.get("overlay_color", DEFAULT_OVERLAY_COLOR), "overlay_color"
        )

        self._add_path_row(Gtk, page, "Overlay image", self.settings.get("overlay_image_path", ""), "overlay_image_path")

        opacity_box = self._make_opacity_control(
            Gtk, float(self.settings.get("overlay_opacity", DEFAULT_OVERLAY_OPACITY)), "opacity_scale"
        )
        self._add_row(Gtk, page, "Overlay opacity", opacity_box)

        self._settings_widgets["overlay_type_dropdown"] = overlay_type_dropdown

        return page

    def _build_titlebar_page(self, Gtk, Gdk):

        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=18, margin_bottom=18, margin_start=18, margin_end=18
        )

        self._add_path_row(Gtk, page, "Title bar image", self.settings.get("header_image_path", ""), "header_image_path")

        header_box = self._make_opacity_control(
            Gtk, float(self.settings.get("header_overlay_opacity", DEFAULT_HEADER_OVERLAY_OPACITY)), "header_scale"
        )
        self._add_row(Gtk, page, "Title bar opacity", header_box)

        hint = Gtk.Label(
            label="The title bar is only themeable on the GTK 4 build.",
            xalign=0, wrap=True
        )
        hint.add_css_class("dim-label")
        page.append(hint)

        return page

    def _build_layout_page(self, Gtk, Gdk):

        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=18, margin_bottom=18, margin_start=18, margin_end=18
        )

        width_control = self._make_userlist_width_control(
            Gtk, int(self.settings.get("userlist_width", DEFAULT_USERLIST_WIDTH))
        )
        self._add_row(Gtk, page, "Room user list width (px)", width_control)

        self._make_switch_row(Gtk, page, "Drag-resizable user list (experimental)", self.settings.get("userlist_resizable", False), "userlist_resizable")

        self._make_switch_row(Gtk, page, "Tint buddy list", self.settings.get("overlay_buddy", True), "overlay_buddy")
        self._make_switch_row(Gtk, page, "Tint chat rooms", self.settings.get("overlay_chat", True), "overlay_chat")
        self._make_switch_row(Gtk, page, "Tint browse / user info", self.settings.get("overlay_browse", True), "overlay_browse")

        hint = Gtk.Label(
            label="The width slider sets the initial/minimum width. "
                  "The drag-resizable option turns the user list into a draggable pane "
                  "(turning it off again needs a Nicotine+ restart to revert).",
            xalign=0, wrap=True
        )
        hint.add_css_class("dim-label")
        page.append(hint)

        return page

    def _build_accent_page(self, Gtk, Gdk):

        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=18, margin_bottom=18, margin_start=18, margin_end=18
        )

        accent_button = self._add_color_control(
            Gtk, Gdk, page, "Accent color", self.settings.get("accent_color", DEFAULT_ACCENT_COLOR), "accent"
        )

        hint = Gtk.Label(
            label="Used for selections, switches, links and highlighted buttons.",
            xalign=0, wrap=True
        )
        hint.add_css_class("dim-label")
        page.append(hint)

        return page

    def _add_row(self, Gtk, container, label_text, control):

        row = Gtk.Box(spacing=12)
        label = Gtk.Label(label=label_text, xalign=0, hexpand=True, wrap=True)
        row.append(label)
        row.append(control)
        container.append(row)
        return row

    def _add_path_row(self, Gtk, page, label, initial, key):

        box = Gtk.Box(spacing=8)

        entry = Gtk.Entry(hexpand=True)
        entry.set_placeholder_text("Path to image or video…")
        entry.set_text(initial)

        browse_button = Gtk.Button(label="Browse…")
        browse_button.connect("clicked", lambda _b, k=key: self._on_choose_path(k))

        box.append(entry)
        box.append(browse_button)
        self._add_row(Gtk, page, label, box)

        entry.connect("activate", lambda e, k=key: self._set_path_value(k, e.get_text()))

        focus_controller = Gtk.EventControllerFocus.new()
        entry.add_controller(focus_controller)
        focus_controller.connect("leave", lambda _controller, e=entry, k=key: self._set_path_value(k, e.get_text()))

        self._settings_widgets[key] = self._clean_path(initial)
        self._settings_widgets[f"{key}_entry"] = entry

        return box

    def _make_switch_row(self, Gtk, page, label, active, key):

        switch = Gtk.Switch(active=bool(active), valign=Gtk.Align.CENTER)
        self._add_row(Gtk, page, label, switch)
        self._settings_widgets[key] = switch
        return switch

    def _make_dropdown(self, Gtk, options, selected):

        model = Gtk.StringList.new(options)
        dropdown = Gtk.DropDown.new(model)

        try:
            index = options.index(selected)
        except ValueError:
            index = 0

        dropdown.set_selected(index)
        return dropdown

    def _set_color_dialog(self, Gtk, button):

        try:
            button.set_dialog(Gtk.ColorDialog())
        except AttributeError:
            try:
                button.set_use_alpha(True)
            except Exception:
                pass

    def _add_color_control(self, Gtk, Gdk, page, label, initial_hex, key):

        box = Gtk.Box(spacing=8)

        button = Gtk.ColorButton()
        self._set_color_dialog(Gtk, button)
        button.set_rgba(self._parse_rgba(Gdk, initial_hex))

        entry = Gtk.Entry(hexpand=True, width_chars=9)
        entry.set_placeholder_text("#RRGGBB")
        entry.set_text(self._normalize_hex(initial_hex) or initial_hex)

        button.connect(
            "notify::rgba",
            lambda b, _pspec, e=entry: e.set_text(self._rgba_to_hex(b.get_rgba()))
        )
        entry.connect("activate", lambda e, b=button: self._apply_entry_hex(e, b))

        focus_controller = Gtk.EventControllerFocus.new()
        entry.add_controller(focus_controller)
        focus_controller.connect("leave", lambda _controller, e=entry, b=button: self._apply_entry_hex(e, b))

        box.append(button)
        box.append(entry)
        self._add_row(Gtk, page, label, box)

        self._settings_widgets[f"{key}_button"] = button
        self._settings_widgets[f"{key}_entry"] = entry

        return button

    def _apply_entry_hex(self, entry, button):

        hex_value = self._normalize_hex(entry.get_text())
        gtk = self._get_gtk()

        if hex_value and gtk:
            button.set_rgba(self._parse_rgba(gtk["Gdk"], hex_value))
        else:
            entry.set_text(self._rgba_to_hex(button.get_rgba()))

    def _normalize_hex(self, value):

        v = (value or "").strip().lstrip("#")

        if len(v) == 3:
            v = "".join(char * 2 for char in v)

        if len(v) != 6:
            return None

        try:
            int(v, 16)
        except (ValueError, TypeError):
            return None

        return "#" + v.lower()

    def _make_opacity_control(self, Gtk, value, key):

        box = Gtk.Box(spacing=8)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
        scale.set_digits(2)
        scale.set_hexpand(True)
        scale.set_value(value)

        spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        spin.set_digits(2)
        spin.set_width_chars(5)
        spin.set_value(value)

        label = Gtk.Label(label=self._opacity_text(value), width_chars=4, xalign=1)

        def sync_from_scale(s, s_spin=spin, s_label=label):
            v = s.get_value()

            if abs(s_spin.get_value() - v) > 0.0005:
                s_spin.set_value(v)

            s_label.set_text(self._opacity_text(v))

        def sync_from_spin(sp, sp_scale=scale, sp_label=label):
            v = sp.get_value()

            if abs(sp_scale.get_value() - v) > 0.0005:
                sp_scale.set_value(v)

            sp_label.set_text(self._opacity_text(v))

        scale.connect("value-changed", sync_from_scale)
        spin.connect("value-changed", sync_from_spin)

        box.append(scale)
        box.append(spin)
        box.append(label)

        self._settings_widgets[key] = scale
        self._settings_widgets[key + "_spin"] = spin

        return box

    def _make_blur_control(self, Gtk, value):

        box = Gtk.Box(spacing=8)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 50, 1)
        scale.set_digits(0)
        scale.set_hexpand(True)
        scale.set_value(value)

        spin = Gtk.SpinButton.new_with_range(0, 50, 1)
        spin.set_digits(0)
        spin.set_width_chars(5)
        spin.set_value(value)

        label = Gtk.Label(label=f"{int(value)}px", width_chars=5, xalign=1)

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

        self._settings_widgets["blur_scale"] = scale
        self._settings_widgets["blur_spin"] = spin

        return box

    def _make_userlist_width_control(self, Gtk, value):

        box = Gtk.Box(spacing=8)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 120, 400, 10)
        scale.set_digits(0)
        scale.set_hexpand(True)
        scale.set_value(value)

        spin = Gtk.SpinButton.new_with_range(120, 400, 10)
        spin.set_digits(0)
        spin.set_width_chars(5)
        spin.set_value(value)

        label = Gtk.Label(label=f"{int(value)}px", width_chars=5, xalign=1)

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

        self._settings_widgets["userlist_scale"] = scale
        self._settings_widgets["userlist_spin"] = spin

        return box

    # settings commit / actions ----------------------------------------------

    def _dropdown_value(self, dropdown):

        item = dropdown.get_selected_item()

        if item is not None:
            return item.get_string()

        return ""

    def _read_and_commit(self):

        widgets = self._settings_widgets

        # Sync any pending hex entries into the color buttons.
        for key in ("bg_color", "overlay_color", "accent"):
            button = widgets.get(f"{key}_button")
            entry = widgets.get(f"{key}_entry")

            if button is not None and entry is not None:
                self._apply_entry_hex(entry, button)

        # Sync any pending path entries.
        for key in ("image_path", "overlay_image_path", "header_image_path"):
            entry = widgets.get(f"{key}_entry")

            if entry is not None:
                self._set_path_value(key, entry.get_text())

        self.settings.update({
            "enabled": widgets["enable_switch"].get_active(),
            "background_type": self._dropdown_value(widgets["type_dropdown"]),
            "image_path": widgets.get("image_path", self.settings.get("image_path", "")),
            "color": self._rgba_to_hex(widgets["bg_color_button"].get_rgba()),
            "mode": self._dropdown_value(widgets["mode_dropdown"]),
            "background_effect": self._dropdown_value(widgets["effect_dropdown"]),
            "blur_strength": int(round(widgets["blur_scale"].get_value())),
            "overlay_color": self._rgba_to_hex(widgets["overlay_color_button"].get_rgba()),
            "overlay_type": self._dropdown_value(widgets["overlay_type_dropdown"]),
            "overlay_image_path": widgets.get("overlay_image_path", ""),
            "overlay_opacity": widgets["opacity_scale"].get_value(),
            "header_image_path": widgets.get("header_image_path", ""),
            "header_overlay_opacity": widgets["header_scale"].get_value(),
            "accent_color": self._rgba_to_hex(widgets["accent_button"].get_rgba()),
            "userlist_width": int(round(widgets["userlist_scale"].get_value())),
            "userlist_resizable": widgets["userlist_resizable"].get_active(),
            "overlay_buddy": widgets["overlay_buddy"].get_active(),
            "overlay_chat": widgets["overlay_chat"].get_active(),
            "overlay_browse": widgets["overlay_browse"].get_active(),
        })

        self._apply_theme()

    def _on_settings_apply(self, *_args):
        self._read_and_commit()

    def _on_settings_ok(self, *_args):

        self._read_and_commit()

        if self._settings_window is not None:
            self._settings_window.close()

    def _on_settings_cancel(self, *_args):

        if self._settings_window is not None:
            self._settings_window.close()

    def _on_choose_path(self, key):

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]
        chooser = Gtk.FileChooserNative(title="Select media file", action=Gtk.FileChooserAction.OPEN)

        if self._settings_window is not None:
            chooser.set_transient_for(self._settings_window)

        media_filter = Gtk.FileFilter()
        media_filter.set_name("Images & Videos")

        for pattern in (
            "*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.svg", "*.webp", "*.tiff",
            "*.webm", "*.mp4", "*.ogv", "*.mkv"
        ):
            media_filter.add_pattern(pattern)

        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")

        chooser.add_filter(media_filter)
        chooser.add_filter(all_filter)
        chooser.set_filter(media_filter)

        self._chooser_key = key
        chooser.connect("response", self._on_image_response)
        chooser.show()

    def _on_image_response(self, dialog, response_id):

        gtk = self._get_gtk()

        if gtk and response_id == gtk["Gtk"].ResponseType.ACCEPT:
            gio_file = dialog.get_file()

            if gio_file is not None:
                path = gio_file.get_path()

                if path:
                    self._set_path_value(self._chooser_key, path)

        dialog.destroy()

    def _set_path_value(self, key, path):

        path = self._clean_path(path)
        self._settings_widgets[key] = path

        entry = self._settings_widgets.get(f"{key}_entry")

        if entry is not None and entry.get_text() != path:
            entry.set_text(path)

    def _on_settings_closed(self, *_args):

        self._settings_window = None
        self._settings_widgets = {}
        return False

    # helpers ----------------------------------------------------------------

    def _opacity_text(self, value):
        return f"{int(round(value * 100))}%"

    def _parse_rgba(self, Gdk, hex_color):

        rgba = Gdk.RGBA()

        if not rgba.parse(hex_color):
            rgba.parse("#000000")

        return rgba

    def _rgba_to_hex(self, rgba):

        red = int(round(max(0.0, min(1.0, rgba.red)) * 255))
        green = int(round(max(0.0, min(1.0, rgba.green)) * 255))
        blue = int(round(max(0.0, min(1.0, rgba.blue)) * 255))
        return f"#{red:02x}{green:02x}{blue:02x}"

    # --- CSS ------------------------------------------------------------------

    def _build_css(self, config):

        rules = []

        # Accent color (selections, switches, links, suggested-action buttons).
        accent = config.get("accent_color") or DEFAULT_ACCENT_COLOR
        accent_fg = self._contrast_fg(accent)
        rules.append(
            f"@define-color accent_color {accent};\n"
            f"@define-color accent_bg_color {accent};\n"
            f"@define-color accent_fg_color {accent_fg};\n"
            f"@define-color theme_selected_bg_color {accent};\n"
            f"@define-color theme_selected_fg_color {accent_fg};"
        )

        if config["type"] == "color":
            rules.append(
                f".{CSS_CLASS_BG} {{\n"
                f"    background-image: none;\n"
                f"    background-color: {config['bg_color']};\n"
                f"    {self._filter_css(config)}\n"
                f"}}"
            )
        else:
            background_size, background_repeat = self._mode_css(config["mode"])

            rules.append(
                f".{CSS_CLASS_BG} {{\n"
                f"    background-image: url(\"{config['uri']}\");\n"
                f"    background-size: {background_size};\n"
                f"    background-repeat: {background_repeat};\n"
                f"    background-position: center center;\n"
                f"    {self._filter_css(config)}\n"
                f"}}"
            )

        rules.append(f".{CSS_CLASS_TRANSPARENT} {{ background-color: transparent; }}")
        rules.append(f".{CSS_CLASS_OVERLAY} {{ {self._overlay_css(config)} }}")
        rules.append(f".{CSS_CLASS_HEADER} {{ {self._header_css(config)} }}")

        return "\n".join(rules)

    def _filter_css(self, config):

        effect = config.get("background_effect") or "none"

        if effect == "none":
            return "filter: none;"

        if effect == "blur":
            strength = max(0, min(50, int(config.get("blur_strength") or 0)))
            return f"filter: blur({strength}px);"

        if effect == "grayscale":
            return "filter: grayscale(1);"

        if effect == "sepia":
            return "filter: sepia(0.7);"

        if effect == "saturate":
            return "filter: saturate(1.6);"

        if effect == "hue-rotate":
            return "filter: hue-rotate(90deg);"

        if effect == "invert":
            return "filter: invert(1);"

        return "filter: none;"

    def _overlay_css(self, config):

        if (config.get("overlay_type") or "color") == "image" and config.get("overlay_uri"):
            return (
                f"background-image: url(\"{config['overlay_uri']}\"); "
                f"background-size: cover; "
                f"background-repeat: no-repeat; "
                f"background-position: center center;"
            )

        return f"background-color: {self._color_to_rgba(config['overlay_color'], config['overlay_opacity'])};"

    def _header_css(self, config):

        parts = []

        if config.get("header_uri"):
            parts.append(f"background-image: url(\"{config['header_uri']}\");")
            parts.append("background-size: cover;")
            parts.append("background-repeat: no-repeat;")
            parts.append("background-position: center center;")
        else:
            parts.append("background-image: none;")

        parts.append(f"background-color: {self._color_to_rgba(config['overlay_color'], config['header_overlay_opacity'])};")

        return " ".join(parts)

    @staticmethod
    def _mode_css(mode):

        if mode == "fit":
            return "contain", "no-repeat"

        if mode == "fill":
            return "cover", "no-repeat"

        return "auto", "repeat"

    def _path_to_uri(self, image_path):

        try:
            path = Path(image_path).expanduser().resolve()
            return path.as_uri().replace('"', "%22")
        except Exception:
            return ""

    @staticmethod
    def _clean_path(path):

        path = (path or "").strip()

        # Strip surrounding single/double quotes (paths pasted from a shell).
        if len(path) >= 2 and path[0] == path[-1] and path[0] in ("'", '"'):
            path = path[1:-1].strip()

        return path

    def _parse_hex_color(self, value, default):

        v = (value or "").strip().lstrip("#")

        try:
            if len(v) == 3:
                v = "".join(char * 2 for char in v)

            if len(v) != 6:
                raise ValueError

            int(v, 16)  # validate it is hex
            return "#" + v.lower()

        except (ValueError, TypeError):
            return default

    def _hex_to_rgb(self, hex_color):

        v = self._parse_hex_color(hex_color, DEFAULT_OVERLAY_COLOR).lstrip("#")
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)

    def _color_to_rgba(self, hex_color, opacity):

        red, green, blue = self._hex_to_rgb(hex_color)
        alpha = max(0.0, min(1.0, float(opacity)))
        return f"rgba({red}, {green}, {blue}, {alpha})"

    def _contrast_fg(self, hex_color):

        red, green, blue = self._hex_to_rgb(hex_color)
        luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255

        if luminance > 0.55:
            return "#000000"

        return "#ffffff"

    # --- GTK plumbing ---------------------------------------------------------

    def _add_provider(self, gtk, css):

        Gtk = gtk["Gtk"]
        Gdk = gtk["Gdk"]

        provider = Gtk.CssProvider()
        self._load_css(provider, css)

        priority = Gtk.STYLE_PROVIDER_PRIORITY_USER
        display = Gdk.Display.get_default()

        if Gtk.get_major_version() >= 4:
            Gtk.StyleContext.add_provider_for_display(display, provider, priority)
        else:
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, priority)

        self._provider = provider

    def _remove_provider(self, gtk):

        Gtk = gtk["Gtk"]
        Gdk = gtk["Gdk"]
        provider = self._provider
        self._provider = None

        if provider is None:
            return

        try:
            if Gtk.get_major_version() >= 4:
                Gtk.StyleContext.remove_provider_for_display(Gdk.Display.get_default(), provider)
            else:
                Gtk.StyleContext.remove_provider_for_screen(Gdk.Screen.get_default(), provider)
        except Exception:
            pass

    @staticmethod
    def _load_css(provider, css):

        data = css.encode("utf-8")

        try:
            provider.load_from_data(data)
        except TypeError:
            provider.load_from_data(data, -1)

    @staticmethod
    def _add_class(Gtk, widget, css_class):

        if Gtk.get_major_version() >= 4:
            widget.add_css_class(css_class)
        else:
            widget.get_style_context().add_class(css_class)

    @staticmethod
    def _remove_class(Gtk, widget, css_class):

        if Gtk.get_major_version() >= 4:
            widget.remove_css_class(css_class)
        else:
            widget.get_style_context().remove_class(css_class)

    @staticmethod
    def _has_class(Gtk, widget, css_class):

        try:
            if Gtk.get_major_version() >= 4:
                return widget.has_css_class(css_class)

            return widget.get_style_context().has_class(css_class)
        except Exception:
            return False

    def _tag_once(self, Gtk, widget, css_class):

        if self._has_class(Gtk, widget, css_class):
            return

        try:
            self._add_class(Gtk, widget, css_class)
            self._tagged.append((widget, css_class))
        except Exception:
            pass

    def _container_types(self, Gtk):

        names = (
            "Box", "Grid", "Paned", "Notebook", "ScrolledWindow", "Viewport",
            "Stack", "Overlay", "Revealer", "ListBox", "FlowBox", "HeaderBar",
            "Frame", "ActionBar", "WindowHandle",
        )
        types = []

        for name in names:
            cls = getattr(Gtk, name, None)

            if cls is not None:
                types.append(cls)

        return tuple(types)

    def _surface_types(self, Gtk):

        names = ("TreeView", "TextView", "Entry", "ListView", "ColumnView", "IconView")
        types = []

        for name in names:
            cls = getattr(Gtk, name, None)

            if cls is not None:
                types.append(cls)

        return tuple(types)

    def _iter_children(self, Gtk, widget):

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
