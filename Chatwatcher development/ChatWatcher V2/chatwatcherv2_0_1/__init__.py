"""ChatWatcher V2 Nicotine+ plugin entry point.

Nicotine+ discovers plugins through the folder-level ``__init__.py``.
"""

from dataclasses import asdict, dataclass
from pathlib import Path
from datetime import datetime
from datetime import timedelta
import json
import os


DEFAULT_SETTINGS = {
	"played": {
		"enabled": True,
		"retention": "1 day",
		"hidden_users": [],
		"now_playing_markers": [
			"np:", "now playing", "is listening to", "is now listening to", "is having an eargasm to"
		],
		"now_playing_exceptions": [],
	},
	"keywords": {"enabled": True, "keywords": [], "case_sensitive": False},
	"shitlist": {"enabled": False, "keywords": [], "mode": "automatic"},
}

RETENTION_SECONDS = {
	"20 min": 20 * 60,
	"1 hr": 60 * 60,
	"12 hr": 12 * 60 * 60,
	"1 day": 24 * 60 * 60,
	"3 days": 3 * 24 * 60 * 60,
	"7 days": 7 * 24 * 60 * 60,
	"1 month": 30 * 24 * 60 * 60,
	"forever": None,
}


class Config:
	"""Small JSON-backed settings store used by the standalone plugin file."""

	def __init__(self, path):
		self.path = Path(path)
		self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
		if self.path.is_file():
			try:
				loaded = json.loads(self.path.read_text(encoding="utf-8"))
				for feature, values in loaded.items():
					if feature in self.settings and isinstance(values, dict):
						self.settings[feature].update(values)
			except (OSError, json.JSONDecodeError):
				pass

	def get_setting(self, feature, setting, default=None):
		return self.settings.get(feature, {}).get(setting, default)

	def set_setting(self, feature, setting, value):
		self.settings.setdefault(feature, {})[setting] = value

	def save_config(self):
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")


@dataclass
class PlayedEntry:
	timestamp: str
	user: str
	message: str
	source: str
	is_self: bool = False


class PlayedFeature:
	def __init__(self, config, log_dir):
		self.config = config
		self.log_dir = Path(log_dir) / "listenings"
		self.entries = []
		self.blocked_users = {
			str(user).casefold()
			for user in config.get_setting("played", "hidden_users", [])
		}
		self.load_entries()

	def is_now_playing(self, message):
		text = message.casefold()
		markers = self.config.get_setting("played", "now_playing_markers", [])
		exceptions = self.config.get_setting("played", "now_playing_exceptions", [])
		if not message.strip() or any(str(exception).casefold() in text for exception in exceptions):
			return False
		return any(str(marker).casefold() in text for marker in markers)

	def add_exception(self, phrase):
		phrase = str(phrase).strip()
		if not phrase:
			return False
		exceptions = list(self.config.get_setting("played", "now_playing_exceptions", []))
		if phrase.casefold() in {item.casefold() for item in exceptions}:
			return False
		exceptions.append(phrase)
		self.config.set_setting("played", "now_playing_exceptions", exceptions)
		self.config.save_config()
		return True

	def remove_exception(self, phrase):
		phrase = str(phrase).strip()
		exceptions = list(self.config.get_setting("played", "now_playing_exceptions", []))
		updated = [item for item in exceptions if item.casefold() != phrase.casefold()]
		if updated == exceptions:
			return False
		self.config.set_setting("played", "now_playing_exceptions", updated)
		self.config.save_config()
		return True

	def get_exceptions(self):
		return list(self.config.get_setting("played", "now_playing_exceptions", []))

	def capture_now_playing(self, user, message, source="unknown", is_self=False):
		user = str(user)
		message = str(message)
		if not self.is_now_playing(message) or user.casefold() in self.blocked_users:
			return False
		entry = PlayedEntry(datetime.now().isoformat(timespec="seconds"), user, message, source, is_self)
		if any(
			item.user.casefold() == user.casefold()
			and item.message == message
			and item.source == source
			for item in self.entries[:5]
		):
			return False
		self.entries.insert(0, entry)
		self.log_entry(entry)
		self.prune_entries()
		return True

	def log_entry(self, entry):
		self.log_dir.mkdir(parents=True, exist_ok=True)
		date = datetime.now().strftime("%Y-%m-%d")
		path = self.log_dir / f"log1[{date}].log"
		with path.open("a", encoding="utf-8") as file:
			file.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

	def load_entries(self):
		loaded = []
		for path in sorted(self.log_dir.glob("log*.log")):
			try:
				lines = path.read_text(encoding="utf-8").splitlines()
			except OSError:
				continue
			for line in lines:
				try:
					data = json.loads(line)
					loaded.append(PlayedEntry(**data))
				except (TypeError, ValueError, json.JSONDecodeError):
					continue
		self.entries = sorted(loaded, key=lambda entry: entry.timestamp, reverse=True)
		self.prune_entries()

	def prune_entries(self):
		retention = self.config.get_setting("played", "retention", "1 day")
		seconds = RETENTION_SECONDS.get(retention, RETENTION_SECONDS["1 day"])
		if seconds is None:
			return
		cutoff = datetime.now() - timedelta(seconds=seconds)
		kept = []
		for entry in self.entries:
			try:
				created = datetime.fromisoformat(entry.timestamp)
			except ValueError:
				continue
			if created >= cutoff:
				kept.append(entry)
		self.entries = kept

	def block_user(self, user):
		self.blocked_users.add(user.casefold())
		self.entries = [entry for entry in self.entries if entry.user.casefold() != user.casefold()]
		self._save_hidden_users()

	def unblock_user(self, user):
		self.blocked_users.discard(user.casefold())
		self._save_hidden_users()

	def clear_log(self):
		self.entries.clear()
		if self.log_dir.is_dir():
			for path in self.log_dir.glob("log*.log"):
				try:
					path.unlink()
				except OSError:
					pass

	def _save_hidden_users(self):
		self.config.set_setting("played", "hidden_users", sorted(self.blocked_users))
		self.config.save_config()


