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
| `gatherd-music-stand` | `scripts/` | `~/.local/bin/` | progressive score picker + presentation-mode viewer, atop tablet mode |
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
`$XDG_RUNTIME_DIR/gatherd/tablet-mode`.

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
   Touchpads are disabled unconditionally rather than filtered by identifier,
   since the i8042 heuristic does not transfer to touchpads and Sway exposes no
   internal-device flag.

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

1. Refresh the index if stale (above).
2. **Level 1 — composer.** Distinct composers, most-recently-played first, then
   alphabetical. 28 entries today.
3. **Level 2 — score.** That composer's scores, most-recently-played first, then
   alphabetical; at most 24 entries today (Medtner). Displays the index `title`,
   falling back to the filename stem. A `‹ Back` entry returns to level 1.
4. Confirm the picked file is still on disk, and that `{{ music_stand_viewer }}`
   is actually installed (`command -v`). Either check failing exits without
   touching tablet mode — deliberately in this order, so a cancelled or failed
   pick never leaves tablet mode half-applied: the index can lag a forScore
   deletion, and `{{ music_stand_viewer }}` is REST tier and may not exist yet
   between first login and the async play reaching the network, while this
   mechanism itself is CORE and must work offline.
5. Record the pick, `gatherd-tablet-mode on`, then open the file in
   `{{ music_stand_viewer }}`'s presentation mode (tap to turn the page).

Both levels use `fuzzel --dmenu` with enlarged entries for touch targets. Empty
or cancelled selection at either level → exit 0, leaving tablet mode as it was
found.

Two levels matter more here than they would on a desktop: **with no keyboard
there is no type-to-filter**, so selection is pure finger-scrolling. One flat
98-entry list is a scroll; composer-then-score is two short lists, and MRU
ordering makes the common case two taps with no scrolling at all.

**MRU state** is a single file, `~/.local/state/gatherd/music-stand-scores`,
holding `<composer>\t<title>\t<filename>` lines — the same three columns as the
index, so neither level needs a second lookup — in the same prepend / dedupe /
cap pattern as `gatherd-remmina-connect`. One file serves both levels: composer
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

**`inhibit_idle fullscreen` was tried first and disproven on hardware.** A
captured sway window-event trace opening a score shows sway's own
`for_window [app_id="org.gnome.Papers"] fullscreen enable` rule firing —
`fullscreen_mode` flips to `1` and the window resizes to the output — and then,
seconds later, papers itself flips `fullscreen_mode` back to `0`:

```
new              fullscreen_mode=0   rect=0x0
focus            fullscreen_mode=1   rect=683x406    <- sway's rule DOES apply
fullscreen_mode  fullscreen_mode=1
title            fullscreen_mode=1   rect=1371x857   <- resized to full output
fullscreen_mode  fullscreen_mode=0   rect=1371x857   <- papers turns it back OFF
```

Root cause: papers persists its own window state in the gsettings key
`org.gnome.Papers.Default fullscreen` and restores it shortly after mapping,
clobbering whatever sway had just set. The sway rule was never broken — it
just loses a race it cannot win. Since `inhibit_idle fullscreen` only inhibits
*while* fullscreen, the inhibitor disengages the moment papers wins that race,
and the screen blanks mid-piece: the one thing this feature exists to prevent.

**The fix is to stop fighting papers for fullscreen state and instead launch
into it.** `papers -f` won outright at the time — a captured trace ended
`fullscreen_mode=1`, `rect=1371x857`, `idle_inhibitors={"user":"fullscreen"}`,
stable at 8 seconds. `gatherd-music-stand` passed this flag
(`{{ music_stand_viewer_flag }}`, derived from `{{ music_stand_viewer }}`
the same way `{{ music_stand_app_id }}` is) when launching the viewer, and
`roles/desktop/tasks/tablet_mode.yml` drops the `fullscreen enable` for_window
rule entirely — the evidence shows it fires and is then overridden, so it
bought nothing but a visible flicker.

