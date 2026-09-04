# Migrations

What each removal-shaped task in the playbook carries forward, and whether it
is still needed. Generated initially by `scripts/gatherd-census-removals
--ledger`; maintained by hand thereafter.

Design and rationale: `docs/superpowers/specs/2026-09-01-spent-cleanup-detection-design.md`.

**This file licenses nothing.** An entry recorded as a pure migration says only
that the task does no work on a fresh install. It does *not* say every machine
has converged past it, which is what actually gates deletion and which nothing
here can answer.

## How an entry works

    - roles/system/tasks/user_path.yml:34 — Remove obsolete profile.d PATH file
      shape: state: absent
      thing: /etc/profile.d/gatherd-local-bin.sh, replaced by pam_env
      check: test -e /etc/profile.d/gatherd-local-bin.sh
      fresh-install expectation: absent (pure migration)
      measured: 2026-09-14 absent

One entry per removed *thing*, not per task: several tasks loop over items of
mixed provenance, and one verdict cannot cover items that legitimately differ.
The seeded entries below are per task, because that is what a census can see;
splitting a looping task is done while writing its checks.

`fresh-install expectation` is stated per entry rather than inferred, because
polarity inverts: for an additive task, "present on a fresh install" means the
task is a no-op there.

Two rules for writing a `check`, both from measured failures:

- Never copy a task's regexp into `grep -E`. Ansible regexps are Python `re`;
  `(?:...)` and `(?!...)` are errors under `grep -E` and work only under `-P`.
- Never use `~` or a relative path. Checks run as root, where `~` is `/root`.

A check is trusted only once it has been *calibrated* — demonstrated returning
the "still does work" answer somewhere it should. Until then the entry is
unmeasured, because every accidental failure (missing binary, wrong dialect,
unexpected path) exits nonzero, which is the answer that licenses deletion.

## Unmeasured

- roles/aur/tasks/slow.yml:9 — Remove the superseded claude-desktop-bin
  shape: state: absent
  check: pacman -Qq claude-desktop-bin >/dev/null 2>&1
  fresh-install expectation: absent (pure migration)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:40 — Remove obsolete per-user gatherd-askpass
  shape: state: absent
  check: test -e "$TARGET_HOME/.local/bin/gatherd-askpass"
  fresh-install expectation: absent (pure migration)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:45 — Remove obsolete environment.d askpass file
  shape: state: absent
  check: test -e "$TARGET_HOME/.config/environment.d/50-gatherd-askpass.conf"
  fresh-install expectation: absent (pure migration)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:50 — Remove obsolete environment.d sentinel file
  shape: state: absent
  check: test -e "$TARGET_HOME/.config/environment.d/99-gatherd-env-sentinel.conf"
  fresh-install expectation: absent (pure migration)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:79 — Remove stock swayidle entries superseded by our configuration
  shape: state: absent
  thing: ^exec swayidle idlehint
  check: grep -q "^exec swayidle idlehint" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: present (permanent: upstream ships this line)
  measured: 2026-09-01 present
- roles/desktop/tasks/core.yml:79 — Remove stock swayidle entries superseded by our configuration
  shape: state: absent
  thing: ^exec_always swayidle -w before-sleep
  check: grep -q "^exec_always swayidle -w before-sleep" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: present (permanent: upstream ships this line)
  measured: 2026-09-01 present
- roles/desktop/tasks/core.yml:104 — Remove EndeavourOS's polkit-gnome agent from sway autostart
  shape: state: absent
  thing: upstream's polkit-gnome exec line
  check: grep -qE "^exec .*polkit-gnome-authentication-agent" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: present (permanent: upstream ships this line)
  measured: 2026-09-01 present
- roles/desktop/tasks/core.yml:110 — Remove the now-orphaned polkit autostart comment
  shape: state: absent
  check: grep -q "^# Auth with polkit" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: present (permanent: upstream ships this line)
  measured: 2026-09-01 present
