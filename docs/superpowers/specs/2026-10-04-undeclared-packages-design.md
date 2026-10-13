# Undeclared Installed Packages — Design

**Type:** New gate. One check, on the machine side of the repo/machine boundary,
naming every explicitly-installed package that neither the base image nor this
repo accounts for.

**Date:** 2026-10-04
**Status:** Draft. No decisions open. Not yet implemented.
**Related:** `scripts/gatherd-assert-sonames` (the same boundary, the same
placement, and the header that argues the case), `scripts/gatherd-check-aur-deps`
(the repo-side gate whose playbook walk this reuses),
`specs/2026-09-01-spent-cleanup-detection-design.md` (what a gate does when the
thing it names is spent).

---

## 1. Problem

A converged machine accumulates explicitly-installed packages that this repo has
stopped declaring, and nothing notices.

Measured on atm-card, 2026-10-04, after the 09:49 converge:

```
$ pacman -Qi electron42 | sed -n '/^Required By/p;/^Install Reason/p'
Required By     : teams-for-linux-electron-bin
Install Reason  : Explicitly installed
```

`electron42` was declared in `group_vars/all/main.yml` until `faf799b`
("Follow three AUR packages that moved out from under us"), which replaced it
with `electron44` to match slack-electron's current PKGBUILD. The repo was
correct from that commit onward. The machine kept the package, explicitly
installed, for as long as its old slack-electron build kept needing it — and
then kept it after the upgrade too, because nothing asks the question.

`pacman -Qdtq` does not find it: the package is *explicitly* installed, so no
orphan sweep reaches it. Measured on atm-card, 2026-10-04, against `nowayprompt`
— explicitly installed, `Required By : None`, the same shape `electron42` had:

```
$ pacman -Qdtq | wc -l
0
$ pacman -Qdtq | grep -c '^nowayprompt$'
0
```

`electron42` came off only because a human was told to type
`pacman -Rs electron42`.

### 1.1 What already catches the other direction

The mirror-image failure — the build needs something nothing declares — is
caught twice, and was caught that same morning. From
`journalctl -u gatherd-async.service`, 2026-10-04 09:33:04:

```
Not installed, and makepkg cannot install them (PACMAN_AUTH=/bin/false):
  asar
  electron44
```

That is `gatherd-assert-aur-deps` failing the slow AUR tier by name, exactly as
designed, and `gatherd-check-aur-deps` enforces the same rule pre-commit. Those
two gates are not the gap. Both read a declaration and ask whether it is
satisfied; neither can ask whether a satisfied thing is still declared.

### 1.2 Why this needs a third gate rather than an extension

`gatherd-check-aur-deps` reads only the repo. On a repo where `electron42` has
already been removed from `group_vars` — which is the state from `faf799b`
onward — there is nothing left in the repo to find. The stray exists only on the
machine. That is the same argument `gatherd-assert-sonames` makes in its own
header for its own existence:

> That gate is DECLARED-not-PRESENT by design and reads only the repo, so it
> cannot see this and never will. Hence a second check on the other side of the
> boundary: this one reads only the machine, after the converge, and asks the
> question the dynamic loader asks.

This gate asks a different machine-side question — not "can it load", but "is it
accounted for" — and belongs beside it.

## 2. Non-goal: noticing built-but-not-installed

The converge builds new AUR versions into `[gatherd-aur]` and installs with
`state: present`, which an older installed version already satisfies. On
2026-10-04 that left slack-electron 4.52.155-1 and
teams-for-linux-electron-bin 2.23.0-1 sitting in the local repo while 4.51.191-1
and 2.20.0-1 stayed installed.

That gap is deliberate and already covered. `group_vars/all/main.yml:271-274`
records the policy: gatherd converges to **installed**, not latest, and upgrades
belong to `arch-update`, the notifier `roles/desktop/tasks/rest.yml:62` enables.
There is no `state: latest` anywhere under `roles/`.

And the chain works, measured. `[gatherd-aur]` is a configured pacman repo
(`/etc/pacman.conf`), so the ordinary upgrade path sees its contents — it is not
a foreign package set. From `/var/log/pacman.log`:

```
[2026-10-04T10:07:15-0400] [PACMAN] Running 'pacman -S -y -u --config /etc/pacman.conf --'
[2026-10-04T10:07:25-0400] [ALPM] upgraded slack-electron (4.51.191-1 -> 4.52.155-1)
[2026-10-04T10:07:25-0400] [ALPM] upgraded teams-for-linux-electron-bin (2.20.0-1 -> 2.23.0-1)
```

A second notifier for this would duplicate a working one. Not built.

## 3. Goals

- Every explicitly-installed package is accounted for: in the measured base
  image, or declared by this repo, or named by the check with a reason to look.
