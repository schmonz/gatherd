# iCloud Drive Sync — Design

**Type:** Feature design. Generalizes the hand-rolled `~/.local/bin/fsnotes-sync`
into a gatherd-managed, fleet-wide iCloud Drive sync.

**Date:** 2026-08-10
**Status:** Approved design; implementation plan pending.
**Related:** `specs/2026-06-29-travel-repave-design.md` (SP3 unattended completion,
SP4 credential lifecycle) — this retires the standing `rclone config` manual step.

---

## 1. Problem

Today gatherd's entire iCloud story is a post-setup nag: *"run `rclone config` and
follow prompts to add a remote named `icloud`; complete 2FA when prompted."* Syncing
is a hand-written one-liner, `~/.local/bin/fsnotes-sync`, that exists on one machine,
covers one folder, is untracked by the playbook, and is run by hand.

**Already done by hand** (as of 2026-08-10, on this machine only): `rclone.conf` is
encrypted, the password lives at `op://Private/rclone config/password`, and
`RCLONE_PASSWORD_COMMAND` is exported from `~/.bashrc`. §4.3 and §5 therefore describe
partly-existing state, not greenfield work — see the notes there.

Three gaps:

1. **No first-run help.** Establishing the local copy means knowing to run
   `rclone bisync --resync` and understanding what it does to a populated directory.
2. **One folder only.** iCloud Drive holds more than FSNotes.
3. **Once per machine.** Every repave means another interactive `rclone config` + 2FA,
   which is exactly the class of manual step the travel-repave program exists to kill.

## 2. Target experience

On a fresh machine: sign into 1Password (already the first standing manual step, and
already required by Tailscale and PIA). Shortly after, the iCloud config arrives on its
own, the declared folders populate, and no one types a 2FA code. Thereafter, unlocking
the screen syncs in the background, silently unless a human decision is required.

Interactive steps, total: **one per fleet, ever** — the initial `bootstrap`.

## 3. Decisions

| # | Decision | Rejected alternative |
|---|---|---|
| D1 | Declared per-folder list; each folder its own bisync pair under a common root | One whole-drive `icloud:` ↔ `~/iCloud` mirror |
| D2 | Local root `~/Documents/iCloud/<Folder>`, iCloud folder names preserved | `~/notes` and other bespoke paths |
| D3 | Automatic `--resync` **only into a missing-or-empty** local dir; explicit `--init` otherwise | Never automatic; or always automatic |
| D4 | `rclone.conf` encrypted; password in 1Password, shared fleet-wide | Per-machine passwords; unencrypted config |
| D5 | The encrypted config is itself a fleet artifact in 1Password, pushed back on refresh | Password-only sharing, per-machine `rclone config` |
| D6 | 1Password (not `vault/vault.yml`) is the config's home | Ansible vault |
| D7 | Start with FSNotes alone; folder list is data, so breadth is a var edit | Start with all non-empty, or every folder |
| D8 | Event-triggered (login, unlock); no timer for now | systemd user timer |

**On D1/D2.** Fifteen of the twenty-one top-level iCloud folders are empty app stubs.
Per-folder pairs under a shared root give the *appearance* of a whole-drive mirror while
keeping blast radius per-folder: a `--max-delete` trip in one folder cannot wedge
another. `Downloads` (310 MB of share-sheet detritus, constantly churning) is a poor
bisync candidate and stays out even when the list grows.

**On D6.** `vault/vault.yml` is the store that works unattended, before any human
touches the machine — but the iCloud session token *rotates*, and a rotating secret in
git means re-committing an encrypted blob on every re-auth. 1Password costs nothing
extra here because signing into it is already on the fresh-machine critical path.

**On D8.** A session unlock is the best available signal that a human is present and
1Password is reachable — which is precisely the precondition a timer cannot satisfy.
Unlock plus network-up may cover the need well enough that no schedule is ever wanted.

## 4. Architecture

