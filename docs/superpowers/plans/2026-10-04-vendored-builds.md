# Vendored Builds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build every vendored PKGBUILD into `[gatherd-aur]` with `aur build` and install it by name, move nowayprompt onto that mechanism, and use it to give the TI-84 backup scripts `tiget`, `ti-tools` and `8xvtopy`.

**Architecture:** `gatherd-check-aur-deps` learns a second kind of build — an `aur_build_command` task looping over a `*_packages` list, whose dependencies come from the committed `packaging/<pkg>/.SRCINFO`. Two sites use it: system REST builds `vendored_packages` (nowayprompt) right after aurutils exists; the slow AUR tier builds the TI library chain in three `aur sync` rounds, then `vendored_slow_packages` (titools, ti-tools, 8xvtopy).

**Tech Stack:** Ansible (`ansible.builtin.*`, `community.general.pacman`), aurutils 20.5.8 (`aur build`, `aur sync`), makepkg, Python 3 (`gatherd-check-aur-deps`), POSIX `sh` tests.

**Spec:** `docs/superpowers/specs/2026-10-04-vendored-builds-design.md`

## Global Constraints

- `tests/gates` is the one command to run before committing. It is green today apart from `tests/assert-aur-deps`, which fails 7 cases on a clean HEAD (measured 2026-10-04); that failure is not yours and must not grow.
- `ansible-lint` clean at the `production` profile for every YAML file touched. (A bare run reports one pre-existing `internal-error` on `site-vault.yml` with no `.vault_pass`; not yours.)
- FQCN always: `ansible.builtin.*`, `community.general.*`.
- Task names are imperative sentences. Comments say *why*, never *what*.
- Every AUR build runs with `environment: "{{ aur_build_environment }}"`, so makepkg cannot reach for root.
- Every `aur sync` is immediately preceded by `tasks/assert_aur_deps.yml` over the same packages under the same `when:`. `aur build` is exempt (spec §4.1.4).
- A removal-shaped task gets a `MIGRATIONS.md` entry in the same commit; `scripts/gatherd-check-migrations` enforces it.
- Never build inside `{{ setup_dir }}` (root-owned checkout). Copy to `{{ target_home }}/.cache/gatherd/vendored/<pkg>/` and build there as `target_user`.
- Commit messages end with `Claude-Session: https://claude.ai/code/session_01UeT4HEYuzFyvcagw5P7Hhn`.
- The working tree carries the owner's unrelated uncommitted edits to `roles/desktop/templates/waterfox-userChrome.css.j2` and `scripts/gatherd-post-setup-notes` (two deleted `verify_li` lines). Never stage them. Task 5 edits `gatherd-post-setup-notes`: stage only your hunk (`git add -p` is unavailable; build the staged blob from `git show HEAD:<file>` plus your edit and `git update-index --cacheinfo`).

## Facts measured for this plan (2026-10-04)

