# TODO

- Have we actually solved the NFS-autofs-Tailscale shutdown ordering problem?
- **PIA credentials from 1Password**: move `piactl login` out of `slow.yml` and into a `gatherd-prompt-pia` script (Sway autostart, same pattern as `gatherd-prompt-tailscale`) that fetches username/password from `op`. Removes `vault_pia_username` and `vault_pia_password` from `vault.yml`.
- Set up SSH authorized key from public URL
- Which Web Apps do I want?
    - LLMs: Lumo, Grok, ...)
    - iCloud: Drive, Notes, Reminders
- Set up VNC
- JetBrains IDE settings, starting with font size

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
