# Hardware Profile Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `tests/test` run the `hardware` role's `when: has_*` paths, so they stop being reviewed by reading only.

**Architecture:** A profile is a YAML file of `has_*` overrides passed to the playbook as `-e @file`; extra-vars outrank `set_fact`, so detection is overridden without touching `machine_facts`. `tests/test <profile>` boots the same snapshot and runs the same playbooks with one extra `-e`. Where QEMU can supply the real hardware (AVX, via `-cpu host`) that is preferred to a forced flag. A `tests/gates` check requires every declared flag to be either in a profile or in an exclusions file with a reason.

**Tech Stack:** bash, QEMU/KVM, Ansible, POSIX sh tests in the style of `tests/check-migrations`.

**Spec:** `docs/superpowers/specs/2026-09-07-hardware-profile-testing-design.md`

## Global Constraints

- Task names read like imperative sentences ("Configure swayidle", not "swayidle config task").
- Use FQCN: `ansible.builtin.*`, `community.general.*`. Never bare module names.
- `ansible-lint` is configured in `.ansible-lint`; run it before committing. `noqa` is a last resort.
- `shellcheck` must pass on every shell script added or modified.
- `tests/gates` must pass before every commit.
- Every `scripts/gatherd-{check,assert}-*` must have a `tests/<same-name>`. No exemption list.
- `tests/test` needs `ap-juicer.local` reachable and a base image from `tests/create-base`. It is minutes-long; `tests/gates` is seconds and is what runs per-commit.
- Do not add a `verify_li` step for anything a test already covers. `section_verify` is at 34 against a threshold of 10.
- Claims about third-party behavior must be measured on this machine and the command cited. Do not take a man page's word for it.

---

### Task 1: Profile mechanism

**Files:**
- Create: `tests/profiles/baseline.yml`
- Create: `tests/profiles/README.md`
- Modify: `tests/test:1-16` (argument handling), `tests/test:102` and `tests/test:147` (the two `ansible-playbook` invocations)

**Interfaces:**
- Produces: `tests/test [profile]` where `profile` is a basename under `tests/profiles/` (default `baseline`). The selected file is passed to both playbook runs as `-e @/usr/local/lib/gatherd/tests/profiles/<profile>.yml`. Later tasks add profiles by dropping a file into that directory; no change to `tests/test` is needed for a new profile.

- [ ] **Step 1: Write the failing test**

Create `tests/profile-selection`:

```sh
#!/bin/sh
# Unit tests for tests/test's profile selection.
#
# tests/test itself boots a VM and takes minutes; this checks only the argument
# handling, which is the part that silently does nothing when it is wrong. A
# profile that does not exist must be a loud failure, because the alternative is
# a run that reports PASS having exercised nothing.
#
# Usage: tests/profile-selection

set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
PASS=0
FAIL=0

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }

# GATHERD_PROFILE_ONLY makes tests/test resolve the profile, print it, and exit
# without booting anything.
resolve() { GATHERD_PROFILE_ONLY=1 "$REPO/tests/test" "$@" 2>&1; }

if [ "$(resolve)" = "baseline" ]; then
    ok "no argument selects baseline"
else
    bad "no argument selects baseline (got '$(resolve)')"
fi

printf 'has_thinkpad_hardware: true\n' > "$REPO/tests/profiles/_selftest.yml"
if [ "$(resolve _selftest)" = "_selftest" ]; then
    ok "a named profile is selected"
else
    bad "a named profile is selected (got '$(resolve _selftest)')"
fi
rm -f "$REPO/tests/profiles/_selftest.yml"

if resolve nosuchprofile >/dev/null 2>&1; then
    bad "an unknown profile exits nonzero"
else
    ok "an unknown profile exits nonzero"
fi
if resolve nosuchprofile 2>&1 | grep -q 'nosuchprofile'; then
    ok "the unknown profile is named"
else
    bad "the unknown profile is named"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `chmod +x tests/profile-selection && tests/profile-selection`
Expected: FAIL — `tests/test` does not understand `GATHERD_PROFILE_ONLY` and will try to reach `ap-juicer.local`.

- [ ] **Step 3: Add profile selection to tests/test**

Insert after `QEMU_PID=""` (currently `tests/test:16`):

```bash
PROFILE="${1:-baseline}"
PROFILE_FILE="$TESTSDIR/profiles/$PROFILE.yml"
[[ -f "$PROFILE_FILE" ]] || {
    echo "No such profile: $PROFILE" >&2
    echo "Available:" >&2
    for p in "$TESTSDIR"/profiles/*.yml; do echo "  $(basename "$p" .yml)" >&2; done
    exit 1
}
# Resolve-and-exit, so tests/profile-selection can check the argument handling
# without booting a machine.
[[ -n "${GATHERD_PROFILE_ONLY:-}" ]] && { echo "$PROFILE"; exit 0; }
```

Note the `trap cleanup EXIT` currently sits above this; move the new block ABOVE
`trap cleanup EXIT` so the resolve-and-exit path does not delete `$DISK`.

Then replace both playbook invocations. Currently `tests/test:102`:

```bash
"${SSH[@]}" "ansible-playbook -e sway_guard_override=true site-core.yml site-async.yml"
```

becomes:

```bash
"${SSH[@]}" "cd /usr/local/lib/gatherd && ansible-playbook -e sway_guard_override=true -e @tests/profiles/$PROFILE.yml site-core.yml site-async.yml"
```

Apply the identical change to the run-2 invocation (currently `tests/test:147`),
which additionally pipes to `tee "$run2_log"` — keep that.

- [ ] **Step 4: Create the baseline profile and the directory README**

`tests/profiles/baseline.yml`:

```yaml
---
# What the VM actually is: an EndeavourOS Sway install on emulated hardware.
# Deliberately empty of has_* overrides -- this is the profile that reproduces
# the historical behaviour of tests/test, so a regression in the mechanism shows
# up as baseline going red rather than as a profile quietly doing nothing.
sway_guard_override: true
```

`tests/profiles/README.md`:

```markdown
# Hardware profiles for tests/test

Each file is a set of `has_*` overrides describing a machine class. Extra-vars
outrank `set_fact`, so these replace what `machine_facts` detected without
touching the role:

    tests/test thinkpad

They do not simulate hardware — QEMU has no Apple SMC to offer. What they
exercise is convergence of a `when: has_*` path: packages resolve and build,
files get written, units get enabled, and run 2 is still clean. Both bugs that
motivated this lived exactly there.

Prefer real hardware where QEMU can supply it. `has_avx` is not in any profile
because `tests/test` passes `-cpu host`, so the guest detects it for real.

Every flag in `roles/machine_facts/defaults/main.yml` must appear in a profile
here or in `tests/profiles/EXCLUSIONS.md` with a reason. `tests/gates` enforces
that, so adding a flag forces a decision rather than allowing an omission.
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `tests/profile-selection`
Expected: `4 passed, 0 failed`

- [ ] **Step 6: Verify the baseline VM run is unchanged**

Run: `tests/test`
Expected: same result as before this task — run 2 clean, health assertions PASS.
This is the only proof that the extra `-e` did not change behaviour. If
`ap-juicer.local` is unreachable, stop and say so rather than skipping it.

- [ ] **Step 7: Lint and commit**

```bash
shellcheck tests/test tests/profile-selection
tests/gates
git add tests/test tests/profile-selection tests/profiles
git commit -m "Let tests/test take a hardware profile"
```

---

### Task 2: Give the VM real AVX

**Files:**
- Modify: `tests/test:45-50` (the `qemu-system-x86_64` invocation)
- Modify: `tests/test:120-143` (health assertions)

**Interfaces:**
- Consumes: `PROFILE`/`PROFILE_FILE` from Task 1.
- Produces: a VM on which `has_avx` is true by detection. `aur_slow_avx_packages` (`claude-code`, `claude-cowork-service`) therefore build during `tests/test`, and the AVX preflight guard runs for real.

- [ ] **Step 1: Confirm the guest currently lacks AVX**

Run: `grep -c avx /proc/cpuinfo` on the host (expect nonzero), then boot the VM
and run the same there.
Expected: host nonzero, guest `0` — QEMU's default CPU model has no AVX. Record
both numbers in the commit message; this is the measurement the change rests on.

- [ ] **Step 2: Add -cpu host**

In the `qemu-system-x86_64` invocation, change:

```bash
    -enable-kvm -m 4096 -smp 2 \
```

to:

```bash
    -enable-kvm -cpu host -m 4096 -smp 2 \
```

Add above the invocation:

```bash
# -cpu host so the guest sees the host's instruction set. has_avx is detected
# from /proc/cpuinfo, and QEMU's default model has none, so without this the
# aur_slow_avx_packages tier and the preflight guard in front of it are dead
# code here -- which is how a guard missing `when: has_avx` reached main.
```

- [ ] **Step 3: Add a health assertion that the AVX path actually ran**

Extend the `REMOTE` heredoc in the health-assertions block, before its final
`exit 1`, with a second member. Insert immediately after the pacman check's
`exit 0`-guarded block:

```sh
if ! grep -q '^flags.*\bavx\b' /proc/cpuinfo; then
    echo "guest has no AVX: -cpu host is not reaching the guest, and the"
    echo "aur_slow_avx_packages tier is silently untested"
    exit 1
fi
if ! pacman -Qq claude-code >/dev/null 2>&1; then
    echo "has_avx is true but claude-code is not installed: the AVX tier did"
    echo "not converge"
    exit 1
fi
```

Update the `if [[ "$health_rc" -ne 0 ]]` message below from
`"FAIL: run 1 left the machine unable to install any package"` to
`"FAIL: run 1 left the machine in a bad state (see above)"`, and the success
line from `"PASS: pacman can prepare a transaction"` to
`"PASS: health assertions"`.

- [ ] **Step 4: Run the VM test**

Run: `tests/test`
Expected: health assertions PASS, run 2 clean. Note that run 1 is now slower —
`claude-code` and `claude-cowork-service` build. If either fails, that is a real
finding: fix it and record it, do not weaken the assertion.

- [ ] **Step 5: Lint and commit**

```bash
shellcheck tests/test
tests/gates
git add tests/test
git commit -m "Give the test VM the host's instruction set"
```

---

### Task 3: The backlight profile

**Files:**
- Create: `tests/profiles/backlight.yml`
- Modify: `tests/test:120-143` (a profile-conditional health assertion)

**Interfaces:**
- Consumes: `PROFILE` from Task 1.
- Produces: `tests/test backlight`, which converges `roles/hardware/tasks/ambient_light.yml` and `roles/hardware/tasks/kbd_backlight.yml`.

- [ ] **Step 1: Write the profile**

`tests/profiles/backlight.yml`:

```yaml
---
# A laptop with a backlight and an ambient light sensor. This is the path that
# cost a repave: clight's undeclared `gsl` broke the whole hardware tier, and
# nothing could catch it because the VM has no backlight. The AUR chain here is
# three rounds deep (libmodule -> clightd -> clight), which is also the only
# place the build/install alternation is exercised at all.
sway_guard_override: true
has_screen_backlight: true
has_kbd_backlight: true
has_ambient_light_sensor: true
```

- [ ] **Step 2: Run it and expect failures to triage**

Run: `tests/test backlight`
Expected: run 1 gets further than baseline ever did. Tasks that write config are
expected to pass; tasks that touch a device node may not. For each failure,
decide and record:
 - a real bug → fix it, and say so in the commit;
 - genuinely impossible without the device → move that flag to
   `tests/profiles/EXCLUSIONS.md` in Task 5 with the task name and the reason.

Do not weaken a task to make the test pass.

- [ ] **Step 3: Add the health assertion**

In the health-assertions block, after the AVX member, add:

```sh
if [ "${GATHERD_PROFILE:-baseline}" = backlight ]; then
    for pkg in libmodule clightd clight; do
        pacman -Qq "$pkg" >/dev/null 2>&1 || {
            echo "backlight profile: $pkg is not installed; the clight chain"
            echo "did not converge"
            exit 1
        }
    done
fi
```

For `GATHERD_PROFILE` to exist in the heredoc, change the `SSH` health
invocation from `"${SSH[@]}" sh -s <<'REMOTE'` to:

```bash
"${SSH[@]}" "GATHERD_PROFILE=$PROFILE sh -s" <<'REMOTE'
```

- [ ] **Step 4: Verify both profiles**

Run: `tests/test` then `tests/test backlight`
Expected: both PASS. `baseline` must still pass — the assertion is conditional.

- [ ] **Step 5: Lint and commit**

```bash
shellcheck tests/test
tests/gates
git add tests/test tests/profiles/backlight.yml
git commit -m "Test the clight chain that cost a repave"
```

---

### Task 4: The fingerprint and thinkpad profiles

**Files:**
- Create: `tests/profiles/fingerprint.yml`, `tests/profiles/thinkpad.yml`
- Modify: `tests/test` (health assertions)

**Interfaces:**
- Consumes: `GATHERD_PROFILE` in the health heredoc, from Task 3.
- Produces: `tests/test fingerprint` and `tests/test thinkpad`.

- [ ] **Step 1: Write the profiles**

`tests/profiles/fingerprint.yml`:

```yaml
---
# A laptop with a fingerprint reader. Reaches the second multi-round AUR chain
# (fprintd-clients-git -> open-fprintd -> python-validity), which is where
# python-cryptography turned out to be undeclared -- present on every machine
# only because ansible-core happens to depend on it.
sway_guard_override: true
has_fingerprint_reader: true
```

`tests/profiles/thinkpad.yml`:

```yaml
---
# A ThinkPad: the embedded controller, its trackpoint, and thinkfan, which is
# the one AUR build reached from site-async.yml's post_tasks rather than a role.
sway_guard_override: true
has_thinkpad_hardware: true
has_thinkpad_trackpoint: true
```

- [ ] **Step 2: Run each and triage**

Run: `tests/test fingerprint`, then `tests/test thinkpad`
Expected: as Task 3 Step 2 — fix real bugs, record genuine impossibilities for
Task 5. `thinkfan` starting is a likely genuine impossibility: it reads
`/proc/acpi/ibm/fan`, which the VM does not have.

- [ ] **Step 3: Add the health assertions**

Extend the heredoc with:

```sh
if [ "${GATHERD_PROFILE:-baseline}" = fingerprint ]; then
    for pkg in fprintd-clients-git open-fprintd python-validity; do
        pacman -Qq "$pkg" >/dev/null 2>&1 || {
            echo "fingerprint profile: $pkg is not installed; the fprintd chain"
            echo "did not converge"
            exit 1
        }
    done
fi
if [ "${GATHERD_PROFILE:-baseline}" = thinkpad ]; then
    pacman -Qq thinkfan >/dev/null 2>&1 || {
        echo "thinkpad profile: thinkfan is not installed"
        exit 1
    }
    [ -f /etc/thinkfan.conf ] || {
        echo "thinkpad profile: /etc/thinkfan.conf was not written"
        exit 1
    }
fi
```

- [ ] **Step 4: Verify every profile**

Run: `tests/test`, `tests/test backlight`, `tests/test fingerprint`, `tests/test thinkpad`
Expected: all four PASS.

- [ ] **Step 5: Lint and commit**

```bash
shellcheck tests/test
tests/gates
git add tests/test tests/profiles
git commit -m "Test the fprintd chain and the ThinkPad path"
```

---

### Task 5: Refuse an untested flag

**Files:**
- Create: `tests/profiles/EXCLUSIONS.md`
- Create: `scripts/gatherd-check-hardware-profiles`
- Create: `tests/check-hardware-profiles`
- Modify: `tests/gates` (add the gate and its unit test to the two lists)
- Modify: `CLAUDE.md` (the Testing section)

**Interfaces:**
- Consumes: `tests/profiles/*.yml` from Tasks 1, 3, 4.
- Produces: `gatherd-check-hardware-profiles [repo-root]`, exit 0 clean / 1 on an unaccounted-for flag. Reads flags from `roles/machine_facts/defaults/main.yml`, coverage from `tests/profiles/*.yml`, and exemptions from `tests/profiles/EXCLUSIONS.md` (one `- has_name — reason` bullet per line, the same shape `MIGRATIONS.md` uses).

- [ ] **Step 1: Write the failing test**

Create `tests/check-hardware-profiles`:

```sh
#!/bin/sh
# Unit tests for gatherd-check-hardware-profiles.
#
# The gate exists so a new has_* flag cannot be added and silently never tested
# -- the same shape as a gate with no test. The cases that matter are a flag in
# no profile and no exclusion (the omission), and a flag that is excluded
# without a reason (the excuse).
#
# Usage: tests/check-hardware-profiles

set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
GATE="$REPO/scripts/gatherd-check-hardware-profiles"
PASS=0
FAIL=0

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/roles/machine_facts/defaults" "$WORK/tests/profiles"

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }

flags() { printf -- '---\n%s\n' "$1" > "$WORK/roles/machine_facts/defaults/main.yml"; }

assert_rc() {
    _d=$1; _want=$2
    if "$GATE" "$WORK" >"$WORK/out" 2>&1; then _got=0; else _got=$?; fi
    if [ "$_got" = "$_want" ]; then ok "$_d"; else bad "$_d (want rc=$_want got rc=$_got)"; cat "$WORK/out"; fi
}

assert_says() {
    _d=$1; _want=$2
    if grep -q "$_want" "$WORK/out"; then ok "$_d"; else bad "$_d (no '$_want' in output)"; fi
}

printf -- '---\nhas_thing: true\n' > "$WORK/tests/profiles/demo.yml"
printf '# Exclusions\n\n- has_other — no device to emulate\n' > "$WORK/tests/profiles/EXCLUSIONS.md"

# 1. Every flag is either in a profile or excluded with a reason.
flags 'has_thing: false
has_other: false'
assert_rc "a covered flag set exits 0" 0

# 2. A new flag in neither place is the omission the gate exists to catch.
flags 'has_thing: false
has_other: false
has_newfangled: false'
assert_rc "an unaccounted-for flag exits 1" 1
assert_says "the unaccounted-for flag is named" 'has_newfangled'

# 3. An exclusion with no reason is an excuse, not a decision.
printf '# Exclusions\n\n- has_other\n' > "$WORK/tests/profiles/EXCLUSIONS.md"
flags 'has_thing: false
has_other: false'
assert_rc "an exclusion with no reason exits 1" 1
assert_says "the reasonless exclusion is named" 'has_other'

# 4. A flag that defaults true is on in every run, so it needs no profile and
#    no excuse. has_resume, has_lid_events and has_powerbutton_events are the
#    real ones.
printf '# Exclusions\n\n- has_other — no device to emulate\n' > "$WORK/tests/profiles/EXCLUSIONS.md"
flags 'has_thing: false
has_other: false
has_always: true'
assert_rc "a flag defaulting true needs no profile" 0

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `chmod +x tests/check-hardware-profiles && tests/check-hardware-profiles`
Expected: FAIL — `scripts/gatherd-check-hardware-profiles` does not exist.

- [ ] **Step 3: Write the gate**

Create `scripts/gatherd-check-hardware-profiles`:

```python
#!/usr/bin/env python3
"""Fail if a hardware flag is neither tested nor knowingly untestable.

Every `when: has_*` task the VM never reaches is reviewed by reading, which is
how an AVX guard missing its own `when:` reached main and how clight's `gsl`
cost a repave. A flag is accounted for when some tests/profiles/*.yml turns it
on, or when tests/profiles/EXCLUSIONS.md says why it cannot be.

The reason is the point. "No device to emulate" is a decision; a bare name is an
omission wearing a decision's clothes, so an exclusion without one fails too.

Usage: gatherd-check-hardware-profiles [repo-root]   (exit 0 clean, 1 on gaps)
"""
import re
import sys
from pathlib import Path

import yaml

EXCLUSION = re.compile(r'^- (?P<flag>has_\w+)\s+—\s+(?P<reason>\S.*)$')


def main():
    root = Path(sys.argv[1] if sys.argv[1:] else
                Path(__file__).resolve().parent.parent)
    defaults = root / 'roles/machine_facts/defaults/main.yml'
    declared = {k for k in (yaml.safe_load(defaults.read_text()) or {})
                if k.startswith('has_')}
    if not declared:
        print(f'no has_* flags in {defaults}', file=sys.stderr)
        return 1

    # A flag that defaults true is on in every run, baseline included, so it is
    # already exercised and needs neither a profile nor an excuse.
    profiles = root / 'tests/profiles'
    covered = {k for k, v in (yaml.safe_load(defaults.read_text()) or {}).items()
               if k.startswith('has_') and v is True}
    for path in sorted(profiles.glob('*.yml')):
        for key, value in (yaml.safe_load(path.read_text()) or {}).items():
            if key.startswith('has_') and value:
                covered.add(key)

    excused, reasonless = set(), []
    ledger = profiles / 'EXCLUSIONS.md'
    for row in (ledger.read_text().splitlines() if ledger.exists() else []):
        match = EXCLUSION.match(row.strip())
        if match:
            excused.add(match['flag'])
        elif re.match(r'^- (has_\w+)\s*$', row.strip()):
            reasonless.append(re.match(r'^- (has_\w+)', row.strip()).group(1))

    gaps = sorted(declared - covered - excused)
    if gaps or reasonless:
        if gaps:
            print('Hardware flags no profile turns on and no exclusion excuses.\n'
                  'Add each to a tests/profiles/*.yml, or to\n'
                  'tests/profiles/EXCLUSIONS.md with the reason it cannot be tested:\n')
            for flag in gaps:
                print(f'  {flag}')
        if reasonless:
            print('\nExclusions with no reason. A bare name is an omission, not a\n'
                  'decision -- say what stops the VM exercising it:\n')
            for flag in sorted(set(reasonless)):
                print(f'  {flag}')
        return 1

    print(f'{len(declared)} hardware flag(s): {len(covered)} exercised by a '
          f'profile, {len(excused)} excluded with a reason.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `chmod +x scripts/gatherd-check-hardware-profiles && tests/check-hardware-profiles`
Expected: `6 passed, 0 failed`

- [ ] **Step 5: Write the real exclusions ledger**

Create `tests/profiles/EXCLUSIONS.md`. Every flag not turned on by a profile from
Tasks 1, 3 and 4 needs a line. Run the gate to get the list rather than guessing
it:

```bash
scripts/gatherd-check-hardware-profiles .
```

It will name 16 flags: everything except the six the profiles cover, `has_avx`
(real, via `-cpu host`), and the three that default true. Write one bullet per
flag it names, in the shape the parser expects — `- has_x — reason`, with an em
dash. Use the reason that is actually true; the triage notes
from Task 3 Step 2 and Task 4 Step 2 are the source for any flag that was tried
and could not converge. For flags never attempted, say so plainly. Example
shape:

```markdown
# Hardware flags the VM cannot exercise

Each line says what stops it, not merely that something does. A flag here is a
candidate for a profile the moment that reason stops being true.

- has_applesmc — QEMU has no Apple SMC, and the role reads /sys/devices/platform/applesmc.768
- has_extlinux — mutually exclusive with has_grub, which the snapshot installs
```

- [ ] **Step 6: Wire it into tests/gates**

In `tests/gates`, the `for gate in ...` loop already globs
`scripts/gatherd-check-*`, so the pairing check picks the new gate up with no
change. Add it to the two explicit lists. After the
`run "$REPO/scripts/gatherd-check-aur-deps" "$REPO"` line add:

```bash
run "$REPO/scripts/gatherd-check-hardware-profiles" "$REPO"
```

and in the unit-test `for suite in ...` list add `check-hardware-profiles`.

- [ ] **Step 7: Document it**

In `CLAUDE.md`, in the Testing section, replace the paragraph beginning
`**One hardware profile.** The VM has no backlight` with:

```markdown
**Hardware profiles.** `tests/test [profile]` picks a file from
`tests/profiles/`, whose `has_*` overrides outrank what `machine_facts`
detected, so a `when: has_*` path can actually run. They do not simulate
hardware — QEMU has no Apple SMC — but they do exercise convergence of a gated
path, which is where both known bugs lived: clight's undeclared `gsl`, and a
preflight guard missing its build's `when: has_avx`. `has_avx` is real rather
than forced; `tests/test` passes `-cpu host`.

What a profile does not cover, `tests/profiles/EXCLUSIONS.md` must, with the
reason. `gatherd-check-hardware-profiles` fails on a flag in neither place, so
adding a flag forces a decision instead of allowing an omission. Flags still
excluded are reviewed by reading and by the next repave — nothing else.
```

- [ ] **Step 8: Verify everything**

```bash
tests/gates
tests/test
tests/test backlight
```
Expected: `tests/gates` green including the new gate and its 6 tests; both VM
runs PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/gatherd-check-hardware-profiles tests/check-hardware-profiles \
        tests/profiles/EXCLUSIONS.md tests/gates CLAUDE.md
git commit -m "Refuse a hardware flag that is neither tested nor excused"
```

---

## Self-Review

**Spec coverage.** Mechanism → Task 1. `-cpu host` for real AVX → Task 2. Three
profiles covering the two AUR chains that have broken, plus ThinkPad → Tasks 3
and 4. "Keeping it honest" → Task 5. Scope's "remaining flags land in the
exclusions file with reasons" → Task 5 Step 5.

**Placeholders.** None: every profile, assertion, gate and test is written out.
Task 3 Step 2 and Task 4 Step 2 deliberately do not predict which tasks fail
without the device — that is a measurement the executor takes, and inventing the
list here would be a claim about third-party behaviour with no command behind
it. The plan says what to do with each outcome instead.

**Type consistency.** `PROFILE` (Task 1) is consumed by Tasks 2, 3 and 4;
`GATHERD_PROFILE` is introduced in Task 3 Step 3 and reused unchanged in Task 4.
`GATHERD_PROFILE_ONLY` appears only in Task 1. The gate's EXCLUSIONS.md bullet
shape (`- has_x — reason`, em dash) is the same in the parser, its unit test, and
Task 5 Step 5.

**Known gap.** Task 1 Step 6 and Tasks 2–4 each need `ap-juicer.local` and a
`tests/create-base` image. On a machine without them the VM steps cannot run and
the task is not done — say so rather than marking it complete.
