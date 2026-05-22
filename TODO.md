# TODO

- NFS client automount: done and ansibilized. `~/.autofs-mounts/code` mounts from ap-juicer via tailscale (works on LAN and remote).
  - Still to do: migrate `/home/schmonz/trees` to a symlink → `.autofs-mounts/code/trees` (local `dotfiles/` already moved to `~/.dotfiles`; `trees/` dir now only has local repos)
- Conky gap_y and systray icon-size: both now scale with foot_font_size, needs repave verification


## Most recent attempted features

needs re-verification on next repave:
- NFS automount via autofs (was not verified on repave; autofs from AUR, config in system role, service started in aur role, mounts ~/.autofs-mounts/code from ap-juicer via tailscale)
- dotfiles cloned to ~/.dotfiles, symlinks for .gitconfig/.gitignore_global/.tmux.conf (was not verified on repave; ~/trees no longer created by playbook)
- conky gap_y clears tmux statusbar (was not verified on repave; scales with foot_font_size)
- systray icon-size matches waybar scale (was not verified on repave; scales with foot_font_size)
- terminal window for slow-Ansible progress (was anti-verified; fixed sentinel-file + timeout approach)
- systray apps start up (was anti-verified; replaced five wrapper scripts with one generic gatherd-systray)
- JetBrains Toolbox starts silently in tray (was almost-verified; now pre-seeds .storage.json to skip onboarding window)
- JetBrains Toolbox user agreement dialog (was anti-verified; now pre-seeds .appState.json navigation to /main)
- captive browser (was semi-verified; dropped unsupported --host-resolver-rules, added DnsOverHttps, switched to whatsmyip.schmonz.com)
- first-run Helium opens directly, no setup tab (was anti-verified; now pre-seeds helium.completed_onboarding in initial_preferences)

## Hardware

- **clight**: installed on any machine with screen or keyboard backlight, but
  intentionally inoperative (clightd not enabled, not in sway autostart). Caused
  blank screen on resume from sleep on MacBook Air 11" (maps dark room to 0%).
  To activate: enable clightd service, add `exec clight` to sway autostart, and
  set a brightness floor (e.g. `min_backlight_pct = 0.15` in `clight.conf`) and
  dimmer config (40% target, 60s battery timeout) — verify key names against
  `man clight` or `/usr/share/clight/modules.conf.d/` on a live machine.

- **iSight camera**: detect and install `isight-firmware` (AUR).

- **ThinkPad fingerprint reader**: investigate `fprintd` + PAM integration.
  Needs per-model enrollment testing (T60 optical sensor vs. newer swipe/touch
  sensors).

- **ThinkPad smart card reader**: investigate `pcscd` + `opensc`. T60 has a
  built-in reader; verify other models.

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
- **webapp-manager** generates non-spec-compliant `Exec` lines (`--app="url"`
  instead of `--app=url`), causing fuzzel to refuse to launch them.
  `gatherd-fix-webapps` auto-fixes new entries via inotifywait. Consider filing
  an upstream bug.
