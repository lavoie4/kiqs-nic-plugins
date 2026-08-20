# ChatWatcher V2 Knowledge

This document records verified findings from building and testing ChatWatcher V2 with Nicotine+ 3.3.10, GTK 4.16.12, and Python 3.12.9 on Windows.

## Nicotine+ Plugin Packaging

Nicotine+ discovers a plugin from the plugin folder's `__init__.py`.

A working plugin folder must contain:

- `__init__.py`
- `PLUGININFO`
- Any additional source files copied into the same plugin folder

`PLUGININFO` uses this format:

```text
Version = "0.1.0"
Authors = ["kiquja"]
Name = "ChatWatcher V2"
Description = "Combined Played, Keywords, and Shitlist monitoring for Nicotine+."
```

The plugin directory name must be a valid Python module name. Do not use a dot in the directory name. This failed:

```text
chatwatcherv2_0.1
```

Nicotine+ interpreted the dot as a package separator and produced import errors. The working name is:

```text
chatwatcherv2_0_1
```

The loader executes the plugin folder's `__init__.py` as a standalone module. Relative imports such as these are unsafe in the loader:

```python
from .config import Config
from .features.played import PlayedFeature
```

The active loader therefore keeps the required configuration and feature classes directly in `__init__.py`. The separate `config.py`, `features/`, and `ui/` files remain useful source organization and historical scaffolding, but the loader must not depend on package-relative imports.

## BasePlugin Structure

The loader uses:

```python
from pynicotine.pluginsystem import BasePlugin

class Plugin(BasePlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def init(self):
        pass

    def disable(self):
        pass
```

Nicotine+ expects:

- `Plugin(BasePlugin)`
- `settings`
- `metasettings`
- A command dictionary containing callback, description, parameters, and group
- `init()` for startup
- `disable()` for cleanup

The plugin currently exposes:

- `/cw`
- `/chatwatcher`
- `/played`
- `/kw`
- `/shitlist`

## Important Nicotine+ Chat Events

Nicotine+ has both event hooks and notification hooks.

Events can modify or observe data before processing. Notifications observe processed data. For Played, both paths matter because `/me` output is transformed by Nicotine+.

### Incoming public chat

The important hook is:

```python
def incoming_public_chat_event(self, room, user, line):
    pass
```

For a now-playing command, the raw line looks like:

```text
/me np: Kanye West - No More Parties in LA
```

Nicotine+ then renders it as a notification similar to:

```text
* adxwkd np: Kanye West - No More Parties in LA
```

The current implementation captures the raw event and also handles the rendered notification fallback.

`public_room_message_notification(room, user, line)` is not guaranteed for every joined room. It is especially associated with the global public feed. Do not rely on it alone for Played.

### Incoming private chat

```python
def incoming_private_chat_event(self, user, line):
    pass
```

Private `/me` messages are normalized and sent to Played.

### Outgoing public chat

```python
def outgoing_public_chat_event(self, room, line):
    pass
```

This is needed to capture the user's own `/now` command before Nicotine+ transforms it.

### Outgoing private chat

```python
def outgoing_private_chat_event(self, user, line):
    pass
```

The user's login name is read from:

```python
self.core.users.login_username
```

The outgoing notification hooks are also present as fallbacks:

```python
def outgoing_public_chat_notification(self, room, line):
    pass

def outgoing_private_chat_notification(self, user, line):
    pass
```

### Avoiding duplicate events

Nicotine+ can emit both an event and a notification for one message. Played checks recent entries for the same user, message, and source before inserting a new record.

Incoming notification handlers only feed Played. They must not forward the entire message into Keywords and Shitlist because those features would receive duplicate records when their post-processing hooks also fire.

## Played Message Normalization

Played accepts only action-style messages:

- Raw `/me text`
- Rendered `* username text`

Ordinary messages are rejected before marker matching. This prevents ordinary chat containing `np:` from being logged accidentally.

The helper effectively performs:

```text
/me np: Artist - Song
```

into:

```text
np: Artist - Song
```

and:

```text
* user np: Artist - Song
```

into:

```text
np: Artist - Song
```

## Played Markers

Default markers currently include:

- `np:`
- `now playing`
- `is listening to`
- `is now listening to`
- `is having an eargasm to`

Marker matching is case-insensitive substring matching.

## Played Exceptions

Regular `/me` roleplay messages can resemble now-playing output. Played supports persistent phrase exceptions.

Commands:

```text
/played exception add <phrase>
/played exception remove <phrase>
/played exception list
```

Examples:

```text
/played exception add is listening to you
/played exception remove is listening to you
/played exception list
```

Exception matching is case-insensitive. If an exception phrase appears in a message, the message is rejected before marker matching.

Exceptions are stored under the Played namespace as:

```json
{
  "played": {
    "now_playing_exceptions": []
  }
}
```

## Played Storage

Played logs are JSON Lines files under:

```text
logs/listenings/
```

Daily files use this format:

```text
log1[YYYY-MM-DD].log
```

Each line stores fields equivalent to:

```json
{
  "timestamp": "2026-08-20T00:25:56",
  "user": "Alice",
  "message": "np: Artist - Song",
  "source": "Room",
  "is_self": false
}
```

