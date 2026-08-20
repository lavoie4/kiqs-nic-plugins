"""Nicotine+ Theme Customizer plugin.

Adds a settings menu (Edit -> Plugins -> Theme Customizer -> Settings) that
lets the user customize the theme:

    * A background image or animated GIF (type is detected automatically), or
      a solid background color when no image is set.
    * Placement modes for image/GIF backgrounds: fit, fill, tile.
    * A colored overlay with adjustable opacity, so the background stays
      readable behind the sidebar, chat, log pane and header/search bar.

The static background and overlay are applied with a GTK CSS provider, so they
work on both the GTK 3 and GTK 4 builds. Animated GIFs use a Gtk.Picture
background layer and therefore require GTK 4.
"""

import colorsys
import json
import os
import random
from pathlib import Path

from pynicotine.pluginsystem import BasePlugin


CSS_CLASS_BG = "nplus-theme-background"
CSS_CLASS_TRANSPARENT = "nplus-theme-background-transparent"
CSS_CLASS_OVERLAY = "nplus-theme-background-overlay"
CSS_CLASS_HEADER = "nplus-theme-header-overlay"
CSS_CLASS_FILTER = "nplus-theme-ui-filter"
TEXT_OUTLINE_SELECTOR = (
    "label, entry, textview, treeview, button, modelbutton, spinbutton, "
    "dropdown, combobox, columnview, listview, tab, searchbar"
)

POLL_INTERVAL_MS = 1000

DEFAULT_COLOR = "#1a1a2e"
DEFAULT_OVERLAY_COLOR = "#000000"
DEFAULT_OVERLAY_OPACITY = 0.45
DEFAULT_OVERLAY_IMAGE_OPACITY = 1.0
DEFAULT_HEADER_OVERLAY_OPACITY = 0.6
DEFAULT_HEADER_COLOR = "#1b1b1b"
DEFAULT_TEXT_OUTLINE_COLOR = "#000000"
DEFAULT_TEXT_OUTLINE_SIZE = 1
DEFAULT_OVERLAY_RADIUS = 0
DEFAULT_FIND_COLOR = "#FFD500"
DEFAULT_FIND_GRADIENT_COLOR = "#00BFFF"
FIND_TAG_PREFIX = "nplus-find-highlight"
FIND_STYLES = ("solid", "rainbow", "gradient")
FIND_SWEEP_CHUNK = 1
FIND_SWEEP_MAX_CHUNKS = 4096
SWATCH_CLASS = "nplus-find-highlight-swatch"
DEFAULT_ACCENT_COLOR = "#5B3368"
DEFAULT_FINDBAR_COLOR = "#1b1b1b"
DEFAULT_BACKGROUND_EFFECT = "none"
DEFAULT_EFFECT_STRENGTH = 50
DEFAULT_GIF_MAX_DIMENSION = 640
DEFAULT_GIF_MAX_FPS = 25
DEFAULT_GIF_FRAME_CACHE = 60
DEFAULT_GIF_PINGPONG_MAX_FRAMES = 200

# Nicotine+ font config keys mapped to their GTK CSS selectors (mirrors
# pynicotine/gtkgui/widgets/theme.py -> _get_custom_font_css).
FONT_SELECTORS = {
    "globalfont": "window, popover",
    "listfont": "treeview",
    "textviewfont": "textview",
    "chatfont": ".chat-view textview",
    "searchfont": ".search-view treeview",
    "transfersfont": ".transfers-view treeview",
    "browserfont": ".userbrowse-view treeview",
}

FONT_LABELS = (
    ("globalfont", "Global font"),
    ("listfont", "List font"),
    ("textviewfont", "Text view font"),
    ("chatfont", "Chat font"),
    ("searchfont", "Search font"),
    ("transfersfont", "Transfers font"),
    ("browserfont", "Browse font"),
)

# (widget key, Nicotine+ config key, label, default color). Empty default = theme default.
COLOR_LABELS = (
    ("chat_local", "chatlocal", "Local username color", ""),
    ("chat_remote", "chatremote", "Remote username color", ""),
    ("chat_command", "chatcommand", "Command color", "#908E8B"),
    ("chat_me", "chatme", "Action (/me) color", "#908E8B"),
    ("chat_hilite", "chathilite", "Highlight color", "#5288CE"),
    ("url_color", "urlcolor", "URL link text color", "#5288CE"),
    ("text_bg", "textbg", "Text entry background color", ""),
    ("input_color", "inputcolor", "Text entry text color", ""),
    ("list_text_color", "search", "List text color", ""),
    ("user_online", "useronline", "Online color", "#16BB5C"),
    ("user_away", "useraway", "Away color", "#C9AE13"),
    ("user_offline", "useroffline", "Offline color", "#E04F5E"),
    ("tab_default_color", "tab_default", "Regular tab label color", ""),
    ("tab_hilite_color", "tab_hilite", "Highlighted tab label color", "#497EC2"),
    ("tab_changed_color", "tab_changed", "Changed tab label color", "#497EC2"),
)

CHAT_APPLY_TOOLTIP = (
    "Mirrors Nicotine+'s own setting. Applies immediately - no restart needed. "
    "Leave empty to use the theme default."
)


