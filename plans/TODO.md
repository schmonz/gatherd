# TODO

## Repave workflow

- After each repave, process `~/.config/gatherd-post-setup.md` on the target:
  fold its VERIFIED items into `section_verify` and turn its ANTI-VERIFIED items
  into TODO entries here.

## Recently anti-verified on T60

- Qt theme not dark (QT_QPA_PLATFORMTHEME not set)
- Helium "continue where you left off" not enabled
- ThinkVantage button does not launch anything

## Low-end / constrained machines

The T60 (2GB RAM, spinning rust) is the test rig for the low end — treat anything
here as "must stay usable on a potato."

- **`claude` dumps core on the T60.** Diagnose: likely memory pressure or a
  CPU-feature/arch mismatch. Capture the crash and decide whether it's fixable
  here or belongs upstream.
- **Always install Netsurf.** A lightweight browser constrained machines can fall
  back to.
- **Don't autostart heavy apps on every login.** JetBrains Toolbox, Zoom, Discord,
  and Slack are heavy; launch them on demand. (Original note: "launch it only if
  I'm not logged in and gatherd isn't running. Otherwise I'll run it myself when I
  need to.") Pin down the gating — probably: autostart only during first-run
  provisioning so they can be configured/signed in, then never again.

# 2026/06/04 Regressions

## Font sizing and general display

- 17" MBP maybe didn't get the phantom-display fix
  ...or maybe 7.x kernels are different about this?
  ...or maybe just had to coax convergence to complete?
  I think I was just expecting it on first login -- in which case it needs to
  happen during `postinstall` already. Anything else that belongs that early?
  Worth doing a couple things that early?

## Session env propagation — `environment.d` may not reach greetd's sway

The GL-context regression (LocalSend, 1Password) and the Qt dark-mode env var both
rode `environment.d`, which is consumed by `systemd --user` and may never reach
greetd's directly-exec'd sway cohort. Both moved to proximate delivery — GL var at
the launch point (`gatherd-systray` checks `lspci` itself), Qt var to `pam_env` —
with verify steps in the post-setup notes. Still open:

- **Settle whether `environment.d` reaches greetd's sway at all.** A uniquely-named
  sentinel `GATHERD_ENVIRONMENT_SENTINEL=cheese` is now dropped in
  `environment.d/99-gatherd-env-sentinel.conf`, with a post-setup verify step:
  `printenv` it in a sway child. If empty, `environment.d` is a black hole for the
  session — rip it out everywhere and stop using it. (Dedicated sentinel so the
  test can't be fooled by a var like `SUDO_ASKPASS` that sudo/PAM may scrub.) Once
  the verdict is in, delete the sentinel too.
- **`SUDO_ASKPASS` is the same antipattern (third instance).** Set in
  `environment.d/50-gatherd-askpass.conf`, but nothing proves it reaches the
  session: `gatherd-prompt-vault` works via a hardcoded fallback
  (`${SUDO_ASKPASS:-…/gatherd-askpass}`) and the post-setup test sets it inline, so
  a bare `sudo -A` may well find nothing. Candidate home: `/etc/sudo.conf`
  (`Path askpass /…/gatherd-askpass`), which sudo reads independent of the
  environment. **Open question: is sudo.conf robust against `sudo` package
  updates?** It has no drop-in/include dir (single file). Check on Arch whether the
  package ships `/etc/sudo.conf` and lists it in its pacman `backup` array — if so
  our edits survive upgrades (with `.pacnew` to merge); if it's not shipped at all,
  the file is fully ours. If neither feels safe, fall back to `pam_env` (already
  the proven session-env mechanism here). Either way, drop the `environment.d` file.

## Helium (fixed in code; apply manually to already-repaved machines)

- ~~lost "continue where you left off"~~ — fixed: initial_preferences and
  Default/Preferences seed now use restore_on_startup:5. Manual fix: in
  Helium settings → On startup → Continue where you left off.
- ~~Qt appearance not dark~~ — fixed: QT_QPA_PLATFORMTHEME=xdgdesktopportal
  (Qt 6.7+) reads color-scheme from the XDG settings portal; xdg-desktop-portal-gtk
  now installed with portals.conf routing Settings→gtk, everything else→wlr
  (geolocation stays off). Default/Preferences keeps system_theme:2 (Qt).
  The env var is delivered via `pam_env` (not `environment.d`) so it reaches the
  sway session; the "Qt dark mode portal" verify step confirms it on repave.
- thinks it's managed by my organization -- pre-existing, not a regression

Still open on the T60:

- **"Continue where I left off" still broken** despite the initial_preferences /
  restore_on_startup:5 fix above — reopen and find why the seed isn't taking on a
  fresh repave.
- **Undo Zen and Compact modes** — not ready for them; revert whatever turned them
  on.
- **Tailscale admin tab on first run?** Expected Helium to open a Tailscale admin
  tab; only the 1Password tab appeared. Confirm whether that tab is supposed to
  exist and wire it up, or drop the expectation.

-----

- **chsh to zsh**: make zsh the login shell as part of provisioning.
- **Install mattwynne/yaks non-interactively**: want it installed without
  `curl | bash` and without interactive prompts. Find/derive a scriptable install
  path (clone + run a documented installer step, or package it) for gatherd to drive.
- a cooler tmux status bar
- arch-update: can running the update be less interactive? lots of reading and
  agreeing. Dunno if I want full automatic but fewer interactions for sure
- Automate preparing a local package mirror on a USB stick (such as Ventoy),
  for quicker bootstrapping on terrible/absent network
- **Travel-repave behind a captive portal**: if repaving while on a captive-portal
  network, is there a bootstrap problem that stops the playbooks from completing
  (the portal not yet cleared when gatherd starts pulling packages/AUR)? Determine
  whether it actually blocks, and either way figure out how much of what a repave
  needs can ride along on a USB stick (ties into the package-mirror item above) to
  speed things up and survive a hostile/absent network.
- need an email app. remember I'm the guy that loved MacSOUP. Also gonna want
  to preconfigure it with (explicitly hardwired for now) servers, other settings

## Session teardown

- **Fold the non-gatherd autostart helpers into the supervisor.** `gatherd-session-helpers`
  reaps gatherd's own cohort on logout (validated 2026-06-03), but the EndeavourOS default
  helpers (`nm-applet`, `mako`, the cliphist watchers) and the `swayidle` block still `exec`
  directly from sway, so nothing reaps them. On systemd they keep the old `session-N.scope`
  from fully draining (state `closing`) until they are folded into the supervisor or handled
  separately. Moot on the Artix/s6 (seatd) target, which has no session scope.

## Secrets

- **Single-credential first-run bootstrap**: a repave currently needs secrets
  supplied by several different paths — the Ansible vault password dropped as a
  plaintext `.vault_pass` file (awaited by the `gatherd-vault`/`gatherd-async`
  services), an interactive
  1Password sign-in (login keyring + CLI toggle, see `section_1password`), and
  per-service web logins. Private SSH keys aren't managed at all; only the public
  `authorized_keys` come from the dotfiles repo. Collapse this toward **one
  memorized credential that unlocks the rest**: decide what the root secret is
  (1Password master password? a passphrase that decrypts an in-repo store?) and
  have everything else derive from it. End state: supply one thing you know, run
  gatherd, and the machine reconstitutes its own credentials with no secret files
  copied around by hand.
- **Reliable first-autologin VPN cred delivery**: the initial VPN credentials need
  to land on the first autologin reliably and without eating CPU (the current path
  apparently does something costly). Find a lighter, more dependable delivery
  mechanism — ties into the single-credential bootstrap above.
- **Git SSH commit signing via the 1Password agent**: agent *auth* for git/ssh is
  wired (`roles/desktop/tasks/ssh-agent.yml` sets `IdentityAgent` for github.com;
  the "Use the SSH agent" GUI toggle is a documented post-setup step). Still to do:
  turn on SSH *commit signing* with the same agent-held key — set `gpg.format=ssh`,
  `user.signingkey` to the public key, and `commit.gpgsign=true` in the managed
  `.gitconfig`, and register the key as a GitHub *signing* key (separate from the
  auth key). Boundary unchanged: the agent needs the unlocked desktop app, so it
  serves the *user's* git/ssh only; gatherd's own root-run provisioning stays on
  the bootstrap path above, not the agent.
- **Optionally pre-populate `~/.ssh/known_hosts`** (default stays trust-on-first-use):
  for hosts we hit often (GitHub, the NAS `ap-juicer`, Tailscale nodes), seed
  known_hosts so first connections don't prompt. Must survive key rotation — derive
  the keys from an authenticated source *each run*, never a static pin (a stale
  pinned key makes ssh refuse the rotated one until the repo is fixed): GitHub
  publishes current keys at `https://api.github.com/meta` over TLS; for our own
  hosts, read their `/etc/ssh/*.pub` during provisioning or carry them in the vault.
  Opt-in convenience, not hardening — TOFU is fine by default.
- **Materialize file-based secrets via the `op` CLI**: for secrets that must exist
  as real files on disk (a tool that reads a token from a path, a config that
  can't talk to an agent), use the already-installed 1Password CLI to `op read`
  them into place once signed in, instead of leaving them as manual post-setup
  steps. Narrower than the SSH agent — prefer the agent for SSH keys so nothing is
  written to disk; reserve this for the cases that genuinely need a file. Decide
  which items live in 1Password vs the vault and a deterministic naming/lookup
  scheme so the fetch is scriptable.
- **Don't leave the vault password on disk**: `.vault_pass` sits in plaintext at
  `/usr/local/lib/gatherd/.vault_pass` for the life of the machine (the `.path`
  units only need it to *exist*). Investigate supplying it without a persistent
  plaintext artifact — prompt once and cache in the kernel keyring, pass it as a
  systemd credential, or derive it from a hardware token — then remove the file.
  Keeps a long-lived secret out of the filesystem after first run.
- **Hardware-token-backed unlock (FIDO2)**: fits the existing smart-card and
  fingerprint threads. Support FIDO2 `sk-` SSH keys, and consider a hardware key
  as a second factor for the first-run bootstrap, so that neither possession of
  the disk nor knowledge of a single passphrase is sufficient on its own to
  reconstitute credentials. Probe for a connected key in `machine_facts`
  (`has_fido2_key`) and branch key generation/enrollment accordingly.
- **Rotate / revoke credentials per install**: treat each install's secrets as
  disposable. A machine that's repaved or retired should have its SSH keys and
  per-machine tokens cheaply revocable and reissuable rather than long-lived. Add
  a play (or documented step) that reissues this machine's keys on first run and
  revokes the prior ones from wherever they were trusted. Bounds the blast radius
  of any single install and keeps `authorized_keys`/known-hosts from accumulating
  dead keys.

- **Auto-detect JetBrains account login**: `section_jetbrains` is now "never
  auto-done" (the old `jetbrains_authed` blocklist false-positived because
  Toolbox autostarts and writes assorted `.json` just by running, before any
  login). To prune the reminder automatically again, find an allowlist signal:
  on a live machine, `find ~/.local/share/JetBrains/Toolbox` (and check the
  keyring) before vs after signing into the JetBrains account, diff, and key
  detection on whatever appears only when authed. Don't reintroduce a blocklist.
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
- **NFS over the WAN → migrate to Syncthing (decided 2026-06-01).** Relying on the
  autofs NFS-over-Tailscale mount for code edits is fragile by design: NFS is a LAN
  protocol, and roaming / sleep / captive-portal / Tailscale-bounce events wedge it.
  *Exhibit A:* a Tailscale bounce + café→home roam left the `soft` mount EIO-wedged for
  10+ min; needed `sudo umount -f -l` + `sudo systemctl restart autofs`, and it still
  wouldn't remount with ap-juicer at 4ms (NFSv4 server-side lease/state) — only a reboot
  cleared it.
  - **Decision:** run Syncthing natively (local disk) on the NAS and every machine,
    peer-to-peer over Tailscale. Edits always target a local copy (fast, offline-tolerant,
    never WAN-blocked); changes propagate in seconds when connected. Every tree is a
    Syncthing folder on the NAS (always-on hub/introducer = central store + repave
    source); each machine subscribes to the subset it wants, cold trees on demand. Remove
    NFS + autofs once proven. Keep SSHFS only as a manual poke tool (its no-sudo
    `fusermount -u` recovery is why it wins for that). Harden NAS Syncthing: GUI on
    localhost/Tailscale only, global discovery + relaying off, device IDs pinned to static
    Tailscale addresses.
  - **Caveats:** (1) conflicts, not last-write-wins → `.sync-conflict-*` files; one machine
    at a time per tree, git is the real conflict layer. (2) "immediate" = a few seconds.
    (3) `.stignore` build junk; don't run git on two machines while a live `.git` syncs
    (corruption) — one-at-a-time or use git remotes. (4) repave ordering: gatherd arrives
    via git bootstrap, *then* installs Syncthing, *then* trees sync down (no instant
    mount-everything).
  - **Migration (parallel run; NFS stays as instant rollback until proven):** A) gatherd
    installs+hardens Syncthing on NAS + machines, NAS shares the existing `/export/code`
    trees as folders, NFS untouched. B) validate behavior for a window — edit via the
    local copies; confirm propagation and the exact roam/offline→reconnect case NFS failed
    at, plus `.stignore`, local git/grep/IDE speed, a deliberate conflict. C) validate
    repave/bootstrap (riskiest unknown) on a VM or next real repave. D) cut over: local
    copies primary, stop mounting NFS for daily work. E) decommission NFS + autofs from
    gatherd; SSHFS stays as the manual tool.
  - **Considered & rejected:** hardened NFS (soft→hard + auto-remount watchdog) keeps the
    model but is still a stateful live mount with no offline edit — its auto-remount
    watchdog is worth keeping only as an optional A–C interim safety net. AFS — purpose-
    built but heavy (Kerberos cell, OpenAFS kernel module lags Arch) and weak at
    disconnected *writes* (the roaming case). SSHFS-as-substrate — better mount than NFS
    but still live / no-offline + slow for code; demoted to manual tool. Stacking Syncthing
    on a network mount — anti-pattern (loses inotify → heavy rescans; reinherits the mount
    fragility); Syncthing must run on local disk on every node incl. the NAS.
