# Undeclared Installed Packages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Name every explicitly-installed package that neither the measured base image nor this repo accounts for, at every login, so a package this repo has stopped declaring cannot sit on a converged machine unnoticed.

**Architecture:** One new machine-side gate, `scripts/gatherd-assert-packages-declared`, which subtracts `tests/base-manifest.txt` and the repo's declared set from `pacman -Qeq`. It reads the declared set by importing `scripts/gatherd-check-aur-deps` and reusing that module's playbook walk, rather than parsing the playbooks a second time. `scripts/gatherd-post-setup-notes` gains a `section_strays` that renders its findings as login bullets, beside the existing `section_sonames`.

**Tech Stack:** Python 3 with PyYAML (what `gatherd-check-aur-deps` already is), POSIX `sh` for the `post-setup-notes` section and the test harness, `shellcheck`, `ansible-lint`.

**Spec:** `docs/superpowers/specs/2026-10-04-undeclared-packages-design.md`

## Global Constraints

- Gate exit conventions: **0** clean, **1** violation, **2** could not run. Never a silent skip. A check that could not look at the machine has not said the machine is fine.
- Every `scripts/gatherd-{check,assert}-*` must have a `tests/<same-name>` beside it. `tests/gates` enforces this by glob with no exemption list, so the test is not optional and cannot be excused.
- `tests/gates` is the one command to run before committing.
- POSIX `sh` only in shell files. `bash`-isms are a defect, not a style choice. `shellcheck` clean, with no `# shellcheck disable` unless the line above says why.
- `ansible-lint` clean at the `production` profile for every YAML file touched. (A bare `ansible-lint` run in a fresh clone reports one pre-existing `internal-error` on `site-vault.yml` because no `.vault_pass` is present — that is not yours.)
- Ansible modules always FQCN: `ansible.builtin.*`, `community.general.*`.
- Ansible task names read as imperative sentences ("Install the mirror ranker", not "mirror ranker task").
- Comments explain *why*, never *what*. The task name already says what.
- This check REPORTS; it never removes. CLAUDE.md: "an orphan sweep can turn a green machine red, and the fix is to declare what it names."
- Python scripts in `scripts/` carry no `.py` extension, matching `gatherd-check-aur-deps`.
- No `MIGRATIONS.md` entry is due: this change adds no `state: absent` task. Do not add one.

---

## Starting state

Working tree is clean except for unrelated edits to
`roles/desktop/templates/waterfox-userChrome.css.j2` and
`scripts/gatherd-post-setup-notes`. Leave both alone; Task 4 edits
`gatherd-post-setup-notes` and must not revert whatever is already uncommitted
there — read the file first and add to it.

Facts measured on atm-card, 2026-10-04, that the tasks below rely on:

- `pacman -Qeq` → 310 packages. `tests/base-manifest.txt` → 896.
- Explicitly installed, undeclared, not in base → exactly four: `ansible`,
  `aurutils`, `nowayprompt`, `rate-mirrors`.
- 28 `community.general.pacman` tasks under `roles/`: 19 literal names, 6 bare
  `{{ *_packages }}` vars, 2 vendored-PKGBUILD file paths, 1 with no `name:` key
  (`roles/aur/tasks/slow.yml:19`, which is `state: absent` and therefore not an
  install event).
- `gatherd-check-aur-deps` imports cleanly with an explicit `SourceFileLoader`
  and runs nothing on import (it has an `if __name__ == '__main__':` guard).

**Task 1's implementation was run before this plan was written**, against this
repo and against a sandbox, 2026-10-04. It is not pseudocode. Measured:

| Run | Result |
|---|---|
| Against this repo, `rate-mirrors` still undeclared | exit 1, names `rate-mirrors` and nothing else |
| `--tsv` on the same | prints `rate-mirrors`, exit 1 |
| Sandbox: package declared only under `when: has_no_such_hardware` | exit 0 |
| Sandbox: `aurutils`, `nowayprompt`, `ansible` installed | exit 0 |
| Sandbox: `aur sync` line the parser cannot read | exit 2, naming the file and task |
| Sandbox: `# arch: nosucharch` manifest | exit 2, naming both architectures |
| Sandbox: `pacman -Qeq` exits 1 | exit 2, quoting pacman's stderr |

So if a step below fails, suspect the transcription rather than the design — and
one transcription trap is already disarmed in the code: `SourceFileLoader`'s name
argument must be the same string as the spec's, or `exec_module` refuses with
`loader for <x> cannot handle <y>`.

---

# Phase 1 — The gate

## Task 1: Name a stray package

**Files:**
- Create: `scripts/gatherd-assert-packages-declared`
- Create: `tests/assert-packages-declared`
- Modify: `tests/gates`

**Interfaces:**
- Consumes: `scripts/gatherd-check-aur-deps`, via import, for `load`, `visit`, `ENTRY_POINTS` and its own `CannotRun`. (`names_from` is used indirectly, inside `visit`; the presence check names it too so a rename there fails here.)
- Produces: `gatherd-assert-packages-declared [--tsv] [<repo-root>]`. Exit 0 clean, 1 with each stray named on stderr (one bare package name per line on stdout under `--tsv`), 2 cannot run with the reason on stderr. Honours `GATHERD_HOME` for the repo root when no argument is given.

