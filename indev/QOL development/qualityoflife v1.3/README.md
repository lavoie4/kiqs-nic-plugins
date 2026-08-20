# Nicotine+ Quality of Life Plugin

**Author:** kiquja

> Formerly the Keybinds plugin — now combines keybinds with the `/rpl` plugin
> refresh/list command.

Adds configurable keyboard shortcuts ("keybinds") to Nicotine+. It can open
every main tab, cycle through tabs and private messages, open Settings, and
refresh plugins — with live conflict detection against Nicotine+'s built-in
shortcuts and common Windows-reserved shortcuts.

It also includes a **`/rpl`** command (alias `/refreshplugins`) to refresh and
list installed plugins — merged from the former "Refresh Plugins List" plugin.

Built against the **Nicotine+ 3.4.0 (dev)** plugin API
(`BasePlugin`, `self.core`, `self.config`, `self.settings`, `self.metasettings`,
Gio/Gtk accelerators). Verified against the API reference at
<https://nicotine-plus-nicotine-plus.mintlify.app/development/plugins/api-reference>.

## Install

Two ways (both work):

**A. Copy the folder (fastest for testing)**

1. Copy the whole `keybinds` folder (containing `PLUGININFO` and `__init__.py`) into:
   - Windows: `%AppData%\Roaming\nicotine\plugins\`
   - Linux/macOS: `~/.local/share/nicotine/plugins/`
2. Close and reopen **Preferences → Plugins** if it is open.
3. Tick **Keybinds** in the plugin list to enable it.

**B. Install from a ZIP**

1. Zip the `keybinds` folder (so the ZIP contains `keybinds/PLUGININFO` and `keybinds/__init__.py`).
2. **Preferences → Plugins → Install…** and select the ZIP.

## Default keybinds

| Action | Default |
|---|---|
| Open Chat Rooms tab | `Win+Shift+C` |
| Open Private Chat | `Win+Shift+P` |
| Open Search Files | `Win+Shift+F` |
| Open Downloads tab | `Win+Shift+D` |
| Open Uploads tab | `Win+Shift+U` |
| Browse Shares | `Win+Shift+B` |
| User Profiles | `Win+Shift+I` |
| Interests | `Win+Shift+T` |
| Open Settings | `Win+Shift+,` |
| Cycle tabs forward | `Ctrl+Alt+Right` |
| Cycle tabs reverse | `Ctrl+Alt+Left` |
| Cycle private messages forward | `Ctrl+Alt+Down` |
| Cycle private messages reverse | `Ctrl+Alt+Up` |
| Refresh plugins | `Win+Shift+R` |
| Keybind settings (this window) | `Win+Shift+K` |

> Modifier notation: `<Super>` = Windows key (or Cmd on macOS), `<Primary>` =
> Ctrl on Windows/Linux (Cmd on macOS), `<Control>` = Ctrl, `<Alt>` = Alt,
> `<Shift>` = Shift.

## Configure keybinds

- Press the **Keybind settings** shortcut (`Win+Shift+K`), or type `/keybinds`
  in any chat box, to open the keybind window.
- Click a keybinding, then press the new chord (e.g. `Win+Shift+T`). Press
  **Esc** to cancel. Use **Clear** to remove a keybind, **Reset defaults** to
  restore everything.
- Conflicts appear in red next to the action, naming the conflicting shortcut
  (Nicotine+ built-in action, another keybind, or a Windows reserved combo).

## Commands

- `/keybinds` — open the keybind configuration window.
- `/rpl` (or `/refreshplugins`) — re-scan, reload updated plugins, and list all
  installed plugins with their loaded/failed/disabled status.

## How it works

- Keybinds are captured with a manual `Gtk.EventControllerKey` (GTK4) or the
  window's `key-press-event` (GTK3) on the main window, then matched against the
  configured chords with `Gtk.accelerator_name()`. Because the key is checked
  *before* it reaches the focused widget, keybinds **do not fire while you are
  typing in a text field** (chat entry, search box, etc.).
- Tabs are switched by locating the main `Gtk.Notebook` and its pages (each page
  carries an `.id` like `"search"`, `"downloads"`, …). The tab cycler walks the
  notebook's **visible** pages, so tabs added by other plugins (for example the
  "Played" tab from "Chat watcher v1") are cycled through automatically. A small
  patch to `MainWindow.set_active_header_bar` makes switching to a plugin tab
  safe (Nicotine+ would otherwise raise `KeyError` because plugin tabs aren't in
  its `window.tabs` mapping). Private-message cycling uses the secondary
  notebook nested in the Private Chat tab.
- Keybinds persist to Nicotine+'s plugin config
  (`config.sections["plugins"]["keybinds"]`).

## Notes / limitations

- **Two places to edit:** keybinds also appear as text fields in
  **Preferences → Plugins → Keybinds → Settings**. Edits there take effect after
  disabling/re-enabling the plugin; edits in the keybind window apply instantly.
- **Chords = modifier combos.** GTK accelerators support combined modifiers
  (Ctrl+Shift+Alt+Win+key). True multi-key *sequences* (press A then B) are not
  supported by GTK accelerators.
- **Conflicts are warnings, not blocks.** If you bind a shortcut Nicotine+
  already uses (for example `Ctrl+L`, which Nicotine+ uses for "focus top bar"),
  the window flags it but still allows it. Your keybind takes priority (it is
  consumed before Nicotine+'s accelerators run), so pick a free chord if you
  still want the built-in shortcut to work.
- **No keybinds while typing.** Keybinds are ignored whenever an editable text
  widget (entry or editable text view) has keyboard focus, so they never
  interfere with normal typing.
- **Windows reserved list is a heuristic** — Windows version, OEM tools, and
  PowerToys can add or remap shortcuts. It is not an exhaustive guarantee.
- **Refresh plugins** reloads currently installed plugins (other than itself).
  The Preferences plugin *list* may still need a close/reopen to show
  newly-added plugin folders, since Nicotine+ builds that list once.
- Built against Nicotine+ `master` (3.4.0.dev1). Older releases may not have
  `Gio.Application.get_default()`-based GUI access patterns; the plugin degrades
  gracefully (logs a warning) if no GUI is present.

## Extending

- Add new actions in `ACTIONS` + a default in `DEFAULT_ACCELS` in `__init__.py`,
  then implement a handler (or add a `TAB_ACTIONS` mapping) in `Plugin._run_action`.
- Add more Windows-reserved or app shortcuts to `WINDOWS_RESERVED` /
  `WIN_ACTION_NAMES`.
