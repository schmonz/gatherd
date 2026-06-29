# Travel-Repave — North-Star Design

**Type:** Umbrella / program design (north star + sequencing). This spec does **not**
implement anything. It defines the target, the invariants, the design decisions that
fall out of them, and the sub-projects + build order. Each sub-project gets its own
`spec → plan → implementation` cycle and links back here.

**Date:** 2026-06-29
**Status:** Approved design; sub-project specs pending.
**Sources synthesized:** `plans/TODO.md` (Potential work, Secrets, Configurability,
Portability, Setup), `plans/ROBUSTIFY.md`, `plans/CAPTIVE-PORTAL.md`,
`plans/HOSTNAME-LOOKUP.md`, `plans/ARTIX.md`, the Syncthing decision in `TODO.md`.

---

## 1. Target experience

You're at a café or hotel. The only computer you have is this laptop. The network is
whatever's on offer — captive, metered, flaky, or none. You boot gatherd, enter a few
memorized secrets up front (LUKS passphrase, vault password; sign into 1Password when
prompted), and walk away. The machine reconstitutes itself — packages from a USB cache
(and the network if/when usable), personal + per-machine config, credentials, identity,
and your working trees — and lands you at a logged-in, usable Sway desktop. If any
individual task fails, you *still* reach that desktop, with the failure surfaced
(progress view / post-setup-notes), never a black screen or bare TTY.

## 2. Success criteria (the measurable contract)

1. After secret entry, the machine reaches an autologin Sway desktop **unattended** —
   zero interaction.
2. WiFi up from preconfigured networks; working (core) trees present; core CLI/tooling
   functional.
3. `gatherd-post-setup-notes` **accurately** lists the remaining manual GUI sign-ins,
   and that list is **as short as practical**.
4. A **full-offline** repave (no network, ever) still reaches at least a *usable core*
   desktop from the USB stick.
5. **No single task failure** prevents reaching a usable, log-in-able desktop.

## 3. Invariants (the drivers)

- **One machine.** Assume no second device to fetch from mid-repave.
- **Network optional.** Offline-capable by design; a usable core completes with zero
  network from USB; network accelerates and fills extras. Never hard-depend on the
  network; never hang on a captive/metered link. (Full-offline is an aspiration we do
  not design ourselves out of, not a mandate that everything always live on USB.)
- **Few justified secrets.** Minimize memorized secrets; each justified. "No plaintext
  secret at rest" is a goal; no forced single root.
- **Fail-safe everywhere.** A task error never costs a bootable, log-in-able machine —
  applied as an acceptance criterion to *every* step in *every* sub-project, not just
  the robustness floor.
- **Unattended after entry.** No interaction between secret entry and the usable desktop.
- **Soft time bound.** Optimize for fast; no hard number.
- **Init-agnostic where feasible.** Artix/s6 is the eventual target (`ARTIX.md`); prefer
  mechanisms that port.

## 4. Decision log — the choices that fall out of the invariants

Each decision is forced by one or more invariants.

**From "network optional / offline-capable":**

- **D1 — The USB stick is a first-class repave source, not just an accelerant.** It must
  be able to serve packages + AUR builds + ride-along *core trees* + (encrypted)
  secrets/config for the offline-core set. (See D12 for "core trees".)
- **D2 — gatherd prefers the local mirror and degrades gracefully to network, branching
  on run phase.** Local-first pacman/AUR; every network operation has
  timeout + retry + backoff and is **non-fatal** (the Chromebook 100e ~300s curl-hang
  that aborted a Calamares install is the cautionary tale). USB-absent behavior depends
  on the run:
  - **First run** (`/etc/gatherd/complete` absent): the USB offline-core source being
    absent is *significant*. Do not silently fall through to a hostile network — bounded
    wait/retry, and if still absent, require explicit operator acceptance to proceed
    network-only.
  - **Converged runs** (`/etc/gatherd/complete` present): USB absent is the normal case
    → proceed to network sources **instantly**, never wait.
- **D3 — Tier classification is in-band, single-source-of-truth, lint-enforced.** Each
  package/role declares `offline-core` vs `online-extra` at its definition site (never a
  parallel list that drifts). A verify/lint check makes an **unclassified package a hard
  failure**, forcing the tier decision at add-time. The USB-build payload is **derived
  from that metadata**, so it cannot disagree with what gatherd installs offline. Core
  completes offline → the "usable machine" milestone; extras defer to the async/online
  phase (`site-async.yml`).

**From "few justified secrets / no plaintext at rest":**

- **D4 — Secrets entered early, unattended thereafter.** Vault password collected at the
  console before the run (the `systemd-ask-password` mechanism landed this session;
  `openvt` under s6). 1Password sign-in stays interactive but one-time.
- **D5 — No long-lived plaintext vault password on disk** (kernel keyring / systemd
  credential / token-derived). Goal, not a blocker.
