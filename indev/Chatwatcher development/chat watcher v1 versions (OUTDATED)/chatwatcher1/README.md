# Chat watcher v1 — Nicotine+ plugin

**Author:** kiquja

One plugin that merges the **Listenings**, **Keyword Watch**, and **Shitlist** plugins into a single install — with **Played**, **Keywords**, and **Shitlist** tabs — keeping every feature of the originals. The three feature sets are fully independent: each has its own tab/log/settings/command, and the settings are namespaced so nothing collides.

## What it does

### 1. Played

Collects other users' `/nowplaying` output (which Nicotine+ renders as `* <user> <text>`) into a **"Played"** tab, saved to a log file, with user blocking and retention control.

```
10:31:59 AM * Pa is having an eargasm to: Sunn O))) - Fried Eagle Mind (9:46)
```

- Detects `/me` actions across every joined room (via `public_room_message_notification`) plus private chat (`incoming_private_chat_event`), and your own via the `outgoing_*` events (marked "(you)").
- Log file: `logs/listenings/listenings.log` (JSON-lines).
- Retention: `20 min` … `7 days` (default `1 day`).

### 2. Keywords

Collects messages from *other* users that mention your keywords (e.g. your username) into a **"Keywords"** tab, in public rooms and private chat.

```
10:31:59 AM [main] <alice> hey ambrose, check this out  [kw: ambrose]
```

- Hooks `public_room_message_notification` (every joined room) / `incoming_private_chat_notification` (private chat) — pure observers.
- Case-insensitive substring match by default (toggleable).
- If no keywords are set, it watches for your username.
- Log file: `logs/keywordwatch/keywordwatch.log` (JSON-lines).
- **Collects from ignored/banned users**: Keyword Watch deliberately bypasses your ignore/ban preferences — a user you've ignored still has their public-room keyword hits logged here (their messages reach it via the #Public global feed).

### 3. Shitlist

IP-bans and IP-ignores users who say keywords you define, plus extras:

- **Keyword banning** — a message containing a Shitlist keyword bans+ignores the sender **by name (soft) and by IP (hard)**, belt-and-suspenders style: the name block filters them instantly, and the IP block survives account re-creation. Every ban is logged with the username and IP (when known).
- **Temporary "Ignore for…"** — right-click a user → **Ignore for…** → `20 min / 1 hr / 12 hr / 1 day / 3 days / 7 days`.
- **Shitlisted Users** list — a live view of everyone currently banned *and* ignored (by name or IP), with Add/Remove in the settings dialog.
- **Message Exceptions** — a whitelist of ignored users whose messages still show (covers both name- and IP-ignored users).
- **Open Logs Folder buttons** — three buttons in the settings dialog (`/cw`) that open each feature's own log folder (Played → `logs/listenings/`, Keywords → `logs/keywordwatch/`, Shitlist → `logs/shitlist/`).

## Settings

Open **Settings → Plugins → Chat watcher v1 → Settings**. Options are grouped:

| Group | Options |
|---|---|
| **Played (/nowplaying)** | Clear log (checkbox), Hide users (`list string`), Keep entries for (`dropdown`) |
| **Keywords** | Keywords (`list string`), Match case-sensitively (`bool`), Clear log (checkbox), Hide users (`list string`), Keep entries for (`dropdown`) |
| **Shitlist** | Auto IP-ban+ignore (`bool`), Keywords (`list string`) |
| **Shitlist: Message Exceptions** | Ignored users whose messages still show (`list string`) |
| **Shitlist: Shitlisted Users** | Users currently banned+ignored (`list string`) |

## Chat commands

```
/cw                        open the settings dialog  (/chatwatcher also works)
/cw status                 show current settings summary
/cw help                   show this plugin's overview

/played                    open the Played settings dialog
/played clear              clear the Played log
/played hide <user>        hide a user's now-playing entries
/played unhide <user>      un-hide a user
/played list               list hidden users and retention

/kw                        open the keyword-watch settings dialog
/kw add <word>             add a keyword
/kw remove <word>          remove a keyword
/kw list                   list keywords

/shitlist                  open the shitlist settings dialog
/shitlist add <word>       add a keyword (quote multi-word phrases)
/shitlist remove <word>    remove a keyword
/shitlist list             list keywords
```