New `icloud` role in `site-async.yml`'s user play, beside `dotfiles`, `aur`, and
`claude_code` — a network-dependent user-tier unit. At converge time it only installs
files and creates directories; it never touches iCloud.

### 4.1 Data (`group_vars/all/main.yml`)

```yaml
icloud_sync_root: "{{ target_home }}/Documents/iCloud"
icloud_filters_base:            # macOS/iCloud noise, applied to every folder
  - "- .DS_Store"
  - "- ._*"
  - "- *.icloud"
icloud_sync_folders:
  - remote: FSNotes             # local path is icloud_sync_root/FSNotes
    filters:
      - "- projects.state"
      - "- *.textbundle"
      - "- /Trash/**"
```

Adding a folder is one list entry. The base/per-folder split reflects the existing
`fsnotes.filter`: its first three lines are generic, its last three are FSNotes-specific.

### 4.2 Components

Four scripts in `scripts/`, installed to `~/.local/bin/`, with one job each. The
boundary that matters: `gatherd-icloud-config` is the only component that knows
1Password exists; `gatherd-icloud-sync` is the only one that knows bisync exists.
Either is testable without the other.

| Script | Responsibility | Interface |
|---|---|---|
| `gatherd-icloud-config` | Config + credential plumbing. Knows 1Password and the encrypted `rclone.conf`; knows nothing of folders or bisync. | `bootstrap`, `pull`, `push`, `status` |
| `gatherd-icloud-sync` | Bisync driver. Knows folders and rclone; assumes a working config exists. | `[folder…]`, `--init`, `--init-if-empty`, `--if-due` |
| `gatherd-prompt-icloud` | Sway autostart, in the `gatherd-prompt-pia` family. Polls until 1Password answers, then calls `config pull` and `sync --init-if-empty`. No logic beyond the readiness wait. | — |
| `gatherd-icloud-password` | Single-word target for `RCLONE_PASSWORD_COMMAND`. Emits the config password from 1Password. | — |

`gatherd-icloud-password` exists to keep `pam_env` quoting out of the picture: the
alternative is embedding `op read 'op://Private/rclone config/password'` — nested quotes
around a value containing a space — directly in `pam_env.conf`. A one-word target also
gives a place to add a session-lifetime cache later.

### 4.3 Templated config

- `~/.config/rclone/filters/<folder>.filter` — base plus per-folder lines.
- `RCLONE_PASSWORD_COMMAND=gatherd-icloud-password` in `/etc/security/pam_env.conf`, via
  the mechanism in `roles/system/tasks/user_path.yml`. Per CLAUDE.md, session env vars
  go through `pam_env` and never `environment.d` — greetd launches sway with no login
  shell. **This is a migration, not a new setting:** the variable is currently exported
  from `~/.bashrc` as `op read --no-newline "op://Private/rclone config/password"`, which
  reaches bash shells but *not* the sway session or the autostart scripts that will call
  this — exactly the trap CLAUDE.md's pam_env convention exists to prevent. The
  `.bashrc` export is removed as part of the migration.
- `unlock-command=gatherd-icloud-sync --if-due` in `gtklock-config.ini.j2`.

## 5. Config and credential lifecycle

### 5.1 1Password items (vault `Private`)

- **`rclone config`** — Password item, the config encryption password. Created with
  `op item create --generate-password` if absent; never typed or chosen by a human.
  **Already exists** at `op://Private/rclone config/password`.
- **`rclone.conf`** — Document item, the **already-encrypted** config. Does not exist
  yet; creating it is the substantive part of `bootstrap`.

"Already-encrypted" is load-bearing. Encryption happens exactly once, on the first
machine; every other machine only ever decrypts. No machine needs to drive
`rclone config encryption set` non-interactively — which is not known to be possible.
rclone preserves existing config encryption when it rewrites the file after a token
refresh, so refreshed configs stay distributable.