class KeywordsFeature:
	def __init__(self, config):
		self.config = config
		self.keywords = list(config.get_setting("keywords", "keywords", []))
		self.message_log = []

	def add_keyword(self, keyword):
		keyword = keyword.strip()
		if keyword and keyword.casefold() not in {item.casefold() for item in self.keywords}:
			self.keywords.append(keyword)

	def remove_keyword(self, keyword):
		self.keywords = [item for item in self.keywords if item.casefold() != keyword.casefold()]

	def matches(self, message):
		text = message if self.config.get_setting("keywords", "case_sensitive", False) else message.casefold()
		return [keyword for keyword in self.keywords if (keyword if self.config.get_setting("keywords", "case_sensitive", False) else keyword.casefold()) in text]


class ShitlistFeature:
	def __init__(self, config):
		self.config = config
		self.banned_keywords = set(config.get_setting("shitlist", "keywords", []))
		self.ignored_ips = set()
		self.log = []

	def add_banned_keyword(self, keyword):
		if keyword.strip():
			self.banned_keywords.add(keyword.strip())

	def remove_banned_keyword(self, keyword):
		self.banned_keywords.discard(keyword)

	def process_message(self, message):
		if not self.config.get_setting("shitlist", "enabled", False):
			return []
		text = message.casefold()
		return [keyword for keyword in self.banned_keywords if keyword.casefold() in text]

try:
	from pynicotine.pluginsystem import BasePlugin
except ImportError:  # Allows unit tests outside Nicotine+.
	class BasePlugin:
		def __init__(self, *args, **kwargs):
			self.settings = {}

		def output(self, message):
			return message


