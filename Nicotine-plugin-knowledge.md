# Nicotine+ Plugin Project — Knowledge & Lessons Learned

> A living reference for the Nicotine+ (Soulseek client) plugin work done with
> Ambrose. Covers the plugins themselves, how they work, the bugs we fought, and
> the Python / GTK / PyGObject / Nicotine+ / Soulseek facts we learned along the
> way. Written 2026-08-19.

---

## 1. What this project is

Ambrose builds and maintains a set of **Nicotine+ plugins** (Python, GTK). The
centerpiece is `theme_customizer`, a plugin that themes the Nicotine+ window:
custom backgrounds (image / animated GIF / solid color), overlay tints, title-bar
styling, chat color/font mirroring, find-term highlighting, presets, and more.

There is **no live Nicotine+ GUI available to me** during development. All
verification is done via `py_compile`, targeted `grep`/`Select-String` reads, and
reading Nicotine+'s installed source; Ambrose live-tests and reports back.

### Plugin inventory (in `!Nicotine plugins\`)

| Plugin | Purpose | Status |
|---|---|---|
| `theme_customizer` | Main theme engine (backgrounds, overlays, GIFs, chat mirroring, presets) | Active, v2.x |
| `pagedoll` | Tumblr-style transparent character image (PNG/GIF) in the Private Chat pane | GTK4 only, v0.1.x |
| `buddylist_userlist_editor` | Owns buddy-list + room user-list width/hide/drag | Standalone, coexists with theme_customizer |
| `customizeuserlist` | User-list mentions / coloring (historically merged `findhighlight`) | Active |
| `keybinds`, `chatwatcher` | Smaller utilities | Present |

