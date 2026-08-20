# -*- coding: utf-8 -*-
"""Extended runtime test: instantiate chatwatcher, run init() (loads + timers),
then build the Shitlist page + settings + render, all with stubbed GTK, to catch
any Python-level runtime errors in the Shitlist code path."""
import sys
import types
from unittest.mock import MagicMock

# ---- stub pynicotine.pluginsystem ----
pluginsystem = types.ModuleType("pynicotine.pluginsystem")

class BasePlugin:
    def __init__(self, *args, **kwargs):
        self.core = kwargs.pop("core", None)
        self.config = kwargs.pop("config", None)
        self.path = kwargs.pop("path", "")
        self.internal_name = kwargs.pop("internal_name", "chatwatcher")

    def log(self, msg, args=()):
        try:
            print("[log] " + msg % args)
        except Exception:
            print("[log] " + str(msg))

    def output(self, msg):
        print("[output] " + str(msg))

pluginsystem.BasePlugin = BasePlugin
sys.modules["pynicotine"] = types.ModuleType("pynicotine")
sys.modules["pynicotine.pluginsystem"] = pluginsystem

# ---- stub pynicotine.events ----
events_mod = types.ModuleType("pynicotine.events")
class _Events:
    def connect(self, name, fn): pass
    def disconnect(self, name, fn): pass
    def emit_main_thread(self, name, msg): pass
events_mod.events = _Events()
sys.modules["pynicotine.events"] = events_mod

# ---- stub gi (MagicMock-based Gtk/GLib/Gio) ----
gi = types.ModuleType("gi")
gi_repo = types.ModuleType("gi.repository")

Gtk = MagicMock(name="Gtk")
Gtk.get_major_version.return_value = 4  # force GTK4 code paths

def _make_box(*args, **kwargs):
    b = MagicMock(name="Gtk.Box")
    b.get_first_child.return_value = None  # empty box -> _box_clear loop terminates
    return b
Gtk.Box = _make_box
Gtk.Orientation.VERTICAL = 1
Gtk.Orientation.HORIZONTAL = 0
Gtk.PolicyType.AUTOMATIC = 0
Gtk.PolicyType.NEVER = 1
Gtk.Align.END = 2
Gtk.Align.START = 0
Gtk.Align.FILL = 1
Gtk.WrapMode.WORD_CHAR = 1
Gtk.ScrollDirection.UP = 0

GLib = MagicMock(name="GLib")
GLib.timeout_add.return_value = 1
GLib.timeout_add_seconds.return_value = 1
GLib.source_remove.return_value = True

Gio = MagicMock(name="Gio")

gi_repo.Gtk = Gtk
gi_repo.GLib = GLib
gi_repo.Gio = Gio
sys.modules["gi"] = gi
sys.modules["gi.repository"] = gi_repo

# ---- fake core ----
class _NetFilter:
    def is_user_banned(self, u): return False
    def is_user_ignored(self, u): return False
    def is_user_ip_banned(self, u): return False
    def is_user_ip_ignored(self, u): return False
    def ban_user(self, u): pass
    def ignore_user(self, u): pass
    def ban_user_ip(self, u, ip_address=None): return ip_address
    def ignore_user_ip(self, u, ip_address=None): pass

class _Users:
    login_username = "kiquja"
    addresses = {}

class _Chatrooms:
    def sanitize_room_name(self, r): return r
    def show_room(self, r, **kw): pass

class _Core:
    def __init__(self):
        self.users = _Users()
        self.network_filter = _NetFilter()
        self.chatrooms = _Chatrooms()

class _Config:
    def __init__(self):
        self.sections = {"plugins": {}}
    def write_configuration(self): pass

core = _Core()
config = _Config()

# ---- import the plugin ----
import importlib.util
spec = importlib.util.spec_from_file_location(
    "chatwatcher_plugin",
    r"C:\Users\kiquj\.openclaw-autoclaw\workspace\!Nicotine plugins\chatwatcher\__init__.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

Plugin = mod.Plugin
plugin = Plugin(core=core, config=config,
                path=r"C:\Users\kiquj\AppData\Roaming\nicotine\plugins\chatwatcher")

print("=== instantiated OK ===")

# ---- full init (loads + schedule builds + timers) ----
plugin.init()
print("=== init() OK ===")

print("shitlist entries:", len(plugin._feeds["shitlist"]["entries"]))
print("listenings entries:", len(plugin._feeds["listenings"]["entries"]))
print("keywordwatch entries:", len(plugin._feeds["keywordwatch"]["entries"]))

# ---- build the Shitlist page + settings (GTK code path) ----
feed = plugin._feeds["shitlist"]
page = plugin._build_shitlist_page(feed)
print("=== _build_shitlist_page() OK ===")

# ---- render the shitlist feed (creates entry buttons + popovers) ----
feed["built"] = True
feed["status_label"] = MagicMock()
plugin._shitlist_render()
print("=== _shitlist_render() OK ===")

# ---- loaded_notification (menu patch + profile-view hook) ----
plugin.loaded_notification()
print("=== loaded_notification() OK ===")

print("=== ALL OK ===")
