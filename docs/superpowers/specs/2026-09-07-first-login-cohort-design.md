# First-Login Session Helpers — Design

**Type:** Subsystem redesign. Makes the sway autostart cohort work on the first
login of a fresh pave, and removes the deadlock that made one of its members
impossible to satisfy.

**Date:** 2026-09-07
**Status:** Designed. Not yet implemented.
**Related:** `specs/2026-08-04-credential-prompt-house-style-design.md` (the one
renderer, and why `gatherd-askpass` refuses to fall back).

---

## 1. Problem

`gatherd-session-helpers` launches its cohort the instant sway starts. On a
repave that is minutes before the REST tier installs what the cohort is *about*.
Every helper probes for its subject, finds nothing, and exits — silently.

Measured on this machine's 2026-09-07 repave. Session start 11:33:55 (`ps -o
lstart=` on the supervisor); the rest from `/var/log/pacman.log`:

| time | package |
|---|---|
| 11:35:26 | tailscale, conky, wayvnc |
| 11:37:48 | nowayprompt |
| 11:44:16 | 1password |
| 11:44:17 | helium-browser-bin, arch-update, cmd-polkit-git, captive-browser-git |
| 11:49:44 | `/etc/gatherd/async-complete` |

Afterwards `pgrep -g` on the supervisor found **zero** surviving children. The
freshly paved machine never opened the Tailscale or 1Password browser tabs — the
only two things on it that actually needed a human — and had no conky, no tray
and no polkit agent, with nothing retrying until the next login. It went
unnoticed for hours because the failure mode of every one of them is silence.

### 1.1 The class

Every instance is the same shape: **a helper that unblocks REST is itself
installed by REST.** The instances split into two kinds, and they want opposite
answers.

**Breakable.** The vault prompt. `gatherd-await-and-run` waits for
`/usr/local/lib/gatherd/.vault_pass` before running *any* playbook, and
`gatherd-async.service` routes `site-async.yml` through it — a playbook that
states outright (`site-async.yml:222`) that it has no `vars_files:
vault/vault.yml` and reads nothing from the vault. So REST is hostage to a
password it never uses. And the in-session prompt that would collect that
password, `gatherd-prompt-vault`, renders through `gatherd-askpass` →
`nowayprompt` — built from a vendored PKGBUILD by REST
(`roles/system/tasks/nowayprompt.yml`), i.e. by the tier the password is
blocking. On a first boot it has never been able to ask: askpass logs
`nowayprompt missing`, returns 1, and the caller's `|| exit 0` retires it for the
session. `gatherd-prompt-vault-console`'s 60-second `systemd-ask-password` window
is the only path to convergence, and its documented deferral "to the desktop
prompt" defers to something that cannot run.

This coupling is self-imposed and gets removed (§3).

**Irreducible.** The captive-portal watcher. `gatherd-prompt-captiveportal` must
be listening during the pave, because a portal is exactly what stops REST
fetching anything. But what it launches — `captive-browser` (AUR) driving
`helium-browser` (AUR) — arrives at 11:44:17. Measured: the base image contains
**no browser at all** — not netsurf, firefox, chromium, epiphany, falkon,
qutebrowser, links, lynx, w3m or elinks; only `webkit2gtk-4.1`, a library. So
there is nothing to substitute and nothing to reorder. The automation genuinely
cannot do this job before REST, and the honest answer is to say so (§6) rather
than exit quietly.

## 2. Scope

In: the cohort's start ordering, the vault/REST coupling, the captive-portal
announcement, and the static gate that keeps all three from regressing.

Out: moving `nowayprompt` into CORE (CLAUDE.md: CORE installs no packages, and it
is a Rust build); any change to `gatherd-askpass`'s refusal to fall back to a
second renderer, which is deliberate and remains correct.

**Constraint.** An Artix/s6 rebase is planned. Every decision below must leave
the init-specific surface the same or smaller. One does: §4 removes the last
`systemctl` call this subsystem would otherwise acquire.

## 3. Decouple REST from the vault password

`gatherd-await-and-run` gains an explicit `--needs-vault` flag. Only
`gatherd-vault.service` passes it; `gatherd-async.service` does not. Without the
flag the runner neither waits for `.vault_pass` nor passes
`--vault-password-file` to `ansible-playbook`.

Explicit flag rather than parsing the playbook for `vars_files:` — YAML parsing
in POSIX sh is a liability, and the unit file is where the decision belongs. The
drift risk (someone adds vault vars to a playbook and forgets the flag) is
covered by a static gate pairing "playbook declares `vault/vault.yml`" with "its
unit passes `--needs-vault`", the same declared-plus-gate shape as
`gatherd-check-aur-deps`. Drift then fails at parse time with `Attempting to
decrypt but no vault secrets found` — loud, not a deadlock.

Consequence chain: REST runs without a password → `nowayprompt` lands at ~11:37 →
`gatherd-prompt-vault` can render → the console prompt's deferral is real → the
vault play converges whenever the human answers.

Ordering note: `site-vault.yml` configures WiFi only. The EndeavourOS installer
leaves a working connection, so REST does not depend on the vault's networks on a
fresh pave. Recorded here because it is the assumption that makes the decoupling
safe.

## 4. Barrier release conditions

`gatherd-await-async` blocks the REST-dependent part of the cohort. Its release
condition must answer "is the REST run for this commit over, one way or another".

**Rejected: `systemctl is-failed`.** Measured on this machine, it is wrong three
ways. After a converged run the unit is `inactive` and `is-failed` returns 1, so
a stale sentinel after `git -C /usr/local/lib/gatherd pull` — the documented
update path — stalls the whole cohort for the full bound on every login until
reboot. For an unknown unit it returns 4. And a failed CORE run never writes
`core-complete`, so `gatherd-await-and-run` blocks before the playbook while the
unit stays `active (running)` and `is-failed` stays false — an hour with no tray
and no polkit agent, at exactly the moment a broken machine needs them.

**Rejected: release when a vault password is owed.** This was in the first draft.
It reintroduces the original bug verbatim on the one state the barrier exists
for: operator misses the 60s console window (the documented normal case), first
login, no `.vault_pass`, barrier returns instantly, entire cohort races the pave
and loses. §3 removes the reason it seemed necessary.

**Chosen: a finished-stamp written by the runner.** `gatherd-await-and-run`
writes `/etc/gatherd/async-finished` (`<sentinel>-finished`, so the vault play
gets its own) containing the HEAD it ran, on **every** exit path once its
preconditions are met — after a successful run, after a failed one, and on the
already-converged short-circuit. The failed case is the one the sentinel itself
cannot express, because `site-async.yml` writes `async-complete` only when no
tier failed. This requires dropping the `exec` before `ansible-playbook` so the
stamp is reachable.

The barrier then contains no `systemctl` at all, which is the point: under s6 it
ports unchanged.

Remaining releases, all init-agnostic:
- stamp records the deployed HEAD → done;
- `/etc/gatherd/last-run` records a non-`ok` CORE status → REST will never start;
- a bounded timeout, validated (see §7).

## 5. The vault prompt gets a targeted wait

This needs a third launch form, because the two in the draft cannot express it:
`start_now` demands base-only packages and `start_later` waits for the whole REST
run.

    start_when <command> "<cmd>"

waits for `<command>` to appear on PATH, then starts the helper.
`start_when nowayprompt "$bin/gatherd-prompt-vault"` is the only use today. On
the measured timings that fires at ~11:37 rather than ~11:49 — the WiFi
configuration lands during the pave rather than after it. It is the one cohort
member whose subject arrives materially earlier than `async-complete`, and the
one whose lateness costs something.

A `start_when` helper is gated, so its command need not be in base — that is the
point of it. It sits outside the `{ … } &` block because it carries its own wait,
and it is bounded the same way the barrier is.

## 6. The captive-portal watcher announces what it cannot do

It stays immediate — it must be listening. On a portal detection with no
`captive-browser` on PATH it sends a desktop notification saying so, instead of
the current silent no-op. `libnotify` and `mako` are both in
`tests/base-manifest.txt` (measured), so this works at first login.

This is the general answer for the irreducible half of the class: a helper that
cannot do its job before REST must say so at the moment it is asked to.

## 7. Correctness details found by review

- `gatherd-needs-run` runs `git rev-parse` against the root-owned checkout. As
  root that is fine; called by the barrier as the desktop user, git refuses
  ("detected dubious ownership") and the failure reads as "a run is still owed",
  forever. It works today only because `~/.gitconfig` carries `safe.directory =
  *` — and those dotfiles are a REST tier, so the first login has no such file.
  Fix: `-c safe.directory="$gatherd_home"`, scoped to the one path.
- Only exit 1 from `gatherd-needs-run` means converged. A missing or
  non-executable script returns 127 and would silently turn the barrier into a
  no-op.
- `GATHERD_AWAIT_ASYNC_TIMEOUT=abc` currently throws under `set -u`, breaking the
  stated always-exit-0 invariant. Validate it.
- The `{ … } &` subshell inherits the supervisor's argv (measured), so the
  startup sweep's `*gatherd-session-helpers*` skip spares a *leaked* one — which
  then sits in the barrier and launches a duplicate cohort into a later session:
  a second polkit agent, a second conky, a second wayvnc fighting for
  127.0.0.1:5900. Skip by pid (`$$` and `$PPID`) instead of by name.

## 8. The gate

`gatherd-check-session-cohort` enforces one rule per launch form:

- `start_now` may only need packages in `tests/base-manifest.txt`, and must
  carry a `# needs:` declaration naming them. That set is exact because CORE
  installs no packages. An undeclared `start_now` is a hard failure, not a silent
  bet.
