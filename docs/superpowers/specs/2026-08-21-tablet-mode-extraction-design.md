# Extracting tablet mode into chuwi-minibook-tablet-mode

**Date:** 2026-08-21
**Status:** approved, not yet implemented

## Why

The fold detection, rotation, input suppression and escape menu are properties
of the *hardware*, not of one person's Ansible setup. Any Chuwi MiniBook X
owner on Linux hits the same wall — `rhalkyard/minibook-dual-accelerometer` was
the prior art that started this — and none of them want a config-management
repo. gatherd keeps the parts that are genuinely gatherd's, and consumes the
rest.

The compositor decoupling (`65fd74e`) was the precondition: 28 `swaymsg` calls
across three scripts and a Python daemon now sit behind ten verbs in one file.
Without that, "works on any Linux" would have been a claim rather than a design.

## What moves

The mechanism, ~1,290 lines of runtime code plus a 2,127-line suite:

| File | Becomes | Lines |
| --- | --- | --- |
| `scripts/gatherd-hinge-daemon` | `bin/minibook-hinge-daemon` | 705 |
| `scripts/gatherd-tablet-mode` | `bin/minibook-tablet-mode` | 204 |
| `scripts/gatherd-compositor` | `bin/minibook-compositor` | 173 |
| `scripts/gatherd-power-button` | `bin/minibook-power-button` | 123 |
| `scripts/gatherd-bind-hinge-sensor` | `bin/minibook-bind-hinge-sensor` | 57 |
| `services/system/gatherd-hinge-sensor.service` | `systemd/minibook-hinge-sensor.service` | 29 |
| `tests/tablet-mode` | `tests/tablet-mode` | 2127 |
| `docs/superpowers/specs/2026-08-16-tablet-mode-design.md` | `docs/design.md` | 653 |

## What stays in gatherd

`gatherd-music-stand`, `gatherd-music-index`, and the forScore `.4sb` parser.
A stranger arriving at a MiniBook X tablet-mode project is not looking for a
sheet-music reader, and forScore is Apple-specific: its backup format is a
proprietary Apple binary plist, and the index is worthless without one.

gatherd also keeps its `has_dual_accelerometer` fact (it gates other things),
the Ansible role, and the config template.

## What changes shape

**The folded menu becomes config-driven.** Today `Pick another score` and
`Close score` are hardcoded in `gatherd-power-button`, which couples the
mechanism to one application. They become a list of `label|command` pairs read
from the config, one per line, split on the **first** `|` only so that a
command may itself contain pipes. `Cancel` and the auto-rotate toggle stay built in: those are
properties of the mechanism, not of whatever is being read.

gatherd's config supplies the music-stand entries. The new repo ships one
trivial example entry so a stranger's first fold produces a menu that does
something.

## Naming

Repo `chuwi-minibook-tablet-mode` — a MiniBook X owner searching for this
should find it. Commands are prefixed `minibook-`: the repo name carries the
vendor for discoverability, the commands stay typeable.

Config moves to `$XDG_CONFIG_HOME/minibook-tablet-mode/config`, with key names
unchanged.

## Layout

```
chuwi-minibook-tablet-mode/
  bin/         minibook-{tablet-mode,hinge-daemon,power-button,compositor,bind-hinge-sensor}
  systemd/     minibook-hinge-sensor.service
  etc/         config.example
  tests/       tablet-mode
  docs/        design.md  PORTING.md
  install.sh
  README.md
```

`install.sh` is POSIX sh, respects `--prefix` (default `/usr/local`), installs
the commands, the unit, and an example config. No make, no build step: the
project is scripts.

## Requirements, stated plainly

`README.md` says what is actually needed:

- **A dual-accelerometer convertible.** Two IIO accelerometers, one in the lid
  and one in the base. `minibook-bind-hinge-sensor` exists because the MiniBook
  X's second sensor is not enumerated by ACPI and must be bound by hand.
- sway (see portability below), `jq`, `python3` (stdlib only), `fuzzel`,
  `setsid`.
- Calibration is per-machine and config-driven. The README documents the
  landscape-versus-portrait trap in deriving `rotation_reference_deg`, because
  getting it wrong produces a display that tracks the tablet perfectly while
  sitting a quarter turn off, and that cost a day here.

