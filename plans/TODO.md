# gatherd backlog (TODO)

> **For agents:** this is the raw backlog and the tracker of *intent* that isn't
> derivable from the code or git log. Designed, in-flight work lives as specs and
> plans under `docs/superpowers/` (indexed below); this file is where ideas start
> and loose ends are recorded. When you finish an item, follow `CLAUDE.md`
> ("Finishing a TODO item"): add a runnable check to `section_verify` in
> `scripts/gatherd-post-setup-notes`, then delete the item here. git log is the
> record of what was done; this file is not.

## Status legend

- `→ planned: <path>` — a written spec/plan exists; execute that, don't freelance.
- `→ DONE` — landed; kept only for context or pending repave-verification.
- `→ blocked: <what>` — waiting on a decision or another item.
- untagged — raw backlog, not yet designed.

## Plans in flight (`docs/superpowers/`)

**Travel-repave program** — north-star spec
`specs/2026-06-29-travel-repave-design.md`. Sub-projects (SP):

| SP | What | Plan / status |
|----|------|---------------|
| 1 | Robustness floor — a task error never blocks boot/login | `plans/2026-06-29-robust-convergence.md` — ready; do Phase 0 first |
| 2 | Offline survival kit (USB cache, captive portal, ride-along trees) | mostly inside SP1 Tasks 3–5; ride-along trees `→ blocked: SP6` |
| 3 | Unattended completion (early secrets, self-naming, VPN cred) | `plans/2026-06-29-self-naming-hostname.md`; vault-early DONE; VPN cred ~done |
| 4 | Credential lifecycle (no-plaintext, rotate/revoke, FIDO2) | unplanned — see **Secrets** below |
| 5 | Config delivery (no me-specific defaults in repo) | unplanned — see **Configurability** below |
| 6 | Data source: NFS→Syncthing | `plans/2026-06-29-syncthing-nfs-pilot.md` — **pilot first; decision NOT settled** |

**Standalone plans:**

| Plan | Status |
|------|--------|
| `plans/2026-06-29-arch-bootstrap-migration.md` — EOS→Arch; owns install-time disk/swap/hibernate | ready; Phase-0 archinstall spike first |
| `plans/2026-06-29-quiet-boot.md` — GRUB quiet (Tier 1), optional Plymouth (Tier 2) | ready |
| `plans/2026-06-29-remmina-vnc-over-ssh-launcher.md` | (separate work) |

## Recently landed (pending repave verification)

- **Early vault-password entry** — now collected on the console before `gatherd`
  via `systemd-ask-password` (the in-session fuzzel box is the fallback). Verify
  on the next repave, then prune this and the old "take the vault password
  earlier" item below. The Artix/s6 `openvt` port is noted in
  `plans/2026-06-29-arch-bootstrap-migration.md` (§Future).

## Backlog (uncategorized)

- **No swap / no hibernate on the Chuwi (check other installs too)**: the
  MiniBook X repave came up with NO swap at all — `/proc/swaps` empty, nothing
  in fstab, no swapfile, no `resume=` on the kernel cmdline — so it cannot
  hibernate, and zswap (now enabled unconditionally) is inert with no backing
  swap to compress into. This is a Calamares install-time outcome (dual-boot
  beside Windows/BitLocker: EFI + MSR + BitLocker + Recovery + one LUKS ext4
  root, no swap carved), and the usual "pick swap big enough to hibernate" step
  didn't take. Decide whether gatherd should ensure a hibernate-sized swap
  rather than rely on the installer: e.g. a swapfile on the LUKS ext4 root sized
  >= RAM, with `resume=UUID` + `resume_offset=` on the cmdline and the `resume`
  hook in the initramfs (the offset must be computed and the initramfs must
  unlock root before resume — the fiddly part). At minimum, detect "no swap" and
  surface it in the post-setup notes so a repave doesn't silently lose hibernate.
  → planned: `arch-bootstrap-migration` (Task 4 now owns install-time disk/swap/
  hibernate — keyfile + crypttab + openswap/resume on a swap partition).
- Can we take the vault password much earlier? We need the LUKS passphrase early
  and it'd be great if we could take the vault password shortly after (maybe from
  GRUB somehow?) so that if it's entered correctly the plays can run to completion
  unattended → **DONE** this session (console `systemd-ask-password` before
  gatherd; see "Recently landed" above). Prune once repave-verified.