Historical note: `findhighlight` and `customizeuserlist` were merged into one
plugin at some point. The old v1.9.2 build of theme_customizer (`theme2` /
"GIF LOOP" build) was preserved in `.trash\themeGIFLOOPver\` for A/B reference,
then functionally retired.

---

## 2. theme_customizer — feature reference (current state)

### Backgrounds
- **Background image / GIF** — file picker. Type is **auto-detected** from the
  extension (`.gif` → animated GIF, empty → solid color, else static image).
  There is no "type" dropdown anymore.
- **Background color (solid)** — used when the image path is cleared.
- **Background mode** — `fit` (contain/letterboxed), `fill` (cover/crop),
  `tile` (repeat). For GIF, `fit`→contain and `fill`/`tile`→cover.
- **Background effect** — `none`, `grayscale`, `sepia`, `saturate`,
  `hue-rotate`, `invert`. Applies to the **whole window**, not just the image.
  Scaled by **effect strength** (0–100%).
- **Blur** — rendered via `Gtk.Snapshot.push_blur()` on the background picture
  scope, **not** a CSS `filter: blur()`. (CSS blur would smear the whole window.)
- **GIF loop style** — `forward` (normal) or `pingpong` (forward then reverse).
- **GIF auto-downscale** — frames larger than 640px (long side) are scaled down
  and capped at ~25 FPS so oversized GIFs don't stall the UI.

### Overlay (two independent layers)
- **Under-text readability tint** — color + opacity (`overlay_color`,
  `overlay_opacity`) drawn over content surfaces so text stays readable.
- **Overlay image** — a picture drawn over the background (behind content), with
  its own opacity (`overlay_image_opacity`).
- **Corner radius** — rounds tinted surfaces (max 24px).
- *(Removed: "background image darkening" — a third tint that only darkened the
  image. It was stripped out entirely.)*

### Title bar (GTK4)
- Image, tint, solid color, or fully transparent blend.

### Text outline (experimental)
- Global text outline (color + thickness 1–3px). Known to add lag, especially
  with GIF backgrounds or thickness > 2px.

### Chat font / color mirroring
- Mirrors Nicotine+'s shared UI settings (fonts + username/highlight/URL/input
  colors). Writes to Nicotine+'s own config `ui` section. **Applies immediately**
  (no restart).

### Accent color
- Configurable accent (selections, switches, links, buttons).

### Find-term highlighting (merged from `findhighlight`)
- Highlight find terms (solid / rainbow / gradient styles), highlight-all,
  color/gradient controls, a live swatch, hue sweep.

### Find bar (Ctrl+F) theming
- `findbar_color` themes the `GtkSearchBar` strip behind the search entry.

### Presets
- Named presets stored in config; JSON export/import files.

### Grab-color helpers
- "Grab color from background image" (chat accent) and "Grab title bar color from
  background image" sample the background image and fill suggested colors.

### Live apply
- 300 ms debounced re-apply on every widget change.

### Commands
- `/theme` and `/ts` → open settings / apply / refresh / disable / presets.

---

## 3. Architecture & how theme_customizer works

### CSS provider approach
- The plugin builds a `Gtk.CssProvider` string (`_build_css`) and attaches it at
  `STYLE_PROVIDER_PRIORITY_USER` (800).
- **Nicotine+'s own theme uses `STYLE_PROVIDER_PRIORITY_APPLICATION` (600)**,
  so the plugin's CSS wins on specificity of priority.

### Widget tagging / transparency
- Containers (boxes, panes, notebooks, scrolled windows, header bars, action
  bars, window handles, etc.) are tagged with a `CSS_CLASS_TRANSPARENT` class
  (`background-color: transparent`) so the background picture shows through.
- Content surfaces (file lists, chat, log, text inputs) get the readability
  tint at the chosen opacity.
- A 1-second poll re-tags newly created widgets (opened profiles, new rooms).

### Background layers
- **Static image / color**: CSS `background-image` / `background-color` on the
  window/root, tagged via `_tag_background`.
- **Animated GIF**: a `Gtk.Picture` background layer is inserted **behind** the
  main content by wrapping: `window.set_child(overlay)`, then
  `overlay.add_overlay(root)` puts the real content on top. The root gets
  `CSS_CLASS_TRANSPARENT` so the picture shows through.
- **WebM/video** (dead code, removed from the UI): `Gtk.MediaFile` +
  `Gtk.Video`.

### GIF animation pipeline (GTK4 only)
- `GdkPixbuf.PixbufAnimation.new_from_file(path)` → `get_iter(None)`.
- Forward loop: `_gif_tick` → `advance()` → `get_pixbuf()` →
  `_gif_scaled_texture()` (scale to ≤640px + cache up to 60 frames) →
  `Gdk.Texture.new_for_pixbuf()` → `picture.set_paintable()` + `queue_draw()`.
- Ping-pong: one forward pass captures scaled textures + delays into
  `_gif_frames` (capped at 200), then `_gif_tick_pingpong` bounces an index
  forward/reverse without repeating endpoints.
- Frame count is read by **parsing the GIF binary block structure**
  (`_gif_frame_count`): counts Image Descriptors (`0x2C`), skips extensions
  (`0x21`) and sub-blocks, stops at trailer (`0x3B`).

### Settings window (`/ts`)
- GTK4 only. Single `Gtk.ScrolledWindow` vertical column; `_big_title` section
  headers; footer with "Changes apply immediately" + Close. Live-apply preserved.
- Eight page builders (`_build_background_page`, `_build_overlay_page`,
  `_build_titlebar_page`, `_build_accent_page`, `_build_chat_page`,
  `_build_highlight_page`, `_build_layout_page`, `_build_presets_page`).
- The Layout page now only holds a note pointing to the separate
  "User-buddylist editor" plugin.

---

## 4. Nicotine+ internals (confirmed facts)

These were verified against the installed source at
`C:\Program Files\Nicotine+\lib\python3.12\site-packages\pynicotine\`.

- **`theme.py`** — `_get_custom_color_css()` lives at
  `pynicotine/gtkgui/widgets/theme.py` (line ~521 in that install). This is the
  function the plugin mirrors in `_chat_color_css`.
- **`update_tag_visuals(tag, color_id)`** requires **two** arguments, not one.
  Text tags have a `color_id` attribute (set in `textview.py`).
- **`TextView` is a wrapper class** (`class TextView:`), not the actual
  `Gtk.TextView`. The real widget is at `self.widget`, and
  `self.textbuffer = self.widget.get_buffer()`. Walking the widget tree finds the
  underlying `Gtk.TextView` objects directly, so tag iteration works.
- **CSS provider priority** — Nicotine+ uses `STYLE_PROVIDER_PRIORITY_APPLICATION`
  (600); the plugin uses `USER` (800), so plugin CSS wins.
- **Config `ui` section** holds fonts (`globalfont`, `listfont`, `textviewfont`,
  `chatfont`, `searchfont`, `transfersfont`, `browserfont`) and chat colors
  (`chatlocal`, `chatremote`, `chatme`, `chat_hilite`, `urlcolor`, `inputcolor`,
  `inputtextcolor`, etc. — see `COLOR_LABELS`).
- **Search bars** in the `.ui` files: `activity_search_bar`, `chat_search_bar`
  (chatrooms.ui), `log_search_bar` (mainwindow.ui), `search_bar`
  (privatechat.ui).
- **`GtkSearchBar` CSS node tree** is `searchbar > revealer > box`. There's no
  `searchbar` styling in Nicotine+'s own CSS, so the strip comes from the system
  Adwaita theme.
- **`TextSearchBar`** is in `pynicotine/gtkgui/widgets/textentry.py`
  (`on_search_match`, `set_visible`).
- **Member-list header anchor** = `room_wall_button`; the header box is its
  parent.

---

## 5. Soulseek / Nicotine+ domain knowledge

- **Soulseek** is a peer-to-peer file-sharing network, historically music-focused
  but used for other media too. It's server-mediated: central servers index
  users/files and relay search, while actual transfers are peer-to-peer.
- **Nicotine+** is the open-source Soulseek client, written in Python with a GTK
  GUI (supports GTK3 and GTK4 builds).
- Core GUI concepts the plugins touch: **rooms** (chat rooms), **private chat**,
  **buddy list**, **room user list**, **transfers**, **search**, **log**.
- **Plugin system**: each plugin is a folder containing `__init__.py` +
  `PLUGININFO` (a Python dict with `name`, `description`, `authors`, `version`).
- Plugins are loaded from `%APPDATA%\nicotine\plugins\<name>\`. **Deployment is
  manual copy** — there's no auto-sync.
- Plugin base: subclasses `BasePlugin` with `init()`, `disable()`, optional
  `settings` / `metasettings` dicts, `commands` dict, and helpers
  `self.output(...)`, `self.log(...)`, `self.config`.

---

## 6. Python + GTK (PyGObject) learnings

### PyGObject / Gtk
- `GdkPixbuf.PixbufAnimationIter.advance()` — the PyGObject binding accepts a
  no-arg call; older bindings need an explicit millisecond timestamp
  (`advance(GLib.get_real_time() // 1000)`). Handle the `TypeError` and fall
  back.
- `Gdk.Texture.new_for_pixbuf(pixbuf)` and `new_from_file(path)` create textures
  (upload to GPU). **This is expensive for large images.**
- `Gtk.Picture` uses `set_content_fit(Gtk.ContentFit.CONTAIN | COVER)`.
- `Gtk.Snapshot.push_blur(radius)` blurs a specific widget scope (used for the
  background picture), unlike CSS `filter: blur()` which smears everything.
- `GdkPixbuf.Pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)` downscales.
- **`PixbufAnimation`'s iterator is NOT thread-safe.** Do not decode frames on a
  background thread with it.
- `Gtk.DropDown` + `Gtk.StringList` for dropdowns (`set_selected(index)`).
- `Gtk.Switch` (`notify::active`), `Gtk.Scale`/`Gtk.SpinButton` (`value-changed`),
  `Gtk.ColorButton` (`notify::rgba`).
- **`ListBox` has no `set_min_content_height`** — use `set_size_request(-1, h)`.
- `Gtk.Window.set_child(child)`, `Gtk.Overlay.add_overlay(child)`,
  `remove_overlay(child)` for GTK4 overlay layering.
- `GLib.timeout_add(ms, cb)`, `GLib.source_remove(id)`, `GLib.idle_add(cb)`
  (callback returning `False` removes the repeating source).

### Performance gotcha (the big one)
- Animated GIF via `GdkPixbuf.PixbufAnimation` decodes **every frame at full
  resolution** on the UI thread every loop iteration. Downscaling the frame
  *before* `new_for_pixbuf` fixes the GPU upload cost but **not** the decode
  cost. The remaining bottleneck is `advance()`'s full-res decode.
- Fixes applied so far: downscale frames to ≤640px, cap FPS at 25, cache scaled
  textures (60), ping-pong holds up to 200 scaled frames.
- **Back-burner options** (not yet done): pre-decode all frames once and replay
  from cache for the forward loop too; use Pillow to decode+resize during load
  (optionally in a worker thread) — Pillow is thread-safe, unlike GdkPixbuf's
  iterator.

---

## 7. The struggles & bugs we fought (with fixes)

This is the hard-won stuff — keep it here so we don't re-fight them.

1. **`KeyError: 'enable_switch'` crash** — `_close_settings_window` resets
   `self._settings_widgets = {}`, but the 300 ms debounced `_live_apply` could
   still fire afterward and hit `widgets["enable_switch"]` on an empty dict.
   *Fix:* guard `_read_and_commit` to return early when the widgets dict is
   empty/missing a sentinel, and cancel the pending `_live_timeout` in
   `_close_settings_window`.

2. **Chat colors not applying instantly** — two layered bugs. (a) Calling
   Nicotine+'s `update_tag_visuals(tag)` with one arg silently failed — it needs
   `(tag, color_id)`. (b) `Gtk.TextView` caret/treeview needed a re-render
   nudge (`caret-color` CSS + re-render workaround).

3. **GIF performance / broken chat auto-scroll** — large GIFs choked the UI via
   per-frame full-res texture upload. *Fix:* downscale + FPS cap + frame cache.
   (Full-res decode remains the residual bottleneck; see §6.)

4. **Overlay scrim / overlay image "did nothing"** — overlay children collapsed
   to zero size. *Fix:* explicit `set_halign(Gtk.Align.FILL)` /
   `set_valign(Gtk.Align.FILL)`.

5. **Find bar color not applying** — the flat `searchbar { background-color }`
   rule was overridden because the plugin tags the searchbar's inner `revealer`
   and `box` transparent, and those inner nodes weren't targeted. *Fix:* target
   `searchbar, searchbar > revealer, searchbar > revealer > box` with
   `!important`.

6. **Preset load reset `/ts` window position** — tried a scroll/position
   preserve, then reverted to a plain close+reopen because the complexity wasn't
   worth it (user decided to keep the reset behavior).

7. **`ListBox` `AttributeError: 'set_min_content_height'`** — replaced with
   `set_size_request(-1, 140)`.

8. **Userlist/buddy flicker** — root cause was double-ownership of userlist
   geometry between `theme_customizer` and the editor. *Fix:* move userlist/buddy
   ownership entirely into `buddylist_userlist_editor` and strip it from
   theme_customizer (the "nuclear" strategy).

9. **Snap-back in the editor** — the paned position snapped back after apply.
   *Fix:* apply width once per value (`_positioned_panes`), sync drag via
   `notify::position` with an `_applying_position` guard.

10. **`edit` tool atomic failure** — one `oldText` mismatch aborts the whole
    multi-edit call (nothing applies). Also, identical `oldText` blocks must be
    disambiguated with surrounding context (we hit this with the GIF state
    init/reset/stop blocks all containing the same `_gif_timeout = None` lines).

11. **Safety Guard false positives** — the guard denied `Remove-Item` (file
    delete) as intended, but also once misclassified a *read-only verification
    command* (`py_compile` + `Get-FileHash`) as a "File delete command" and
    blocked it. Don't retry a denied command in the same turn; use a different
    tool (e.g. `read`) or wait for the next turn.

12. **Power loss mid-operation** — laptop died mid-work once. Verification that
    files weren't truncated (reading file tails across workspace/DELIVERY/live
    copies) confirmed nothing was corrupted because writes had completed before
    the drop.

