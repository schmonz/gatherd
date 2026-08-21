# Syncthing-vs-NFS Decision Pilot

> **Human-executed validation protocol** (not an agent coding plan). The output is a
> recorded **GO/NO-GO** on replacing NFS-over-WAN with Syncthing for shared source
> trees across the heterogeneous fleet. Steps use checkboxes; fill in the **Result**
> lines as you go.

**Goal:** Decide, from evidence, whether Syncthing convincingly replaces NFS as
"shared source trees across machines" — near-synchronous when connected, tolerable
when not — across the whole fleet, **without** committing to it or touching NFS.

**Parent:** sub-project 6 of `docs/superpowers/specs/2026-06-29-travel-repave-design.md`.
Reopens the `plans/TODO.md` "decided 2026-06-01" Syncthing entry (see memory
`syncthing-decision-not-settled`). Blocks SP2's ride-along-core-trees piece until resolved.

## Non-negotiable guardrails

- **NFS stays untouched** — source of truth and instant rollback for the whole pilot.
  Do not point real work at Syncthing until (and unless) the gate passes.
- **Pilot folder = a *copy* of one active tree**, on a separate path, not your live
  NFS-mounted tree. A conflict or delete mishap during the pilot must not touch real work.
- **No gatherd/Ansible automation in the pilot.** Everything is manual, on purpose —
  the point is to learn the cross-platform reality before deciding what to automate.

## Decision gate (the kill criteria — read first)

- **STOP / NO-GO if ANY of Mavericks, Windows, or NetBSD cannot interoperate** with the
  mesh (join, round-trip a file both directions, stay compatible). Fleet-wide is the
  whole value; losing any platform → keep NFS. *(2026-08-21: much likelier to pass than
  when written — see the Mavericks note in Phase 1. The binding risk has moved to
  Phase 4.)*
- **STOP / NO-GO if** any weird platform mangles source trees (perms/symlinks/case/charset
  corruption), **or** live-`.git` is unworkable *and* the `.stignore`-the-`.git` model is
  unacceptable to your workflow.
- **GO if** all three weird platforms interoperate; connected sync ≈ seconds; the
  offline/roam reconnect never wedges (clear NFS win); conflicts are rare and
  git-recoverable; cross-platform semantics are acceptable everywhere.
- On **GO** → spec the full migration + the SP2 ride-along. On **NO-GO** → keep NFS, nothing lost.

## Nodes

- **Hub** (always-on introducer): the NAS (`ap-juicer`) if it runs Syncthing easily;
  otherwise keep this Arch laptop up as the hub for the pilot. Platform-of-NAS decision
  is **not** needed to run the pilot.
- **Clients:** this Arch laptop + the three weird platforms — **Mavericks, Windows, NetBSD.**

## Shared conventions (set on every node — the contract in miniature)

- GUI/web bound to **localhost or Tailscale address only** (never 0.0.0.0).
- **Global discovery OFF, relaying OFF.** Add devices by **static Tailscale address** only.
- One shared folder (the pilot folder), same **Folder ID** on every node.
- **File versioning ON** (Simple, a few versions) so an accidental `rm` that propagates is recoverable.
- A `.stignore` covering build junk (`node_modules`, `target`, `.venv`, `*.o`, etc.).

---

## Phase 0 — Stand up the hub and the pilot folder

- [ ] **Install Syncthing on the hub** and apply the shared conventions above.
  - Arch hub: `sudo pacman -S syncthing`; run as your user (`systemctl --user enable --now syncthing` or `syncthing serve`).
  - Appliance NAS: enable its Syncthing app/package; set the GUI bind + discovery/relay off in its UI.
- [ ] **Create the pilot folder** from a copy of one active tree:

```sh
# on the hub (adjust the source tree):
cp -a ~/trees/<some-active-tree> ~/syncthing-pilot/<some-active-tree>
```
- [ ] Add `~/syncthing-pilot` as a Syncthing folder; note its **Folder ID**.
- [ ] Add a `.stignore` with build-junk patterns.
- [ ] **Record:** hub platform + Syncthing version: ____________________

---

## Phase 1 — INTEROP GATE (all three weird platforms — the kill switch)

Do this for **each** of Mavericks, Windows, NetBSD **before** any deeper testing. If any
one fails, **STOP and record NO-GO** — do not continue.

### Mavericks

**2026-08-21 — the protocol-floor premise is obsolete.** This plan was written assuming
Mavericks would be stuck on whatever Syncthing release still shipped a 10.9 binary, and
that this old version would pin the whole mesh to its protocol. ModernMavericks now
provides golang on 10.9 plus latest-version tools built from it — Tailscale among them,
which is a large Go program leaning on modern TLS and networking, so Syncthing (Go, and
a smaller ask) should build current too. Ship a current build and there is no floor: every
node runs a recent Syncthing and no protocol compatibility question arises. Verify rather
than assume, but expect this to pass.

