# Vendored Builds into the Local Repository — Design

**Type:** New mechanism, plus its first four users. Builds every vendored
PKGBUILD into `[gatherd-aur]` with `aur build`, the way `aur sync` builds AUR
packages, and installs them by name.

**Date:** 2026-10-04
**Status:** Approved in conversation. Not yet implemented.
**Related:** `specs/2026-09-15-fleet-package-repo-design.md` (one builder for AUR
and vendored packages; this moves vendored builds into the same repo it would
serve), `specs/2026-10-04-undeclared-packages-design.md` (the stray gate, which
reads whatever this declares).

---

## 1. Problem

Two needs, one mechanism.

**The TI-84 backup scripts have no dependencies on this machine.**
`backup-taavi-ti84/bin/ti84-fetch-all` runs `tiget`;
`ti84-convert-to-text` runs `ti-tools` and `8xvtopy`. None is installed, and
none is packaged anywhere (AUR RPC search, 2026-10-04: `tiget`, `titools`,
`8xvtopy` have no results; `ti-tools` matches only an unrelated
`eti-tools-git`). What they need beneath that is packaged:

| Need | Source | Measured |
|---|---|---|
| `python-colorama` | `[extra]` | 8xvtopy's only non-stdlib import |
| `libticonv`, `libtifiles`, `libticables`, `libticalcs` | AUR, 1.1.5 / 1.1.7 / 1.3.5 / 1.1.9 | each AUR PKGBUILD runs `autoreconf -fi` then `./configure` |
| `tiget` | github.com/Jonimoose/TITools, v0.2, `cc7dc08` (2016) | GPL; autotools; `PKG_CHECK_MODULES` on ticalcs2, ticables2, tifiles2, ticonv |
| `ti-tools` | github.com/cqb13/ti-tools, crate 0.2.0 | Rust, `Cargo.lock` committed |
| `8xvtopy` | github.com/Guillaume-favier/8xvtopy, `0b74547` | one Python script; **no license file** |

**Vendoring today costs 100 lines per package.** `roles/system/tasks/nowayprompt.yml`
reads pkgver and pkgrel out of the PKGBUILD, compares them against
`pacman -Q`, copies the PKGBUILD to a scratch directory, runs makepkg, clears
stale artifacts, asserts exactly one was produced, and installs it by file
path. Three more copies would be 300 lines of the same thing. And none of them
is visible to `gatherd-check-aur-deps`, which reads only `aur sync` lines, so
their build dependencies are declared by hand — the shape CLAUDE.md records
failing three times.

## 2. Feasibility, measured

Built 2026-10-04 in the scratchpad against a private prefix, nothing installed
system-wide:

- All four `libti*` libraries: `autoreconf -fi && ./configure && make && make
  install` succeed with the current toolchain.
- TITools: `./configure && make` succeeds against them and produces `tidump
  tiget tiinfo tikey tils tiput tirm tiscr`. `tiget --help` runs.
- ti-tools: `cargo build --release --locked` succeeds in 15s.
- 8xvtopy: run on a copy of `data/BDAY.8Xv`, its output matches the committed
  `data/BDAY.py` except for trailing whitespace on one line.

USB access needs nothing from gatherd. `libticables`' AUR package installs
`69-libticables.rules`, which sets `ENV{ID_PDA}="1"` on TI's USB vendor
`0451`; systemd's `/usr/lib/udev/rules.d/70-uaccess.rules:55` is
`ENV{ID_PDA}=="?*", TAG+="uaccess"`, so the seat user gets the device. Measured
from the rule files, not with a calculator attached.