13. **WebM backgrounds removed** — `.webm` type and the background-type dropdown
    were removed in favor of auto-detect. Dead `_setup_webm_background` /
    `_stop_webm` remain as harmless backward-compatible code.

14. **Image darkening removed** — the "background image darkening" feature (a
    separate tint that only darkened the image) was fully stripped: constant,
    settings, metasettings, signature, config, scrim method + calls, UI, CSS.

---

## 8. Key design decisions

- **Nuclear userlist strategy** — consolidate buddy-list + user-list width/hide/
  drag into a single standalone editor; theme_customizer keeps zero ownership of
  that geometry.
- **Background auto-detect** — infer color/gif/image from the path; no type
  dropdown.
- **Overlay as independent layers** — readability tint + overlay image are
  separate; removed the combined `overlay_type`.
- **Blur via `Gtk.Snapshot.push_blur`**, never CSS `filter`.
- **Member-list header anchor** = `room_wall_button`.
- **Command contract** — command callbacks must use `self.output()` and
  `return True`.
- **Pagedoll anchor** = `private_content` box; on-top overlay (last
  `add_overlay` child, no event controllers → click-through).
- **GIF auto-downscale + FPS cap + cache** to keep large GIFs from stalling the
  UI; ping-pong loop style re-added on top of the scaled cache.

