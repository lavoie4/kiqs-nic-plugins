#### Nicotine+ Theme Customizer
## written by kiquja ### 

A Nicotine+ plugin that adds a settings menu to customize the app theme: a
custom **background** (image, animated GIF, WebM video or solid color) with
**fit / fill / tile** placement, an optional **background effect** (blur,
grayscale, sepia, saturate, hue-rotate, invert), a colored or **image overlay**
with adjustable opacity, a **title bar** image, a resizable/hideable
**buddy-list sidebar** and **room user list** (width, drag-resize and full
hide), named **theme presets**,
**color grabbing** from the background image, a configurable **accent
color**, **chat font / username color** mirroring, and **live-apply** settings.

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
   a slider for the overlay opacity).## Settings

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
  `hue-rotate` or `invert`. Applied to the background image.
- **Effect strength** — `0` to `100%`, the intensity of the selected effect
  (e.g. `50%` saturation = `+50` saturation; `100%` blur = `50px` blur).
- **Overlay type** — `color` (a tint) or `image` (a picture drawn over the
  background behind content).
- **Overlay image** — file used when **Overlay type** is `image`.
- **Overlay color** — hex color (`#RRGGBB`) of the tint drawn over the
  background behind content.
- **Overlay opacity** — `0` (background fully visible) to `1` (solid overlay,
  background hidden). A single global tint: it dims both the content surfaces
  (chat, user list, log) and the background image. Start around `0.45` for a
  readable dimmed look.
- **Header bar opacity** — `0` to `1`, the tint drawn over the window title bar
  (GTK 4). Start around `0.6` so the search box and buttons stay readable.
- **Title bar image** — an image drawn behind the window title bar (GTK 4).
- **Completely transparent title bar** — removes the title bar tint and image
  entirely (GTK 4).
- **Buddy list width (px)** — `50` to `1200`, moves Nicotine+'s native
  buddy-list divider (the "sliding buddy frame"). You can still drag it yourself.
- **Hide buddy-list sidebar** — completely hides the buddy list.
- **Room user list width (px)** — `120` to `400`, the width of the user list
  shown next to each chat room.
- **Drag-resizable user list (experimental)** — turns the room user list into a
  draggable pane (like the buddy list). Turning it off needs a Nicotine+ restart
  to revert.
- **Hide user list in chat rooms** — completely hides the room user list.
- **Accent color** — hex color (`#RRGGBB`) used for selections, switches, links
  and highlighted buttons. Defaults to `#5B3368`. A contrasting foreground
  (black/white) is chosen automatically.