- [ ] **Step 1: Write the failing test**

Create `tests/assert-packages-declared`:

```sh
#!/bin/sh
# Unit tests for gatherd-assert-packages-declared.
#
# Machine state arrives through a pacman shim on $PATH answering from
# $GATHERD_TEST_DB, the same mechanism tests/assert-sonames uses. Repo state is a
# sandbox tree, so these tests never depend on what this working tree happens to
# declare today.
set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
CHECK="$REPO/scripts/gatherd-assert-packages-declared"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }

# A pacman that answers only what this check asks. Anything else is a test bug,
# not a pass: a shim that silently answers an unexpected query would let the
# check drift away from what it claims to read.
mkdir -p "$WORK/shim"
cat > "$WORK/shim/pacman" <<'SHIM'
#!/bin/sh
db=${GATHERD_TEST_DB:?}
case "$1" in
    -Qeq) [ -f "$db/explicit" ] || { echo 'error: database broken' >&2; exit 1; }
          cat "$db/explicit" ;;
    *)    echo "shim pacman: unexpected invocation: $*" >&2; exit 1 ;;
esac
SHIM
chmod +x "$WORK/shim/pacman"
PATH="$WORK/shim:$PATH"
export PATH

# A sandbox repo: group_vars, a base manifest for THIS architecture, and one
# playbook the walk can reach.
sandbox() {
    _root=$1
    rm -rf "$_root"
    mkdir -p "$_root/group_vars/all" "$_root/tests" "$_root/roles/system/tasks"
    printf '# arch: %s\n' "$(uname -m)" > "$_root/tests/base-manifest.txt"
    cat > "$_root/group_vars/all/main.yml" <<'GV'
---
core_packages: []
rest_packages:
  - declared-pkg
GV
    cat > "$_root/roles/system/tasks/rest.yml" <<'T'
---
- name: Install the rest packages
  community.general.pacman:
    name: "{{ rest_packages }}"
    state: present
T
    cat > "$_root/site-core.yml" <<'P'
---
- name: System
  hosts: localhost
  tasks: []
P
    cat > "$_root/site-async.yml" <<'P'
---
- name: System
  hosts: localhost
  tasks:
    - name: Configure the system
      ansible.builtin.include_tasks: roles/system/tasks/rest.yml
P
}

run_check() {
    GATHERD_TEST_DB="$WORK/db" "$CHECK" "$1" > "$WORK/out" 2> "$WORK/err"
    echo $?
}

# --- Case 1: installed, declared nowhere, not in base -> exit 1, named --------
sandbox "$WORK/repo"
mkdir -p "$WORK/db"
printf 'declared-pkg\nstray-pkg\n' > "$WORK/db/explicit"
rc=$(run_check "$WORK/repo" || true)
if [ "$rc" = 1 ] && grep -q 'stray-pkg' "$WORK/err"; then
    ok 'a stray is exit 1 and named'
else
    bad "a stray should be exit 1 and named (got $rc)"; sed 's/^/       /' "$WORK/err"
fi
if ! grep -q 'declared-pkg' "$WORK/err"; then
    ok 'a declared package is not reported'
else
    bad 'a declared package was reported as a stray'
fi

# --- Case 2: everything declared -> exit 0 -----------------------------------
printf 'declared-pkg\n' > "$WORK/db/explicit"
rc=$(run_check "$WORK/repo" || true)
[ "$rc" = 0 ] && ok 'all declared is exit 0' || {
    bad "all declared should be exit 0 (got $rc)"; sed 's/^/       /' "$WORK/err"; }

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

```bash
chmod +x tests/assert-packages-declared
```

- [ ] **Step 2: Run it to verify it fails**

Run: `tests/assert-packages-declared`
Expected: FAIL — the script does not exist, so the harness cannot execute `$CHECK`.

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/gatherd-assert-packages-declared`:

```python
#!/usr/bin/env python3
"""Name every explicitly-installed package nothing accounts for.

The bug this exists for, on a converged machine:

    $ pacman -Qi electron42 | sed -n '/^Required By/p;/^Install Reason/p'
    Required By     : teams-for-linux-electron-bin
    Install Reason  : Explicitly installed

faf799b replaced electron42 with electron44 in group_vars to follow
slack-electron's PKGBUILD. The repo was right from that commit on; the machine
kept the package. `pacman -Qdtq` never finds one of these -- measured against
nowayprompt, which is explicitly installed with `Required By : None`, and
`pacman -Qdtq` names nothing at all -- because an explicit install is not an
orphan. It came off only because a human was told to type `pacman -Rs`.

WHY A THIRD GATE. gatherd-check-aur-deps and gatherd-assert-aur-deps both read a
declaration and ask whether it is satisfied. Neither can ask whether a satisfied
thing is still declared, and on the repo as of faf799b there is nothing left in
the tree to find -- the stray exists only on the machine. Same argument
gatherd-assert-sonames makes for itself, a different machine-side question: not
"can it load" but "is it accounted for".

WHAT IT DOES NOT DO. It never removes anything. CLAUDE.md: an orphan sweep can
turn a green machine red, and the fix is to declare what it names.

Exit 0 clean, 1 with each stray named, 2 could not run.
"""
import importlib.util
import os
import platform
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

VIOLATION = 1
CANNOT_RUN = 2

# Walked in addition to gatherd-check-aur-deps' own ENTRY_POINTS. site-vault.yml
# installs nothing today (measured: `grep -c community.general.pacman
# site-vault.yml` is 0, and the one role it names has none either), but a vault
# task that installed a package would otherwise read as a stray.
EXTRA_ENTRY_POINTS = ('site-vault.yml',)