- roles/desktop/tasks/core.yml:166 — Remove network throughput widget from waybar center
  shape: state: absent
  thing: "network" in waybar config
  check: grep -qE "^[[:space:]]+\"network\"[[:space:]]*,?[[:space:]]*$" "$TARGET_HOME/.config/waybar/config"
  fresh-install expectation: present (permanent: upstream ships this widget)
  measured: 2026-09-01 present
- roles/desktop/tasks/core.yml:403 — Remove vestigial Chromium browser config
  shape: state: absent
  thing: .config/chromium/initial_preferences
  check: test -e "$TARGET_HOME/.config/chromium/initial_preferences"
  fresh-install expectation: absent (pure migration: gatherd seeded it in a913393)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:403 — Remove vestigial Chromium browser config
  shape: state: absent
  thing: .config/chromium/Default/Preferences
  check: test -e "$TARGET_HOME/.config/chromium/Default/Preferences"
  fresh-install expectation: absent (pure migration: gatherd seeded it in a913393)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:403 — Remove vestigial Chromium browser config
  shape: state: absent
  thing: .config/chromium-flags.conf
  check: test -e "$TARGET_HOME/.config/chromium-flags.conf"
  fresh-install expectation: absent (pure migration: gatherd seeded it in a913393)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:696 — Remove the obsolete ssh host-key float rule
  shape: state: absent
  thing: gatherd-hostkey-verify float rule
  check: grep -q "gatherd-hostkey-verify" "$TARGET_HOME/.config/sway/config.d/application_defaults"
  fresh-install expectation: absent (pure migration: gatherd's own former rule)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:842 — Remove sway-install.sh stray gparted desktop entry
  shape: state: absent
  thing: gparted.desktop
  check: test -e "$TARGET_HOME/.local/share/applications/gparted.desktop"
  fresh-install expectation: absent (measured 2026-09-01: the Sway edition's .local/share/applications is populated at install but ships no gparted.desktop; the earlier 'upstream leaves it' belief was wrong)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:847 — Remove obsolete gnome-keyring --unlock autostart lines
  shape: state: absent
  thing: gnome-keyring-daemon --unlock
  check: grep -q "gnome-keyring-daemon --unlock" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd added it in 58f3522, dropped in e3b0612)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:853 — Remove obsolete systray autostart entries
  shape: state: absent
  thing: gatherd-launch-systray
  check: grep -qE "^exec (.*/)?gatherd-launch-systray$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former helper)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:853 — Remove obsolete systray autostart entries
  shape: state: absent
  thing: gatherd-systray-1password
  check: grep -qE "^exec (.*/)?gatherd-systray-1password$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former helper)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:853 — Remove obsolete systray autostart entries
  shape: state: absent
  thing: gatherd-systray-localsend
  check: grep -qE "^exec (.*/)?gatherd-systray-localsend$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former helper)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:853 — Remove obsolete systray autostart entries
  shape: state: absent
  thing: gatherd-systray-tailscale
  check: grep -qE "^exec (.*/)?gatherd-systray-tailscale$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former helper)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:853 — Remove obsolete systray autostart entries
  shape: state: absent
  thing: gatherd-systray-updater
  check: grep -qE "^exec (.*/)?gatherd-systray-updater$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former helper)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:853 — Remove obsolete systray autostart entries
  shape: state: absent
  thing: gatherd-systray-jetbrains
  check: grep -qE "^exec (.*/)?gatherd-systray-jetbrains$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former helper)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:853 — Remove obsolete systray autostart entries
  shape: state: absent
  thing: gatherd-wait-sni
  check: grep -qE "^exec (.*/)?gatherd-wait-sni$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former helper)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:876 — Remove per-helper autostart entries now launched by the session supervisor
  shape: state: absent
  thing: ^exec conky$
  check: grep -qE "^exec conky$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former line)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:876 — Remove per-helper autostart entries now launched by the session supervisor
  shape: state: absent
  thing: gatherd-prompt-* helpers
  check: grep -qE "^exec (.*/)?gatherd-prompt-(captiveportal|1password|tailscale|postsetup|vault|pia)$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former helpers)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:876 — Remove per-helper autostart entries now launched by the session supervisor
  shape: state: absent
  thing: gatherd-systray invocations
  check: grep -qE "^exec .*gatherd-systray " "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former helper)
  measured: 2026-09-01 absent
- roles/desktop/tasks/core.yml:876 — Remove per-helper autostart entries now launched by the session supervisor
  shape: state: absent
  thing: gatherd-polkit-agent
  check: grep -qE "^exec (.*/)?gatherd-polkit-agent$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (pure migration: gatherd's own former helper)
  measured: 2026-09-01 absent
- roles/desktop/tasks/tablet_mode.yml:99 — Remove the hand-written forscore-sync superseded by gatherd-musicscores-fetch
  shape: state: absent
  thing: forscore-sync
  check: test -e "$TARGET_HOME/.local/bin/forscore-sync"
  fresh-install expectation: absent (pure migration: never shipped by gatherd or anything else — hand-written into ~/.local/bin on 2026-08-15, superseded by gatherd-musicscores-fetch)
  measured: 2026-09-04 present on this machine (the only one it was ever written on); absent by construction anywhere else
- roles/desktop/tasks/tablet_mode.yml:70 — Unbind the old tablet mode and music stand keystrokes in sway
  shape: state: absent
  thing: $mod+t binding
  check: grep -qE "^[[:space:]]*bindsym[[:space:]]+\$mod\+t[[:space:]]" "$TARGET_HOME/.config/sway/config.d/default"
  fresh-install expectation: absent (pure migration: gatherd's own former binding)
  measured: 2026-09-01 absent
- roles/desktop/tasks/tablet_mode.yml:99 — Remove the hand-written forscore-sync superseded by gatherd-musicscores-fetch
  shape: state: absent
  thing: forscore-sync
  check: test -e "$TARGET_HOME/.local/bin/forscore-sync"
  fresh-install expectation: absent (pure migration: never shipped by gatherd or anything else — hand-written into ~/.local/bin on 2026-08-15, superseded by gatherd-musicscores-fetch)
  measured: 2026-09-04 present on this machine (the only one it was ever written on); absent by construction anywhere else
- roles/desktop/tasks/tablet_mode.yml:70 — Unbind the old tablet mode and music stand keystrokes in sway
  shape: state: absent
  thing: $mod+Shift+t binding
  check: grep -qE "^[[:space:]]*bindsym[[:space:]]+\$mod\+Shift\+t[[:space:]]" "$TARGET_HOME/.config/sway/config.d/default"
  fresh-install expectation: absent (pure migration: gatherd's own former binding)
  measured: 2026-09-01 absent
- roles/desktop/tasks/tablet_mode_upstream.yml:49 — Link the hinge-sensor udev rule
  shape: force+link
  thing: force:true replacing a copied rule
  check: test -e /etc/udev/rules.d/99-minibook-hinge-sensor.rules
  fresh-install expectation: absent (the link is permanent work; only force:true is the migration, and it has no separate observable)
  measured: 2026-09-01 absent
- roles/desktop/tasks/vesktop.yml:57 — Discard the truncated Vencord bundle so Vesktop refetches it
  shape: state: absent
  thing: truncated Vencord bundle
  check: test -e "$TARGET_HOME/.config/vesktop/sessionData/vencordFiles"
  fresh-install expectation: absent (runtime hygiene: heals a killed fetch, never spent)
  measured: 2026-09-01 absent
- roles/desktop/tasks/vesktop_vencord.yml:57 — Discard whatever incomplete bundle is there
  shape: state: absent
  thing: incomplete Vencord bundle
  check: test -e "$TARGET_HOME/.config/vesktop/sessionData/vencordFiles"
  fresh-install expectation: absent (runtime hygiene: heals a killed fetch, never spent)
  measured: 2026-09-01 absent
- roles/desktop/tasks/vesktop_vencord.yml:116 — Leave no partial bundle behind for Vesktop to trust
  shape: state: absent
  thing: partial Vencord bundle
  check: test -e "$TARGET_HOME/.config/vesktop/sessionData/vencordFiles"
  fresh-install expectation: absent (runtime hygiene: heals a killed fetch, never spent)
  measured: 2026-09-01 absent
- roles/desktop/tasks/wallpaper.yml:65 — Remove EndeavourOS wallpaper leftovers
  shape: state: absent
  thing: .azotebg
  check: test -e "$TARGET_HOME/.azotebg"
  fresh-install expectation: present (permanent: upstream ships it)
  measured: 2026-09-01 present
- roles/desktop/tasks/wallpaper.yml:65 — Remove EndeavourOS wallpaper leftovers
  shape: state: absent
  thing: EndeavourOS_SpaceStation png
  check: test -e "$TARGET_HOME/.config/sway/EndeavourOS_SpaceStation__3840x2160.png"
  fresh-install expectation: present (permanent: upstream ships it)
  measured: 2026-09-01 present
- roles/desktop/tasks/wallpaper.yml:65 — Remove EndeavourOS wallpaper leftovers
  shape: state: absent
  thing: EndeavourOS_Astronaut png
  check: test -e "$TARGET_HOME/.config/gtklock/EndeavourOS_Astronaut_SpaceWalk.png"
  fresh-install expectation: present (permanent: upstream ships it)
  measured: 2026-09-01 present
- roles/hardware/tasks/ambient_light.yml:58 — Disable clightd service
  shape: unit off
  thing: clightd enabled
  check: systemctl is-enabled clightd >/dev/null 2>&1
  fresh-install expectation: unmeasurable here (measured 2026-09-01: clightd is not installed, so systemctl is-enabled returns not-found with rc 4, correctly recorded as an error rather than as absent; this task is hardware-gated and needs a machine with the sensor)
  measured: 2026-09-01 error
- roles/hardware/tasks/ambient_light.yml:64 — Remove clight from sway autostart
  shape: state: absent
  thing: exec clight
  check: grep -q "^exec clight$" "$TARGET_HOME/.config/sway/config.d/autostart_applications"
  fresh-install expectation: absent (permanent: upstream ships it only where clight is installed)
  measured: 2026-09-01 absent
- roles/system/tasks/aurutils.yml:51 — Clear a stale repository lock left by a killed build
  shape: state: absent
  thing: stale repo lock
  check: test -e /var/cache/gatherd-aur/gatherd-aur.db.tar.zst.lck
  fresh-install expectation: absent (runtime hygiene: heals a killed build, never spent)
  measured: 2026-09-01 absent
- roles/system/tasks/aurutils.yml:63 — Repair the repository database symlinks
  shape: force+link
  thing: repo db symlinks
  check: test -e /var/cache/gatherd-aur/gatherd-aur.db
  fresh-install expectation: absent (permanent config, not a migration: force:true is the ordinary symlink idiom here)
  measured: 2026-09-01 absent
- roles/system/tasks/aurutils.yml:148 — Remove aurutils artifacts from earlier builds
  shape: state: absent
  thing: stale build artifacts
  check: test -d /var/cache/gatherd-aur
  fresh-install expectation: absent (runtime hygiene: prunes earlier builds, never spent)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:15 — Symlink resolv.conf to stub resolver
  shape: force+link
  thing: /etc/resolv.conf
  check: test -L /etc/resolv.conf
  fresh-install expectation: permanent config, not a migration: force:true is the ordinary symlink idiom here
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:159 — Remove EOS default logind suspend drop-in
  shape: state: absent
  thing: EOS logind suspend drop-in
  check: test -e /etc/systemd/logind.conf.d/suspend.conf
  fresh-install expectation: present (permanent: upstream ships it)
  measured: 2026-09-01 present
- roles/system/tasks/core.yml:177 — Mask sleep targets
  shape: unit off
  thing: hibernate.target
  check: [ "$(systemctl is-enabled hibernate.target 2>/dev/null)" = masked ]
  fresh-install expectation: absent (permanent config, not a migration: a fresh machine is unmasked)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:177 — Mask sleep targets
  shape: unit off
  thing: hybrid-sleep.target
  check: [ "$(systemctl is-enabled hybrid-sleep.target 2>/dev/null)" = masked ]
  fresh-install expectation: absent (permanent config, not a migration: a fresh machine is unmasked)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:177 — Mask sleep targets
  shape: unit off
  thing: sleep.target
  check: [ "$(systemctl is-enabled sleep.target 2>/dev/null)" = masked ]
  fresh-install expectation: absent (permanent config, not a migration: a fresh machine is unmasked)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:177 — Mask sleep targets
  shape: unit off
  thing: suspend-then-hibernate.target
  check: [ "$(systemctl is-enabled suspend-then-hibernate.target 2>/dev/null)" = masked ]
  fresh-install expectation: absent (permanent config, not a migration: a fresh machine is unmasked)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:177 — Mask sleep targets
  shape: unit off
  thing: suspend.target
  check: [ "$(systemctl is-enabled suspend.target 2>/dev/null)" = masked ]
  fresh-install expectation: absent (permanent config, not a migration: a fresh machine is unmasked)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:267 — Mask services that conflict with TLP
  shape: unit off
  thing: systemd-rfkill.service
  check: [ "$(systemctl is-enabled systemd-rfkill.service 2>/dev/null)" = masked ]
  fresh-install expectation: absent (permanent config, not a migration: a fresh machine is unmasked)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:267 — Mask services that conflict with TLP
  shape: unit off
  thing: systemd-rfkill.socket
  check: [ "$(systemctl is-enabled systemd-rfkill.socket 2>/dev/null)" = masked ]
  fresh-install expectation: absent (permanent config, not a migration: a fresh machine is unmasked)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:267 — Mask services that conflict with TLP
  shape: unit off
  thing: power-profiles-daemon.service
  check: [ "$(systemctl is-enabled power-profiles-daemon.service 2>/dev/null)" = masked ]
  fresh-install expectation: absent (permanent config, not a migration: a fresh machine is unmasked)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:290 — Remove obsolete gatherd path units
  shape: unit off
  thing: gatherd-vault.path
  check: [ "$(systemctl is-enabled gatherd-vault.path 2>/dev/null)" = masked ]
  fresh-install expectation: absent (pure migration: gatherd's own former unit, replaced in a5cae14)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:290 — Remove obsolete gatherd path units
  shape: unit off
  thing: gatherd-async.path
  check: [ "$(systemctl is-enabled gatherd-async.path 2>/dev/null)" = masked ]
  fresh-install expectation: absent (pure migration: gatherd's own former unit, replaced in a5cae14)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:301 — Delete obsolete gatherd path unit links
  shape: state: absent
  thing: gatherd-vault.path
  check: test -e /etc/systemd/system/gatherd-vault.path
  fresh-install expectation: absent (pure migration: gatherd's own former unit, replaced in a5cae14)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:301 — Delete obsolete gatherd path unit links
  shape: state: absent
  thing: gatherd-async.path
  check: test -e /etc/systemd/system/gatherd-async.path
  fresh-install expectation: absent (pure migration: gatherd's own former unit, replaced in a5cae14)
  measured: 2026-09-01 absent
- roles/system/tasks/core.yml:366 — Remove gnome-keyring PAM auth line (starts --login daemon with autologin, locking keyring with unknown password)
  shape: state: absent
  thing: pam_gnome_keyring auth line
  check: grep -q "auth.*pam_gnome_keyring.so" /etc/pam.d/greetd
  fresh-install expectation: absent (measured 2026-09-01: /etc/pam.d/greetd exists but no file under /etc/pam.d mentions keyring; the earlier 'upstream ships it' belief was wrong)
  measured: 2026-09-01 absent
- roles/system/tasks/nfs_client.yml:49 — Symlink ~/trees to NFS code mount
  shape: force+link
  thing: ~/trees symlink
  check: test -L "$TARGET_HOME/trees"
  fresh-install expectation: absent (permanent config, not a migration: force:true is the ordinary symlink idiom here)
  measured: 2026-09-01 absent
- roles/system/tasks/nfs_client.yml:171 — Remove the superseded autofs ordering drop-ins
  shape: state: absent
  thing: gatherd-tailscaled-ordering.conf
  check: test -e /etc/systemd/system/autofs.service.d/gatherd-tailscaled-ordering.conf
  fresh-install expectation: absent (pure migration: gatherd's own former drop-in)
  measured: 2026-09-01 absent
- roles/system/tasks/nfs_client.yml:171 — Remove the superseded autofs ordering drop-ins
  shape: state: absent
  thing: gatherd-ordering.conf
  check: test -e /etc/systemd/system/autofs.service.d/gatherd-ordering.conf
  fresh-install expectation: absent (pure migration: gatherd's own former drop-in)
  measured: 2026-09-01 absent
- roles/system/tasks/nowayprompt.yml:74 — Remove nowayprompt artifacts from earlier builds
  shape: state: absent
  thing: stale build artifacts
  check: test -d /var/cache/gatherd-nowayprompt
  fresh-install expectation: absent (runtime hygiene: prunes earlier builds, never spent)
  measured: 2026-09-01 absent
- roles/system/tasks/rest.yml:2 — Remove firefox
  shape: state: absent
  thing: firefox package
  check: pacman -Qq firefox >/dev/null 2>&1
  fresh-install expectation: absent (measured 2026-09-01: the Sway edition installs no firefox at all; the earlier 'upstream installs it' belief was wrong)
  measured: 2026-09-01 absent
- roles/system/tasks/rest.yml:11 — Remove polkit-gnome (replaced by our fuzzel polkit agent)
  shape: state: absent
  thing: polkit-gnome package
  check: pacman -Qq polkit-gnome >/dev/null 2>&1
  fresh-install expectation: present (permanent: upstream installs it)
  measured: 2026-09-01 present
- roles/system/tasks/rest.yml:88 — Symlink resolv.conf to stub resolver
  shape: force+link
  thing: /etc/resolv.conf
  check: test -L /etc/resolv.conf
  fresh-install expectation: permanent config, not a migration: force:true is the ordinary symlink idiom here
  measured: 2026-09-01 absent
- roles/system/tasks/sudo.yml:60 — Remove superseded sudo timestamp drop-in
  shape: state: absent
  check: test -e /etc/sudoers.d/gatherd-sudo-timestamp
  fresh-install expectation: absent (pure migration)
  measured: 2026-09-01 absent
- roles/system/tasks/user_path.yml:34 — Remove obsolete profile.d PATH file
  shape: state: absent
  check: test -e /etc/profile.d/gatherd-local-bin.sh
  fresh-install expectation: absent (pure migration)
  measured: 2026-09-01 absent
- roles/system/tasks/user_path.yml:40 — Remove obsolete profile.d Go file
  shape: state: absent
  check: test -e /etc/profile.d/gatherd-go.sh
  fresh-install expectation: absent (pure migration)
  measured: 2026-09-01 absent
- roles/system/tasks/user_path.yml:46 — Remove obsolete environment.d PATH file
  shape: state: absent
  check: test -e /etc/environment.d/10-gatherd-local-bin.conf
  fresh-install expectation: absent (pure migration)
  measured: 2026-09-01 absent
- roles/system/tasks/user_path.yml:52 — Remove obsolete environment.d Go file
  shape: state: absent
  check: test -e /etc/environment.d/10-gatherd-go.conf
  fresh-install expectation: absent (pure migration)
  measured: 2026-09-01 absent