## Install

### Option A — install the zip

1. In Nicotine+: **Settings → Plugins → Install Plugin**.
2. Select `chatwatcher.zip`.
3. Tick **Chat watcher v1** in the list to enable it.

### Option B — copy the folder

Copy the `chatwatcher` folder (containing `__init__.py` and `PLUGININFO`) into your Nicotine+ plugins folder:

- **Windows**: `%APPDATA%\nicotine\plugins\`
- **Linux**: `~/.local/share/nicotine/plugins/`

Then enable it under **Settings → Plugins**. No restart needed.

> **Note:** this replaces the three old plugins. Disable **Listenings**, **Keyword Watch**, and **Shitlist** after enabling **Chat watcher v1** so their hooks/patches don't run twice.

## How it works (page logic)

1. **Hooks** — Public-room messages are captured via `public_room_message_notification` (fires for every joined room, not just the focused one); private chat via `incoming_private_chat_event` / `incoming_private_chat_notification`; your own messages via the `outgoing_*` events.
2. **Filter** — each feed skips your own messages, blocked users, empty lines, and (for Keyword Watch) lines with no keyword match.
3. **Store** — matched entries are inserted newest-first into the feed's in-memory list and written to a JSON-lines log in that feature's own folder under `logs/` (`listenings` / `keywordwatch` / `shitlist`).
4. **Prune** — entries past each feed's retention window are dropped (on add, on load, and every 60 s).
5. **Render** — each tab is rebuilt from its in-memory list, newest first.

Both tabs attach to Nicotine+'s main notebook (GTK 3 and GTK 4 compatible). To keep Nicotine+ from crashing with `KeyError('<tab id>')` when you switch to a plugin tab, the plugin patches `MainWindow.set_active_header_bar` to skip its own tab ids (the single funnel every header-bar/toolbar swap goes through), and the "Ignore for…" menu + message-exceptions whitelist monkey-patch `UserPopupMenu.setup_user_menu` and `NetworkFilter.is_user_ignored` / `is_user_ip_ignored`. All patches are restored when the plugin is disabled.

## Customizing

| Want to change… | Edit this |
|---|---|
| Tab names (`Played`, `Keywords`) | `LISTENINGS_TAB_NAME` / `KEYWORDWATCH_TAB_NAME` near the top of `__init__.py` |
| Log file names & folders | `LISTENINGS_LOG_FILENAME` / `KEYWORDWATCH_LOG_FILENAME` / `SHITLIST_LOG_FILENAME`, plus the `_listenings_log_dir()` / `_kw_log_dir()` / `_shitlist_log_dir()` helpers |
| Retention options / defaults | `RETENTION_SECONDS` dict + the `"listenings_retention"` / `"kw_retention"` defaults |
| Timestamp format (12-h vs 24-h) | `time.strftime(...)` in `_listenings_format_entry()` / `_kw_format_entry()` — e.g. `"%H:%M:%S"` for 24-hour |
| Temporary-ignore durations | `Plugin.IGNORE_DURATIONS` tuple |

## Notes & limitations

- **No official "add tab" API** exists, so the tabs reach the main `Gtk.Notebook` via `Gio.Application.get_default()` + garbage-collector recovery of the `MainWindow` wrapper. Everything is wrapped in try/except so a GTK mismatch never crashes Nicotine+.
- **Header-bar fix**: Nicotine+'s `on_switch_page` calls `set_active_header_bar(page.id)`, which looks the tab up in `window.tabs` and raises `KeyError` for plugin tabs. This plugin patches `MainWindow.set_active_header_bar` to no-op for its own tab ids instead of relying on wrapping `notebook.switch_page_callback` (which could be bypassed).
- Keyword matching is plain substring matching (like the built-in chat censor), not regex or word-boundary aware.
- The "Ignore for…" menu and message-exceptions rely on internal GUI classes (`pynicotine.gtkgui.widgets.popupmenu`, `NetworkFilter`). They work in the graphical client but not headless mode, and are verified against Nicotine+ **3.3.10**.
- IP bans are permanent until removed. Use the **Shitlisted Users** list (which now also shows IP-banned users) to unban, or Nicotine+'s banned-IPs settings page.
- Logs are JSON-lines so retention pruning can use real timestamps; the tabs show the human-readable format.