class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.settings = {
            "enabled": True,
            "background_type": "image",
            "image_path": "",
            "color": DEFAULT_COLOR,
            "mode": "fill",
            "gif_loop_style": "forward",
            "overlay_color": DEFAULT_OVERLAY_COLOR,
            "overlay_opacity": DEFAULT_OVERLAY_OPACITY,
            "overlay_image_opacity": DEFAULT_OVERLAY_IMAGE_OPACITY,
            "header_overlay_opacity": DEFAULT_HEADER_OVERLAY_OPACITY,
            "header_transparent": False,
            "header_color_enabled": False,
            "header_color": DEFAULT_HEADER_COLOR,
            "text_outline_enabled": False,
            "text_outline_color": DEFAULT_TEXT_OUTLINE_COLOR,
            "text_outline_size": DEFAULT_TEXT_OUTLINE_SIZE,
            "overlay_radius": DEFAULT_OVERLAY_RADIUS,
            "accent_color": DEFAULT_ACCENT_COLOR,
            "findbar_color": DEFAULT_FINDBAR_COLOR,
            "background_effect": DEFAULT_BACKGROUND_EFFECT,
            "effect_strength": DEFAULT_EFFECT_STRENGTH,
            "overlay_image_path": "",
            "header_image_path": "",
            "find_enabled": True,
            "find_style": "solid",
            "find_color": DEFAULT_FIND_COLOR,
            "find_gradient_color": DEFAULT_FIND_GRADIENT_COLOR,
            "find_highlight_all": False,
            "presets": "{}",
        }
        self.metasettings = {
            "enabled": {
                "description": "Enable custom background",
                "type": "bool",
            },
            "image_path": {
                "description": "Background image / GIF (type auto-detected)",
                "type": "file",
                "chooser": "image",
            },
            "color": {
                "description": "Background color (solid, used when no image is set, #RRGGBB)",
                "type": "str",
            },
            "mode": {
                "description": "Background mode (image/gif)",
                "type": "dropdown",
                "options": ["fit", "fill", "tile"],
            },
            "gif_loop_style": {
                "description": "GIF loop style (forward or forward-reverse ping-pong)",
                "type": "dropdown",
                "options": ["forward", "pingpong"],
            },
            "overlay_color": {
                "description": "Text tint color - the readability overlay drawn under text (#RRGGBB)",
                "type": "str",
            },
            "overlay_opacity": {
                "description": "Text tint opacity - readability overlay under text (0 = none, 1 = solid)",
                "type": "float",
                "minimum": 0.0,
                "maximum": 1.0,
                "stepsize": 0.05,
            },
            "overlay_image_opacity": {
                "description": "Overlay image opacity (0 = none, 1 = solid)",
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
            "header_transparent": {
                "description": "Make the title bar completely transparent",
                "type": "bool",
            },
            "header_color_enabled": {
                "description": "Use a solid color for the title bar",
                "type": "bool",
            },
            "header_color": {
                "description": "Solid title bar color (#RRGGBB)",
                "type": "str",
            },
            "text_outline_enabled": {
                "description": "Draw an outline around all text (experimental - may cause lag with GIF backgrounds or thickness above 2 px)",
                "type": "bool",
            },
            "text_outline_color": {
                "description": "Text outline color (#RRGGBB)",
                "type": "str",
            },
            "text_outline_size": {
                "description": "Text outline thickness in pixels",
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
            },
            "overlay_radius": {
                "description": "Rounded corner radius for tinted overlay surfaces in pixels",
                "type": "integer",
                "minimum": 0,
                "maximum": 24,
            },
            "accent_color": {
                "description": "Accent color (selections, switches, links, buttons)",
                "type": "str",
            },
            "findbar_color": {
                "description": "Find bar (Ctrl+F search bar) background color (#RRGGBB)",
                "type": "str",
            },
            "background_effect": {
                "description": "Background effect (none/grayscale/sepia/saturate/hue-rotate/invert)",
                "type": "dropdown",
                "options": ["none", "grayscale", "sepia", "saturate", "hue-rotate", "invert"],
            },
            "effect_strength": {
                "description": "Effect strength as a percentage (applies to the selected background effect)",
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
            },
            "overlay_image_path": {
                "description": "Overlay image drawn over the background",
                "type": "file",
                "chooser": "image",
            },
            "header_image_path": {
                "description": "Title bar background image",
                "type": "file",
                "chooser": "image",
            },
            "find_enabled": {
                "description": "Enable find highlighting",
                "type": "bool",
            },
            "find_style": {
                "description": "Find highlight style",
                "type": "dropdown",
                "options": ["solid", "rainbow", "gradient"],
            },
            "find_color": {
                "description": "Find highlight color (#RRGGBB)",
                "type": "str",
            },
            "find_gradient_color": {
                "description": "Find gradient end color (#RRGGBB)",
                "type": "str",
            },
            "find_highlight_all": {
                "description": "Highlight all matches, not just the current one",
                "type": "bool",
            },
        }
        self.commands = {
            "theme": {
                "callback": self.theme_command,
                "description": "Apply, refresh or disable the custom theme background, or open the settings window",
                "parameters": ["[on|off|refresh|settings|unload|presets]"],
                "group": "Theme Customizer",
            },
            "ts": {
                "callback": self.theme_command,
                "description": "Open the Theme Customizer settings window (short alias for /theme settings)",
                "parameters": ["[on|off|refresh|settings|unload|presets]"],
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
        self._gif_frame_cache = {}
        self._gif_frame_index = 0
        self._gif_scaled_warned = False
        self._gif_loop_style = "forward"
        self._gif_frames = None
        self._gif_index = 0
        self._gif_direction = 1
        self._gif_capture_done = False
        self._gif_target = 0
        self._webm_stream = None
        self._unloaded = False

        # custom settings dialog state
        self._settings_window = None
        self._settings_widgets = {}
        self._chooser_key = "image_path"
        self._applying = False
        self._live_timeout = None

        # find-highlight state
        self._find_patched = False
        self._find_original_match = None
        self._find_original_visible = None
        self._find_menu_patched = False
        self._find_original_secondary = None
        self._find_clear_menu_widget = None
        self._find_syncing = False
        self._swatch_provider = None

    # --- lifecycle -----------------------------------------------------------

    def init(self):
        """Settings have loaded; apply the theme and start watching for changes."""

        self._apply_theme()
        self._find_patch()
        self._find_patch_context_menu()

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

        self._find_unpatch()
        self._find_unpatch_context_menu()
        self._clear_theme()

    # --- command -------------------------------------------------------------

    def theme_command(self, args, **_unused):

        action = (args or "").strip().lower()

        if action in {"", "settings", "gui", "options"}:
            return self._open_settings()

        if action in {"unload", "clear"}:
            self._clear_theme()
            self._unloaded = True
            self.output("Theme unloaded (plugin stays active). Use /theme on or /theme refresh to restore.")
            return True

        if action == "on":
            self.settings["enabled"] = True
            self._unloaded = False
        elif action == "off":
            self.settings["enabled"] = False
        elif action in {"refresh", "apply"}:
            self._unloaded = False
        else:
            self.output("Usage: /theme [on|off|refresh|settings|unload|presets]")
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
            self.settings.get("gif_loop_style", "forward") or "forward",
            self.settings.get("overlay_color", DEFAULT_OVERLAY_COLOR) or "",
            float(self.settings.get("overlay_opacity", DEFAULT_OVERLAY_OPACITY) or 0.0),
            float(self.settings.get("overlay_image_opacity", DEFAULT_OVERLAY_IMAGE_OPACITY) or 0.0),
            float(self.settings.get("header_overlay_opacity", DEFAULT_HEADER_OVERLAY_OPACITY) or 0.0),
            self.settings.get("accent_color", DEFAULT_ACCENT_COLOR) or "",
            self.settings.get("background_effect", DEFAULT_BACKGROUND_EFFECT) or "none",
            int(self.settings.get("effect_strength", DEFAULT_EFFECT_STRENGTH) or 0),
            self.settings.get("overlay_image_path", "") or "",
            self.settings.get("header_image_path", "") or "",
        )

    def _poll_settings(self):

        if self._unloaded:
            return True

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

    @staticmethod
    def _detect_background_type(image_path):
        """Infer the background type from the selected file (no user dropdown)."""

        image_path = (image_path or "").strip()

        if not image_path:
            return "color"

        if image_path.lower().endswith(".gif"):
            return "gif"

        return "image"

    def _apply_theme(self):

        self._unloaded = False

        gtk = self._get_gtk()

        if not gtk:
            self._signature = None
            return False

        self._clear_theme(gtk)

        signature = self._current_signature()

        enabled = bool(self.settings.get("enabled", True))
        image_path = self._clean_path(self.settings.get("image_path", ""))
        background_type = self._detect_background_type(image_path)

        if not enabled:
            self._signature = signature
            return True

        if background_type in {"image", "gif"}:
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

        config = self._build_config()
        config["type"] = background_type

        self.log(
            "Applying background: type=%s image=%s",
            (background_type, config.get("image_path", "") or config.get("bg_color", ""))
        )

        try:
            self._add_provider(gtk, self._build_css(config))
        except Exception as exc:
            self.log("Theme CSS failed to apply: %s", (exc,))

        if background_type == "gif":
            self._setup_gif_background(gtk, window, config)
        elif background_type == "webm":
            self._setup_webm_background(gtk, window, config)
        else:
            self._setup_static_background(gtk, window, config)

        self._tag_assets(gtk)
        self._tag_header(gtk)

        # Force a repaint so CSS background/image/overlay changes show up
        # immediately. Static backgrounds (image/color) don't repaint on their
        # own the way animated GIF/WebM layers do, so invalidate every widget.
        try:
            window.queue_draw()

            if self._root is not None:
                self._root.queue_draw()

            for widget, _css_class in self._tagged:
                try:
                    widget.queue_draw()
                except Exception:
                    pass
        except Exception:
            pass

        self._signature = signature
        self.log("Applied theme background (%s)", (background_type,))
        return True

    def _build_config(self):

        image_path = self._clean_path(self.settings.get("image_path", ""))
        background_type = self._detect_background_type(image_path)
        color = self.settings.get("color", DEFAULT_COLOR) or ""
        mode = self.settings.get("mode", "fill") or "fill"
        overlay_color = self.settings.get("overlay_color", DEFAULT_OVERLAY_COLOR) or ""
        overlay_opacity = float(self.settings.get("overlay_opacity", DEFAULT_OVERLAY_OPACITY) or 0.0)
        overlay_image_opacity = float(self.settings.get("overlay_image_opacity", DEFAULT_OVERLAY_IMAGE_OPACITY) or 0.0)
        header_overlay_opacity = float(self.settings.get("header_overlay_opacity", DEFAULT_HEADER_OVERLAY_OPACITY) or 0.0)
        accent_color = self.settings.get("accent_color", DEFAULT_ACCENT_COLOR) or ""

        config = {
            "type": background_type,
            "mode": mode,
            "gif_loop_style": self.settings.get("gif_loop_style", "forward") or "forward",
            "overlay_color": overlay_color,
            "overlay_opacity": overlay_opacity,
            "overlay_image_opacity": overlay_image_opacity,
            "header_overlay_opacity": header_overlay_opacity,
            "header_transparent": bool(self.settings.get("header_transparent", False)),
            "header_color_enabled": bool(self.settings.get("header_color_enabled", False)),
            "header_color": self._parse_hex_color(self.settings.get("header_color", "") or "", DEFAULT_HEADER_COLOR),
            "text_outline_enabled": bool(self.settings.get("text_outline_enabled", False)),
            "text_outline_color": self._parse_hex_color(self.settings.get("text_outline_color", "") or "", DEFAULT_TEXT_OUTLINE_COLOR),
            "text_outline_size": max(1, min(3, int(self.settings.get("text_outline_size", DEFAULT_TEXT_OUTLINE_SIZE) or DEFAULT_TEXT_OUTLINE_SIZE))),
            "overlay_radius": max(0, min(24, int(self.settings.get("overlay_radius", DEFAULT_OVERLAY_RADIUS) or 0))),
            "accent_color": self._parse_hex_color(accent_color, DEFAULT_ACCENT_COLOR),
            "findbar_color": self._parse_hex_color(self.settings.get("findbar_color", "") or "", DEFAULT_FINDBAR_COLOR),
            "background_effect": self.settings.get("background_effect", DEFAULT_BACKGROUND_EFFECT) or "none",
            "effect_strength": int(self.settings.get("effect_strength", DEFAULT_EFFECT_STRENGTH) or 0),
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

        ui = self._ui_config()
        config["ui_fonts"] = {key: ui.get(key, "") or "" for key in FONT_SELECTORS}
        config["ui_colors"] = {config_key: ui.get(config_key, "") or "" for _w, config_key, _l, _d in COLOR_LABELS}

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
        self._gif_frame_cache = {}
        self._gif_frame_index = 0
        self._gif_scaled_warned = False
        self._gif_loop_style = "forward"
        self._gif_frames = None
        self._gif_index = 0
        self._gif_direction = 1
        self._gif_capture_done = False
        self._gif_target = 0
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

    def _add_overlay_image(self, Gtk, overlay, config):
        """Lay the custom overlay image over the background (all background types)."""

        overlay_path = config.get("overlay_image_path") or ""

        if not overlay_path:
            return

        overlay_file = os.path.expanduser(overlay_path)

        if not os.path.isfile(overlay_file):
            return

        try:
            from gi.repository import Gdk

            overlay_texture = Gdk.Texture.new_from_file(overlay_file)

            if overlay_texture is None:
                return

            overlay_picture = Gtk.Picture(
                visible=True, can_shrink=True, hexpand=True, vexpand=True
            )
            overlay_picture.set_halign(Gtk.Align.FILL)
            overlay_picture.set_valign(Gtk.Align.FILL)
            overlay_picture.set_paintable(overlay_texture)
            overlay_picture.set_content_fit(Gtk.ContentFit.COVER)
            overlay_picture.set_opacity(
                max(0.0, min(1.0, float(config.get("overlay_image_opacity", 1.0) or 1.0)))
            )
            overlay.add_overlay(overlay_picture)
        except Exception:
            pass

    def _blur_radius(self, config):
        """Blur radius (px) for the background, 0 when the effect isn't blur."""

        effect = config.get("background_effect") or "none"

        if effect != "blur":
            return 0.0

        strength = max(0, min(100, int(config.get("effect_strength") or 0)))
        return (strength / 100.0) * 50.0

    def _blurred_picture_cls(self, Gtk):
        """Return a cached Gtk.Picture subclass that blurs its own rendering via
        Gtk.Snapshot.push_blur(). The blur is confined to this widget's snapshot
        scope, so only the background image is blurred - the UI content rendered
        on top stays untouched. A CSS ``filter: blur()`` would instead smear the
        whole window (and hit the window/root widgets on the CSS fallback path)."""

        cls = getattr(self, "_blurred_picture_class", None)

        if cls is not None:
            return cls

        class BlurredPicture(Gtk.Picture):

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._blur_radius = 0.0

            def set_blur_radius(self, radius):
                radius = max(0.0, float(radius))

                if radius != self._blur_radius:
                    self._blur_radius = radius
                    self.queue_draw()

            def do_snapshot(self, snapshot):
                if self._blur_radius > 0.0 and hasattr(snapshot, "push_blur"):
                    snapshot.push_blur(self._blur_radius)

                    try:
                        super().do_snapshot(snapshot)
                    finally:
                        snapshot.pop()
                else:
                    super().do_snapshot(snapshot)

        self._blurred_picture_class = BlurredPicture
        return BlurredPicture

    def _setup_static_background(self, gtk, window, config):
        """GTK 4: paint the static background (image or solid color) on a
        dedicated layer behind the content."""

        Gtk = gtk["Gtk"]
        root = self._root

        if root is None or Gtk.get_major_version() < 4:
            # GTK 3 (or no root): keep the simple CSS-on-window/root approach.
            self._tag_background(gtk, config)
            return

        if config.get("type") != "image":
            # Solid color: CSS background-color on a plain box.
            try:
                bg = Gtk.Box(hexpand=True, vexpand=True, visible=True)
                self._add_class(Gtk, bg, CSS_CLASS_BG)
                self._tagged.append((bg, CSS_CLASS_BG))

                overlay = Gtk.Overlay(visible=True)
                overlay.set_child(bg)
                self._add_overlay_image(Gtk, overlay, config)
                window.set_child(None)
                overlay.add_overlay(root)
                window.set_child(overlay)
                self._overlay = overlay

                self._add_class(Gtk, root, CSS_CLASS_TRANSPARENT)
                self._tagged.append((root, CSS_CLASS_TRANSPARENT))
            except Exception:
                self._tag_background(gtk, config)
            return

        # Image: use Gtk.Picture. CSS background-image on a plain box does not
        # reliably render in GTK 4, while Gtk.Picture does.
        try:
            from gi.repository import Gdk

            texture = Gdk.Texture.new_from_file(config["image_path"])
        except Exception:
            self._tag_background(gtk, config)
            return

        blur_radius = self._blur_radius(config)

        try:
            if blur_radius > 0.0:
                picture = self._blurred_picture_cls(Gtk)(visible=True, can_shrink=True)
                picture.set_blur_radius(blur_radius)
            else:
                picture = Gtk.Picture(visible=True, can_shrink=True)

            picture.set_paintable(texture)
            picture.set_content_fit(self._content_fit(config["mode"]))

            self._add_class(Gtk, picture, CSS_CLASS_BG)
            self._tagged.append((picture, CSS_CLASS_BG))

            overlay = Gtk.Overlay(visible=True)
            overlay.set_child(picture)

            self._add_overlay_image(Gtk, overlay, config)

            window.set_child(None)
            overlay.add_overlay(root)
            window.set_child(overlay)
            self._overlay = overlay

            self._add_class(Gtk, root, CSS_CLASS_TRANSPARENT)
            self._tagged.append((root, CSS_CLASS_TRANSPARENT))
        except Exception:
            try:
                window.set_child(None)
                window.set_child(root)
            except Exception:
                pass

            self._tag_background(gtk, config)

    def _tag_assets(self, gtk):
        """Make structural containers transparent and tint content surfaces."""

        Gtk = gtk["Gtk"]
        root = self._root

        if root is None:
            return

        # UI filter (grayscale/sepia/etc.) applies to the whole content.
        self._tag_once(Gtk, root, CSS_CLASS_FILTER)

        container_types = self._container_types(Gtk)
        surface_types = self._surface_types(Gtk)
        row_types = self._row_surface_types(Gtk)

        for widget in self._walk(Gtk, root):
            try:
                if isinstance(widget, row_types):
                    # Tree/list views render each entry (row) as its own node,
                    # so a border-radius on the widget itself rounds every row
                    # instead of the whole surface. Move the tint + radius onto
                    # the enclosing panel and keep the list itself transparent.
                    panel = self._enclosing_panel(Gtk, widget, container_types)

                    if panel is not None:
                        self._tag_once(Gtk, panel, CSS_CLASS_OVERLAY)

                    self._tag_once(Gtk, widget, CSS_CLASS_TRANSPARENT)
                elif isinstance(widget, surface_types):
                    self._tag_once(Gtk, widget, CSS_CLASS_OVERLAY)
                elif isinstance(widget, container_types):
                    self._tag_once(Gtk, widget, CSS_CLASS_TRANSPARENT)
            except Exception:
                pass

        # Tint the chat-room member-list header (the "Users(n)" + "Room Wall"
        # strip) so it matches the tinted list below instead of showing the raw
        # background through a transparent gap in the top-right corner.
        self._tag_userlist_headers(Gtk)

    @staticmethod
    def _widget_id(widget):
        """Best-effort GtkBuilder id for a widget (GTK 3 uses get_name)."""

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

    def _tag_userlist_headers(self, Gtk):
        """Tag the chat-room member-list header rows with the overlay tint."""

        root = self._root

        if root is None:
            return

        for widget in self._walk(Gtk, root):
            try:
                if self._widget_id(widget) != "room_wall_button":
                    continue

                header = self._parent_of(Gtk, widget)

                if header is not None:
                    self._tag_once(Gtk, header, CSS_CLASS_OVERLAY)
            except Exception:
                continue

    def _tag_header(self, gtk):
        """Theme the window title bar (GTK 4 header bar)."""

        Gtk = gtk["Gtk"]

        if self._window is None:
            return

        titlebar = self._get_titlebar(Gtk, self._window)

        if titlebar is None:
            return

        self._tag_once(Gtk, titlebar, CSS_CLASS_HEADER)

        try:
            titlebar.queue_draw()
        except Exception:
            pass

    def _get_titlebar(self, Gtk, window):

        try:
            if Gtk.get_major_version() >= 4:
                return window.get_titlebar()
        except Exception:
            pass

        return None

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

        blur_radius = self._blur_radius(config)

        try:
            if blur_radius > 0.0:
                picture = self._blurred_picture_cls(Gtk)(visible=True, can_shrink=True)
                picture.set_blur_radius(blur_radius)
            else:
                picture = Gtk.Picture(visible=True, can_shrink=True)

            picture.set_content_fit(self._content_fit(config["mode"]))

            self._add_class(Gtk, picture, CSS_CLASS_BG)
            self._tagged.append((picture, CSS_CLASS_BG))

            overlay = Gtk.Overlay(visible=True)
            overlay.set_child(picture)

            self._add_overlay_image(Gtk, overlay, config)

            window.set_child(None)          # detach the original content
            overlay.add_overlay(root)       # put content on top of the picture
            window.set_child(overlay)

            self._overlay = overlay

            # The content root must be transparent so the picture shows through.
            self._add_class(Gtk, root, CSS_CLASS_TRANSPARENT)
            self._tagged.append((root, CSS_CLASS_TRANSPARENT))

            self._start_gif_animation(gtk, picture, animation, config.get("gif_loop_style", "forward"), config.get("image_path", ""))

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

            self._add_overlay_image(Gtk, overlay, config)

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

    def _start_gif_animation(self, gtk, picture, animation, loop_style="forward", image_path=""):

        self._gif_picture = picture
        self._gif_animation = animation
        self._gif_loop_style = loop_style
        self._gif_frames = None
        self._gif_index = 0
        self._gif_direction = 1
        self._gif_capture_done = False
        self._gif_target = 0

        if loop_style == "pingpong":
            self._start_gif_pingpong(gtk, image_path)
        else:
            self._start_gif_forward(gtk)

    def _start_gif_forward(self, gtk):
        """Start the standard forward-loop animation."""

        GLib = gtk["GLib"]

        try:
            self._gif_iter = self._gif_animation.get_iter(None)
        except Exception as exc:
            self._gif_iter = None
            self.log("GIF animation not started: %s", (exc,))
            return

        # Show the first frame immediately, then schedule the next tick.
        self._gif_show_current_frame()
        self._gif_timeout = GLib.timeout_add(self._gif_current_delay(), self._gif_tick)
        self.log("GIF animation started")

    def _start_gif_pingpong(self, gtk, image_path):
        """Capture frames during one forward pass, then bounce back and forth."""

        GLib = gtk["GLib"]

        target = self._gif_frame_count(image_path)

        if target < 2:
            # Single-frame GIF (or unparseable): just use the forward loop.
            self._gif_loop_style = "forward"
            self._start_gif_forward(gtk)
            return

        self._gif_frames = []
        self._gif_capture_done = False
        self._gif_target = min(target, DEFAULT_GIF_PINGPONG_MAX_FRAMES)
        self._gif_index = 0
        self._gif_direction = 1

        try:
            self._gif_iter = self._gif_animation.get_iter(None)
        except Exception as exc:
            self._gif_iter = None
            self.log("GIF ping-pong capture not started: %s", (exc,))
            return

        # Show + capture the first frame, then the forward tick captures the rest.
        self._gif_show_current_frame()
        self._capture_gif_frame()
        self._gif_timeout = GLib.timeout_add(self._gif_current_delay(), self._gif_tick)
        self.log("GIF ping-pong capturing (%d frames)", (self._gif_target,))

    def _capture_gif_frame(self):
        """Record the current scaled frame; switch to the bounce loop once done."""

        if self._gif_capture_done:
            return

        try:
            pixbuf = self._gif_iter.get_pixbuf()
        except Exception:
            return

        if pixbuf is None:
            return

        Gdk = self._gtk["Gdk"]
        texture = self._gif_scaled_texture(Gdk, pixbuf)

        if texture is None:
            return

        delay = self._gif_current_delay()
        self._gif_frames.append((texture, delay))

        if len(self._gif_frames) < self._gif_target:
            return

        self._gif_capture_done = True
        self._gif_index = len(self._gif_frames) - 1
        self._gif_direction = -1

        try:
            self._gif_timeout = self._gtk["GLib"].timeout_add(delay, self._gif_tick_pingpong)
        except Exception:
            pass

        self.log("GIF ping-pong started (%d frames)", (len(self._gif_frames),))

    def _gif_frame_count(self, path):
        """Count frames (Image Descriptors) in a GIF by parsing its block structure."""

        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except Exception:
            return 0

        if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
            return 0

        n = len(data)
        pos = 6 + 7  # header + logical screen descriptor

        # Global color table.
        if data[10] & 0x80:
            pos += 3 * (2 ** ((data[10] & 0x07) + 1))

        count = 0

        while pos < n:
            block = data[pos]
            pos += 1

            if block == 0x3B:      # trailer
                break

            if block == 0x21:      # extension: label + sub-blocks
                if pos >= n:
                    break

                pos += 1           # skip extension label

                while pos < n:
                    size = data[pos]
                    pos += 1

                    if size == 0:
                        break

                    pos += size

            elif block == 0x2C:    # image descriptor = a frame
                count += 1

                if pos + 9 > n:
                    break

                image_packed = data[pos + 8]
                pos += 9

                if image_packed & 0x80:  # local color table
                    pos += 3 * (2 ** ((image_packed & 0x07) + 1))

                if pos >= n:
                    break

                pos += 1           # LZW minimum code size

                while pos < n:
                    size = data[pos]
                    pos += 1

                    if size == 0:
                        break

                    pos += size

            elif block == 0x00:    # stray sub-block terminator
                continue

            else:
                break

        return count

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

            self._gif_frame_index += 1
            self._gif_show_current_frame()
            delay = self._gif_current_delay()

            if self._gif_loop_style == "pingpong" and not self._gif_capture_done:
                self._capture_gif_frame()

                if self._gif_capture_done:
                    return False
        except Exception as exc:
            self.log("GIF animation stopped: %s", (exc,))
            return False

        self._gif_timeout = GLib.timeout_add(delay, self._gif_tick)
        return False

    def _gif_show_current_frame(self):

        Gdk = self._gtk["Gdk"]

        try:
            pixbuf = self._gif_iter.get_pixbuf()
        except Exception:
            return

        if pixbuf is None:
            return

        texture = self._gif_scaled_texture(Gdk, pixbuf)

        if texture is not None:
            self._gif_picture.set_paintable(texture)
            self._gif_picture.queue_draw()

    def _gif_scaled_texture(self, Gdk, pixbuf):
        """Downscale oversized GIF frames and cache them so loop repeats stay cheap.

        Large GIFs are the main source of UI jank here: every full-resolution
        frame forces a fresh Gdk.Texture upload on the UI thread, which stalls
        chat auto-scroll and other redraws. Capping the frame size and reusing
        the scaled textures keeps per-frame work to a single set_paintable().
        """

        index = self._gif_frame_index
        texture = self._gif_frame_cache.get(index)

        if texture is not None:
            return texture

        width = pixbuf.get_width()
        height = pixbuf.get_height()
        max_dim = DEFAULT_GIF_MAX_DIMENSION

        if width > max_dim or height > max_dim:
            if not self._gif_scaled_warned:
                self.log(
                    "GIF frames are large (%dx%d) - scaling to %dpx to keep the UI responsive",
                    width, height, max_dim
                )
                self._gif_scaled_warned = True

            pixbuf = self._scale_pixbuf(pixbuf, max_dim)

            if pixbuf is None:
                return None

        try:
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
        except Exception:
            return None

        if len(self._gif_frame_cache) >= DEFAULT_GIF_FRAME_CACHE:
            self._gif_frame_cache.clear()

        self._gif_frame_cache[index] = texture
        return texture

    @staticmethod
    def _scale_pixbuf(pixbuf, max_dim):

        width = pixbuf.get_width()
        height = pixbuf.get_height()

        if width <= max_dim and height <= max_dim:
            return pixbuf

        scale = min(max_dim / width, max_dim / height)
        scaled_width = max(1, int(width * scale))
        scaled_height = max(1, int(height * scale))

        try:
            from gi.repository import GdkPixbuf  # pylint: disable=import-error
            return pixbuf.scale_simple(scaled_width, scaled_height, GdkPixbuf.InterpType.BILINEAR)
        except Exception:
            return pixbuf

    def _gif_current_delay(self):

        delay = self._gif_iter.get_delay_time()

        if not delay or delay < 10:
            delay = 100

        # Cap the frame rate so a fast GIF can't saturate the main thread.
        min_delay = 1000 // DEFAULT_GIF_MAX_FPS

        if delay < min_delay:
            delay = min_delay

        return delay

    def _gif_tick_pingpong(self):

        if self._gtk is None or self._gif_picture is None or not self._gif_frames:
            return False

        GLib = self._gtk["GLib"]
        n = len(self._gif_frames)

        try:
            # Bounce without repeating the endpoints.
            if n > 1:
                if self._gif_direction == 1:
                    nxt = self._gif_index + 1

                    if nxt >= n:
                        nxt = n - 2
                        self._gif_direction = -1
                else:
                    nxt = self._gif_index - 1

                    if nxt < 0:
                        nxt = 1
                        self._gif_direction = 1

                self._gif_index = nxt

            self._gif_show_pingpong_frame()

            _texture, delay = self._gif_frames[self._gif_index]
            delay = delay if (delay and delay >= 10) else 100
        except Exception as exc:
            self.log("GIF ping-pong stopped: %s", (exc,))
            return False

        self._gif_timeout = GLib.timeout_add(delay, self._gif_tick_pingpong)
        return False

    def _gif_show_pingpong_frame(self):

        if not self._gif_frames or self._gif_picture is None:
            return

        try:
            texture, _delay = self._gif_frames[self._gif_index]

            if texture is not None:
                self._gif_picture.set_paintable(texture)
                self._gif_picture.queue_draw()
        except Exception:
            pass

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
        self._gif_frame_cache = {}
        self._gif_frame_index = 0
        self._gif_scaled_warned = False
        self._gif_loop_style = "forward"
        self._gif_frames = None
        self._gif_index = 0
        self._gif_direction = 1
        self._gif_capture_done = False
        self._gif_target = 0

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

        if self._live_timeout is not None:
            try:
                if self._gtk:
                    self._gtk["GLib"].source_remove(self._live_timeout)
            except Exception:
                pass

            self._live_timeout = None

        self._remove_swatch_provider()
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

    def _big_title(self, Gtk, text):

        label = Gtk.Label(xalign=0.0)
        label.set_markup(f'<span size="x-large" weight="bold">{text}</span>')
        label.set_margin_top(10)
        label.set_margin_bottom(6)
        return label

    def _build_settings_window(self, gtk):

        Gtk = gtk["Gtk"]
        Gdk = gtk["Gdk"]

        main_window = self._find_main_window(Gtk)

        window = Gtk.Window(title="Theme Customizer Settings")
        window.set_default_size(720, 760)
        window.set_resizable(True)
        window.set_size_request(520, 480)

        if main_window is not None:
            try:
                window.set_transient_for(main_window)
            except Exception:
                pass

        self._settings_window = window
        self._settings_widgets = {}

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_hexpand(True)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        box.append(self._big_title(Gtk, "Background"))
        box.append(self._build_background_page(Gtk, Gdk))
        box.append(self._big_title(Gtk, "Overlay"))
        box.append(self._build_overlay_page(Gtk, Gdk))
        box.append(self._big_title(Gtk, "Title bar"))
        box.append(self._build_titlebar_page(Gtk, Gdk))
        box.append(self._big_title(Gtk, "Accent"))
        box.append(self._build_accent_page(Gtk, Gdk))
        box.append(self._big_title(Gtk, "Chat"))
        box.append(self._build_chat_page(Gtk, Gdk))
        box.append(self._big_title(Gtk, "Highlight"))
        box.append(self._build_highlight_page(Gtk, Gdk))
        box.append(self._big_title(Gtk, "Layout"))
        box.append(self._build_layout_page(Gtk, Gdk))
        box.append(self._big_title(Gtk, "Presets"))
        box.append(self._build_presets_page(Gtk))

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_top(12)

        live_hint = Gtk.Label(label="Changes apply immediately", xalign=0)
        live_hint.add_css_class("dim-label")
        live_hint.set_hexpand(True)

        close_button = Gtk.Button(label="Close")
        close_button.add_css_class("suggested-action")
        close_button.connect("clicked", self._on_settings_close_button)

        footer.append(live_hint)
        footer.append(close_button)
        box.append(footer)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_child(box)

        window.set_child(scrolled)

        self._connect_live(Gtk)

        window.connect("close-request", self._on_settings_closed)
        window.present()

    def _build_background_page(self, Gtk, Gdk):

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        enable_switch = Gtk.Switch(active=bool(self.settings.get("enabled", True)), valign=Gtk.Align.CENTER)
        self._add_row(Gtk, page, "Enable custom background", enable_switch)

        self._add_path_row(
            Gtk, page, "Background image / GIF", self.settings.get("image_path", ""), "image_path",
            tooltip="Accepts images and animated GIFs. The type is detected automatically from the file."
        )

        self._add_color_control(
            Gtk, Gdk, page, "Background color (solid)",
            self.settings.get("color", DEFAULT_COLOR), "bg_color"
        )

        solid_hint = Gtk.Label(
            label="To use a solid color background, clear the image path above.",
            xalign=0, wrap=True
        )
        solid_hint.add_css_class("dim-label")
        page.append(solid_hint)

        mode_dropdown = self._make_dropdown(
            Gtk, ["fit", "fill", "tile"], self.settings.get("mode", "fill")
        )
        self._add_row(Gtk, page, "Background mode", mode_dropdown)

        loop_dropdown = self._make_dropdown(
            Gtk, ["forward", "pingpong"], self.settings.get("gif_loop_style", "forward")
        )
        self._add_row(Gtk, page, "GIF loop style", loop_dropdown)

        loop_hint = Gtk.Label(
            label="Ping-pong plays the GIF forward then back again (GTK 4). Holds every frame in memory.",
            xalign=0, wrap=True
        )
        loop_hint.add_css_class("dim-label")
        page.append(loop_hint)

        effect_dropdown = self._make_dropdown(
            Gtk, ["none", "grayscale", "sepia", "saturate", "hue-rotate", "invert"],
            self.settings.get("background_effect", DEFAULT_BACKGROUND_EFFECT)
        )
        self._add_row(Gtk, page, "Background effect", effect_dropdown)

        effect_control = self._make_effect_strength_control(Gtk, int(self.settings.get("effect_strength", DEFAULT_EFFECT_STRENGTH)))
        self._add_row(Gtk, page, "Effect strength", effect_control)

        effect_hint = Gtk.Label(
            label="Effects apply to the whole window, not just the background image.",
            xalign=0, wrap=True
        )
        effect_hint.add_css_class("dim-label")
        page.append(effect_hint)

        self._settings_widgets["enable_switch"] = enable_switch
        self._settings_widgets["mode_dropdown"] = mode_dropdown
        self._settings_widgets["gif_loop_style_dropdown"] = loop_dropdown
        self._settings_widgets["effect_dropdown"] = effect_dropdown

        return page

    def _build_overlay_page(self, Gtk, Gdk):

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        text_heading = Gtk.Label(xalign=0)
        text_heading.set_markup('<span size="large" weight="bold">Under-text readability tint</span>')
        page.append(text_heading)

        self._add_color_control(
            Gtk, Gdk, page, "Text tint color",
            self.settings.get("overlay_color", DEFAULT_OVERLAY_COLOR), "overlay_color"
        )

        text_opacity = self._make_opacity_control(
            Gtk, float(self.settings.get("overlay_opacity", DEFAULT_OVERLAY_OPACITY)), "opacity_scale"
        )
        self._add_row(Gtk, page, "Text tint opacity", text_opacity)

        overlay_image_heading = Gtk.Label(xalign=0)
        overlay_image_heading.set_markup('<span size="large" weight="bold">Overlay image</span>')
        overlay_image_heading.set_margin_top(6)
        page.append(overlay_image_heading)

        self._add_path_row(Gtk, page, "Overlay image", self.settings.get("overlay_image_path", ""), "overlay_image_path")

        overlay_image_opacity = self._make_opacity_control(
            Gtk, float(self.settings.get("overlay_image_opacity", DEFAULT_OVERLAY_IMAGE_OPACITY)), "overlay_image_opacity_scale"
        )
        self._add_row(Gtk, page, "Overlay image opacity", overlay_image_opacity)

        radius_spin = Gtk.SpinButton.new_with_range(0, 24, 1)
        radius_spin.set_digits(0)
        radius_spin.set_value(int(self.settings.get("overlay_radius", DEFAULT_OVERLAY_RADIUS)))
        radius_spin.set_width_chars(4)
        self._settings_widgets["overlay_radius_spin"] = radius_spin
        radius_box = Gtk.Box(spacing=8)
        radius_box.append(radius_spin)
        radius_box.append(Gtk.Label(label="px", xalign=0))
        self._add_row(Gtk, page, "Corner radius", radius_box)

        radius_hint = Gtk.Label(label="Max value is 24.", xalign=0)
        radius_hint.add_css_class("dim-label")
        page.append(radius_hint)

        return page

    def _build_titlebar_page(self, Gtk, Gdk):

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        self._add_path_row(
            Gtk, page, "Title bar image", self.settings.get("header_image_path", ""), "header_image_path",
            tooltip="Clear the path field to remove the image."
        )

        image_hint = Gtk.Label(
            label="With a title bar image set, the title bar cannot be made "
                  "transparent or translucent - the image fills the bar instead.",
            xalign=0, wrap=True
        )
        image_hint.add_css_class("dim-label")
        page.append(image_hint)

        header_box = self._make_opacity_control(
            Gtk, float(self.settings.get("header_overlay_opacity", DEFAULT_HEADER_OVERLAY_OPACITY)), "header_scale"
        )
        self._add_row(Gtk, page, "Title bar opacity", header_box)

        self._make_switch_row(
            Gtk, page, "Completely transparent title bar",
            self.settings.get("header_transparent", False), "header_transparent"
        )

        self._make_switch_row(
            Gtk, page, "Use solid title bar color",
            self.settings.get("header_color_enabled", False), "header_color_enabled"
        )

        self._add_color_control(
            Gtk, Gdk, page, "Title bar color",
            self.settings.get("header_color", DEFAULT_HEADER_COLOR), "header_color"
        )

        grab_header_button = Gtk.Button(label="Grab title bar color from background image")
        grab_header_button.connect("clicked", self._on_grab_header_color)
        page.append(grab_header_button)

        hint = Gtk.Label(
            label="The title bar is only themeable on the GTK 4 build.",
            xalign=0, wrap=True
        )
        hint.add_css_class("dim-label")
        page.append(hint)

        return page

    def _build_layout_page(self, Gtk, Gdk):

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        note = Gtk.Label(xalign=0, wrap=True)
        note.set_markup(
            '<span size="large" weight="bold">Settings moved to separate plugin '
            '"User-buddylist editor" by kiquja</span>'
        )
        note.set_margin_top(10)
        page.append(note)

        hint = Gtk.Label(
            label="Buddy-list and room user-list width / hide / drag controls now live in "
                  "the \"Buddy List / User List Editor\" plugin. Use /buddylist to open "
                  "its settings.",
            xalign=0, wrap=True
        )
        hint.add_css_class("dim-label")
        page.append(hint)

        return page

    def _build_accent_page(self, Gtk, Gdk):

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        accent_button = self._add_color_control(
            Gtk, Gdk, page, "Accent color", self.settings.get("accent_color", DEFAULT_ACCENT_COLOR), "accent"
        )

        grab_button = Gtk.Button(label="Grab colors from background image")
        grab_button.connect("clicked", self._on_grab_colors)
        page.append(grab_button)

        hint = Gtk.Label(
            label="Used for selections, switches, links and highlighted buttons. "
                  "\"Grab colors\" extracts an accent and a background color from the background image.",
            xalign=0, wrap=True
        )
        hint.add_css_class("dim-label")
        page.append(hint)

        return page

    def _ui_config(self):
        """Nicotine+'s shared UI config section (chat font/colors live here)."""

        if self.config is None:
            return {}

        return self.config.sections.get("ui", {}) or {}

    def _chat_color_value(self, key):

        entry = self._settings_widgets.get(f"{key}_entry")

        if entry is None:
            return ""

        return self._normalize_hex(entry.get_text()) or ""

    def _add_font_row(self, Gtk, page, label, config_key):

        entry = Gtk.Entry(hexpand=True, width_chars=24)
        entry.set_placeholder_text("e.g. Sans 10")
        entry.set_tooltip_text(CHAT_APPLY_TOOLTIP)
        entry.set_text(self._ui_config().get(config_key, "") or "")

        clear_button = Gtk.Button(label="Clear")
        clear_button.connect(
            "clicked", lambda _b, e=entry: (e.set_text(""), self._on_live_change())
        )

        box = Gtk.Box(spacing=8)
        box.append(entry)
        box.append(clear_button)
        self._add_row(Gtk, page, label, box)

        entry.connect("activate", lambda _e: self._on_live_change())
        focus_controller = Gtk.EventControllerFocus.new()
        entry.add_controller(focus_controller)
        focus_controller.connect("leave", lambda _controller: self._on_live_change())

        self._settings_widgets[f"{config_key}_entry"] = entry

        return entry

    def _build_chat_page(self, Gtk, Gdk):

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        ui = self._ui_config()

        outline_header = Gtk.Label(xalign=0)
        outline_header.set_markup(
            "<b>Text outline</b> <span size='small'>(all text in the program)</span> "
            "<span size='small' weight='bold' foreground='#c9862a'>— EXPERIMENTAL</span>"
        )
        page.append(outline_header)

        outline_switch = self._make_switch_row(
            Gtk, page, "Enable text outline",
            self.settings.get("text_outline_enabled", False), "text_outline_enabled"
        )
        outline_switch.set_tooltip_text(
            "Experimental. May cause system lag if a GIF is used as the background; "
            "thickness values above 2 px cause a lot of lag."
        )

        self._add_color_control(
            Gtk, Gdk, page, "Outline color",
            self.settings.get("text_outline_color", DEFAULT_TEXT_OUTLINE_COLOR), "text_outline_color"
        )

        outline_size = Gtk.SpinButton.new_with_range(1, 3, 1)
        outline_size.set_digits(0)
        outline_size.set_value(int(self.settings.get("text_outline_size", DEFAULT_TEXT_OUTLINE_SIZE)))
        outline_size.set_width_chars(4)
        self._settings_widgets["text_outline_size_spin"] = outline_size
        size_box = Gtk.Box(spacing=8)
        size_box.append(outline_size)
        size_box.append(Gtk.Label(label="px", xalign=0))
        self._add_row(Gtk, page, "Outline thickness", size_box)

        outline_hint = Gtk.Label(
            label="Note: the text outline adds some visual lag, since every text "
                  "element is re-rendered with a shadow on each change.",
            xalign=0, wrap=True
        )
        outline_hint.add_css_class("dim-label")
        page.append(outline_hint)

        for config_key, label in FONT_LABELS:
            self._add_font_row(Gtk, page, label, config_key)

        for widget_key, config_key, label, default_hex in COLOR_LABELS:
            initial = ui.get(config_key, "") or default_hex or ""
            self._add_chat_color_control(Gtk, Gdk, page, label, initial, widget_key)

        grab_button = Gtk.Button(label="Grab color from background image")
        grab_button.connect("clicked", self._on_grab_bg_color)

        grab_entry = Gtk.Entry(hexpand=True, width_chars=9)
        grab_entry.set_editable(False)
        grab_entry.set_placeholder_text("#RRGGBB")
        self._settings_widgets["grabbed_color_entry"] = grab_entry

        grab_box = Gtk.Box(spacing=8)
        grab_box.append(grab_button)
        grab_box.append(grab_entry)
        self._add_row(Gtk, page, "Background image color", grab_box)

        hint = Gtk.Label(
            label="These mirror Nicotine+'s chat/interface appearance settings. "
                  "Changes apply immediately - no restart needed. "
                  "Leave a field empty to use the theme default.",
            xalign=0, wrap=True
        )
        hint.add_css_class("dim-label")
        page.append(hint)

        return page

    def _build_presets_page(self, Gtk):

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        name_entry = Gtk.Entry(hexpand=True)
        name_entry.set_placeholder_text("Preset name")

        save_button = Gtk.Button(label="Save current as preset")
        save_button.connect("clicked", lambda _b, e=name_entry: self._on_preset_save(e))

        name_row = Gtk.Box(spacing=8)
        name_row.append(name_entry)
        name_row.append(save_button)
        page.append(name_row)

        listbox = Gtk.ListBox.new()
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        listbox.set_vexpand(True)
        listbox.set_size_request(-1, 140)
        self._settings_widgets["preset_listbox"] = listbox

        load_button = Gtk.Button(label="Load")
        remove_button = Gtk.Button(label="Remove")
        load_button.connect("clicked", lambda _b: self._on_preset_load(listbox))
        remove_button.connect("clicked", lambda _b: self._on_preset_remove(listbox))

        manage_row = Gtk.Box(spacing=8)
        manage_row.append(load_button)
        manage_row.append(remove_button)
        page.append(manage_row)

        export_button = Gtk.Button(label="Export selected…")
        import_button = Gtk.Button(label="Import…")
        export_button.connect("clicked", lambda _b: self._on_preset_export(listbox))
        import_button.connect("clicked", lambda _b: self._on_preset_import())

        share_row = Gtk.Box(spacing=8)
        share_row.append(export_button)
        share_row.append(import_button)
        page.append(share_row)

        share_hint = Gtk.Label(
            label="Export saves the selected preset (or the current settings) to a "
                  "shareable .json file. Import loads a preset .json file back in.",
            xalign=0, wrap=True
        )
        share_hint.add_css_class("dim-label")
        page.append(share_hint)

        page.append(listbox)

        hint = Gtk.Label(
            label="All saved presets are listed above. Select one, then press Load "
                  "to apply it or Remove to delete it. Presets are stored with this "
                  "plugin's settings.",
            xalign=0, wrap=True
        )
        hint.add_css_class("dim-label")
        page.append(hint)

        self._refresh_preset_list()

        return page

    def _presets_dict(self):

        raw = self.settings.get("presets", "{}") or "{}"

        try:
            data = json.loads(raw)
        except Exception:
            data = {}

        return data if isinstance(data, dict) else {}

    def _preset_name_list(self):

        return list(self._presets_dict().keys())

    def _selected_preset_name(self, listbox):

        row = listbox.get_selected_row()

        if row is None:
            return None

        names = self._preset_name_list()

        try:
            idx = row.get_index()
        except Exception:
            return None

        if idx < 0 or idx >= len(names):
            return None

        return names[idx]

    def _preset_settings(self):

        data = dict(self.settings)
        data.pop("presets", None)
        return data

    def _save_presets(self, data):

        self.settings["presets"] = json.dumps(data)

    def _on_preset_save(self, entry):

        name = (entry.get_text() or "").strip()

        if not name:
            self.output("Enter a preset name first.")
            return

        presets = self._presets_dict()
        presets[name] = self._preset_settings()
        self._save_presets(presets)
        entry.set_text("")
        self._refresh_preset_list()
        self.output("Preset saved: %s" % name)

    def _on_preset_load(self, listbox):

        name = self._selected_preset_name(listbox)

        if not name:
            self.output("Select a preset to load.")
            return

        data = self._presets_dict().get(name)

        if not isinstance(data, dict):
            self.output("Preset '%s' not found." % name)
            return

        self.settings.update(data)
        self._apply_theme()
        self.output("Preset loaded: %s" % name)
        self._rebuild_settings_window()

    def _on_preset_remove(self, listbox):

        name = self._selected_preset_name(listbox)

        if not name:
            self.output("Select a preset to remove.")
            return

        presets = self._presets_dict()
        presets.pop(name, None)
        self._save_presets(presets)
        self._refresh_preset_list()
        self.output("Preset removed: %s" % name)

    def _on_preset_export(self, listbox):

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]

        name = self._selected_preset_name(listbox)

        if name:
            data = self._presets_dict().get(name)
            payload = {"name": name, "settings": data if isinstance(data, dict) else {}}
            suggested = "%s.json" % name.strip().lower().replace(" ", "-")
        else:
            payload = {"name": "current", "settings": self._preset_settings()}
            suggested = "theme-preset.json"

        try:
            text = json.dumps(payload, indent=2, sort_keys=True)
        except Exception as exc:
            self.output("Could not serialize preset: %s" % (exc,))
            return

        chooser = Gtk.FileChooserNative(
            title="Export theme preset", action=Gtk.FileChooserAction.SAVE,
            accept_label="Save", cancel_label="Cancel"
        )

        file_filter = Gtk.FileFilter()
        file_filter.set_name("JSON preset (*.json)")
        file_filter.add_pattern("*.json")
        chooser.add_filter(file_filter)

        try:
            chooser.set_current_name(suggested)
            chooser.set_transient_for(self._settings_window)
        except Exception:
            pass

        def on_response(_dialog, response_id):
            try:
                if response_id == Gtk.ResponseType.ACCEPT:
                    file = chooser.get_file()

                    if file is not None:
                        path = file.get_path()

                        if path:
                            if not path.lower().endswith(".json"):
                                path += ".json"

                            with open(path, "w", encoding="utf-8") as handle:
                                handle.write(text)

                            self.output("Preset exported to %s" % path)
            except Exception as exc:
                self.output("Preset export failed: %s" % (exc,))
            finally:
                chooser.destroy()

        chooser.connect("response", on_response)
        chooser.show()

    def _on_preset_import(self):

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]

        chooser = Gtk.FileChooserNative(
            title="Import theme preset", action=Gtk.FileChooserAction.OPEN,
            accept_label="Open", cancel_label="Cancel"
        )

        file_filter = Gtk.FileFilter()
        file_filter.set_name("JSON preset (*.json)")
        file_filter.add_pattern("*.json")
        file_filter.add_pattern("*.txt")
        chooser.add_filter(file_filter)

        try:
            chooser.set_transient_for(self._settings_window)
        except Exception:
            pass

        def on_response(_dialog, response_id):
            try:
                if response_id != Gtk.ResponseType.ACCEPT:
                    return

                file = chooser.get_file()

                if file is None:
                    return

                path = file.get_path()

                if not path or not os.path.isfile(path):
                    return

                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)

                if isinstance(payload, dict) and isinstance(payload.get("settings"), dict):
                    name = str(payload.get("name") or "").strip() or os.path.splitext(os.path.basename(path))[0]
                    presets = self._presets_dict()
                    presets[name] = dict(payload["settings"])
                    presets[name].pop("presets", None)
                    self._save_presets(presets)
                    self._refresh_preset_list()
                    self.output("Preset imported: %s" % name)
                else:
                    self.output("Not a valid theme preset file: %s" % path)
            except Exception as exc:
                self.output("Preset import failed: %s" % (exc,))
            finally:
                chooser.destroy()

        chooser.connect("response", on_response)
        chooser.show()

    def _refresh_preset_list(self):

        listbox = self._settings_widgets.get("preset_listbox")

        if listbox is None:
            return

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]

        try:
            while True:
                row = listbox.get_row_at_index(0)

                if row is None:
                    break

                listbox.remove(row)
        except Exception:
            pass

        names = self._preset_name_list()

        if not names:
            try:
                empty_row = Gtk.ListBoxRow.new()
                empty_row.set_activatable(False)
                empty_row.set_selectable(False)
                empty_row.set_sensitive(False)
                empty_label = Gtk.Label(
                    label="(no presets)", xalign=0,
                    margin_top=6, margin_bottom=6, margin_start=6, margin_end=6
                )
                empty_label.add_css_class("dim-label")
                empty_row.set_child(empty_label)
                listbox.append(empty_row)
            except Exception:
                pass

            return

        try:
            for name in names:
                row = Gtk.ListBoxRow.new()
                label = Gtk.Label(
                    label=name, xalign=0,
                    margin_top=6, margin_bottom=6, margin_start=6, margin_end=6
                )
                row.set_child(label)
                listbox.append(row)
        except Exception:
            pass

    def _rebuild_settings_window(self):

        self._close_settings_window()
        self._open_settings()

    def _on_grab_colors(self, _button):

        gtk = self._get_gtk()

        if not gtk:
            return

        path = self._clean_path(self.settings.get("image_path", ""))

        if not path:
            self.output("Set a background image first, then grab colors.")
            return

        expanded = os.path.expanduser(path)

        if not os.path.isfile(expanded):
            self.output("Background image not found: %s" % expanded)
            return

        avg, vibrant = self._image_colors(expanded)

        if avg is None or vibrant is None:
            self.output("Could not read colors from the background image.")
            return

        accent_hex = "#%02x%02x%02x" % vibrant
        bg_hex = "#%02x%02x%02x" % avg

        self.settings["accent_color"] = accent_hex
        self.settings["color"] = bg_hex
        self._set_color_widget("accent", accent_hex)
        self._set_color_widget("bg_color", bg_hex)
        self._apply_theme()
        self.output("Grabbed accent %s and background %s from the image." % (accent_hex, bg_hex))

    def _on_grab_header_color(self, _button):
        """Sample the background image and use its dominant color for the title bar."""

        gtk = self._get_gtk()

        if not gtk:
            return

        path = self._clean_path(self.settings.get("image_path", ""))

        if not path:
            self.output("Set a background image first, then grab a title bar color.")
            return

        expanded = os.path.expanduser(path)

        if not os.path.isfile(expanded):
            self.output("Background image not found: %s" % expanded)
            return

        avg, vibrant = self._image_colors(expanded)

        if avg is None or vibrant is None:
            self.output("Could not read colors from the background image.")
            return

        # The vibrant/dominant color reads best as a title bar tint.
        header_hex = "#%02x%02x%02x" % vibrant

        self.settings["header_color"] = header_hex
        self.settings["header_color_enabled"] = True
        self.settings["header_transparent"] = False
        self._set_color_widget("header_color", header_hex)

        header_switch = self._settings_widgets.get("header_color_enabled")

        if header_switch is not None:
            try:
                header_switch.set_active(True)
            except Exception:
                pass

        transparent_switch = self._settings_widgets.get("header_transparent")

        if transparent_switch is not None:
            try:
                transparent_switch.set_active(False)
            except Exception:
                pass

        self._apply_theme()
        self.output("Grabbed title bar color %s from the background image." % header_hex)

    def _on_grab_bg_color(self, _button):
        """Sample the background image and show its dominant color in a read-only field."""

        gtk = self._get_gtk()

        if not gtk:
            return

        path = self._clean_path(self.settings.get("image_path", ""))

        if not path:
            self.output("Set a background image first, then grab its color.")
            return

        expanded = os.path.expanduser(path)

        if not os.path.isfile(expanded):
            self.output("Background image not found: %s" % expanded)
            return

        avg, vibrant = self._image_colors(expanded)

        if avg is None or vibrant is None:
            self.output("Could not read colors from the background image.")
            return

        hex_value = "#%02x%02x%02x" % vibrant

        entry = self._settings_widgets.get("grabbed_color_entry")

        if entry is not None:
            entry.set_text(hex_value)

        self.output("Background image color: %s" % hex_value)

    def _set_color_widget(self, key, hex_value):

        gtk = self._get_gtk()

        if not gtk:
            return

        try:
            rgba = self._parse_rgba(gtk["Gdk"], hex_value)
        except Exception:
            return

        button = self._settings_widgets.get(f"{key}_button")
        entry = self._settings_widgets.get(f"{key}_entry")

        try:
            if button is not None:
                button.set_rgba(rgba)

            if entry is not None:
                entry.set_text(hex_value)
        except Exception:
            pass

    def _image_colors(self, path):

        try:
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
        except Exception:
            return None, None

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except Exception:
            return None, None

        width = pixbuf.get_width()
        height = pixbuf.get_height()

        if width <= 0 or height <= 0:
            return None, None

        scale = min(1.0, 48.0 / max(width, height))
        scaled_width = max(1, int(width * scale))
        scaled_height = max(1, int(height * scale))

        try:
            small = pixbuf.scale_simple(scaled_width, scaled_height, GdkPixbuf.InterpType.BILINEAR)
        except Exception:
            small = pixbuf

        n_channels = small.get_n_channels()
        rowstride = small.get_rowstride()
        scaled_width = small.get_width()
        scaled_height = small.get_height()
        pixels = small.get_pixels()

        rsum = gsum = bsum = 0
        count = 0
        best = None
        best_score = -1.0

        for y in range(scaled_height):
            base = y * rowstride

            for x in range(scaled_width):
                offset = base + x * n_channels
                r = pixels[offset]
                g = pixels[offset + 1]
                b = pixels[offset + 2]

                rsum += r
                gsum += g
                bsum += b
                count += 1

                maximum = max(r, g, b)
                minimum = min(r, g, b)
                saturation = maximum - minimum
                luminance = (maximum + minimum) / 2.0
                score = saturation * 3.0 - abs(luminance - 128.0) * 0.4

                if score > best_score:
                    best_score = score
                    best = (r, g, b)

        if count == 0:
            return None, None

        return (rsum // count, gsum // count, bsum // count), best

    def _add_row(self, Gtk, container, label_text, control):

        row = Gtk.Box(spacing=12)
        row.set_hexpand(True)
        label = Gtk.Label(label=label_text, xalign=0, wrap=True)
        label.set_max_width_chars(28)
        label.set_size_request(180, -1)
        label.set_valign(Gtk.Align.CENTER)
        row.append(label)
        row.append(control)
        container.append(row)
        return row

    def _add_path_row(self, Gtk, page, label, initial, key, tooltip=None):

        box = Gtk.Box(spacing=8)

        entry = Gtk.Entry(hexpand=True, width_chars=32)
        entry.set_placeholder_text("Path to image or video…")
        entry.set_text(initial)

        if tooltip:
            entry.set_tooltip_text(tooltip)

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

    def _add_chat_color_control(self, Gtk, Gdk, page, label, initial_hex, key):

        box = Gtk.Box(spacing=8)

        button = Gtk.ColorButton()
        self._set_color_dialog(Gtk, button)
        button.set_rgba(self._parse_rgba(Gdk, initial_hex or "#000000"))
        button.set_tooltip_text(CHAT_APPLY_TOOLTIP)

        entry = Gtk.Entry(hexpand=True, width_chars=9)
        entry.set_placeholder_text("default")
        entry.set_tooltip_text(CHAT_APPLY_TOOLTIP)
        entry.set_text(initial_hex or "")

        def on_button(_button, _pspec, e=entry):
            e.set_text(self._rgba_to_hex(_button.get_rgba()))

        def on_entry_leave(_controller, e=entry, b=button):
            hex_value = self._normalize_hex(e.get_text())

            if hex_value:
                b.set_rgba(self._parse_rgba(Gdk, hex_value))

            self._on_live_change()

        button.connect("notify::rgba", on_button)
        entry.connect("activate", lambda _e: on_entry_leave(None))
        focus_controller = Gtk.EventControllerFocus.new()
        entry.add_controller(focus_controller)
        focus_controller.connect("leave", on_entry_leave)

        box.append(button)
        box.append(entry)
        self._add_row(Gtk, page, label, box)

        self._settings_widgets[f"{key}_button"] = button
        self._settings_widgets[f"{key}_entry"] = entry

        return button

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

    def _make_effect_strength_control(self, Gtk, value):

        box = Gtk.Box(spacing=8)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_digits(0)
        scale.set_hexpand(True)
        scale.set_value(value)

        spin = Gtk.SpinButton.new_with_range(0, 100, 1)
        spin.set_digits(0)
        spin.set_width_chars(5)
        spin.set_value(value)

        label = Gtk.Label(label=f"{int(value)}%", width_chars=5, xalign=1)

        def sync_from_scale(s, s_spin=spin, s_label=label):
            v = int(round(s.get_value()))

            if s_spin.get_value_as_int() != v:
                s_spin.set_value(v)

            s_label.set_text(f"{v}%")

        def sync_from_spin(sp, sp_scale=scale, sp_label=label):
            v = sp.get_value_as_int()

            if int(round(sp_scale.get_value())) != v:
                sp_scale.set_value(v)

            sp_label.set_text(f"{v}%")

        scale.connect("value-changed", sync_from_scale)
        spin.connect("value-changed", sync_from_spin)

        box.append(scale)
        box.append(spin)
        box.append(label)

        self._settings_widgets["effect_strength_scale"] = scale
        self._settings_widgets["effect_strength_spin"] = spin

        return box

    # settings commit / actions ----------------------------------------------

    def _dropdown_value(self, dropdown):

        item = dropdown.get_selected_item()

        if item is not None:
            return item.get_string()

        return ""

    def _read_and_commit(self):

        if self._applying:
            return

        widgets = self._settings_widgets

        if not widgets or "enable_switch" not in widgets:
            return

        self._applying = True

        try:

            # Sync any pending hex entries into the color buttons.
            for key in ("bg_color", "overlay_color", "accent", "header_color", "text_outline_color", "find_color", "find_gradient_color", "findbar_color"):
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
                "image_path": widgets.get("image_path", self.settings.get("image_path", "")),
                "color": self._rgba_to_hex(widgets["bg_color_button"].get_rgba()),
                "mode": self._dropdown_value(widgets["mode_dropdown"]),
                "gif_loop_style": self._dropdown_value(widgets["gif_loop_style_dropdown"]),
                "background_effect": self._dropdown_value(widgets["effect_dropdown"]),
                "effect_strength": int(round(widgets["effect_strength_scale"].get_value())),
                "overlay_color": self._rgba_to_hex(widgets["overlay_color_button"].get_rgba()),
                "overlay_opacity": widgets["opacity_scale"].get_value(),
                "overlay_image_path": widgets.get("overlay_image_path", ""),
                "overlay_image_opacity": widgets["overlay_image_opacity_scale"].get_value(),
                "overlay_radius": int(round(widgets["overlay_radius_spin"].get_value())),
                "header_image_path": widgets.get("header_image_path", ""),
                "header_overlay_opacity": widgets["header_scale"].get_value(),
                "header_transparent": widgets["header_transparent"].get_active(),
                "header_color_enabled": widgets["header_color_enabled"].get_active(),
                "header_color": self._rgba_to_hex(widgets["header_color_button"].get_rgba()),
                "text_outline_enabled": widgets["text_outline_enabled"].get_active(),
                "text_outline_color": self._rgba_to_hex(widgets["text_outline_color_button"].get_rgba()),
                "text_outline_size": int(round(widgets["text_outline_size_spin"].get_value())),
                "accent_color": self._rgba_to_hex(widgets["accent_button"].get_rgba()),
                "findbar_color": self._rgba_to_hex(widgets["findbar_color_button"].get_rgba()),
                "find_enabled": widgets["find_enabled"].get_active(),
                "find_style": self._dropdown_value(widgets["find_style_dropdown"]),
                "find_color": self._rgba_to_hex(widgets["find_color_button"].get_rgba()),
                "find_gradient_color": self._rgba_to_hex(widgets["find_gradient_color_button"].get_rgba()),
                "find_highlight_all": widgets["find_highlight_all"].get_active(),
            })

            if self.config is not None:
                ui = self.config.sections.setdefault("ui", {})

                for config_key in FONT_SELECTORS:
                    entry = widgets.get(f"{config_key}_entry")

                    if entry is not None:
                        ui[config_key] = entry.get_text()

                for widget_key, config_key, _label, _default in COLOR_LABELS:
                    ui[config_key] = self._chat_color_value(widget_key)

            self._apply_theme()
            self._refresh_chat_tag_colors()
        finally:
            self._applying = False

    def _refresh_chat_tag_colors(self):
        """Re-apply Nicotine+'s chat tag colors (usernames, /me, highlights, URLs)."""

        gtk = self._get_gtk()

        if not gtk:
            return

        try:
            from pynicotine.gtkgui.widgets.theme import update_tag_visuals
        except Exception:
            return

        Gtk = gtk["Gtk"]
        window = self._find_main_window(Gtk)

        if window is None:
            return

        for widget in self._walk(Gtk, window):
            if not isinstance(widget, Gtk.TextView):
                continue

            try:
                buf = widget.get_buffer()
            except Exception:
                continue

            if buf is None:
                continue

            tag_table = buf.get_tag_table()

            if tag_table is None:
                continue

            def _refresh(tag, _visuals=update_tag_visuals):
                try:
                    color_id = getattr(tag, "color_id", None)

                    if color_id:
                        _visuals(tag, color_id)
                except Exception:
                    pass

            try:
                tag_table.foreach(_refresh)
            except Exception:
                continue

    def _on_settings_apply(self, *_args):
        self._read_and_commit()

    def _on_settings_ok(self, *_args):

        self._read_and_commit()

        if self._settings_window is not None:
            self._settings_window.close()

    def _on_settings_cancel(self, *_args):

        if self._settings_window is not None:
            self._settings_window.close()

    def _on_settings_close_button(self, *_args):

        if self._settings_window is not None:
            self._settings_window.close()

    def _connect_live(self, Gtk):
        """Connect settings widgets so changes apply immediately (debounced)."""

        for key, widget in self._settings_widgets.items():
            if key == "preset_listbox" or key.endswith("_entry"):
                continue

            if isinstance(widget, Gtk.Switch):
                widget.connect("notify::active", self._on_live_change)
            elif isinstance(widget, Gtk.DropDown):
                widget.connect("notify::selected", self._on_live_change)
            elif isinstance(widget, Gtk.Scale):
                widget.connect("value-changed", self._on_live_change)
            elif isinstance(widget, Gtk.SpinButton):
                widget.connect("value-changed", self._on_live_change)
            elif isinstance(widget, Gtk.ColorButton):
                widget.connect("notify::rgba", self._on_live_change)

    def _on_live_change(self, *_args):
        """Debounced immediate-apply trigger (no-op while committing)."""

        if self._applying:
            return

        self._schedule_live_apply()

    def _schedule_live_apply(self):

        if self._gtk is None or not self._gtk:
            return

        GLib = self._gtk["GLib"]

        if self._live_timeout is not None:
            try:
                GLib.source_remove(self._live_timeout)
            except Exception:
                pass

        self._live_timeout = GLib.timeout_add(300, self._live_apply)

    def _live_apply(self):

        self._live_timeout = None
        self._read_and_commit()
        return False

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
            "*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.svg", "*.webp", "*.tiff"
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

        self._on_live_change()

    def _on_settings_closed(self, *_args):

        self._remove_swatch_provider()
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
                f"    {self._background_filter_css(config)}\n"
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
                f"    {self._background_filter_css(config)}\n"
                f"}}"
            )

        rules.append(f".{CSS_CLASS_TRANSPARENT} {{ background-color: transparent; }}")
        rules.append(f".{CSS_CLASS_OVERLAY} {{ {self._overlay_css(config)} }}")

        rules.append(f".{CSS_CLASS_HEADER} {{ {self._header_css(config)} }}")
        rules.append(f".{CSS_CLASS_FILTER} {{ {self._ui_filter_css(config)} }}")
        rules.append(
            "searchbar, searchbar > revealer, searchbar > revealer > box "
            f"{{ background-color: {config['findbar_color']} !important; background-image: none !important; }}"
        )

        if config.get("text_outline_enabled"):
            outline = self._text_outline_shadows(config["text_outline_color"], config["text_outline_size"])
            rules.append(f"{TEXT_OUTLINE_SELECTOR} {{ text-shadow: {outline}; }}")

        ui_fonts = config.get("ui_fonts", {})

        for key, selector in FONT_SELECTORS.items():
            font_css = self._font_css(selector, ui_fonts.get(key, "") or "")

            if font_css:
                rules.append(font_css)

        color_css = self._chat_color_css(config.get("ui_colors", {}))

        if color_css:
            rules.append(color_css)

        return "\n".join(rules)

    def _background_filter_css(self, config):
        """Filter applied to the background layer, scaled by effect strength."""

        effect = config.get("background_effect") or "none"

        if effect == "none":
            return "filter: none;"

        strength = max(0, min(100, int(config.get("effect_strength") or 0)))
        ratio = strength / 100.0

        if effect == "blur":
            # Blur is rendered via Gtk.Snapshot.push_blur() on the background
            # picture (GTK 4), never as a CSS filter. A CSS blur would smear the
            # entire window and, on the CSS fallback path, hit window + root.
            return "filter: none;"

        if effect == "grayscale":
            return f"filter: grayscale({ratio:.2f});"

        if effect == "sepia":
            return f"filter: sepia({ratio:.2f});"

        if effect == "saturate":
            return f"filter: saturate({1 + ratio:.2f});"

        if effect == "hue-rotate":
            return f"filter: hue-rotate({ratio * 180:.0f}deg);"

        if effect == "invert":
            return f"filter: invert({ratio:.2f});"

        return "filter: none;"

    def _ui_filter_css(self, config):
        """Background effects now apply to the background layer only."""

        return "filter: none;"

    def _chat_color_css(self, colors):
        """CSS for Nicotine+'s chat/interface colors (mirrors theme._get_custom_color_css)."""

        rules = []

        online = self._normalize_hex(colors.get("useronline", ""))
        away = self._normalize_hex(colors.get("useraway", ""))
        offline = self._normalize_hex(colors.get("useroffline", ""))

        if online and away and offline:
            rules.append(
                f".user-status {{ -gtk-icon-palette: success {online}, warning {away}, error {offline}; }}"
            )

        for selector, key in (
            (".notebook-tab", "tab_default"),
            (".notebook-tab-changed", "tab_changed"),
            (".notebook-tab-highlight", "tab_hilite"),
            ("entry", "inputcolor"),
            ("treeview .cell:not(:disabled):not(:selected):not(.progressbar)", "search"),
        ):
            color = self._normalize_hex(colors.get(key, ""))

            if color:
                rules.append(f"{selector} {{ color: {color}; }}")

        textbg = self._normalize_hex(colors.get("textbg", ""))

        if textbg:
            rules.append(f"entry {{ background: {textbg}; }}")

        if self._normalize_hex(colors.get("search", "")):
            rules.append("treeview header { color: initial; }")

        # Force tree views to re-render with the new colors (GTK caches them
        # until the cursor moves over the widget otherwise).
        rules.append(
            "treeview { caret-color: #%06x; }\n"
            "treeview popover { caret-color: initial; }" % random.randint(0, 0xFFFFFF)
        )

        return "\n".join(rules)

    def _font_css(self, selector, font):

        if not font:
            return ""

        try:
            from gi.repository import Pango

            desc = Pango.FontDescription.from_string(font)
        except Exception:
            return ""

        family = desc.get_family()
        size = desc.get_size()

        if not family and not size:
            return ""

        parts = []

        if family:
            parts.append(f"font-family: '{family}';")

        if size:
            parts.append(f"font-size: {size // 1024}pt;")

        if not parts:
            return ""

        return f"{selector} {{ " + " ".join(parts) + " }"

    def _overlay_css(self, config):
        """Readability tint drawn under text."""

        radius = max(0, int(config.get("overlay_radius", 0) or 0))
        radius_css = f" border-radius: {radius}px;" if radius > 0 else ""

        return f"background-color: {self._color_to_rgba(config['overlay_color'], config['overlay_opacity'])};{radius_css}"

    def _header_css(self, config):

        if config.get("header_transparent"):
            return self._header_blend_css(config)

        if config.get("header_color_enabled") and config.get("header_color"):
            return (
                f"background-color: {self._color_to_rgba(config['header_color'], config['header_overlay_opacity'])}; "
                "background-image: none; box-shadow: none;"
            )

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

    def _header_blend_css(self, config):
        """Match the title bar to the content background so it looks transparent."""

        if config.get("type") == "color":
            color = config.get("bg_color") or DEFAULT_COLOR
            return f"background-color: {color}; background-image: none; box-shadow: none;"

        uri = config.get("uri") or ""

        if not uri:
            return "background-color: transparent; background-image: none; box-shadow: none;"

        return (
            f"background-image: url(\"{uri}\"); "
            "background-size: cover; "
            "background-repeat: no-repeat; "
            "background-position: center top; "
            "box-shadow: none;"
        )

    @staticmethod
    def _text_outline_shadows(color, size):
        """Return a text-shadow value that draws an outline around text."""

        s = max(1, int(size or 1))
        parts = []

        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue

                parts.append(f"{dx * s}px {dy * s}px 0 {color}")

        return ", ".join(parts)

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

    # --- Find highlight -------------------------------------------------------

    def _find_is_enabled(self):
        return bool(self.settings.get("find_enabled", True))

    def _find_valid_color(self, hexstr):
        return self._normalize_hex(hexstr) or DEFAULT_FIND_COLOR

    @staticmethod
    def _hue_to_hex(hue):
        red, green, blue = colorsys.hsv_to_rgb((hue % 360) / 360.0, 1.0, 1.0)
        return "#%02X%02X%02X" % (round(red * 255), round(green * 255), round(blue * 255))

    def _hex_to_hue(self, color):
        red, green, blue = self._hex_to_rgb(color)
        hue, _s, _v = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
        return round(hue * 360)

    @staticmethod
    def _lerp_rgb(rgb1, rgb2, t):
        return (
            round(rgb1[0] + (rgb2[0] - rgb1[0]) * t),
            round(rgb1[1] + (rgb2[1] - rgb1[1]) * t),
            round(rgb1[2] + (rgb2[2] - rgb1[2]) * t),
        )

    @staticmethod
    def _rgb_to_hex(rgb):
        return "#%02X%02X%02X" % rgb

    def _find_clear_highlights(self, buffer):

        collected = []

        def collect(tag, *_args):
            name = tag.props.name or ""

            if name.startswith(FIND_TAG_PREFIX):
                collected.append(tag)

        try:
            table = buffer.get_tag_table()
            table.foreach(collect)

            for tag in collected:
                table.remove(tag)
        except Exception:
            pass

    def _find_apply_color_tag(self, buffer, start, end, color):

        gtk = self._get_gtk()

        if not gtk:
            return

        Gdk = gtk["Gdk"]
        name = f"{FIND_TAG_PREFIX}:{color[1:]}"

        background = Gdk.RGBA()

        if not background.parse(color):
            return

        foreground = Gdk.RGBA()
        foreground.parse(self._contrast_fg(color))

        try:
            table = buffer.get_tag_table()
            tag = table.lookup(name)

            if tag is None:
                tag = buffer.create_tag(name)

            # Nicotine+ 3.3.x's TextView.update_tag() reads tag.color_id on every
            # theme/color refresh. A tag without this attribute crashes that loop.
            tag.color_id = name
            tag._nplus_find_highlight = True

            tag.props.background_rgba = background
            tag.props.foreground_rgba = foreground
            buffer.apply_tag(tag, start, end)
        except Exception:
            pass

    def _find_apply_highlight(self, buffer, start, end):

        style = self.settings.get("find_style", "solid")

        if style == "rainbow":
            self._find_apply_color_sweep(buffer, start, end, lambda t: self._hue_to_hex(round(t * 359)))
        elif style == "gradient":
            rgb1 = self._hex_to_rgb(self._find_valid_color(self.settings.get("find_color")))
            rgb2 = self._hex_to_rgb(self._find_valid_color(self.settings.get("find_gradient_color")))
            self._find_apply_color_sweep(
                buffer, start, end,
                lambda t, r1=rgb1, r2=rgb2: self._rgb_to_hex(self._lerp_rgb(r1, r2, t))
            )
        else:
            color = self._find_valid_color(self.settings.get("find_color"))
            self._find_apply_color_tag(buffer, start, end, color)

    def _find_apply_color_sweep(self, buffer, start, end, color_func):

        start_offset = start.get_offset()
        end_offset = end.get_offset()

        if end_offset <= start_offset:
            return

        length = end_offset - start_offset
        current = start.copy()
        chunks = 0

        while current.get_offset() < end_offset and chunks < FIND_SWEEP_MAX_CHUNKS:
            nxt = current.copy()
            nxt.forward_chars(FIND_SWEEP_CHUNK)

            if nxt.get_offset() > end_offset:
                nxt = end.copy()

            t = (current.get_offset() - start_offset) / float(length)
            self._find_apply_color_tag(buffer, current, nxt, color_func(t))

            current = nxt
            chunks += 1

    def _find_highlight_all(self, buffer, query, current):

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]
        flags = Gtk.TextSearchFlags.TEXT_ONLY | Gtk.TextSearchFlags.CASE_INSENSITIVE
        start = buffer.get_start_iter()
        guard = 0

        while guard < 100000:
            guard += 1

            match = start.forward_search(query, flags, None)

            if not match or len(match) != 2:
                break

            match_start, match_end = match

            if not (current and match_start.equal(current[0]) and match_end.equal(current[1])):
                self._find_apply_highlight(buffer, match_start, match_end)

            if match_end.equal(start) or match_end.is_end():
                break

            start = match_end

    def _find_deselect(self, buffer):

        try:
            mark = buffer.get_insert()
            iterator = buffer.get_iter_at_mark(mark)
            buffer.place_cursor(iterator)
        except Exception:
            pass

    def _find_patch(self):

        if self._find_patched:
            return

        try:
            from pynicotine.gtkgui.widgets.textentry import TextSearchBar
        except Exception as error:
            self.log("Could not patch the find search bar (find highlighting disabled): %s", (error,))
            return

        plugin = self
        original_match = TextSearchBar.on_search_match
        original_visible = TextSearchBar.set_visible

        def patched_match(search_bar, search_type, restarted=False):
            try:
                if not search_bar.search_bar.get_search_mode():
                    original_match(search_bar, search_type, restarted)
                    return

                buffer = search_bar.textview.get_buffer()
                query = search_bar.entry.get_text()

                plugin._find_clear_highlights(buffer)
                original_match(search_bar, search_type, restarted)

                if not plugin._find_is_enabled() or not query:
                    return

                bounds = buffer.get_selection_bounds()

                if not bounds:
                    return

                plugin._find_apply_highlight(buffer, bounds[0], bounds[1])

                if plugin.settings.get("find_highlight_all", False):
                    plugin._find_highlight_all(buffer, query, bounds)

                plugin._find_deselect(buffer)
            except Exception as error:
                plugin.log("Highlight error: %s", (error,))

        def patched_visible(search_bar, visible):
            original_visible(search_bar, visible)

            if not visible:
                try:
                    plugin._find_clear_highlights(search_bar.textview.get_buffer())
                except Exception:
                    pass

        TextSearchBar.on_search_match = patched_match
        TextSearchBar.set_visible = patched_visible

        self._find_patched = True
        self._find_original_match = original_match
        self._find_original_visible = original_visible

    def _find_unpatch(self):

        if not self._find_patched:
            return

        try:
            from pynicotine.gtkgui.widgets.textentry import TextSearchBar

            TextSearchBar.on_search_match = self._find_original_match
            TextSearchBar.set_visible = self._find_original_visible
        except Exception:
            pass

        self._find_patched = False
        self._find_original_match = None
        self._find_original_visible = None

    def _find_patch_context_menu(self):

        if self._find_menu_patched:
            return

        try:
            from pynicotine.gtkgui.widgets.textview import TextView
        except Exception as error:
            self.log("Could not patch the textview context menu (Clear Highlight unavailable): %s", (error,))
            return

        plugin = self
        original = TextView.on_pressed_secondary

        def patched_secondary(tv_self, controller, num_p, x, y):
            try:
                if not tv_self.textbuffer.get_has_selection() and plugin._find_has_highlight_at(tv_self, x, y):
                    plugin._find_show_clear_menu(tv_self, controller, x, y)
                    return True
            except Exception:
                pass

            return original(tv_self, controller, num_p, x, y)

        TextView.on_pressed_secondary = patched_secondary

        self._find_menu_patched = True
        self._find_original_secondary = original

    def _find_unpatch_context_menu(self):

        if not self._find_menu_patched:
            return

        try:
            from pynicotine.gtkgui.widgets.textview import TextView

            if self._find_original_secondary is not None:
                TextView.on_pressed_secondary = self._find_original_secondary
        except Exception:
            pass

        self._find_menu_patched = False
        self._find_original_secondary = None
        self._find_clear_menu_widget = None

    def _find_has_highlight_at(self, tv_self, x, y):

        try:
            for tag in tv_self.get_tags_for_pos(x, y):
                if getattr(tag, "_nplus_find_highlight", False):
                    return True
        except Exception:
            pass

        return False

    def _find_show_clear_menu(self, tv_self, controller, x, y):

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]
        Gdk = gtk["Gdk"]

        try:
            buffer = tv_self.textbuffer
        except Exception:
            return

        def do_clear(*_args):
            try:
                self._find_clear_highlights(buffer)
            except Exception:
                pass

            widget = getattr(self, "_find_clear_menu_widget", None)

            if widget is not None and Gtk.get_major_version() >= 4:
                try:
                    widget.popdown()
                except Exception:
                    pass

        try:
            if Gtk.get_major_version() >= 4:
                try:
                    parent = tv_self.widget.get_ancestor(Gtk.Box)
                except Exception:
                    parent = tv_self.widget

                popover = Gtk.Popover()
                popover.set_parent(parent)
                popover.set_has_arrow(False)

                vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                button = Gtk.Button(label="Clear Highlight")
                button.set_has_frame(False)
                button.set_halign(Gtk.Align.FILL)
                button.connect("clicked", do_clear)
                vbox.append(button)

                popover.set_child(vbox)

                rectangle = Gdk.Rectangle()
                rectangle.x = x
                rectangle.y = y
                rectangle.width = 4
                rectangle.height = 4
                popover.set_pointing_to(rectangle)
                popover.popup()

                self._find_clear_menu_widget = popover
            else:
                menu = Gtk.Menu()
                item = Gtk.MenuItem(label="Clear Highlight")
                item.connect("activate", do_clear)
                menu.append(item)
                menu.show_all()

                event = None

                if controller is not None:
                    try:
                        sequence = controller.get_current_sequence()

                        if sequence is not None:
                            event = controller.get_last_event(sequence)
                    except Exception:
                        event = None

                menu.popup_at_pointer(event)
                self._find_clear_menu_widget = menu
        except Exception as error:
            self.log("Could not show the Clear Highlight menu: %s", (error,))

    def _build_highlight_page(self, Gtk, Gdk):

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        findbar_heading = Gtk.Label(xalign=0)
        findbar_heading.set_markup('<span size="large" weight="bold">Find bar (Ctrl+F)</span>')
        page.append(findbar_heading)

        self._add_color_control(
            Gtk, Gdk, page, "Find bar color",
            self.settings.get("findbar_color", DEFAULT_FINDBAR_COLOR), "findbar_color"
        )

        findbar_hint = Gtk.Label(
            label="Background color of the search bar that slides down on Ctrl+F.",
            xalign=0, wrap=True
        )
        findbar_hint.add_css_class("dim-label")
        page.append(findbar_hint)

        self._make_switch_row(
            Gtk, page, "Enable find highlighting",
            self.settings.get("find_enabled", True), "find_enabled"
        )

        style_dropdown = self._make_dropdown(
            Gtk, list(FIND_STYLES), self.settings.get("find_style", "solid")
        )
        self._add_row(Gtk, page, "Highlight style", style_dropdown)
        self._settings_widgets["find_style_dropdown"] = style_dropdown

        # Live preview swatch
        swatch = Gtk.Label(label="Solid", xalign=0.5, yalign=0.5)
        swatch.set_hexpand(True)
        self._add_class(Gtk, swatch, SWATCH_CLASS)
        page.append(swatch)
        self._settings_widgets["find_swatch"] = swatch

        # Primary color hue slider
        hue_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 360, 1)
        hue_scale.set_hexpand(True)
        hue_scale.set_digits(0)
        hue_scale.set_draw_value(True)
        page.append(hue_scale)
        self._settings_widgets["find_hue_scale"] = hue_scale

        hue_hint = Gtk.Label(label="Primary color hue (0\u2013360\u00b0)", xalign=0)
        hue_hint.add_css_class("dim-label")
        page.append(hue_hint)

        self._add_color_control(
            Gtk, Gdk, page, "Highlight color",
            self.settings.get("find_color", DEFAULT_FIND_COLOR), "find_color"
        )

        gradient_button = self._add_color_control(
            Gtk, Gdk, page, "End color",
            self.settings.get("find_gradient_color", DEFAULT_FIND_GRADIENT_COLOR), "find_gradient_color"
        )

        # Keep a reference to the row holding the gradient control so it can be
        # shown/hidden when the style changes.
        try:
            gradient_row = gradient_button.get_parent().get_parent()
        except Exception:
            gradient_row = None
        self._settings_widgets["find_gradient_row"] = gradient_row

        self._make_switch_row(
            Gtk, page, "Highlight all matches",
            self.settings.get("find_highlight_all", False), "find_highlight_all"
        )

        hint = Gtk.Label(
            label="Solid uses one color, Rainbow sweeps the full hue wheel, and Gradient blends "
                  "from Highlight color to End color. Changes apply to the next find. "
                  "Right-click a highlighted match to Clear Highlight.",
            xalign=0, wrap=True
        )
        hint.add_css_class("dim-label")
        page.append(hint)

        effects_hint = Gtk.Label(
            label="Note: the Background effects (grayscale, sepia, hue-rotate, etc.) also "
                  "affect the highlight color, since they filter the whole window.",
            xalign=0, wrap=True
        )
        effects_hint.add_css_class("dim-label")
        page.append(effects_hint)

        # Live preview wiring (immediate, independent of the debounced apply)
        style_dropdown.connect("notify::selected", lambda *_a: self._sync_find_widgets())
        hue_scale.connect("value-changed", self._on_find_hue_changed)
        self._settings_widgets["find_color_button"].connect("notify::rgba", lambda *_a: self._sync_find_widgets())
        self._settings_widgets["find_gradient_color_button"].connect("notify::rgba", lambda *_a: self._sync_find_widgets())

        self._sync_find_widgets()

        return page

    def _sync_find_widgets(self):

        widgets = self._settings_widgets

        if "find_swatch" not in widgets or "find_hue_scale" not in widgets:
            return

        style = self._dropdown_value(widgets["find_style_dropdown"])
        color = self._rgba_to_hex(widgets["find_color_button"].get_rgba())
        color2 = self._rgba_to_hex(widgets["find_gradient_color_button"].get_rgba())

        # Hue slider follows the primary color (guarded so it doesn't re-enter).
        self._find_syncing = True
        try:
            widgets["find_hue_scale"].set_value(self._hex_to_hue(color))
        finally:
            self._find_syncing = False

        if style == "gradient":
            text = f"Gradient  {color} \u2192 {color2}"
            image = f"linear-gradient(to right, {color}, {color2})"
        elif style == "rainbow":
            text = "Rainbow"
            image = "linear-gradient(to right, #FF0000, #FFFF00, #00FF00, #00FFFF, #0000FF, #FF00FF)"
        else:
            text = f"Solid  {color}"
            image = None

        widgets["find_swatch"].set_text(text)
        self._apply_swatch_css(color, image)

        row = widgets.get("find_gradient_row")
        if row is not None:
            row.set_visible(style == "gradient")

    def _on_find_hue_changed(self, scale):

        if self._find_syncing:
            return

        gtk = self._get_gtk()

        if not gtk:
            return

        widgets = self._settings_widgets
        color = self._hue_to_hex(scale.get_value())
        button = widgets.get("find_color_button")
        entry = widgets.get("find_color_entry")

        self._find_syncing = True
        try:
            if button is not None:
                button.set_rgba(self._parse_rgba(gtk["Gdk"], color))
            if entry is not None:
                entry.set_text(color)
        finally:
            self._find_syncing = False

        self._sync_find_widgets()

    def _apply_swatch_css(self, color, image):

        gtk = self._get_gtk()

        if not gtk:
            return

        Gtk = gtk["Gtk"]
        Gdk = gtk["Gdk"]

        css = f".{SWATCH_CLASS} {{\n"
        css += f"  background-color: {color};\n"

        if image:
            css += f"  background-image: {image};\n"

        css += f"  color: {self._contrast_fg(color)};\n"
        css += "  min-height: 22px;\n"
        css += "  min-width: 64px;\n"
        css += "  border: 1px solid rgba(128,128,128,0.6);\n"
        css += "}\n"

        self._remove_swatch_provider()

        provider = Gtk.CssProvider()
        self._load_css(provider, css)

        if Gtk.get_major_version() >= 4:
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        else:
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

        self._swatch_provider = provider

    def _remove_swatch_provider(self):

        gtk = self._get_gtk()
        provider = self._swatch_provider
        self._swatch_provider = None

        if provider is None or not gtk:
            return

        Gtk = gtk["Gtk"]
        Gdk = gtk["Gdk"]

        try:
            if Gtk.get_major_version() >= 4:
                Gtk.StyleContext.remove_provider_for_display(Gdk.Display.get_default(), provider)
            else:
                Gtk.StyleContext.remove_provider_for_screen(Gdk.Screen.get_default(), provider)
        except Exception:
            pass

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

    def _row_surface_types(self, Gtk):
        """Row-based list/tree widgets, which render each entry as a node."""

        names = ("TreeView", "ListView", "ColumnView", "IconView")
        types = []

        for name in names:
            cls = getattr(Gtk, name, None)

            if cls is not None:
                types.append(cls)

        return tuple(types)

    @staticmethod
    def _parent_of(Gtk, widget):

        try:
            return widget.get_parent()
        except Exception:
            return None

    def _enclosing_panel(self, Gtk, widget, container_types):
        """Nearest container ancestor of a surface (its visible "card")."""

        viewport = getattr(Gtk, "Viewport", None)
        node = self._parent_of(Gtk, widget)

        while node is not None:
            if viewport is not None and isinstance(node, viewport):
                node = self._parent_of(Gtk, node)
                continue

            if isinstance(node, container_types):
                return node

            node = self._parent_of(Gtk, node)

        return None

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
