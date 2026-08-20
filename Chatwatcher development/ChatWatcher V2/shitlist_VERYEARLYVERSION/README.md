# Shitlist — Nicotine+ plugin

Bans users who say keywords you define, and adds a temporary **"Ignore for…"** option to the user right-click menu.

## What it does

1. **Keyword banning** — Watches incoming room chat and private chat. If a message contains a keyword on your Shitlist, the sender is **banned and ignored** (`core.network_filter.ban_user` + `ignore_user`). Matching is case-insensitive substring matching, the same behaviour as Nicotine+'s built-in chat censor feature ("Chats → censor").

2. **User-friendly keyword menu** — Keywords are edited in the standard plugin settings dialog (a list editor with Add/Edit/Remove, identical to the censor list editor). Open it from **Preferences → Plugins → Shitlist → Settings**, or type `/shitlist` in any chat.

3. **Temporary ignore** — Right-click a user and hover **Ignore for…** to choose **20 min / 1 hr / 12 hr / 1 day / 3 days / 7 days**. The user is ignored and automatically un-ignored when the time expires.

## Install

1. Copy the whole `shitlist` folder into your plugins directory:
   - Windows: `%AppData%\Roaming\nicotine\plugins\` → `C:\Users\<you>\AppData\Roaming\nicotine\plugins\shitlist\`
   - Linux/macOS: `~/.local/share/nicotine/plugins/shitlist/`
2. Close and reopen the **Preferences** dialog if it is already open.
3. Enable **Shitlist** in **Preferences → Plugins** (no restart required).

The folder must contain `PLUGININFO` and `__init__.py`.

## Usage

### Keywords (the `/shitlist` command)

| Command | What it does |
|---|---|
| `/shitlist` | Opens the keyword settings dialog |
| `/shitlist list` | Lists current keywords in the chat |
| `/shitlist add <word>` | Adds a keyword |
| `/shitlist add "no thanks"` | Adds a multi-word phrase (must be quoted) |
| `/shitlist remove <word>` | Removes a keyword |

**The quoting rule:** one word is expected per entry. If you need a multi-word
phrase, wrap it in double quotes — e.g. `"no thanks"`. The settings dialog
shows this hint next to the keyword field, and the `/shitlist add` command
enforces it.

### Temporary ignore

Right-click a user (in the user list, chat room, private chat, search results,
browse, etc.) → **Ignore for…** → pick a duration. The user is ignored
immediately and un-ignored automatically after that time.

- If the user was *already* permanently ignored, the temporary ignore keeps
  them ignored and does **not** auto-remove them.
- Selecting a new duration for an already temporarily-ignored user restarts the
  timer.

## Matching behaviour

- Keywords are matched as **case-insensitive substrings**, exactly like the
  censor feature. A keyword `foo` matches any message containing `foo`
  (including `food`, `fool`, etc.). Use a more specific word or a quoted phrase
  to narrow matches.
- Your own messages are ignored (you won't ban yourself).

## How it works (technical)

- **Plugin API**: subclass of `pynicotine.pluginsystem.BasePlugin`.
- **Chat hooks**: `incoming_public_chat_notification(room, user, line)` and
  `incoming_private_chat_notification(user, line)`.
- **Ban/ignore**: `core.network_filter.ban_user()`, `.ignore_user()`,
  `.unignore_user()`.
- **Auto-unignore**: `events.schedule(seconds, callback, (username,))`.
- **Settings UI**: `metasettings` with `"type": "list string"` (the same list
  editor the censor feature uses).
- **Context menu**: Nicotine+ 3.3.x does not expose a plugin hook for the user
  right-click menu, so the plugin monkey-patches `UserPopupMenu.setup_user_menu`
  to append the "Ignore for…" submenu. This patch is removed when the plugin is
  disabled. It is verified against Nicotine+ **3.3.10**; a future Nicotine+
  release that changes `UserPopupMenu` may require a small update.

## Notes / limitations

- The "Ignore for…" context menu entry relies on internal GUI classes
  (`pynicotine.gtkgui.widgets.popupmenu`). It works in the graphical client
  (Windows/macOS GTK4 and Linux GTK3/GTK4), but not in headless mode.
- In headless mode, `/shitlist` falls back to listing keywords instead of
  opening a window.
- Bans are permanent (Nicotine+'s normal banlist). Use the built-in
  **Banned Users** settings page or `/unban <user>` to remove them.