- The check reads the playbooks rather than restating them, so a reordered or
  renamed tier cannot leave it green by accident.
- Anything it cannot parse is a hard failure, never a silent skip.
- It reports; it never removes. CLAUDE.md's standing warning applies: "an orphan
  sweep can turn a green machine red, and the fix is to declare what it names."

## 4. Design

### 4.1 Name and placement

`scripts/gatherd-assert-packages-declared`, with `tests/assert-packages-declared`
beside it.

`gatherd-check-*` read only the working tree and run from `tests/gates`.
`gatherd-assert-*` read the machine. This reads the machine against the tree, so
it is an `assert-*`, and it runs where `gatherd-assert-sonames` runs: from
`scripts/gatherd-post-setup-notes` at every login, after the converge.

Not a `verify_li` step, for the reason `section_sonames` already gives about
itself: a verify step is a manual acceptance check and is deleted once exercised
(CLAUDE.md, Repave cadence), so after the next repave nothing would invoke this
at all. And not a task in `site-async.yml`: that play writes `async-complete`
only when no tier failed, and `gatherd-await-and-run` gates the whole REST run on
that sentinel, so one stray package would re-run every REST tier on every boot,
forever, over a leftover electron.

### 4.2 The three sets

**Installed:** `pacman -Qeq`. Explicitly installed only — a package pulled in as
a dependency is accounted for by whatever depends on it, and `pacman -Qdtq`
already covers the case where that thing goes away. Measured on atm-card:
310 packages.

**Base:** `tests/base-manifest.txt`, which is measured from a first-boot
`/var/log/pacman.log` rather than derived (CLAUDE.md, AUR dependencies).
Measured: 896 packages. The manifest's `# arch:` header must match
`platform.machine()`; `gatherd-check-aur-deps` already refuses on a mismatch and
this check refuses the same way, because one architecture's answer would mark the
wrong packages present.

**Declared:** every package this repo installs or builds, read out of the
playbooks.

### 4.3 Reading the declared set

`gatherd-check-aur-deps` already walks the playbooks and emits exactly the two
event kinds this needs. From its `visit()`:

- `('install', names_from(pacman['name'], gv), conds)` for every
  `community.general.pacman` task whose `state` is not a removal
- `('build', (where, task_name, targets, conds))` for every `aur sync` line

`names_from(value, gv)` resolves a literal, a list, or a bare `{{ var }}` against
`group_vars/all/main.yml`. That covers all 28 `community.general.pacman` tasks
under `roles/`: 19 literal names and 6 bare `*_packages` vars, measured
2026-10-04.

So the declared set is the union of every `install` event's names and every
`build` event's targets. This check imports that module rather than
reimplementing the walk — a second parser would drift from the first, and the
first is the one that already handles role includes, `tasks_from`, inherited
`when:` conditions and arch gating.

The module has no `.py` extension, so `spec_from_file_location` alone returns
`None`; it needs an explicit loader. Measured working form:

```python
from importlib.machinery import SourceFileLoader
import importlib.util as u
p = 'scripts/gatherd-check-aur-deps'
s = u.spec_from_file_location('cad', p, loader=SourceFileLoader('cad', p))
m = u.module_from_spec(s); s.loader.exec_module(m)
```

It has an `if __name__ == '__main__':` guard, so importing it runs nothing.

**Conditions are ignored here, deliberately.** `gatherd-check-aur-deps` needs
`when:` conditions because it reasons about tier ORDER — what is installed before
what. This check asks only whether the repo declares a package anywhere, so a
hardware-gated declaration still counts. Were it to respect conditions, every
`has_*` package absent from this machine's profile would read as undeclared on
the machines that do have it, which inverts the gate.

**Entry points.** `ENTRY_POINTS` in that module is
`('site-core.yml', 'site-async.yml')`; this check walks `site-vault.yml` as well.
That play installs no packages today. Measured, 2026-10-04:

```
$ grep -c community.general.pacman site-vault.yml
0
$ grep -rc community.general.pacman roles/machine_facts/tasks/
roles/machine_facts/tasks/main.yml:0
```

Its first play names one role (`machine_facts`) and its second play has `tasks:`
rather than `roles:` — three tasks, none of them a pacman task. But a vault task
that installed a package would otherwise read as a stray, and the walk is free.

### 4.4 The irreducible cases

Three packages on a converged machine are installed by gatherd but not reachable
as an `install` or `build` event. Each needs naming in the check, with its
reason, in the shape `gatherd-check-aur-deps` already uses for its `ALLOWED`
table.