- `start_later` must sit inside the `{ … } &` block, below the barrier call.
- `start_when` must sit outside that block, and names its own wait, so no
  `# needs:` applies.

Known limits, to be stated in the gate's own header rather than left implied:
- it checks *declared* start-time needs, not completeness, and cannot verify a
  declaration is honest;
- it therefore does not catch §1.1's irreducible case, which is why §6 is a
  runtime announcement rather than a static rule.

Holes to close (all measured against the current draft):
- a `start_later` inside the block but *above* the barrier passes; compare
  against the barrier line, not the block's opening brace;
- `comm` is fed `grep -n` output in numeric order and warns once the file passes
  line 100; sort first, or compare by line number;
- nothing checks that `scripts/gatherd-await-async` exists or that a role
  installs it — delete the copy task and the suite stays green while the barrier
  degrades to a no-op;
- `*start_later*` matches the whole line, so a *command* containing the string is
  misdiagnosed; match the leading token.

Plus the new §3 gate: every playbook declaring `vault/vault.yml` must be run by a
unit passing `--needs-vault`, and no other unit may pass it.

## 9. Testing

All offline, in `tests/gates`:

- `tests/await-and-run` — the conditional vault wait, and the finished-stamp on
  both success and failure.
- `tests/await-async` — waits on a stale sentinel; releases on a fresh one, on a
  finished-but-failed run, and on a CORE failure; waits again when only a stale
  finished-stamp is present; returns at once on a converged machine; survives a
  checkout git calls foreign
  (`GIT_TEST_ASSUME_DIFFERENT_OWNER=1` reproduces it, and the case must stall
  without the fix — a sandbox repo is owned by whoever runs the suite, so an
  earlier version of this test passed vacuously).
