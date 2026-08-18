# SPDX-FileCopyrightText: 2026 Nicotine+ Keybinds Plugin Contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Configurable keyboard shortcuts (keybinds) for Nicotine+, plus a plugin
refresh/list command (merged from the "Refresh Plugins List" plugin).

Keybinds are captured with a manual GTK key controller on the main window, so
they do NOT fire while the user is typing in a text field (chat entry, search
box, etc.).

Modifier syntax (GTK accelerator notation):
    <Primary>  Ctrl on Windows/Linux, Cmd on macOS
    <Shift>    Shift
    <Alt>      Alt
    <Super>    Windows key (or Super/Command on macOS)
    <Control>  Ctrl (explicit)

Example chords: <Super><Shift>t  = Win+Shift+T ; <Control><Alt>Right = Ctrl+Alt+Right.
"""

import builtins
import sys

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

from pynicotine.pluginsystem import BasePlugin

_ = builtins.__dict__.get("_", lambda s: s)

GTK4 = Gtk.get_major_version() >= 4

# (key, label, description) — the key is used for settings storage and action naming.
ACTIONS = (
    ("open_chatrooms", "Open Chat Rooms tab", "Switch to the Chat Rooms tab"),
    ("open_private", "Open Private Chat", "Switch to the Private Chat tab"),
    ("open_search", "Open Search Files", "Switch to the Search Files tab"),
    ("open_downloads", "Open Downloads tab", "Switch to the Downloads tab"),
    ("open_uploads", "Open Uploads tab", "Switch to the Uploads tab"),
    ("open_browse", "Browse Shares", "Switch to the Browse Shares tab"),
    ("open_userinfo", "User Profiles", "Switch to the User Profiles tab"),
    ("open_interests", "Interests", "Switch to the Interests tab"),
    ("open_settings", "Open Settings", "Open the Preferences (settings) window"),
    ("cycle_tabs_forward", "Cycle tabs forward", "Cycle through the main tabs (forward)"),
    ("cycle_tabs_reverse", "Cycle tabs reverse", "Cycle through the main tabs (reverse)"),
    ("cycle_pm_forward", "Cycle private messages forward", "Cycle to the next open private chat"),
    ("cycle_pm_reverse", "Cycle private messages reverse", "Cycle to the previous open private chat"),
    ("refresh_plugins", "Refresh plugins", "Reload currently installed plugins"),
    ("open_keybind_window", "Keybind settings", "Open this keybind configuration window"),
)

DEFAULT_ACCELS = {
    "open_chatrooms": "<Super><Shift>c",
    "open_private": "<Super><Shift>p",
    "open_search": "<Super><Shift>f",
    "open_downloads": "<Super><Shift>d",
    "open_uploads": "<Super><Shift>u",
    "open_browse": "<Super><Shift>b",
    "open_userinfo": "<Super><Shift>i",
    "open_interests": "<Super><Shift>t",
    "open_settings": "<Super><Shift>comma",
    "cycle_tabs_forward": "<Control><Alt>Right",
    "cycle_tabs_reverse": "<Control><Alt>Left",
    "cycle_pm_forward": "<Control><Alt>Down",
    "cycle_pm_reverse": "<Control><Alt>Up",
    "refresh_plugins": "<Super><Shift>r",
    "open_keybind_window": "<Super><Shift>k",
}

# Main notebook page ids (Nicotine+ main tabs).
MAIN_PAGE_IDS = {
    "search", "downloads", "uploads", "userbrowse", "userinfo",
    "private", "userlist", "chatrooms", "interests",
}

TAB_ACTIONS = {
    "open_chatrooms": "chatrooms",
    "open_private": "private",
    "open_search": "search",
    "open_downloads": "downloads",
    "open_uploads": "uploads",
    "open_browse": "userbrowse",
    "open_userinfo": "userinfo",
    "open_interests": "interests",
}

# Nicotine+ window-level actions (queried dynamically for conflict detection).
WIN_ACTION_NAMES = (
    "main-menu", "focus-top-bar", "change-focus-view", "toggle-status",
    "show-log-pane", "search-mode", "reopen-closed-tab", "close-tab",
    "cycle-tabs", "cycle-tabs-reverse",
) + tuple(f"primary-tab-{num}" for num in range(1, 10))

# Common Windows-reserved shortcuts (heuristic; varies by Windows version and
# can be remapped by the user or OEM software).
WINDOWS_RESERVED = {
    "<Super>", "<Super>Tab", "<Super><Shift>Tab",
    "<Super>l", "<Super>d", "<Super>e", "<Super>r", "<Super>s", "<Super>x",
    "<Super>m", "<Super>v", "<Super>g", "<Super>p", "<Super>i", "<Super>h",
    "<Super>a", "<Super>q", "<Super>w", "<Super>k", "<Super>c", "<Super>b",
    "<Super>n", "<Super>f", "<Super>u", "<Super>t",
    "<Super>Up", "<Super>Down", "<Super>Left", "<Super>Right",
    "<Super>Home", "<Super>End", "<Super>Print", "<Super>period",
    "<Super>comma", "<Super>slash", "<Super>BackSpace",
    "<Super><Shift>s", "<Super><Shift>Up", "<Super><Shift>Down",
    "<Super><Shift>Left", "<Super><Shift>Right",
    "<Super><Control><Shift>b",
    "<Super><Alt>r", "<Super><Alt>g", "<Super><Alt>b", "<Super><Alt>Enter",
    "<Control><Alt>Delete", "<Alt>F4", "<Alt>Tab", "<Alt><Shift>Tab",
    "<Control>Escape", "<Alt>space",
}
WINDOWS_RESERVED |= {f"<Super>{num}" for num in range(1, 10)}

_MODIFIER_KEY_NAMES = {
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Super_L", "Super_R", "Meta_L", "Meta_R", "ISO_Level3_Shift",
    "Caps_Lock", "Num_Lock",
}


# --- GTK helpers -----------------------------------------------------------

def _add(container, child):
    if GTK4:
        container.append(child)
    else:
        container.add(child)


def _children(widget):
    try:
        if GTK4:
            child = widget.get_first_child()
            while child is not None:
                yield child
                child = child.get_next_sibling()
        else:
            yield from widget.get_children()
    except Exception:
        return


def _show_all(widget):
    if not GTK4:
        widget.show_all()


def _normalize_accel(accel):
    """Normalize <Primary> so <Control>l and <Primary>l compare as equal."""
    primary = "<Meta>" if sys.platform == "darwin" else "<Control>"
    return (accel or "").replace("<Primary>", primary)


# --- Keybind window --------------------------------------------------------

class _KeybindWindow:
    """GTK window listing every keybind, with live recording + conflict display."""

    def __init__(self, plugin):
        self.plugin = plugin
        self.recording_key = None
        self.key_controller = None
        self.key_handler = None
        self._build()

    def _build(self):
        self.win = Gtk.Window(title=_("Nicotine+ Keybinds"))
        self.win.set_default_size(660, 520)

        main_win = self.plugin._main_window()
        if main_win is not None:
            self.win.set_transient_for(main_win)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=True)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        title = Gtk.Label(visible=True, halign=Gtk.Align.START)
        title.set_markup("<b>" + GLib.markup_escape_text(_("Keybinds")) + "</b>")
        _add(outer, title)

        hint = Gtk.Label(visible=True, halign=Gtk.Align.START, wrap=True)
        hint.set_markup(
            "<small>" + GLib.markup_escape_text(
                _("Click a keybinding to change it. Press Esc to cancel. "
                  "<Super> = Windows key, <Primary> = Ctrl/Cmd. Conflicts are shown in red.")
            ) + "</small>"
        )
        _add(outer, hint)

        self.scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True, visible=True)
        self.grid = Gtk.Grid(column_spacing=10, row_spacing=6, visible=True)
        self.grid.set_margin_top(6)
        self.grid.set_margin_bottom(6)
        self.grid.set_margin_start(6)
        self.grid.set_margin_end(6)
        if GTK4:
            self.scroll.set_child(self.grid)
        else:
            self.scroll.add(self.grid)
        _add(outer, self.scroll)

        btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, visible=True)
        reset_btn = Gtk.Button(label=_("Reset defaults"), visible=True)
        reset_btn.connect("clicked", self._on_reset)
        _add(btn_bar, reset_btn)
        refresh_btn = Gtk.Button(label=_("Refresh plugins"), visible=True)
        refresh_btn.connect("clicked", self._on_refresh_plugins)
        _add(btn_bar, refresh_btn)
        close_btn = Gtk.Button(label=_("Close"), visible=True)
        close_btn.connect("clicked", self._on_close)
        _add(btn_bar, close_btn)
        _add(outer, btn_bar)

        if GTK4:
            self.win.set_child(outer)
            self.win.connect("close-request", self._on_close_request)
        else:
            self.win.add(outer)
            self.win.connect("delete-event", self._on_delete_event)

        self._refresh_rows()
        _show_all(self.win)

    # Rows #

    def _refresh_rows(self):
        for child in list(_children(self.grid)):
            self.grid.remove(child)

        row = 0
        for key, label, desc in ACTIONS:
            accel = self.plugin.settings.get(key) or ""
            conflicts = self.plugin._find_conflicts(key, accel)

            name_label = Gtk.Label(xalign=0, hexpand=True, visible=True)
            name_label.set_markup("<b>" + GLib.markup_escape_text(label) + "</b>")
            name_label.set_tooltip_text(desc)

            if self.recording_key == key:
                btn_label = _("Press keys… (Esc to cancel)")
            else:
                btn_label = accel if accel else _("Click to set")
            bind_btn = Gtk.Button(label=btn_label, visible=True)
            bind_btn.connect("clicked", self._on_record, key)

            if conflicts:
                c_label = Gtk.Label(xalign=0, wrap=True, visible=True)
                c_label.set_markup(
                    "<span foreground=\"#c62828\">⚠ "
                    + GLib.markup_escape_text(", ".join(conflicts)) + "</span>"
                )
            else:
                c_label = Gtk.Label(label="", xalign=0, visible=True)

            clear_btn = Gtk.Button(label=_("Clear"), visible=True)
            clear_btn.set_sensitive(bool(accel))
            clear_btn.connect("clicked", self._on_clear, key)

            self.grid.attach(name_label, 0, row, 1, 1)
            self.grid.attach(bind_btn, 1, row, 1, 1)
            self.grid.attach(c_label, 2, row, 1, 1)
            self.grid.attach(clear_btn, 3, row, 1, 1)
            row += 1

        _show_all(self.grid)

    # Recording #

    def _begin_recording(self, key):
        self.recording_key = key
        self._stop_controller()

        if GTK4:
            self.key_controller = Gtk.EventControllerKey()
            self.key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            self.key_controller.connect("key-pressed", self._on_key_pressed)
            self.win.add_controller(self.key_controller)
        else:
            self.key_handler = self.win.connect("key-press-event", self._on_key_press_event)

    def _stop_recording(self):
        self.recording_key = None
        self._stop_controller()
        self._refresh_rows()

    def _stop_controller(self):
        if self.key_controller is not None:
            self.win.remove_controller(self.key_controller)
            self.key_controller = None
        if self.key_handler is not None:
            self.win.disconnect(self.key_handler)
            self.key_handler = None

    def _capture(self, keyval, state):
        key = self.recording_key
        if key is None:
            return

        # GTK's accelerator_name() only includes Control/Alt/Shift/Super/Hyper/Meta
        # and ignores lock modifiers (Caps Lock / Num Lock), so `state` (already a
        # Gdk.ModifierType) can be passed through unchanged.
        name = Gdk.keyval_name(keyval)
        if name in _MODIFIER_KEY_NAMES:
            return

        if name == "Escape":
            self._stop_recording()
            return

        accel = Gtk.accelerator_name(keyval, state) or ""
        if accel:
            self.plugin._set_keybind(key, accel)

        self._stop_recording()

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        self._capture(keyval, state)
        return True

    def _on_key_press_event(self, _widget, event):
        self._capture(event.keyval, event.state)
        return True

    # Callbacks #

    def _on_record(self, _button, key):
        self._begin_recording(key)
        self._refresh_rows()

    def _on_clear(self, _button, key):
        self.plugin._set_keybind(key, "")
        self._refresh_rows()

    def _on_reset(self, _button):
        for key, accel in DEFAULT_ACCELS.items():
            self.plugin._set_keybind(key, accel)
        self.plugin._save_settings()
        self._refresh_rows()

    def _on_refresh_plugins(self, _button):
        self.plugin._refresh_plugins()

    def _on_close(self, _button):
        self.destroy()

    def _on_close_request(self, *_args):
        self.destroy()
        return True

    def _on_delete_event(self, *_args):
        self.destroy()
        return True

    def destroy(self):
        self._stop_controller()
        self.win.destroy()
        if self.plugin._window is self:
            self.plugin._window = None


# --- Plugin ----------------------------------------------------------------

class Plugin(BasePlugin):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.settings = dict(DEFAULT_ACCELS)

        # Expose the keybinds as editable text fields in the standard
        # Preferences -> Plugins -> Keybinds -> Settings dialog too.
        self.metasettings = {
            key: {"description": label, "type": "string"}
            for (key, label, _desc) in ACTIONS
        }

        self._keymap = {}
        self._key_controller = None
        self._key_handler = None
        self._window = None
        self._header_bar_patched = False
        self._original_set_active_header_bar = None

    # Lifecycle #

    def init(self):
        self.commands = {
            "keybinds": {
                "callback": self._command_keybinds,
                "description": _("Open the keybind configuration window"),
                "group": self.human_name,
            },
            "rpl": {
                "aliases": ["refreshplugins"],
                "callback": self.refresh_plugins_command,
                "description": _("Refresh and list installed plugins"),
                "group": _("Plugins"),
            },
        }
        self._register_keybinds()
        self._patch_header_bar()
        self.log(
            _("Loaded %(count)s keybinds. Press %(open)s or type /keybinds to configure."),
            {"count": len(ACTIONS), "open": self.settings.get("open_keybind_window", "<Super><Shift>k")}
        )

    def disable(self):
        self._restore_header_bar()
        self._unregister_keybinds()
        if self._window is not None:
            self._window.destroy()
            self._window = None

    # Key registration #

    @staticmethod
    def _action_name(key):
        return "keybinds-" + key.replace("_", "-")

    def _register_keybinds(self):
        window = self._main_window()
        if window is None:
            self.log(_("No GUI available; keybinds will not be registered"))
            return

        self._build_keymap()

        if GTK4:
            self._key_controller = Gtk.EventControllerKey()
            self._key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            self._key_controller.connect("key-pressed", self._on_key_pressed)
            window.add_controller(self._key_controller)
        else:
            self._key_handler = window.connect("key-press-event", self._on_key_press_event)

    def _unregister_keybinds(self):
        window = self._main_window()
        if window is None:
            return
        if self._key_controller is not None:
            try:
                window.remove_controller(self._key_controller)
            except Exception:
                pass
            self._key_controller = None
        if self._key_handler is not None:
            try:
                window.disconnect(self._key_handler)
            except Exception:
                pass
            self._key_handler = None

    def _build_keymap(self):
        keymap = {}
        for (key, _label, _desc) in ACTIONS:
            accel = self.settings.get(key)
            if accel:
                keymap[_normalize_accel(accel)] = key
        self._keymap = keymap

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        return self._handle_key(keyval, state)

    def _on_key_press_event(self, _widget, event):
        return self._handle_key(event.keyval, event.state)

    def _handle_key(self, keyval, state):
        accel = Gtk.accelerator_name(keyval, state) or ""
        if not accel:
            return False

        key = self._keymap.get(_normalize_accel(accel))
        if key is None:
            return False

        # Never fire keybinds while the user is typing in a text field.
        if self._focus_is_text_input():
            return False

        self._run_action(key)
        return True

    def _focus_is_text_input(self):
        window = self._main_window()
        if window is None:
            return False

        focus = window.get_focus()
        if focus is None:
            return False

        if isinstance(focus, Gtk.Editable):
            return True
        if isinstance(focus, Gtk.TextView) and focus.get_editable():
            return True

        return False

    def _set_keybind(self, key, accel):
        self.settings[key] = accel
        self._build_keymap()
        self._save_settings()

    def _save_settings(self):
        try:
            self.config.sections["plugins"][self.internal_name.lower()] = self.settings
            self.config.write_configuration()
        except Exception as error:
            self.log(_("Failed to save settings: %(error)s"), {"error": error})

    # Header-bar patch (plugin-added tabs) #

    def _patch_header_bar(self):
        """Make MainWindow.set_active_header_bar a no-op for plugin-added tabs.

        Nicotine+ raises KeyError('<tab id>') when switching to a tab that is
        not registered in MainWindow.tabs (which only holds Nicotine+'s own
        tabs), so cycling to a tab added by another plugin (e.g. "Played")
        breaks the header bar. Patch the class method to skip the
        header/toolbar swap for any unknown page id, so the tab cycler works
        with tabs from any plugin. The patch chains through whatever method is
        already set, so it coexists with plugins that patch this method too.
        """

        if self._header_bar_patched:
            return

        try:
            from pynicotine.gtkgui.mainwindow import MainWindow
        except Exception:
            return

        original = getattr(MainWindow, "set_active_header_bar", None)

        if original is None or getattr(original, "_qol_headerbar_patched", False):
            return

        def patched(mw_self, page_id):
            tabs = getattr(mw_self, "tabs", None)

            if tabs is not None and page_id not in tabs:
                return

            original(mw_self, page_id)

        patched._qol_headerbar_patched = True
        MainWindow.set_active_header_bar = patched

        self._header_bar_patched = True
        self._original_set_active_header_bar = original

    def _restore_header_bar(self):
        if not self._header_bar_patched:
            return

        try:
            from pynicotine.gtkgui.mainwindow import MainWindow
        except Exception:
            return

        current = getattr(MainWindow, "set_active_header_bar", None)

        # Only restore if our patch is still the active one (another plugin may
        # have patched on top of us since we applied it).
        if current is not None and getattr(current, "_qol_headerbar_patched", False):
            MainWindow.set_active_header_bar = self._original_set_active_header_bar

        self._header_bar_patched = False
        self._original_set_active_header_bar = None

    # Actions #

    def _run_action(self, key):
        try:
            if key in TAB_ACTIONS:
                self._switch_main_tab(TAB_ACTIONS[key])
            elif key == "open_settings":
                self._open_settings()
            elif key == "cycle_tabs_forward":
                self._cycle_main_tabs(reverse=False)
            elif key == "cycle_tabs_reverse":
                self._cycle_main_tabs(reverse=True)
            elif key == "cycle_pm_forward":
                self._cycle_pm(reverse=False)
            elif key == "cycle_pm_reverse":
                self._cycle_pm(reverse=True)
            elif key == "refresh_plugins":
                self._refresh_plugins()
            elif key == "open_keybind_window":
                self._open_window()
        except Exception as error:
            self.log(_("Error running action %(key)s: %(error)s"), {"key": key, "error": error})

    def _command_keybinds(self, _args, room=None, user=None):
        GLib.idle_add(self._open_window)
        return True

    # Refresh plugins (merged from "Refresh Plugins List") #

    def refresh_plugins_command(self, _args, room=None, user=None):
        """Re-scan, reload updated plugins, and output the current plugin list."""

        pluginhandler = self.core.pluginhandler
        reloaded = self._reload_other_plugins()

        installed = sorted(pluginhandler.list_installed_plugins())
        loaded = self._loaded_plugins(pluginhandler)
        enabled = self.config.sections["plugins"].get("enabled", [])

        self.output(_("Refreshed plugin list (%(installed)d installed, %(reloaded)d reloaded):") % {
            "installed": len(installed),
            "reloaded": len(reloaded)
        })

        if not installed:
            self.output(_("No plugins found."))
            return True

        for plugin_name in installed:
            if plugin_name in loaded:
                marker, status = "‣", "loaded"
            elif plugin_name in enabled:
                marker, status = "•", "failed"
            else:
                marker, status = "•", "disabled"

            self.output("%s %s (%s)" % (marker, plugin_name, status))

        return True

    def _refresh_plugins(self):
        reloaded = self._reload_other_plugins()
        self.log(_("Refreshed %(count)s plugin(s)"), {"count": len(reloaded)})

    def _reload_other_plugins(self):
        pluginhandler = self.core.pluginhandler
        loaded = self._loaded_plugins(pluginhandler)
        reloaded = []

        for plugin_name in list(loaded):
            if plugin_name == self.internal_name:
                continue

            try:
                pluginhandler.reload_plugin(plugin_name)
                reloaded.append(plugin_name)
            except Exception as error:
                self.log(_("Could not reload %(name)s: %(error)s"),
                         {"name": plugin_name, "error": error})

        return reloaded

    @staticmethod
    def _loaded_plugins(pluginhandler):
        """Return the PluginHandler's loaded-plugins dict across Nicotine+ versions."""

        for attr in ("loaded_plugins", "enabled_plugins"):
            value = getattr(pluginhandler, attr, None)

            if isinstance(value, dict):
                return value

        return {}

    # Window / notebook access #

    def _main_window(self):
        app = Gio.Application.get_default()
        if app is None:
            return None
        windows = app.get_windows()
        return windows[0] if windows else None

    def _main_notebook(self):
        app = Gio.Application.get_default()
        if app is None:
            return None
        for win in app.get_windows():
            notebook = self._find_main_notebook_in(win)
            if notebook is not None:
                return notebook
        return None

    @staticmethod
    def _find_main_notebook_in(root):
        stack = [root]
        while stack:
            widget = stack.pop()
            if isinstance(widget, Gtk.Notebook):
                for i in range(widget.get_n_pages()):
                    page = widget.get_nth_page(i)
                    if getattr(page, "id", None) in MAIN_PAGE_IDS:
                        return widget
            stack.extend(_children(widget))
        return None

    def _defer_focus_reset(self):
        """Move focus back to the notebook shortly after a tab switch.

        Nicotine+ focuses a tab's default widget (usually the search entry)
        through a HIGH-priority idle callback right after a page switch. That
        leaves focus in a text field, which stops our keybinds from firing (they
        are intentionally ignored while typing). Schedule a lower-priority idle
        to grab focus back on the notebook so keybinds keep working after
        switching tabs.
        """

        notebook = self._main_notebook()

        if notebook is None:
            return

        GLib.idle_add(self._grab_notebook_focus, notebook)

    @staticmethod
    def _grab_notebook_focus(notebook):
        try:
            notebook.grab_focus()
        except Exception:
            pass

        return False

    def _switch_main_tab(self, page_id):
        notebook = self._main_notebook()
        if notebook is None:
            self.log(_("Main window not available"))
            return

        for i in range(notebook.get_n_pages()):
            page = notebook.get_nth_page(i)
            if getattr(page, "id", None) == page_id:
                try:
                    page.set_visible(True)
                except Exception:
                    pass
                notebook.set_current_page(i)
                self._defer_focus_reset()
                return

        self.log(_("Tab '%(tab)s' not found"), {"tab": page_id})

    def _cycle_main_tabs(self, reverse=False):
        notebook = self._main_notebook()
        if notebook is None:
            return

        num_pages = notebook.get_n_pages()
        if num_pages <= 1:
            return

        # Cycle through visible pages only (matches Nicotine+'s tab switching).
        # Plugin-added tabs are visible, so they are included automatically.
        visible = [i for i in range(num_pages) if notebook.get_nth_page(i).get_visible()]

        if len(visible) <= 1:
            return

        current = notebook.get_current_page()

        try:
            current_index = visible.index(current)
        except ValueError:
            current_index = 0

        new_index = (current_index - 1) % len(visible) if reverse else (current_index + 1) % len(visible)
        notebook.set_current_page(visible[new_index])
        self._defer_focus_reset()

    def _private_notebook(self):
        notebook = self._main_notebook()
        if notebook is None:
            return None

        for i in range(notebook.get_n_pages()):
            page = notebook.get_nth_page(i)
            if getattr(page, "id", None) != "private":
                continue

            stack = [page]
            while stack:
                widget = stack.pop()
                if isinstance(widget, Gtk.Notebook) and widget is not notebook:
                    return widget
                stack.extend(_children(widget))
        return None

    def _cycle_pm(self, reverse=False):
        self._switch_main_tab("private")
        notebook = self._private_notebook()
        if notebook is None or notebook.get_n_pages() <= 1:
            return

        current = notebook.get_current_page()
        num_pages = notebook.get_n_pages()
        new_page = (current - 1) % num_pages if reverse else (current + 1) % num_pages
        notebook.set_current_page(new_page)
        self._defer_focus_reset()

    def _open_settings(self):
        app = Gio.Application.get_default()
        if app is None:
            return
        action = app.lookup_action("preferences")
        if action is not None:
            action.activate(None)

    def _open_window(self):
        if self._window is None or not self._window.win.get_visible():
            self._window = _KeybindWindow(self)
        self._window.win.present()

    # Conflict detection #

    def _find_conflicts(self, key, accel):
        if not accel:
            return []

        conflicts = []
        normalized = _normalize_accel(accel)

        builtin_map = self._builtin_accel_map()
        if normalized in builtin_map:
            conflicts.extend(builtin_map[normalized])

        for other_key, _label, _desc in ACTIONS:
            if other_key == key:
                continue
            if _normalize_accel(self.settings.get(other_key)) == normalized:
                conflicts.append(self._action_name(other_key))

        if normalized in WINDOWS_RESERVED:
            conflicts.append(_("Windows reserved shortcut"))

        return conflicts

    def _builtin_accel_map(self):
        app = Gio.Application.get_default()
        accel_map = {}
        if app is None:
            return accel_map

        try:
            app_names = app.list_actions() or []
        except Exception:
            app_names = []

        for name in app_names:
            if name.startswith("keybinds-"):
                continue
            self._collect_accels(accel_map, app, f"app.{name}")

        for name in WIN_ACTION_NAMES:
            self._collect_accels(accel_map, app, f"win.{name}")

        return accel_map

    @staticmethod
    def _collect_accels(accel_map, app, detailed_name):
        try:
            accels = app.get_accels_for_action(detailed_name)
        except Exception:
            return
        for accel in accels:
            normalized = _normalize_accel(accel)
            accel_map.setdefault(normalized, []).append(detailed_name)