# Installed by gatherd, unreachable as an install or build event. Each line is a
# reason, not an exemption: the parser is not failing here, these three are
# genuinely outside the shape it reads.
DECLARED_ELSEWHERE = {
    # Built from a vendored PKGBUILD and installed by file path --
    # `name: "{{ _aurutils_built.files[0].path }}"`. names_from resolves a bare
    # {{ var }} and a literal; a registered-fact subscript returns [] (measured).
    'aurutils': 'roles/system/tasks/aurutils.yml, from a vendored PKGBUILD',
    'nowayprompt': 'roles/system/tasks/nowayprompt.yml, from a vendored PKGBUILD',
    # gatherd's own bootstrap: installed before any playbook exists to declare
    # it. Deliberately NOT added to tests/base-manifest.txt -- counting
    # gatherd's own ansible install as base is what certified
    # python-cryptography (CLAUDE.md, AUR dependencies).
    'ansible': "gatherd's own bootstrap, installed before the playbooks run",
}


class CannotRun(Exception):
    """The check could not look at the machine. Not the same as a clean run."""


def aur_deps_module(root):
    """gatherd-check-aur-deps as a module, for its playbook walk.

    Imported rather than reimplemented: a second parser would drift from the
    first, and the first already handles role includes, tasks_from, inherited
    when: conditions and arch gating. tests/assert-packages-declared pins the
    names used here so that gate's next refactor fails loudly rather than
    quietly widening the declared set.

    spec_from_file_location returns None for a file with no .py extension, so
    the loader is explicit (measured).
    """
    path = root / 'scripts' / 'gatherd-check-aur-deps'
    if not path.is_file():
        raise CannotRun(f'{path} is missing; this check reads its playbook walk')
    # The loader's name must be the same string as the spec's, or exec_module
    # refuses with "loader for <loader name> cannot handle <spec name>".
    name = 'gatherd_check_aur_deps'
    spec = importlib.util.spec_from_file_location(
        name, path, loader=SourceFileLoader(name, str(path)))
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as failure:          # noqa: BLE001 -- any import failure is exit 2
        raise CannotRun(f'cannot import {path}: {failure}') from failure
    for name in ('load', 'visit', 'names_from', 'ENTRY_POINTS', 'CannotRun'):
        if not hasattr(module, name):
            raise CannotRun(f'{path} no longer provides {name}; this check '
                            'reads its playbook walk and must be updated with it')
    return module


def declared(root):
    """Every package this repo installs or builds, read out of the playbooks.

    HARDWARE CONDITIONS DO NOT NARROW THIS, and not by accident. The imported
    resolve() decides only the architecture -- measured, it returns None for
    has_backlight, for has_no_such_hardware and for every other fact, so
    conditions_of keeps the task and records the condition by name rather than
    dropping it. A has_* package therefore stays in the declared set on every
    machine. That is what this check needs: it asks whether the repo declares a
    package anywhere, not whether this machine's profile reaches it. Were a
    gated task dropped, every has_* package would read as a stray on exactly the
    machines that have the hardware, which inverts the gate.

    The one condition resolve() does decide is is_aarch64. An aarch64-only task
    is dropped on x86_64 -- correctly, because its packages are not installed
    there either, so no stray appears.
    """
    module = aur_deps_module(root)
    arch = platform.machine()
    try:
        gv = module.load(root / 'group_vars/all/main.yml')

        names = set()
        seen = set()
        for entry in tuple(module.ENTRY_POINTS) + EXTRA_ENTRY_POINTS:
            path = root / entry
            if not path.is_file():
                continue
            events = []
            module.visit(root, path, gv, arch, (), seen, events)
            for kind, payload, *_ in events:
                if kind == 'install':
                    names |= set(payload)
                elif kind == 'build':
                    names |= set(payload[2])
                elif kind == 'unreadable':
                    raise CannotRun(payload)
    except module.CannotRun as failure:
        # That module raises its own CannotRun -- load() does, on a malformed
        # group_vars. Letting it through would surface as a traceback and exit 1:
        # this gate reporting a stray because it could not read the repo.
        raise CannotRun(str(failure)) from failure
    if not names:
        raise CannotRun(f'the walk of {root} found no package at all; the '
                        'playbooks or group_vars are not being read')
    return names