The flag has since moved from `-f` to `-s` (presentation mode — see Viewer
choice below): first real use at the piano rejected continuous scrolling in
favour of tap-to-turn, and presentation mode turned out to subsume
fullscreen anyway. A re-captured trace with `-s` shows `fullscreen_mode=1`,
`rect=1371x857`, and papers additionally holding its own idle inhibitor —
`idle_inhibitors={"user":"fullscreen","application":"enabled"}` — so the
`inhibit_idle visible` rule below and the tablet-mode-wide inhibitor are now
belt-and-braces rather than the only defence.

**Inhibition is now split into two layers, on two different properties, for
two different reasons:**

```
for_window [app_id="org.gnome.Papers"] inhibit_idle visible
```

This is viewer-scoped and keyed on `visible`, not `fullscreen` — the safety
property that actually matters is the score being *on screen*, not the window
manager's fullscreen flag, and `visible` cannot be clobbered by papers the way
`fullscreen` was. It remains a declarative `config.d` line rather than a flag
or a daemon, so there is still no inhibitor to leak if a script dies and no
cleanup path to get wrong.

`gatherd-tablet-mode` additionally inhibits idle for the whole of tablet mode,
not just the score viewer: `on` runs `inhibit_idle open` on every view
currently in the tree (from `swaymsg -t get_tree`, filtered to nodes with a
non-null `app_id` — outputs and workspaces are containers, not views, and must
never be targeted), and `off` runs `inhibit_idle none` on the same set. This
is tablet-mode-scoped: the score being visible is only one of the things a
folded, keyboard-disabled machine must stay awake for, and coupling *all*
idle-inhibition to whatever `{{ music_stand_app_id }}` happens to be would
leave every other window blanking normally while folded. Clearing it in `off`
is placed after the built-in-input re-enable and wrapped in `|| true` — input
must come first no matter what, and a compositor error clearing inhibitors
must never block the rotation restore or state cleanup that follow it.

Both layers exist together because they answer different questions: `visible`
on the viewer's own window is what makes the *feature* correct even if
tablet-mode's own inhibitor is ever removed or fails; `open` across the whole
tree is what makes *tablet mode itself* safe to fold the machine into,
independent of which application happens to be focused.

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
  *Exit music stand*, *Pick another score*, *Power…* (which chains to
  `power_menu.sh`).

*Pick another score* dispatches to `gatherd-music-stand on`, not `toggle`:
found in real use at the piano, where reading a score and wanting to switch to
a different one left no touch-reachable path — `$mod+Shift+t` is unreachable
with the keyboard disabled, and the menu offered only ways out of tablet mode.
`on` re-runs the composer/score picker and, since tablet mode is already
active, `gatherd-tablet-mode on` inside it is a no-op — the fold is never
interrupted. `toggle` would have exited tablet mode instead.

`roles/desktop/tasks/core.yml:115` already manages the
`bindsym XF86PowerOff exec $powermenu` line, so this is a change to an existing
task rather than a fork of the EndeavourOS script. The binding target becomes
conditional: `gatherd-power-button` where the feature applies, `$powermenu`
otherwise.

**Tablet mode is not a setting.** It is the fold. It begins when the hinge
folds and ends when the hinge unfolds, and nothing else turns it on or off.
The power-button menu therefore offers no exit: an exit entry could only mean
"undo the fold you are still holding", which the daemon corrects within a poll
and which hands back a keyboard lying face-down on the stand. Unfolding is the
exit, and it is a thing the hands already know how to do.

Everything that went wrong at the piano came from an earlier design in which a
manual toggle and the fold trigger coexisted: the ownership rule existed to
stop them fighting and is what trapped a human with no way out; the futile
exit ("Exit tablet mode" appearing to do nothing) was the two of them
disagreeing once per poll; a suppression latch was a patch on that
disagreement; and a live keyboard on a folded machine was a patch on the
patch. All four are deleted by making the fold the only authority.