---

## 9. Deployment & verification workflow

- **Canonical source**: `!Nicotine plugins\<name>\__init__.py`.
- **Delivery**: mirror finished files to `DELIVERY\<name>\` (Ambrose's request:
  "from now on put any updates in DELIVERY"). Do **not** touch the live
  `%APPDATA%\nicotine\plugins\` folder unless asked.
- **Live install**: `C:\Users\kiquj\AppData\Roaming\nicotine\plugins\<name>\`
  (manual copy).
- **Verify without a GUI**: `python -m py_compile __init__.py`, then targeted
  `Select-String` greps for symbols/dangling references. No live testing.

---

## 10. Known issues / back-burner

- **GIF residual lag** (hi-rez GIFs): full-res decode via `advance()` every
  frame. Brainstormed options: (A) pre-decode once → replay from cache for the
  forward loop; (B) Pillow decode+resize in a worker thread; (C) configurable
  FPS/dimension caps, `INTERP_NEAREST`. On hold while Ambrose meditates.
- **Text outline lag** with GIF backgrounds — documented, left manual (not
  auto-disabled).
- The find-highlight `patched_match` has a `restarted=False` param that is
  unrelated to the "restart to apply" text (do not confuse the two).

---

## 11. File locations (current)

- Canonical plugin source: `C:\Users\kiquj\.openclaw-autoclaw\workspace\!Nicotine plugins\<name>\`
- Delivery mirror: `C:\Users\kiquj\.openclaw-autoclaw\workspace\DELIVERY\<name>\`
- Trash/preserved: `C:\Users\kiquj\.openclaw-autoclaw\workspace\!Nicotine plugins\.trash\`
- Live install: `C:\Users\kiquj\AppData\Roaming\nicotine\plugins\<name>\`
- Nicotine+ installed source (reference): `C:\Program Files\Nicotine+\lib\python3.12\site-packages\pynicotine\`
