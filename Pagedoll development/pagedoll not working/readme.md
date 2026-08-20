# Page Doll

A decorative "page doll" — a transparent PNG character that sits in a corner
of a Nicotine+ pane, Tumblr-style.

## Panes

- **Private Chat** — the doll floats *on top* of the chat notebook, corner
  aligned. It carries no event controllers, so clicks pass through to the chat.
- **Downloads** — the doll is layered *behind* the downloads list, using the
  same `Gtk.Overlay` + transparent-CSS technique as the `theme_customizer`
  background image (the list text stays readable on top of the doll).

## Features

- **PNG page doll** (transparent PNG supported; PNG only — no GIF).
- **Exact sizing** — set width and height in pixels (1 px up to 4000 px).
- **Position** — bottom-right (default), bottom-left, top-right, top-left, or center.
- **Live apply** — every change applies immediately, no Apply button.
- **Independent settings per pane** — each pane has its own enabled / image /
  size / position fields.

## Commands

- `/pagedoll` or `/pd` — open the settings window.
- `/pagedoll settings` — same as above.
- `/pagedoll on` / `off` — enable/disable the Private Chat doll.
- `/pagedoll downloads on` / `off` — enable/disable the Downloads doll.
- `/pagedoll refresh` — re-apply immediately.

## Settings

Per pane (Private Chat, Downloads):

- **Enabled** — toggle the doll.
- **Image** — a `.png` file.
- **Width / Height** — doll size in pixels.
- **Position** — which corner/edge of the pane the doll hugs.

## Notes

- **GTK 4 only** — overlay layering requires GTK 4. On GTK 3 the plugin logs a
  notice and does nothing (no crash).
- The doll is placed inside the `private_content` container (Private Chat tab)
  and the downloads `tree_container` (Downloads tab), so it appears only when
  the relevant pane is shown.
- To see why a doll is not appearing, enable Nicotine+'s debug log; the plugin
  logs each state (image missing, wrong extension, container not found, etc.).