- **D6 — Credentials are reconstituted, not hand-copied; disposable per install.** A
  memorized secret unlocks a store that rebuilds SSH/VPN/etc.; per-install rotate/revoke
  bounds blast radius. FIDO2 stays optional (we chose "few secrets", not mandated 2FA).

**From "fail-safe everywhere":**

- **D7 — A failed task degrades, never blocks login.** greetd/multiuser comes up
  regardless; failure is surfaced, not fatal. Also the universal acceptance gate.
- **D8 — Every feature ships with a verify step + idempotency** (per `CLAUDE.md`);
  `gatherd-post-setup-notes` is the living test suite and the "done" contract — accurate
  and short.

**From "one machine / identity / data":**

- **D9 — Everything needed to recover is carriable on your person:** USB stick +
  memorized secrets (+ optional token). No "ssh to my other box for X".
- **D10 — The machine names itself** (online lookup, `HOSTNAME-LOOKUP.md`) **with an
  offline fallback** (local derive from a stable hardware id, or prompt-once, when the
  lookup is unreachable).
- **D11 — The repo carries no me-specific defaults.** Personal/per-machine config
  arrives via USB/network with an early **fail-fast assert** listing every required key
  (Configurability item).
- **D12 — Trees come from Syncthing post-repave; *core trees* ride the USB.** "Core
  trees" = the minimal working trees needed to be productive immediately — at minimum
  **the gatherd repo + dotfiles**, plus any designated active project(s). The full set
  syncs via Syncthing afterward. Which trees are "core" is a **personal designation**
  (lives in personal config, D11), defaulting to gatherd + dotfiles. Repave ordering:
  git bootstrap → gatherd → Syncthing install → sync; core trees do not block on sync.

## 5. Sub-project map & build order (risk-ordered)

Build order is 1 → 6. Each lands independently and leaves the tree shippable.

| # | Sub-project | Charter | Feeds from |
|---|---|---|---|
| 1 | **Robustness floor** | Make any task failure non-fatal to boot/login; establish the fail-safe gate all later work must pass | `ROBUSTIFY.md` |
| 2 | **Offline survival kit** | USB mirror + offline-core/extra split (D3) + local-first pacman/AUR (D2) + captive-portal bootstrap + ride-along core trees (D12) | package-mirror & captive-portal items, `CAPTIVE-PORTAL.md` |
| 3 | **Unattended completion** | Early secret entry (D4, done-ish), self-naming w/ offline fallback (D10), reliable first-autologin cred delivery | vault-early, `HOSTNAME-LOOKUP.md`, VPN-cred item |
| 4 | **Credential lifecycle** | Single-credential bootstrap, no-plaintext-at-rest (D5), per-install rotate/revoke (D6); FIDO2 optional | Secrets section |
| 5 | **Config delivery** | Strip me-specific defaults; personal/per-machine config via USB/network + fail-fast asserts (D11) | Configurability section |
| 6 | **Data source** | NFS→Syncthing as repave/tree source, USB ride-along ordering (D12) | Syncthing decision |

**Rationale for risk-ordering:** you do not run unattended repaves until a failed task
can't strand you — exactly the failure mode this project keeps hitting (this session's
wayvnc/vault failures bricked a pave). Build the net before the trapeze.

## 6. Cross-cutting acceptance criteria (apply to every sub-project, every step)

- **Fail-safe gate (D7):** no step may leave the machine unbootable or unable to reach a
  login. Demonstrated, not assumed.
- **Verify + idempotency (D8):** every shipped feature adds a `section_verify` step in
  `gatherd-post-setup-notes` and is idempotent (second converge = zero changes).
- **Init-agnostic where feasible:** prefer mechanisms that survive the Artix/s6 move;
  isolate the init-coupled piece and note its port (as done for the vault prompt).

## 7. Relationship to existing plans

- **`ROBUSTIFY.md`** → becomes sub-project 1's implementation plan (already drafted).
- **`CAPTIVE-PORTAL.md`** → feeds sub-project 2 (largely executed; latency remainder).
- **`HOSTNAME-LOOKUP.md`** → feeds sub-project 3 (add the offline fallback, D10).
- **Syncthing decision (`TODO.md`)** → sub-project 6's plan; honor the repave-ordering
  caveat (D12).
- **`ARTIX.md`** → owns install-time disk/swap/hibernate correctness and `bootstrap.sh`;
  this umbrella **references** it rather than duplicating it. The init-agnostic invariant
  aligns the two.

## 8. Scope boundary & next step

This spec is the north star and the sequencing decision. It deliberately does **not**
design any sub-project's internals. **Next step:** take sub-project 1 (Robustness floor,
already drafted as `ROBUSTIFY.md`) through `spec → plan` first; subsequent sub-projects
follow in the order above, each refreshing/superseding its source TODO items and linking
back to this document.
