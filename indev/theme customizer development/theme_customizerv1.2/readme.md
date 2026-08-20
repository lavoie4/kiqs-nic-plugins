#### Nicotine+ Theme Customizer
## written by Ambrose "KIQUJA" LaVoie ### 

A Nicotine+ plugin that adds a settings menu to customize the app theme: a
custom **background** (image, animated GIF, WebM video or solid color) with
**fit / fill / tile** placement, an optional **background effect** (blur,
grayscale, sepia, saturate, hue-rotate, invert), a colored or **image overlay**
with adjustable opacity, a **title bar** image, an adjustable **room user list
width**, per-area overlay toggles, and a configurable **accent color**.

## Install

1. Copy the `theme_customizer` folder into Nicotine+'s user plugin directory:

   | Platform | Plugin directory |
   |---|---|
   | Linux | `~/.local/share/nicotine/plugins` |
   | Windows | `%APPDATA%\nicotine\plugins` |
   | macOS | `~/Library/Application Support/nicotine/plugins` |

2. Restart Nicotine+ (or toggle the plugin off/on).
3. Enable it: **Edit → Plugins** → tick **Theme Customizer**.
4. Open its settings: select **Theme Customizer** → click **Settings**, or
   type `/theme settings` in the chat/CLI for a Nicotine+-style settings
   window (left category tree + right settings panel, with color pickers and
   a slider for the overlay opacity).

## Settings

- **Enable custom background** — on/off switch.
- **Background type** — `image` (static picture), `color` (solid fill), `gif`
  (animated image; GTK 4) or `webm` (animated video; GTK 4 + GStreamer).
- **Background image** — file picker (PNG, JPG, GIF, BMP, SVG, WebP, WebM, MP4…).
  Used by the `image`, `gif` and `webm` types. `.gif` and `.webm`/`.mp4` files
  are auto-detected and animated (GTK 4) even if the type is still `image`.
- **Background color** — hex color (`#RRGGBB`) used by the `color` type.
- **Background mode** — `fit` (scale to fit, letterboxed) / `fill` (scale to
  cover, may crop) / `tile` (repeat at natural size). Image only; for GIF the
  plugin maps `fit`→contain and `fill`/`tile`→cover.
- **Background effect** — `none`, `blur`, `grayscale`, `sepia`, `saturate`,
  `hue-rotate` or `invert`, applied to the background via CSS `filter`.
- **Blur strength (px)** — `0` to `50`, the radius used by the `blur` effect.
- **Overlay type** — `color` (a tint) or `image` (a picture drawn over the
  background behind content).
- **Overlay image** — file used when **Overlay type** is `image`.
- **Overlay color** — hex color (`#RRGGBB`) of the tint drawn over the
  background behind content.
- **Overlay opacity** — `0` (background fully visible) to `1` (solid overlay,
  background hidden). Start around `0.45` for a readable dimmed look.
- **Header bar opacity** — `0` to `1`, the tint drawn over the window title bar
  (GTK 4). Start around `0.6` so the search box and buttons stay readable.
- **Title bar image** — an image drawn behind the window title bar (GTK 4).
- **Room user list width (px)** — `120` to `400`, the width of the user list
  shown next to each chat room.
- **Drag-resizable user list (experimental)** — turns the room user list into a
  draggable pane (like the buddy list). Turning it off needs a Nicotine+ restart
  to revert.
- **Tint buddy list / chat rooms / browse** — per-area switches that toggle the
  overlay tint on those surfaces.
- **Accent color** — hex color (`#RRGGBB`) used for selections, switches, links
  and highlighted buttons. Defaults to `#5B3368`. A contrasting foreground
  (black/white) is chosen automatically.

Changes are applied live (the plugin watches the settings and reapplies within a
second of clicking **Apply**). There is also a chat/CLI command:

```
/theme            # open the settings window (color pickers + slider)
/theme settings   # same as above
/theme on         # enable
/theme off        # disable
/theme refresh    # re-apply immediately
```

## How it works