The config password is still worth having even though it and the config now sit behind
the same 1Password login: it is what keeps a stolen disk from yielding a live iCloud
token.

### 5.2 `bootstrap` (once per fleet, interactive)

`rclone config` with 2FA → `rclone config encryption set` → create both 1Password items.
The only step in this design a human performs.

Each stage must be **idempotent against work already done by hand**: this machine already
has a working remote, an encrypted config, and the password item, so on it `bootstrap`
does nothing but upload the document. A `bootstrap` that assumes greenfield would
re-encrypt a config that is already encrypted, or overwrite a password item that other
machines will later depend on.

### 5.3 `pull` (login, and on demand)

1. No local config → download the document, install `0600`. Done.
2. Local config exists → test with `rclone lsd icloud:`.
   - Works → fall through to `push`.
   - Fails → fetch the document to a temp file and test *that*. If it works, replace
     local. If it also fails, leave local alone and surface "iCloud needs re-auth."
     Never overwrite a broken config with an equally broken one.

### 5.4 `push` (after a verified re-auth)

1. Local config must pass `rclone lsd icloud:`. A config that cannot list the remote is
   never published.
2. Compare **decrypted** contents, not encrypted bytes. rclone's config encryption is
   nonce-randomized: two encryptions of identical content differ byte-for-byte, so a
   ciphertext comparison would re-upload on every run.
3. Differ → upload, replacing the document.

Decryption for that comparison goes to a `0600` file in `mktemp -d` under
`$XDG_RUNTIME_DIR` (tmpfs, per-user, gone at logout) with a cleanup trap. A decrypted
config is a live iCloud token in plaintext and must not touch disk.

Two machines re-authing at once is last-writer-wins on the document. No fleet locking:
both configs are valid, and the loser re-pulls at next login.

## 6. Sync behavior

Flags carry over from `fsnotes-sync`, with per-folder paths generalized:

```
--filters-file ~/.config/rclone/filters/<folder>.filter
--conflict-resolve newer --conflict-loser pathname
--max-delete 10 --resilient --recover
--transfers 2 --checkers 4 --tpslimit 4
--backup-dir2 ~/.local/share/gatherd/icloud-backup/<folder>
--log-file ~/.local/state/gatherd/rclone-icloud-<folder>.log -v
```

`--backup-dir` must live on the destination's remote, and Path2 (the local
directory) is the destination here — not Path1, the iCloud remote — so this is
`--backup-dir2`.

Baseline presence is read from rclone's own bisync listing cache, and selects one of
three paths:

| Baseline | Local dir | Action |
|---|---|---|
| absent | missing or empty | `--resync` — provably safe, nothing local to lose |
| absent | populated | refuse; print the exact `--init` command; surface in notes |
| present | any | normal bisync |

`--resync` is not a wholesale "remote wins" overwrite — verified against real
rclone 1.75 against scratch remotes. It is a **union**: files present on only
one side are copied to the other (a local-only file is uploaded, not
deleted), and only files present on **both** sides with differing content
take Path1's (the remote's) version — and even then the overwritten local
version is not simply gone: `--backup-dir2` preserves it, byte-for-byte,
under `~/.local/share/gatherd/icloud-backup/<folder>` (verified against real
rclone 1.75 against scratch remotes; a control run with no `--backup-dir2`
does destroy it with no trace). The backup dir keeps only the most recent
version per path, with no suffixing — a second `--init` overwrites whatever
the first one backed up. The refuse-on-populated-dir guard above is still the
right call: two identically-named files that happen to differ still silently
take the remote's copy, which is real enough that a human should watch it
happen — but the guard is deliberately more conservative than the actual
danger requires, not a correction of an otherwise-accurate "remote replaces
everything, unrecoverably" model.

### 6.1 Triggers

Scripts are trigger-agnostic; `gatherd-icloud-sync` is safe to call at any moment. Two
guards live in the script rather than in each caller:

- **`flock`** per folder, non-blocking. Not optional: concurrent bisync on one pair is
  how baselines corrupt.
- **`--if-due`** — stamp file (`~/.local/state/gatherd/icloud-sync.stamp`) plus a
  minimum interval of a few minutes. Bare
  `gatherd-icloud-sync` ignores the stamp, so a manual run is always immediate.

| Event | Hook |
|---|---|
| Login | `gatherd-prompt-icloud` (also does `--init-if-empty`) |
| Unlock | `gtklock` `unlock-command` in `config.ini` — covers idle timeout, lid close via `gatherd-handle-lid`, and `before-sleep`/`after-resume`, since all route through `gtklock -d` |
| Network up | NetworkManager `dispatcher.d` — **out of scope**, the deferred-scheduling shape |

### 6.2 Failure modes

Unattended runs are silent unless a human must decide.

| Failure | Behavior |
|---|---|
| 1Password locked / no config | Not-ready, not broken. Quiet exit 0 when event-triggered; loud when run by hand — but only for the first 3 days after the last successful sync (`STALE_AFTER`). Past that, a still-not-ready condition escalates to a loud notification even when event-triggered, since it now looks like a permanent op/1Password problem rather than a locked vault. |
| Auth expired (2FA due) | Notify once, rate-limited, plus a post-setup-notes line that auto-prunes when it works again — the shape `icloud_configured()` already uses. |
| `--max-delete 10` tripped | Abort, nothing lost, notify. This is the design working: it stands between an empty iCloud listing and your notes. |
| Wedged baseline | `--resilient --recover` covers recoverable cases; a hard wedge routes to the notes and an explicit `--init` after inspecting both sides. |
| Concurrent run | `flock` non-blocking, exit 0. |
| No network / captive portal | Fail fast, quiet exit. `gatherd-prompt-captiveportal` owns that problem. |

## 7. Migration (one-time, manual — not playbook logic)

1. `mv ~/notes ~/Documents/iCloud/FSNotes`
2. `gatherd-icloud-sync --init FSNotes` — the move invalidates the old baseline, so this
   takes the populated-local path, correctly requiring a human to watch.
3. Remove `~/.local/bin/fsnotes-sync` and `~/.config/rclone/fsnotes.filter`.

**Not a formality.** The predecessor script, `fsnotes-sync`, used a
`--backup-dir` flag on the wrong side (Path1, the remote, instead of Path2)
and aborted before it ever transferred anything — its log
(`~/.local/state/rclone-fsnotes.log`) shows zero successful bisyncs. The two
sides may have diverged, silently, for as long as that script ran, and may
never have actually been in sync. Treat step 2 as a real reconciliation to
watch, not a rubber stamp, and take an independent copy of both sides before
running it.

## 8. Post-setup notes changes

- Replace the `rclone config` nag with one that fires only when the 1Password document
  is absent — i.e. the first machine in the fleet, ever — pointing at
  `gatherd-icloud-config bootstrap`.
- Add a re-auth line that auto-prunes, per §6.2.

## 9. Verification

`gatherd-icloud-config status` exists largely so the verify step is a runnable command
with expected output rather than prose. Two `li` items in `section_verify`, each a
paste-and-run sequence:

```sh
# li 1 — sync works end to end
gatherd-icloud-config status     # config: encrypted, verified; fleet: in sync
gatherd-icloud-sync FSNotes      # exits 0; log tail: "Bisync successful"
ls ~/Documents/iCloud/FSNotes | wc -l          # non-zero

# li 2 — unlock trigger is wired, then fires
grep -q '^unlock-command=gatherd-icloud-sync' ~/.config/gtklock/config.ini && echo ok
stat -c %Y ~/.local/state/gatherd/icloud-sync.stamp   # lock, unlock, re-run: advances
```

The `grep` answers CLAUDE.md's fleeting-state requirement: it confirms the unlock hook
is wired without requiring the screen to be locked. Manual residue is one line — lock,
unlock, confirm the stamp file's mtime advanced.