- **NFS mount slow to return after resume** *(superseded by the Syncthing migration above
  once it reaches Phase E; the autofs `negative_timeout` tuning below stays useful as an
  A–C interim safety net)*: after unlock the `~/trees` NFS mount takes ~1 min to come back. Network
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
- **Web app icons not hi-res enough**: some web apps' icons look blurry/pixelated
  in the Mod-Shift-D application menu. Audit each web app's icon, find higher-
  resolution sources, and install them so they render crisply at the menu's size.
- **App menu needs horizontal scrolling**: the detailed app menu almost fills the
  screen and needs a little left-right scrolling to see everything — likely a side
  effect of font-size scaling (see the Scaling item). Figure out whether tuning the
  menu geometry/font or the scaling fixes it so nothing is clipped.
- **App menu missing icons for some shipped apps**: the short app-menu list is
  missing icons for Text Editor and a few others that shipped with the system
  (distinct from the blurry web-app icons above — these are absent, not low-res).
  Find why their `.desktop`/icon-theme lookup fails and fix it.
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
  Concrete cases waiting on this: the T60 and the Latitude 9330 both have
  sensors — capture their USB IDs and reader families as the next branches.

- **ThinkPad smart card reader**: investigate `pcscd` + `opensc`. T60 has a
  built-in reader; X270 (20HMS6VR00) has Alcor Micro AU9540 (058f:9540), a
  USB CCID-class device — use this to develop the probe and install steps.
  T470 (20JM000BUS) does NOT have one — no USB CCID interface, no PCI smart
  card device.

