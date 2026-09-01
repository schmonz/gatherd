# Migration Ledger (Phase 1: census and ledger) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a mechanical census of removal-shaped Ansible tasks and a `MIGRATIONS.md` ledger seeded from it, so that what each removal carries forward stops being undocumented.

**Architecture:** One Python script, `scripts/gatherd-census-removals`, walks the task YAML with a line-number-preserving loader and reports every task carrying a removal shape. A `--ledger` mode emits those findings in `MIGRATIONS.md` entry format. Entries start with no `check:` line, which is the ledger's legitimate "unmeasured" state, not a placeholder. Nothing classifies anything: classification is the output of the Phase 2 measurement pass.

**Tech Stack:** Python 3 with PyYAML (already a dependency of `scripts/gatherd-check-package-tiers`), POSIX `sh` for tests, `ansible-lint` for the repo gate.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-01-spent-cleanup-detection-design.md`.
- Calling convention mirrors `scripts/gatherd-check-package-tiers`: optional repo-root argument, defaults to the repo the script lives in.
- Scan set is exactly `roles/*/tasks/*.yml`, `tasks/*.yml`, `site-*.yml`. `plans/` and `docs/` are excluded: they contain verbatim task YAML in plan documents and would register as phantom tasks.
- The script classifies nothing and deletes nothing. It reports.
- Run `ansible-lint` before committing (repo rule in `CLAUDE.md`).
- Python scripts in `scripts/` carry a module docstring stating purpose and the usage/exit contract, matching `gatherd-check-package-tiers`.
- Expected census on the tree at `fa86109`: **43** tasks — 34 `state: absent`, 5 `force+link`, 4 `unit off`.

---

### Task 1: Census script

**Files:**
- Create: `scripts/gatherd-census-removals`
- Test: `tests/census-removals`

**Interfaces:**
- Produces: executable `scripts/gatherd-census-removals [repo-root]`, printing one line per finding as `<path>:<line>\t<shape>\t<task name>`, sorted by path then line. Exit 0 always (it is a report, not a gate). `--ledger` switches output to ledger-entry format, consumed by Task 2.

- [ ] **Step 1: Write the failing test**

Create `tests/census-removals`:

```sh
#!/bin/sh
# Unit tests for gatherd-census-removals.
#
# Fixtures pin the two things the walker must get right and that a naive
# implementation gets wrong: a shape nested inside a block: must be credited to
# the task that owns it rather than to the block parent, and the reported line
# must be the task's own `- name:` line.
#
# Usage: tests/census-removals

set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
CENSUS="$REPO/scripts/gatherd-census-removals"
PASS=0
FAIL=0

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/roles/demo/tasks"

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }

assert_out() {
    _d=$1; _want=$2; shift 2
    _got=$("$@" 2>/dev/null || true)
    if [ "$_got" = "$_want" ]; then ok "$_d"; else bad "$_d (want [$_want] got [$_got])"; fi
}

cat > "$WORK/roles/demo/tasks/main.yml" <<'FIXTURE'
---
- name: Plain removal
  ansible.builtin.file:
    path: /tmp/gone
    state: absent

- name: Not a removal
  ansible.builtin.file:
    path: /tmp/here
    state: touch

- name: Block parent
  block:
    - name: Nested removal
      ansible.builtin.file:
        path: /tmp/nested
        state: absent

- name: Forced symlink
  ansible.builtin.file:
    src: /tmp/a
    dest: /tmp/b
    state: link
    force: true

- name: Masked unit
  ansible.builtin.systemd:
    name: demo.service
    masked: true
FIXTURE

assert_out "reports every shape, credits the owning task, keeps line numbers" \
"roles/demo/tasks/main.yml:2	state: absent	Plain removal
roles/demo/tasks/main.yml:14	state: absent	Nested removal
roles/demo/tasks/main.yml:19	force+link	Forced symlink
roles/demo/tasks/main.yml:26	unit off	Masked unit" \
    "$CENSUS" "$WORK"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

Make it executable: `chmod +x tests/census-removals`

- [ ] **Step 2: Run test to verify it fails**

Run: `tests/census-removals`
Expected: FAIL — `scripts/gatherd-census-removals` does not exist, so the command produces empty output and the comparison fails.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/gatherd-census-removals`:

```python
#!/usr/bin/env python3
"""Report every task carrying a removal shape.

The playbook accumulates tasks that exist only to carry already-converged
machines past a change. Which of them are spent is not derivable from the code
-- see docs/superpowers/specs/2026-09-01-spent-cleanup-detection-design.md --
so this script deliberately classifies nothing. It produces the inventory that
MIGRATIONS.md is seeded from, mechanically, because the hand-curated list it
replaces was not reproducible and was wrong three times in nineteen.

A shape is credited to the task that owns it, never to an enclosing block:.
Crediting the parent is what an earlier grep-based attempt did, and it inflated
the count with tasks that remove nothing.

plans/ and docs/ are outside the scan set on purpose: plan documents quote task
YAML verbatim and would register as phantom tasks.

Usage: gatherd-census-removals [repo-root] [--ledger]   (exit 0; this reports)
"""
import sys
from pathlib import Path

import yaml

NEST = ('block', 'rescue', 'always')
PLAY_KEYS = ('tasks', 'pre_tasks', 'post_tasks')


class LineLoader(yaml.SafeLoader):
    """SafeLoader that records each mapping's source line."""


def _construct_mapping(loader, node):
    mapping = super(LineLoader, loader).construct_mapping(node, deep=True)
    mapping['__line__'] = node.start_mark.line + 1
    return mapping


LineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _args(task):
    return [v for v in task.values() if isinstance(v, dict)]


SHAPES = (
    ('state: absent', lambda t: any(a.get('state') == 'absent' for a in _args(t))),
    ('force+link', lambda t: any(
        a.get('state') == 'link' and a.get('force') is True for a in _args(t))),
    ('unit off', lambda t: any(
        a.get('enabled') is False or a.get('masked') is True for a in _args(t))),
)


def walk(tasks, path, found):
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        nested = [k for k in NEST if k in task]
        for key in nested:
            walk(task[key], path, found)
        if nested:
            continue
        for label, matches in SHAPES:
            if matches(task):
                found.append((path, task.get('__line__'), label, task.get('name')))
                break


def scan(root):
    found = []
    paths = sorted(root.glob('roles/*/tasks/*.yml')) \
        + sorted(root.glob('tasks/*.yml')) + sorted(root.glob('site-*.yml'))
    for path in paths:
        try:
            doc = yaml.load(path.read_text(), Loader=LineLoader)
        except (yaml.YAMLError, UnicodeDecodeError) as exc:
            print(f'{path}: unreadable: {exc}', file=sys.stderr)
            continue
        if not isinstance(doc, list):
            continue
        rel = path.relative_to(root).as_posix()
        walk(doc, rel, found)
        for play in doc:
            if isinstance(play, dict):
                for key in PLAY_KEYS:
                    walk(play.get(key), rel, found)
    return sorted(found, key=lambda f: (f[0], f[1] or 0))


def main():
    argv = [a for a in sys.argv[1:] if a != '--ledger']
    ledger = '--ledger' in sys.argv[1:]
    root = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent
    for path, line, shape, name in scan(root):
        if ledger:
            print(f'- {path}:{line} — {name}\n  shape: {shape}')
        else:
            print(f'{path}:{line}\t{shape}\t{name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

Make it executable: `chmod +x scripts/gatherd-census-removals`

- [ ] **Step 4: Run test to verify it passes**

Run: `tests/census-removals`
Expected: `4 passed, 0 failed`, exit 0.

- [ ] **Step 5: Verify against the real tree**

Run: `scripts/gatherd-census-removals | wc -l`
Expected: `43`

Run: `scripts/gatherd-census-removals | cut -f2 | sort | uniq -c | sort -rn`
Expected:
```
     34 state: absent
      5 force+link
      4 unit off
```

Run: `scripts/gatherd-census-removals | grep -c 'Build and install aurutils'`
Expected: `0` — that task encloses a removal in a `block:` but removes nothing itself. A non-zero result means block attribution regressed.

- [ ] **Step 6: Commit**

```bash
ansible-lint
git add scripts/gatherd-census-removals tests/census-removals
git commit -m "Census the removal-shaped tasks mechanically"
```

---

### Task 2: Seed MIGRATIONS.md

**Files:**
- Create: `MIGRATIONS.md`

**Interfaces:**
- Consumes: `scripts/gatherd-census-removals --ledger` from Task 1.
- Produces: `MIGRATIONS.md`, whose entries Phase 2 annotates with `check:` and `fresh-install expectation:` lines.

- [ ] **Step 1: Generate the entry list**

Run: `scripts/gatherd-census-removals --ledger > /tmp/ledger-entries.txt`
Expected: 86 lines (43 entries × 2).

- [ ] **Step 2: Write MIGRATIONS.md**

Create `MIGRATIONS.md` with this header, then paste the generated entries beneath the `## Unmeasured` heading:

```markdown
# Migrations

What each removal-shaped task in the playbook carries forward, and whether it
is still needed. Generated initially by `scripts/gatherd-census-removals
--ledger`; maintained by hand thereafter.

Design and rationale: `docs/superpowers/specs/2026-09-01-spent-cleanup-detection-design.md`.

**This file licenses nothing.** An entry recorded as a pure migration says only
that the task does no work on a fresh install. It does *not* say every machine
has converged past it, which is what actually gates deletion and which nothing
here can answer.

## How an entry works

    - roles/system/tasks/user_path.yml:34 — Remove obsolete profile.d PATH file
      shape: state: absent
      thing: /etc/profile.d/gatherd-local-bin.sh, replaced by pam_env
      check: test -e /etc/profile.d/gatherd-local-bin.sh
      fresh-install expectation: absent (pure migration)
      measured: 2026-09-14 absent

One entry per removed *thing*, not per task: several tasks loop over items of
mixed provenance, and one verdict cannot cover items that legitimately differ.

`fresh-install expectation` is stated per entry rather than inferred, because
polarity inverts: for an additive task, "present on a fresh install" means the
task is a no-op there.

Two rules for writing a `check`, both from measured failures:

- Never copy a task's regexp into `grep -E`. Ansible regexps are Python `re`;
  `(?:...)` and `(?!...)` are errors under `grep -E` and work only under `-P`.
- Never use `~` or a relative path. Checks run as root, where `~` is `/root`.

A check is trusted only once it has been *calibrated* — demonstrated returning
the "still does work" answer somewhere it should. Until then the entry is
unmeasured, because every accidental failure (missing binary, wrong dialect,
unexpected path) exits nonzero, which is the answer that licenses deletion.

## Unmeasured
```

- [ ] **Step 3: Verify the file is complete and honest**

Run: `grep -c '^- roles/\|^- tasks/\|^- site-' MIGRATIONS.md`
Expected: `43`

Run: `grep -c 'check:' MIGRATIONS.md`
Expected: `1` — only the example in the "How an entry works" section. Every real entry is unmeasured until Phase 2, and that is a legitimate state rather than a placeholder.

- [ ] **Step 4: Commit**

```bash
git add MIGRATIONS.md
git commit -m "Seed the migration ledger from the census"
```

---

### Task 3: The CLAUDE.md rule

**Files:**
- Modify: `CLAUDE.md` (new section after "Finishing a TODO item")

- [ ] **Step 1: Add the section**

Insert after the "Finishing a TODO item" section:

```markdown
## Migrations

A task that exists only to carry already-converged machines past a change gets
an entry in `MIGRATIONS.md` when it is written. Same moment as adding a
`verify_li` step — a change lands, its follow-up gets recorded.

Regenerate the inventory with `scripts/gatherd-census-removals` when you want to
check nothing was missed; it reports, and classifies nothing.

**Any unmeasured entry means the ledger is due for a measurement pass**, which
runs against a snapshot of the Calamares-only base image (`tests/create-base`).
Deliberately not a count over a threshold: unlike a `verify_li` step, which is
spent once exercised and deleted, a measured entry stays, so a count would be
permanently true and never clear — which is how the verify list reached 23
against a threshold of 10.

Retirement is never scheduled. Deleting one of these wrongly fails silently for
nearly all of them, so an entry becomes a deletion candidate only for someone
already working in that file.
```

- [ ] **Step 2: Verify the count claim is still true**

Run: `grep -c "verify_li" scripts/gatherd-post-setup-notes`
Expected: a number well above 10. If it has come down below 10, reword the
parenthetical rather than leaving a false statement in `CLAUDE.md`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "Record the rule for migration ledger entries"
```

---

## Not in this plan

**Phase 2 — the measurement pass — is blocked and deliberately excluded.** It
needs a snapshot of `$GATHERD_VM_DIR/eos-base.qcow2`, and that image does not
exist on this machine (`~/.local/share/gatherd/` holds only `icloud-backup`).
Building it means `tests/create-base <ISO>`: a multi-GB EndeavourOS ISO plus a
human driving Calamares interactively. Until it exists, the runner cannot be
tested, so writing it would mean shipping unverified code — which is what the
whole spec exists to avoid.

Phase 2 covers: a runner that boots a snapshot and executes each entry's check;
authoring and calibrating the checks; and recording results back into
`MIGRATIONS.md`.

**Splitting loop tasks into per-thing entries is Phase 2 work.** The spec
requires one entry per removed *thing*; the census necessarily emits one per
*task*. Several tasks loop over items of mixed provenance — `roles/desktop/
tasks/core.yml` loops eight autostart regexps in one task and four in another,
mixing `^exec conky$` with `^exec (?:.*/)?gatherd-polkit-agent$`. Those entries
must be split before they can carry a meaningful `check`, and the split is only
decidable while writing the checks, which is Phase 2. Seeding them per-task here
is correct: an unmeasured per-task entry is an honest record of what was
censused, and splitting early would mean guessing the provenance of items whose
provenance is exactly what the measurement determines.

**A completeness gate is not included, and is worth a decision later.** With a
mechanical census, a check that every censused task has a ledger entry would be
cheap, and would close the "a migration written with no entry is invisible" gap
the spec lists as a known limit. It is omitted here because the spec does not
specify it, and because it would fail on day one for all 43 entries until the
ledger is populated.
