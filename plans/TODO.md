# TODO

- We never validated that `mbpfan` is doing useful things on applicable machines (such as MBA7,1)
- Chromebook gets described as `Google Robo (rev3)`, want it to say `Lenovo Chromebook 100e`, not seeing any helpful strings in `dmidecode` output
- Something in the playbooks needs golang and that's causing stuff to get dumped in `~schmonz/go`. Didn't we take steps to make that stuff go elsewhere? Why aren't they taking effect?
- PIA systray icon has tooltip "update available", the right-click menu gives only "Quit", and if I log out and log back into Sway to push the VPN-login flow again, I do get prompted by 1Password to let it happen, but then I get a notification that PIA login failed
- `jetbrains_authed` is inaccurate -- thinks I'm authed (and removes the post-setup instructions) when I'm not
- **Slow shutdown** (~54s measured, reboot trigger → final unmount; was framed
  as "Tailscale 2 min + umount.nfs4 a minute or two"). Traced via persistent
  journal + verbose autofs logging. Three contributors, in order of cost:
  - **tmux pane scope — ~30s (dominant).** The tmux server registers each pane
    as its own systemd user scope; one pane held `user@1000.service` open ~30s
    while every other user unit stopped in ~0.4s. Nothing to do with NFS/Tailscale.
    *Unknown*: why ~30s (default user `TimeoutStopSec` is 90s, so either that
    scope sets its own ~30s timeout — i.e. an interactive process ignoring
    SIGTERM, easily bounded lower — or it did ~30s of real/NFS-blocked cleanup).
    Confirm on a future shutdown whether the scope is SIGKILLed at the timeout.
    Per-pane-scope registration is NOT in `~/.tmux.conf`; find its source first.
    Note: the Claude Code session runs in a tmux pane, so it may be a contributor.
  - **NFS umount — ~10s.** Verbose autofs shows `/net` + `/misc` unmount
    instantly; the whole cost is the `code` nfs4 session/TCP teardown to the
    server over Tailscale. Candidate fix: a shutdown-time force-unmount (mirror
    `gatherd-unmount-nfs`), or investigate NFSv4 lease/delegation return.
  - **tailscaled — ~10s.** Correctly capped (`TimeoutStopUSec=10s` drop-in
    works), but wastes the full 10s retrying log uploads to `log.tailscale.com`
    after the link is already down, then gets SIGKILLed. Candidate fix: suppress
    the shutdown log-upload retries, or drop the stop timeout to ~5s.
  - **Reframe**: "Tailscale 2 min" is no longer true (capped at 10s of wasted
    log-flush). Biggest win is the tmux pane scope, not NFS or Tailscale.
- **NFS mount slow to return after resume**: suspend itself is fixed
  (`gatherd-unmount-nfs` force-unmounts before sleep so the freeze succeeds),
  but after unlock the `~/trees` NFS mount takes ~1 min to come back. Network
  and Tailscale recover in ~5s, so the delay is NOT reconnect time.
  *Hypothesis* (unconfirmed): autofs's negative-mount cache. If something
  touches `~/trees` in the few seconds after unlock — before Tailscale is up —
  that mount attempt fails, and autofs then refuses to retry the `code` key for
  `negative_timeout` (default 60s), which matches the symptom.
  - **First, confirm the cause.** Verbose autofs logging is now on (takes
    effect after an autofs restart / reboot). On the next resume cycle, read
    `journalctl -u autofs`: a `code` mount *failure* right after unlock followed
    by *success* ~60s later confirms the negative cache. If instead the minute
    is NFSv4 lease/grace recovery, a stale lazy-unmount reference left by
    `gatherd-unmount-nfs`, or DNS, neither fix below applies — investigate that.
  - **(1) Lower autofs `negative_timeout`** (e.g. 10s) in `autofs.conf`. Bounds
    the worst case: a too-early access still fails, but autofs retries sooner
    instead of waiting out the full minute. Cheap; doesn't prevent the failed
    attempt.
  - **(2) Post-resume warm-up hook**: a `system-sleep` `post` hook that waits
    for Tailscale connectivity, then triggers the `~/trees` mount so it's warm
    before you touch it. Removes the delay in the common case.
  - **Choosing**: (2) alone is not airtight — if you unlock-and-`cd` faster than
    Tailscale reconnects (~5s), your own access poisons the negative cache
    before the warm-up wins, and you still wait it out. (1) alone never prevents
    the failed attempt, only caps the penalty. So if the cause is confirmed to
    be the negative cache, do **both**: (2) to avoid the failed attempt, (1) to
    bound any residual race.