Not measurable: `ti-tools convert`. No `.8xp` file exists anywhere in
backup-taavi-ti84's history (`git log --all --diff-filter=A -- 'data/*.8xp'
'data/*.8Xp'` is empty).

## 3. Design

### 3.1 `aur build`, not makepkg

`aur build` from a directory holding a PKGBUILD builds it and adds the result to
the named repo. It skips the build when the package files for the PKGBUILD's
version already exist in the repo directory
(`/usr/lib/aurutils/aur-build:371-389`, aurutils 20.5.8: "skipping existing
package (use -f to overwrite)"). That is the version comparison
`nowayprompt.yml` hand-rolls, for free. **Read in the source, not yet run:** the
plan's first task measures it, building one package twice.

A new `aur_build_command` var in `group_vars/all/main.yml`, beside
`aur_sync_command`, carries the flags, each checked against aurutils 20.5.8 the
way `aur_sync_command`'s are: `--database {{ aur_repo_name }}`, `--no-sync`
(build without installing; the install is a separate pacman task, as with
`aur sync`), and makepkg's `--noconfirm` and `--skippgpcheck`. The exact
spelling of each is measured in the plan; aur-build(1) lists `-d`,
`--no-sync`, `-n` and `--margs`, and man pages here have been wrong before. It runs with
`aur_build_environment`, so makepkg still cannot reach for root.

### 3.2 Two lists, one task file

```yaml
vendored_packages:          # built in system REST, after aurutils.yml
  - nowayprompt
vendored_slow_packages:     # built in the slow AUR tier
  - tiget
  - ti-tools
  - 8xvtopy
```

Named to match `aur_packages` / `aur_slow_packages`, which is also what
`gatherd-check-package-tiers`' `TIER_VAR` (`\w*_packages`) already classifies.

`tasks/vendored_build.yml` (location chosen in the plan) takes a list and, for
each package:

1. copies `{{ setup_dir }}/packaging/<pkg>/` to
   `{{ target_home }}/.cache/gatherd/vendored/<pkg>/`, owned by `target_user`
   — never builds in the root-owned checkout, the reason
   `packaging/.gitignore` already gives;
2. runs `aur_build_command` there as `target_user`.

Then one task installs the whole list by name:
`community.general.pacman: name: "{{ vendored_packages }}"`, refreshing the
`[gatherd-aur]` database the way the AUR installs do.

### 3.3 Placement

- `python-colorama` → `rest_packages`. makepkg checks `depends`, not only
  `makedepends`, before building, and cannot install either (measured, §4.1.4).
- `libticonv libtifiles libticables libticalcs` → `aur_slow_packages`. The
  existing guard, build and install cover them unchanged.
- `vendored_slow_packages` → built in `roles/aur/tasks/slow.yml` after the slow
  AUR install, so `tiget`'s `libticalcs` is installed when it builds.
- `vendored_packages` (nowayprompt) → `roles/system/tasks/rest.yml`,
  immediately after `aurutils.yml`, which creates both `aur` and the
  `[gatherd-aur]` database. Today nowayprompt builds just before it
  (`rest.yml:38-42`).

**Trade-off accepted:** an `aurutils.yml` failure now also prevents
nowayprompt's build. Both are in the same tier block already, so a failure in
either skips everything after it; only the order changes.

### 3.4 The packages

Each `packaging/<pkg>/` holds a PKGBUILD pinned to a commit and a committed
`.SRCINFO`, both to AUR standard, so that publishing one later is: copy the
directory to an AUR git repo, move the name from `vendored_*_packages` to
`aur_slow_packages`, delete the directory.

- **tiget** (pkgname `titools`, provides the eight `ti*` binaries): `depends=(libticalcs
  glib2)`, `makedepends=(autoconf automake)`, `autoreconf -fi` in `prepare()`.
  The pkgname is chosen in the plan; it must be the name `vendored_slow_packages`
  lists.
- **ti-tools**: `makedepends=(cargo)`, `cargo build --frozen --release`, with
  `cargo fetch --locked` in `prepare()` per the Arch Rust package guidelines.
- **8xvtopy**: `depends=(python python-colorama)`, installs the script under
  `/usr/share/8xvtopy/` and a `/usr/bin/8xvtopy` wrapper.
  `license=('LicenseRef-unknown')`: upstream has no license file. Fine for
  personal use; it must be settled with upstream before publishing.

### 3.5 Migrating nowayprompt

- `roles/system/tasks/nowayprompt.yml` is deleted; `rest.yml` includes the
  shared task file instead.
- On a converged machine the installed nowayprompt already satisfies the
  install by name, so nothing reinstalls. Its first `aur build` adds the same
  version to `[gatherd-aur]`, from which `arch-update` can then upgrade it.
- A removal task deletes the stale `~/.cache/gatherd/nowayprompt` scratch
  directory, with a `MIGRATIONS.md` entry (`gatherd-check-migrations` enforces
  the pairing).
- `gatherd-check-package-tiers`' `ALLOWED` loses `nowayprompt` and
  `{{ _nowayprompt_built.files[0].path }}`.
- `gatherd-assert-packages-declared` needs no change: it reads
  `{{ vendored_packages }}` as a bare var. Its `VENDORED` rule stays for
  aurutils, which still installs by path.

`aurutils` is out of scope and stays as it is: it is what `aur build` is.

## 4. The dependency gates

### 4.1 `gatherd-check-aur-deps` learns vendored builds

1. **Finding them.** A command containing `aur_build_command` is a build. Its
   targets come from the task's `loop:` (resolved with the existing
   `names_from`); a loop it cannot resolve is an `unreadable` event, a hard
   failure, as an unparseable `aur sync` is today. `unreachable()` also flags a
   file containing `aur_build_command` that no playbook reaches.
2. **Their dependencies.** Read from `packaging/<pkg>/.SRCINFO` with the
   existing `srcinfo(text, arch)` parser, offline, instead of fetched from the
   AUR. Then checked by the existing rule, unchanged: declared by an earlier
   pacman task, in the base manifest, or built and installed earlier. Same
   batch semantics: `--no-sync` means a vendored build cannot satisfy its
   neighbour in the same loop.
3. **A stale `.SRCINFO` fails.** A missing `.SRCINFO`, or one that differs from
   `makepkg --printsrcinfo` for its PKGBUILD, is exit 1. Without this, editing a
   PKGBUILD's `depends` leaves the gate checking the old ones.
4. **No guard pairing for vendored builds**, exempted in code with the reason.
   The preflight guard exists because `aur sync` builds a chain and a missing
   dependency used to surface fourteen minutes in. `aur build` here runs one
   makepkg per package, and makepkg checks dependencies before fetching
   sources. Measured 2026-10-04 with a probe PKGBUILD whose only source is
   `https://example.invalid/...`, run as `PACMAN_AUTH=/bin/false makepkg
   --noconfirm`: with `depends=(no-such-runtime-dep)` and again with
   `makedepends=(no-such-build-dep)`, rc=8, `==> Missing dependencies: ->
   <name>`, `==> ERROR: Could not resolve all dependencies.`, and no
   `Retrieving` line. The guard's failure mode is already the build's.

### 4.2 `gatherd-assert-aur-deps`

Unchanged, by §4.1.4.

### 4.3 `gatherd-check-package-tiers`

`{{ vendored_packages }}` and `{{ vendored_slow_packages }}` already match
`TIER_VAR`. Only the two nowayprompt `ALLOWED` entries go (§3.5).

The fleet package repo (`specs/2026-09-15-...`) will read `*_packages` vars to
decide what to fetch. A vendored name is not fetchable from any mirror; that
design already plans to build vendored packages itself, so it must treat
`vendored_*` lists as build inputs. Recorded here so it is not discovered then.

## 5. Testing

**Before committing** (`tests/gates`, green apart from the pre-existing
`tests/assert-aur-deps` failure):

- `tests/check-aur-deps`: a vendored `.SRCINFO` dependency nothing declares
  fails; one an earlier task installs passes; a stale `.SRCINFO` fails; a
  missing one fails; an unresolvable `loop:` fails; an `aur_build_command` file
  no playbook reaches fails; a vendored build with no guard passes.
- `tests/check-package-tiers`: the nowayprompt entries are gone and the tree is
  still clean.
- `tests/assert-packages-declared`: a package declared only in
  `vendored_slow_packages` is accounted for.
- `ansible-lint` clean at the `production` profile.

**On this machine, after a converge:**

```
pacman -Q nowayprompt titools ti-tools 8xvtopy libticalcs   # all resolve
pacman -Si nowayprompt | grep Repository                    # gatherd-aur
scripts/gatherd-assert-packages-declared; echo $?           # 0
```

and a second converge reports the vendored build tasks unchanged, because
`aur build` skipped existing versions.

**One `verify_li` step:** `tiget --help` runs, and with the calculator plugged
in, `ti84-fetch-all` fetches without sudo — which exercises the uaccess chain
§2 could only read.

## 6. Out of scope

- **`ti84-convert-to-text` runs `python3 ../8xvtopy/8xvtopy.py` from inside
  `data/`**, which resolves to `backup-taavi-ti84/8xvtopy` and does not exist. It
  should call `8xvtopy`. That is a one-line change in backup-taavi-ti84, for
  that repo's session once this lands.
- Publishing any of the three to the AUR.
- Moving `aurutils` to this mechanism.
- A runtime preflight for vendored builds (§4.1.4).
