#### Nicotine+ Theme Customizer
## written by kiquja ### 

A Nicotine+ plugin that adds a settings menu to customize the app theme: a
custom **background** (image or animated GIF — auto-detected — or a solid
color) with **fit / fill / tile** placement, an optional **background effect**
(grayscale, sepia, saturate, hue-rotate, invert) with adjustable strength,
**readability tint** and an **image overlay**
(two independent layers), a **title bar** image/tint (or a fully transparent
title bar), **text outline**, **find-term highlighting**, **find-bar theming**,
full **chat font / username color** mirroring, **named presets** (with JSON
export/import), **color grabbing**, a configurable **accent color**, and
**live-apply** settings.

> **Buddy-list / room-user-list controls live in a separate plugin** — see
> "Buddy List / User List Editor" (`/buddylist`). They were split out so this
> plugin can theme colors/backgrounds without fighting the editor over panel
> geometry.

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
   type `/ts` (or `/theme settings`) for a single scrollable settings window —
   big section titles (Background / Overlay / Title bar / Accent / Chat /
   Highlight / Layout / Presets) with color pickers, sliders and file pickers,
   and a **Close** button (changes apply immediately).

## Settings

### Background
- **Enable custom background** — on/off switch.
- **Background image / GIF** — file picker (PNG, JPG, GIF, BMP, SVG, WebP, TIFF…).
  The type is detected automatically: a `.gif` is animated (GTK 4), any other
  image is static. There is no separate "type" dropdown, so there's nothing to
  mis-set.
- **GIF auto-downscale** — animated GIFs larger than 640px (long side) are
  scaled down and capped to ~25 FPS automatically, so an oversized GIF can't
  freeze chat auto-scroll or make the UI sluggish.
- **Background color (solid)** — hex color (`#RRGGBB`) used when the image path
  above is cleared.
- **Background mode** — `fit` (scale to fit, letterboxed) / `fill` (scale to
  cover, may crop) / `tile` (repeat at natural size). Image only; for GIF the
  plugin maps `fit`→contain and `fill`/`tile`→cover.
- **GIF loop style** — `forward` (normal loop) or `pingpong` (plays forward then
  reverses, bouncing back and forth without repeating the endpoints). GIF only.
  Ping-pong holds every frame in memory, so very long GIFs use more RAM.
- **Background effect** — `none`, `grayscale`, `sepia`, `saturate`,
  `hue-rotate` or `invert`. These apply to the whole window, not just the
  background image.
- **Effect strength** — `0` to `100%`, the intensity of the selected effect
  (e.g. `50%` saturation = `+50` saturation).

### Overlay (two independent layers)
- **Under-text readability tint** — a tint (**Overlay color** + **Overlay
  opacity**, `0`–`1`) drawn over content surfaces (chat, user list, log) so text
  stays readable over a busy background. Start around `0.45`.
- **Overlay image** — a picture drawn over the background (behind content), with
  its own **Overlay image opacity** (`0`–`1`).
- **Corner radius** — rounds the tinted overlay surfaces (max `24` px).

### Title bar
- **Title bar image** — an image drawn behind the window title bar (GTK 4).
  With an image set, the title bar can't be transparent or translucent — the
  image fills the bar.
- **Title bar opacity** — `0` to `1`, the tint drawn over the title bar (GTK 4).
- **Completely transparent title bar** — removes the title bar tint and image
  entirely (GTK 4).
- **Use solid title bar color** + **Title bar color** — give the title bar a
  fixed color instead of a transparent blend.
- **Grab title bar color from background image** — samples the background image
  and sets the title bar color to its dominant color.

### Accent
- **Accent color** — hex color (`#RRGGBB`) used for selections, switches, links
  and highlighted buttons. Defaults to `#5B3368`. A contrasting foreground
  (black/white) is chosen automatically.
- **Grab colors from background image** — reads the background image and fills
  in a suggested accent color (most-saturated pixel) and background color
  (average pixel).

### Chat
- **Text outline** *(experimental)* — a subtle outline around all program text
  (color + thickness `1`–`3` px) for readability over busy backgrounds. Note
  that this adds some visual lag, since every text element is re-rendered with
  a shadow on each change.