**No keybinding enters or exits tablet mode.** `$mod+t` and `$mod+Shift+t`
originally toggled tablet mode and music stand; both were removed after a real
lockout at the piano. Folding is the only way in and unfolding is always the
way out, which makes the escape physical, obvious, and available even when the
screen is showing something unexpected.

The two halves of that are load-bearing together. While a keystroke could start
tablet mode from a typing angle, the hinge daemon needed an ownership rule
(exit only a session it entered itself) or it would have reversed such a
session instantly — and that rule is exactly what made unfolding a no-op for
manually-started sessions, leaving the edge power button as the single way out
of a machine with no keyboard. Remove the keystrokes and the ownership rule has
nothing left to protect, so it goes too. Score picking moves entirely to the
power button's touch menu (`Pick another score`), which is reachable folded.

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
tablet_mode_transform: normal         # or 180; see open questions
```

**The resting transform on this machine is `90`, not `normal`.** wlroots reads
the DRM panel-orientation quirk that `rotated_panel.yml` sets and applies a 90°
transform itself, so upright landscape *is* transform 90 here. Measured:

| transform | logical size | |
|---|---|---|
| `90` | 1371×857 | landscape — the resting state |
| `normal` | 857×1371 | **portrait** |
| `180` | 857×1371 | portrait, inverted |

This is exactly why `gatherd-tablet-mode off` restores the *recorded* transform
rather than hardcoding `normal`: hardcoding it would leave the machine sideways.

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

`papers` was originally chosen on toolkit rather than feature list: the claim
was that GTK4 provides kinetic touch-drag scrolling and pinch-zoom natively.
That reasoning is wrong — per the GNOME developer blog on Papers, Evince's
swipe-gesture code "stopped doing its job in Papers with the port to GTK 4".
`papers` remains the choice anyway, but for a different reason now: its
presentation mode (`-s`), not its toolkit — see Idle inhibition above.
`xreader`, a GTK3 Evince fork with 0 new dependencies, is the fallback
precisely because it predates that GTK4 regression. `okular`'s 25 KDE
Frameworks packages for one PDF viewer is the trade `docs/vnc.md` already
flags.

Configure the viewer for **presentation mode** (`-s`), not continuous scroll.
Continuous scroll was the original plan, on the reasoning that dragging a
score upward with one finger is a smaller and more forgiving mid-piece motion
than hitting a page-turn target — but it was rejected at the instrument: the
human tried it against the real hardware and wants to tap to turn the page,
not scroll. This was a design assumption corrected by first real use, not a
change of requirements. Presentation mode delivers tap-to-turn directly, and
as a bonus is inherently fullscreen (no race with sway's `for_window` rule —
see Idle inhibition above) and self-inhibits idle.

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

### Calibration, measured

A 30-second hand-held sweep through the full hinge range settled the geometry.
The angle between the two gravity vectors swung **164.1°**, which establishes
that one sensor really is in the lid — the concern that both might sit in the
base, which the bus topology had suggested, is disproved.

**The hinge axis is `y` in both sensor frames.** Gravity's component along the
hinge axis is preserved across a hinge, and exactly one axis behaves that way:

| Axis | mean \|device0 − device1\| (1 g = 1024) |
|---|---|
| x | 518.8 |
| **y** | **12.6** |
| z | 665.4 |

**The unsigned angle between the vectors is not usable.** It is symmetric about
180°, so it reads identically at 90° and 270° — it cannot distinguish a normal
typing angle from folded past flat, which the daemon needs to tell apart. It
must take the **signed** rotation about the hinge axis, projecting both
vectors onto the x–z plane:

```
θ = atan2(a0.x·a1.z − a0.z·a1.x,  a0.x·a1.x + a0.z·a1.z)
```

**θ is the hinge angle itself** (to within a small fixed sensor-mounting
offset) — there is no further transform. An earlier draft of this spec applied
one anyway (`φ = 180° − θ`) on the theory that it produced an asymmetry
letting the daemon "tell a shut laptop from a folded-back tablet". That claim
was false, and cost real use of the device to find: `atan2` wraps at ±180°,
not at zero, so hinge 0° (shut) and hinge 360° (folded all the way back) both
land at θ ≈ 0° regardless of which transform is applied to θ afterward. No
function of θ alone breaks that tie — closed and folded are the same angle.

That earlier draft also read the calibration sweep backwards. It recorded
"flat-open reads φ = 179.9°" — under the θ-is-the-angle correction, that
sample is θ ≈ 0°, not θ ≈ 180°. θ ≈ 0° is what **aligned** sensors read, and
aligned sensors mean the two bodies are parallel and stacked — shut or folded
— not coplanar and flat. What was recorded as the flat pose was actually a
shut-or-folded one; flat-open is the θ ≈ 178°–180° reading instead, matched in
the same sweep by the "normal typing angle reads φ = 107.8°" sample, which
under the same correction is θ ≈ 72°, in the same neighborhood as the typing
angle actually is once the offset is accounted for.

**The lid switch disambiguates what the angle cannot.** Since θ ≈ 0° means
either shut or folded, the daemon gates entry on the lid switch reading open
(`/proc/acpi/button/lid/LID0/state`), readable without privileges. Refusing to
act when the lid state can't be read is the safe default: acting means
disabling the keyboard.

**Reject contaminated samples.** These sensors measure all acceleration, not
just gravity; 6 of 16 sampled points in a hand-held sweep had magnitudes outside
1 g by more than 15%. Discard any sample where either magnitude deviates from
1 g by more than ~15%, rather than feeding it to `atan2`.

### The degenerate pose

**The method goes blind when the hinge axis is parallel to gravity.** Rotating
two bodies about a vertical axis changes neither sensor's reading, so nothing
encodes the fold.

This is not a corner case here — it is close to the piano pose. Reading portrait
puts the hinge on a vertical edge, so a machine held upright as a portrait tablet
is exactly where detection fails.

The measured hinge axis makes the test concrete rather than hand-wavy: when
`√(aₓ² + a_z²)` is small relative to `|a|`, gravity lies along the hinge axis and
the projection carries no signal. Two consequences for the daemon:

- On detecting that geometry it must **hold its last state** rather than
  threshold-crossing on noise. The normal path still works: the fold happens
  while the machine is roughly horizontal, where the angle reads cleanly, and the
  state persists as it is stood up.
- The **manual toggle stays the primary control**, with the daemon a
  convenience. This is why phase 1 ships first and stands alone, rather than
  being scaffolding for phase 2.

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
swaymsg -t get_outputs | jq -r '.[0] | "\(.transform) \(.rect.width)x\(.rect.height)"'
                                                          # normal 857x1371
swaymsg -t get_inputs | jq -r '.[] | select(.identifier | startswith("1:1:")) | .libinput.send_events'
                                                          # disabled
gatherd-tablet-mode off
swaymsg -t get_outputs | jq -r '.[0] | "\(.transform) \(.rect.width)x\(.rect.height)"'
                                                          # 90 1371x857
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

- ~~**Rotation direction**~~ — **settled on hardware.** `normal` reads correctly
  when the machine is folded, and there is no preferred "up" for this use, so
  either choice would have been acceptable. `tablet_mode_transform: normal`
  stands; `180` remains available as a variable if a preference emerges.
- **`papers` touch-drag** — cannot be verified without a finger on the glass.
  If it disappoints, `music_stand_viewer: xreader` costs nothing.
- ~~**Hinge sign convention and threshold**~~ — **settled by real use.** θ is
  the hinge angle itself; folding drives it toward 0° (wrapping past ±180°,
  not through it), and closed reads the same. `gatherd-hinge-daemon` detects
  on `|θ|` near zero (`fold_enter_deg`/`fold_exit_deg`, default 30/50) gated
  on the lid switch reading open, which is what tells closed from folded.

## Repave cadence

Per `CLAUDE.md`, `section_verify` items above ten are the signal to repave and
run the checklist. This feature adds two or three; the count is to be checked
when the verify items are written.
