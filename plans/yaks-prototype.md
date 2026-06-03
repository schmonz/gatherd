# What `plans/TODO.md` looks like as a yaks tree (prototype, not wired up)

Scratch artifact to evaluate mattwynne/yaks. Nothing here is installed or committed
to the workflow — this is "what would it feel like." Delete when the decision is made.

Mapping rules I used:
- **Section headers → tags**, not parent yaks. "Hardware" / "Secrets" / "Desktop" are
  *areas*, not goals, so they're `#tags`. Genuine goals-with-prerequisites become
  nesting.
- **Long prose (mechanism / evidence / decision / rejected) → context on the yak**, not
  visible tree nodes. Only the *remaining actions* stay as child yaks. This is the
  biggest change in feel: the tree shows live work; the reasoning lives in `yx show`.
- **"IMPLEMENTED, awaiting validation" → `wip`** (not done — done gets pruned).
- **Real dependencies → `blocked` + a `--blocks` edge**, the thing markdown can't express.

State glyphs below: I use the confirmed markdown format `- [state] name`. The exact
pretty-tree glyph for wip/blocked I haven't run, so I'm showing the format I verified.

---

## The dependency chains (this is where yaks earns its keep)

### Travel-repave is blocked on the package mirror

Today these are two bullets 200 lines apart that say "ties into the item above." As a
real edge:

```
- [todo] Prepare a local package mirror on a USB stick  #repave #network
    ↳ blocks: Travel-repave behind a captive portal
- [blocked] Travel-repave behind a captive portal  #repave #network
    ↳ blocked by: Prepare a local package mirror on a USB stick
  - [todo] Determine whether the portal actually blocks gatherd's package/AUR pulls
  - [todo] Decide how much a repave needs can ride along on the USB stick
- [blocked] arch-update timer on Artix/s6  #portability
    ↳ blocked by: arch-update less interactive (same mechanism gets reworked)
```

### NFS → Syncthing migration: the phase gate

The decision/caveats/rejected-alternatives prose (lines 212–249) all collapses into
context. What's left is the phase ladder, which is a literal dependency chain:

```
- [wip] Migrate code trees off NFS-over-WAN to Syncthing  #nfs #syncthing
    context: decided 2026-06-01; NFS stays as instant rollback until Phase E.
             Caveats (conflicts not LWW, ~few-sec propagation, .stignore, one-git-at-a-time)
             and rejected alts (hardened NFS / AFS / SSHFS-substrate / stacking) in full.
  - [todo]    Phase A — install+harden Syncthing on NAS + machines, share /export/code trees
  - [blocked] Phase B — validate roam/offline/reconnect + conflict behavior   ↳ by: Phase A
  - [blocked] Phase C — validate repave/bootstrap on a VM (riskiest unknown)  ↳ by: Phase A
  - [blocked] Phase D — cut over: local copies primary, stop mounting NFS     ↳ by: Phase B, C
  - [blocked] Phase E — decommission NFS + autofs from gatherd                ↳ by: Phase D
- [wip] NFS mount slow to return after resume (interim; superseded at Phase E)  #nfs
    context: hypothesis = autofs negative-mount cache (negative_timeout 60s). Confirm first.
  - [todo] Confirm cause via verbose `journalctl -u autofs` on next resume
  - [todo] Lower autofs negative_timeout to ~10s
  - [todo] Post-resume warm-up hook (wait for Tailscale, pre-touch ~/trees)
```

---

## Where a giant prose block becomes one wip yak + two real actions

The session-teardown investigation is ~60 lines of markdown. As a yak:

```
- [wip] Logout strands the whole autostart cohort  #session
    context: two compounding causes (KillUserProcesses=no + sway doesn't reap exec
             children → session-N.scope stuck `closing` forever, cohorts stack).
             Chosen fix: single session-lifetime supervisor (gatherd-session-helpers,
             POSIX sh, polls Wayland socket, kills its process group when sway exits) —
             init-agnostic, dodges the tmux tradeoff. Rejected: KillUserProcesses=yes
             (not portable to seatd/s6, elogind #53 ignores it), uwsm/graphical-session
             (systemd-coupled). IMPLEMENTED 2026-06-02, hand-applied to live machine.
  - [todo] Validate through a real logout/login: no session stuck `closing`, cohort
           doesn't stack, supervisor session drains
  - [todo] Fold EndeavourOS default helpers (nm-applet, mako, cliphist, swayidle) into
           the supervisor so the scope fully drains on systemd
```

Compare: in `TODO.md` the "delete this item once validated" instruction is buried in
paragraph 6. Here the only thing standing between this and `done` is one visible child.

Same shape for the two other "implemented-but-unvalidated" items:

```
- [wip] Auto-close captive-browser when connectivity returns to full  #captiveportal
    context: captive-browser doesn't self-close; watcher matches *Connectivity*Full*
             and runs swaymsg kill. Never fired at a real portal (validations ended
             with manual close). Re-test recipe: temporary random MAC on LaPromNyack.
  - [todo] Confirm the full-triggered close fires at the next real portal
- [wip] Slow shutdown ~54s  #shutdown
    context: traced via persistent journal. tmux pane scope ~30s (dominant) > NFS
             umount ~10s > tailscaled log-flush ~10s. "Tailscale 2 min" no longer true.
  - [todo] Bound the tmux per-pane systemd scope (find where it's registered; ~30s)
  - [todo] Force-unmount NFS at shutdown, mirror gatherd-unmount-nfs (~10s)
  - [todo] Suppress tailscaled shutdown log-upload retries / drop stop timeout (~10s)
```

