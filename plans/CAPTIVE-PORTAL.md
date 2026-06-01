# Captive portal: reliable captive-browser auto-launch (and make the trigger init-agnostic)

> Plan for a fresh agent. Self-contained. Read "Diagnosis status" before writing any code.

## Status (2026-06-01) — café trip resolved the open questions; live tracker is plans/TODO.md

This plan is largely **executed**. The facts below supersede the Phase 1/Phase 2 framing
further down (kept as historical record):

- **Phase 1 DONE.** Watcher moved off the systemd `--user` service onto sway autostart. The
  original "never pops" root cause: the user-service env had no `WAYLAND_DISPLAY`/`SWAYSOCK`,
  so the Wayland GUI it spawned had no display. Autostart inherits the session env.
- **Phase 2 question ANSWERED — no trigger-condition change needed.** At the café,
  `nmcli networking connectivity` = **`portal`**, so the existing `*Connectivity*Portal*`
  match was right all along. The failure was never the match condition.
- **The real remaining problem is latency, not the trigger** (measured join→portal-page ~70s):
  - **nmcli monitor buffering (~100s, the worst offender).** `nmcli monitor`'s piped stdout
    block-buffers, so a lone "Connectivity is now 'portal'" line sat unflushed until a later
    event filled the 4KB buffer. Fixed with `stdbuf -oL nmcli monitor` — **applied but NOT yet
    verified** (the flap test flooded >4KB and flushed regardless, so it didn't isolate the
    fix; confirm on the next real portal — the watcher now logs detection time to
    `~/.cache/captive-browser.log`).
  - **~24s captive-browser "Obtaining DHCP DNS"** (mystery, browser-agnostic) **+ ~44s
    navigation through the SOCKS5 proxy on the captured net.** NOT helium cold-start — plain
    helium windows in ~2.9s. Still open.
- **HTTPS-First "site is not secure" modal — FIXED:** `captive-browser.toml` now disables
  `HttpsUpgrades,HttpsFirstBalancedMode,HttpsFirstModeV2,HttpsFirstModeIncognito` and the
  captive profile seeds `https_only_mode_enabled=false`.