- `tests/check-session-cohort` — each hole in §8, each proven to fail before the
  fix.
- `tests/post-setup-notes` — already covers the Vault section.

Not reachable offline, and left to the repave: that the tabs actually open. §10.

## 10. Verification

One `verify_li`, replacing the unrunnable draft (`FOO=1 time cmd` demotes `time`
from keyword to command, and `/usr/bin/time` is not installed here — measured):

> The cohort waits for REST rather than racing it: `~/.local/bin/gatherd-await-async`
> returns immediately on this converged machine, and with
> `GATHERD_ASYNC_SENTINEL=/nonexistent GATHERD_AWAIT_ASYNC_TIMEOUT=5` it takes
> about 5s. On a fresh pave the Tailscale and 1Password tabs open without logging
> out and back in.

The `GATHERD_ASYNC_SENTINEL` override is what makes the fleeting state
reproducible on a converged machine, per CLAUDE.md.

## 11. Phasing

Landable in three independent commits, each green on its own:

1. §3 + its gate — decouple REST from the vault password. This is the fix; the
   rest is what stops it silently regressing.
2. §4, §5, §7 + the cohort restructure — the barrier and the launch forms.
3. §6 + §8's gate holes.

## 12. Migration

None of this is removal-shaped, so no `MIGRATIONS.md` entry. Already-converged
machines pick it up on the next converge: CORE reinstalls the supervisor and the
barrier, and the unit files are rewritten with the new `ExecStart`.