---

## A whole area as a subtree: #secrets

The single-credential goal becomes an umbrella with its prerequisites nested under it,
which is exactly the "discovery tree" framing:

```
- [todo] Single-credential first-run bootstrap (one memorized secret unlocks the rest)  #secrets
  - [todo] Don't leave the vault password in plaintext on disk (keyring / systemd cred / token)
  - [todo] Hardware-token-backed unlock (FIDO2 sk- keys; has_fido2_key probe)
  - [todo] Rotate / revoke credentials per install (disposable per-machine keys)
  - [todo] Materialize file-based secrets via the op CLI (only where a file is unavoidable)
- [todo] Git SSH commit signing via the 1Password agent  #secrets
- [todo] Optionally pre-populate ~/.ssh/known_hosts (derive keys each run, never pin)  #secrets
```

---

## The rest, condensed (flat areas — tags, little nesting)

```
#notes        - [todo] Re-author the lost rclone setup notes
#conveniences - [todo] chsh to zsh as part of provisioning
              - [todo] Install mattwynne/yaks non-interactively (no curl|bash)   ← this evaluation
              - [todo] A cooler tmux status bar
              - [todo] arch-update less interactive (fewer prompts, not full-auto)
              - [todo] An email app (MacSOUP-spirited), preconfigured servers
#hardware     - [todo] Activate clight w/ brightness floor (currently inert by design)
              - [todo] iSight camera: detect + install isight-firmware (AUR)
              - [todo] Expand fingerprint PAM beyond sudo (system-auth; TTY-verify first)
              - [todo] Generalize fingerprint reader support + enrollment control flow
              - [todo] ThinkPad smart card reader (pcscd + opensc; X270 AU9540)
              - [todo] ThinkPad docking (dockd / udev dock-undock events)
#multidisplay - [todo] Multi-display support
                - [todo] Detection (has_multiple_displays)
                - [todo] Layout (output positions, primary)
                - [todo] Scaling across differing DPI
                    ↳ blocks: App menu needs horizontal scrolling
                - [todo] Screen security on resume covers all outputs
#desktop      - [todo] foot light/dark switching (server-mode reconfig problem)
              - [todo] Geolocation via xdg-desktop-portal-gtk
                  ↳ blocks: Auto light/dark mode
              - [blocked] Auto light/dark mode (geolocation or timer)   ↳ by: Geolocation
              - [todo] Lid close: mute + lock + suspend (non-Chromebook)
              - [todo] Hot corners (lower-right lock+sleep; upper-right lock)
              - [todo] More dotfiles without losing system defaults
              - [todo] More systray/waybar indicators (LLM token usage, notifications)
              - [todo] Web app icons hi-res
              - [blocked] App menu horizontal scrolling   ↳ by: Scaling
              - [todo] App menu missing icons for some shipped apps
              - [todo] Decide which Web Apps (iCloud suite, Amazon, Duolingo, Reddit)
              - [todo] Set up VNC (see VNC.md)
              - [todo] JetBrains IDE settings (font size first)
              - [todo] Auto-detect JetBrains account login (allowlist signal, no blocklist)
              - [todo] Auto git pull on a cadence (systemd timer)
              - [todo] Auto-etckeeper-commit per /etc-touching task (no per-task boilerplate)
              - [todo] Script GUI app setup (ydotool/wtype/AT-SPI/DevTools)
#setup        - [todo] Snapshots: snapper vs Timeshift (CLI config)
              - [todo] Swap sized for hibernate
              - [todo] TI calculator AUR packages
#config       - [todo] Personal / per-machine config delivery (drop hardcoded_* placeholders)
```

---

## How you'd actually build a slice of this (the workflow)

```sh
yx add Prepare a local package mirror on a USB stick --tag repave
yx add Travel-repave behind a captive portal --tag repave \
      --context "Does the portal block gatherd's pulls? How much rides on the stick?"
yx add Prepare a local package mirror on a USB stick --blocks Travel-repave behind a captive portal

yx add Migrate code trees off NFS-over-WAN to Syncthing --state wip --tag nfs --context - <<'EOF'
Decided 2026-06-01. NFS stays as instant rollback until Phase E. Conflicts not LWW...
EOF
yx add "Phase A — install+harden Syncthing" --under Migrate code trees off NFS-over-WAN to Syncthing
yx add "Phase B — validate roam/offline + conflict" --under Migrate code trees off NFS-over-WAN to Syncthing
yx add "Phase A — install+harden Syncthing" --blocks "Phase B — validate roam/offline + conflict"
```

Then `yx list --filter not-done` is your TODO; `yx show <yak>` is the buried prose;
`yx done <yak>` prunes it and git log keeps the history — which is *literally* the
"TODO.md is not a record of what was done; git log is" rule from CLAUDE.md, enforced.