`section_verify` currently holds 7 `li` items; this brings it to 9, under the
repave-suggestion threshold but only just.

## 10. Risks

**R1 — Shared session token across machines (informational, not blocking).** Whether
iCloud tolerates one session token in use from several machines is not settleable on
paper, and there is no second machine available to test on. §11 substitutes a
single-machine shadow-config test.

R1 is **informational** because the acceptance criterion was never "Apple never
invalidates a shared session" — it is "when it does, the fleet heals without a human,"
which the pull-and-retest path in §5.3 already implements. If refresh turns out to kill
sibling sessions, the consequence is not a redesign: machines re-pull more often, and
human 2FA frequency lands somewhere between "once per fleet" and "once per machine."

Only one outcome actually breaks D5: **hard revocation of the trust token on concurrent
use**, forcing fresh 2FA. That failure appears within minutes of T2/T3, not weeks. If it
occurs, the fallback is shared-password/per-machine-config — and because
`gatherd-icloud-config` is the only component that knows where configs come from, that
fallback rewrites one script, not the design.

**R2 — Token expiry is unavoidable.** Even with a portable config, 2FA re-auth comes due
periodically. This design changes *how often* someone types a code — once per fleet
per expiry, rather than once per machine per repave — not whether.

**R3 — `op` unavailable while locked.** `rclone` at the terminal will fail while
1Password is locked. Accepted; identical to PIA's behavior today.

## 11. Pre-completion testing

### 11.1 The shadow-config test (replaces the two-machine test)

No second machine is available. Substitute this, which is stronger than it sounds: under
D5 a fleet machine holds a **byte-identical copy** of the encrypted config — same
`client_id`, same trust token, same cookies. So a second config directory driven via
`RCLONE_CONFIG=` is not an approximation of a second machine; on every axis Apple can
see except the network, it *is* one. Two rclone processes hold the same session
independently, each free to refresh and rewrite its own file.

| | What it tests | Time |
|---|---|---|
| **T1** Copy authenticates | `RCLONE_CONFIG=<shadow> rclone lsd icloud:` succeeds alongside the real one | minutes |
| **T2** Concurrent use | Repeated simultaneous operations from both; neither errors, neither is forced to re-auth | minutes |
| **T3** Divergent egress | T2 again with the shadow's traffic over PIA, so the sessions arrive from different public IPs | minutes |
| **T4** Refresh/rotation | Both copies exercised on a cadence for 1–2 weeks: does rclone rewrite either config, does one side's refresh kill the other | weeks |
| **T5** Self-healing | Stale-ify one copy's session; confirm `gatherd-icloud-config pull` restores it from the fleet copy with no 2FA | minutes |

T3 covers the one axis a same-machine shadow genuinely misses: Apple's fraud heuristics
may key on source IP, and PIA supplies a second egress without a second computer. A qemu
VM would add hostname and MAC divergence, which the iCloud session layer is unlikely to
observe — not worth the setup unless T1–T3 come back ambiguous.

**Sequencing: do not block on T4.** Run T1–T3 and T5 in an afternoon; let T4 accumulate
in the background while implementation proceeds. T4 piggybacks on the unlock trigger from
§6.1 — the shadow syncs on unlock and appends a timestamped line to its own log, so
evidence gathers without attention. Remove the shadow once T4 concludes.

### 11.2 Remaining tests

1. `--init-if-empty` against an empty dir.
2. Push-back guard: deliberately break the local config, confirm nothing is published.
3. 1Password locked (not merely absent) produces "not ready," not a failure notification
   — the `authorization timeout` case, observed live on 2026-08-10.

## 12. Out of scope

- Scheduled/timer-driven sync, and the NetworkManager dispatcher trigger.
- Folders beyond FSNotes (a var edit once the mechanism holds).
- `Downloads` — excluded on the merits, not merely deferred.
