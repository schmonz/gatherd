# Fitting the application drawer to the screen it opens on

**Status:** Approved design; implementation plan pending.

## Problem

`$mod+Shift+d` opens nwg-drawer, and the icon grid is wider than the screen.
Reaching the leftmost and rightmost columns means scrolling the grid sideways,
which is nasty on a trackpad and worse on a touchscreen. It is not a MiniBook
quirk: the column count is a constant, so every machine gatherd converges gets
the same grid regardless of how wide its panel is.

The launch comes from EndeavourOS's stock line in
`~/.config/sway/config.d/autostart_applications`, which gatherd does not manage:

    exec_always nwg-drawer -r -c 7 -is 90 -mb 10 -ml 50 -mr 50 -mt 10

## Why it overflows

`-c` is not a maximum. `uicomponents.go:220-224` sets it as **both** bounds of a
homogeneous flowbox:

    flowBox.SetMinChildrenPerLine(*columnsNumber)
    flowBox.SetMaxChildrenPerLine(*columnsNumber)
    flowBox.SetColumnSpacing(*itemSpacing)
    flowBox.SetRowSpacing(*itemSpacing)
    flowBox.SetHomogeneous(true)

With the minimum pinned, the grid cannot reflow to fewer columns when it does
not fit. It overflows its scrolled window instead, and you get a horizontal
scrollbar.

**The icon is not what sets the cell width.** Homogeneous means every cell is as
wide as the widest child, and each child is a button with the icon above a
label. nwg-drawer truncates names to 17 characters plus an ellipsis
(`if len(name) > 20`), and on this machine the widest resulting label —
"NetSurf Web Browser" — renders 135px wide in the GTK interface font, against
an icon only 90px wide. The label wins, so any formula written in terms of
`-is` alone is wrong.

Measured on the MiniBook X panel (1200x1920 at scale 1.4, so 1371 logical px
wide): cell pitch 193px, 7 columns = 1331px of grid against 1271px of usable
width after `-ml 50 -mr 50`. Sixty pixels of overflow, and that is the scroll.

## Approach

A wrapper script computes the column count at launch from the width of the
output the drawer is about to appear on, and relaunches nwg-drawer if that
count has changed.

Computing it once at converge time and baking it into the exec line was
rejected: it is wrong the moment a narrower external monitor is plugged in or
the output is rotated, and it would need a reconverge to recover. A wrapper is
right on any panel, any monitor, and after a tablet-mode rotation, with nothing
to reconverge.

## The math

    cell    = max(widest_label_px, icon_size) + 38
    pitch   = cell + spacing
    columns = max(1, (output_width - ml - mr + spacing) / pitch)

`38` is button chrome: GTK's own button padding plus `drawer.css`'s
`button, image { margin: 10px }` on each side. `spacing` is nwg-drawer's
`--spacing`, 20 by default. The column formula follows from n cells needing
`n * cell + (n - 1) * spacing` of room, i.e. `n * pitch - spacing`.

Checked against reality on the MiniBook X panel: widest label 135 gives a pitch
of 193, matching the 193 measured from a screenshot of the real drawer;
`(1371 - 100 + 20) / 193` = 6 columns, occupying 1138 of 1271 usable px. Seven
is correctly rejected. A 1920-wide output gets 10.

## Components

### `scripts/gatherd-drawer-cell-width`

Python. Prints one integer — the widest label in pixels — and nothing else.

Reads `gtk-font-name` from `~/.config/gtk-3.0/settings.ini` (default
`Noto Sans 10`), walks `.desktop` entries in `/usr/share/applications`,
`/usr/local/share/applications` and `~/.local/share/applications`, skips
`NoDisplay=true`, applies nwg-drawer's truncation rule, and asks PangoCairo for
the rendered width of each name.

PangoCairo rather than a GTK widget on purpose: measuring a real `Gtk.Button`
requires mapping a window, which took 14 seconds and needs a display.
`PangoCairo.FontMap.get_default()` needs neither and takes 310ms over 99
entries.

Exits nonzero if the bindings or the font are unavailable, so the caller can
fall back rather than fail.

### `scripts/gatherd-drawer`

POSIX sh. Owns the nwg-drawer flags — icon size, margins, spacing — so the
values in the launch command and the values in the arithmetic cannot drift
apart.

- **no arguments** (what `$mod+Shift+d` runs): read the focused output's
  `rect.width` from `swaymsg -t get_outputs` — already logical pixels, scale
  applied — and compute the column count. If the resident instance is alive
  with that count, run plain `nwg-drawer`, which sends `SIGUSR1` and preserves
  today's press-again-to-close toggle. Otherwise relaunch (below) and then
  `nwg-drawer -open`.
- **`--start`** (what autostart runs): the same, without opening. Idempotent,
  because `exec_always` re-runs on every sway reload.
- **`--columns [WIDTH]`**: print the column count, computing from `WIDTH` if
  given and from the focused output otherwise. This is the pure function, and
  what the tests and the verify step call.

**Relaunching** reads the PID from `~/.local/share/nwg-drawer.lock`, kills that
exact PID, starts `nwg-drawer -r -c <columns> …`, and waits for the lock file to
reappear before signalling it. Killing by recorded PID and never by name or
pattern is deliberate: a pattern kill has taken out unrelated sessions here
before.

**Caching.** The measured cell width is cached in `$XDG_RUNTIME_DIR` and
recomputed when any of the three `applications` directories has a newer mtime,
so installing an app with a long name is picked up but an ordinary keypress
costs three `stat` calls instead of 310ms. If the measurement fails, the script
falls back to a pitch of 200px: slightly conservative on a crowded screen,
never a missing launcher.

### `roles/desktop/tasks/drawer.yml`

CORE — no packages, no network, and nwg-drawer is already on the machine.

1. Install both scripts to `~/.local/bin`.
2. `set $menu gatherd-drawer` in `config.d/default`.
3. Replace the stock `exec_always nwg-drawer -r -c 7 …` line in
   `autostart_applications` with `exec_always gatherd-drawer --start`, matching
   either spelling so a converged machine is not left with two drawers.
4. Add `python-gobject` to the package list. It is present on this machine only
   as another package's dependency, which is not a guarantee.

## Testing

`tests/drawer`, in the style of `tests/tablet-mode`: fake `swaymsg`,
`nwg-drawer` and the cell-width helper on `PATH`, no compositor required.

- The column count for a range of widths, including the MiniBook X's 1371 (6),
  a 1920 output (10), and a screen too narrow for even one column (clamped
  to 1).
- The 200px fallback pitch when the cell-width helper exits nonzero.
- No relaunch when the running instance already has the right count, and the
  toggle path is what runs.
- A relaunch kills the PID named in the lock file and nothing else.

## Verification

A step in `section_verify` of `scripts/gatherd-post-setup-notes`: compare
`gatherd-drawer --columns` against the focused output's width from `swaymsg`,
asserting `columns * pitch - spacing` fits within the usable width, and one
manual line — press `$mod+Shift+d`, confirm there is no horizontal scrollbar.

## Deliberately out of scope

- **No cap on the column count.** A wide monitor gets as many columns as fit.
- **No change to `-is 90`.** Worth recording that the labels leave headroom to
  raise icons to about 135px before they would start driving the cell width, if
  bigger touch targets are ever wanted.