- **Sideways GRUB-stage display on the Chuwi MiniBook X (LUKS prompt + GRUB menu)**:
  the kernel cmdline params (`fbcon=rotate:1` + `video=DSI-1:panel_orientation=right_side_up`,
  now applied by `roles/hardware/tasks/rotated_panel.yml`) straighten the tty and
  the Wayland session, but NOT anything drawn before the kernel loads. This box has
  `GRUB_ENABLE_CRYPTODISK=y` with `/boot` inside the LUKS volume (only `/boot/efi`
  is unencrypted), so GRUB does the LUKS unlock itself (`cryptomount`) before it can
  read grub.cfg — the LUKS passphrase prompt AND the boot menu are both GRUB's own
  `gfxterm`, rendering at the firmware's native (sideways) orientation. No kernel
  param, initramfs change, or Plymouth helps; none of that exists yet at GRUB time.
  Realistic options, none great: (a) live with it / hide just the menu
  (`GRUB_TIMEOUT=0` hidden — but you still must SEE the LUKS prompt to type the
  passphrase, so that stays sideways); (b) move `/boot` out of LUKS onto its own
  unencrypted partition and drop `GRUB_ENABLE_CRYPTODISK` — then GRUB reads the
  kernel in the clear (menu still sideways but hideable) and the LUKS prompt moves
  into the initramfs, where `fbcon=rotate:1` (i915 is already force-loaded early via
  `/etc/dracut.conf.d/eos_intel_i915.conf`) or Plymouth WOULD rotate it — at the
  cost of an unencrypted /boot and a repartition/reinstall; (c) patch GRUB's
  gfxterm to rotate (out-of-tree only, not durable). Decide whether a once-per-boot
  sideways prompt is worth any of this. → partial lever: `quiet-boot` Tier 2
  (Plymouth) could rotate the LUKS prompt via `fbcon=rotate:1` **only** under
  option (b) — `/boot` out of LUKS, prompt moved into the initramfs.
- **Pre-configure more known WiFi networks**: Review other machines and add SSID/PSK pairs to the vault
- **chsh to zsh**: make zsh the login shell as part of provisioning.
- **Install mattwynne/yaks non-interactively**: want it installed without
  `curl | bash` and without interactive prompts. Find/derive a scriptable install
  path (clone + run a documented installer step, or package it) for gatherd to drive.
  Decision (2026-06-29): yaks is adopted. Preferred path: **install from the AUR**;
  if nobody has packaged it there yet, **create the AUR package** ourselves, then
  install it like any other AUR package (ties into the offline prebuilt-AUR cache).
- a cooler tmux status bar
- arch-update: can running the update be less interactive? lots of reading and
  agreeing. Dunno if I want full automatic but fewer interactions for sure
- Automate preparing a local package mirror on a USB stick (such as Ventoy),
  for quicker bootstrapping on terrible/absent network
  → planned: `robust-convergence` Phase 4 (offline USB cache); travel-repave SP2.
- **Travel-repave behind a captive portal**: if repaving while on a captive-portal
  network, is there a bootstrap problem that stops the playbooks from completing
  (the portal not yet cleared when gatherd starts pulling packages/AUR)? Determine
  whether it actually blocks, and either way figure out how much of what a repave
  needs can ride along on a USB stick (ties into the package-mirror item above) to
  speed things up and survive a hostile/absent network.
  → planned: `robust-convergence` Phases 3–4 (REST waits for real connectivity +
  offline cache); travel-repave SP2.
- **Try Netsurf as the captive-portal browser**: now that Netsurf is always
  installed (lightweight fallback), see whether the captive-portal flow
  (`gatherd-prompt-captiveportal`) should open the portal in Netsurf instead of
  the default browser — small footprint, fast launch, no profile/session baggage,
  and it keeps the portal's (often sketchy) login page out of the main browser
  profile. Confirm it renders typical captive portals well enough to authenticate.
- **Captive-portal auto-launch — latency remainder** (from the retired
  CAPTIVE-PORTAL.md; Phase 1 portability restructure is DONE — watcher runs from
  sway autostart, no systemd user service; trigger match `*Connectivity*Portal*`
  confirmed correct at a café). What's left is latency (measured join→portal-page
  ~70s): (1) `nmcli monitor` block-buffering fix (`stdbuf -oL nmcli monitor`)
  **applied but not yet verified** — confirm on the next real portal; the watcher
  logs detection time to `~/.cache/captive-browser.log`. (2) ~24s captive-browser
  "Obtaining DHCP DNS" (browser-agnostic mystery) + ~44s navigation through the
  SOCKS5 proxy — still open. Constraints (do NOT): don't disable Tailscale
  `--accept-dns` (breaks the `~/trees` NFS mount — `nfs_server` resolves only via
  MagicDNS); don't touch the tailnet "Override Local DNS" setting (not engaged).
  Optional: version `~/.local/bin/gatherd-debug-captiveportal` into `scripts/`
  (install to `~/.local/bin` — it must be on local disk; at a portal the NFS tree
  is unreachable).
