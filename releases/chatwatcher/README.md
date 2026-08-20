# Chat watcher v1 - Nicotine+ plugin

**Author:** kiquja

One plugin that merges the **Listenings**, **Keyword Watch**, and **Shitlist** plugins into a single install - with **Played**, **Keywords**, and **Shitlist** tabs - keeping every feature of the originals. The three feature sets are fully independent: each has its own tab/log/settings/command, and the settings are namespaced so nothing collides.

## What it does

### 1. Played

Collects other users' `/nowplaying` output (which Nicotine+ renders as `* <user> <text>`) into a **"Played"** tab, saved to a log file, with user blocking and retention control.

```
10:31:59 AM * Pa is having an eargasm to: Sunn O))) - Fried Eagle Mind (9:46)
```

- Detects `/me` actions on the global `#Public` feed (via `public_room_message_notification`) plus private chat (`incoming_private_chat_event`), and your own via the `outgoing_*` events (marked "(you)").
- **Now-playing filter**: only `/me` lines that look like an auto "now playing" announcement are captured (matched against the **now-playing markers** setting, e.g. `np:`, `is now listening to`); stray `/me` emotes are skipped.
- Log file: one file per day in `logs/listenings/`, named `log1[2026-08-18].log`, `log2[2026-08-19].log`, ... (JSON-lines, numbered by consecutive days).
- Retention: `20 min` ... `7 days` (default `1 day`).
- **Disable**: turn off "show the Played tab" in settings to disable this feature entirely (the tab is removed).

### 2. Keywords

Collects messages from *other* users that mention your keywords (e.g. your username) into a **"Keywords"** tab, in public rooms and private chat.

```
10:31:59 AM [main] <alice> hey ambrose, check this out  [kw: ambrose]
```

