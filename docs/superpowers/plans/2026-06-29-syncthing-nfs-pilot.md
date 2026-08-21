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

**2026-08-21 — the protocol-floor premise is obsolete.** This plan assumed Mavericks would
be stuck on whatever Syncthing release still shipped a 10.9 binary, and that this old
version would pin the whole mesh's protocol. Checked against `../mavericks-golang` and
`../mavericks-tailscale`:

- **Go 1.26.4** runs on 10.9.5, shipped as a self-updating `.pkg`, plus an arm64 cross
  toolchain that targets 10.9 from a modern Mac.
- **`tailscaled` (go1.26.4) joined a real tailnet on 10.9.5** — node `ultimate-hat`,
  `BackendState=Running`, control-plane TLS verified by the baked-in pure-Go keychain-union
  trust, no proxy and no per-binary shim. That is a large Go program doing modern TLS.
- **Linking is already handled transparently:** every on-box `go build` routes through the
  `mavericks-clang` CC wrapper, which injects the legacy-support shim and holds the 10.9
  floor that Go 1.26 would otherwise raise to 12.0.

So a current Syncthing should build, and with every node on a recent version there is no
floor to honour. Three reasons it should be a *strictly easier* port than Tailscale was:

1. **The trust model — the crux of the Tailscale work — barely applies.** Syncthing's
   device-to-device TLS uses self-signed certs pinned by device ID, not the public CA pool.
   With global discovery and relaying off (our conventions above), the only public-TLS
   touchpoints are the upgrade check and crash reporting, both disableable. *Confirm rather
   than assume — this is reasoning about Syncthing's design, not something observed.*
2. **No cgo shim.** Tailscale needed WS3's version-gated `certstore` shim; Syncthing builds
   CGO_ENABLED=0. One whole workstream absent.
3. **The delivery pattern already exists** — signed `.pkg` + Sparkle + LaunchDaemon/LaunchAgent,
   worked out in `mavericks-tailscale`'s standalone-pkg design; reusable for a syncthing
   daemon plus menu-bar.

**Genuinely open, and it feeds Phase 2:** does Syncthing's filesystem watcher (fsnotify →
kqueue on macOS) work on 10.9? If not, Syncthing falls back to periodic full rescans — which
on old hardware over a large tree is exactly the footprint risk Phase 2 measures. Check this
early; it is cheaper to learn here than in Phase 2.

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
- [ ] ~~**Live `.git` — model A (sync the `.git`)**~~ — **struck 2026-08-21, do not test.**
      Upstream has already answered, and testing it risks corrupting a tree to learn something
      documented. A Syncthing lead developer: *"The answer to the topic question 'Can syncthing
      reliably sync local Git repos?' is definitely no."* A moderator: *"I expect that your repo
      will become corrupted almost immediately."* The community recommendation is to ignore any
      directory containing a `.git`.
      <https://forum.syncthing.net/t/can-syncthing-reliably-sync-local-git-repos-not-github/8404>,
      <https://github.com/syncthing/syncthing/issues/7215>
- [ ] **Live `.git` — model B (`.stignore` the `.git`, git via remotes)** — now the only
      candidate: ignore `.git`, each machine keeps its own clone, sync only the working tree.
      **Record:** acceptable to your workflow? ______
  - Confront the awkward part deliberately: our trees *are* git repos, and the received advice
    is "don't sync git repos". Model B stays coherent only under the one-machine-at-a-time-per-tree
    discipline the TODO caveats already impose — with a shared working tree and independent
    `.git`s, a commit on one machine diverges its history from the other's while they keep
    sharing files. Decide this on purpose, do not discover it.

---

## Phase 4 — Cross-platform file semantics (per weird platform)

**Now the top risk for Mavericks** (2026-08-21), with the protocol floor gone — but narrower
than first written here, and only one half of it is real:

- **Case-insensitivity: solved upstream, deprioritize.** Fixed in Syncthing **v1.9.0**;
  it detects the real case on disk and keeps the database consistent with it, with a
  `caseSensitiveFS` option to skip the checks where the FS is known case-sensitive. Residual
  is a genuine `foo`-and-`Foo` collision, which raises a sync *error* to resolve by hand on a
  case-sensitive peer rather than silently overwriting. Friction, not corruption.
  <https://github.com/syncthing/syncthing/wiki/Filesystem-Case-Sensitivity>,
  <https://docs.syncthing.net/advanced/folder-caseSensitiveFS.html>
- **Unicode normalization: unsolved by design, and worse on 10.9 than on a modern Mac.**
  HFS+ normalizes filenames to NFD; Linux stores NFC. Syncthing renormalizes on transfer and
  the maintainers consider that correct, but the observed result is duplicates plus repeated
  `has UTF8 encoding conflict with another file; ignoring`. It does **not** self-resolve —
  you delete the bad duplicates by hand. (`autoNormalize` can be turned off, trading visible
  errors for hidden collisions.) Modern APFS is a "bag of bytes" and does not normalize, so
  Mavericks-on-HFS+ is the worst case in the fleet, and no newer Syncthing build helps: this
  is the filesystem, not the protocol.
  <https://forum.syncthing.net/t/unicode-errors-while-syncing-between-mac-os-x-and-linux/9741>

- [ ] **Cheap pre-check before investing in any of this:**
      `LC_ALL=C find -L ~/trees -name '*[! -~]*'`. Non-ASCII filenames are what trigger the
      normalization pathology; if the trees are ASCII-only, this whole risk is theoretical.
      `LC_ALL=C` is load-bearing — bracket ranges are collation-dependent, so without it a
      UTF-8 locale makes ` -~` match everything and the check silently passes nothing. `-L`
      is too: `~/trees` is a symlink, and plain `find` stops at it. **Record:** non-ASCII
      paths found? ______
      *(Expect `._*` AppleDouble sidecars and `.DS_Store` in the results as ASCII noise —
      they are not normalization risks, but they are real cross-platform grit worth a
      `.stignore` line.)*

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