| Package | Why the walk misses it | Handling |
|---|---|---|
| `aurutils` | Installed by `roles/system/tasks/aurutils.yml` from a vendored PKGBUILD, via `community.general.pacman: name: "{{ _aurutils_built.files[0].path }}"`. `names_from` cannot resolve a registered-fact subscript and returns nothing for it (measured below). | Declared, with the task file cited. |
| `nowayprompt` | Same shape, `roles/system/tasks/nowayprompt.yml`. | Declared, with the task file cited. |
| `ansible` | gatherd's own bootstrap. It is installed before any playbook exists to declare it. | Declared, with the reason. Deliberately NOT added to `tests/base-manifest.txt` — CLAUDE.md names that exact trap: "counting gatherd's own `ansible` install as base is what certified `python-cryptography`." |

Measured, 2026-10-04, against this repo's `names_from`:

```
'{{ _aurutils_built.files[0].path }}' -> []
'{{ rest_packages }}'                 -> ['curl', 'git']
'literal-pkg'                         -> ['literal-pkg']
```

`names_from` dropping an unresolvable expression is safe in this direction: a
dropped name makes a package read as *undeclared*, which is loud, rather than as
declared, which would be blind. The table exists to silence three known-good
names, not to paper over a parser that fails quietly.

### 4.5 Output and exit codes

Following `gatherd-check-aur-deps`:

- **0** — every explicitly-installed package is accounted for.
- **1** — one or more strays, each named on stderr, with the two things a human
  can do about it: declare it in a `*_packages` var, or remove it.
- **2** — could not run. A missing or wrong-architecture `tests/base-manifest.txt`,
  an unreadable `group_vars/all/main.yml`, a failed `pacman -Qeq`, or a
  `community.general.pacman` task whose `name:` resolves to nothing while being
  neither a literal nor a known var. Never a silent skip.

A `--tsv` mode prints one stray per line, for `gatherd-post-setup-notes` to turn
into bullets — the same contract `gatherd-assert-sonames --tsv` has.

### 4.6 What it finds on atm-card today

With §4.4 handled and `rate-mirrors` still undeclared, exactly one line:

```
rate-mirrors
```

Measured by hand, 2026-10-04:

```
$ pacman -Qeq | sort > explicit        # 310
$ comm -23 explicit declared | comm -23 - base
ansible
aurutils
nowayprompt
rate-mirrors
```

`rate-mirrors` is a genuine finding, not noise. It is the `Depends =` of a pacman
hook this repo installs (`roles/system/tasks/core.yml:136`), it is in no
`*_packages` var, and it is not in `tests/base-manifest.txt` — so on a fresh
repave it is absent and the hook's dependency is unmet. Declaring it in
`rest_packages` is part of this change, which makes the gate green honestly
rather than by exemption.

Had `electron42` not been removed by hand at 10:07:51, it would have been the
second line.

## 5. Testing

`tests/assert-packages-declared`, run from `tests/gates`' unit-test block.
`tests/gates` already enforces the pairing by glob over
`scripts/gatherd-{check,assert}-*`, so the sibling test is not optional.

Machine state is injected the way `tests/assert-sonames` does it: a `pacman`
shim on `$PATH` answering from `$GATHERD_TEST_DB`, which here needs only `-Qeq`.
Repo state is a sandbox tree holding a `group_vars/all/main.yml`, a
`tests/base-manifest.txt` with a matching `# arch:` header, and the playbooks the
walk reaches.

Cases it pins:

1. A package installed, in no var, not in base → exit 1, named.
2. A package installed and declared in a `*_packages` var → exit 0.
3. A package installed and in the base manifest, declared nowhere → exit 0.
4. A package declared only through a vendored-PKGBUILD task → exit 0 (the §4.4
   table, not an accident of parsing).
5. A package declared under a `when: has_*` this machine does not satisfy →
   exit 0 (§4.3: conditions ignored).
6. A base manifest whose `# arch:` disagrees with the machine → exit 2.
7. A missing base manifest → exit 2.
8. `pacman -Qeq` failing → exit 2.
9. The functions this check imports from `gatherd-check-aur-deps` still exist
   and still behave — so that gate's next refactor fails here rather than
   silently widening the declared set.

Case 9 is what makes the reuse in §4.3 safe to choose over a private parser.

## 6. Scope

In:

- `scripts/gatherd-assert-packages-declared`
- `tests/assert-packages-declared`, wired into `tests/gates`
- A `section_strays` in `scripts/gatherd-post-setup-notes`, plus its coverage in
  `tests/post-setup-notes`
- `rate-mirrors` declared in `rest_packages`
- One `verify_li` step

Out:

- Removing anything automatically (§3).
- Any built-but-not-installed notice (§2).
- Non-explicit packages; `pacman -Qdtq` covers that and needs nothing from here.
- `MIGRATIONS.md`: this change adds no `state: absent` task.
