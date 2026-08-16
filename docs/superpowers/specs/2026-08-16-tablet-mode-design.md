# Tablet mode (with music-stand as its first consumer)

**Status:** Approved design; implementation plan pending.

## Problem

The Chuwi MiniBook X is a 360° convertible, but nothing in the playbook knows
that. Folded into tablet form it is worse than useless: the screen stays
landscape, the keyboard and touchpad face down and register phantom input
against whatever the machine is resting on, and the screen blanks on the idle
timer.

The motivating use is reading piano scores at the instrument — portrait, full
page, hands on the keys — but the capability wanted is general. Rotation,
input suppression and an escape hatch are what "tablet mode" means on any
convertible; sheet music is one consumer of it.

## Constraints that shape the design

**There is no tablet-mode switch.** `Lid Switch` exposes SW bits `1` — `SW_LID`
only. No input device on the machine carries `SW_TABLET_MODE`, and
`Intel HID events` has `EV=13` (no `EV_SW` at all). Nothing in the kernel can
tell us the machine has been folded, so the trigger must come from somewhere
else.

**There is no keyboard in tablet mode.** Whatever turns tablet mode *off* must
be reachable with a finger, or by a button on an edge of the chassis. This rules
out a keybinding as the only control, and it rules out type-to-filter in any
picker.

**The panel is mounted rotated 90°.** `roles/hardware/tasks/rotated_panel.yml`
already corrects this at the kernel level, so sway sees an upright 1920×1200
landscape output. Two consequences: portrait is the panel's *native*
orientation and therefore lossless, and the accelerometer — whose mount matrix
is identity — reads 90° out of true. `iio-sensor-proxy` reports
`AccelerometerOrientation: "right-up"` with the machine flat on a desk, where
it should say `normal`. Any off-the-shelf auto-rotation tool will be wrong here
without that offset.

**`core_packages` is empty and must stay that way.** The mechanism has to
converge with no network.

## Hardware findings

Established by probing, and recorded here because they are not obvious and cost
real effort to rediscover.

The DSDT declares three accelerometer nodes, only one of which the firmware
enables:

| ACPI node | Path | `_STA` | Bound |
|---|---|---|---|
| `MXC6655:00` | `\_SB_.PC00.I2C0.ACMG` | `0` | no — but hardware answers at `i2c-11` `0x15` |
| `MXC6655:01` | `\_SB_.PC00.I2C2.ACMG` | `0` | no — **no hardware behind it** |
| `MDA6655:00` | `\_SB_.ACMK` | `15` | yes → `iio:device0` on `i2c-12` |

So there are genuinely two physical accelerometers — one per body — and
firmware simply declines to enumerate the second. Binding it by hand works and
is reversible:

```
echo mxc6655 0x15 > /sys/bus/i2c/devices/i2c-11/new_device   # → iio:device1
echo 0x15 > /sys/bus/i2c/devices/i2c-11/delete_device
```

Both report at scale `0.009582` (≈1024 LSB/g) and are world-readable, so the
angle daemon needs no privileges at runtime. Both carry a noticeable zero
offset; the magnitudes read ≈0.82 g and ≈1.17 g at rest rather than 1.00 g.