- [ ] Build/install a **current** Syncthing from the ModernMavericks golang toolchain. Record the version.
- [ ] Connect it to the hub by static Tailscale address; share the pilot folder (same Folder ID).
- [ ] **Round-trip test:** create `mavericks.txt` on Mavericks → appears on the hub; edit a file on the hub → change reaches Mavericks.
- [ ] **Record:** Mavericks Syncthing version ______; matches the other nodes (no floor to honour)? **PASS / FAIL** ______
  - Only if a current build turns out NOT to be possible does the old floor logic apply:
    note the newest workable version, and every other node must stay compatible with it: ______
  - If ModernMavericks is pkgsrc-flavoured, check whether the same `net/syncthing` package
    serves NetBSD too — that would collapse two of the three install stories into one.

### Windows

- [ ] Install official Syncthing (or SyncTrayzor). Apply conventions; connect by Tailscale address; share the folder.
- [ ] Round-trip test both directions.
- [ ] **Record:** Windows interoperates (incl. with the Mavericks-floor version)? **PASS / FAIL** ______

### NetBSD

- [ ] Install via pkgsrc (`pkgin install syncthing` or build `net/syncthing`); set up an rc.d service. Apply conventions; connect; share the folder.
- [ ] Round-trip test both directions.
- [ ] **Record:** NetBSD interoperates? **PASS / FAIL** ______

- [ ] **GATE:** all three PASS? If **no → STOP, record NO-GO and why.** If yes → continue.

---

## Phase 2 — The NFS-killer UX (does it beat NFS where NFS hurts?)

- [ ] **Connected latency:** edit a file on the laptop → time its appearance on the hub and one weird platform. **Record:** ____ s (expect single-digit seconds).
- [ ] **Offline / roam reconnect (the case NFS wedges on):** disconnect a node (or roam café→home / bounce Tailscale), edit offline on two nodes, reconnect.
  - [ ] **Record:** did it reconcile cleanly with **no wedge** (vs the `soft` NFS EIO hang that needed `umount -f -l` + reboot)? **PASS / FAIL** ______
- [ ] **Footprint:** observe CPU/disk/rescan on the **old Mavericks hardware** and NetBSD over a day. **Record:** acceptable? ______

---

## Phase 3 — Conflict & git semantics (does it stay "shared trees"?)

- [ ] **Deliberate same-file conflict:** edit the same file on two nodes with one offline; reconnect.
  - [ ] **Record:** `.sync-conflict-*` appears, is git-recoverable, not maddening? **PASS / FAIL** ______
- [ ] **Live `.git` — model A (sync the `.git`):** run `git status`/commits on two machines against the synced `.git`; watch for index churn / corruption over a few cycles. **Record:** safe? ______
- [ ] **Live `.git` — model B (`.stignore` the `.git`, git via remotes):** ignore `.git` in the pilot folder; use normal git remotes; sync only the working tree. **Record:** acceptable to your workflow? ______
- [ ] **Decide the git model** (A or B) for a real deployment. **Record:** ______

---

## Phase 4 — Cross-platform file semantics (per weird platform)

**Now the top risk for Mavericks** (2026-08-21), with the protocol floor gone. HFS+ on 10.9
is case-insensitive and normalizes filenames to NFD, while Linux stores NFC — a long-standing
source of Syncthing churn (files that look perpetually renamed, conflict loops on
case-colliding paths). Windows shares the case-insensitivity half. Nothing about a newer
Syncthing build fixes either; test both deliberately.

For **each** of Mavericks / Windows / NetBSD, round-trip a tree containing edge cases and record what breaks:

- [ ] **Permissions/modes** (executable bits) survive? ______
- [ ] **Symlinks** handled or mangled? ______
- [ ] **Case collisions** (`File.txt` vs `file.txt`) — behavior on case-insensitive macOS/Windows? ______
- [ ] **Line endings / filename charset** (unicode, spaces) round-trip? ______
- [ ] **Record per platform:** acceptable / mangles trees? **PASS / FAIL** ______

---

## Phase 5 — Record the decision

- [ ] Tally the gate: interop (Phase 1), NFS-killer UX (Phase 2), conflict/git (Phase 3), semantics (Phase 4).
- [ ] **Write the GO/NO-GO** here with the evidence, and update `plans/TODO.md` (replace the stale "decided 2026-06-01" line with the real, evidence-backed decision and date).
- [ ] **On GO:** tear down nothing yet; proceed to spec the full migration (Phases A–E from the TODO entry) + the SP2 ride-along-core-trees design. NFS stays until that migration's own cutover.
- [ ] **On NO-GO:** remove the pilot folders; keep NFS; record what killed it so it isn't re-litigated blind.

**Decision:** ______________________  **Date:** __________
