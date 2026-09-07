# First-Login Session Cohort Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every sway autostart helper work on the first login of a fresh pave, by removing the vault password's hold over the REST tier and starting each helper only once its subject exists.

**Architecture:** `gatherd-await-and-run` stops demanding a vault password for playbooks that do not use one, and writes a finished-stamp on every exit path. `gatherd-session-helpers` gains three launch forms — immediate, behind a barrier that waits for that stamp, and behind a wait for one named command. A static gate enforces which form each helper may use.

**Tech Stack:** POSIX sh, Ansible (FQCN only), systemd unit files, shellcheck, ansible-lint.

**Spec:** `docs/superpowers/specs/2026-09-07-first-login-cohort-design.md`

## Global Constraints

- POSIX `sh` only. `bash`-isms are a defect, not a style choice.
- `shellcheck` clean, with no `# shellcheck disable` unless the line above it says why.
- `ansible-lint` clean at the `production` profile for every file touched. (A bare `ansible-lint` run in a fresh clone reports one pre-existing `internal-error` on `site-vault.yml` because no `.vault_pass` is present — that is not yours.)
- Ansible modules always FQCN: `ansible.builtin.*`, `community.general.*`.
- CORE installs no packages, ever. That is what makes `tests/base-manifest.txt` an exact statement of what exists at the first login.
- Task names in Ansible read as imperative sentences ("Install the barrier script", not "barrier install task").
- Comments explain *why*, never *what*.
- `tests/gates` is the one command to run before committing. Every `scripts/gatherd-{check,assert}-*` must have a `tests/<same-name>` beside it; the suite enforces this with no exemption list.
- `scripts/gatherd-await-async` must contain no `systemctl` call. Removing the subsystem's last init-specific line is a design goal (the Artix/s6 rebase), not an incidental tidy.
- Exit conventions for gates: 0 clean, 1 violation, 2 could not run. Never a silent skip.

---

## Starting state

The working tree has **staged, uncommitted** work from an earlier attempt at Phase 2. It contains a barrier whose release condition is known-wrong (it releases when a vault password is owed, which reintroduces the original bug on exactly the state the barrier exists for — spec §4). Task 5 discards it deliberately. Do not try to salvage it; every file it touched is rewritten in full below.

Committed and done already, not part of this plan:
- `315dd82` — the Vault section of `gatherd-post-setup-notes` and `tests/post-setup-notes`.
- `d346139` — the waybar Claude usage icon and separator.
- `b073541` — the spec.

---

# Phase 1 — Decouple REST from the vault password

## Task 1: Make the vault wait conditional

**Files:**
- Modify: `scripts/gatherd-await-and-run`
- Modify: `services/system/gatherd-vault.service:11`
- Create: `tests/await-and-run`
- Modify: `tests/gates`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `gatherd-await-and-run [--needs-vault] <sentinel> <playbook>`. Without the flag the script never reads `.vault_pass` and never passes `--vault-password-file` to `ansible-playbook`.

- [ ] **Step 1: Write the failing test**

Create `tests/await-and-run`:

```sh
#!/bin/sh
# Unit tests for gatherd-await-and-run's vault gating.
#
# The bug being closed: the runner waited for /usr/local/lib/gatherd/.vault_pass
# before running ANY playbook, and gatherd-async.service routes site-async.yml
# through it -- a playbook that states outright it reads nothing from the vault.
# So REST was hostage to a password it never used, and the in-session prompt that
# would collect that password renders through nowayprompt, which REST installs.
#
# ansible-playbook is stubbed: these test the gating, not Ansible.
#
# Usage: tests/await-and-run

set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
RUNNER="$REPO/scripts/gatherd-await-and-run"
PASS=0
FAIL=0

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }
assert() { _d=$1; shift; if [ "$@" ]; then ok "$_d"; else bad "$_d"; fi; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/gatherd/scripts" "$WORK/gatherd/vault" "$WORK/stub" "$WORK/etc"

cp "$REPO/scripts/gatherd-needs-run" "$WORK/gatherd/scripts/"
git -C "$WORK/gatherd" init -q
git -C "$WORK/gatherd" -c user.email=t@t -c user.name=t commit -q --allow-empty -m base

: > "$WORK/gatherd/site-async.yml"
: > "$WORK/etc/core-complete"

# Stubs. ansible-playbook records its argv and its exit code is scripted;
# ansible-galaxy and systemd-inhibit are no-ops we do not want to reach for real.
cat > "$WORK/stub/ansible-playbook" <<STUB
#!/bin/sh
printf '%s\n' "\$*" >> "$WORK/argv"
exit "\$(cat "$WORK/rc" 2>/dev/null || echo 0)"
STUB
printf '#!/bin/sh\nexit 0\n' > "$WORK/stub/ansible-galaxy"
printf '#!/bin/sh\nexit 0\n' > "$WORK/stub/ansible-vault"
chmod 755 "$WORK/stub"/*
printf '0\n' > "$WORK/rc"

run_runner() {
    rm -f "$WORK/argv"
    PATH="$WORK/stub:$PATH" GATHERD_HOME="$WORK/gatherd" \
        GATHERD_CORE_COMPLETE="$WORK/etc/core-complete" \
        timeout 10 sh "$RUNNER" "$@" >/dev/null 2>&1 && RC=0 || RC=$?
}

# 1. Without --needs-vault the runner must not wait for a password that does not
#    exist, and must not hand ansible-playbook a --vault-password-file it cannot
#    read. Before this change it blocked here forever.
rm -f "$WORK/gatherd/.vault_pass"
run_runner "$WORK/etc/async-complete" "$WORK/gatherd/site-async.yml"
assert "runs with no vault password when the flag is absent (rc=$RC)" "$RC" -eq 0
if grep -q 'vault-password-file' "$WORK/argv" 2>/dev/null; then
    bad "and passes no --vault-password-file"
else
    ok "and passes no --vault-password-file"
fi

# 2. With --needs-vault and no password stored, it must block rather than run the
#    play, because the play cannot be decrypted.
: > "$WORK/gatherd/vault/vault.yml"
: > "$WORK/gatherd/site-vault.yml"
run_runner --needs-vault "$WORK/etc/vault-complete" "$WORK/gatherd/site-vault.yml"
assert "blocks without a password when the flag is given (rc=$RC)" "$RC" -eq 124
assert "and never reached ansible-playbook" ! -f "$WORK/argv"

# 3. With --needs-vault and a password that decrypts, it runs and passes the file.
printf 'secret\n' > "$WORK/gatherd/.vault_pass"
run_runner --needs-vault "$WORK/etc/vault-complete" "$WORK/gatherd/site-vault.yml"
assert "runs once a password is stored (rc=$RC)" "$RC" -eq 0
if grep -q -- '--vault-password-file' "$WORK/argv" 2>/dev/null; then
    ok "and passes --vault-password-file"
else
    bad "and passes --vault-password-file"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

`chmod 755 tests/await-and-run`.

- [ ] **Step 2: Run it to verify it fails**

Run: `tests/await-and-run`
Expected: FAIL on case 1 — the runner blocks waiting for `.vault_pass` and `timeout` kills it (rc=124, not 0).

- [ ] **Step 3: Implement the conditional wait**

In `scripts/gatherd-await-and-run`, replace lines 15-24 (the usage comment through `complete=`) with:

```sh
# Usage: gatherd-await-and-run [--needs-vault] <sentinel> <playbook>
#
# --needs-vault is passed by exactly the units whose playbook declares
# `vars_files: vault/vault.yml`. It used to be unconditional, which made the REST
# tier hostage to a password site-async.yml never reads -- and REST is what
# installs nowayprompt, the renderer the in-session vault prompt needs, so on a
# fresh machine the password could not even be asked for. See
# docs/superpowers/specs/2026-09-07-first-login-cohort-design.md.
set -eu

needs_vault=no
case "${1:-}" in
--needs-vault) needs_vault=yes; shift ;;
esac

sentinel="$1"
playbook="$2"

# Overridable only so these paths can be pointed at a sandbox in tests.
gatherd_home="${GATHERD_HOME:-/usr/local/lib/gatherd}"
vault_pass="$gatherd_home/.vault_pass"
vault_file="$gatherd_home/vault/vault.yml"
complete="${GATHERD_CORE_COMPLETE:-/etc/gatherd/core-complete}"
```

Replace the wait block (old lines 29-47) with:

```sh
# Block until the first-boot run has finished. Polling (rather than inotify)
# keeps this dependency-free and identical across inits; 2s latency is irrelevant
# for setup work.
while [ ! -f "$complete" ]; do
    sleep 2
done

# And, only for a play that actually reads the vault, until a password that
# decrypts it is present. A mistyped password is discarded right here so the
# prompt side re-asks; we never carry a bad password into the play, where the
# decryption failure would fail the unit permanently with no retry path.
if [ "$needs_vault" = yes ]; then
    while :; do
        while [ ! -f "$vault_pass" ]; do
            sleep 2
        done
        # No vault deployed → the password only needs to exist, not to decrypt.
        [ -f "$vault_file" ] || break
        if ansible-vault view --vault-password-file="$vault_pass" "$vault_file" >/dev/null 2>&1; then
            break
        fi
        rm -f "$vault_pass"
    done
