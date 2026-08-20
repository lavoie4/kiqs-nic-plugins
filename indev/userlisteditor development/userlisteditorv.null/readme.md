# Buddy List / User List Editor

A standalone plugin that owns the buddy-list sidebar and the room user list
(member list): width sliders, hide toggles, and a drag-resizable room user list.

This supersedes the earlier `userlist_nuclearmode` and `userlist_nuclearmode2`
experimental builds.

## What it does

- **Buddy list** — width slider (moves Nicotine+'s native divider) + hide toggle.
- **Room user list** — width slider + drag-resizable + hide toggle.

The room user list doesn't sit in a native paned (it's a fixed-width box next to
the vertical chat paned), so this plugin rips it out and rebuilds the row as a
horizontal `Gtk.Paned` (chat = start, user list = end). The native divider then
gives drag-resize for free, exactly like the buddy list.

## Running alongside Theme Customizer

This plugin is built to coexist with Theme Customizer:

- It finds widgets by Gtk.Builder id from the full window tree every time, so it
  works no matter how Theme Customizer re-wraps the window in its background
  overlay.
- Every operation is idempotent and re-applied on a short (750 ms) poll, so if
  Theme Customizer rebuilds its overlay, this plugin re-finds and re-applies.

**Important:** leave Theme Customizer's own buddy-list / room-user-list options
OFF (Layout page) — this plugin is the single owner of those controls.

## Commands

- `/buddylist` or `/bul` — open settings, or:
  - `hide-buddy` / `show-buddy`
  - `hide-users` / `show-users`

## Settings

- Buddy list width (slider, 50–1200 px) + hide
- Room user list width (slider, 40–1600 px) + drag-resizable + hide

Open a chat room to see the room user list. Enable Nicotine+'s debug log to see
what the plugin finds and does.