- **ThinkPad docking**: investigate `dockd` or udev rules for dock/undock events
  (display reconfiguration, power profile switch).

## Multi-display

- **Detection**: probe connected outputs, set a fact (e.g. `has_multiple_displays`) so tasks can condition on it
- **Layout**: configure output positions in sway (which is primary, relative placement)
- **Scaling**: font size and other size-dependent values (conky, waybar, systray icons) need to make sense across displays that may differ in resolution or DPI — figure out what "going well together" means and automate it
- **Screen security on resume**: verify that at no point after lid-close / sleep / hibernate / lock is the pre-lock screen content visible — confirm swaylock is covering all outputs before the session is unsuspended

## Desktop / UX

- **fuzzel for polkit prompts**: the vault and sudo prompts already use fuzzel and
  it's great — extend the same treatment to the polkit agent prompts.
- **"Reboot to UEFI" power-menu entry shows on BIOS-only machines**: the T60 is
  BIOS-only, so it can't reboot to UEFI firmware setup — yet the power menu still
  offers the entry. Gate it on the machine actually being UEFI (`/sys/firmware/efi`
  present), so it's hidden on legacy-BIOS boxes. Likely a Sway CE PR.
- **Chromebook gtklock on lid-open isn't a faithful resume**: opening the lid
  lights the screen via gtklock but doesn't land on the password prompt, so it
  doesn't quite mimic real suspend/resume. Make lid-open present the lock prompt.
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

- **WiFi reconnect blip on re-run**: gatherd pushes a network config for the SSID
  you're already connected to, which bounces the connection. Diff the existing vs
  pushed config — if they're equivalent, make the task idempotent (skip the write,
  don't trigger a reconnect) so re-running gatherd on the active network doesn't
  blip it.
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
