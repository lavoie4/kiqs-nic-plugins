# Page Doll

A decorative "page doll" for the Nicotine+ Private Chat pane — a transparent
PNG or animated GIF character that sits in a corner of the pane.

## Features

- **Transparent PNG or animated GIF** page doll in the Private Chat pane.
- **Exact sizing** — you set the doll's width and height in pixels. There is no
  practical size cap (anything from 1 px up to the pane size works).
- **Position** — bottom-right (default), bottom-left, top-right, top-left, or center.
- **Live apply** — changes take effect immediately.
- **Always visible** — the doll is layered *above* the private-chat notebook. It
  carries no event controllers, so clicks pass straight through to the chat
  underneath.

## Commands

- `/pagedoll` or `/pd` — open the settings window.
- `/pagedoll on` / `off` — enable/disable.
- `/pagedoll refresh` — re-apply.

## Settings

- **Enabled** — toggle the doll.
- **Image** — `.png` or `.gif` (animated GIF supported).
- **Width / Height** — doll size in pixels (no meaningful upper limit).
- **Position** — which corner/edge of the pane the doll hugs.

## Notes

- **GTK 4 only** — animated GIF and overlay layering require GTK 4. On GTK 3 the
  plugin logs a notice and does nothing (no crash).
- The doll is placed inside the `private_content` container (the Private Chat
  tab), so it appears only when the Private Chat pane is shown.
- To see why a doll is not appearing, enable Nicotine+'s debug log; the plugin
  logs each state (image missing, wrong extension, container not found, etc.).