| Fact | How |
|---|---|
| `aur build --database <db> --no-sync --noconfirm --margs --skippgpcheck` builds and `repo-add`s; all four flags accepted | probe PKGBUILD into a scratch repo via `--pacman-conf` |
| Second run: stderr `build: warning: skipping existing package (use -f to overwrite)`, rc 0, no rebuild | same probe, stdout and stderr captured separately |
| makepkg with a missing `depends` or `makedepends`: rc 8, `==> Missing dependencies:`, no `Retrieving` line | probe with `source=(https://example.invalid/...)` |
| In a looped task, `changed_when` sees the item's own result; the registered var's `.changed` is true if any item changed | `ansible-playbook` on localhost: `[False, True] aggregate=True` |
| AUR deps: libticonv→glib2; libticables→libusb, glib2; libtifiles→libarchive, libticonv; libticalcs→libticables, libtifiles | AUR `.SRCINFO` |
| TITools `cc7dc08d831beaf6c4f865c3acd49a2be58df5a9`: shipped `./configure && make` builds against the four libs; `make install DESTDIR=` installs 8 binaries + 7 man pages | scratch build |
| ti-tools `654a8e28e79d7de62bb333c8f5656a93f90ba017` (MIT): `cargo build --release --locked` builds `target/release/ti-tools` | scratch build |
| 8xvtopy `0b745472e2eb293881fcf5d787a64f1e62dc8711` (no license): reproduces `data/BDAY.py` | scratch venv |
| `visit()` returns early for a path already in `seen` | `scripts/gatherd-check-aur-deps`, `visit()` |
| `ansible.builtin.copy` with `remote_src: true`, `src: <dir>/`, `mode: preserve`, in a loop: copies the contents including dotfiles, keeps each file's mode (640 stayed 640), second run `ok` | `ansible-playbook` on localhost |
| `cowsay` (Task 1's fixture dependency) is in neither `tests/base-manifest.txt` nor `group_vars` | `grep` |

---

## Task 1: Teach gatherd-check-aur-deps to read vendored builds

**Files:**
- Modify: `scripts/gatherd-check-aur-deps`
- Modify: `tests/check-aur-deps`

**Interfaces:**
- Produces: a task whose command contains `aur_build_command` and whose `loop:` is a literal list of names or a bare `{{ var }}` naming a list in `group_vars/all/main.yml` is a vendored build of those names. Its dependencies are read from `packaging/<name>/.SRCINFO`, which must equal `makepkg --printsrcinfo` for `packaging/<name>/PKGBUILD`. Exit 1 for an undeclared dependency, a missing or stale `.SRCINFO`, a missing PKGBUILD, an unreadable `loop:`, or an `aur_build_command` file no playbook reaches. Vendored builds need no guard.

- [ ] **Step 1: Write the failing tests**

In `tests/check-aur-deps`, add before the final tally (`printf '\n%s passed` … at the end of the file — read the file's tail to find it):

```sh
# 20. Vendored builds: `aur build` over a loop, dependencies from the committed
#     .SRCINFO. A probe package that needs cowsay, which nothing declares.
PROBE="$WORK/repo/packaging/probe-vendored"
mkdir -p "$PROBE"
cat > "$PROBE/PKGBUILD" <<'FIXTURE'
pkgname=probe-vendored
pkgver=1
pkgrel=1
arch=(any)
depends=(cowsay)
package() { :; }
FIXTURE
(cd "$PROBE" && makepkg --printsrcinfo > .SRCINFO)
printf '\nprobe_vendored_packages:\n  - probe-vendored\n' >> "$VARS"
cat >> "$WORK/repo/roles/aur/tasks/slow.yml" <<'FIXTURE'

- name: Build the vendored probe
  ansible.builtin.command: "{{ aur_build_command }}"
  args:
    chdir: "/nonexistent/{{ item }}"
  loop: "{{ probe_vendored_packages }}"
  changed_when: false
FIXTURE
assert_rc "a vendored build's undeclared dependency exits 1" 1
assert_says "and is named" "probe-vendored needs cowsay"

sed -i 's/^rest_packages:/rest_packages:\n  - cowsay/' "$VARS"
assert_rc "declared in an earlier tier, it exits 0 with no guard" 0

# 21. A .SRCINFO that no longer matches its PKGBUILD is not trusted.
sed -i 's/^depends=(cowsay)/depends=(cowsay sl)/' "$PROBE/PKGBUILD"
assert_rc "a stale .SRCINFO exits 1" 1
assert_says "and says so" "probe-vendored/.SRCINFO is stale"
(cd "$PROBE" && makepkg --printsrcinfo > .SRCINFO)
rm "$PROBE/.SRCINFO"
assert_rc "a missing .SRCINFO exits 1" 1
assert_says "and says so" "probe-vendored/.SRCINFO is missing"
(cd "$PROBE" && makepkg --printsrcinfo > .SRCINFO)

# 22. A loop this gate cannot resolve is a failure, never "builds nothing".
sed -i 's/loop: "{{ probe_vendored_packages }}"/loop: "{{ probe_vendored_packages | list }}"/' \
    "$WORK/repo/roles/aur/tasks/slow.yml"
assert_rc "an unreadable vendored loop exits 1" 1
assert_says "and names the build" "Build the vendored probe"
cp "$WORK/pristine-slow" "$WORK/repo/roles/aur/tasks/slow.yml"

# 23. A file that runs aur_build_command but no playbook reaches.
mkdir -p "$WORK/repo/roles/newthing/tasks"
cat > "$WORK/repo/roles/newthing/tasks/main.yml" <<'FIXTURE'
---
- name: Build something nobody reaches
  ansible.builtin.command: "{{ aur_build_command }}"
  loop: [probe-vendored]
  changed_when: false
FIXTURE
assert_rc "an unreachable vendored build exits 1" 1
assert_says "the unreachable file is named" "roles/newthing/tasks/main.yml"
rm -rf "$WORK/repo/roles/newthing" "$PROBE"
restore
```

- [ ] **Step 2: Run them to verify they fail**

Run: `tests/check-aur-deps 2>&1 | grep -E '^FAIL|passed'`
Expected: cases 20–23 FAIL (the gate ignores `aur_build_command`, so case 20 exits 0, the stale/missing cases exit 0, and so on). Earlier cases unchanged.

- [ ] **Step 3: Implement**

In `scripts/gatherd-check-aur-deps`:

(a) Add, after `targets_from`:

```python
def loop_targets(task, gv):
    """The packages a vendored `aur build` loops over, or None if it will not parse."""
    loop = task.get('loop')
    if isinstance(loop, list):
        names = [str(item) for item in loop]
    else:
        match = re.fullmatch(r'\{\{\s*(\w+)\s*\}\}', str(loop or '').strip())
        listed = gv.get(match.group(1)) if match else None
        names = [str(item) for item in listed] if isinstance(listed, list) else []
    if not names or any('{{' in name or '/' in name for name in names):
        return None
    return names


def vendored_srcinfo(root, name):
    """packaging/<name>/.SRCINFO, refused if its PKGBUILD no longer produces it.

    Read from the tree because a vendored package is not in the AUR, and
    regenerated to compare because a .SRCINFO is a copy of what the PKGBUILD
    says: a stale one would have this gate checking dependencies the build no
    longer has.
    """
    where = root / 'packaging' / name
    committed = where / '.SRCINFO'
    if not (where / 'PKGBUILD').is_file():
        raise Violation(f'packaging/{name}/PKGBUILD is missing, but a vendored '
                        f'build names {name}')
    if not committed.is_file():
        raise Violation(f'packaging/{name}/.SRCINFO is missing; run '
                        f'`makepkg --printsrcinfo > .SRCINFO` in packaging/{name}')
    try:
        done = subprocess.run(['makepkg', '--printsrcinfo'], cwd=where,
                              capture_output=True, text=True,
                              timeout=timeout_seconds())
    except (OSError, subprocess.TimeoutExpired) as failure:
        raise CannotRun(f'cannot run makepkg --printsrcinfo in '
                        f'packaging/{name}: {failure}') from failure
    if done.returncode != 0:
        raise CannotRun(f'makepkg --printsrcinfo failed in packaging/{name}: '
                        f'{done.stderr.strip()}')
    if done.stdout != committed.read_text():
        raise Violation(f'packaging/{name}/.SRCINFO is stale; run '
                        f'`makepkg --printsrcinfo > .SRCINFO` in packaging/{name}')
    return done.stdout
```

(b) In `visit()`, immediately after the `if command and 'aur_sync_command' in command:` block:

```python
        if command and 'aur_build_command' in command:
            where = path.relative_to(root).as_posix()
            targets = loop_targets(task, gv)
            if targets is None:
                events.append(('unreadable',
                               f'{where}: {task.get("name", "?")}: cannot tell '
                               'which vendored packages it builds; loop: must be '
                               'a list of names or a bare {{ var }}'))
            else:
                events.append(('vendored',
                               (where, task.get('name', '?'), targets, here)))
```

(c) In `unreachable()`: change `if 'aur_sync_command' in text:` to
`if 'aur_sync_command' in text or 'aur_build_command' in text:`, and its
docstring to `"""Files that build a package but no playbook ever reaches."""`.

(d) In `check()`, replace

```python
    cache = {name: srcinfo(fetch_srcinfo(*info[name]), arch) for name in sorted(asked)}
```

with

```python
    cache = {name: srcinfo(fetch_srcinfo(*info[name]), arch) for name in sorted(asked)}
    vendored = {pkg for kind, *rest in events if kind == 'vendored'
                for pkg in rest[0][2]}
    cache.update({name: srcinfo(vendored_srcinfo(root, name), arch)
                  for name in sorted(vendored)})
```

(e) In `check()`'s guard loop, replace `if event[0] != 'build':` and the
`continue` under it with:

```python
        # A vendored build needs no guard. The guard exists because `aur sync`
        # builds a chain and a missing dependency once surfaced fourteen
        # minutes in; `aur build` runs one makepkg per package, and makepkg
        # exits 8 naming a missing dependency before it fetches a single
        # source (measured 2026-10-04, spec §4.1.4).
        if event[0] != 'build':
            continue
```

The violations loop needs no change: it already treats every event that is not
`guard` or `install` as `(where, task, targets, conds)`, and `cache` now holds
the vendored names.

(f) In the module docstring, after the paragraph that ends "a task file that
will not load.", add:

```
VENDORED BUILDS. A task running aur_build_command over a loop: builds the
PKGBUILDs under packaging/, which the AUR has never heard of. Their
dependencies come from the committed packaging/<pkg>/.SRCINFO, regenerated
with makepkg --printsrcinfo and compared, so an edited PKGBUILD cannot leave
this gate checking the old list. Otherwise they are held to the same rule.
```

- [ ] **Step 4: Run the tests**

Run: `tests/check-aur-deps 2>&1 | grep -E '^FAIL|passed'`
Expected: `N passed, 0 failed` (N = previous count + 9).

Run: `scripts/gatherd-check-aur-deps . ; echo rc=$?`
Expected: `rc=0` — the real tree has no vendored builds yet.

- [ ] **Step 5: Full suite, lint, commit**

```bash
tests/gates 2>&1 | grep -E '^FAIL|passed'      # only tests/assert-aur-deps fails
git add scripts/gatherd-check-aur-deps tests/check-aur-deps
git commit -m "Check vendored builds' dependencies against their own .SRCINFO

Claude-Session: https://claude.ai/code/session_01UeT4HEYuzFyvcagw5P7Hhn"
```

---

## Task 2: Build nowayprompt with aur build

**Files:**
- Modify: `group_vars/all/main.yml`
- Create: `packaging/nowayprompt/.SRCINFO`
- Modify: `packaging/nowayprompt/PKGBUILD` (comments only)
- Create: `roles/system/tasks/vendored.yml`
- Modify: `roles/system/tasks/rest.yml:38-42`
- Delete: `roles/system/tasks/nowayprompt.yml`
- Modify: `MIGRATIONS.md`
- Modify: `scripts/gatherd-check-package-tiers` (ALLOWED)
- Modify: `scripts/gatherd-assert-packages-declared` (one comment)

**Interfaces:**
- Consumes: Task 1's vendored-build reading.
- Produces: `aur_build_command` and `vendored_packages` in group_vars; the three-task build pattern (copy, `aur build`, install by name) that Task 4 repeats.

- [ ] **Step 1: Add the vars**

In `group_vars/all/main.yml`, immediately after the `aur_sync_command` block
(after its `--makepkg-args --skippgpcheck` line), add:

```yaml

# The one way this repo builds a vendored PKGBUILD (packaging/<pkg>/). Run in a
# copy of that directory, as target_user, with aur_build_environment. Flags
# measured against aurutils 20.5.8 on 2026-10-04 with a probe package built
# into a scratch repo:
#   --database    into our repo by name, as aur_sync_command does
#   --no-sync     build and repo-add only; root installs by name afterwards
#   --noconfirm   makepkg --noconfirm
#   --margs --skippgpcheck   what aur_sync_command passes
# A version already in the repo is skipped, rc 0, with "skipping existing
# package" on stderr, which is what changed_when keys on.
aur_build_command: >-
  aur build --database {{ aur_repo_name }}
  --no-sync --noconfirm --margs --skippgpcheck
```

After the `aur_slow_avx_packages` list (before the `# Local pacman repository
that AUR builds land in.` comment), add:

```yaml
# Vendored PKGBUILDs (packaging/<pkg>/), built into the local repo with
# aur_build_command and installed by name. In system REST, right after
# roles/system/tasks/aurutils.yml creates aur and the repo.
vendored_packages:
  # Wayland askpass/pinentry; see packaging/nowayprompt/PKGBUILD for why vendored.
  - nowayprompt
```

In `rest_packages`, the comments on `base-devel` and `rust` name
`roles/system/tasks/nowayprompt.yml`. Change them to:

```yaml
  # fakeroot + cc, for the vendored builds (vendored_packages), which run
  # before the aur role would otherwise pull this in as an AUR build dependency.
  - base-devel
  # cargo, for nowayprompt's vendored build, and for arch-update's makedepends.
```

(only that first comment line changes; the two comment lines after it and
`- rust` stay as they are).

- [ ] **Step 2: Commit nowayprompt's .SRCINFO and fix its comments**

```bash
cd packaging/nowayprompt && makepkg --printsrcinfo > .SRCINFO && cd -
git status --short packaging/   # only .SRCINFO new; packaging/.gitignore hides build output
```

In `packaging/nowayprompt/PKGBUILD`, the header says `See
roles/system/tasks/nowayprompt.yml for why:` — change to `Why:`. Replace the
pkgver comment

```
# pkgver encodes _commit below (0.1.0+<short sha>) rather than staying a bare
# constant. roles/system/tasks/nowayprompt.yml compares the installed
# pkgver-pkgrel against this file's, so bumping _commit without bumping pkgver
# would otherwise never trigger a rebuild.
```

with

```
# pkgver encodes _commit below (0.1.0+<short sha>) rather than staying a bare
# constant. aur build skips a version already in the local repo, so bumping
# _commit without bumping pkgver would never trigger a rebuild.
```

A comment edit does not change `.SRCINFO`; confirm with
`cd packaging/nowayprompt && makepkg --printsrcinfo | diff - .SRCINFO && cd -`.

- [ ] **Step 3: Write roles/system/tasks/vendored.yml**

```yaml
---
# Vendored PKGBUILDs, built like AUR packages: aur build adds each to the local
# repo as target_user, and root installs it by name. That makes them visible to
# arch-update, to gatherd-check-aur-deps (which reads packaging/<pkg>/.SRCINFO)
# and to gatherd-assert-packages-declared, none of which can see a package
# installed from a file path.
#
# Built in a copy because makepkg writes its sources, src/ and pkg/ next to the
# PKGBUILD, and setup_dir is root's checkout.

- name: Copy the vendored PKGBUILDs to their build directories
  ansible.builtin.copy:
    src: "{{ setup_dir }}/packaging/{{ item }}/"
    dest: "{{ target_home }}/.cache/gatherd/vendored/{{ item }}/"
    remote_src: true
    owner: "{{ target_user }}"
    mode: preserve
  loop: "{{ vendored_packages }}"

- name: Build vendored packages into the local repository
  ansible.builtin.command: "{{ aur_build_command }}"
  args:
    chdir: "{{ target_home }}/.cache/gatherd/vendored/{{ item }}"
  loop: "{{ vendored_packages }}"
  become: true
  become_user: "{{ target_user }}"
  environment: "{{ aur_build_environment }}"
  register: _vendored_build
  changed_when: "'skipping existing package' not in _vendored_build.stderr"

# update_cache only when something was built, for the reason the AUR install in
# roles/aur/tasks/main.yml gives: an unconditional refresh makes a no-op install
# depend on the network and the pacman lock.
- name: Install vendored packages
  community.general.pacman:
    name: "{{ vendored_packages }}"
    state: present
    update_cache: "{{ _vendored_build.changed }}"

- name: Remove the build directory nowayprompt.yml used
  ansible.builtin.file:
    path: "{{ target_home }}/.cache/gatherd/nowayprompt"
    state: absent
```

- [ ] **Step 4: Rewire rest.yml and delete the old file**

In `roles/system/tasks/rest.yml`, replace

```yaml
- name: Build and install the credential prompt
  ansible.builtin.include_tasks: nowayprompt.yml

- name: Set up the AUR builder and the local repository it builds into
  ansible.builtin.include_tasks: aurutils.yml
```

with

```yaml
- name: Set up the AUR builder and the local repository it builds into
  ansible.builtin.include_tasks: aurutils.yml

# After aurutils.yml, which creates both aur and the repo this builds into.
- name: Build and install the vendored packages, the credential prompt among them
  ansible.builtin.include_tasks: vendored.yml
```

```bash
git rm roles/system/tasks/nowayprompt.yml
grep -rn 'nowayprompt\.yml' --include='*.yml' --include='*.j2' roles site-*.yml   # expect nothing
```

- [ ] **Step 5: Record the migration**

```bash
scripts/gatherd-check-migrations; echo rc=$?    # expect rc=1 naming the new removal task
```

Add to `MIGRATIONS.md`, under `## Unmeasured`, in the shape of its neighbours
(match the file and task name exactly as `gatherd-check-migrations` printed
them):

```
- roles/system/tasks/vendored.yml:NN — Remove the build directory nowayprompt.yml used
  shape: state: absent
  thing: the makepkg scratch directory of the retired roles/system/tasks/nowayprompt.yml
  check: test -e "$TARGET_HOME/.cache/gatherd/nowayprompt"
  fresh-install expectation: absent (pure migration)
```

(`NN` is the task's line; the check matches on file and name, not line.)

```bash
scripts/gatherd-check-migrations; echo rc=$?    # rc=0
```

- [ ] **Step 6: Retire nowayprompt's exceptions in the other gates**

In `scripts/gatherd-check-package-tiers`' `ALLOWED`, delete the
`'nowayprompt': ...` entry and the
`'{{ _nowayprompt_built.files[0].path }}': ...` entry. In the comment above the
remaining `'{{ _aurutils_built.files[0].path }}'` entry, change
`see packaging/nowayprompt/PKGBUILD` to `see packaging/aurutils/PKGBUILD`.

In `scripts/gatherd-assert-packages-declared`, the comment above `VENDORED`
reads `(roles/system/tasks/aurutils.yml,\n# nowayprompt.yml)`; make it
`(roles/system/tasks/aurutils.yml)`.

- [ ] **Step 7: Verify**

```bash
scripts/gatherd-check-aur-deps . ; echo rc=$?          # rc=0, and the summary counts nowayprompt
scripts/gatherd-check-package-tiers . ; echo rc=$?     # rc=0
scripts/gatherd-assert-packages-declared . ; echo rc=$? # rc=0
ansible-lint --profile production roles/system/tasks/vendored.yml roles/system/tasks/rest.yml group_vars/all/main.yml
tests/gates 2>&1 | grep -E '^FAIL|passed'               # only tests/assert-aur-deps fails
```

If `check-aur-deps` names a nowayprompt dependency, that is a real finding:
declare it in `rest_packages`, never in its `ALLOWED`.

- [ ] **Step 8: Commit**

```bash
git add group_vars/all/main.yml packaging/nowayprompt/.SRCINFO packaging/nowayprompt/PKGBUILD \
    roles/system/tasks/vendored.yml roles/system/tasks/rest.yml MIGRATIONS.md \
    scripts/gatherd-check-package-tiers scripts/gatherd-assert-packages-declared
git commit -m "Build nowayprompt into the local repository like an AUR package

Claude-Session: https://claude.ai/code/session_01UeT4HEYuzFyvcagw5P7Hhn"
```

---

## Task 3: Build the TI calculator libraries

**Files:**
- Modify: `group_vars/all/main.yml`
- Create: `roles/aur/tasks/ti84.yml`
- Modify: `roles/aur/tasks/slow.yml` (end of the block, before `  always:`)

**Interfaces:**
- Produces: `libticonv libticables libtifiles libticalcs` installed before anything after the include in the slow AUR tier; `python-colorama` installed in system REST.

- [ ] **Step 1: Add the vars**

In `group_vars/all/main.yml`, in `rest_packages`, after the `rate-mirrors`
entry:

```yaml
  # 8xvtopy's only import outside the standard library. Declared here, not
  # left to its PKGBUILD, because makepkg checks depends before building and
  # cannot install them (PACMAN_AUTH=/bin/false).
  - python-colorama        # 8xvtopy
```

After `vendored_packages` (Task 2), add:

```yaml
# The TI calculator link libraries, for titools (packaging/titools). Three
# lists because they are three rounds: aur sync installs nothing between the
# packages of one batch, and libticalcs needs libtifiles, which needs
# libticonv. roles/aur/tasks/ti84.yml builds and installs each before the next.
aur_ti_base_packages:
  - libticonv
  - libticables
aur_ti_files_packages:
  - libtifiles
aur_ti_calcs_packages:
  - libticalcs
```

- [ ] **Step 2: Write roles/aur/tasks/ti84.yml**

```yaml
---
# The TI calculator link libraries, which titools links against. Built in
# rounds, the way the fingerprint driver is in slow.yml: aur sync passes
# --no-sync, so nothing is installed between the packages of one batch, and
# makepkg cannot install a missing dependency itself.
#
# USB access needs nothing here: libticables ships 69-libticables.rules, which
# marks TI's vendor 0451 ID_PDA, and systemd's 70-uaccess.rules grants uaccess
# to ID_PDA devices.

- name: Check the build dependencies of the base TI libraries
  ansible.builtin.include_tasks: tasks/assert_aur_deps.yml
  vars:
    aur_assert_targets: "{{ aur_ti_base_packages }}"

- name: Build the base TI libraries
  ansible.builtin.command: "{{ aur_sync_command }} {{ aur_ti_base_packages | join(' ') }}"
  environment: "{{ aur_build_environment }}"
  register: _aur_sync_ti_base
  changed_when: "'there is nothing to do' not in _aur_sync_ti_base.stderr"

- name: Install the base TI libraries
  community.general.pacman:
    name: "{{ aur_ti_base_packages }}"
    state: present
    update_cache: "{{ _aur_sync_ti_base.changed }}"
  become: true
  become_user: root

- name: Check the build dependencies of the TI file library
  ansible.builtin.include_tasks: tasks/assert_aur_deps.yml
  vars:
    aur_assert_targets: "{{ aur_ti_files_packages }}"

- name: Build the TI file library
  ansible.builtin.command: "{{ aur_sync_command }} {{ aur_ti_files_packages | join(' ') }}"
  environment: "{{ aur_build_environment }}"
  register: _aur_sync_ti_files
  changed_when: "'there is nothing to do' not in _aur_sync_ti_files.stderr"

- name: Install the TI file library
  community.general.pacman:
    name: "{{ aur_ti_files_packages }}"
    state: present
    update_cache: "{{ _aur_sync_ti_files.changed }}"
  become: true
  become_user: root

- name: Check the build dependencies of the TI calculator library
  ansible.builtin.include_tasks: tasks/assert_aur_deps.yml
  vars:
    aur_assert_targets: "{{ aur_ti_calcs_packages }}"

- name: Build the TI calculator library
  ansible.builtin.command: "{{ aur_sync_command }} {{ aur_ti_calcs_packages | join(' ') }}"
  environment: "{{ aur_build_environment }}"
  register: _aur_sync_ti_calcs
  changed_when: "'there is nothing to do' not in _aur_sync_ti_calcs.stderr"

- name: Install the TI calculator library
  community.general.pacman:
    name: "{{ aur_ti_calcs_packages }}"
    state: present
    update_cache: "{{ _aur_sync_ti_calcs.changed }}"
  become: true
  become_user: root
```

- [ ] **Step 3: Include it in the slow AUR tier**

In `roles/aur/tasks/slow.yml`, after the `Wait for piavpn IPC to be ready`
task (its last line is `      changed_when: false`) and before `  always:`,
add (indented to match the block's tasks):

```yaml

    - name: Build and install the TI calculator libraries
      ansible.builtin.include_tasks: ti84.yml
```

- [ ] **Step 4: Prove the rounds are needed, then verify**

The gate must reject the one-batch shortcut. Temporarily move `libtifiles`
from `aur_ti_files_packages` into `aur_ti_base_packages`, then:

```bash
scripts/gatherd-check-aur-deps . ; echo rc=$?   # rc=1, naming "libtifiles needs libticonv"
```

Undo that edit by hand (`git checkout -p` is interactive and unavailable here;
`git diff group_vars/all/main.yml` must show only Step 1's additions), then:

```bash
scripts/gatherd-check-aur-deps . ; echo rc=$?          # rc=0
scripts/gatherd-check-package-tiers . ; echo rc=$?     # rc=0
scripts/gatherd-assert-packages-declared . ; echo rc=$? # rc=0: none of these is installed yet
ansible-lint --profile production roles/aur/tasks/ti84.yml roles/aur/tasks/slow.yml group_vars/all/main.yml
tests/gates 2>&1 | grep -E '^FAIL|passed'
```

- [ ] **Step 5: Commit**

```bash
git add group_vars/all/main.yml roles/aur/tasks/ti84.yml roles/aur/tasks/slow.yml
git commit -m "Build the TI calculator link libraries in the slow AUR tier

Claude-Session: https://claude.ai/code/session_01UeT4HEYuzFyvcagw5P7Hhn"
```

---

## Task 4: Vendor titools, ti-tools and 8xvtopy

**Files:**
- Create: `packaging/titools/PKGBUILD`, `packaging/titools/.SRCINFO`
- Create: `packaging/ti-tools/PKGBUILD`, `packaging/ti-tools/.SRCINFO`
- Create: `packaging/8xvtopy/PKGBUILD`, `packaging/8xvtopy/.SRCINFO`
- Modify: `group_vars/all/main.yml`
- Modify: `roles/aur/tasks/slow.yml`
- Modify: `tests/assert-packages-declared`

**Interfaces:**
- Consumes: Task 1 (gate), Task 2 (`aur_build_command`, the copy/build/install pattern), Task 3 (libticalcs installed earlier in the same tier).
- Produces: `/usr/bin/tiget` (and seven other `ti*`), `/usr/bin/ti-tools`, `/usr/bin/8xvtopy`.

- [ ] **Step 1: Write the three PKGBUILDs**

`packaging/titools/PKGBUILD`:

```bash
# Maintainer: gatherd (vendored, not yet submitted to the AUR)
#
# TITools: command-line link tools for TI calculators, on libticalcs. Not in
# the AUR or any repo (AUR RPC search, 2026-10-04). backup-taavi-ti84's
# ti84-fetch-all runs tiget.
pkgname=titools
pkgver=0.2+cc7dc08
pkgrel=1
pkgdesc="Command-line tools for TI graphing calculators (tiget, tiput, tils, ...)"
arch=('x86_64')
url="https://github.com/Jonimoose/TITools"
license=('GPL-3.0-or-later')
depends=('libticalcs' 'libticables' 'libtifiles' 'libticonv' 'glib2')
# Upstream's last commit (2016); v0.2 is the tag before it. pkgver carries the
# short sha so a bump rebuilds -- aur build skips a version it already has.
_commit=cc7dc08d831beaf6c4f865c3acd49a2be58df5a9
source=("$pkgname-$_commit.tar.gz::https://github.com/Jonimoose/TITools/archive/$_commit.tar.gz")
sha256sums=('f51b27689b43e32a0181876a4904740b989b9e484c723ddd4219993407554d71')

build() {
    cd "TITools-$_commit"
    # The shipped configure, not autoreconf: measured building against the
    # tilp2 1.18 libraries on 2026-10-04.
    ./configure --prefix=/usr
    make
}

package() {
    cd "TITools-$_commit"
    make DESTDIR="$pkgdir" install
}
```

Before committing that license string, read `COPYING` and the source headers:
the file is GPL v3 text, but a header saying "version 2 or later" would make it
`GPL-2.0-or-later`. Use what the headers say.

`packaging/ti-tools/PKGBUILD`:

```bash
# Maintainer: gatherd (vendored, not yet submitted to the AUR)
#
# ti-tools: converts TI calculator files (8xp programs) to text. Not in the
# AUR (an unrelated eti-tools-git is the only name match, 2026-10-04).
# backup-taavi-ti84's ti84-convert-to-text runs `ti-tools convert`.
pkgname=ti-tools
pkgver=0.2.0+654a8e2
pkgrel=1
pkgdesc="Tools for TI calculator files: convert programs to and from text"
arch=('x86_64')
url="https://github.com/cqb13/ti-tools"
license=('MIT')
depends=('gcc-libs' 'glibc')
makedepends=('cargo')
_commit=654a8e28e79d7de62bb333c8f5656a93f90ba017
source=("$pkgname-$_commit.tar.gz::https://github.com/cqb13/ti-tools/archive/$_commit.tar.gz")
sha256sums=('d8f58931ea55fd2a0af1a3cd1a375b3e4a3e7d4d22179f58f7ddd73e52e36b66')

build() {
    cd "ti-tools-$_commit"
    cargo build --release --locked
}

package() {
    cd "ti-tools-$_commit"
    install -Dm755 target/release/ti-tools "$pkgdir/usr/bin/ti-tools"
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
```

Check `depends` against what the binary links: after the Step 3 build,
`readelf -d target/release/ti-tools | grep NEEDED` inside the build directory.
Every `lib*.so` it names must come from a package in `depends`; fix the list
to match, then regenerate `.SRCINFO`.

`packaging/8xvtopy/PKGBUILD`:

```bash
# Maintainer: gatherd (vendored, not submitted to the AUR)
#
# 8xvtopy: extracts the Python source from a TI-83 Premium CE / TI-84 Python
# AppVar (.8xv). Not in the AUR. backup-taavi-ti84's ti84-convert-to-text
# runs it.
#
# Upstream has no license file, which is why this is not in the AUR: settle
# that with upstream before publishing it.
pkgname=8xvtopy
pkgver=r10.0b74547
pkgrel=1
pkgdesc="Convert TI calculator Python AppVars (.8xv) to .py files"
arch=('any')
url="https://github.com/Guillaume-favier/8xvtopy"
license=('LicenseRef-unknown')
depends=('python' 'python-colorama')
_commit=0b745472e2eb293881fcf5d787a64f1e62dc8711
source=("$pkgname-$_commit.tar.gz::https://github.com/Guillaume-favier/8xvtopy/archive/$_commit.tar.gz")
sha256sums=('e5122c91d4f973324cb9c1e4c3df036468041b07ea461a67d9386be2e47ed720')

package() {
    cd "8xvtopy-$_commit"
    install -Dm644 8xvtopy.py "$pkgdir/usr/share/8xvtopy/8xvtopy.py"
    install -dm755 "$pkgdir/usr/bin"
    printf '#!/bin/sh\nexec python3 /usr/share/8xvtopy/8xvtopy.py "$@"\n' \
        > "$pkgdir/usr/bin/8xvtopy"
    chmod 755 "$pkgdir/usr/bin/8xvtopy"
}
```

- [ ] **Step 2: Generate the .SRCINFOs and fetch-check the sources**

```bash
for p in titools ti-tools 8xvtopy; do
    (cd packaging/$p && makepkg --printsrcinfo > .SRCINFO && makepkg -od --noconfirm) || echo "FAILED $p"
done
git status --short packaging/    # only PKGBUILD and .SRCINFO per package; build output is gitignored
```

Expected: no `FAILED`, and each `makepkg -od` ends `Sources are ready.` after
`Validating source files with sha256sums... Passed`.

- [ ] **Step 3: Build what this machine can build now**

`ti-tools` needs only cargo; `8xvtopy` needs python-colorama, which is not
installed yet, so build it with `-d` (skip dependency checks — packaging only):

```bash
(cd packaging/ti-tools && makepkg -f --noconfirm && readelf -d src/ti-tools-*/target/release/ti-tools | grep NEEDED)
(cd packaging/8xvtopy && makepkg -fd --noconfirm && bsdtar -tf 8xvtopy-*.pkg.tar.zst | grep -v '^\.')
```

Expected: `usr/bin/8xvtopy` and `usr/share/8xvtopy/8xvtopy.py` listed. titools
needs libticalcs, which only the converge installs; it is built for real in
Task 5's converge.

- [ ] **Step 4: Declare and build them in the slow tier**

In `group_vars/all/main.yml`, after `vendored_packages`, add:

```yaml
# Same, built in the slow AUR tier after the TI libraries they link against
# (roles/aur/tasks/ti84.yml). For backup-taavi-ti84's scripts.
vendored_slow_packages:
  - titools
  - ti-tools
  - 8xvtopy
```

In `roles/aur/tasks/slow.yml`, immediately after the `Build and install the TI
calculator libraries` include from Task 3, add (same indentation):

```yaml

    # Same three steps as roles/system/tasks/vendored.yml, for the slow list.
    # Not a shared task file: gatherd-check-aur-deps visits each file once, so
    # one included from two places would be checked only at the first.
    - name: Copy the slow vendored PKGBUILDs to their build directories
      ansible.builtin.copy:
        src: "{{ setup_dir }}/packaging/{{ item }}/"
        dest: "{{ target_home }}/.cache/gatherd/vendored/{{ item }}/"
        remote_src: true
        owner: "{{ target_user }}"
        mode: preserve
      loop: "{{ vendored_slow_packages }}"
      become: true
      become_user: root

    - name: Build slow vendored packages into the local repository
      ansible.builtin.command: "{{ aur_build_command }}"
      args:
        chdir: "{{ target_home }}/.cache/gatherd/vendored/{{ item }}"
      loop: "{{ vendored_slow_packages }}"
      environment: "{{ aur_build_environment }}"
      register: _vendored_slow_build
      changed_when: "'skipping existing package' not in _vendored_slow_build.stderr"

    - name: Install slow vendored packages
      community.general.pacman:
        name: "{{ vendored_slow_packages }}"
        state: present
        update_cache: "{{ _vendored_slow_build.changed }}"
      become: true
      become_user: root
```

(The aur role runs as `target_user` already — see the build tasks above it —
so the build needs no `become_user`; the copy and install need root.)

- [ ] **Step 5: Pin the stray gate's reading of the new list**

In `tests/assert-packages-declared`, before the `# --- Case 10:` block, add:

```sh
# --- Case 9g: a package declared only in a vendored list -> exit 0 -----------
sandbox "$WORK/repo"
printf 'vendored_slow_packages:\n  - vendored-pkg\n' >> "$WORK/repo/group_vars/all/main.yml"
cat >> "$WORK/repo/roles/system/tasks/rest.yml" <<'T'
- name: Install slow vendored packages
  community.general.pacman:
    name: "{{ vendored_slow_packages }}"
    state: present
T
printf 'declared-pkg\nvendored-pkg\n' > "$WORK/db/explicit"
rc=$(run_check "$WORK/repo" || true)
if [ "$rc" = 0 ]; then
    ok 'a vendored list declares its packages'
else
    bad "a vendored list should declare its packages (got $rc)"; sed 's/^/       /' "$WORK/err"
fi
printf 'declared-pkg\n' > "$WORK/db/explicit"
```

- [ ] **Step 6: Verify**

```bash
tests/assert-packages-declared | tail -1                # all pass
scripts/gatherd-check-aur-deps . ; echo rc=$?            # rc=0; titools' libticalcs is satisfied by ti84.yml
scripts/gatherd-check-package-tiers . ; echo rc=$?
ansible-lint --profile production roles/aur/tasks/slow.yml group_vars/all/main.yml
tests/gates 2>&1 | grep -E '^FAIL|passed'
```

Then prove the ordering is load-bearing: move the `Build and install the TI
calculator libraries` include to AFTER the three vendored tasks, run
`scripts/gatherd-check-aur-deps .` — expect rc=1 with `titools needs libticalcs`
— and move it back.

- [ ] **Step 7: Commit**

```bash
git add packaging/titools packaging/ti-tools packaging/8xvtopy group_vars/all/main.yml \
    roles/aur/tasks/slow.yml tests/assert-packages-declared
git status --short packaging/   # nothing left untracked except gitignored build output
git commit -m "Vendor the TI-84 backup tools: titools, ti-tools, 8xvtopy

Claude-Session: https://claude.ai/code/session_01UeT4HEYuzFyvcagw5P7Hhn"
```

---

## Task 5: Verify on this machine, and hand off

**Files:**
- Modify: `scripts/gatherd-post-setup-notes` (`section_verify`)

- [ ] **Step 1: Add the verify step**

In `section_verify`, after the last `verify_li` line, add:

```sh
    verify_li 'TI-84 backup tools are installed and talk to the calculator: `tiget --help` runs, and with the calculator plugged in, `ti84-fetch-all` in backup-taavi-ti84 fetches without sudo.'
```

Stage only this hunk (Global Constraints). Commit:

```bash
git commit -m "Add the verify step for the vendored TI-84 tools

Claude-Session: https://claude.ai/code/session_01UeT4HEYuzFyvcagw5P7Hhn"
```

- [ ] **Step 2: Converge (the human runs these; pushing needs their 1Password SSH agent)**

```bash
git push origin main
sudo git -C /usr/local/lib/gatherd pull
sudo rm -f /etc/gatherd/async-complete && sudo systemctl start gatherd-async.service
journalctl -u gatherd-async.service -f     # until it ends
```

- [ ] **Step 3: Check the result**

```bash
pacman -Q nowayprompt titools ti-tools 8xvtopy libticalcs python-colorama
pacman -Si nowayprompt | grep Repository        # gatherd-aur
command -v tiget ti-tools 8xvtopy
tiget --help | head -3
/usr/local/lib/gatherd/scripts/gatherd-assert-packages-declared; echo rc=$?   # 0
test -e ~/.cache/gatherd/nowayprompt && echo STILL THERE || echo removed
```

Then converge once more and confirm the vendored build tasks report `ok`, not
`changed` (`aur build` skipped existing versions).

- [ ] **Step 4: Hand off the 8xvtopy path**

`ti84-convert-to-text` runs `python3 ../8xvtopy/8xvtopy.py` from inside
`data/`, which resolves to a directory that does not exist. Tell the
backup-taavi-ti84 session (SendMessage) that `8xvtopy` is now on `PATH` and the
line should become `8xvtopy "$f"`. That repo is its to change, not this plan's.

- [ ] **Step 5: Retire the verify step's backlog line in TODO.md, if any**

```bash
grep -n -i 'ti84\|ti-84\|vendored\|nowayprompt' plans/TODO.md
```

Delete any item this work completes; commit with the verify step if so.
