# Hot corners that lock, and lock with the screen off

**Status:** Approved design; implementation plan pending.

## Problem

Locking the screen is a keystroke — `$mod+f1` runs bare `gtklock` — and there
is no gesture for it at all. macOS hot corners are the habit worth reproducing:
throw the pointer into the upper-right corner to lock, into the lower-right to
turn the screen off and lock.

Blanking is not a new capability; it is one already spelled out three times in
`autostart_applications`, where swayidle locks with
`gtklock -d --lock-command "swaymsg output * dpms off"`. What is missing is a
way to ask for it deliberately rather than waiting five minutes for the idle
timer.

## Constraints that shape the design

**The upper-right corner is waybar's power button.** `custom/power` is the last
entry in `modules-right`, so the corner a pointer is thrown at is already
occupied. waycorner's surface is on the overlay layer with
`set_exclusive_zone(-1)`, i.e. above waybar and positioned against the true
screen edge, so the hot corner wins the extreme pixels and the power button
keeps the rest of its width. This was weighed against moving the corners to the
bottom edge or moving the power button, and the macOS layout was chosen
knowingly: a 10px capture at the very corner, and a dwell delay so that a
pointer flung at the power button does not lock the screen on the way past.

**waycorner ignores touch, but its surface still absorbs it.** It listens only
to `wl_pointer` `Enter`/`Leave` (`wayland.rs:130-134`) and only on seats with
`has_pointer`, so no fingertip can ever trigger a lock. The surface has no
input region carved out, though, so a touch in those 10 pixels lands on it and
goes nowhere. Two dead corners are harmless with a trackpad and unacceptable at
the piano, where koreader's page-turn tap zones reach the edges of a folded
screen.

**Corner locations ignore `margin`.** In waycorner, the margin arms of the match
resolve to 0 for `top_right` and `bottom_right` (`wayland.rs:266-284`); only the
edge locations use it. The hotspot therefore sits flush in the corner, which is
what makes a corner slam work at all.

## Approach

waycorner from the AUR, running as a systemd user service, with both corners
pointed at one small script that owns what "lock" and "blank and lock" mean.

`wlhc` was the alternative and was rejected: an unversioned git AUR package with
no dwell delay, no per-output configuration, and no releases.

## Components

### `scripts/gatherd-lock-screen [--blank]`

The single entry point for locking, from a corner or a keystroke.

- Plain: `gtklock -d`.
- `--blank`: `gtklock -d --lock-command 'swaymsg output * dpms off'` — verbatim
  what swayidle already runs, so a screen blanked deliberately and a screen
  blanked by the idle timer are the same state, and any input wakes it still
  locked.
- If gtklock is already running, `--blank` blanks and does not start a second
  lock; plain does nothing.
- `--print` writes the commands it would run to stdout and exits without
  running them. This is what the tests and the verify step call.

**It warps the pointer to the centre of the focused output before locking.**
Without that, the pointer sits in the hot corner for the duration of the lock,
and unlocking delivers a fresh pointer `Enter` to waycorner's surface, which
locks the screen again — a loop with no way out but a keyboard. `swaymsg
seat - cursor move` is confirmed working on this machine; `cursor set` to the
focused output's centre is the intended call, and the first implementation step
is to confirm both the re-entry loop and that the warp prevents it.

### `~/.config/waycorner/config.toml`

Templated, with no `[*.output]` section so both corners exist on every output at
any resolution — nothing to compute per machine.

    [lock]
    locations = ["top_right"]
    enter_command = ["gatherd-lock-screen"]
    size = 10
    timeout_ms = 250

    [blank]
    locations = ["bottom_right"]
    enter_command = ["gatherd-lock-screen", "--blank"]
    size = 10
    timeout_ms = 250

### `waycorner.service` (systemd user unit)

Follows `gatherd-handle-lid` exactly: `PartOf=graphical-session.target`,
`WantedBy=graphical-session.target` by symlink into
`graphical-session.target.wants`, and
`exec systemctl --user start waycorner.service` in `autostart_applications`.

A unit rather than an `exec_always` line so that tablet mode can stop and start
it by name, without any process ever being killed by pattern.

### Tablet mode

`turn_on` in `gatherd-tablet-mode` stops the unit; `turn_off` starts it. Folded
on a music stand there are no corners to hit and no pointer to hit them with,
and the two dead touch zones disappear for exactly as long as fingers are the
input device.

### Keybindings

`$mod+f1` becomes `gatherd-lock-screen` and `$mod+Shift+f1` becomes
`gatherd-lock-screen --blank`, so the keyboard and the corners do the same two
things. Today `$mod+f1` runs bare `gtklock`: no daemonize, no blank.

### `roles/desktop/tasks/hot_corners.yml`

CORE — script, config template, user unit, symlink, autostart line and
keybindings are all local file edits.

`waycorner` goes in `aur_slow_packages`; it is a Rust build and does not belong
in the fast list. The unit therefore fails harmlessly on a fresh machine until
the async play has built it, so `roles/desktop/tasks/rest.yml` starts it once
the package exists rather than leaving the first session without corners.

## Testing

`tests/lock-screen`, in the style of `tests/tablet-mode`: fake `swaymsg`,
`gtklock` and the running-lock check on `PATH`, no compositor required.

- The pointer is warped before gtklock is invoked, not after.
- `--blank` passes the dpms lock-command; plain does not.
- A trigger while already locked blanks without spawning a second gtklock.
- `--print` runs nothing.

## Verification

A step in `section_verify` of `scripts/gatherd-post-setup-notes`:
`gatherd-lock-screen --print --blank` shows the expected gtklock command,
`systemctl --user is-active waycorner` reads `active`, and the same command
reads `inactive` while folded into tablet mode. The manual half is two
sentences: throw the pointer into the upper-right corner and the screen locks;
into the lower-right and it goes dark and locks.

## Deliberately out of scope

- **The upper-left and lower-left corners** stay unassigned.
- **No unlock-side behaviour**: the pointer is left where the warp put it.