def base_manifest(root):
    """The measured first-boot package set, refusing another architecture's."""
    manifest = root / 'tests/base-manifest.txt'
    if not manifest.exists():
        raise CannotRun(f'{manifest} is missing; regenerate it with '
                        'scripts/gatherd-capture-base-manifest from a '
                        'first-boot /var/log/pacman.log')
    rows = manifest.read_text().splitlines()
    arch = platform.machine()
    measured = next((row.split(':', 1)[1].strip() for row in rows
                     if row.startswith('# arch:')), None)
    if measured != arch:
        raise CannotRun(f'{manifest} was measured on '
                        f'{measured or "an unrecorded architecture"}, but this '
                        f'is {arch}; one architecture\'s answer would mark the '
                        f'wrong packages present')
    return {row.strip() for row in rows
            if row.strip() and not row.lstrip().startswith('#')}


def explicit():
    """Explicitly installed packages.

    -Qeq, not -Qq: a package pulled in as a dependency is accounted for by
    whatever depends on it, and pacman -Qdtq already covers that going away.
    """
    try:
        done = subprocess.run(['pacman', '-Qeq'], capture_output=True,
                              text=True, check=False)
    except OSError as failure:
        raise CannotRun(f'cannot run pacman: {failure}') from failure
    if done.returncode != 0:
        raise CannotRun('pacman -Qeq failed; is the local database readable? '
                        + done.stderr.strip())
    return {line.strip() for line in done.stdout.splitlines() if line.strip()}


def main():
    argv = sys.argv[1:]
    tsv = False
    if argv and argv[0] == '--tsv':
        tsv = True
        argv = argv[1:]
    if len(argv) > 1:
        print(f'usage: {sys.argv[0]} [--tsv] [<repo-root>]', file=sys.stderr)
        return CANNOT_RUN
    root = Path(argv[0]) if argv else Path(
        os.environ.get('GATHERD_HOME', '/usr/local/lib/gatherd'))

    try:
        strays = sorted(explicit() - base_manifest(root) - declared(root)
                        - set(DECLARED_ELSEWHERE))
    except CannotRun as failure:
        print(f'cannot run: {failure}', file=sys.stderr)
        return CANNOT_RUN

    if not strays:
        return 0

    if tsv:
        for name in strays:
            print(name)
    print('Explicitly installed, and nothing in this repo or the base image '
          'accounts for them:', file=sys.stderr)
    for name in strays:
        print(f'  {name}', file=sys.stderr)
    print('\nEach is either a package this repo should declare in a *_packages '
          'var, or\na leftover to remove with `sudo pacman -Rs <name>`. '
          'Deciding which is not\nderivable from the code: a leftover and an '
          'undeclared dependency look identical\nfrom here.', file=sys.stderr)
    return VIOLATION


if __name__ == '__main__':
    sys.exit(main())
```

```bash
chmod +x scripts/gatherd-assert-packages-declared
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `tests/assert-packages-declared`
Expected: `3 passed, 0 failed`

- [ ] **Step 5: Wire it into tests/gates**

`tests/gates` already enforces the gate/test pairing by glob over
`scripts/gatherd-check-*` and `scripts/gatherd-assert-*`, so the new pair is
picked up with no edit. The unit-test block lists each suite explicitly; add the
new one there, beside `assert-sonames`.

Find the `== unit tests ==` block and add:

```sh
run "$REPO/tests/assert-packages-declared"
```

Do **not** add it to the `== gates, against this working tree ==` block. That
block runs each gate against the repo; this one reads the machine, and on a
developer's machine mid-change its answer is about that machine, not the tree —
the same reason `assert-sonames` and `assert-aur-deps` are in the unit-test block
and not that one. The comment already in `tests/gates` above that block says so.

- [ ] **Step 6: Run the full suite**

Run: `tests/gates`
Expected: every line `ok`, including `ok   assert-packages-declared is exercised by tests/assert-packages-declared`.

- [ ] **Step 7: Commit**

```bash
git add scripts/gatherd-assert-packages-declared tests/assert-packages-declared tests/gates
git commit -m "Notice packages this repo has stopped declaring

Claude-Session: https://claude.ai/code/session_01QVDsBp9rLkfbTm8hWLUot8"
```

---

## Task 2: Pin the cases that keep the gate honest

**Files:**
- Modify: `tests/assert-packages-declared`

**Interfaces:**
- Consumes: `gatherd-assert-packages-declared` from Task 1, unchanged.
- Produces: nothing new. This task adds coverage only; if any case fails, the defect is in Task 1's implementation and belongs fixed there.

Seven more cases. Each one exists because getting it wrong is a specific way this
gate goes quietly useless.

- [ ] **Step 1: Write the failing tests**

Append to `tests/assert-packages-declared`, before the final tally:

```sh
# --- Case 3: in the base manifest, declared nowhere -> exit 0 ----------------
# The base image is not this repo's to declare. Were this a violation, the gate
# would open with ~900 findings and be switched off the same day.
printf '# arch: %s\nbase-pkg\n' "$(uname -m)" > "$WORK/repo/tests/base-manifest.txt"
printf 'declared-pkg\nbase-pkg\n' > "$WORK/db/explicit"
rc=$(run_check "$WORK/repo" || true)
[ "$rc" = 0 ] && ok 'a base-image package is accounted for' || {
    bad "base-image package should be exit 0 (got $rc)"; sed 's/^/       /' "$WORK/err"; }

# --- Case 4: the vendored-PKGBUILD pair -> exit 0 ---------------------------
# aurutils and nowayprompt are installed by file path, which names_from cannot
# resolve. They must be accounted for by the DECLARED_ELSEWHERE table, with a
# reason -- not by luck.
printf 'declared-pkg\naurutils\nnowayprompt\nansible\n' > "$WORK/db/explicit"
rc=$(run_check "$WORK/repo" || true)
[ "$rc" = 0 ] && ok 'the vendored pair and the bootstrap are accounted for' || {
    bad "vendored pair should be exit 0 (got $rc)"; sed 's/^/       /' "$WORK/err"; }

# --- Case 5: declared under a when: this machine fails -> exit 0 -------------
# A has_* declaration still counts. It works because the imported resolve()
# decides only the architecture -- measured, it returns None for every has_*
# fact, so conditions_of records the condition by name instead of dropping the
# task. Pinned here because the day resolve() learns to evaluate facts, every
# has_* package starts reading as a stray on exactly the machines that have the
# hardware, and this case is the only thing that would say so.
cat > "$WORK/repo/roles/system/tasks/gated.yml" <<'T'
---
- name: Install the hardware-gated package
  community.general.pacman:
    name: gated-pkg
    state: present
  when: has_no_such_hardware
T
cat >> "$WORK/repo/site-async.yml" <<'P'
    - name: Configure gated hardware
      ansible.builtin.include_tasks: roles/system/tasks/gated.yml
P
printf 'declared-pkg\ngated-pkg\n' > "$WORK/db/explicit"
rc=$(run_check "$WORK/repo" || true)
[ "$rc" = 0 ] && ok 'a hardware-gated declaration still counts' || {
    bad "gated declaration should be exit 0 (got $rc)"; sed 's/^/       /' "$WORK/err"; }

# --- Case 6: base manifest from another architecture -> exit 2 --------------
printf '# arch: nosucharch\nbase-pkg\n' > "$WORK/repo/tests/base-manifest.txt"
printf 'declared-pkg\n' > "$WORK/db/explicit"
rc=$(run_check "$WORK/repo" || true)
if [ "$rc" = 2 ] && grep -q 'nosucharch' "$WORK/err"; then
    ok 'a foreign-architecture manifest is exit 2'
else
    bad "foreign-arch manifest should be exit 2 (got $rc)"; sed 's/^/       /' "$WORK/err"
fi

# --- Case 7: no base manifest -> exit 2 ------------------------------------
rm -f "$WORK/repo/tests/base-manifest.txt"
rc=$(run_check "$WORK/repo" || true)
if [ "$rc" = 2 ] && grep -q 'base-manifest' "$WORK/err"; then
    ok 'a missing manifest is exit 2, not a clean run'
else
    bad "missing manifest should be exit 2 (got $rc)"; sed 's/^/       /' "$WORK/err"
fi

# --- Case 8: pacman fails -> exit 2 ---------------------------------------
sandbox "$WORK/repo"
rm -f "$WORK/db/explicit"
rc=$(run_check "$WORK/repo" || true)
if [ "$rc" = 2 ] && grep -qi 'pacman' "$WORK/err"; then
    ok 'a failed pacman query is exit 2'
else
    bad "failed pacman should be exit 2 (got $rc)"; sed 's/^/       /' "$WORK/err"
fi

# --- Case 9: an unreadable aur sync line -> exit 2 -------------------------
# Never "assume declared". A build whose targets cannot be read would otherwise
# widen the declared set silently, which is how a gate goes blind.
printf 'declared-pkg\n' > "$WORK/db/explicit"
cat > "$WORK/repo/roles/system/tasks/opaque.yml" <<'T'
---
- name: Build something the parser cannot read
  ansible.builtin.command: "{{ aur_sync_command }} {{ some_var | map('upper') | list }}"
  changed_when: false
T
cat >> "$WORK/repo/site-async.yml" <<'P'
    - name: Build opaquely
      ansible.builtin.include_tasks: roles/system/tasks/opaque.yml
P
rc=$(run_check "$WORK/repo" || true)
[ "$rc" = 2 ] && ok 'an unreadable build line is exit 2' || {
    bad "unreadable build should be exit 2 (got $rc)"; sed 's/^/       /' "$WORK/err"; }

# --- Case 10: the imported module still provides what this reads -----------
# The reuse in gatherd-assert-packages-declared is only safe if this fails when
# gatherd-check-aur-deps is refactored out from under it.
if python3 - "$REPO" <<'PY'
import importlib.util, sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
p = Path(sys.argv[1]) / 'scripts' / 'gatherd-check-aur-deps'
s = importlib.util.spec_from_file_location('g', p, loader=SourceFileLoader('g', str(p)))
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
missing = [n for n in ('load', 'visit', 'names_from', 'ENTRY_POINTS')
           if not hasattr(m, n)]
sys.exit(1 if missing else 0)
PY
then
    ok 'gatherd-check-aur-deps still provides the walk this reads'
else
    bad 'gatherd-check-aur-deps no longer provides load/visit/names_from/ENTRY_POINTS'
fi
```