- Which Web Apps do I want?
    - iCloud: Drive, Find My Devices, Notes, Reminders, Maps
    - Other: Amazon, Duolingo, Reddit
- Set up VNC (see `VNC.md`)
- JetBrains IDE settings, starting with font size
- **Auto git pull on a cadence**: the sentinels now record the git HEAD that
  ran to completion, and gatherd-needs-run re-runs a play when HEAD changes.
  Add a timer (systemd) that periodically `git -C /usr/local/lib/gatherd pull`s
  origin, so a pushed change converges every machine on its next reboot without
  a manual pull. Decide: pull on boot, on a timer, or both; how to surface
  failures; whether to auto-reboot or wait for the next natural one.
- **Auto-etckeeper-commit per /etc-touching task**: today most /etc-writing tasks
  carry `notify: Etckeeper commit` and a few don't. Make the wiring automatic so
  a freshly written task doesn't have to remember. Candidates: a wrapper module,
  an `import_tasks` shim, or a post-play `meta: flush_handlers` + global path-watch
  scheme. End state: any task that writes under `/etc` results in an etckeeper
  commit, with no per-task boilerplate.
- **Script GUI app setup**: many manual first-run steps (1Password CLI toggle,
  JetBrains IDE prefs, Zoom 2FA, web app sign-ins) live behind GUI-only paths.
  Investigate driving them programmatically — candidates: `ydotool`/`wtype` for
  Wayland keystrokes, accessibility APIs (AT-SPI), `dogtail`-style tools, Electron
  apps' DevTools protocols, app-specific URL schemes. Goal: shrink the manual
  steps in `gatherd-post-setup-notes` toward zero.

## Hardware

- **clight**: installed on any machine with screen or keyboard backlight, but
  intentionally inoperative (clightd not enabled, not in sway autostart). Caused
  blank screen on resume from sleep on MacBook Air 11" (maps dark room to 0%).
  To activate: enable clightd service, add `exec clight` to sway autostart, and
  set a brightness floor (e.g. `min_backlight_pct = 0.15` in `clight.conf`) and
  dimmer config (40% target, 60s battery timeout) — verify key names against
  `man clight` or `/usr/share/clight/modules.conf.d/` on a live machine.

- **iSight camera**: detect and install `isight-firmware` (AUR).

- **Expand fingerprint PAM beyond sudo**: currently `pam_fprintd.so` is only
  wired into `/etc/pam.d/sudo`. Once we trust it, also add to `system-auth`
  (covers greetd login, gtklock lock screen, polkit). Verify on a TTY before
  rolling out, since a broken system-auth edit can lock you out of GUI logins.

- **Generalize fingerprint reader support**: the probe in `machine_facts`
  currently matches only Validity 138a:0097 (driven by `python-validity`).
  When we hit a different reader, extend the USB ID case statement and branch
  the install task (stock `fprintd` for libfprint-supported sensors,
  `python-validity` for Validity 0097-family). Furthermore, we don't have
  explicit checking or control flow for enrollment: is it already done,
  do we need to do it, do we need to _undo_ it first, etc.

- **ThinkPad smart card reader**: investigate `pcscd` + `opensc`. T60 has a
  built-in reader; X270 (20HMS6VR00) has Alcor Micro AU9540 (058f:9540), a
  USB CCID-class device — use this to develop the probe and install steps.
  T470 (20JM000BUS) does NOT have one — no USB CCID interface, no PCI smart
  card device.

- **ThinkPad docking**: investigate `dockd` or udev rules for dock/undock events
  (display reconfiguration, power profile switch).

## Electron app UI scaling

Five Electron apps are installed. Their UI may be fine at default scale on 1080p,
but if they ever look too small, here's how to scale each:

- **Slack** (`slack-electron`, system `electron39`) and **Teams**
  (`teams-for-linux-electron`, system `electron41`): both wrapper scripts fall back
  to `~/.config/electron-flags.conf`. Add `--force-device-scale-factor=1.4` there.
  Teams also reads its own app-specific conf
  (`~/.config/teams-for-linux-electron-flags.conf`) which avoids the double-application
  that happens when using `electron-flags.conf` (Teams reads it, then `electron41` reads
  it again).

- **Signal**: has `~/.config/signal-desktop-flags.conf` support built into its launcher.

- **Claude**: runs native Wayland automatically (no flags.conf hook). Options: local
  desktop override at `~/.local/share/applications/claude.desktop`, or a wrapper at
  `~/.local/bin/claude-desktop`.

- **1Password**: add the flag to its `gatherd-systray` autostart entry in sway config.

Ansible hook: write `~/.config/electron-flags.conf` (covers Slack + Teams) and
`~/.config/signal-desktop-flags.conf` from the desktop role, using
`--force-device-scale-factor={{ foot_font_size | float / 10.0 }}`.

## Multi-display

- **Detection**: probe connected outputs, set a fact (e.g. `has_multiple_displays`) so tasks can condition on it
- **Layout**: configure output positions in sway (which is primary, relative placement)
- **Scaling**: font size and other size-dependent values (conky, waybar, systray icons) need to make sense across displays that may differ in resolution or DPI — figure out what "going well together" means and automate it
- **Screen security on resume**: verify that at no point after lid-close / sleep / hibernate / lock is the pre-lock screen content visible — confirm swaylock is covering all outputs before the session is unsuspended

## Desktop / UX

- **Light/dark mode switch**: darkman + waybar button wired up; Helium, xed,
  apostrophe switch. foot does not: in server mode, existing sessions can't be
  reconfigured without killing them all, and new sessions don't pick up the
  portal state either. Options: (a) tolerate it and accept foot always starts
  in dark mode; (b) try foot in non-server mode (latency tradeoff); (c) find a
  replacement terminal that is native Wayland or X11, starts with low latency,
  can suppress all UI chrome, and supports programmatic per-session color
  reconfiguration — candidates: lxterminal, gnome-terminal.
- **Geolocation**: enable via `xdg-desktop-portal-gtk` or punt.
- **Auto light/dark mode**: via geolocation or simple timer.
- **Lid close**: mute + lock + suspend (non-Chromebook).
- **Hot corners**: lower-right → lock + sleep display; upper-right → lock.
- **More dotfiles**: currently only `.gitconfig` and `.tmux.conf` are symlinked.
  Want to use more without losing system-provided defaults (sway configs, waybar,
  foot, etc. come from `sway-install.sh` and are patched by Ansible). Options:
  (a) for tools that support includes/fragments, have the personal dotfile source
  the system one; (b) for Sway specifically, already using `config.d/` — personal
  dotfiles can add more fragments; (c) for files that don't compose, decide whether
  personal or system default wins and manage accordingly.
- **More systray or waybar indicators**: LLM token usage and
  notifications. What else?

## Setup

- **Snapshots**: find CLI equivalent to Welcome-app GUI for Timeshift initial
  config. Decide snapper vs. Timeshift (snapper + pacman hooks?).
- **Swap for hibernate**: size swap partition appropriately; Chromebook may differ.
- **TI calculator AUR packages**: create AUR packages for TI calculator backup
  programs; install here once they exist.

## Portability

- **arch-update timer**: currently a systemd user timer; will need a different
  mechanism on Artix/s6.

## Configurability

- **Personal / per-machine config**: replace the `hardcoded_*` placeholders in
  `group_vars/all/main.yml` (`hardcoded_dotfiles_repo`,
  `hardcoded_ssh_authorized_keys_dotfile`) and `wifi_networks` in the vault
  with a real delivery mechanism so the repo carries no me-specific defaults.
  Candidates: `ansible-playbook -e @/etc/gatherd/personal.yml` with the file
  staged by Calamares (or USB at install); inventory + `host_vars/` pointing
  at an out-of-repo path; network-fetched config in `postinstall`. Add an
  early `assert` listing every required key so missing config fails fast
  instead of silently skipping tasks.