## Portability, stated honestly

`PORTING.md` carries the verb-by-verb assessment. A port implements the ten
verbs of `minibook-compositor` and changes nothing else.

| Verbs | Elsewhere |
| --- | --- |
| `internal-output`, `output-transform`, `set-transform`, `valid-transform` | Easy everywhere. `xrandr` on X11; `hyprctl`/`riverctl`/Wayfire IPC on other wlroots compositors; GNOME and KDE both have rotation CLIs |
| `window-present`, `set-fullscreen` | Easy on wlroots and X11 (`wmctrl`, `xdotool`); awkward on GNOME/KDE |
| `silence-builtin-input`, `builtin-input-silenced`, `builtin-input-disabled` | **Hard.** sway exposes libinput `send_events` per device; X11 has `xinput --disable`; GNOME and KDE expose nothing equivalent to scripts |
| `inhibit-idle-all` | **Hard.** sway sets it per window; elsewhere idle inhibition is a Wayland protocol an application requests, not something a script imposes |

Verdict: **other wlroots compositors and X11 are real ports. GNOME and KDE are
not feasible** with this architecture — they would need extensions, not
scripts. The README claims sway only, because that is all that has been run.

What is *not* compositor-specific, and is the valuable part: the dual-sensor
hinge geometry, the measured calibration, fold hysteresis, the degenerate-pose
guards, and adaptive polling.

## History

Preserved with `git filter-repo` (`pacman -S git-filter-repo`, in `extra`).

That history is load-bearing here in a way it often is not. It records why
`rotation_reference_deg` is 267 and not 177; three separately falsified
explanations for a menu that came up empty; the measured noise floors behind
every threshold; and which mutation each test exists to catch. Someone changing
a constant can find out why it is what it is.

Three phases, each separately verifiable:

1. **Extract.** `filter-repo` a clone of gatherd down to the paths above.
2. **Rename.** `filter-repo --replace-text` for `gatherd-*` → `minibook-*`
   across blobs and messages. This makes old commits describe commands by names
   they did not yet have — a mild fiction, noted in the README, and preferable
   to a history that talks about a repo the reader has never seen.
3. **Convert the suite to BATS**, as one ordinary commit.

Phase 3 is deliberately *not* a history rewrite. Making history "always BATS"
would require either hand-converting every historical revision of a file that
changed on nearly every commit, or replacing all historical revisions with the
final content — which destroys the diffs, breaks `git bisect`, and defeats the
reason for keeping history at all. A newcomer is better served by an honest
commit that says the suite was converted.

BATS is a test-only dependency (bash), so it does not affect what a user needs;
it does raise the bar slightly for a contributor on a minimal system.

## How gatherd consumes it

A `tablet_mode` role that:

1. clones `chuwi-minibook-tablet-mode` at `tablet_mode_version` (a pinned tag
   in `group_vars`) into `~/.local/src/chuwi-minibook-tablet-mode`;
2. runs `install.sh --prefix ~/.local`, so the commands land in `~/.local/bin`
   where the current ones already live and nothing else has to move;
3. templates the config, including the music-stand menu entries.

Pinned rather than tracking `main`: this repo already pins package tiers and
keeps an offline-cache manifest, and a repave two years from now should
reproduce what runs today. Upgrading is a one-line bump that can be reverted.

The moved scripts are deleted from `scripts/`. gatherd's suite keeps only what
covers music-stand.

## Verification

Not "it still seems to work":

- The 297 assertions move with the code and stay green through the rename, and
  again after the BATS conversion.
- gatherd's remaining suite stays green after the deletion.
- A converge leaves the machine behaving exactly as it does now: fold enters,
  unfold exits, auto-rotate follows, the folded menu offers the music-stand
  entries from gatherd's config, and a score fills the screen in both orders.
- The boundary assertion travels too: a `swaymsg` appearing outside
  `minibook-compositor` fails a test.

## Deferred

- Packaging (PKGBUILD/AUR). Scripts plus `install.sh` first; packaging once
  someone other than its author has installed it.
- Ports to other compositors. `PORTING.md` documents the contract; no second
  backend is written until someone wants one.
- The KOReader `hwdetect` patch stays in gatherd: it is about a PDF viewer, not
  about tablet mode, and it expires when koreader ships e9c0a6e39.