- [ ] **Step 2: Run them**

Run: `tests/assert-packages-declared`
Expected: `11 passed, 0 failed`.

If any case fails, fix `scripts/gatherd-assert-packages-declared` — not the test.
Each case states in its comment the failure it is there to prevent; if a case
looks wrong, re-read the spec section it cites before changing it.

- [ ] **Step 3: Commit**

```bash
git add tests/assert-packages-declared
git commit -m "Pin the cases that keep the stray-package gate honest

Claude-Session: https://claude.ai/code/session_01QVDsBp9rLkfbTm8hWLUot8"
```

---

# Phase 2 — Surfacing it, and the first finding

## Task 3: Declare rate-mirrors

**Files:**
- Modify: `group_vars/all/main.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks read. This is the gate's first real finding, fixed before the gate starts reporting it.

`rate-mirrors` is the `Depends =` of a pacman hook this repo installs
(`roles/system/tasks/core.yml:136`), it is in no `*_packages` var, and it is not
in `tests/base-manifest.txt` — so on a fresh repave it is absent. Declaring it is
how the gate goes green honestly rather than by exemption.

- [ ] **Step 1: Confirm the finding still holds**

```bash
grep -rn 'rate-mirrors' group_vars/ roles/ tests/base-manifest.txt
```

Expected: hits only in `roles/system/tasks/core.yml` (the hook's `Description`
and `Depends` lines). If it already appears in `group_vars/all/main.yml` or the
manifest, someone has fixed this — skip to Task 4 and say so.

- [ ] **Step 2: Declare it**

In `group_vars/all/main.yml`, in `rest_packages`, beside the other
declared-because-something-needs-it entries (near `mailcap`), add:

```yaml
  # Depends of the gatherd-rerank-mirrors pacman hook
  # (roles/system/tasks/core.yml). Never declared, and absent from
  # tests/base-manifest.txt, so on a fresh repave the hook's dependency is
  # unmet. Found by gatherd-assert-packages-declared, which is the whole point
  # of it.
  - rate-mirrors
```

- [ ] **Step 3: Verify the gate now finds nothing on this machine**

Run: `scripts/gatherd-assert-packages-declared . ; echo "exit=$?"`
Expected: `exit=0`, no output.

If it still names something, that is a real finding too — report it rather than
adding it to `DECLARED_ELSEWHERE`. The table is for the three cases the spec
names, not a place to put whatever turns up.

- [ ] **Step 4: Lint and run the suite**

```bash
ansible-lint group_vars/all/main.yml
tests/gates
```

Expected: `ansible-lint` clean; every `tests/gates` line `ok`.

- [ ] **Step 5: Commit**

```bash
git add group_vars/all/main.yml
git commit -m "Declare the mirror ranker the rerank hook depends on

Claude-Session: https://claude.ai/code/session_01QVDsBp9rLkfbTm8hWLUot8"
```

---

## Task 4: Report strays at login

**Files:**
- Modify: `scripts/gatherd-post-setup-notes`
- Modify: `tests/post-setup-notes`

**Interfaces:**
- Consumes: `gatherd-assert-packages-declared --tsv` from Task 1 — one bare package name per line on stdout, exit 0/1/2.
- Produces: a `Packages` section in `~/.config/gatherd-post-setup.md`, one bullet per stray, each opening with the literal marker `gatherd does not account for ` so `prune_derived` can find it again next login.

Read `scripts/gatherd-post-setup-notes` first. `section_sonames` (around line 487)
is the model for all of this: the sentinel guard, the `--tsv` read, the exit-2
branch, the `prune_derived` marker, and the splice-under-the-header dance. Follow
it rather than inventing a second shape.

- [ ] **Step 1: Write the failing test**

`tests/post-setup-notes` already stubs `gatherd-assert-sonames` (around line 55).
Add a stub for the new check beside it, in the same style:

```sh
# A stand-in for gatherd-assert-packages-declared. Three answers matter: clean,
# a stray named, and could-not-run.
cat > "$WORK/gatherd/scripts/gatherd-assert-packages-declared" <<'STUB'
#!/bin/sh
case "${GATHERD_TEST_STRAYS:-clean}" in
    clean)  exit 0 ;;
    stray)  echo 'electron42'; exit 1 ;;
    cannot) echo 'gatherd-assert-packages-declared: tests/base-manifest.txt is missing' >&2
            exit 2 ;;