class Plugin(BasePlugin):
	"""Nicotine+ lifecycle, commands, and event hooks."""

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self.settings = {
			"played_enabled": True,
			"keywords_enabled": True,
			"shitlist_enabled": False,
		}
		self.metasettings = {
			"played_enabled": {
				"description": "Show the Played tab",
				"type": "bool",
			},
			"played_retention": {
				"description": "Played log retention",
				"type": "dropdown",
				"options": list(RETENTION_SECONDS),
			},
			"keywords_enabled": {
				"description": "Show the Keywords tab",
				"type": "bool",
			},
			"shitlist_enabled": {
				"description": "Enable Shitlist",
				"type": "bool",
			},
		}
		self.commands = {
			"cw": {
				"callback": self.cw_command,
				"description": "Open ChatWatcher settings or show status/help",
				"parameters": ["[status|help]"],
				"group": "ChatWatcher V2",
			},
			"chatwatcher": {
				"callback": self.cw_command,
				"description": "Open ChatWatcher settings",
				"parameters": ["[status|help]"],
				"group": "ChatWatcher V2",
			},
			"played": {
				"callback": self.played_command,
				"description": "Open Played or manage hidden users",
				"parameters": ["[clear|hide|unhide|list|exception] [username|add|remove|list] [phrase]"],
				"group": "ChatWatcher V2",
			},
			"kw": {
				"callback": self.keywords_command,
				"description": "Manage Keyword Watch",
				"parameters": ["[add|remove|list] [word]"],
				"group": "ChatWatcher V2",
			},
			"shitlist": {
				"callback": self.shitlist_command,
				"description": "Manage Shitlist keywords",
				"parameters": ["[add|remove|list] [word]"],
				"group": "ChatWatcher V2",
			},
		}

		self.config = Config(Path(__file__).resolve().parent.parent / "config" / "settings.json")
		self.played = None
		self.keywords = None
		self.shitlist = None
		self._gtk = None
		self._ui_poll_id = None
		self._notebook = None
		self._pages = {}
		self._page_widgets = {}
		self._page_ids = set()
		self._header_bar_original = None
		self._header_bar_class = None

	def init(self):
		"""Initialize feature state after Nicotine+ loads settings."""
		self.config.set_setting("played", "enabled", self.settings["played_enabled"])
		self.config.set_setting(
			"played", "retention", self.settings.get(
				"played_retention", self.config.get_setting("played", "retention", "1 day")
			)
		)
		self.config.set_setting("keywords", "enabled", self.settings["keywords_enabled"])
		self.config.set_setting("shitlist", "enabled", self.settings["shitlist_enabled"])

		log_dir = Path(__file__).resolve().parent / "logs"
		self.played = PlayedFeature(self.config, log_dir)
		self.keywords = KeywordsFeature(self.config)
		self.shitlist = ShitlistFeature(self.config)
		self._refresh_all_pages()
		self._start_ui_attach()

	def disable(self):
		"""Release feature state when the plugin is disabled."""
		self._stop_ui_attach()
		self._remove_tabs()
		self._restore_header_bar_patch()
		if self.config:
			self.config.save_config()
		self.played = None
		self.keywords = None
		self.shitlist = None

	def _get_gtk(self):
		if self._gtk is not None:
			return self._gtk
		try:
			import gi  # noqa: F401
			from gi.repository import GLib, Gtk
			self._gtk = {"GLib": GLib, "Gtk": Gtk}
		except Exception:
			self._gtk = False
		return self._gtk

	def _start_ui_attach(self):
		gtk = self._get_gtk()
		if not gtk:
			return
		self._try_attach_tabs()
		if self._notebook is None:
			self._ui_poll_id = gtk["GLib"].timeout_add(500, self._try_attach_tabs)

	def _stop_ui_attach(self):
		if self._ui_poll_id is None:
			return
		gtk = self._get_gtk()
		if gtk:
			try:
				gtk["GLib"].source_remove(self._ui_poll_id)
			except Exception:
				pass
		self._ui_poll_id = None

	def _try_attach_tabs(self):
		if self._notebook is not None:
			return False
		gtk = self._get_gtk()
		if gtk and self._attach_tabs(gtk["Gtk"]):
			self._ui_poll_id = None
			return False
		return True

	@staticmethod
	def _children(Gtk, widget):
		if Gtk.get_major_version() >= 4:
			try:
				child = widget.get_first_child()
				while child is not None:
					yield child
					child = child.get_next_sibling()
			except Exception:
				return
		else:
			try:
				yield from widget.get_children()
			except Exception:
				return

	def _find_main_window(self, Gtk):
		try:
			windows = Gtk.Window.list_toplevels()
		except Exception:
			return None
		for window in windows:
			try:
				if isinstance(window, Gtk.ApplicationWindow):
					return window
			except Exception:
				continue
		return windows[0] if windows else None

	def _find_notebook(self, Gtk, window):
		stack = list(self._children(Gtk, window))
		while stack:
			widget = stack.pop(0)
			if isinstance(widget, Gtk.Notebook):
				try:
					if widget.get_n_pages() >= 2:
						return widget
				except Exception:
					return widget
			stack.extend(self._children(Gtk, widget))
		return None

	def _attach_tabs(self, Gtk):
		window = self._find_main_window(Gtk)
		if window is None:
			return False
		notebook = self._find_notebook(Gtk, window)
		if notebook is None:
			return False
		self._notebook = notebook
		for tab_id, title in (("played", "Played"), ("keywords", "Keywords"), ("shitlist", "Shitlist")):
			if tab_id == "played" and not self.settings["played_enabled"]:
				continue
			if tab_id == "keywords" and not self.settings["keywords_enabled"]:
				continue
			page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
			page.id = f"chatwatcher_{tab_id}"
			self._page_ids.add(page.id)
			page.set_hexpand(True)
			page.set_vexpand(True)
			self._build_log_page(Gtk, page, tab_id, title)
			try:
				page.set_margin_top(12)
				page.set_margin_bottom(12)
				page.set_margin_start(12)
				page.set_margin_end(12)
			except AttributeError:
				pass
			tab_label = Gtk.Label(label=title)
			try:
				notebook.append(page, tab_label)
			except AttributeError:
				notebook.append_page(page, tab_label)
			self._pages[tab_id] = page
		try:
			page.show()
		except Exception:
			pass
		self._patch_header_bar()
		return True

	def _add_child(self, parent, child):
		try:
			parent.append(child)
		except AttributeError:
			parent.pack_start(child, False, False, 0)

	def _build_log_page(self, Gtk, page, tab_id, title):
		toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
		clear_button = Gtk.Button(label="Clear Log")
		clear_button.connect("clicked", lambda *_args: self._clear_page_log(tab_id))
		self._add_child(toolbar, clear_button)
		open_button = Gtk.Button(label="Open Log Folder")
		open_button.connect("clicked", lambda *_args: self._open_log_folder(tab_id))
		self._add_child(toolbar, open_button)
		count = Gtk.Label(label="0 entries", hexpand=True, halign=Gtk.Align.END)
		self._add_child(toolbar, count)
		self._add_child(page, toolbar)

		search = Gtk.SearchEntry(placeholder_text="Find in log... (Ctrl+F)", hexpand=True)
		search.connect("search-changed", lambda entry: self._refresh_page(tab_id, entry.get_text()))
		self._add_child(page, search)

		filter_dropdown = None
		if tab_id == "keywords":
			filter_dropdown = Gtk.DropDown.new_from_strings(["All", "Keywords", "Profile views", "Downloads"])
			filter_dropdown.connect("notify::selected", lambda *_args: self._refresh_page(tab_id, search.get_text()))
			self._add_child(page, filter_dropdown)

		scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
		text_view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
		buffer = text_view.get_buffer()
		try:
			scroller.set_child(text_view)
		except AttributeError:
			scroller.add(text_view)
		self._add_child(page, scroller)
		self._page_widgets[tab_id] = {
			"buffer": buffer,
			"count": count,
			"search": search,
			"filter": filter_dropdown,
		}
		self._refresh_page(tab_id)

	def _entries_for_page(self, tab_id):
		if tab_id == "played":
			return self.played.entries if self.played else []
		if tab_id == "keywords":
			return self.keywords.message_log if self.keywords else []
		return self.shitlist.log if self.shitlist else []

	def _format_page_entry(self, tab_id, entry):
		if isinstance(entry, str):
			return entry
		if hasattr(entry, "timestamp"):
			return f"{entry.timestamp} [{entry.source}] {entry.user}: {entry.message}"
		return str(entry)

	def _refresh_all_pages(self):
		for tab_id in self._page_widgets:
			self._refresh_page(tab_id)

	def _refresh_page(self, tab_id, query=""):
		widgets = self._page_widgets.get(tab_id)
		if not widgets:
			return
		lines = [self._format_page_entry(tab_id, entry) for entry in self._entries_for_page(tab_id)]
		query = (query or "").casefold()
		lines = [line for line in lines if not query or query in line.casefold()]
		text = "\n".join(lines)
		widgets["buffer"].set_text(text)
		widgets["count"].set_text(f"{len(lines)} entries")

	def _clear_page_log(self, tab_id):
		if tab_id == "played" and self.played:
			self.played.clear_log()
		elif tab_id == "keywords" and self.keywords:
			self.keywords.message_log.clear()
		elif tab_id == "shitlist" and self.shitlist:
			self.shitlist.log.clear()
		self._refresh_page(tab_id)

	def _open_log_folder(self, tab_id):
		folder = Path(__file__).resolve().parent / "logs" / {
			"played": "listenings",
			"keywords": "keywordwatch",
			"shitlist": "shitlist",
		}.get(tab_id, tab_id)
		folder.mkdir(parents=True, exist_ok=True)
		try:
			os.startfile(folder)
		except (AttributeError, OSError):
			pass

	def _patch_header_bar(self):
		if self._header_bar_original is not None:
			return
		try:
			from pynicotine.gtkgui.mainwindow import MainWindow
			original = MainWindow.set_active_header_bar
		except Exception:
			return

		plugin = self

		def set_active_header_bar(window, page_id, *args, **kwargs):
			if page_id in plugin._page_ids:
				return None
			return original(window, page_id, *args, **kwargs)

		self._header_bar_original = original
		self._header_bar_class = MainWindow
		MainWindow.set_active_header_bar = set_active_header_bar

	def _restore_header_bar_patch(self):
		if self._header_bar_original is not None and self._header_bar_class is not None:
			try:
				self._header_bar_class.set_active_header_bar = self._header_bar_original
			except Exception:
				pass
		self._header_bar_original = None
		self._header_bar_class = None

	def _remove_tabs(self):
		if self._notebook is None:
			return
		for page in list(self._pages.values()):
			try:
				page_num = self._notebook.page_num(page)
				if page_num >= 0:
					self._notebook.remove_page(page_num)
			except Exception:
				pass
		self._pages.clear()
		self._page_ids.clear()
		self._notebook = None

	def cw_command(self, args, **_kwargs):
		argument = (args or "").strip().casefold()
		if argument == "status":
			self.output(
				"ChatWatcher V2 — Played: %s, Keywords: %s, Shitlist: %s"
				% (
					"on" if self.settings["played_enabled"] else "off",
					"on" if self.settings["keywords_enabled"] else "off",
					"on" if self.settings["shitlist_enabled"] else "off",
				)
			)
		elif argument == "help":
			self.output("/played, /kw, /shitlist, and /cw status")
		else:
			self.output("Use Nicotine+ plugin Settings to configure ChatWatcher V2.")
		return True

	def played_command(self, args, **_kwargs):
		if self.played is None:
			return False
		parts = (args or "").strip().split(maxsplit=1)
		command = parts[0].casefold() if parts else "open"
		username = parts[1].strip() if len(parts) > 1 else ""
		if command == "hide" and username:
			self.played.block_user(username)
		elif command == "unhide" and username:
			self.played.unblock_user(username)
		elif command == "clear":
			self.played.clear_log()
		elif command == "list":
			self.output("Hidden Played users: %s" % (", ".join(sorted(self.played.blocked_users)) or "none"))
		elif command == "exception":
			self._played_exception_command(username)
		return True

	def _played_exception_command(self, argument):
		parts = argument.split(maxsplit=1)
		action = parts[0].casefold() if parts else "list"
		phrase = parts[1].strip() if len(parts) > 1 else ""
		if action == "add" and phrase:
			added = self.played.add_exception(phrase)
			self.output(("Added" if added else "Already listed") + f" Played exception: {phrase}")
		elif action == "remove" and phrase:
			removed = self.played.remove_exception(phrase)
			self.output(("Removed" if removed else "Not found") + f" Played exception: {phrase}")
		elif action == "list":
			exceptions = ", ".join(self.played.get_exceptions()) or "none"
			self.output(f"Played exceptions: {exceptions}")
		else:
			self.output("Usage: /played exception [add|remove] <phrase> or /played exception list")

	def keywords_command(self, args, **_kwargs):
		self.output("Keyword Watch commands are being implemented next.")
		return True

	def shitlist_command(self, args, **_kwargs):
		self.output("Shitlist commands are being implemented next.")
		return True

	@staticmethod
	def _played_action_text(user, line):
		"""Return only /me text, including Nicotine+'s rendered form."""
		text = str(line or "").strip()
		if text.startswith("/me "):
			return text[4:].strip()
		prefix = f"* {user} "
		if text.startswith(prefix):
			return text[len(prefix):].strip()
		return None

	def public_room_message_notification(self, room, user, line):
		if self.played and self.settings["played_enabled"]:
			text = self._played_action_text(user, line)
			if text:
				self.played.capture_now_playing(user, text, source=room)
		if self.keywords and self.settings["keywords_enabled"]:
			matches = self.keywords.matches(line)
			if matches:
				self.keywords.message_log.insert(0, f"[{room}] {user}: {line} [kw: {', '.join(matches)}]")
		if self.shitlist:
			matches = self.shitlist.process_message(line)
			if matches:
				self.shitlist.log.insert(0, f"[{room}] {user}: {line} [kw: {', '.join(matches)}]")
		self._refresh_all_pages()

	def incoming_public_chat_event(self, room, user, line):
		"""Capture another user's raw /me before Nicotine+ renders it."""
		if self.played and self.settings["played_enabled"]:
			text = self._played_action_text(user, line)
			if text:
				self.played.capture_now_playing(user, text, source=room)
		self._refresh_all_pages()
		return None

	def incoming_private_chat_event(self, user, line):
		if self.played and self.settings["played_enabled"]:
			text = self._played_action_text(user, line)
			if text:
				self.played.capture_now_playing(user, text, source="private")
		if self.keywords and self.settings["keywords_enabled"]:
			matches = self.keywords.matches(line)
			if matches:
				self.keywords.message_log.insert(0, f"[Private] {user}: {line} [kw: {', '.join(matches)}]")
		self._refresh_all_pages()

	def incoming_public_chat_notification(self, room, user, line):
		"""Capture transformed /me output, which may not reach the public hook."""
		if self.played and self.settings["played_enabled"]:
			text = self._played_action_text(user, line)
			if text:
				self.played.capture_now_playing(user, text, source=room)
		self._refresh_all_pages()

	def incoming_private_chat_notification(self, user, line):
		"""Capture transformed private /me output without duplicating event data."""
		if self.played and self.settings["played_enabled"]:
			text = self._played_action_text(user, line)
			if text:
				self.played.capture_now_playing(user, text, source="private")
		self._refresh_all_pages()

	def _login_username(self):
		try:
			return str(self.core.users.login_username)
		except (AttributeError, TypeError):
			return "(you)"

	def outgoing_public_chat_notification(self, room, line):
		"""Capture your own /now output, which is not an incoming room event."""
		if self.played and self.settings["played_enabled"]:
			text = self._played_action_text(self._login_username(), line)
			if text:
				self.played.capture_now_playing(
					self._login_username(), text, source=room, is_self=True
				)
		self._refresh_all_pages()

	def outgoing_public_chat_event(self, room, line):
		"""Capture your own /me before Nicotine+ transforms it for display."""
		if self.played and self.settings["played_enabled"]:
			text = self._played_action_text(self._login_username(), line)
			if text:
				self.played.capture_now_playing(
					self._login_username(), text, source=room, is_self=True
				)
		self._refresh_all_pages()

	def outgoing_private_chat_event(self, user, line):
		"""Capture your own private /me before Nicotine+ sends it."""
		if self.played and self.settings["played_enabled"]:
			text = self._played_action_text(self._login_username(), line)
			if text:
				self.played.capture_now_playing(
					self._login_username(), text, source="private", is_self=True
				)
		self._refresh_all_pages()

	def outgoing_private_chat_notification(self, user, line):
		"""Capture your own private /now output after dispatch."""
		if self.played and self.settings["played_enabled"]:
			text = self._played_action_text(self._login_username(), line)
			if text:
				self.played.capture_now_playing(
					self._login_username(), text, source="private", is_self=True
				)
		self._refresh_all_pages()