- **Netsurf dark mode (blocked on package version)**: the search provider
  (DuckDuckGo), search-from-URL-bar, and small toolbar icons are now seeded into
  `~/.config/netsurf/Choices` by the desktop role. Dark mode is *not* — the
  "prefer dark mode" core option was merged upstream after the 3.11 release and is
  absent from the installed `netsurf-gtk3` 3.11 (the binary has no dark/scheme
  option key, only CSS color names). Revisit when the package advances past 3.11:
  find the new Choices key (grep the upgraded binary for a dark/scheme option) and
  add it to the same loop. Also decide what else is worth seeding while in there.
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

> Most of this section is **travel-repave SP4 (credential lifecycle)** — see the
> north-star spec `specs/2026-06-29-travel-repave-design.md` (decisions D4–D6).
> It's unplanned; the single-credential bootstrap is its spine. Note D-decisions
> locked: minimize-but-don't-force-one-root, "no plaintext at rest" is a goal,
> FIDO2 stays optional.

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
  → largely **DONE**: `scripts/gatherd-prompt-pia` (cheap "already" probe +
  bounded poll) + `gatherd-pia-login`. The "eats CPU" framing looks stale; verify
  it's moot, then prune. travel-repave SP3.
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
  → travel-repave SP4 / decision D5.
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
  → **NOT settled despite the 2026-06-01 "decided"**: reopened 2026-06-29 for the
  heterogeneous fleet (Mavericks/NetBSD/Windows, where NFS is easy). Being
  validated via a keep-NFS pilot — `plans/2026-06-29-syncthing-nfs-pilot.md`
  (STOP if any of those three can't interoperate). travel-repave SP6; the Decision/
  Migration/Caveats below are the *proposed* design the pilot is gating.
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
- **App menu needs horizontal scrolling**: the detailed app menu almost fills the
  screen and needs a little left-right scrolling to see everything — likely a side
  effect of font-size scaling (see the Scaling item). Figure out whether tuning the
  menu geometry/font or the scaling fixes it so nothing is clipped.
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
  `man clight` or `/usr/share/clight/modules.conf.d/` on a live machine. Once it
  behaves, these become the `section_verify` entry (post-reboot checklist, from
  the retired CLIGHT.md): (1) **dark-room floor** — backlight stays ≥10% instead
  of going to 0; (2) **DPMS recovery** — after a 10-min idle DPMS off, a
  mouse/keypress wakes it normally (no `swaymsg` incantation, since clight now
  starts cleanly); (3) **dimmer** — 60s on battery before dimming, dims to 40%
  not invisibly low. Tuning: if the dark-room floor feels too low, raise the first
  value in `ac_regression_points` (`/etc/clight/modules.conf.d/sensor.conf`) from
  `0.10` toward `0.15`–`0.20`, then `etckeeper commit`.

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

- **IR receiver not detected on the T60**: `machine_facts` finds no `/dev/lirc*`
  or `/sys/class/rc/rc*`, so `has_ir_receiver` stays false and the IR tasks and
  verify steps are skipped. Unclear whether the T60 simply lacks a receiver or
  it's disabled by a hardware/software kill switch or a missing kernel module.
  Probe a live T60: `dmesg | grep -iE 'rc_core|lirc|cir|ir-|infrared'`,
  `rfkill list`, BIOS settings, and whether modprobing the CIR/`rc_core` driver
  surfaces a device. If the T60 has no usable receiver, drop it as the "e.g.
  T60" example in the IR verify steps; if it just needs a module loaded, add it
  to the hardware role gated on the machine.

## Multi-display

- **Detection**: probe connected outputs, set a fact (e.g. `has_multiple_displays`) so tasks can condition on it
- **Layout**: configure output positions in sway (which is primary, relative placement)
- **Scaling**: font size and other size-dependent values (conky, waybar, systray icons) need to make sense across displays that may differ in resolution or DPI — figure out what "going well together" means and automate it
- **Screen security on resume**: verify that at no point after lid-close / sleep / hibernate / lock is the pre-lock screen content visible — confirm swaylock is covering all outputs before the session is unsuspended

## Desktop / UX

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
- **1Password GUI quits when opening its first-run window (T60)**: the systray
  icon appears, but a left-click or the tray context-menu's "open" makes the
  1Password app exit instead of showing the unlock/first-run window. Reproduce on
  the T60: launch `1password` from a terminal and read the stderr/exit code. Old
  hardware suggests a GPU/EGL angle — try `1password --disable-gpu` (or the
  Electron software-rendering flags) and check for a missing keyring/secret-store
  dependency. If a flag fixes it, bake it into how we launch/configure 1Password
  on GPU-poor machines.

## Setup

- **Snapshots**: find CLI equivalent to Welcome-app GUI for Timeshift initial
  config. Decide snapper vs. Timeshift (snapper + pacman hooks?).
- **Swap for hibernate**: size swap partition appropriately; Chromebook may differ.
- **TI calculator AUR packages**: create AUR packages for TI calculator backup
  programs; install here once they exist.
- **Chromebook 100e: `postinstall` timed out (exit 28), failing the Calamares
  install**: confirmed from the install log — `main()` runs
  `setup_sway_community_edition` first, whose bare
  `curl -fsSL .../setup_sway_isomode.bash | bash` (no
  `--connect-timeout`/`--max-time`/`--retry`) hung on the connect phase and
  failed with `curl: (28) Connection timed out after 300609 milliseconds`; with
  `set -euo pipefail` that one fetch aborted the whole install ("Failed to run
  script"). The 100e's install-time network was genuinely flaky — the same log
  shows pacman mirror downloads (intel-ucode, vulkan-intel, libavtp) timing out
  at 10s repeatedly. Fix: give our curl a short `--connect-timeout` plus
  `--retry`/`--retry-all-errors` (and a `--max-time`) so a transient blip
  retries instead of one ~300s hang turning fatal; consider which postinstall
  steps may fail soft vs. must succeed. Re-test on the 100e.

## Portability

> These are the init-coupling loose ends for the eventual Artix/s6 move; context
> in `plans/2026-06-29-arch-bootstrap-migration.md` (§Future) and the travel-repave
> spec's init-agnostic invariant.

- **arch-update timer**: currently a systemd user timer; will need a different
  mechanism on Artix/s6.
- **gatherd-show-slow-progress display loop is systemd-coupled**: the gating is
  now init-agnostic (sentinel file only), but the *display* half still calls
  `journalctl -fn 50 -u gatherd-async.service` to tail and `systemctl is-failed`
  to break on failure. When the async runner moves off systemd (s6, or Sway
  launching it directly), replace these: have `gatherd-await-and-run` tee its
  output to a logfile (e.g. `/var/log/gatherd-async.log`) for the progress
  script to `tail -f`, and write an `async-failed` sentinel on non-zero exit so
  the loop can break without `systemctl`. The runner currently `exec`s
  ansible-playbook, so a failure sentinel needs a trap (drop the final `exec`).

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
  → travel-repave SP5 (config delivery); the early `assert` is decision D11.

## Quality and testing

Live items harvested from the retired REVIEW.md (already-done observations —
the update story via sentinel+git-HEAD+gatherd-needs-run, the git-SHA record,
and `vm/test`'s twice-run `changed=0` check — were dropped as done):

- **Shell-script tests with `bats`**: `bats` is installed but unused. The
  `gatherd-show-slow-progress` logic, the `gatherd-prompt-*` scripts, and the
  systray scripts have real, testable behavior. Add bats tests for them.
- **`become: false` hygiene audit**: some tasks run as root that don't need to.
  Audit which tasks don't need root and set `become: false` explicitly.
- **Extract `machine_facts` as a standalone Galaxy role**: it has zero deps on
  gatherd's packages/config — pure Arch-family hardware detection others would
  want (Pinebook Pro, MacBook on Arch). Candidate to publish.
- **Extract the `gatherd-*` scripts as a separate package / AUR entry**: they're
  a small Sway session utility library (`gatherd-launch-systray`,
  `gatherd-prompt-captiveportal`, …) independently useful to Sway-on-Arch users.
- **Per-phase re-run (tags)**: no tags within phases, so you can't re-run just
  the waybar config or just AUR without the full playbook. Revisit alongside the
  CORE/REST split + converge story (the robust-convergence plan). (Note: CI lint
  enforcement is already covered by that plan's Phase 5.)
- **Doc-quality parity**: `machine_facts` documents *why* per probe; the rest of
  the roles (esp. the long sequential `desktop` role) don't hold that standard —
  hard to tell load-bearing tasks from cosmetic tweaks. Bring them up to par.