- Hooks `public_room_message_notification` (the global `#Public` feed) / `incoming_private_chat_notification` (private chat) - pure observers.
- Case-insensitive substring match by default (toggleable).
- If no keywords are set, it watches for your username.
- **Go to room**: right-click an entry → **Go to room** to open that room and switch to it (private-chat entries don't show this option).
- **Profile views & downloads**: also logs (with timestamps) when another user views your profile or finishes downloading a file from your shares.
- **Filter dropdown**: a dropdown in the toolbar (next to Clear Log / Open Log Folder) filters the list by **All / Keywords / Profile views / Downloads**.
- **Hide users**: expand the **Hide users** section in the pane (or use the setting in `/cw`) to list users whose keyword mentions, profile views and downloads you don't want to see.
- Log file: one file per day in `logs/keywordwatch/`, named `log1[2026-08-18].log`, `log2[2026-08-19].log`, ... (JSON-lines).
- **Collects from ignored/banned users**: Keyword Watch deliberately bypasses your ignore/ban preferences - a user you've ignored still has their public-room keyword hits logged here (their messages reach it via the #Public global feed).
- **Disable**: turn off "show the Keywords tab" in settings to disable this feature entirely (the tab is removed).

### 3. Shitlist

IP-bans and IP-ignores users who say keywords you define, plus extras:

- **Keyword banning** - a message containing a Shitlist keyword bans+ignores the sender **by name (soft) and by IP (hard)**, belt-and-suspenders style: the name block filters them instantly, and the IP block survives account re-creation. Every ban is logged with the username and IP (when known).
- **Enable Shitlist** - a checkbox at the top of the Shitlist pane turns the whole feature on/off (without losing its settings).
- **Automatic / Manual review mode** - a dropdown in the Shitlist pane: **Automatic mode** bans+ignores users who say a keyword (name + IP), while **Manual review mode** only logs them (like the Keywords pane), so you can review and ban them yourself.
- **Now-playing skip** - auto "now playing" `/me` lines (e.g. `* user is now listening to...`) are not flagged, so a song/artist title containing a keyword won't trigger a false ban; manual `/me` abuse still is.
- **Shitlist pane** - a dedicated tab with the flagged-users log on the left (with **Clear Log** / **Open Log Folder** / **Import Log** buttons) and **all Shitlist settings on the right** (mode, keywords, whitelist, message-exceptions whitelist, Shitlisted Users list, retention). Each entry shows the full flagged message, ending with `[kw:keyword]`.
- **Slur counter** - at the bottom of the Shitlist settings column, a summary of each offender: how many times they've triggered a keyword, plus how long ago their latest hit was. Sort by **Most triggers** or **Most recent**. Users are dropped off the list once both their last swear and last seen are more than 30 days old.
- **Temporary "Ignore for..."** - right-click a user → **Ignore for...** → `20 min / 1 hr / 12 hr / 1 day / 3 days / 7 days`.
- **Shitlisted Users** list - a manual list of names to ban+ignore: add a name to ban+ignore it (name + IP), remove to unban+unignore, in the Shitlist pane.
- **Message Exceptions** - a whitelist of ignored users whose messages still show **in public rooms only** (covers both name- and IP-ignored users). They stay ignored everywhere else, so they still can't send you private messages - the whitelist only lifts the ignore filter for the public feed.
- **Right-click a flagged entry** - **Remove entry**, **Block + ignore user**, or **Whitelist user** (so they stop being flagged when they say keywords).
- **Import Log** - click **Import Log** to open a saved log file and view it temporarily on the left; click **Close Log** to return to the live log. Imported entries get the same right-click menu (remove / block+ignore / whitelist).
- **Open Logs Folder buttons** - the settings dialog (`/cw`) has buttons for the Played and Keywords log folders; the Shitlist pane has its own **Open Log Folder** / **Clear Log** / **Import Log** buttons.

## Settings

Open **Settings → Plugins → Chat watcher v1 → Settings**. Options are grouped:

| Group | Options |
|---|---|
| **Played (/nowplaying)** | Show Played tab (`bool`), Hide users (`list string`), Keep entries for (`dropdown`), Now-playing markers (`list string`), Clear Played Log (button) |
| **Keywords** | Show Keywords tab (`bool`), Keywords (`list string`), Match case-sensitively (`bool`), Hide users (`list string`), Keep entries for (`dropdown`), Clear Keywords Log (button) |
| **Shitlist** | *(all Shitlist settings now live in the Shitlist pane, not here)* |

The **Clear Played Log** / **Clear Keywords Log** and **Open ... Log Folder** buttons live at the bottom of the settings dialog (the old "tick to clear" checkboxes are gone). Shitlist settings, including its whitelist and Shitlisted Users list, are edited inside the Shitlist pane itself.

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

### Option A - install the zip

1. In Nicotine+: **Settings → Plugins → Install Plugin**.
2. Select `chatwatcher.zip`.
3. Tick **Chat watcher v1** in the list to enable it.

### Option B - copy the folder

Copy the `chatwatcher` folder (containing `__init__.py` and `PLUGININFO`) into your Nicotine+ plugins folder:

- **Windows**: `%APPDATA%\nicotine\plugins\`
- **Linux**: `~/.local/share/nicotine/plugins/`

Then enable it under **Settings → Plugins**. No restart needed.

> **Note:** this replaces the three old plugins. Disable **Listenings**, **Keyword Watch**, and **Shitlist** after enabling **Chat watcher v1** so their hooks/patches don't run twice.

## How it works (page logic)

1. **Hooks** - Public-room messages via `public_room_message_notification` (the global `#Public` feed); private chat via `incoming_private_chat_event` / `incoming_private_chat_notification`; profile views via the internal `user-info-request` event; downloads-from-your-shares via `upload_finished_notification`; your own messages via the `outgoing_*` events.
2. **Filter** - each feed skips your own messages, blocked users, empty lines, and (for Keyword Watch) lines with no keyword match.
3. **Store** - matched entries are inserted newest-first into the feed's in-memory list and written to that feature's own folder under `logs/` (`listenings` / `keywordwatch` / `shitlist`), one JSON-lines file per day named `logN[YYYY-MM-DD].log` (numbered by consecutive days).
4. **Prune** - entries past each feed's retention window are dropped (on add, on load, and every 60 s).
5. **Render** - each tab is rebuilt from its in-memory list, newest first.
6. **Find** — press **Ctrl+F** in any pane to search its log; the pane shows only entries containing your search text (case-insensitive). Esc clears the search.

All three tabs attach to Nicotine+'s main notebook (GTK 3 and GTK 4 compatible). To keep Nicotine+ from crashing with `KeyError('<tab id>')` when you switch to a plugin tab, the plugin patches `MainWindow.set_active_header_bar` to skip its own tab ids (the single funnel every header-bar/toolbar swap goes through), and the "Ignore for..." menu monkey-patches `UserPopupMenu.setup_user_menu`. The message-exceptions whitelist is applied locally inside `public_room_message_notification` (the ignore re-check is skipped for whitelisted names) - no `NetworkFilter` patch - so whitelisted users stay ignored everywhere else, including private messages. All patches are restored when the plugin is disabled.

## Customizing

| Want to change... | Edit this |
|---|---|
| Tab names (`Played`, `Keywords`, `Shitlist`) | `LISTENINGS_TAB_NAME` / `KEYWORDWATCH_TAB_NAME` / `SHITLIST_TAB_NAME` near the top of `__init__.py` |
| Log folders & daily naming | `_listenings_log_dir()` / `_kw_log_dir()` / `_shitlist_log_dir()`, plus the `LOG_DATE_FORMAT` constant and the `_daily_filename()` / `_save_daily_log()` / `_load_daily_log()` helpers |
| Retention options / defaults | `RETENTION_SECONDS` dict + the `"listenings_retention"` / `"kw_retention"` defaults |
| Timestamp format (12-h vs 24-h) | `time.strftime(...)` in `_listenings_format_entry()` / `_kw_format_entry()` - e.g. `"%H:%M:%S"` for 24-hour |
| Now-playing markers | `DEFAULT_NOW_PLAYING_MARKERS` near the top of `__init__.py` (or the "Now-playing markers" setting) |
| Temporary-ignore durations | `Plugin.IGNORE_DURATIONS` tuple |

## Notes & limitations

- **No official "add tab" API** exists, so the tabs reach the main `Gtk.Notebook` via `Gio.Application.get_default()` + garbage-collector recovery of the `MainWindow` wrapper. Everything is wrapped in try/except so a GTK mismatch never crashes Nicotine+.
- **Header-bar fix**: Nicotine+'s `on_switch_page` calls `set_active_header_bar(page.id)`, which looks the tab up in `window.tabs` and raises `KeyError` for plugin tabs. This plugin patches `MainWindow.set_active_header_bar` to no-op for its own tab ids instead of relying on wrapping `notebook.switch_page_callback` (which could be bypassed).
- Keyword matching is plain substring matching (like the built-in chat censor), not regex or word-boundary aware.
- The "Ignore for..." menu relies on the internal GUI class `pynicotine.gtkgui.widgets.popupmenu`. It works in the graphical client but not headless mode, and is verified against Nicotine+ **3.3.10**.
- IP bans are permanent until removed. Use the **Shitlisted Users** list to unban a name, or Nicotine+'s banned-IPs settings page.
- The Shitlist pane shows keyword-hit messages. Older ban-only records (from before the pane existed) won't appear in it, but they remain in your `logs/shitlist/` backup.
- Profile-view logging subscribes to Nicotine+'s internal `user-info-request` event (emitted on the main thread when someone browses your profile) and unsubscribes on disable.
- Logs are JSON-lines so retention pruning can use real timestamps; the tabs show the human-readable format. Each feature writes one file per day (`log1[date]`, `log2[date]`, ...), numbered by consecutive days since that feature first logged.