esac
STUB
chmod +x "$WORK/gatherd/scripts/gatherd-assert-packages-declared"
```

**First, make `generate` pass the new variable through.** `generate()` (around
line 95) sets an explicit env list; a variable not named there never reaches the
script. Add `GATHERD_TEST_STRAYS` beside `GATHERD_TEST_SONAMES`:

```sh
generate() {
    HOME="$WORK/home" GATHERD_HOME="$WORK/gatherd" \
        XDG_STATE_HOME="$WORK/state" RCLONE_CONFIG='' \
        GATHERD_ASYNC_SENTINEL="${SENTINEL_OVERRIDE:-$SENTINEL}" \
        GATHERD_TEST_SONAMES="$SONAMES_MODE" \
        GATHERD_TEST_STRAYS="${STRAYS_MODE:-clean}" sh "$NOTES" >/dev/null 2>&1
}
```

Note the names this file actually uses, which differ from the obvious guesses:
`$NOTES` is the *script* under test and `$OUT` is the generated notes file. The
helpers are `assert <description> <command...>`, `refute` likewise,
`has <string>` for a literal grep of `$OUT`, and `flows <string>` for a string
that straddles a wrapped line. Use those rather than open-coding `grep`.

Then add the assertions:

```sh
printf '\n== strays ==\n'

# Clean: no section at all. A gate with nothing to say says nothing.
rm -f "$OUT"; STRAYS_MODE=clean; generate
refute "says nothing when every package is accounted for" has 'does not account for'

# A stray: named, with both of the two things a human can do about it.
rm -f "$OUT"; STRAYS_MODE=stray; generate
assert "names a stray package"            flows 'does not account for electron42'
assert "under a Packages header"          grep -q '^# Packages$' "$OUT"
assert "and offers the removal command"   flows 'sudo pacman -Rs electron42'

# Exit 2 is not exit 0. A check that could not look has not said it is fine.
rm -f "$OUT"; STRAYS_MODE=cannot; generate
assert "reports a check that could not run" flows 'base-manifest.txt is missing'

# The bullet is derived, so a second login must not stack a second copy.
rm -f "$OUT"; STRAYS_MODE=stray; generate; generate
_n=$(grep -c 'does not account for electron42' "$OUT" || true)
if [ "$_n" = 1 ]; then
    ok 'the stray bullet does not accumulate'
else
    bad "the stray bullet should appear once, got $_n"
fi

STRAYS_MODE=clean
```

The header assertion uses `^# Packages$` because `h` writes a `#` heading — check
how the existing Vault assertion spells it (`grep -q '^# Vault$' "$OUT"`) and
match that, since the level is `h`'s business and may differ from `##`.

- [ ] **Step 2: Run it to verify it fails**

Run: `tests/post-setup-notes`
Expected: FAIL on the stray assertions — `gatherd-post-setup-notes` has no
`section_strays` yet, so nothing is ever written.

- [ ] **Step 3: Add section_strays**

In `scripts/gatherd-post-setup-notes`, after `section_sonames`, add:

```sh
section_strays() {
    # Packages this machine has and nothing accounts for. Recomputed at every
    # login for the same reason section_sonames is: the defect arrives without
    # any edit to this repo. An electron version bumps in an AUR PKGBUILD, the
    # repo follows it, and the superseded one stays installed -- explicitly, so
    # no orphan sweep reaches it.
    #
    # Not a verify_li step: those are deleted once exercised (CLAUDE.md, Repave
    # cadence), so after the next repave nothing would invoke the check at all.
    # Not a task in site-async.yml either: async-complete is written only when
    # no tier failed and gatherd-await-and-run gates REST on that sentinel, so
    # one stray package would re-run every REST tier on every boot, forever.
    _mark='gatherd does not account for '

    # The declared set comes out of the playbooks, which are only all present
    # once the deployed checkout exists. Before then the check would exit 2 at
    # every login of a first pave with nothing a human could do about it.
    _sentinel="${GATHERD_ASYNC_SENTINEL:-/etc/gatherd/async-complete}"
    [ -f "$_sentinel" ] || { prune_derived 'Packages' "$_mark"; return; }

    _tsv=$(mktemp)
    _why=$(mktemp)
    "${GATHERD_HOME:-/usr/local/lib/gatherd}/scripts/gatherd-assert-packages-declared" \
        --tsv > "$_tsv" 2> "$_why"
    _rc=$?

    set --
    if [ "$_rc" -eq 1 ]; then
        while read -r _pkg; do
            [ -n "$_pkg" ] || continue
            set -- "$@" "$_mark$_pkg. Either declare it in the *_packages var\
 for the tier that needs it, or remove it: \`sudo pacman -Rs $_pkg\`. Which one\
 is not derivable from here -- a leftover and an undeclared dependency look\
 identical to the check."
        done < "$_tsv"
    elif [ "$_rc" -ne 0 ]; then
        # Exit 2 is not exit 0, the same argument section_sonames makes.
        _why1=$(head -1 "$_why")
        set -- "${_mark}anything, because the check could not run:\
 ${_why1:-it gave no reason}. Until that is fixed, nothing here says this\
 machine carries no leftovers."
    fi
    rm -f "$_tsv" "$_why"

    prune_derived 'Packages' "$_mark"
    [ "$#" -gt 0 ] || return

    if section_present 'Packages'; then
        append_to_section 'Packages' "$@"
        return
    fi

    _blk=$(mktemp)
    _main=$OUTPUT
    OUTPUT=$_blk
    h 'Packages'
    for _b in "$@"; do li "$_b"; done
    OUTPUT=$_main
    { head -n 1 "$OUTPUT"; cat "$_blk"; tail -n +2 "$OUTPUT"; } \
        > "${OUTPUT}.tmp" && mv "${OUTPUT}.tmp" "$OUTPUT"
    rm -f "$_blk"
}
```