- **`gatherd-debug-captiveportal` recreated** on local disk (still not versioned).
- **Authoritative live status + next steps now live in `plans/TODO.md`** ("Captive portal
  auto-launch — corrected status"). The sections below are the original plan.

## Problem

On captive-portal wifi (e.g. `LaPromNyack`), `captive-browser` does **not** auto-launch.
The user has to manually open a browser to `http://whatsmyip.schmonz.com` to reach the
portal page and complete the connection.

## How it works today

- `scripts/gatherd-prompt-captiveportal` — POSIX sh watcher: runs `nmcli monitor` and,
  on a line matching `*Connectivity*Portal*`, launches `captive-browser` (guarded by `pgrep`).
- `services/user/gatherd-prompt-captiveportal.service` — a **systemd user service**
  (`Restart=always`, `WantedBy=default.target`) that runs the watcher.
- Wiring in `roles/desktop/tasks/main.yml`:
  - Tasks **"Install gatherd user service units"** + **"Enable gatherd user services"**
    install/enable the service. These two loops currently contain **only** this one
    service, and both already carry the comment "systemd-specific; will need a different
    mechanism on Artix/s6".
  - Task **"Install gatherd-prompt-captiveportal script"** installs the watcher to `~/.local/bin/`.
  - Task **"Remove autostart entries now managed as systemd user services"** currently
    *removes* `exec gatherd-prompt-captiveportal` from sway autostart (leftover from when
    it was migrated sway-exec -> systemd unit).
  - Task **"Configure captive-browser to use Ungoogled Chromium"** writes
    `~/.config/captive-browser.toml`. Note: captive-browser derives `dhcp-dns` from the
    wifi link and proxies DNS through it, so captive-browser itself is robust to
    system-resolver state — **the weak link is only the trigger**, not captive-browser.

## Diagnosis status — READ BEFORE CODING (assessed 2026-05-28)

The root cause of the auto-launch failure is **NOT yet confirmed.** Do not assume one.

- A hypothesis was **disproven**: "Tailscale pushes a global Quad9 DNS override that breaks
  NM's connectivity probe." `tailscale dns status` shows the tailnet pushes **no global
  resolver** — only the MagicDNS suffix `taile54b91.ts.net` and a split route for `ts.net.`.
  The Quad9 (`9.9.9.9`) seen in `resolvectl` is systemd-resolved's compiled-in `FallbackDNS`,
  used only when no link DNS exists. General lookups go to the link's DHCP DNS, which a
  portal normally answers — so by this corrected model NM *should* detect the portal, yet it
  didn't. Cause genuinely unknown.
- The decisive missing datum: what `nmcli networking connectivity` reports **while on the
  portal** (`portal` / `limited` / `none` / `full`). A diagnostic script
  `~/.local/bin/gatherd-debug-captiveportal` (local disk, NOT in the repo) captures this plus
  DNS/HTTP/gateway probes. It must be run at the portal, before manually working around it.
- **Do NOT disable Tailscale `--accept-dns`.** `nfs_server = ap-juicer.taile54b91.ts.net`
  (group_vars/all/main.yml) resolves **only** via Tailscale MagicDNS (verified: router DNS
  returns nothing; `100.100.100.100` returns `100.66.57.125`). Disabling accept-dns breaks
  the `~/trees` autofs mount.
- **Do NOT pursue the tailnet "Override Local DNS" admin setting.** It is not engaged
  (no global resolver pushed), so it changes nothing here.

## Two orthogonal workstreams

1. **Portability restructure (Phase 1, this plan's main deliverable).** Move the trigger off
   the systemd user service onto an init-agnostic mechanism. Implementable and validatable
   now; does not depend on café data. Does **not** by itself fix the portal bug — it is the
   portable container.
2. **Trigger-condition fix (Phase 2).** Correct *which* NM state launches captive-browser.
   Blocked on café data.

## Chosen approach (and the rejected alternative)

**Approach B — session watcher launched from sway autostart.** Replace the systemd user
service with an `exec gatherd-prompt-captiveportal` line in sway autostart, and add an
internal self-restart loop to the script (to replace systemd `Restart=always`).

- Why: the binding constraint is "launch a Wayland GUI (`captive-browser`) in the user's
  graphical session." A session-launched watcher gets that for free, and depends only on
  sway + nmcli — neither tied to systemd — so it runs unchanged under Artix/s6.
- **Rejected: NM `dispatcher.d`** (`connectivity-change` -> `CONNECTIVITY_STATE`). Cleaner
  signal (an enum instead of text-scraping), but dispatcher scripts run as **root with no
  graphical session env**, making the Wayland GUI launch fragile (would need
  XDG_RUNTIME_DIR/WAYLAND_DISPLAY/DBUS plumbing or a session-side helper). Not worth it here.

## Phase 1 — portability restructure (do now; no café data needed)

1. `scripts/gatherd-prompt-captiveportal`: wrap the existing `nmcli monitor | while …`
   pipeline in an outer self-restart loop so the watcher respawns if `nmcli monitor` exits
   (replaces systemd `Restart=always`). Keep POSIX sh. **Do not change the match pattern in
   this phase** (that's Phase 2). Target shape:
   ```sh
   #!/bin/sh
   # Watches NM connectivity; launches captive-browser on portal detection.
   # Self-restarting: runs from sway autostart, not a supervised unit.
   while :; do
       LC_ALL=C nmcli monitor 2>/dev/null | while IFS= read -r line; do
           case "$line" in
               *[Cc]onnectivity*[Pp]ortal*)
                   pgrep -x captive-browser >/dev/null || captive-browser &
                   ;;
           esac
       done
       sleep 1
   done
   ```

2. `roles/desktop/tasks/main.yml`:
   - Remove the **"Install gatherd user service units"** and **"Enable gatherd user
     services"** tasks. They contain only `gatherd-prompt-captiveportal.service`; with it
     gone they are dead. (This removes the repo's only systemd user service — intended for
     the Artix/s6 goal.)
   - In **"Remove autostart entries now managed as systemd user services"**, drop the
     `gatherd-prompt-captiveportal` loop item. If that empties the loop, remove the whole task.
   - In **"Add gatherd script autostart entries"** (the loop that writes
     `exec ~/.local/bin/<item>`), add `gatherd-prompt-captiveportal` to the list.
   - Leave **"Install gatherd-prompt-captiveportal script"** unchanged.

3. Delete `services/user/gatherd-prompt-captiveportal.service`.

4. Run `ansible-lint` (config: `.ansible-lint`); resolve findings (prefer fixing over `noqa`).

### Phase 1 validation (local)
- Apply on a live machine (full playbook, or hand-apply: add the sway autostart `exec`,
  remove + disable the user unit, then start the script in-session).
- Respawn check: `pkill -f "nmcli monitor"`; confirm the wrapper respawns it
  (`pgrep -f gatherd-prompt-captiveportal` persists; a new `nmcli monitor` child appears).
- No systemd user service remains: `systemctl --user list-unit-files | grep captiveportal`
  returns nothing.
- Sanity: confirm `~/.config/sway/config.d/autostart_applications` has
  `exec …/gatherd-prompt-captiveportal` and no leftover removal.

## Phase 2 — trigger-condition fix (BLOCKED on café data; do not guess)

Get the café snapshot first: have the user run `gatherd-debug-captiveportal` at the portal,
then branch on `nmcli networking connectivity`:

- **`portal`** -> the existing `*Connectivity*Portal*` match is correct in principle; the
  failure was elsewhere (most likely the watcher wasn't actually firing in-session). Phase 1
  alone probably fixes it. Confirm, then stop.
- **`limited`** (or `none`) -> broaden the `case` to also match it, e.g. add
  `*[Cc]onnectivity*[Ll]imited*`. Tradeoff: may also launch captive-browser on genuinely
  internet-less wifi; the `pgrep` guard limits dupes and a stray window is easy to close.
- **`full`, or NM never probes** -> no connectivity-state trigger can help. Switch to an
  **active probe**: on wifi-up, fetch a check URL through the link's DHCP DNS (mirror
  captive-browser's `dhcp-dns` logic) and launch captive-browser on a redirect/portal
  response. Separate design — revisit then.

### Phase 2 local validation (optional, before café)
Simulate portal states by overriding NM's connectivity check: drop
`/etc/NetworkManager/conf.d/99-debug-connectivity.conf` with `[connectivity] uri=` pointing
at a URL that 302-redirects (-> NM reports `portal`) or an unreachable host (-> `limited`);
`nmcli general reload`; toggle wifi; observe `nmcli networking connectivity` and whether
captive-browser launches. **Revert the drop-in afterward.**

## Files touched (Phase 1)
- `scripts/gatherd-prompt-captiveportal` — add self-restart loop
- `roles/desktop/tasks/main.yml` — drop 2 user-service tasks; move autostart item into the
  "Add gatherd script autostart entries" loop
- `services/user/gatherd-prompt-captiveportal.service` — delete

## Out of scope / do not do
- Do not disable Tailscale accept-dns (breaks NFS `~/trees`).
- Do not change the tailnet "Override Local DNS" setting (not engaged; no effect).
- Do not use NM `dispatcher.d` to launch the GUI (root / no-session problem).
- Do not land Phase 2 until café data confirms which NM state to match.

## Optional follow-up
`~/.local/bin/gatherd-debug-captiveportal` is currently local-only. If worth versioning, add
it to `scripts/` and install via the playbook **to `~/.local/bin`** (it must live on local
disk — at a portal the NFS tree is unreachable because Tailscale is down).