fi
```

Replace the invocation block (old lines 57-63) with:

```sh
# Hold off sleep during the long package run when the tooling is available
# (elogind ships systemd-inhibit on Artix too), but tolerate its absence. The
# inhibitor is passed as this function's argv rather than interpolated into a
# command string, so --why's spaces survive without unquoted word splitting.
play() {
    if [ "$needs_vault" = yes ]; then
        "$@" ansible-playbook --vault-password-file="$vault_pass" "$playbook"
    else
        "$@" ansible-playbook "$playbook"
    fi
}

if command -v systemd-inhibit >/dev/null 2>&1; then
    play systemd-inhibit --what=sleep --who=gatherd \
        --why="gatherd background work in progress" --mode=block
else
    play
fi
```

- [ ] **Step 4: Pass the flag from the vault unit only**

`services/system/gatherd-vault.service:11` becomes:

```
ExecStart=/usr/local/lib/gatherd/scripts/gatherd-await-and-run --needs-vault /etc/gatherd/vault-complete /usr/local/lib/gatherd/site-vault.yml
```

`services/system/gatherd-async.service:14` is left exactly as it is.

- [ ] **Step 5: Wire the suite in**

In `tests/gates`, add `await-and-run` to the `for suite in ...` list.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `shellcheck scripts/gatherd-await-and-run tests/await-and-run && tests/await-and-run`
Expected: `shellcheck` silent, `6 passed, 0 failed`.

- [ ] **Step 7: Commit**

```bash
git add scripts/gatherd-await-and-run services/system/gatherd-vault.service tests/await-and-run tests/gates
git commit -m "Stop holding the REST tier hostage to a vault password it never reads"
```

## Task 2: Gate the --needs-vault pairing

**Files:**
- Create: `scripts/gatherd-check-vault-units`
- Create: `tests/check-vault-units`
- Modify: `tests/gates`

**Interfaces:**
- Consumes: the `--needs-vault` flag introduced in Task 1.
- Produces: `gatherd-check-vault-units [repo-root]`, exit 0/1/2.

- [ ] **Step 1: Write the failing test**

Create `tests/check-vault-units`:

```sh
#!/bin/sh
# Unit tests for gatherd-check-vault-units.
#
# The flag is a declaration, and a declaration can drift from what it describes.
# Both directions are failures: a playbook that reads the vault but whose unit
# forgot the flag dies at parse time with "Attempting to decrypt but no vault
# secrets found", and a unit that passes the flag for a playbook with no vault
# vars silently reinstates the coupling this whole change removed.
#
# Usage: tests/check-vault-units

set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
GATE="$REPO/scripts/gatherd-check-vault-units"
PASS=0
FAIL=0

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/services/system"

assert_rc() {
    _d=$1; _want=$2
    if "$GATE" "$WORK" >"$WORK/out" 2>&1; then _got=0; else _got=$?; fi
    if [ "$_got" = "$_want" ]; then ok "$_d"; else bad "$_d (want rc=$_want got rc=$_got)"; sed 's/^/       /' "$WORK/out"; fi
}
assert_says() {
    _d=$1; _want=$2
    if grep -q -- "$_want" "$WORK/out"; then ok "$_d"; else bad "$_d (no '$_want' in output)"; fi
}

unit() {
    printf '[Service]\nExecStart=/usr/local/lib/gatherd/scripts/gatherd-await-and-run %s /usr/local/lib/gatherd/%s\n' \
        "$2" "$3" > "$WORK/services/system/$1"
}

# 1. Matched pair: the vault play declares vault vars and its unit passes the
#    flag; the async play declares none and its unit does not.
printf -- '---\n- hosts: localhost\n  vars_files:\n    - vault/vault.yml\n' > "$WORK/site-vault.yml"
printf -- '---\n- hosts: localhost\n' > "$WORK/site-async.yml"
unit gatherd-vault.service '--needs-vault /etc/gatherd/vault-complete' site-vault.yml
unit gatherd-async.service '/etc/gatherd/async-complete' site-async.yml
assert_rc "a matched pair exits 0" 0

# 2. A playbook reads the vault and its unit forgot the flag.
unit gatherd-vault.service '/etc/gatherd/vault-complete' site-vault.yml
assert_rc "vault vars without the flag fails" 1
assert_says "and names the playbook" "site-vault.yml"

# 3. A unit passes the flag for a playbook with no vault vars, quietly putting
#    the coupling back.
unit gatherd-vault.service '--needs-vault /etc/gatherd/vault-complete' site-vault.yml
unit gatherd-async.service '--needs-vault /etc/gatherd/async-complete' site-async.yml
assert_rc "the flag on a vault-free playbook fails" 1
assert_says "and names that playbook" "site-async.yml"

# 4. A unit naming a playbook that is not in the repo is a could-not-run, never a
#    pass -- a gate that returns 0 when it could not look is worse than no gate.
unit gatherd-async.service '/etc/gatherd/async-complete' site-missing.yml
assert_rc "a missing playbook is rc=2" 2