Played loads existing JSONL entries during initialization, sorts newest first, and prunes entries according to retention.

Retention options:

- `20 min`
- `1 hr`
- `12 hr`
- `1 day`
- `3 days`
- `7 days`
- `1 month`
- `forever`

The retention setting is exposed through Nicotine+'s plugin settings as `played_retention` and stored under the Played namespace.

## Played User Controls

```text
/played hide <username>
/played unhide <username>
/played clear
/played list
```

Hidden users are stored case-insensitively. Hiding a user removes their current visible entries and persists the hidden-user list.

`Clear Log` clears memory and deletes the Played JSONL files from disk.

## GTK Pane Integration

There is no official add-plugin-tab API being used here. ChatWatcher finds Nicotine+'s main `Gtk.Notebook` by walking the main application window widget tree.

The adapter supports GTK 3 and GTK 4 patterns:

- GTK 4 uses `get_first_child()` and `get_next_sibling()`.
- GTK 3 uses `get_children()`.
- GTK 4 adds pages with `notebook.append(page, label)`.
- GTK 3 adds pages with `notebook.append_page(page, label)`.

The pages are:

- Played
- Keywords
- Shitlist

All pages have stable IDs:

```text
chatwatcher_played
chatwatcher_keywords
chatwatcher_shitlist
```

Nicotine+ GTK 4 requires notebook pages to expose `.id`. Without it, switching tabs caused:

```text
AttributeError: 'Box' object has no attribute 'id'
```

The plugin also patches `MainWindow.set_active_header_bar` only for these ChatWatcher page IDs. This prevents Nicotine+ from looking up plugin pages in its internal `window.tabs` mapping. The original method is restored in `disable()`.

The UI attachment is delayed with a GLib timer because Nicotine+'s main window and notebook may not exist when the plugin's `init()` first runs.

## Pane Layout

Each pane has:

- `Clear Log`
- `Open Log Folder`
- Entry count
- Search field with `Ctrl+F` placeholder
- Scrollable text log

Keywords additionally has a filter dropdown:

- All
- Keywords
- Profile views
- Downloads

Loaded entries are explicitly rendered when the pane is built. This is required because feature data loads before GTK widgets are attached.

## Deployment

Workspace source:

```text
C:\Users\kiquj\Desktop2\New folder\ChatWatcher V2\chatwatcher_v2
```

Workspace build:

```text
C:\Users\kiquj\Desktop2\New folder\ChatWatcher V2\chatwatcherv2_0_1
```

Live Nicotine+ plugin:

```text
%APPDATA%\nicotine\plugins\chatwatcherv2_0_1
```

The live folder should be updated only after a focused validation succeeds.

Typical deployment sequence:

```powershell
$workspace = 'C:\Users\kiquj\Desktop2\New folder\ChatWatcher V2'
$build = "$workspace\chatwatcherv2_0_1"
$live = "$env:APPDATA\nicotine\plugins\chatwatcherv2_0_1"

Copy-Item "$workspace\chatwatcher_v2\__init__.py" "$build\__init__.py" -Force
Copy-Item "$build\*" $live -Recurse -Force
```

Validate the loader:

```powershell
Push-Location $live
python -m py_compile __init__.py
Pop-Location
```

Do not leave `__pycache__` directories in the shipped plugin when preparing a clean build.

## Tests That Passed

The following focused checks passed during development:

- Standalone loader import without package-relative imports
- Plugin initialization outside Nicotine+
- Played marker matching
- Played exception matching
- JSONL persistence and reload
- Hidden-user filtering
- Clear-log behavior
- Raw `/me` plus rendered notification duplicate suppression
- Incoming and outgoing Played hook handling
- Ordinary messages containing `np:` are not captured
- GTK-facing loader compilation

## Historical v1 Findings

The workspace contains multiple v1 folders. Many contain duplicated, corrupted, or dead code and should not be copied wholesale.

Useful verified patterns from the newer v1 versions:

- Use `incoming_public_chat_event` for raw `/me` messages.
- Strip `/me ` before testing markers.
- Use `outgoing_public_chat_event` and `outgoing_private_chat_event` for the user's own `/now` output.
- Treat `public_room_message_notification` as a global-feed/post-processing path, not the only source of room messages.
- Use stable page IDs and patch the header-bar lookup narrowly for plugin tabs.

No exact v1 lines were copied into ChatWatcher V2. The current implementation is a smaller standalone equivalent based on the observed behavior and API signatures.

## Unrelated Nicotine+ Error

This error appeared during startup:

```text
PermissionError: [WinError 32]
... nicotine\\words.dbn
```

It occurs during Nicotine+'s share rescan when `words.dbn` is locked by another process. It is unrelated to ChatWatcher V2. Restarting Nicotine+ and checking for another running Nicotine+ process is safer than deleting database files immediately.

## Current Known Limitations

- Keywords and Shitlist feature logic is still less complete than Played.
- Profile-view and download logging are not fully implemented in the current standalone loader.
- The GTK pane currently uses a simple `Gtk.TextView` log rather than a row-based model with per-entry context menus.
- Settings changes that require rebuilding or removing tabs are not yet dynamically applied while the plugin is running.
- The legacy `features/` and `ui/` files are not the authoritative Nicotine+ loader path.