Then call it, in the invocation list near the end of the file, immediately after
`section_sonames`:

```sh
section_sonames
section_strays
section_verify
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
tests/post-setup-notes
tests/gates
```
Expected: both clean.

- [ ] **Step 5: Check it against this machine**

```bash
GATHERD_HOME="$PWD" scripts/gatherd-post-setup-notes
grep -A3 '^# Packages' ~/.config/gatherd-post-setup.md || echo "no Packages section -- machine is clean"
```

Expected after Task 3: no `Packages` section, because the machine has no strays.
To see the section render, install a throwaway package and re-run:

```bash
sudo pacman -S --asexplicit --noconfirm cowsay
GATHERD_HOME="$PWD" scripts/gatherd-post-setup-notes
grep -A3 '^# Packages' ~/.config/gatherd-post-setup.md
sudo pacman -Rs --noconfirm cowsay
```

- [ ] **Step 6: shellcheck**

Run: `shellcheck scripts/gatherd-post-setup-notes`
Expected: clean, or no new findings beyond what the file already had — check with
`git stash` if unsure which are yours.

- [ ] **Step 7: Commit**

```bash
git add scripts/gatherd-post-setup-notes tests/post-setup-notes
git commit -m "Report packages nothing accounts for at login

Claude-Session: https://claude.ai/code/session_01QVDsBp9rLkfbTm8hWLUot8"
```

---

## Task 5: Add the verify step and retire the plan

**Files:**
- Modify: `scripts/gatherd-post-setup-notes` (the `section_verify` function)
- Modify: `plans/TODO.md` (only if an item there covers this; see Step 2)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Add one verify_li line**

CLAUDE.md: keep it short, very often one line, and prefer a command to a
description. In `section_verify`, add:

```sh
    verify_li 'Nothing is unaccounted for: `/usr/local/lib/gatherd/scripts/gatherd-assert-packages-declared; echo $?` prints `0`. Then `sudo pacman -S --asexplicit --noconfirm cowsay`, log out and in: the Packages section names cowsay. `sudo pacman -Rs cowsay`.'
```

- [ ] **Step 2: Check the backlog**

```bash
grep -n -i 'electron\|undeclared\|stray' plans/TODO.md
```

If an item there describes this work, delete it — CLAUDE.md, "Finishing a TODO
item". If nothing matches, this never had a backlog entry; change nothing.

- [ ] **Step 3: Count the verify list and say the number out loud**

```bash
grep -c 'verify_li' scripts/gatherd-post-setup-notes
```

It was **29** before this change, measured 2026-10-04 — already far past the
threshold of 10, and this task adds a thirtieth. CLAUDE.md, Repave cadence: say
so to the human and suggest working the checklist. Do not start a repave, and do
not delete anyone else's verify steps to bring the count down — step 2 of that
cadence is deleting steps *that have been exercised*, which is a repave's work,
not this plan's.

- [ ] **Step 4: Full suite, then commit**

```bash
tests/gates
shellcheck scripts/gatherd-post-setup-notes
git add scripts/gatherd-post-setup-notes plans/TODO.md
git commit -m "Add the verify step for the stray-package gate

Claude-Session: https://claude.ai/code/session_01QVDsBp9rLkfbTm8hWLUot8"
```

- [ ] **Step 5: Push**

```bash
git push origin main
```

Then, so the machine actually runs it — the failure that started this was a
deployed checkout nine commits behind:

```bash
sudo git -C /usr/local/lib/gatherd pull
```

---

## Not in scope

- **Removing anything automatically.** The check reports. CLAUDE.md's warning
  about orphan sweeps turning a green machine red is the reason, and the two
  possible fixes for a stray (declare it, or remove it) are not distinguishable
  from inside the check.
- **A built-but-not-installed notice.** Spec §2: `arch-update` already does
  this, measured. `[gatherd-aur]` is a configured pacman repo, so
  `pacman -S -y -u` upgraded both stale AUR packages on 2026-10-04 at 10:07:25
  straight out of it.
- **A `MIGRATIONS.md` entry.** No `state: absent` task is added anywhere.
- **Non-explicit packages.** `pacman -Qdtq` covers those and needs nothing here.