- The plugin defines a `metasettings` block, which Nicotine+ turns into a
  standard plugin **Settings** dialog (switch / dropdown / text entry).
  A Nicotine+-style **settings window** is also available via `/theme settings`:
  a left `Gtk.StackSidebar` tree (Background / Overlay / Title bar / Accent /
  Layout) with a right `Gtk.Stack` panel and **Cancel / Apply / OK** buttons, built with
  `Gtk.ColorButton`, `Gtk.Scale`, `Gtk.DropDown` and `Gtk.FileChooserNative` —
  the same widgets Nicotine+'s own **User Interface** preferences use. Each
  color picker is paired with a **hex-code text field** (type `#RRGGBB` and press
  Enter, or tab away, to apply); the background has a **path entry** plus a
  **Browse…** button; and each opacity slider is paired with a **spin box** for
  typed numeric values. Apply/OK commit the changes; Cancel closes without
  saving.
- **Image / solid color** are applied with a `Gtk.CssProvider`
  (`background-image: url("file://…")` / `background-color`), so they work on
  both GTK 3 and GTK 4.
- **Animated GIF** is drawn by a `Gtk.Picture` background layer inserted behind
  the main window content, animated via `GdkPixbuf.PixbufAnimation`. This path
  is GTK 4 only; on GTK 3 a GIF is shown as a static background.
- **WebM / video** is played by a `Gtk.Video` + `Gtk.MediaFile` background layer
  (GStreamer). This path is GTK 4 only and requires GStreamer; if it is
  unavailable the plugin falls back to a static background.
- Structural containers (boxes, panes, notebooks, scrolled windows, header bar,
  etc.) are made transparent so the background shows through. Content surfaces
  (file lists, chat, log, text inputs) get the **overlay** color at the chosen
  opacity, so the image/GIF shows through them while text stays readable.
- The window **title bar** (GTK 4 header bar) is themed separately: it is made
  semi-transparent so the window background shows through, and tinted with the
  **header bar opacity** value (the same overlay color). It can also show its
  own **title bar image**.
- The **background effect** is applied with CSS `filter` on the background
  layer. The **overlay image** and **title bar image** are applied with CSS
  `background-image` (cover, centered).
- Newly created widgets (a profile's **bio** text, newly opened rooms) are kept
  tagged by a lightweight re-scan every second, so the overlay and background
  stay consistent as pages open and close.
- The **accent color** is applied by overriding GTK's named accent/selection
  colors (`@accent_color`, `@accent_bg_color`, `@theme_selected_bg_color`, and
  their foreground counterparts) via CSS, so it affects all standard GTK
  widgets without touching individual selectors.

## How to modify

- **Change defaults** — edit the `self.settings` dict in
  `theme_customizer/__init__.py` (e.g. `mode`, `overlay_opacity`, `color`).
- **Add a background type** — add it to the `background_type` `options` list and
  handle it in `_build_css()` / `_build_config()`.
- **Add an overlay target** — add the GTK type name to `_surface_types()`
  (content surfaces get the overlay tint) or `_container_types()` (made
  transparent).
- **Change the plugin name / author / description** — edit `PLUGININFO`.

## Notes / limitations

- The overlay tint is applied once per content surface; intermediate containers
  are fully transparent so the tint doesn't stack and get too dark.
- On GTK 3, semi-transparent tree views can have minor repaint quirks; GTK 4
  (Windows/macOS default) is recommended.
- The title bar is only themeable on GTK 4 (it uses client-side decorations).
  On GTK 3 the window title bar is drawn by the OS/window manager and can't be
  styled by the plugin.
- GIF/WebM animation only works on GTK 4. WebM additionally requires GStreamer
  (bundled with Nicotine+ on Windows and most Linux GTK builds).
- The **background effect** (`blur`, `grayscale`, …) applies to image and color
  backgrounds; animated GIF/WebM backgrounds are rendered as a widget layer and
  are not filtered.
- An **overlay image** is drawn at full opacity (cover); it is not tinted by the
  overlay opacity. A GIF used as an overlay renders as a static picture.
- The **drag-resizable user list** is experimental: it reparents the per-room
  widget tree into a `Gtk.Paned` at runtime. The initial width is best-effort for
  room tabs that aren't currently visible; drag the handle to fine-tune.
- If the configured image is deleted, the plugin logs a warning and leaves the
  previous state until a valid image is chosen.
- In headless (no-GUI) mode the plugin no-ops gracefully.