- **Fonts** — `Global`, `List`, `Text view`, `Chat`, `Search`, `Transfers` and
  `Browse` fonts (mirrors Nicotine+'s interface fonts). Leave empty for the
  theme default.
- **Interface colors** — `Local`/`Remote`/`Command`/`Action`/`Highlight`
  username colors, `URL link`, `Text entry background`, `Text entry text`,
  `List text`, `Online`/`Away`/`Offline` status, and
  `Regular`/`Highlighted`/`Changed` tab label colors. Leave empty for the theme
  default. Colors apply immediately.
- **Grab color from background image** — samples the background image and shows
  its dominant color in a read-only field next to the button, so you can copy it
  into a username/interface color above.

### Highlight (find)
- **Find bar color** — background color of the search bar that slides down on
  Ctrl+F, so it matches the theme.
- **Enable find highlighting** — on/off.
- **Highlight style** — `solid` (one color), `rainbow` (full hue wheel) or
  `gradient` (blends two colors).
- **Find highlight color** — the base/start color.
- **Find gradient end color** — the second color for the `gradient` style.
- **Highlight all matches** — highlight every match, not just the current one.
- Note: the Background effects (grayscale, sepia, hue-rotate, etc.) also affect
  the highlight color, since they filter the whole window.

### Presets
- Save the current theme under a name; load or remove saved presets.
- **Export selected / Import** — save a preset (or the current settings) to a
  shareable `.json` file and load one back.
- Loading a preset keeps the settings window's size and scroll position.

Changes apply immediately as you make them — there is no Apply button, just a
**Close** button. The plugin also watches the settings and reapplies within a
second, so edits made through Nicotine+'s own Preferences are picked up too.
There is also a chat/CLI command:

```
/ts              # open the settings window (short alias)
/theme settings  # open the settings window
/theme on        # enable
/theme off       # disable
/theme refresh   # re-apply immediately
/theme unload    # fully unload the theme (keep the plugin active)
```

## How it works

- The plugin defines a `metasettings` block, which Nicotine+ turns into a
  standard plugin **Settings** dialog (switch / dropdown / text entry). A
  custom **settings window** is also available via `/ts`: a single scrollable
  column with big section titles, built with `Gtk.ColorButton`, `Gtk.Scale`,
  `Gtk.DropDown`, `Gtk.SpinButton`, `Gtk.Entry` and `Gtk.FileChooserNative` —
  the same widgets Nicotine+'s own **User Interface** preferences use. Each
  color picker is paired with a **hex-code text field** (type `#RRGGBB` and
  press Enter, or tab away, to apply); the background and overlay images have a
  **path entry** plus a **Browse…** button; and opacity sliders are paired with
  a **spin box** for typed values. Changes are committed immediately as you edit
  them.
- **Image / solid color** are applied with a `Gtk.CssProvider`
  (`background-image: url("file://…")` / `background-color`), so they work on
  both GTK 3 and GTK 4.
- **Animated GIF** is drawn by a `Gtk.Picture` background layer inserted behind
  the main window content, animated via `GdkPixbuf.PixbufAnimation`. Frames
  bigger than 640px are scaled down and cached, and the frame rate is capped at
  ~25 FPS, so large GIFs don't stall the UI. This path is GTK 4 only; on GTK 3 a
  GIF is shown as a static background.
- Structural containers (boxes, panes, notebooks, scrolled windows, header bar,
  etc.) are made transparent so the background shows through. Content surfaces
  (file lists, chat, log, text inputs) get the **readability tint** at the
  chosen opacity, so the image/GIF shows through them while text stays readable.
- The window **title bar** (GTK 4 header bar) is themed separately: it is made
  semi-transparent so the window background shows through, and tinted with the
  **title bar opacity** value. It can also show its own **title bar image** or a
  **solid color**.
- The **background effect** (grayscale, sepia, saturate, hue-rotate, invert)
  uses CSS `filter` on the background layer. The **overlay image** and
  **title bar image** are applied with CSS `background-image` (cover, centered).
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
- **Add a background effect** — add it to the effect `options` list in
  `_build_background_page()` and handle it in `_background_filter_css()`.
- **Add an overlay target** — add the GTK type name to `_surface_types()`
  (content surfaces get the overlay tint) or `_container_types()` (made
  transparent).
- **Change the plugin name / author / description** — edit `PLUGININFO`.

## Notes / limitations

- Nicotine+ ships GTK 4 on **Windows and macOS**; on **Linux** whether you get
  GTK 3 or GTK 4 depends on the distro/package (many distros still package the
  GTK 3 build). Check **Help → About** for the toolkit version. Image/color
  backgrounds and the overlay work on both; animated GIF, the title bar
  image, and the custom settings window need GTK 4.
- The overlay tint is applied once per content surface; intermediate containers
  are fully transparent so the tint doesn't stack and get too dark.
- On GTK 3, semi-transparent tree views can have minor repaint quirks; GTK 4
  (Windows/macOS default) is recommended.
- The title bar is only themeable on GTK 4 (it uses client-side decorations).
  On GTK 3 the window title bar is drawn by the OS/window manager and can't be
  styled by the plugin.
- GIF animation only works on GTK 4. The `pingpong` loop style holds every
  frame in memory (up to 200 frames), so very long GIFs use more RAM.
- All **background effects** (`grayscale`, `sepia`, `saturate`, `hue-rotate`,
  `invert`) are scaled by the **effect strength**. Animated GIF backgrounds are
  rendered as a widget layer, so the other effects may not apply to them on
  every GTK build.
- An **overlay image** is drawn with its own opacity; a GIF used as an overlay
  renders as a static picture.
- The **text outline** is experimental: it applies an outline to all program
  text and may look heavy on some themes, and it adds some visual lag.
- If the configured image is deleted, the plugin logs a warning and leaves the
  previous state until a valid image is chosen.
- **Fonts and interface colors** mirror Nicotine+'s shared UI settings (they are
  written to Nicotine+'s own config) and apply immediately via CSS.
- In headless (no-GUI) mode the plugin no-ops gracefully.
