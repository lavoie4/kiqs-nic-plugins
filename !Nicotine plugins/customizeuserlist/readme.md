# Customize User List

A Nicotine+ plugin that resizes and hides the two side lists:

- **Buddy list** (the "sliding buddy frame") — controlled by moving Nicotine+'s
  **existing** horizontal `Gtk.Paned` divider. No widgets are created, wrapped,
  reparented or replaced.
- **Room user list** (the per-room *member* list, `users_container`) — controlled
  with the plain `set_width_request()` property and `set_visible()`. This list has
  no native divider, so a property change is the clean way to control it (no
  reparenting).

Works on GTK 3 and GTK 4.

---

## What this hooks

### Buddy list (native `Gtk.Paned` handle)

Loaded from `pynicotine/gtkgui/ui/mainwindow.ui`:

| Widget (`id`) | Class | Orientation | Children (start → end) |
|---|---|---|---|
| `horizontal_paned` | `Gtk.Paned` | horizontal | `vertical_paned` → `buddy_list_container` |
| `chatrooms_paned` | `Gtk.Paned` | horizontal | `chatrooms_container` → `chatrooms_buddy_list_container` |

- `MainWindow` (`gtkgui/mainwindow.py`, ~lines 192–226) configures the
  resize/shrink flags.
- Nicotine+ moves the single buddy-list widget between these two containers (and
  the "Buddies" tab) via `Buddies.set_buddy_list_position()`
  (`gtkgui/buddies.py`, ~lines 205–260), keyed on
  `config.sections["ui"]["buddylistinchatrooms"]` ∈ `"always"` / `"chatrooms"` / `"tab"`.

The plugin resizes the buddy list by `paned.set_position(total − width)` and
hides/shows it via the end container's `set_visible`.

### Room user list (`users_container`, no paned)

Loaded from `pynicotine/gtkgui/ui/chatrooms.ui`: `users_container` is a `GtkBox`
with `width-request=180`, `hexpand=False`, beside the vertical `chat_paned`
(activity log ↔ chat). It has **no** divider, so the plugin sets its width with
`set_width_request(width)` and hides it with `set_visible(False)`. This never
wraps or reparents the widget.

---

## Usage

- **Settings window:** run `/userlist` (or `/cul`) in any chat, or open
  *Edit → Plugins → Customize User List → Settings*.
- **Quick toggles:**
  - `/userlist hide-buddy` / `show-buddy`
  - `/userlist hide-users` / `show-users`
- **Settings:**
  - *Enable user-list customization* — master switch.
  - *Buddy list width (px)* — moves the native divider.
  - *Hide the buddy-list sidebar*.
  - *Room user list width (px)* — sets `set_width_request()` on the member list.
  - *Hide the room user list*.
- Changes apply immediately. The buddy list's drag handle keeps working — the
  plugin sets its width once and does not fight the drag afterwards.

> Note: which pane shows the buddy list is controlled by Nicotine+'s own
> "Buddy list position" preference (`buddylistinchatrooms`). In `"tab"` mode
> there is no buddy-list sidebar pane, so the buddy-list settings are a no-op;
> the room user list is unaffected.

---

## How it works (no reparenting)

1. Finds the main window via `Gtk.Window.list_toplevels()`.
2. Walks the widget tree.
3. **Buddy list:** collects horizontal `Gtk.Paned` widgets and keeps only the ones
   whose end child is a native buddy-list container (`buddy_list_container` /
   `chatrooms_buddy_list_container`, matched by Gtk.Builder id). Width =
   `paned.set_position(get_allocated_width() − width)`; hide = end-child
   `set_visible`.
4. **Room user list:** collects every `users_container` (by Gtk.Builder id) and
   applies `set_width_request(width)` + `set_visible` for hide. New rooms are
   picked up by a 1-second poll.

---

## Notes / limitations

- **GTK 4** is the only runtime on Windows/macOS Nicotine+ builds; the GTK 3 code
  path (same native calls, `get_children`/`get_child2`/`pack_start`) is present but
  not runtime-verified here.
- Built against Nicotine+ **3.3.10** widget ids and structure.
- **Running alongside `theme_customizer`: safe.** This plugin only touches the two
  native buddy-list containers and the member list via `set_width_request`, so it
  ignores the synthetic member-list pane that `theme_customizer`'s
  "Drag-resizable user list" option creates. If you use this plugin for the room
  user list, turn `theme_customizer`'s "Drag-resizable user list" off to avoid two
  sources of truth for the member list width.
- Disabling or unloading the plugin restores any list it had hidden.