# 5. No units at all is also rc=2, not a clean bill of health.
rm -f "$WORK/services/system"/*.service
assert_rc "no units to check is rc=2" 2

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

`chmod 755 tests/check-vault-units`.

- [ ] **Step 2: Run it to verify it fails**

Run: `tests/check-vault-units`
Expected: FAIL — `scripts/gatherd-check-vault-units` does not exist yet.

- [ ] **Step 3: Write the gate**

Create `scripts/gatherd-check-vault-units`:

```sh
#!/bin/sh
# Fail if a unit's --needs-vault flag disagrees with its playbook.
#
# gatherd-await-and-run takes --needs-vault, and exactly the units whose playbook
# declares `vars_files: vault/vault.yml` may pass it. The flag exists because the
# wait used to be unconditional, which made the REST tier hostage to a password
# site-async.yml never reads -- and REST installs nowayprompt, which the
# in-session vault prompt needs to render, so on a fresh machine the password
# could not even be asked for.
#
# Both directions are failures. A playbook that gained vault vars whose unit
# forgot the flag dies at parse time ("Attempting to decrypt but no vault secrets
# found") -- loud, but only at runtime, on the machine, during a pave. A unit
# that passes the flag for a playbook with no vault vars silently restores the
# deadlock.
#
# DECLARED, not present: this reads the repo, never the machine it runs on.
#
# Exit 0 clean, 1 violation, 2 could not run. Never a silent skip.
#
# Usage: gatherd-check-vault-units [repo-root]
set -u

repo="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
units="$repo/services/system"

die() { printf 'gatherd-check-vault-units: %s\n' "$1" >&2; exit 2; }

[ -d "$units" ] || die "cannot read $units"

rc=0
fail() { printf 'FAIL %s\n' "$1" >&2; rc=1; }

checked=0
for unit in "$units"/*.service; do
    [ -f "$unit" ] || continue
    line=$(grep -m1 '^ExecStart=.*gatherd-await-and-run' "$unit") || continue
    checked=$((checked + 1))

    # The playbook is the last whitespace-separated word of the ExecStart line.
    playbook=${line##* }
    # Units name absolute deployed paths; map that back onto this checkout.
    rel=${playbook#/usr/local/lib/gatherd/}
    [ -f "$repo/$rel" ] || die "$(basename "$unit") names $playbook, which is not in this repo"

    declares=no
    grep -qE '^[[:space:]]*-[[:space:]]*vault/vault\.yml[[:space:]]*$' "$repo/$rel" && declares=yes

    passes=no
    case "$line" in
    *--needs-vault*) passes=yes ;;
    esac

    if [ "$declares" = yes ] && [ "$passes" = no ]; then
        fail "$(basename "$unit"): $rel declares vars_files: vault/vault.yml but the unit does not pass --needs-vault -- the play will die at parse time with 'no vault secrets found'"
    fi
    if [ "$declares" = no ] && [ "$passes" = yes ]; then
        fail "$(basename "$unit"): passes --needs-vault for $rel, which declares no vault vars -- that blocks the play on a password it never reads"
    fi
done

[ "$checked" -gt 0 ] || die "no gatherd-await-and-run units found under $units"

exit "$rc"
```

`chmod 755 scripts/gatherd-check-vault-units`.

- [ ] **Step 4: Wire it in**

In `tests/gates`, add to the "gates, against this working tree" block:

```sh
run "$REPO/scripts/gatherd-check-vault-units" "$REPO"
```

and add `check-vault-units` to the `for suite in ...` list.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `shellcheck scripts/gatherd-check-vault-units tests/check-vault-units && tests/check-vault-units && scripts/gatherd-check-vault-units .`
Expected: `7 passed, 0 failed`, then exit 0 against the real tree.

- [ ] **Step 6: Commit**

```bash
git add scripts/gatherd-check-vault-units tests/check-vault-units tests/gates
git commit -m "Check that --needs-vault agrees with the playbook it runs"
```

---

# Phase 2 — The barrier and the launch forms

## Task 3: Fix gatherd-needs-run for a non-root caller

**Files:**
- Modify: `scripts/gatherd-needs-run:18`
- Create: `tests/needs-run`
- Modify: `tests/gates`

**Interfaces:**
- Produces: `gatherd-needs-run <sentinel>` usable by an unprivileged caller against the root-owned checkout. Exit 0 = a run is owed, 1 = converged.

- [ ] **Step 1: Write the failing test**

Create `tests/needs-run`:

```sh
#!/bin/sh
# Unit tests for gatherd-needs-run.
#
# It used to be called only by root, which owns /usr/local/lib/gatherd.
# gatherd-await-async calls it as the desktop user, and git refuses a repository
# it thinks belongs to someone else ("detected dubious ownership"). Read as "a
# run is still owed", that stalls the whole session cohort. It works on a
# converged machine only because ~/.gitconfig carries `safe.directory = *` -- and
# those dotfiles are themselves a REST tier, so the first login has no such file.
#
# A test repo is necessarily owned by whoever runs the suite, so the mismatch is
# simulated with git's own knob for it, GIT_TEST_ASSUME_DIFFERENT_OWNER.
#
# Usage: tests/needs-run

set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
SCRIPT="$REPO/scripts/gatherd-needs-run"
PASS=0
FAIL=0

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }
assert() { _d=$1; shift; if [ "$@" ]; then ok "$_d"; else bad "$_d"; fi; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/gatherd" "$WORK/nohome"
git -C "$WORK/gatherd" init -q
git -C "$WORK/gatherd" -c user.email=t@t -c user.name=t commit -q --allow-empty -m base
HEAD=$(git -C "$WORK/gatherd" rev-parse HEAD)
SENTINEL="$WORK/sentinel"

probe() {
    HOME="$WORK/nohome" GATHERD_HOME="$WORK/gatherd" "$@" sh "$SCRIPT" "$SENTINEL" && RC=0 || RC=$?
}

# 1. No sentinel: a run is owed.
rm -f "$SENTINEL"
probe env
assert "a missing sentinel means a run is owed (rc=$RC)" "$RC" -eq 0

# 2. Sentinel at the deployed HEAD: converged.
printf '%s\n' "$HEAD" > "$SENTINEL"
probe env
assert "a current sentinel means converged (rc=$RC)" "$RC" -eq 1

# 3. Stale sentinel: a run is owed again. This is every boot after a git pull.
printf '%s\n' 0000000000000000000000000000000000000000 > "$SENTINEL"
probe env
assert "a stale sentinel means a run is owed (rc=$RC)" "$RC" -eq 0

# 4. A checkout git calls foreign must still answer, or a converged machine reads
#    as permanently unconverged.
printf '%s\n' "$HEAD" > "$SENTINEL"
probe env GIT_TEST_ASSUME_DIFFERENT_OWNER=1
assert "a foreign-owned checkout still reads as converged (rc=$RC)" "$RC" -eq 1

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

`chmod 755 tests/needs-run`.

- [ ] **Step 2: Run it to verify case 4 fails**

Run: `tests/needs-run`
Expected: `FAIL a foreign-owned checkout still reads as converged (rc=0)` — three pass, one fails.

- [ ] **Step 3: Scope safe.directory to the one path**

In `scripts/gatherd-needs-run`, replace line 18 with:

```sh
# -c safe.directory: this used to be called only by root, which owns the
# checkout, and gatherd-await-async now calls it as the desktop user. Git refuses
# a repository owned by someone else ("detected dubious ownership") and we would
# read that as "a run is still owed" -- forever, on a converged machine. It works
# today only because ~/.gitconfig carries `safe.directory = *`, and the dotfiles
# that install it are themselves a REST tier, so the very first login has no such
# file. Scoped to this one path, for this one command.
head=$(git -C "$gatherd_home" -c safe.directory="$gatherd_home" rev-parse HEAD 2>/dev/null) || exit 0
```

Also make `gatherd_home` overridable, replacing line 14:

```sh
# Overridable only so callers can be exercised against a sandbox in tests, the
# same reason gatherd-vault-pass-needed takes it.
gatherd_home="${GATHERD_HOME:-/usr/local/lib/gatherd}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `shellcheck scripts/gatherd-needs-run tests/needs-run && tests/needs-run`
Expected: `4 passed, 0 failed`.

- [ ] **Step 5: Wire the suite in and commit**

Add `needs-run` to the `for suite in ...` list in `tests/gates`.

```bash
git add scripts/gatherd-needs-run tests/needs-run tests/gates
git commit -m "Let gatherd-needs-run answer for a caller that does not own the checkout"
```

## Task 4: Write a finished-stamp on every exit path

**Files:**
- Modify: `scripts/gatherd-await-and-run`
- Modify: `tests/await-and-run`

**Interfaces:**
- Consumes: Task 1's `--needs-vault` runner, Task 3's `gatherd-needs-run`.
- Produces: `<sentinel>-finished` (e.g. `/etc/gatherd/async-finished`), containing the git HEAD the run was made at, written after a successful run, after a failed one, and on the already-converged short-circuit.

- [ ] **Step 1: Add the failing tests**

Append to `tests/await-and-run`, before the summary lines:

```sh
# 4. The stamp is the barrier's release signal, so it must be written whatever
#    happens -- including the case the sentinel itself cannot express, since
#    site-async.yml writes async-complete only when no tier failed.
STAMP="$WORK/etc/async-complete-finished"
HEAD=$(git -C "$WORK/gatherd" rev-parse HEAD)

rm -f "$STAMP" "$WORK/etc/async-complete"
printf '0\n' > "$WORK/rc"
run_runner "$WORK/etc/async-complete" "$WORK/gatherd/site-async.yml"
assert "a successful run writes the finished stamp" -f "$STAMP"
assert "recording the deployed HEAD" "$(cat "$STAMP" 2>/dev/null)" = "$HEAD"

rm -f "$STAMP"
printf '2\n' > "$WORK/rc"
run_runner "$WORK/etc/async-complete" "$WORK/gatherd/site-async.yml"
assert "a failed run writes it too" -f "$STAMP"
assert "and still reports the failure (rc=$RC)" "$RC" -eq 2
printf '0\n' > "$WORK/rc"

# 5. And on the short-circuit, where the play already converged at this HEAD and
#    never runs. Without this the barrier waits out its whole bound on every
#    login of a machine that has nothing to do.
rm -f "$STAMP"
printf '%s\n' "$HEAD" > "$WORK/etc/async-complete"
run_runner "$WORK/etc/async-complete" "$WORK/gatherd/site-async.yml"
assert "an already-converged short-circuit writes it" -f "$STAMP"
assert "and exits 0 (rc=$RC)" "$RC" -eq 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `tests/await-and-run`
Expected: FAIL on "a successful run writes the finished stamp" — no stamp exists.

- [ ] **Step 3: Write the stamp**

In `scripts/gatherd-await-and-run`, after the `sentinel`/`playbook` assignments add:

```sh
# The barrier the session cohort waits on (scripts/gatherd-await-async) needs to
# know this run is OVER, which is a different question from whether it succeeded:
# site-async.yml writes its sentinel only when no tier failed, so a failed run is
# indistinguishable from one still going. This stamp answers the first question
# and the sentinel keeps answering the second.
stamp="${sentinel}-finished"

mark_finished() {
    _head=$(git -C "$gatherd_home" -c safe.directory="$gatherd_home" rev-parse HEAD 2>/dev/null) || return 0
    printf '%s\n' "$_head" > "$stamp" 2>/dev/null || true
}
```

Replace the short-circuit (old line 50) with:

```sh
# Skip if this play already converged at the deployed git HEAD -- but stamp
# first, or a machine with nothing to do never releases the cohort.
if ! "$gatherd_home/scripts/gatherd-needs-run" "$sentinel"; then
    mark_finished
    exit 0
fi
```

Replace the invocation block's tail so the stamp survives a failure. `play` must no longer be the last command, and `set -e` must not abort on a nonzero playbook:

```sh
if command -v systemd-inhibit >/dev/null 2>&1; then
    play systemd-inhibit --what=sleep --who=gatherd \
        --why="gatherd background work in progress" --mode=block && rc=0 || rc=$?
else
    play && rc=0 || rc=$?
fi

mark_finished
exit "$rc"
```

Note the `exec`s are gone: the stamp is unreachable past an `exec`, and one extra process for the life of a converge costs nothing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `shellcheck scripts/gatherd-await-and-run tests/await-and-run && tests/await-and-run`
Expected: `12 passed, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/gatherd-await-and-run tests/await-and-run
git commit -m "Record that a gatherd run finished, separately from whether it converged"
```

## Task 5: Discard the earlier barrier attempt

**Files:**
- Revert: `scripts/gatherd-session-helpers`, `roles/desktop/tasks/core.yml`
- Delete: `scripts/gatherd-await-async`, `scripts/gatherd-check-session-cohort`, `tests/await-async`, `tests/check-session-cohort`

- [ ] **Step 1: Keep a copy for reference, then reset**

```bash
git diff --cached > /tmp/abandoned-barrier.patch
git restore --staged --worktree scripts/gatherd-session-helpers roles/desktop/tasks/core.yml
git restore --staged scripts/gatherd-await-async scripts/gatherd-check-session-cohort tests/await-async tests/check-session-cohort
rm -f scripts/gatherd-await-async scripts/gatherd-check-session-cohort tests/await-async tests/check-session-cohort
```

Note: `scripts/gatherd-post-setup-notes` may also carry a staged `verify_li` from that attempt. Leave it; Task 9 rewrites that line.

- [ ] **Step 2: Verify the tree is clean of it**

Run: `git status --short && tests/gates`
Expected: only Phase 1's committed work present; `tests/gates` green.

Do not commit — this task only removes uncommitted work.

## Task 6: Write the barrier

**Files:**
- Create: `scripts/gatherd-await-async`
- Create: `tests/await-async`
- Modify: `roles/desktop/tasks/core.yml` (after the `Install gatherd-session-helpers supervisor script` task)
- Modify: `tests/gates`

**Interfaces:**
- Consumes: Task 4's `<sentinel>-finished` stamp, Task 3's `gatherd-needs-run`.
- Produces: `~/.local/bin/gatherd-await-async`, which blocks until the REST run for the deployed commit is over and always exits 0. Environment knobs, all test-only: `GATHERD_HOME`, `GATHERD_ASYNC_SENTINEL`, `GATHERD_CORE_MARKER`, `GATHERD_AWAIT_ASYNC_TIMEOUT`.

- [ ] **Step 1: Write the failing test**

Create `tests/await-async`:

```sh
#!/bin/sh
# Unit tests for gatherd-await-async, the barrier the session cohort waits on.
#
# Each case is a way the barrier could quietly undo the fix it delivers:
#   - it must return AT ONCE on a converged machine, or every login pays for the
#     first one;
#   - it must WAIT while the run is unfinished, or nothing changed;
#   - it must treat a STALE sentinel as unfinished, because site-async.yml
#     overwrites the sentinel without removing it, so after a `git pull` the file
#     is still there holding the old commit while REST re-runs;
#   - it must release on a run that FINISHED AND FAILED, which the sentinel
#     cannot express;
#   - it must release when CORE failed, because REST will then never start;
#   - it must always exit 0, because it is a wait and not a predicate.
#
# Usage: tests/await-async

set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
BARRIER="$REPO/scripts/gatherd-await-async"
PASS=0
FAIL=0

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }
assert() { _d=$1; shift; if [ "$@" ]; then ok "$_d"; else bad "$_d"; fi; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
HOMEDIR="$WORK/gatherd"
mkdir -p "$HOMEDIR/scripts" "$WORK/nohome"
cp "$REPO/scripts/gatherd-needs-run" "$HOMEDIR/scripts/"
git -C "$HOMEDIR" init -q
git -C "$HOMEDIR" -c user.email=t@t -c user.name=t commit -q --allow-empty -m base
HEAD=$(git -C "$HOMEDIR" rev-parse HEAD)

SENTINEL="$WORK/async-complete"
STAMP="$WORK/async-complete-finished"
LASTRUN="$WORK/last-run"
printf 'ok\n' > "$LASTRUN"

run_barrier() {
    _start=$(date +%s)
    GATHERD_HOME="$HOMEDIR" GATHERD_ASYNC_SENTINEL="$SENTINEL" \
        GATHERD_CORE_MARKER="$LASTRUN" "$@" sh "$BARRIER" >/dev/null 2>&1 && RC=0 || RC=$?
    ELAPSED=$(( $(date +%s) - _start ))
}

# 1. Converged: sentinel records the deployed HEAD. Every login after the first.
printf '%s\n' "$HEAD" > "$SENTINEL"
run_barrier env
assert "returns at once when the sentinel is current (${ELAPSED}s)" "$ELAPSED" -le 1
assert "and exits 0 (rc=$RC)" "$RC" -eq 0

# 2. Stale sentinel and no stamp: what every boot after a `git pull` looks like
#    while REST re-runs. An existence test would return instantly here.
printf '%s\n' 0000000000000000000000000000000000000000 > "$SENTINEL"
rm -f "$STAMP"
run_barrier env GATHERD_AWAIT_ASYNC_TIMEOUT=3
assert "waits on a stale sentinel (${ELAPSED}s)" "$ELAPSED" -ge 2
assert "and exits 0 at the bound (rc=$RC)" "$RC" -eq 0

# 3. A stale stamp is no better than a stale sentinel.
printf '%s\n' 0000000000000000000000000000000000000000 > "$STAMP"
run_barrier env GATHERD_AWAIT_ASYNC_TIMEOUT=3
assert "waits on a stale stamp (${ELAPSED}s)" "$ELAPSED" -ge 2

# 4. The run finished and FAILED: no fresh sentinel will ever appear, but the
#    tiers are over. Without this the cohort waits out the bound after every
#    failure.
printf '%s\n' "$HEAD" > "$STAMP"
run_barrier env GATHERD_AWAIT_ASYNC_TIMEOUT=60
assert "releases on a finished-but-failed run (${ELAPSED}s)" "$ELAPSED" -le 5
assert "and exits 0 (rc=$RC)" "$RC" -eq 0

# 5. The stamp landing mid-wait releases it -- the actual first-boot sequence,
#    where the barrier is already blocked when the run ends.
rm -f "$STAMP"
( sleep 2; printf '%s\n' "$HEAD" > "$STAMP" ) &
run_barrier env GATHERD_AWAIT_ASYNC_TIMEOUT=60
wait
assert "releases when the stamp lands mid-wait (${ELAPSED}s)" "$ELAPSED" -le 10
assert "and not before it landed (${ELAPSED}s)" "$ELAPSED" -ge 2

# 6. CORE failed: gatherd-await-and-run blocks before the playbook, so REST never
#    starts and no stamp is ever written. A broken machine is exactly when the
#    tray and the polkit agent are wanted.
rm -f "$STAMP"
printf 'timeout\n/var/log/gatherd.log\n' > "$LASTRUN"
run_barrier env GATHERD_AWAIT_ASYNC_TIMEOUT=60
assert "releases when CORE did not converge (${ELAPSED}s)" "$ELAPSED" -le 5
assert "and exits 0 (rc=$RC)" "$RC" -eq 0
printf 'ok\n' > "$LASTRUN"

# 7. A checkout git calls foreign must not read as permanently unconverged.
printf '%s\n' "$HEAD" > "$SENTINEL"
run_barrier env GIT_TEST_ASSUME_DIFFERENT_OWNER=1 HOME="$WORK/nohome" GATHERD_AWAIT_ASYNC_TIMEOUT=6
assert "returns at once on a foreign-owned checkout (${ELAPSED}s)" "$ELAPSED" -le 1

# 8. Always exits 0 is an invariant, not an aspiration: a garbage bound must not
#    throw under `set -u`.
run_barrier env GATHERD_AWAIT_ASYNC_TIMEOUT=abc
assert "a non-numeric bound still exits 0 (rc=$RC)" "$RC" -eq 0
assert "and does not hang (${ELAPSED}s)" "$ELAPSED" -le 5

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

`chmod 755 tests/await-async`.

- [ ] **Step 2: Run it to verify it fails**

Run: `tests/await-async`
Expected: FAIL — `scripts/gatherd-await-async` does not exist.

- [ ] **Step 3: Write the barrier**

Create `scripts/gatherd-await-async`:

```sh
#!/bin/sh
# Barrier for session helpers whose subject the REST tier installs. Blocks until
# the REST run for the deployed commit is over -- converged, failed, or never
# going to start -- then always exits 0.
#
# Why: gatherd-session-helpers starts the cohort the instant sway starts, which
# on a repave is minutes before REST installs the things the cohort is about.
# Measured on the 2026-09-07 repave of this machine (session start 11:33:55, from
# `ps -o lstart=` on the supervisor; the rest from /var/log/pacman.log):
#
#     11:35:26  tailscale, conky, wayvnc
#     11:37:48  nowayprompt
#     11:44:16  1password
#     11:44:17  helium-browser-bin, arch-update, cmd-polkit-git, captive-browser-git
#     11:49:44  /etc/gatherd/async-complete
#
# Every helper that probed for its subject found nothing and exited quietly:
# `pgrep -g` on the supervisor found zero surviving children afterwards. The
# freshly paved machine never opened the Tailscale or 1Password tabs the human
# had to act on, and nothing retried until the next login.
#
# A barrier, not a probe. Helpers keep their own readiness logic; this only stops
# them running it against a machine that has not finished installing.
#
# Contains no systemctl call, deliberately. An earlier draft asked
# `systemctl is-failed`, which is wrong three measured ways -- `inactive` after a
# converged run, rc=4 for an unknown unit, and false while a CORE failure has the
# runner blocked before the playbook. Reading gatherd's own files instead is both
# correct and one less thing the Artix/s6 rebase has to answer.
#
# Always exits 0. It is a wait, not a predicate -- a helper must never be
# suppressed because the barrier itself could not decide.
set -u

gatherd_home="${GATHERD_HOME:-/usr/local/lib/gatherd}"

# Overridable only so the wait can be exercised in tests. On a converged machine
# the real files are always present, so without these the property that matters
# most -- that it actually waits -- is the one no test can reach.
sentinel="${GATHERD_ASYNC_SENTINEL:-/etc/gatherd/async-complete}"
core_marker="${GATHERD_CORE_MARKER:-/etc/gatherd/last-run}"
stamp="${sentinel}-finished"

# Freshness, not existence. site-async.yml overwrites the sentinel at the end of
# a run and never removes it at the start, so after a `git pull` the file is
# still on disk holding the OLD commit while REST re-runs the whole tier. A test
# for existence would return instantly on exactly the boots where a newly added
# helper most needs to wait.
#
# Only exit 1 means converged. A missing or non-executable script exits 127, and
# treating that as converged would silently turn this barrier into a no-op.
current() {
    "$gatherd_home/scripts/gatherd-needs-run" "$1"
    [ "$?" -eq 1 ]
}

# A bound, so a hung run cannot hold the cohort for a whole session. Validated
# rather than trusted: `$(( ${VAR:-3600} ))` on a non-numeric value throws under
# `set -u`, which would break the always-exit-0 invariant this file states twice.
timeout=${GATHERD_AWAIT_ASYNC_TIMEOUT:-3600}
case "$timeout" in
'' | *[!0-9]*) timeout=3600 ;;
esac
deadline=$(( $(date +%s) + timeout ))

while :; do
    # The run converged at this commit.
    current "$sentinel" && break

    # Or it ran and ended badly. site-async.yml writes its sentinel only when no
    # tier failed, so this stamp is the only thing that can say "over" about a
    # failed run. gatherd-await-and-run writes it on every exit path.
    current "$stamp" && break

    # Or CORE never converged, in which case gatherd-await-and-run is blocked
    # before the playbook and REST will not start at all this boot. Waiting for
    # it would cost an hour of no tray and no polkit agent at exactly the moment
    # a broken machine needs them.
    [ -f "$core_marker" ] && [ "$(head -n1 "$core_marker" 2>/dev/null)" != ok ] && break

    [ "$(date +%s)" -lt "$deadline" ] || break
    sleep 2
done

exit 0
```

`chmod 755 scripts/gatherd-await-async`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `shellcheck scripts/gatherd-await-async tests/await-async && tests/await-async`
Expected: `14 passed, 0 failed`.

- [ ] **Step 5: Prove the tests are not vacuous**

Temporarily delete the `current "$stamp" && break` line, re-run `tests/await-async`, and confirm case 4 fails. Restore it. Do the same for the `case "$timeout"` validation and confirm case 8 fails. A test that passes with its subject removed is not a test.

- [ ] **Step 6: Install it from CORE**

In `roles/desktop/tasks/core.yml`, immediately after the `Install gatherd-session-helpers supervisor script` task, add:

```yaml
# The barrier gatherd-session-helpers puts its REST-dependent cohort behind. CORE
# rather than REST for the same reason the supervisor itself is: it has to exist
# at the FIRST login, which is the only login it changes anything on.
- name: Install gatherd-await-async barrier script
  ansible.builtin.copy:
    src: "{{ setup_dir }}/scripts/gatherd-await-async"
    dest: "{{ target_home }}/.local/bin/gatherd-await-async"
    mode: '0755'
    remote_src: true
```

- [ ] **Step 7: Wire the suite in and commit**

Add `await-async` to the `for suite in ...` list in `tests/gates`.

```bash
git add scripts/gatherd-await-async tests/await-async tests/gates roles/desktop/tasks/core.yml
git commit -m "Wait for the REST run to end before starting the helpers that need it"
```

## Task 7: Give the cohort three launch forms

**Files:**
- Modify: `scripts/gatherd-session-helpers` (the `run()` definition at line 42, and the cohort block at lines 68-118)

**Interfaces:**
- Consumes: `~/.local/bin/gatherd-await-async` from Task 6.
- Produces: three launch forms the gate in Task 8 parses — `start_now "<cmd>"  # needs: <pkg>...`, `start_later "<cmd>"` inside the `{ … } &` block below the barrier call, and `start_when <command> "<cmd>"` outside it.

- [ ] **Step 1: Replace the `run()` definition**

Delete line 42 (`run() { sh -c "$1" & }`).

- [ ] **Step 2: Fix the orphan sweep to skip by pid**

The `{ … } &` block added below is the first long-lived subshell in this file, and a backgrounded `{ }` subshell keeps the parent's argv — measured. So the existing name-based skip would spare a *leaked* one from a previous session, which then sits in the barrier and launches a duplicate cohort into a later session: a second polkit agent, a second conky, a second wayvnc fighting for 127.0.0.1:5900.

In the sweep loop, replace the `case`/`continue` name test with a pid test. The two processes that must survive are this shell and the `setsid -w` that launched it:

```sh
for _pid in $(pgrep -f "$bin/gatherd-" 2>/dev/null); do
    # Skip by pid, not by name. A backgrounded `{ … } &` subshell inherits this
    # script's argv, so a name test would also spare one LEAKED by a previous
    # session -- which would then wake from the barrier and launch a whole second
    # cohort into this one. Only two processes are genuinely ours: this shell,
    # and the `setsid -w` waiting on it.
    #
    # gatherd-show-slow-progress still needs sparing: it is a current-session
    # sibling sway `exec` in its own process group, and its `foot` wrapper's
    # cmdline matches the glob above. It self-terminates once the run is over.
    [ "$_pid" = "$$" ] && continue
    [ "$_pid" = "$PPID" ] && continue
    case "$(ps -o args= -p "$_pid" 2>/dev/null)" in
        *gatherd-show-slow-progress*) continue ;;
    esac
    _pgid=$(ps -o pgid= -p "$_pid" 2>/dev/null | tr -d ' ')
    [ -n "$_pgid" ] && [ "$_pgid" != "$$" ] && kill -KILL -- "-$_pgid" 2>/dev/null
done
```

- [ ] **Step 3: Replace the cohort block**

Replace lines 68-118 (from `# The cohort: long-running session helpers` through the last `run "..."` line) with:

```sh
# The cohort: long-running session helpers gatherd autostarts. One-shots and
# things with their own lifecycle (swayidle, gatherd-show-slow-progress) stay as
# plain sway `exec` lines and are intentionally not listed here.
#
# Three launch forms, split on WHEN each helper's subject exists. sway starts
# this the instant the session does, which on a repave is minutes before the REST
# tier installs what most of these helpers are about. A helper started ahead of
# its subject probes, finds nothing, and exits without saying so; measured on the
# 2026-09-07 repave, that silently lost every one of them for the whole first
# session, including the Tailscale and 1Password browser tabs that are the only
# reason a fresh machine needs a human at all. scripts/gatherd-await-async
# carries the measurements.
#
#   start_now    immediate. Carries a `# needs:` declaration of the packages that
#                must already be installed. CORE installs no packages, so that
#                means "in tests/base-manifest.txt" and nothing else;
#                scripts/gatherd-check-session-cohort enforces exactly that, and
#                an undeclared start_now is a hard failure rather than a silent
#                bet.
#   start_later  behind the barrier, inside the block below. The default. When in
#                doubt use it: waiting costs a converged machine nothing (the
#                barrier returns at once) and costs a repave only the minutes
#                during which the helper had nothing to work with anyway.
#   start_when   behind a wait for one named command. For the helper whose
#                subject lands materially earlier than the end of the run.
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }

# Bounded the same way the barrier is, and always proceeds: a helper must never
# be suppressed because a wait could not decide.
start_when() {
    _cmd=$1
    shift
    sh -c '
        _n=0
        while ! command -v "$1" >/dev/null 2>&1; do
            _n=$((_n + 1))
            [ "$_n" -ge 1800 ] && break
            sleep 2
        done
        shift
        exec sh -c "$1"
    ' _ "$_cmd" "$1" &
}

# --- Immediately: needed DURING the pave, and subject is already in base ---

# xdg-desktop-portal's systemd unit has Requisite=graphical-session.target, which
# we don't activate (init-agnostic design). Start it directly so the Requisite
# check is bypassed; the backends (xdg-desktop-portal-gtk for Qt Settings/dark mode)
# only have PartOf/After, not Requisite, so they D-Bus-activate fine once this runs.
start_now "/usr/lib/xdg-desktop-portal"  # needs: xdg-desktop-portal
# A watcher, not a probe, so it is immediate even though captive-browser itself
# arrives with REST: what it needs at start is nmcli, and it must already be
# listening when a portal appears. It cannot actually clear one during a pave --
# nothing in the base image can, measured -- so it says so instead; see the
# notification in the script.
start_now "$bin/gatherd-prompt-captiveportal"  # needs: networkmanager coreutils procps-ng sway
# Reports the CORE run's outcome, which is settled before the greeter appears.
start_now "$bin/gatherd-prompt-lastrun"  # needs: libnotify

# --- When its own renderer exists ---

# It looks like it belongs above -- it exists to unblock site-vault.yml while the
# pave is still running -- and it cannot go there: it prompts through
# SUDO_ASKPASS, i.e. gatherd-askpass, which renders with nowayprompt, a REST
# package. Nor does it belong behind the barrier, because nowayprompt lands at
# ~11:37 and the run does not end until ~11:49, and those twelve minutes are the
# difference between the WiFi configuration landing during the pave or after it.
start_when nowayprompt "$bin/gatherd-prompt-vault"

# --- Behind the barrier: subject is installed by the REST tier ---
#
# One barrier for the whole group rather than one per helper, so relative launch
# order is preserved (localsend's flash interceptor must still start just ahead
# of localsend) and the wait is polled once instead of a dozen times. The group
# is a child of this supervisor, so it stays in our process group and the
# teardown below still reaps it.
{
    "$bin/gatherd-await-async"

    # The polkit agent belongs here, not as a standalone sway `exec`: launched as a
    # cohort child it shares our process group, so the stale-orphan sweep above
    # spares it and we reap it on logout — a standalone exec sat in its own group and
    # the sweep SIGKILL'd the fresh agent every login (its `cmd-polkit-agent -c
    # .../gatherd-polkit-agent` cmdline matches the gatherd- glob). Launch it first so
    # it is registered before anything can trigger a polkit prompt.
    start_later "$bin/gatherd-polkit-agent"
    # wayvnc as a cohort child, not a plain sway `exec`: a plain exec would orphan on
    # logout (sway reaps nothing) and keep holding 127.0.0.1:5900, so the next
    # session's wayvnc could not bind. As a cohort child it dies with the group on
    # logout, freeing the port. VNC is localhost-only, reached over SSH — plans/VNC.md.
    start_later "wayvnc"
    start_later "$bin/gatherd-conky"
    # Only installed on has_dual_accelerometer machines (roles/desktop/tasks/
    # tablet_mode_upstream.yml); starting a missing binary just fails quietly like
    # any other cohort member would on hardware that lacks it.
    start_later "$bin/minibook-hinge-daemon"
    start_later "$bin/gatherd-prompt-1password"
    start_later "$bin/gatherd-prompt-tailscale"
    # Behind the barrier so its detection sees the finished machine. Run ahead of
    # REST it writes "Sign in to 1Password" against a machine where 1Password is
    # not installed yet, and then -- because each section is only added once --
    # never revisits the sections it got wrong.
    start_later "$bin/gatherd-prompt-postsetup"
    start_later "$bin/gatherd-prompt-pia"
    start_later "$bin/gatherd-prompt-icloud"
    # One-shot, not a watcher: it rate-limits itself and exits. Login only, unlike
    # iCloud's extra unlock trigger — the Mac it pulls from is usually asleep, and
    # scores change on the order of weeks, so retrying on every unlock would buy
    # nothing but wakeups.
    start_later "$bin/gatherd-musicscores-fetch --if-due"
    start_later "env XDG_CURRENT_DESKTOP=GNOME $bin/gatherd-systray 1password --silent"
    # Stash LocalSend's startup-window flash before it reaches the screen. Must be
    # launched just ahead of localsend so it is already subscribed when the first
    # surface maps (see scripts/gatherd-intercept-localsend-flash).
    start_later "$bin/gatherd-intercept-localsend-flash"
    start_later "$bin/gatherd-systray localsend --hidden"
    start_later "$bin/gatherd-systray tailscale systray"
    # Sign-in apps (JetBrains Toolbox, Discord/vesktop, Slack, Zoom, …) are
    # deliberately never autostarted — not here and not during provisioning. They
    # are just installed; open them on demand and sign in via 1Password when needed.
    # Nothing special about them, and starting them on every login wastes a potato.
    start_later "$bin/gatherd-systray /opt/piavpn/bin/pia-client --quiet"
    start_later "$bin/gatherd-systray arch-update --tray"
} &
```

- [ ] **Step 4: Update the stale cross-reference**

`scripts/gatherd-prompt-vault:17` names `run() { sh -c "$1" & }`, which no longer exists. Change it to `start_when() { … }`.

- [ ] **Step 5: Smoke-test the launcher in isolation**

Build a sandbox with stubs for every cohort target that append `date +%s.%N` plus their own name to a log, a `gatherd-await-async` stub that sleeps 2s, and a `swaymsg` stub that answers `get_version` then blocks 4s. Run with `HOME` and `PATH` pointed at the sandbox.

Run: the sandbox launcher, then sort the log.
Expected: the three `start_now` members at t≈0; `gatherd-prompt-vault` at t≈0 (its stub `nowayprompt` exists); the barrier's members at t≈2, in declared order, with `gatherd-intercept-localsend-flash` ahead of `gatherd-systray localsend`.

- [ ] **Step 6: Commit**

```bash
git add scripts/gatherd-session-helpers scripts/gatherd-prompt-vault
git commit -m "Start each session helper only once the thing it needs exists"
```

## Task 8: Gate the launch forms

**Files:**
- Create: `scripts/gatherd-check-session-cohort`
- Create: `tests/check-session-cohort`
- Modify: `tests/gates`

**Interfaces:**
- Consumes: Task 7's three launch forms.
- Produces: `gatherd-check-session-cohort [repo-root]`, exit 0/1/2.

- [ ] **Step 1: Write the failing test**

Create `tests/check-session-cohort`:

```sh
#!/bin/sh
# Unit tests for gatherd-check-session-cohort.
#
# The cases that matter reproduce the 2026-09-07 repave: a helper started ahead
# of a package the REST tier installs, and a helper that never said what it
# needed. The rest pin the ways a gate like this goes quietly useless -- a
# missing or commented-out barrier, a launch that sits outside the block that
# waits, an unreadable input reported as "could not run" rather than "clean".
#
# Usage: tests/check-session-cohort

set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
GATE="$REPO/scripts/gatherd-check-session-cohort"
PASS=0
FAIL=0

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/scripts" "$WORK/tests" "$WORK/roles/desktop/tasks"

# A two-package base: one thing that ships with the machine, and nothing else.
# Anything not named here is, by definition, installed by REST.
printf 'networkmanager\nfuzzel\nlibfoo-bar\n' > "$WORK/tests/base-manifest.txt"

# The gate also asserts the barrier is real and installed, so the sandbox needs
# both -- otherwise deleting the install task would leave every case green while
# the barrier degraded to a no-op.
printf '#!/bin/sh\nexit 0\n' > "$WORK/scripts/gatherd-await-async"
chmod 755 "$WORK/scripts/gatherd-await-async"
printf -- '- name: Install gatherd-await-async barrier script\n  ansible.builtin.copy:\n    src: "{{ setup_dir }}/scripts/gatherd-await-async"\n' \
    > "$WORK/roles/desktop/tasks/core.yml"

helpers() { cat > "$WORK/scripts/gatherd-session-helpers"; }

assert_rc() {
    _d=$1; _want=$2
    if "$GATE" "$WORK" >"$WORK/out" 2>&1; then _got=0; else _got=$?; fi
    if [ "$_got" = "$_want" ]; then ok "$_d"; else bad "$_d (want rc=$_want got rc=$_got)"; sed 's/^/       /' "$WORK/out"; fi
}
assert_says() {
    _d=$1; _want=$2
    if grep -q -- "$_want" "$WORK/out"; then ok "$_d"; else bad "$_d (no '$_want' in output)"; sed 's/^/       /' "$WORK/out"; fi
}

# 1. All three forms used properly.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_when()  { shift; sh -c "$1" & }
start_now "$bin/watcher"  # needs: networkmanager
start_when nowayprompt "$bin/gatherd-prompt-vault"
{
    "$bin/gatherd-await-async"
    start_later "$bin/gatherd-prompt-tailscale"
} &
EOF
assert_rc "a correct cohort exits 0" 0

# 2. The actual bug: started immediately, subject arrives with REST.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_now "$bin/gatherd-prompt-tailscale"  # needs: tailscale
{
    "$bin/gatherd-await-async"
    start_later "$bin/other"
} &
EOF
assert_rc "start_now needing a REST package fails" 1
assert_says "and names the package" "needs 'tailscale'"

# 3. Silence is not a pass: an undeclared start_now must fail, so the author
#    answers the question rather than skipping it.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_now "$bin/gatherd-prompt-tailscale"
{
    "$bin/gatherd-await-async"
    start_later "$bin/other"
} &
EOF
assert_rc "undeclared start_now fails" 1
assert_says "and says what is missing" "no \`# needs:\` declaration"

# 4. Several packages on one line, one of them bad.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_now "$bin/watcher"  # needs: networkmanager conky fuzzel
{
    "$bin/gatherd-await-async"
    start_later "$bin/other"
} &
EOF
assert_rc "one bad package among good ones fails" 1
assert_says "and names the bad one, not the good ones" "needs 'conky'"

# 5. start_later above the block.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_later "$bin/gatherd-prompt-tailscale"
{
    "$bin/gatherd-await-async"
    start_later "$bin/other"
} &
EOF
assert_rc "start_later above the block fails" 1
assert_says "and says it does not wait" "does not wait"

# 6. start_later below the closing `} &`. A line-number test passes this,
#    because its line number is greater than the barrier's.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
{
    "$bin/gatherd-await-async"
    start_later "$bin/first"
} &
start_later "$bin/gatherd-prompt-tailscale"
EOF
assert_rc "start_later below the closing brace fails" 1
assert_says "and says it does not wait" "does not wait"

# 7. start_later inside the block but ABOVE the barrier call -- the most natural
#    mistake to make, dropping a new helper at the top of the block. A test that
#    only checks the block's bounds passes this.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
{
    start_later "$bin/RACES-THE-BARRIER"
    "$bin/gatherd-await-async"
    start_later "$bin/ok"
} &
EOF
assert_rc "start_later above the barrier inside the block fails" 1
assert_says "and says it does not wait" "does not wait"

# 8. A commented-out barrier: every start_later reads as gated and waits for
#    nothing. A grep for the name alone matches the comment.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
{
#   "$bin/gatherd-await-async"
    start_later "$bin/gatherd-prompt-tailscale"
} &
EOF
assert_rc "a commented-out barrier is rc=2, not a pass" 2
assert_says "and says it is not invoked" "never invokes gatherd-await-async"

# 9. start_now inside the block is delayed despite its name, and its declaration
#    then certifies nothing.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
{
    "$bin/gatherd-await-async"
    start_now "$bin/watcher"  # needs: fuzzel
} &
EOF
assert_rc "start_now inside the block fails" 1
assert_says "and says it is not immediate" "not immediate"

# 10. start_when carries its own wait, so nesting it delays it twice.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_when()  { shift; sh -c "$1" & }
{
    "$bin/gatherd-await-async"
    start_when nowayprompt "$bin/gatherd-prompt-vault"
} &
EOF
assert_rc "start_when inside the block fails" 1
assert_says "and says it already waits" "carries its own wait"

# 11. start_when with no command to wait for waits for nothing.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_when()  { shift; sh -c "$1" & }
start_when "$bin/gatherd-prompt-vault"
{
    "$bin/gatherd-await-async"
    start_later "$bin/other"
} &
EOF
assert_rc "start_when without a command fails" 1
assert_says "and says what is missing" "names no command"

# 12. A launch whose argument is not a quoted string is invisible to every rule
#     above, so it must be rejected rather than skipped.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_later $cmd
{
    "$bin/gatherd-await-async"
    start_later "$bin/other"
} &
EOF
assert_rc "an unquoted launch argument fails" 1
assert_says "and says why nothing can check it" "not a quoted string"

# 13. A package name is a literal, not a regex: a typo must not match its
#     neighbour and certify itself.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_now "$bin/watcher"  # needs: libfoo.bar
{
    "$bin/gatherd-await-async"
    start_later "$bin/other"
} &
EOF
assert_rc "a regex metachar does not match a different package" 1
assert_says "and names the undeclared spelling" "needs 'libfoo.bar'"

# 14. A file that never calls the barrier: start_later would be decoration.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_now "$bin/watcher"  # needs: fuzzel
start_later "$bin/other"
EOF
assert_rc "a missing barrier is rc=2, not a pass" 2

# 15. Prose and definitions are not launches. A file with nothing to check is a
#     could-not-run, not a clean bill of health -- silence is the failure this
#     gate guards against.
helpers <<'EOF'
# start_now is the exception; prefer start_later.
{
    "$bin/gatherd-await-async"
} &
EOF
assert_rc "a file with no launches is rc=2" 2

# 16. The barrier script itself must exist and be installed by a role. Deleting
#     the copy task would otherwise leave this suite green while every
#     start_later waited on a command that is not there.
helpers <<'EOF'
start_now()   { sh -c "$1" & }
start_later() { sh -c "$1" & }
start_now "$bin/watcher"  # needs: fuzzel
{
    "$bin/gatherd-await-async"
    start_later "$bin/other"
} &
EOF
mv "$WORK/roles/desktop/tasks/core.yml" "$WORK/core.yml.bak"
assert_rc "an uninstalled barrier is rc=2" 2
assert_says "and says so" "no role installs"
mv "$WORK/core.yml.bak" "$WORK/roles/desktop/tasks/core.yml"

# 17. Unreadable inputs are rc=2. A gate that returns 0 when it could not look is
#     worse than no gate.
rm -f "$WORK/scripts/gatherd-session-helpers"
assert_rc "an unreadable helpers file is rc=2" 2

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

`chmod 755 tests/check-session-cohort`.

- [ ] **Step 2: Run it to verify it fails**

Run: `tests/check-session-cohort`
Expected: FAIL — `scripts/gatherd-check-session-cohort` does not exist.

- [ ] **Step 3: Write the gate**

Create `scripts/gatherd-check-session-cohort`:

```sh
#!/bin/sh
# Fail if a session helper is started ahead of the thing it needs.
#
# The mistake this catches: gatherd-session-helpers starts its cohort the instant
# sway starts, which on a repave is minutes before the REST tier installs what
# most of those helpers are about. A helper started too early probes for its
# subject, finds nothing, and exits -- silently, with no notification and no log.
# Measured on the 2026-09-07 repave, that lost the entire cohort for the whole
# first session: no Tailscale tab, no 1Password tab, no conky, no tray, no polkit
# agent, and nothing retried until the next login. It went unnoticed for hours
# precisely because the failure mode of every one of them is to say nothing.
#
# The rule for the immediate form is exact, and cheap, because CORE installs no
# packages at all (CLAUDE.md, "No packages, no AUR, no downloads"). So the set of
# packages present at the first login is precisely tests/base-manifest.txt:
#
#     a `start_now` helper may only need packages in tests/base-manifest.txt.
#
# It therefore has to declare what it needs. An undeclared start_now is a hard
# failure rather than a silent bet -- writing the declaration is the moment the
# author asks the question this gate exists to force.
#
# WHAT THIS DOES NOT DO. It checks DECLARED START-TIME needs. It cannot verify a
# declaration is complete, or honest, and it says nothing about what a helper
# reaches for later: gatherd-prompt-captiveportal legitimately declares only base
# packages and still cannot clear a portal during a pave, because captive-browser
# is itself a REST package and the base image has no browser at all. That case is
# irreducible -- no ordering fixes it -- so the helper announces its inability at
# runtime instead. Do not read a green run here as "every helper can do its job".
#
# DECLARED, not present: this reads the repo, never the machine it runs on. A
# converged machine has everything installed, so "does it work here" would pass
# for every possible ordering and catch nothing.
#
# Exit 0 clean, 1 violation, 2 could not run. Never a silent skip.
#
# Usage: gatherd-check-session-cohort [repo-root]
set -u

repo="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
helpers="$repo/scripts/gatherd-session-helpers"
manifest="$repo/tests/base-manifest.txt"
barrier=gatherd-await-async

die() { printf 'gatherd-check-session-cohort: %s\n' "$1" >&2; exit 2; }

[ -r "$helpers" ]  || die "cannot read $helpers"
[ -r "$manifest" ] || die "cannot read $manifest"

# The barrier has to exist and to be installed, or every start_later waits on a
# command that is not there and the whole mechanism is decoration.
[ -f "$repo/scripts/$barrier" ] || die "$repo/scripts/$barrier does not exist"
grep -rql "scripts/$barrier" "$repo/roles" >/dev/null 2>&1 \
    || die "no role installs scripts/$barrier"

# Locate the gated block, so "behind the barrier" is a fact about nesting rather
# than a guess from line numbers. A bare line-number test passes four different
# ways of not waiting: a start_later after the closing `} &`, one at the top of
# the block above the barrier call, a barrier invocation commented out, and a
# start_now buried inside the block.
#
# The leading-quote anchor is what rules out a comment, which
# `#   "$bin/gatherd-await-async"` would otherwise satisfy.
barrier_line=$(grep -n "^[[:space:]]*\"[^\"]*/$barrier\"[[:space:]]*$" "$helpers" | head -1 | cut -d: -f1)
[ -n "$barrier_line" ] \
    || die "$helpers never invokes $barrier as a command; start_later would not wait"

