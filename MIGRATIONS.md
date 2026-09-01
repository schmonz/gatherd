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
- roles/desktop/tasks/core.yml:40 — Remove obsolete per-user gatherd-askpass
  shape: state: absent
- roles/desktop/tasks/core.yml:45 — Remove obsolete environment.d askpass file
  shape: state: absent
- roles/desktop/tasks/core.yml:50 — Remove obsolete environment.d sentinel file
  shape: state: absent
- roles/desktop/tasks/core.yml:79 — Remove stock swayidle entries superseded by our configuration
  shape: state: absent
- roles/desktop/tasks/core.yml:104 — Remove EndeavourOS's polkit-gnome agent from sway autostart
  shape: state: absent
- roles/desktop/tasks/core.yml:110 — Remove the now-orphaned polkit autostart comment
  shape: state: absent
- roles/desktop/tasks/core.yml:166 — Remove network throughput widget from waybar center
  shape: state: absent
- roles/desktop/tasks/core.yml:403 — Remove vestigial Chromium browser config
  shape: state: absent
- roles/desktop/tasks/core.yml:687 — Remove the obsolete ssh host-key float rule
  shape: state: absent
- roles/desktop/tasks/core.yml:833 — Remove sway-install.sh stray gparted desktop entry
  shape: state: absent
- roles/desktop/tasks/core.yml:838 — Remove obsolete gnome-keyring --unlock autostart lines
  shape: state: absent
- roles/desktop/tasks/core.yml:844 — Remove obsolete systray autostart entries
  shape: state: absent
- roles/desktop/tasks/core.yml:867 — Remove per-helper autostart entries now launched by the session supervisor
  shape: state: absent
- roles/desktop/tasks/tablet_mode.yml:52 — Unbind the old tablet mode and music stand keystrokes in sway
  shape: state: absent
- roles/desktop/tasks/tablet_mode_upstream.yml:49 — Link the hinge-sensor udev rule
  shape: force+link
- roles/desktop/tasks/vesktop.yml:57 — Discard the truncated Vencord bundle so Vesktop refetches it
  shape: state: absent
- roles/desktop/tasks/vesktop_vencord.yml:57 — Discard whatever incomplete bundle is there
  shape: state: absent
- roles/desktop/tasks/vesktop_vencord.yml:116 — Leave no partial bundle behind for Vesktop to trust
  shape: state: absent
- roles/desktop/tasks/wallpaper.yml:65 — Remove EndeavourOS wallpaper leftovers
  shape: state: absent
- roles/hardware/tasks/ambient_light.yml:58 — Disable clightd service
  shape: unit off
- roles/hardware/tasks/ambient_light.yml:64 — Remove clight from sway autostart
  shape: state: absent
- roles/system/tasks/aurutils.yml:51 — Clear a stale repository lock left by a killed build
  shape: state: absent
- roles/system/tasks/aurutils.yml:63 — Repair the repository database symlinks
  shape: force+link
- roles/system/tasks/aurutils.yml:148 — Remove aurutils artifacts from earlier builds
  shape: state: absent
- roles/system/tasks/core.yml:15 — Symlink resolv.conf to stub resolver
  shape: force+link
- roles/system/tasks/core.yml:159 — Remove EOS default logind suspend drop-in
  shape: state: absent
- roles/system/tasks/core.yml:177 — Mask sleep targets
  shape: unit off
- roles/system/tasks/core.yml:267 — Mask services that conflict with TLP
  shape: unit off
- roles/system/tasks/core.yml:290 — Remove obsolete gatherd path units
  shape: unit off
- roles/system/tasks/core.yml:301 — Delete obsolete gatherd path unit links
  shape: state: absent
- roles/system/tasks/core.yml:366 — Remove gnome-keyring PAM auth line (starts --login daemon with autologin, locking keyring with unknown password)
  shape: state: absent
- roles/system/tasks/nfs_client.yml:49 — Symlink ~/trees to NFS code mount
  shape: force+link
- roles/system/tasks/nfs_client.yml:171 — Remove the superseded autofs ordering drop-ins
  shape: state: absent
- roles/system/tasks/nowayprompt.yml:74 — Remove nowayprompt artifacts from earlier builds
  shape: state: absent
- roles/system/tasks/rest.yml:2 — Remove firefox
  shape: state: absent
- roles/system/tasks/rest.yml:11 — Remove polkit-gnome (replaced by our fuzzel polkit agent)
  shape: state: absent
- roles/system/tasks/rest.yml:88 — Symlink resolv.conf to stub resolver
  shape: force+link
- roles/system/tasks/sudo.yml:60 — Remove superseded sudo timestamp drop-in
  shape: state: absent
- roles/system/tasks/user_path.yml:34 — Remove obsolete profile.d PATH file
  shape: state: absent
- roles/system/tasks/user_path.yml:40 — Remove obsolete profile.d Go file
  shape: state: absent
- roles/system/tasks/user_path.yml:46 — Remove obsolete environment.d PATH file
  shape: state: absent
- roles/system/tasks/user_path.yml:52 — Remove obsolete environment.d Go file
  shape: state: absent