- **Fonts** — `Global`, `List`, `Text view`, `Chat`, `Search`, `Transfers` and
  `Browse` fonts (mirrors Nicotine+'s interface fonts). Leave empty for the theme
  default.
- **Interface colors** — `Local`/`Remote`/`Command`/`Action`/`Highlight`
  username colors, `URL link`, `Text entry background`, `Text entry text`,
  `List text`, `Online`/`Away`/`Offline` status, and
  `Regular`/`Highlighted`/`Changed` tab label colors. Leave empty for the theme
  default.
- **Grab colors from background image** — reads the background image and fills in
  a suggested **accent color** (most-saturated pixel) and **background color**
  (average pixel).
- **Presets** — save the current theme under a name. All saved presets are shown
  in a list on the Presets page: select one and press **Load** to apply it, or
  **Remove** to delete it. Presets are stored with the plugin's own settings.

Changes apply immediately as you make them — there is no Apply button, just a
**Close** button. The plugin also watches the settings and reapplies within a
second, so edits made through Nicotine+'s own Preferences are picked up too.
There is also a chat/CLI command:

```
/theme            # open the settings window (color pickers + sliders)
/theme settings   # same as above
/theme on         # enable
/theme off        # disable
/theme refresh    # re-apply immediately
/theme unload     # fully unload the theme (keep the plugin active)
/userlist               # open the settings window (Layout page)
/userlist hide-buddy    # hide the buddy-list sidebar
/userlist show-buddy    # show the buddy-list sidebar
/userlist hide-users    # hide the room user list
/userlist show-users    # show the room user list
/cul                    # short alias for /userlist
```

## How it works

- The plugin defines a `metasettings` block, which Nicotine+ turns into a
  standard plugin **Settings** dialog (switch / dropdown / text entry).
  A Nicotine+-style **settings window** is also available via `/theme settings`:
  a left `Gtk.StackSidebar` tree (Background / Overlay / Title bar / Accent /
  Layout / Presets / Chat) with a right `Gtk.Stack` panel and a **Close** button
  (changes apply immediately), built with
  `Gtk.ColorButton`, `Gtk.Scale`, `Gtk.DropDown` and `Gtk.FileChooserNative` —
  the same widgets Nicotine+'s own **User Interface** preferences use. Each
  color picker is paired with a **hex-code text field** (type `#RRGGBB` and press
  Enter, or tab away, to apply); the background has a **path entry** plus a
  **Browse…** button; and each opacity slider is paired with a **spin box** for
  typed numeric values. Changes are committed immediately as you edit them.
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
- The **background effect** is applied on the background layer: **blur** uses
  `Gtk.Snapshot.push_blur()` on the background picture (GTK 4), so it blurs only
  the background image and never the UI on top; the other effects (grayscale,
  sepia, saturate, hue-rotate, invert) use CSS `filter` on the background layer.
  The **overlay image** and **title bar image** are applied with CSS
  `background-image` (cover, centered).
- Newly created widgets (a profile's **bio** text, newly opened rooms) are kept
  tagged by a lightweight re-scan every second, so the overlay and background
  stay consistent as pages open and close.
- The **buddy-list sidebar** and **room user list** are resized/hidden with
  plain GTK property calls only (no reparenting): the buddy list by moving
  Nicotine+'s own horizontal `Gtk.Paned` divider (`set_position`), and the room
  user list by `set_width_request()` + `set_visible()`. A 1-second poll keeps
  new rooms and the divider in sync without fighting manual dragging.
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

- Nicotine+ ships GTK 4 on **Windows and macOS**; on **Linux** whether you get
  GTK 3 or GTK 4 depends on the distro/package (many distros still package the
  GTK 3 build). Check **Help → About** for the toolkit version. Image/color
  backgrounds and the overlay work on both; animated GIF/WebM, the title bar
  image, and the custom settings window need GTK 4.
- The overlay tint is applied once per content surface; intermediate containers
  are fully transparent so the tint doesn't stack and get too dark.
- On GTK 3, semi-transparent tree views can have minor repaint quirks; GTK 4
  (Windows/macOS default) is recommended.
- The title bar is only themeable on GTK 4 (it uses client-side decorations).
  On GTK 3 the window title bar is drawn by the OS/window manager and can't be
  styled by the plugin.
- GIF/WebM animation only works on GTK 4. WebM additionally requires GStreamer
  (bundled with Nicotine+ on Windows and most Linux GTK builds).
- All **background effects** (`blur`, `grayscale`, `sepia`, `saturate`,
  `hue-rotate`, `invert`) apply to the background layer and are scaled by the
  **effect strength**. **Blur** is rendered via `Gtk.Snapshot.push_blur()` so it
  is confined to the background image (GTK 4 only; on GTK 3 blur is a no-op).
  Animated GIF/WebM backgrounds are rendered as a widget layer, so the other
  effects may not apply to them on every GTK build.
- An **overlay image** is drawn at full opacity (cover); it is not tinted by the
  overlay opacity. A GIF used as an overlay renders as a static picture.
- The **drag-resizable user list** is experimental: it reparents the per-room
  widget tree into a `Gtk.Paned` at runtime. The initial width is best-effort for
  room tabs that aren't currently visible; drag the handle to fine-tune.
- If the configured image is deleted, the plugin logs a warning and leaves the
  previous state until a valid image is chosen.
- **Fonts and interface colors** mirror Nicotine+'s shared UI settings (they are
  written to Nicotine+'s own config). Fonts apply immediately via CSS; color
  changes apply to new content immediately and to existing content after the
  theme is reloaded or Nicotine+ restarts.
- In headless (no-GUI) mode the plugin no-ops gracefully.