open_line=$(awk -v b="$barrier_line" 'NR < b && /^[[:space:]]*\{[[:space:]]*$/ { n = NR } END { print n }' "$helpers")
close_line=$(awk -v b="$barrier_line" 'NR > b && /^[[:space:]]*\}[[:space:]]*&[[:space:]]*$/ { print NR; exit }' "$helpers")
[ -n "$open_line" ]  || die "no \`{\` opening a block above the $barrier call on line $barrier_line"
[ -n "$close_line" ] || die "no \`} &\` closing the block opened on line $open_line"

rc=0
fail() { printf 'FAIL %s\n' "$1" >&2; rc=1; }

# Every launch, however written. Two greps because the rules below need a quoted
# argument to reason about, and a launch written without one -- `start_later
# $cmd` -- would otherwise be invisible to all of them. Written to files so the
# loop runs in THIS shell: a `grep | while` pipeline counts failures in a
# subshell and always reports success.
all=$(mktemp) || die "mktemp failed"
launches=$(mktemp) || die "mktemp failed"
trap 'rm -f "$all" "$launches"' EXIT
grep -n '^[[:space:]]*start_\(now\|later\|when\)[[:space:]]' "$helpers" \
    | grep -v '^[0-9]*:[[:space:]]*start_[a-z]*()' | sort -n -t: -k1,1 > "$all"