The DSDT also contains an `LTSM` method with the debug strings
`UPBT(LTSM) Laptop Start` and `UPBT(LTSM) Slate Start` — the firmware's own
laptop/slate transition, which disables the keyboard and emits genuine HID
tablet-mode events. **This is deliberately out of scope here** (see
[Deferred: the `LTSM` firmware path](#deferred-the-ltsm-firmware-path)).

`chassis_type` is `10` (Notebook), not `31` (Convertible) — Chuwi did not flag
the chassis, so DMI cannot be used to gate this feature.

## Approach

Split **trigger** from **mechanism**, and make the mechanism the only thing that
touches sway state:

```
   trigger                  mechanism                    policy
─────────────      ──────────────────────────      ─────────────────
keybinding    ─┐
power button  ─┼──▶  gatherd-tablet-mode      ◀──  gatherd-music-stand
hinge daemon ──┘     (on|off|toggle|status)        (adds idle-inhibit
   (phase 2)          rotate + disable input        + score picker)
```

Every trigger is a caller of one entry point. That is what lets phase 2 land
without reopening phase 1, and what would let the `LTSM` work land later as
*just another trigger* rather than a rewrite.

## Components

| Artifact | Source | Installed to | Purpose |
|---|---|---|---|
| `gatherd-tablet-mode` | `scripts/` | `~/.local/bin/` | the mechanism: rotate + suppress built-in input |
| `gatherd-music-stand` | `scripts/` | `~/.local/bin/` | progressive score picker + fullscreen viewer, atop tablet mode |
| `gatherd-music-index` | `scripts/` | `~/.local/bin/` | decodes forScore's backup into a composer/title index |
| `gatherd-power-button` | `scripts/` | `~/.local/bin/` | state-dependent power-button dispatcher |
| `roles/desktop/tasks/tablet_mode.yml` | new task file | — | installs the above; imported from `desktop/tasks/core.yml` |
| `has_touchscreen`, `has_accelerometer`, `has_dual_accelerometer` | `machine_facts` | — | capability gating |
| verify items | `scripts/gatherd-post-setup-notes` | — | mechanical checks |

Lives in the **desktop** role because it is per-user session tooling, alongside
`gatherd-remmina-connect` and the other `~/.local/bin` helpers. It is *not* in
`roles/hardware`, despite being hardware-gated, because that role runs only in
the REST plays and this must be CORE.

## `gatherd-tablet-mode`

`on | off | toggle | status`. Idempotent; state in
`$XDG_RUNTIME_DIR/gatherd-tablet-mode`.

**on:**

1. Identify the internal output by name (`eDP-*`, `DSI-*`, `LVDS-*`) — `DSI-1`
   here. Record its current `transform` in the state file, then
   `swaymsg output <name> transform {{ tablet_mode_transform }}`.
2. Suppress built-in input only:
   - keyboards whose sway identifier begins `1:1:` — the i8042 controller,
     `1:1:AT_Translated_Set_2_keyboard` on this machine
   - `swaymsg input type:touchpad events disabled`

   Matching the built-in keyboard by its i8042 identifier rather than
   `type:keyboard` is load-bearing: a Bluetooth page-turner pedal enumerates as
   a keyboard with a real vendor:product ID, and must keep working. The same
   goes for any external keyboard on a machine docked in tablet orientation.

**off:** restore the recorded transform, re-enable both device classes, clear
the state file. Restoring the *recorded* value rather than hardcoding `normal`
keeps this correct on a machine whose resting transform is not `normal`.

**status:** exit 0 when active, 1 otherwise. This is what `gatherd-power-button`
branches on, and what the verify step asserts against.

Calling `on` twice must not overwrite the saved transform with the rotated one —
the state file is written only on a genuine off→on transition.

## Score metadata: `gatherd-music-index`

Selecting by composer needs composer data, and **the filenames do not carry it**
(`12 Etudes, Op. 39.pdf`, `2 Skazki, Op. 48.pdf`). Neither do the PDFs: their
metadata is scanner residue (`HP Scanjet 8300 Document TWAIN`,
`www.ilovepdf.com`) with no title or author field.

The data lives in forScore's own `Automatic Backup.4sb`, whose format decodes
cleanly:

```
bytes 0..79    ASCII header:  <--4SBV02-->  <len>  <uuid>
bytes 80..     gzip  →  Apple binary plist (bplist00), ~1 MB
```

The plist is a flat dictionary keyed `"<filename>|<field>"`, with fields
including `composer`, `title`, `genre`, `rating` and per-page layout state. All
98 on-disk PDFs have a `composer` — coverage is complete, with 28 distinct
composers (Medtner 24, Bortkiewicz 16, Grieg 10, then a long tail).

`gatherd-music-index` decodes that into a plain TSV at
`~/.local/state/gatherd/music-index.tsv`:

```
<composer>\t<title>\t<filename>
```

**Python 3 stdlib only** — `zlib` and `plistlib` both read this natively, so
this adds no packages and the feature stays CORE.

Isolating the parse in its own script is the point. forScore's format is
proprietary and may change; when it does, the index goes stale rather than the
picker breaking, and staleness is detectable. `gatherd-music-stand` regenerates
the index automatically whenever the `.4sb` is newer than the TSV (a `stat`
comparison, no cron, no manual step), and **falls back to a flat MRU list of all
PDFs** if the backup is absent or fails to parse. Composer grouping is an
enhancement over the flat picker, never a prerequisite for reading a score.

Two data-quality artefacts are surfaced, not silently repaired: `Clara Schumann`
and `Schumann Clara` are recorded as two composers, and
`German Language School Westwood` is not a composer at all. Merging names by
guesswork would be wrong; these are edited in forScore, and the next index
refresh picks the corrections up.

## `gatherd-music-stand`

`on | off | toggle`. The picker is **progressive: composer, then score**, both
levels MRU-ordered.

**on:**

1. `gatherd-tablet-mode on`.
2. Refresh the index if stale (above).
3. **Level 1 — composer.** Distinct composers, most-recently-played first, then
   alphabetical. 28 entries today.
4. **Level 2 — score.** That composer's scores, most-recently-played first, then
   alphabetical; at most 24 entries today (Medtner). Displays the index `title`,
   falling back to the filename stem. A `‹ Back` entry returns to level 1.
5. Record the pick, then open the file fullscreen in `{{ music_stand_viewer }}`.

Both levels use `fuzzel --dmenu` with enlarged entries for touch targets. Empty
or cancelled selection at either level → exit 0, leaving tablet mode as it was
found.

Two levels matter more here than they would on a desktop: **with no keyboard
there is no type-to-filter**, so selection is pure finger-scrolling. One flat
98-entry list is a scroll; composer-then-score is two short lists, and MRU
ordering makes the common case two taps with no scrolling at all.

**MRU state** is a single file, `~/.local/state/gatherd/music-stand-scores`,
holding `<composer>\t<filename>` lines in the same prepend / dedupe / cap
pattern as `gatherd-remmina-connect`. One file serves both levels: composer
recency is the first appearance of each composer, score recency the order within
it. Two separate MRU files could disagree with each other; one cannot.

Only `*.pdf` is ever offered. The score directory also holds forScore's own
metadata (`*.4sb`, `syncFolderState`, `syncFolderLog`, `syncFolderIDs`), which
must never appear as a choice.

**off:** `gatherd-tablet-mode off`. The viewer is left running — closing a
document the user may still want is not this script's business.

The score directory is read live at invocation. The playbook never manages its
contents; note that it sits *outside* `icloud_sync_root`
(`~/Documents/iCloud`), so it is not populated by the iCloud sync feature.

### Idle inhibition

Not a daemon and not `systemd-inhibit`, but one declarative line in
`config.d`:

```
for_window [app_id="org.gnome.Papers"] inhibit_idle fullscreen
```

Sway suppresses blanking exactly while the score is fullscreen, and stops the
moment it is not. There is no inhibitor to leak if the script dies, and no
cleanup path to get wrong. The `app_id` is derived from
`{{ music_stand_viewer }}` so the fallback viewer stays correct.

## `gatherd-power-button` — the escape hatch

The power button is on an edge of the chassis and stays reachable when folded.
It already opens the power menu, and `has_powerbutton_events` is true on this
machine — `phys` is `PNP0C0C/button/input0`, not `LNXPWRBN`, so the repo's
suppression condition does not fire, and `HandlePowerKey=ignore` means logind is
not grabbing it.

The dispatcher branches on `gatherd-tablet-mode status`:

- **laptop mode** → exec EndeavourOS's `power_menu.sh` unchanged. Behaviour on
  every non-tablet machine, and on this one when unfolded, is untouched.
- **tablet mode** → a `fuzzel --dmenu` touch menu: *Exit tablet mode*,
  *Exit music stand*, *Power…* (which chains to `power_menu.sh`).

`roles/desktop/tasks/core.yml:115` already manages the
`bindsym XF86PowerOff exec $powermenu` line, so this is a change to an existing
task rather than a fork of the EndeavourOS script. The binding target becomes
conditional: `gatherd-power-button` where the feature applies, `$powermenu`
otherwise.

Keybindings for the unfolded case, both currently free: `$mod+t` toggles tablet
mode, `$mod+Shift+t` toggles music stand.

## Facts and gating

Following the repo's register-then-`set_fact` probe pattern, `changed_when:
false` on the read-only commands:

| Fact | Probe |
|---|---|
| `has_touchscreen` | any input device with `udev` property `ID_INPUT_TOUCHSCREEN=1` |
| `has_accelerometer` | any `/sys/bus/iio/devices/*/in_accel_x_raw` exists |
| `has_dual_accelerometer` | ≥2 `MXC6655` ACPI nodes present (phase 2 only) |

The feature installs when `has_touchscreen and has_accelerometer`. A laptop with
both is a convertible or a tablet in practice, and unlike `chassis_type` these
are actually true on the hardware.

## Variables

```yaml
music_stand_root: "{{ target_home }}/Documents/forscore"
music_stand_viewer: papers            # xreader is the zero-cost fallback
tablet_mode_transform: 90             # or 270; see open questions
```

The viewer is a variable, not a hardcode, precisely because its touch behaviour
is unverified.

## Tiering

| Piece | Tier | Why |
|---|---|---|
| all four scripts, sway config, facts, keybindings | **CORE** | shell plus Python stdlib and config only; zero packages, converges offline |
| `papers` | REST (`rest_packages`) | a package, therefore network |
| phase 2 udev rule + angle daemon | **CORE** | `/etc` and a shell script; no packages |

`core_packages` stays `[]`, so `gatherd-check-package-tiers` keeps passing. The
mechanism works on a fresh offline repave; only the preferred viewer waits for
the network, and `xreader` is already installed as a fallback if it never comes.

## Viewer choice

Linux has no equivalent of forScore or MobileSheets — no purpose-built sheet
music reader worth recommending exists. This is therefore a choice of general
PDF viewer with the best touch behaviour, measured on *this* machine by new
dependencies pulled in:

| Viewer | Toolkit | New deps | |
|---|---|---|---|
| `xreader` | GTK3 | **0** | already satisfied; the fallback |
| `papers` | **GTK4** | **2** | chosen |
| `evince` | GTK3 | 5 | superseded by Papers |
| `okular` | Qt6/KDE | **25** | richest touch features, whole KDE stack |

`papers` wins on toolkit rather than feature list: GTK4 provides kinetic
touch-drag scrolling and pinch-zoom natively. `okular`'s 25 KDE Frameworks
packages for one PDF viewer is the trade `docs/vnc.md` already flags.

Configure the viewer for **continuous scroll, fit-width, fullscreen**. A score
is a ribbon; dragging it upward with one finger is a smaller and more forgiving
mid-piece motion than hitting a page-turn target, and it never strands the
reader on a page boundary in the middle of a system.

## Phase 2 — hinge-angle trigger

Same spec, second phase, once phase 1 is proven.

1. **udev rule** binding the second accelerometer at boot (`i2c-11`, `0x15`) —
   the manual binding above does not survive a reboot.
2. **Angle daemon** — shell/awk, no `numpy`, therefore no packages. Computes the
   angle between the two gravity vectors and calls `gatherd-tablet-mode` across
   a threshold. Needs hysteresis: a single threshold will chatter while the
   hinge sits near it.
3. **Auto-rotation** from the lid sensor, applying the 90° offset implied by
   `has_rotated_panel`. The offset is the reason a stock tool cannot simply be
   installed.

Calibration constants come from a probe run that samples both accelerometers at
known hinge positions (closed, 90°, 120°, 180°, 270°, 360°). Evidence so far
puts `iio:device0` in the lid — gravity split evenly across two axes with the
lid tilted back — and `iio:device1` in the base, reading almost entirely on one
axis with the machine flat. This must be confirmed, not assumed.

## Deferred: the `LTSM` firmware path

`rhalkyard/minibook-dual-accelerometer` drives the `LTSM` ACPI method through a
small out-of-tree kernel module, making the *firmware* disable the keyboard and
emit a genuine `SW_TABLET_MODE`. That is architecturally the better answer: a
real switch works in greetd and on the tty, not only inside sway, and sway gets
native `bindswitch tablet:on`.

It is deferred to its own spec because it is the only piece carrying real risk
and real ongoing cost — a DKMS module rebuilt on every kernel bump, invoking an
undocumented ACPI method on a daily-driver machine, and REST/`slow.yml` tiering
for the toolchain. Deferring is cheap precisely because of the trigger/mechanism
seam: it arrives as a new trigger against an unchanged entry point.

That project would also need porting rather than installing: it targets an N100
under OpenSUSE and is explicitly "proof-of-concept stage", while this machine is
an **N150 on BIOS DNN20A V2.51** whose ACPI layout has moved — `MXC6655:01` is a
phantom node here, and the working sensor is exposed as `MDA6655`.

## Verification

Added to `section_verify` in `scripts/gatherd-post-setup-notes` as runnable
command sequences:

```
# Facts detected
gatherd-tablet-mode status; echo $?          # 1 (inactive)

# Mechanism
gatherd-tablet-mode on
swaymsg -t get_outputs | jq -r '.[0].transform'          # 90
swaymsg -t get_inputs | jq -r '.[] | select(.identifier | startswith("1:1:")) | .libinput.send_events'
                                                          # disabled
gatherd-tablet-mode off
swaymsg -t get_outputs | jq -r '.[0].transform'          # normal
swaymsg -t get_inputs | jq -r '.[] | select(.identifier | startswith("1:1:")) | .libinput.send_events'
                                                          # enabled

# Idle inhibit is armed
swaymsg -t get_tree | jq -r '.. | select(.app_id? == "org.gnome.Papers") | .idle_inhibitors'

# Score index decodes, and covers every PDF on disk
gatherd-music-index
cut -f1 ~/.local/state/gatherd/music-index.tsv | sort -u | wc -l     # 28
wc -l < ~/.local/state/gatherd/music-index.tsv                        # 98
ls ~/Documents/forscore/*.pdf | wc -l                                 # same 98
```

Manual residue, kept to what commands cannot cover: touch the screen while
rotated and confirm the pointer lands where the finger does (this exercises
wlroots' remapping of touch coordinates through the output transform), and
confirm a one-finger drag scrolls the score.

## Open questions

- **Rotation direction** — `90` or `270`, depending which way the machine folds
  and which edge ends up at the top. Settled by one test; a variable regardless.
- **`papers` touch-drag** — cannot be verified without a finger on the glass.
  If it disappoints, `music_stand_viewer: xreader` costs nothing.
- **Hinge calibration** — phase 2 only; needs the probe run.

## Repave cadence

Per `CLAUDE.md`, `section_verify` items above ten are the signal to repave and
run the checklist. This feature adds two or three; the count is to be checked
when the verify items are written.
