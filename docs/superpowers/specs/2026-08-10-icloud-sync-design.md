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
  shell.
- `unlock-command=gatherd-icloud-sync --if-due` in `gtklock-config.ini.j2`.

## 5. Config and credential lifecycle

### 5.1 1Password items (vault `Private`)

- **`rclone config`** — Password item, the config encryption password. Created with
  `op item create --generate-password` if absent; never typed or chosen by a human.
- **`rclone.conf`** — Document item, the **already-encrypted** config.

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
--backup-dir1 ~/.local/share/gatherd/icloud-backup/<folder>
--log-file ~/.local/state/rclone-icloud-<folder>.log -v
```

Baseline presence is read from rclone's own bisync listing cache, and selects one of
three paths:

| Baseline | Local dir | Action |
|---|---|---|
| absent | missing or empty | `--resync` — provably safe, nothing local to lose |
| absent | populated | refuse; print the exact `--init` command; surface in notes |
| present | any | normal bisync |

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
| 1Password locked / no config | Not-ready, not broken. Quiet exit 0 when event-triggered; loud when run by hand. |
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

Safe specifically because both sides are in sync *today*, which makes the re-baseline a
formality. Do the migration while that is still true.

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

**R1 — Shared session token across machines (blocking).** Whether iCloud tolerates one
session token in use from several machines, or invalidates on concurrent use, is not
settleable on paper. **Test on two machines before the fleet depends on it.** If it does
not hold, the fallback is shared-password/per-machine-config; because
`gatherd-icloud-config` is the only component that knows where configs come from, that
fallback rewrites one script, not the design.

**R2 — Token expiry is unavoidable.** Even with a portable config, 2FA re-auth comes due
periodically. This design changes *how often* someone types a code — once per fleet
per expiry, rather than once per machine per repave — not whether.

**R3 — `op` unavailable while locked.** `rclone` at the terminal will fail while
1Password is locked. Accepted; identical to PIA's behavior today.

## 11. Pre-completion testing

In order:

1. **R1's two-machine token test** — the one result that can invalidate the approach.
2. `--init-if-empty` against an empty dir.
3. Push-back guard: deliberately break the local config, confirm nothing is published.

## 12. Out of scope

- Scheduled/timer-driven sync, and the NetworkManager dispatcher trigger.
- Folders beyond FSNotes (a var edit once the mechanism holds).
- `Downloads` — excluded on the merits, not merely deferred.