grep -n '^[[:space:]]*start_\(now\|later\)[[:space:]]*"' "$helpers" > "$launches"
grep -n '^[[:space:]]*start_when[[:space:]][^[:space:]]*[[:space:]]*"' "$helpers" >> "$launches"
sort -n -t: -k1,1 "$launches" -o "$launches"
[ -s "$all" ] || die "no start_now/start_later/start_when launches found in $helpers"

if [ "$(wc -l < "$all")" -ne "$(wc -l < "$launches")" ]; then
    comm -13 "$launches" "$all" | while IFS= read -r entry; do
        printf 'FAIL line %s: launch argument is not a quoted string, so nothing here can check it\n' \
            "${entry%%:*}" >&2
    done
    rc=1
fi

while IFS= read -r entry; do
    lineno=${entry%%:*}
    line=${entry#*:}
    # The leading TOKEN, not a substring: a command containing the string
    # "start_later" must not be diagnosed as one.
    form=$(printf '%s' "$line" | sed -n 's/^[[:space:]]*\(start_[a-z]*\).*/\1/p')

    inside=no
    [ "$lineno" -gt "$open_line" ] && [ "$lineno" -lt "$close_line" ] && inside=yes

    case "$form" in
    start_later)
        # Against the BARRIER line, not the block's opening brace: a start_later
        # at the top of the block is inside it and still races the pave.
        if [ "$inside" = no ] || [ "$lineno" -lt "$barrier_line" ]; then
            fail "line $lineno: start_later is not below the $barrier call inside the block (lines $open_line-$close_line, barrier on $barrier_line), so it does not wait"
        fi
        continue
        ;;
    start_when)
        [ "$inside" = no ] || fail \
            "line $lineno: start_when is inside the block, which already waits on $barrier -- it carries its own wait and belongs outside"
        # `start_when <command> "<cmd>"`: two arguments, the first unquoted.
        printf '%s' "$line" | grep -q '^[[:space:]]*start_when[[:space:]][^[:space:]"]\{1,\}[[:space:]]*"' \
            || fail "line $lineno: start_when names no command to wait for"
        continue
        ;;
    esac

    # start_now from here down.
    if [ "$inside" = yes ]; then
        fail "line $lineno: start_now is inside the block that waits on $barrier, so it is not immediate -- use start_later"
        continue
    fi

    case "$line" in
    *'#'*needs:*) ;;
    *)
        fail "line $lineno: start_now with no \`# needs:\` declaration -- name what must already be installed, or use start_later"
        continue
        ;;
    esac

    needs=${line#*needs:}
    if [ -z "$(printf '%s' "$needs" | tr -d '[:space:]')" ]; then
        fail "line $lineno: empty \`# needs:\` declaration"
        continue
    fi
    # -F, not a plain -x: a package name is a literal. `libfoo.bar` matched
    # `libfoo-bar` as a regex, so a typo could certify itself.
    for pkg in $needs; do
        grep -qxF -- "$pkg" "$manifest" || fail \
            "line $lineno: start_now needs '$pkg', absent from tests/base-manifest.txt -- CORE installs no packages, so it is not there at the first login; use start_later"
    done
done < "$launches"

exit "$rc"
```

`chmod 755 scripts/gatherd-check-session-cohort`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `shellcheck scripts/gatherd-check-session-cohort tests/check-session-cohort && tests/check-session-cohort && scripts/gatherd-check-session-cohort .`
Expected: all cases pass, then exit 0 against the real tree.

- [ ] **Step 5: Wire it in and commit**

Add `run "$REPO/scripts/gatherd-check-session-cohort" "$REPO"` to the gates block and `check-session-cohort` to the suite list.

```bash
git add scripts/gatherd-check-session-cohort tests/check-session-cohort tests/gates
git commit -m "Check that each session helper waits for what it needs"
```

---

# Phase 3 — The irreducible case, and the notes

## Task 9: Make the captive-portal watcher say what it cannot do

**Files:**
- Modify: `scripts/gatherd-prompt-captiveportal`
- Modify: `scripts/gatherd-post-setup-notes` (the `section_verify` block)

**Interfaces:**
- Consumes: nothing.
- Produces: a desktop notification on a portal detected with no `captive-browser` installed.

- [ ] **Step 1: Add the announcement**

In the portal-detected branch, before the existing `captive-browser` launch, add:

```sh
# captive-browser and the helium profile it drives are both AUR packages the
# REST tier installs -- and a portal is exactly what stops REST fetching them.
# Measured: the base image contains no browser at all, not netsurf, firefox,
# chromium, epiphany, falkon, qutebrowser, links, lynx, w3m or elinks, only the
# webkit2gtk-4.1 library. So during a first pave there is genuinely nothing to
# launch, and the only useful thing this watcher can do is say so rather than
# go quiet. libnotify and mako are both in tests/base-manifest.txt, so this
# reaches the screen at the first login.
command -v captive-browser >/dev/null 2>&1 || {
    printf '\n===== portal detected %s; captive-browser not installed yet =====\n' \
        "$(date '+%F %T')" >>"$log"
    notify-send --urgency=critical --icon=dialog-warning --expire-time=300000 \
        "Captive portal" \
        "This network needs a sign-in, and captive-browser is not installed yet. Clear the portal from another device, or connect to a different network -- setup cannot download anything until you do."
    continue
}
```

Verify `continue` is valid at that point in the `while read` loop; if the branch is inside a `case`, restructure so the guard runs before the `pgrep`/launch and skips to the next event.

- [ ] **Step 2: Test it by hand**

Run: `PATH=/nonexistent:/usr/bin sh -c 'command -v captive-browser || notify-send "Captive portal" "test"'`
Expected: the notification appears on screen with the crimson-adjacent mako styling.

Then re-read the script and confirm the guard cannot fire on a machine where `captive-browser` *is* installed.

- [ ] **Step 3: Replace the unrunnable verify step**

The draft step used `GATHERD_ASYNC_SENTINEL=… GATHERD_AWAIT_ASYNC_TIMEOUT=5 time ~/.local/bin/gatherd-await-async`. Leading assignments demote `time` from shell keyword to command word, and `/usr/bin/time` is not installed here — measured, it fails with `time: command not found`. Replace that `verify_li` with:

```sh
    verify_li 'The cohort waits for REST rather than racing it: `~/.local/bin/gatherd-await-async; echo done` returns immediately on this converged machine, and `env GATHERD_ASYNC_SENTINEL=/nonexistent GATHERD_AWAIT_ASYNC_TIMEOUT=5 ~/.local/bin/gatherd-await-async; echo done` takes about 5s. On a fresh pave the Tailscale and 1Password tabs open without logging out and back in.'
```

- [ ] **Step 4: Run the full suite**

Run: `shellcheck scripts/gatherd-prompt-captiveportal scripts/gatherd-post-setup-notes && tests/gates && ansible-lint roles/desktop/tasks/core.yml`
Expected: `shellcheck` silent, `tests/gates` all green, `ansible-lint` `Passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/gatherd-prompt-captiveportal scripts/gatherd-post-setup-notes
git commit -m "Say so when a captive portal appears before the browser that clears it"
```

## Task 10: Converge this machine and confirm

**Files:** none.

- [ ] **Step 1: Deploy and converge**

Push, then on the machine: `sudo git -C /usr/local/lib/gatherd pull`, then `sudo systemctl start gatherd.service` followed by `sudo systemctl start gatherd-async.service`.

- [ ] **Step 2: Confirm the barrier is instant here**

Run: `time ~/.local/bin/gatherd-await-async`
Expected: returns in well under a second — this machine is converged.

- [ ] **Step 3: Confirm it waits when it should**

Run: `env GATHERD_ASYNC_SENTINEL=/nonexistent GATHERD_AWAIT_ASYNC_TIMEOUT=5 ~/.local/bin/gatherd-await-async; echo done`
Expected: about 5 seconds, then `done`.

- [ ] **Step 4: Confirm REST no longer waits on the vault**

Run: `grep ExecStart /etc/systemd/system/gatherd-async.service /etc/systemd/system/gatherd-vault.service`
Expected: only the vault unit carries `--needs-vault`.

- [ ] **Step 5: Confirm the finished stamp exists**

Run: `ls -l /etc/gatherd/async-finished && head -1 /etc/gatherd/async-finished && git -C /usr/local/lib/gatherd rev-parse HEAD`
Expected: the stamp exists and its contents match HEAD.
