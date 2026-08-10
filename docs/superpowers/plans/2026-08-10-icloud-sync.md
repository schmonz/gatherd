# iCloud Drive Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-rolled `~/.local/bin/fsnotes-sync` and the manual `rclone config` post-setup nag with a gatherd-managed, fleet-wide iCloud Drive sync that needs one interactive setup per fleet rather than one per machine.

**Architecture:** A new `icloud` role installs four small POSIX-sh scripts and a rendered folder manifest. `gatherd-icloud-config` owns 1Password and the encrypted `rclone.conf`; `gatherd-icloud-sync` owns rclone bisync; `gatherd-prompt-icloud` is a session-cohort readiness waiter that calls both; `gatherd-icloud-password` is a one-word target for `RCLONE_PASSWORD_COMMAND`. Triggers (login, gtklock unlock) call the sync driver, which carries its own `flock` and rate-limit guards.

**Tech Stack:** POSIX `sh`, `rclone` 1.75 (`bisync`, config encryption), 1Password CLI (`op`), Ansible (FQCN modules), `pam_env`, gtklock, `flock` (util-linux).

**Spec:** `docs/superpowers/specs/2026-08-10-icloud-sync-design.md`

## Global Constraints

- **Spec deviation, deliberate:** spec §4 places the `icloud` role in `site-async.yml`. This plan places it in **`site-core.yml`** instead, as `roles/icloud/tasks/core.yml`. Rationale: every converge-time action is file installation and directory creation — no packages, no network, no downloads — so it is CORE-legal by the rule in `CLAUDE.md`. Putting it in REST would mean the scripts do not exist during the *first* login of a fresh machine, so iCloud would not start until the second login, which defeats the unattended-repave goal the spec is written to serve. There is deliberately no `tasks/rest.yml`: nothing this role does at converge time touches the network.
- **All Ansible modules use FQCN** — `ansible.builtin.*`, `community.general.*`. Never bare names.
- **Task names read like imperative sentences** — "Install the iCloud sync driver", not "icloud script task".
- **Run `ansible-lint` before every commit** that touches YAML. `noqa` is a last resort.
- **Comments explain *why*, never *what*.** The task name already says what.
- **Scripts are POSIX `sh`**, not bash, and live in `scripts/` without an extension.
- **Session env vars go in `pam_env`**, never `environment.d` — greetd launches sway with no login shell.
- Remote name is `icloud`. 1Password vault is `Private`. Password item is `rclone config`, field `password`. Document item is `rclone.conf`.
- Local root is `~/Documents/iCloud/<Folder>`. Only `FSNotes` is declared initially.
- Every script accepts environment overrides for its paths and for the `op`/`rclone` binaries so `tests/icloud` can drive it with fakes. This is the only reason those overrides exist; do not add configuration knobs beyond them.

## Testing Approach

This repo has no unit-test framework — `tests/test` is a full QEMU idempotency run, and `CLAUDE.md` designates `scripts/gatherd-post-setup-notes` as the living test suite. That is right for Ansible tasks and wrong for these four scripts: their decision logic (baseline detection, the refuse-on-populated-dir guard, the publish-only-if-verified guard) is exactly the kind of thing that must not be discovered to be wrong on a fresh repave, and none of it needs a real iCloud account to exercise.

So this plan adds **`tests/icloud`**, a single POSIX-sh runner that puts fake `rclone` and `op` executables on `PATH` and asserts script behavior. It is run by hand (`tests/icloud`), takes under a second, and touches no network. Tasks 3–6 are written test-first against it.

Live behavior that fakes cannot cover — real bisync, real 1Password, the shared-token question — is covered by Tasks 1, 8, and 9 and by the `section_verify` items in Task 7.

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `tests/icloud` | Test runner with fake `rclone`/`op`. Only place tests live. |
| `scripts/gatherd-icloud-password` | Emit the config-encryption password. Nothing else. |
| `scripts/gatherd-icloud-sync` | rclone bisync driver: folders, baseline detection, guards, triggers. Knows nothing of 1Password. |
| `scripts/gatherd-icloud-config` | 1Password ↔ local `rclone.conf`: `bootstrap`, `pull`, `push`, `status`. Knows nothing of folders or bisync. |
| `scripts/gatherd-prompt-icloud` | Session-cohort readiness waiter. Calls the two above. No logic of its own. |
| `roles/icloud/tasks/core.yml` | Install scripts, render manifest and filters, create directories. |
| `roles/icloud/templates/icloud.conf.j2` | Runtime folder manifest read by the scripts. |
| `roles/icloud/templates/folder.filter.j2` | Per-folder rclone filter file. |
| `tests/icloud-shadow` | Shadow-config probe for spec §11.1 (T1–T4). Temporary; deleted in Task 9's follow-up. |

**Modify:**

| Path | Change |
|---|---|
| `group_vars/all/main.yml` | Add `icloud_*` vars. |
| `site-core.yml` | Import `icloud` role, `tasks_from: core`, in the user play. |
| `roles/system/tasks/user_path.yml` | Add `RCLONE_PASSWORD_COMMAND` to `pam_env.conf`. |
| `roles/desktop/templates/gtklock-config.ini.j2` | Add `unlock-command`. |
| `scripts/gatherd-session-helpers` | Add `gatherd-prompt-icloud` to the cohort. |
| `scripts/gatherd-post-setup-notes` | Replace the `rclone config` nag; add re-auth nag; add two `li` verify items. |

---

### Task 1: Answer the shared-token question (spec §11.1, T1–T3)

Do this first. It is the only result that can invalidate D5, it needs no code from later tasks, and it takes an afternoon. Everything downstream is cheap to adapt but pointless to build twice.

**Files:**
- Create: `tests/icloud-shadow`

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/icloud-shadow` — a script taking one argument, `probe` or `log`. Later used by Task 9 for T4.

- [ ] **Step 1: Write the shadow probe**

Create `tests/icloud-shadow`:

```sh
#!/bin/sh
# Shadow-config probe for the shared-session-token question (spec §11.1).
#
# Under D5 every fleet machine holds a byte-identical copy of the encrypted
# rclone.conf — same client_id, same trust token, same cookies. So a second
# config directory driven via RCLONE_CONFIG differs from a second machine only
# in source IP, which `probe --vpn` covers by requiring PIA to be up. Two rclone
# processes then hold the same session independently, each free to refresh and
# rewrite its own copy.
#
# Usage:
#   tests/icloud-shadow probe        T1+T2: copy authenticates, concurrent use
#   tests/icloud-shadow probe --vpn  T3:    same, asserting a different egress IP
#   tests/icloud-shadow log          T4:    one timestamped datapoint, appended
#
# Delete this script once T4 concludes.

set -eu

REAL="${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}"
SHADOW_DIR="${GATHERD_SHADOW_DIR:-$HOME/.local/state/gatherd/icloud-shadow}"
SHADOW="$SHADOW_DIR/rclone.conf"
LOG="$SHADOW_DIR/probe.log"
REMOTE="${GATHERD_ICLOUD_REMOTE:-icloud}"

mkdir -p "$SHADOW_DIR"
chmod 700 "$SHADOW_DIR"

sync_shadow() {
    # Byte copy, deliberately: divergence here would test something other than
    # what a fleet machine actually holds.
    cp -p "$REAL" "$SHADOW"
    chmod 600 "$SHADOW"
}

real_ls()   { rclone lsd "$REMOTE:" >/dev/null 2>&1; }
shadow_ls() { RCLONE_CONFIG="$SHADOW" rclone lsd "$REMOTE:" >/dev/null 2>&1; }

egress_ip() { curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || echo unknown; }

probe() {
    _vpn=${1:-}

    sync_shadow

    printf 'T1 copy authenticates ... '
    if shadow_ls; then echo PASS; else echo FAIL; return 1; fi

    printf 'T1 real still authenticates ... '
    if real_ls; then echo PASS; else echo 'FAIL (shadow use killed the real session)'; return 1; fi

    if [ "$_vpn" = "--vpn" ]; then
        printf 'T3 egress IP ... '
        _ip=$(egress_ip)
        echo "$_ip"
        [ "$_ip" != unknown ] || { echo 'T3 FAIL: could not determine egress IP'; return 1; }
        echo "T3 note: confirm this differs from the non-VPN run's IP"
    fi

    printf 'T2 concurrent use (10 rounds) ... '
    _i=0
    while [ "$_i" -lt 10 ]; do
        real_ls & _r=$!
        shadow_ls & _s=$!
        wait "$_r" || { echo "FAIL: real session died on round $_i"; return 1; }
        wait "$_s" || { echo "FAIL: shadow session died on round $_i"; return 1; }
        _i=$((_i + 1))
    done
    echo PASS

    printf 'T2 configs unchanged by use ... '
    if cmp -s "$REAL" "$SHADOW"; then
        echo 'PASS (neither side rotated)'
    else
        echo 'DIVERGED — a refresh rewrote one side; this is T4 territory, not a failure'
    fi
}

log() {
    _when=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    _real=fail; real_ls   && _real=ok
    _shadow=fail; shadow_ls && _shadow=ok
    _same=differ; cmp -s "$REAL" "$SHADOW" && _same=identical
    printf '%s real=%s shadow=%s configs=%s\n' "$_when" "$_real" "$_shadow" "$_same" >> "$LOG"
}

case "${1:-probe}" in
    probe) shift 2>/dev/null || true; probe "${1:-}" ;;
    log)   log ;;
    *)     echo "usage: $0 [probe [--vpn] | log]" >&2; exit 2 ;;
esac
```

- [ ] **Step 2: Make it executable and run T1/T2**

```bash
chmod +x tests/icloud-shadow
tests/icloud-shadow probe
```

Expected: four `PASS` lines. 1Password must be unlocked first — if you see `authorization timeout`, approve the CLI prompt and re-run.

- [ ] **Step 3: Record the non-VPN egress IP, then run T3**

```bash
curl -fsS https://api.ipify.org; echo
piactl connect && sleep 10 && piactl get connectionstate
tests/icloud-shadow probe --vpn
```

Expected: the same `PASS` lines, and a `T3 egress IP` that differs from the first `curl`. Then `piactl disconnect`.

- [ ] **Step 4: Interpret the result**

Only one outcome blocks the design: **both sessions are forced to re-authenticate with fresh 2FA**. That is a hard trust-token revocation and means D5 fails.

- All PASS → proceed. R1 stays informational.
- `DIVERGED` on the config comparison → **not** a failure. A refresh rewrote one copy; §5.3's pull-and-retest absorbs exactly this. Note it and proceed.
- Hard revocation → **stop and re-plan.** The fallback is spec §10: shared password, per-machine config. `gatherd-icloud-config` is the only component that changes.

- [ ] **Step 5: Commit**

```bash
git add tests/icloud-shadow
git commit -m "Probe whether iCloud tolerates one session token from two clients

Stands in for the two-machine test the spec calls for, which no second
machine is available to run. A byte-identical config copy driven via
RCLONE_CONFIG is what a fleet machine would hold anyway, so it differs
only in egress IP — which --vpn supplies via PIA."
```

---

### Task 2: Declare the folder data and render the runtime manifest

**Files:**
- Modify: `group_vars/all/main.yml`
- Modify: `site-core.yml` (user play, after the `desktop` import)
- Create: `roles/icloud/tasks/core.yml`
- Create: `roles/icloud/templates/icloud.conf.j2`
- Create: `roles/icloud/templates/folder.filter.j2`

**Interfaces:**
- Consumes: `target_home`, `target_user`, `setup_dir` (existing play facts).
- Produces: `~/.config/gatherd/icloud.conf`, a `sh`-sourceable manifest defining `ICLOUD_REMOTE`, `ICLOUD_ROOT`, and `ICLOUD_FOLDERS` (space-separated). Produces `~/.config/rclone/filters/<Folder>.filter`. Every later task's scripts read these.

- [ ] **Step 1: Add the variables**

Append to `group_vars/all/main.yml`:

```yaml
# iCloud Drive sync. The folder list is data on purpose: widening coverage is a
# list edit, not a code change. Downloads is excluded on the merits — 310 MB of
# constantly-churning share-sheet detritus is a poor fit for a bisync pair with a
# max-delete tripwire.
icloud_remote: icloud
icloud_sync_root: "{{ target_home }}/Documents/iCloud"
icloud_filters_base:
  - "- .DS_Store"
  - "- ._*"
  - "- *.icloud"
icloud_sync_folders:
  - remote: FSNotes
    filters:
      - "- projects.state"
      - "- *.textbundle"
      - "- /Trash/**"
```

- [ ] **Step 2: Write the manifest template**

Create `roles/icloud/templates/icloud.conf.j2`:

```jinja
# Managed by gatherd (roles/icloud). Sourced by gatherd-icloud-sync.
ICLOUD_REMOTE={{ icloud_remote }}
ICLOUD_ROOT={{ icloud_sync_root }}
ICLOUD_FOLDERS="{{ icloud_sync_folders | map(attribute='remote') | join(' ') }}"
```

- [ ] **Step 3: Write the filter template**

Create `roles/icloud/templates/folder.filter.j2`:

```jinja
# Managed by gatherd (roles/icloud).
{% for line in icloud_filters_base %}
{{ line }}
{% endfor %}
{% for line in item.filters | default([]) %}
{{ line }}
{% endfor %}
```

- [ ] **Step 4: Write the role tasks**

Create `roles/icloud/tasks/core.yml`. Scripts are installed in Task 3 onward; this step creates only what exists now.

```yaml
---
- name: Create iCloud sync directories
  ansible.builtin.file:
    path: "{{ item }}"
    state: directory
    mode: '0755'
  loop:
    - "{{ target_home }}/.config/gatherd"
    - "{{ target_home }}/.config/rclone/filters"
    - "{{ icloud_sync_root }}"
    - "{{ target_home }}/.local/state/gatherd"
    - "{{ target_home }}/.local/share/gatherd/icloud-backup"

- name: Create the local directory for each synced iCloud folder
  ansible.builtin.file:
    path: "{{ icloud_sync_root }}/{{ item.remote }}"
    state: directory
    mode: '0755'
  loop: "{{ icloud_sync_folders }}"
  loop_control:
    label: "{{ item.remote }}"

- name: Render the iCloud folder manifest
  ansible.builtin.template:
    src: icloud.conf.j2
    dest: "{{ target_home }}/.config/gatherd/icloud.conf"
    mode: '0644'

- name: Render the rclone filter file for each synced folder
  ansible.builtin.template:
    src: folder.filter.j2
    dest: "{{ target_home }}/.config/rclone/filters/{{ item.remote }}.filter"
    mode: '0644'
  loop: "{{ icloud_sync_folders }}"
  loop_control:
    label: "{{ item.remote }}"
```

- [ ] **Step 5: Wire the role into the CORE user play**

In `site-core.yml`, in the third play ("User configuration"), immediately after the existing `import_role` for `desktop`, add:

```yaml
    - name: Converge the offline iCloud sync tier
      ansible.builtin.import_role:
        name: icloud
        tasks_from: core
```

- [ ] **Step 6: Lint**

Run: `ansible-lint`
Expected: no new findings. Fix any that appear rather than adding `noqa`.

- [ ] **Step 7: Converge and verify the rendered files**

```bash
ansible-playbook -i inventory site-core.yml --tags icloud 2>/dev/null \
  || ansible-playbook -i inventory site-core.yml
cat ~/.config/gatherd/icloud.conf
cat ~/.config/rclone/filters/FSNotes.filter
```

Expected manifest:

```
ICLOUD_REMOTE=icloud
ICLOUD_ROOT=/home/schmonz/Documents/iCloud
ICLOUD_FOLDERS="FSNotes"
```

Expected filter: the three base lines then the three FSNotes lines — the same six patterns as today's `~/.config/rclone/fsnotes.filter`. Confirm with:

```bash
diff <(grep -v '^#' ~/.config/rclone/filters/FSNotes.filter) \
     <(sort -o /dev/stdout ~/.config/rclone/fsnotes.filter | cat)
```

Expected: same six patterns present (order may differ; verify by eye, not by exit code).

- [ ] **Step 8: Commit**

```bash
git add group_vars/all/main.yml site-core.yml roles/icloud
git commit -m "Declare the iCloud folder list and render its runtime manifest

The folder list is data so widening coverage is a list edit. Lands in CORE,
not REST: every converge-time action here is file installation with no
network, and REST placement would leave the scripts absent during a fresh
machine's first login."
```

---

### Task 3: Build the test harness and the password helper

**Files:**
- Create: `tests/icloud`
- Create: `scripts/gatherd-icloud-password`
- Modify: `roles/icloud/tasks/core.yml`
- Modify: `roles/system/tasks/user_path.yml`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `tests/icloud` exposing shell functions `assert_ok DESC CMD…`, `assert_fail DESC CMD…`, `assert_out DESC EXPECTED CMD…`, and `fake_bin NAME BODY`, used by Tasks 4–6. Produces `gatherd-icloud-password`, which reads `GATHERD_OP_VAULT` (default `Private`) and `GATHERD_OP_PASSWORD_ITEM` (default `rclone config`) and prints the password with no trailing newline.

- [ ] **Step 1: Write the test harness with its first failing test**

Create `tests/icloud`:

```sh
#!/bin/sh
# Unit tests for the gatherd-icloud-* scripts.
#
# Fakes rclone and op on PATH so the decision logic — baseline detection, the
# refuse-on-populated-dir guard, the publish-only-if-verified guard — is
# exercised without an iCloud account or a network. Those guards are the parts
# that must not be discovered to be wrong on a fresh repave.
#
# Usage: tests/icloud

set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
PASS=0
FAIL=0

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FAKEBIN="$WORK/bin"
mkdir -p "$FAKEBIN"
PATH="$FAKEBIN:$REPO/scripts:$PATH"
export PATH

# fake_bin NAME BODY — install a fake executable that shadows the real one.
fake_bin() {
    printf '#!/bin/sh\n%s\n' "$2" > "$FAKEBIN/$1"
    chmod +x "$FAKEBIN/$1"
}

ok()   { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }

assert_ok()   { _d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$_d"; else bad "$_d (expected success)"; fi; }
assert_fail() { _d=$1; shift; if "$@" >/dev/null 2>&1; then bad "$_d (expected failure)"; else ok "$_d"; fi; }
assert_out()  {
    _d=$1; _want=$2; shift 2
    _got=$("$@" 2>/dev/null || true)
    if [ "$_got" = "$_want" ]; then ok "$_d"; else bad "$_d (want [$_want] got [$_got])"; fi
}

# ── gatherd-icloud-password ───────────────────────────────────────────────────

fake_bin op 'case "$*" in
    *"op://Private/rclone config/password"*) printf secret123 ;;
    *) echo "unexpected op args: $*" >&2; exit 1 ;;
esac'

assert_out 'password helper reads the default item' secret123 gatherd-icloud-password

# Exported, not prefixed: a `VAR=x func` prefix does not reliably scope to a
# shell function the way it does to an external command.
export GATHERD_OP_VAULT=Other GATHERD_OP_PASSWORD_ITEM='other item'
assert_fail 'password helper honours item overrides' gatherd-icloud-password
unset GATHERD_OP_VAULT GATHERD_OP_PASSWORD_ITEM

fake_bin op 'echo "[ERROR] authorization timeout" >&2; exit 1'
assert_fail 'password helper fails when op is locked' gatherd-icloud-password

# ── summary ───────────────────────────────────────────────────────────────────

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Run it to verify it fails**

```bash
chmod +x tests/icloud
tests/icloud
```

Expected: FAIL lines for all three password-helper assertions, because `scripts/gatherd-icloud-password` does not exist. Exit status non-zero.

- [ ] **Step 3: Write the password helper**

Create `scripts/gatherd-icloud-password`:

```sh
#!/bin/sh
# Emits the rclone config-encryption password. Target of RCLONE_PASSWORD_COMMAND.
#
# A one-word command exists so pam_env.conf never has to quote a value that
# itself contains spaces and quotes (`op read "op://Private/rclone config/password"`)
# — pam_env's parser handles that poorly. It also gives one place to add a
# session-lifetime cache if shelling out to op on every rclone call gets tiresome.

set -eu

: "${GATHERD_OP_VAULT:=Private}"
: "${GATHERD_OP_PASSWORD_ITEM:=rclone config}"

exec op read --no-newline "op://${GATHERD_OP_VAULT}/${GATHERD_OP_PASSWORD_ITEM}/password"
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
chmod +x scripts/gatherd-icloud-password
tests/icloud
```

Expected: `3 passed, 0 failed`.

- [ ] **Step 5: Install the helper via the role**

Append to `roles/icloud/tasks/core.yml`:

```yaml
- name: Install the iCloud config-password helper
  ansible.builtin.copy:
    src: "{{ setup_dir }}/scripts/gatherd-icloud-password"
    dest: "{{ target_home }}/.local/bin/gatherd-icloud-password"
    mode: '0755'
    remote_src: true
```

- [ ] **Step 6: Migrate `RCLONE_PASSWORD_COMMAND` to pam_env**

`roles/system/tasks/user_path.yml` has one `blockinfile` task whose `block:` holds every session variable. Add two lines to the end of that block, immediately after the `SSH_ASKPASS` line:

```yaml
      # rclone shells out to this for the config-encryption password. A one-word
      # helper keeps pam_env from having to quote a value containing spaces and
      # quotes. Absolute path because rclone execs the command directly rather
      # than through a shell, so it does not get this file's own PATH edit.
      RCLONE_PASSWORD_COMMAND  DEFAULT=@{HOME}/.local/bin/gatherd-icloud-password
```

Also extend that task's `name:` so it still describes its contents:

```yaml
- name: Set user-session environment (PATH, Go, Qt theme, askpass, rclone) via pam_env
```

- [ ] **Step 7: Remove the hand-rolled export**

`~/.bashrc` currently carries `export RCLONE_PASSWORD_COMMAND='op read --no-newline "op://Private/rclone config/password"'`. Determine whether `~/.bashrc` is managed by the dotfiles repo:

```bash
ls -l ~/.bashrc
git -C ~/.dotfiles status --short 2>/dev/null || echo "not a dotfiles checkout"
```

If it is a dotfiles-managed file, remove the line **in the dotfiles repo** and commit there. If it is a plain local file, remove the line directly. Either way the line goes: leaving it means two sources of truth, and the `.bashrc` one shadows pam_env inside terminals.

- [ ] **Step 8: Verify delivery through PAM**

```bash
ansible-lint
ansible-playbook -i inventory site-core.yml
grep RCLONE_PASSWORD_COMMAND /etc/security/pam_env.conf
```

Expected: one line naming `gatherd-icloud-password`.

The variable only reaches a session created *after* the change, so full verification is deferred to Task 7's `section_verify` item. Confirm the mechanism now with:

```bash
env -u RCLONE_PASSWORD_COMMAND sh -c 'RCLONE_PASSWORD_COMMAND=gatherd-icloud-password rclone listremotes'
```

Expected: `icloud:` (requires 1Password unlocked).

- [ ] **Step 9: Commit**

```bash
git add tests/icloud scripts/gatherd-icloud-password roles/icloud/tasks/core.yml roles/system/tasks/user_path.yml
git commit -m "Deliver the rclone config password through pam_env

A one-word helper keeps a value containing spaces and quotes out of
pam_env.conf, whose parser handles it poorly. pam_env rather than .bashrc
because the sway session and the prompt cohort get no login shell.

Adds tests/icloud, which fakes rclone and op on PATH so the guard logic in
the scripts that follow can be tested without an account or a network."
```

---

### Task 4: Build the bisync driver

**Files:**
- Modify: `tests/icloud`
- Create: `scripts/gatherd-icloud-sync`
- Modify: `roles/icloud/tasks/core.yml`

**Interfaces:**
- Consumes: `~/.config/gatherd/icloud.conf` from Task 2 (`ICLOUD_REMOTE`, `ICLOUD_ROOT`, `ICLOUD_FOLDERS`); `gatherd-icloud-password` indirectly, via rclone.
- Produces: `gatherd-icloud-sync [--init|--init-if-empty|--if-due] [folder…]`. Exit 0 on success or not-ready; non-zero on genuine failure. Writes `$STATE/icloud-sync.stamp` on success and `$STATE/icloud-needs-reauth` on an auth failure (removing it on success) — Task 7 reads both. Honours `GATHERD_ICLOUD_CONF`, `GATHERD_ICLOUD_STATE`, `GATHERD_ICLOUD_FILTERS`, `GATHERD_ICLOUD_BACKUPS`, `GATHERD_ICLOUD_MIN_INTERVAL`.

- [ ] **Step 1: Write the failing tests**

Insert into `tests/icloud`, immediately before the `── summary ──` block:

```sh
# ── gatherd-icloud-sync ───────────────────────────────────────────────────────

sync_env() {
    HOME_DIR="$WORK/h$1"
    rm -rf "$HOME_DIR"
    mkdir -p "$HOME_DIR/conf" "$HOME_DIR/state" "$HOME_DIR/filters" "$HOME_DIR/backup" "$HOME_DIR/root/FSNotes"
    cat > "$HOME_DIR/conf/icloud.conf" <<EOF
ICLOUD_REMOTE=icloud
ICLOUD_ROOT=$HOME_DIR/root
ICLOUD_FOLDERS="FSNotes"
EOF
    : > "$HOME_DIR/filters/FSNotes.filter"
    export GATHERD_ICLOUD_CONF="$HOME_DIR/conf/icloud.conf"
    export GATHERD_ICLOUD_STATE="$HOME_DIR/state"
    export GATHERD_ICLOUD_FILTERS="$HOME_DIR/filters"
    export GATHERD_ICLOUD_BACKUPS="$HOME_DIR/backup"
    export GATHERD_ICLOUD_MIN_INTERVAL=300
}

# rclone fake: `lsd` succeeds, `bisync` records its argv and succeeds.
fake_rclone_ok() {
    fake_bin rclone 'case "$1" in
    lsd) exit 0 ;;
    bisync) printf "%s\n" "$*" >> "$GATHERD_ICLOUD_STATE/bisync.argv"; exit 0 ;;
    *) exit 0 ;;
esac'
}

sync_env 1; fake_rclone_ok
assert_ok 'resyncs into an empty local dir' gatherd-icloud-sync --init-if-empty
assert_ok 'used --resync on first run' grep -q -- --resync "$WORK/h1/state/bisync.argv"

sync_env 2; fake_rclone_ok
echo note > "$WORK/h2/root/FSNotes/a.md"
assert_fail 'refuses to resync a populated local dir' gatherd-icloud-sync --init-if-empty
assert_fail 'ran no bisync when refusing' test -f "$WORK/h2/state/bisync.argv"

sync_env 3; fake_rclone_ok
echo note > "$WORK/h3/root/FSNotes/a.md"
assert_ok 'explicit --init resyncs a populated dir' gatherd-icloud-sync --init
assert_ok 'explicit --init used --resync' grep -q -- --resync "$WORK/h3/state/bisync.argv"

sync_env 4; fake_rclone_ok
mkdir -p "$WORK/h4/state/bisync/FSNotes"
: > "$WORK/h4/state/bisync/FSNotes/icloud_FSNotes..path1.lst"
assert_ok 'syncs when a baseline exists' gatherd-icloud-sync
assert_fail 'did not resync over an existing baseline' \
    grep -q -- --resync "$WORK/h4/state/bisync.argv"

sync_env 5; fake_rclone_ok
assert_ok 'first --if-due run proceeds' gatherd-icloud-sync --init-if-empty --if-due
assert_ok 'wrote the stamp' test -f "$WORK/h5/state/icloud-sync.stamp"
cp "$WORK/h5/state/bisync.argv" "$WORK/h5/state/argv.before"
assert_ok 'second --if-due run is suppressed' gatherd-icloud-sync --if-due
assert_ok 'suppressed run did no work' cmp -s "$WORK/h5/state/argv.before" "$WORK/h5/state/bisync.argv"

sync_env 6
fake_bin rclone 'echo "Failed to load config file: password command failed" >&2; exit 1'
assert_ok 'a locked 1Password is not-ready, not failure' gatherd-icloud-sync --init-if-empty
assert_fail 'not-ready set no reauth flag' test -f "$WORK/h6/state/icloud-needs-reauth"

sync_env 7
fake_bin rclone 'case "$1" in
    lsd) echo "couldn'"'"'t list directory: 401 Unauthorized" >&2; exit 1 ;;
    *) exit 1 ;;
esac'
assert_fail 'an auth error is a real failure' gatherd-icloud-sync --init-if-empty
assert_ok 'auth error set the reauth flag' test -f "$WORK/h7/state/icloud-needs-reauth"

sync_env 8; fake_rclone_ok
: > "$WORK/h8/state/icloud-needs-reauth"
assert_ok 'a good run clears the reauth flag' gatherd-icloud-sync --init-if-empty
assert_fail 'reauth flag is gone' test -f "$WORK/h8/state/icloud-needs-reauth"

unset GATHERD_ICLOUD_CONF GATHERD_ICLOUD_STATE GATHERD_ICLOUD_FILTERS \
      GATHERD_ICLOUD_BACKUPS GATHERD_ICLOUD_MIN_INTERVAL
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `tests/icloud`
Expected: the 3 password assertions pass; all 18 sync assertions FAIL because `scripts/gatherd-icloud-sync` does not exist.

- [ ] **Step 3: Write the sync driver**

Create `scripts/gatherd-icloud-sync`:

```sh
#!/bin/sh
# Bidirectional sync of the declared iCloud Drive folders, via rclone bisync.
#
# Trigger-agnostic on purpose: safe to call from login, from gtklock's
# unlock-command, or by hand. The guards that make that true — a per-folder
# flock and the --if-due rate limit — live here rather than in each caller, so
# adding a trigger stays a one-liner.
#
# Usage:
#   gatherd-icloud-sync [FOLDER...]        sync (requires an existing baseline)
#   gatherd-icloud-sync --init [FOLDER...] build a baseline, even over local data
#   gatherd-icloud-sync --init-if-empty    build a baseline only where local is empty
#   gatherd-icloud-sync --if-due           no-op unless the rate-limit interval elapsed

set -eu

CONF="${GATHERD_ICLOUD_CONF:-$HOME/.config/gatherd/icloud.conf}"
STATE="${GATHERD_ICLOUD_STATE:-$HOME/.local/state/gatherd}"
FILTERS="${GATHERD_ICLOUD_FILTERS:-$HOME/.config/rclone/filters}"
BACKUPS="${GATHERD_ICLOUD_BACKUPS:-$HOME/.local/share/gatherd/icloud-backup}"
MIN_INTERVAL="${GATHERD_ICLOUD_MIN_INTERVAL:-300}"

STAMP="$STATE/icloud-sync.stamp"
REAUTH="$STATE/icloud-needs-reauth"
NOTIFIED="$STATE/icloud-notified.stamp"
NOTIFY_INTERVAL=3600

[ -r "$CONF" ] || { echo "gatherd-icloud-sync: no manifest at $CONF" >&2; exit 1; }
# shellcheck disable=SC1090
. "$CONF"

mkdir -p "$STATE" "$BACKUPS"

mode=sync
if_due=0
folders=

while [ $# -gt 0 ]; do
    case $1 in
        --init)          mode=init ;;
        --init-if-empty) mode=init-if-empty ;;
        --if-due)        if_due=1 ;;
        -*)              echo "gatherd-icloud-sync: unknown option $1" >&2; exit 2 ;;
        *)               folders="$folders $1" ;;
    esac
    shift
done
[ -n "$folders" ] || folders=$ICLOUD_FOLDERS

# Interactive runs talk to the terminal; triggered ones talk to the notification
# daemon, and then only about states a human has to resolve.
say() {
    if [ -t 2 ]; then
        printf 'gatherd-icloud-sync: %s\n' "$1" >&2
    else
        _now=$(date +%s)
        _last=0
        [ -f "$NOTIFIED" ] && _last=$(cat "$NOTIFIED" 2>/dev/null || echo 0)
        if [ $((_now - _last)) -ge "$NOTIFY_INTERVAL" ]; then
            command -v notify-send >/dev/null 2>&1 && notify-send "iCloud sync" "$1"
            echo "$_now" > "$NOTIFIED"
        fi
    fi
}

# Being unable to decrypt the config is "not ready" (1Password locked, or a
# machine that has not pulled the fleet config yet), not a failure. Silence is
# correct: the login path retries, and nagging on every unlock trains you to
# ignore the one notification that matters.
not_ready() {
    case $1 in
        *"password command failed"*|\
        *"Failed to load config"*|\
        *"authorization timeout"*|\
        *"could not read secret"*) return 0 ;;
    esac
    return 1
}

due() {
    [ "$if_due" -eq 1 ] || return 0
    [ -f "$STAMP" ] || return 0
    _now=$(date +%s)
    _then=$(cat "$STAMP" 2>/dev/null || echo 0)
    [ $((_now - _then)) -ge "$MIN_INTERVAL" ]
}

dir_is_empty() { [ -z "$(ls -A "$1" 2>/dev/null || true)" ]; }

# A baseline is the pair of listing files bisync leaves in its workdir. Giving
# each folder its own --workdir makes this a plain directory test instead of
# matching rclone's hashed default filenames.
has_baseline() { ls "$1"/*.path1.lst >/dev/null 2>&1; }

sync_folder() {
    _folder=$1
    _local="$ICLOUD_ROOT/$_folder"
    _workdir="$STATE/bisync/$_folder"
    _resync=

    mkdir -p "$_local" "$_workdir" "$BACKUPS/$_folder"

    if ! has_baseline "$_workdir"; then
        case $mode in
            init)
                _resync=--resync
                ;;
            init-if-empty)
                if dir_is_empty "$_local"; then
                    _resync=--resync
                else
                    say "$_folder has local files but no baseline; run: gatherd-icloud-sync --init $_folder"
                    return 1
                fi
                ;;
            *)
                say "$_folder has no baseline; run: gatherd-icloud-sync --init-if-empty"
                return 1
                ;;
        esac
    fi

    # --max-delete guards against a truncated remote listing deleting real files.
    # Keep the value at 10, identical to the fsnotes-sync it replaces, so the
    # migration changes no behaviour.
    rclone bisync "$ICLOUD_REMOTE:$_folder" "$_local" \
        $_resync \
        --workdir "$_workdir" \
        --filters-file "$FILTERS/$_folder.filter" \
        --conflict-resolve newer --conflict-loser pathname \
        --max-delete 10 --resilient --recover \
        --transfers 2 --checkers 4 --tpslimit 4 \
        --backup-dir1 "$BACKUPS/$_folder" \
        --log-file "$STATE/rclone-icloud-$_folder.log" -v
}

due || exit 0

# One probe up front, so "not ready" and "no network" are decided once rather
# than once per folder.
if ! probe=$(rclone lsd "$ICLOUD_REMOTE:" 2>&1 >/dev/null); then
    if not_ready "$probe"; then
        exit 0
    fi
    : > "$REAUTH"
    say "cannot reach iCloud; it may need re-authentication (rclone config reconnect $ICLOUD_REMOTE:)"
    exit 1
fi
rm -f "$REAUTH"

mkdir -p "$STATE/locks"
rc=0
for folder in $folders; do
    # The lock is held by the subshell for the whole sync_folder call and
    # released when it exits. Non-blocking on purpose: a sync already running for
    # this folder means this trigger has nothing to add, and two bisyncs on one
    # pair is how a baseline corrupts. A skipped folder exits 0 — it is not a
    # failure, so it must not set rc.
    (
        exec 9>"$STATE/locks/$folder.lock"
        flock -n 9 || exit 0
        sync_folder "$folder"
    ) || rc=1
done

[ "$rc" -eq 0 ] && date +%s > "$STAMP"
exit "$rc"
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
chmod +x scripts/gatherd-icloud-sync
tests/icloud
```

Expected: `21 passed, 0 failed`.

- [ ] **Step 5: Determine `--max-delete` semantics and record them**

rclone's global flag documents `--max-delete int` as a count, while bisync's own documentation describes `--max-delete PERCENT`. The value carried over from `fsnotes-sync` is `10` either way, so behaviour is unchanged — but the comment in the script must be true.

```bash
rclone bisync --help | grep -B2 -A2 max-delete
rclone help flags 2>/dev/null | grep -A2 'max-delete'
```

Amend the comment in `sync_folder` to state whichever it is: "at most 10 deletions" or "at most 10% of files deleted". Do not guess.

- [ ] **Step 6: Install the driver via the role**

Append to `roles/icloud/tasks/core.yml`:

```yaml
- name: Install the iCloud sync driver
  ansible.builtin.copy:
    src: "{{ setup_dir }}/scripts/gatherd-icloud-sync"
    dest: "{{ target_home }}/.local/bin/gatherd-icloud-sync"
    mode: '0755'
    remote_src: true
```

- [ ] **Step 7: Lint and commit**

```bash
ansible-lint
git add tests/icloud scripts/gatherd-icloud-sync roles/icloud/tasks/core.yml
git commit -m "Add the iCloud bisync driver with its baseline and rate-limit guards

Refusing to resync a populated local directory is the guard that matters:
resync declares a winner, and doing that unattended over real files is how
edits vanish. An empty directory has nothing to lose, so that case is safe
to automate and is the one a fresh repave hits.

Per-folder --workdir turns baseline detection into a directory test rather
than matching rclone's hashed default listing filenames."
```

---

### Task 5: Build the config and credential plumbing

**Files:**
- Modify: `tests/icloud`
- Create: `scripts/gatherd-icloud-config`
- Modify: `roles/icloud/tasks/core.yml`

**Interfaces:**
- Consumes: `gatherd-icloud-password` (Task 3) for decryption; `ICLOUD_REMOTE` from the manifest (Task 2).
- Produces: `gatherd-icloud-config {bootstrap|pull|push|status}`. `status` prints exactly one line to stdout of the form `config: <encrypted|plaintext|absent>, <verified|unreachable|not-ready>; fleet: <in sync|differs|absent|unknown>`. Writes `$STATE/icloud-fleet-ok` after a successful pull or push — Task 7 reads it. Honours `GATHERD_ICLOUD_STATE`, `GATHERD_OP_VAULT`, `GATHERD_OP_DOCUMENT` (default `rclone.conf`), `GATHERD_OP_PASSWORD_ITEM`, `RCLONE_CONFIG`.

- [ ] **Step 1: Write the failing tests**

Insert into `tests/icloud` before the `── summary ──` block:

```sh
# ── gatherd-icloud-config ─────────────────────────────────────────────────────

cfg_env() {
    C="$WORK/c$1"
    rm -rf "$C"
    mkdir -p "$C/state" "$C/op"
    export GATHERD_ICLOUD_STATE="$C/state"
    export RCLONE_CONFIG="$C/rclone.conf"
    export FAKE_OP_DIR="$C/op"
}

# op fake: documents are files under $FAKE_OP_DIR.
fake_op_docs() {
    fake_bin op 'case "$1 $2" in
    "document get")
        [ -f "$FAKE_OP_DIR/doc" ] || { echo "not found" >&2; exit 1; }
        cat "$FAKE_OP_DIR/doc" ;;
    "document create")
        cat > "$FAKE_OP_DIR/doc" ;;
    "document edit")
        cat > "$FAKE_OP_DIR/doc" ;;
    "item get")
        [ -f "$FAKE_OP_DIR/pw" ] || { echo "not found" >&2; exit 1; } ;;
    "item create")
        printf secret123 > "$FAKE_OP_DIR/pw" ;;
    *) exit 0 ;;
esac'
}

# rclone fake whose reachability is toggled by a marker file.
fake_rclone_reachable() {
    fake_bin rclone 'case "$1" in
    lsd) [ -f "$FAKE_OP_DIR/reachable" ] || { echo "401 Unauthorized" >&2; exit 1; }; exit 0 ;;
    config) case "$2" in show) cat "$RCLONE_CONFIG" 2>/dev/null ;; *) exit 0 ;; esac ;;
    *) exit 0 ;;
esac'
}

cfg_env 1; fake_op_docs; fake_rclone_reachable
printf 'FLEET-CONFIG-A' > "$C/op/doc"
assert_ok 'pull installs the fleet config when none is local' gatherd-icloud-config pull
assert_out 'pulled contents match the fleet copy' FLEET-CONFIG-A cat "$C/rclone.conf"

cfg_env 2; fake_op_docs; fake_rclone_reachable
printf 'FLEET-CONFIG-A' > "$C/op/doc"
printf 'LOCAL-BROKEN'   > "$C/rclone.conf"
assert_ok 'pull replaces an unreachable local config with a working fleet one' \
    sh -c 'touch "$FAKE_OP_DIR/reachable_after"; gatherd-icloud-config pull'

cfg_env 3; fake_op_docs; fake_rclone_reachable
printf 'LOCAL-BROKEN' > "$C/rclone.conf"
printf 'ALSO-BROKEN'  > "$C/op/doc"
assert_fail 'pull leaves a broken local config alone when the fleet copy is broken too' \
    gatherd-icloud-config pull
assert_out 'broken local config untouched' LOCAL-BROKEN cat "$C/rclone.conf"

cfg_env 4; fake_op_docs; fake_rclone_reachable
touch "$C/op/reachable"
printf 'LOCAL-REFRESHED' > "$C/rclone.conf"
printf 'FLEET-STALE'     > "$C/op/doc"
assert_ok 'push publishes a verified local config' gatherd-icloud-config push
assert_out 'fleet copy now matches local' LOCAL-REFRESHED cat "$C/op/doc"

cfg_env 5; fake_op_docs; fake_rclone_reachable
printf 'LOCAL-BROKEN' > "$C/rclone.conf"
printf 'FLEET-GOOD'   > "$C/op/doc"
assert_fail 'push refuses to publish an unverifiable config' gatherd-icloud-config push
assert_out 'fleet copy survives the refused push' FLEET-GOOD cat "$C/op/doc"

cfg_env 6; fake_op_docs; fake_rclone_reachable
touch "$C/op/reachable"
printf 'SAME' > "$C/rclone.conf"
printf 'SAME' > "$C/op/doc"
assert_ok 'push is a no-op when nothing changed' gatherd-icloud-config push
assert_ok 'push recorded fleet-ok' test -f "$C/state/icloud-fleet-ok"

cfg_env 7; fake_op_docs; fake_rclone_reachable
touch "$C/op/reachable"
printf '# Encrypted rclone configuration File\n\nRCLONE_ENCRYPT_V0:\nabc\n' > "$C/rclone.conf"
cp "$C/rclone.conf" "$C/op/doc"
assert_out 'status reports an encrypted, verified, in-sync config' \
    'config: encrypted, verified; fleet: in sync' gatherd-icloud-config status

cfg_env 8; fake_op_docs; fake_rclone_reachable
assert_out 'status reports an absent config' \
    'config: absent, not-ready; fleet: absent' gatherd-icloud-config status

unset GATHERD_ICLOUD_STATE RCLONE_CONFIG FAKE_OP_DIR
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `tests/icloud`
Expected: the 21 earlier assertions pass; the 13 new ones FAIL because `scripts/gatherd-icloud-config` does not exist.

- [ ] **Step 3: Write the config plumbing**

Create `scripts/gatherd-icloud-config`:

```sh
#!/bin/sh
# The 1Password half of gatherd's iCloud sync: moves the encrypted rclone.conf
# between this machine and the fleet copy. Knows nothing about folders or bisync.
#
# The distributed artifact is already encrypted, so no machine ever has to drive
# `rclone config encryption set` non-interactively — encryption happens once, in
# `bootstrap`, and every other machine only decrypts. rclone preserves existing
# encryption when it rewrites the file after a token refresh, so refreshed
# configs stay distributable.
#
# Usage: gatherd-icloud-config {bootstrap|pull|push|status}

set -eu

STATE="${GATHERD_ICLOUD_STATE:-$HOME/.local/state/gatherd}"
CONFIG="${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}"
REMOTE="${GATHERD_ICLOUD_REMOTE:-icloud}"

: "${GATHERD_OP_VAULT:=Private}"
: "${GATHERD_OP_DOCUMENT:=rclone.conf}"
: "${GATHERD_OP_PASSWORD_ITEM:=rclone config}"

FLEET_OK="$STATE/icloud-fleet-ok"

mkdir -p "$STATE"

# A decrypted config is a live iCloud token in plaintext, so scratch space is
# tmpfs (per-user, gone at logout) and never the disk.
TMP=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/gatherd-icloud.XXXXXX")
chmod 700 "$TMP"
trap 'rm -rf "$TMP"' EXIT

die() { printf 'gatherd-icloud-config: %s\n' "$1" >&2; exit 1; }

doc_get()    { op document get "$GATHERD_OP_DOCUMENT" --vault "$GATHERD_OP_VAULT"; }
doc_exists() { doc_get >/dev/null 2>&1; }
doc_put() {
    if doc_exists; then
        op document edit "$GATHERD_OP_DOCUMENT" --vault "$GATHERD_OP_VAULT" - < "$1"
    else
        op document create - --title "$GATHERD_OP_DOCUMENT" --vault "$GATHERD_OP_VAULT" < "$1"
    fi
}

# Reachability is the only definition of "this config works" that matters here.
config_works() { RCLONE_CONFIG="$1" rclone lsd "$REMOTE:" >/dev/null 2>&1; }

install_config() {
    mkdir -p "$(dirname "$CONFIG")"
    cp "$1" "$CONFIG"
    chmod 600 "$CONFIG"
}

cmd_pull() {
    if [ ! -s "$CONFIG" ]; then
        doc_get > "$TMP/fleet" 2>/dev/null || die "no fleet config yet; run: gatherd-icloud-config bootstrap"
        install_config "$TMP/fleet"
        : > "$FLEET_OK"
        return 0
    fi

    if config_works "$CONFIG"; then
        cmd_push
        return $?
    fi

    doc_get > "$TMP/fleet" 2>/dev/null || die "local config does not work and no fleet config exists"
    if config_works "$TMP/fleet"; then
        install_config "$TMP/fleet"
        : > "$FLEET_OK"
        return 0
    fi

    # Both copies are dead. Overwriting one with the other would look like
    # progress and be none, and would destroy the only config a human could
    # still repair with `rclone config reconnect`.
    die "neither the local nor the fleet config authenticates; iCloud needs re-authentication"
}

cmd_push() {
    [ -s "$CONFIG" ] || die "no local config to publish"
    config_works "$CONFIG" || die "refusing to publish a config that cannot reach iCloud"

    if doc_get > "$TMP/fleet" 2>/dev/null; then
        # Compare decrypted contents: rclone's config encryption is
        # nonce-randomised, so two encryptions of identical content differ
        # byte-for-byte and a ciphertext comparison would re-upload every run.
        RCLONE_CONFIG="$CONFIG"    rclone config show > "$TMP/local.plain" 2>/dev/null || true
        RCLONE_CONFIG="$TMP/fleet" rclone config show > "$TMP/fleet.plain" 2>/dev/null || true
        if cmp -s "$TMP/local.plain" "$TMP/fleet.plain"; then
            : > "$FLEET_OK"
            return 0
        fi
    fi

    doc_put "$CONFIG"
    : > "$FLEET_OK"
}

cmd_bootstrap() {
    # Every stage is idempotent against work already done by hand: this machine
    # already has a working remote, an encrypted config, and the password item,
    # so here bootstrap does nothing but upload the document. A bootstrap that
    # assumed greenfield would re-encrypt an encrypted config or overwrite a
    # password item other machines will come to depend on.
    if ! op item get "$GATHERD_OP_PASSWORD_ITEM" --vault "$GATHERD_OP_VAULT" >/dev/null 2>&1; then
        op item create --category=password \
            --title "$GATHERD_OP_PASSWORD_ITEM" --vault "$GATHERD_OP_VAULT" --generate-password
        echo "Created the config password item. Now encrypt the config:"
        echo "  rclone config encryption set"
        echo "and re-run: gatherd-icloud-config bootstrap"
        return 0
    fi

    [ -s "$CONFIG" ] || die "no local rclone config; run 'rclone config' and add the '$REMOTE' remote first"

    if ! head -n1 "$CONFIG" | grep -q 'Encrypted rclone configuration'; then
        die "local config is not encrypted; run: rclone config encryption set"
    fi

    config_works "$CONFIG" || die "local config does not authenticate; fix it before publishing it to the fleet"

    doc_put "$CONFIG"
    : > "$FLEET_OK"
    echo "Published the encrypted config to op://$GATHERD_OP_VAULT/$GATHERD_OP_DOCUMENT"
}

cmd_status() {
    if [ ! -s "$CONFIG" ]; then
        _enc=absent
    elif head -n1 "$CONFIG" | grep -q 'Encrypted rclone configuration'; then
        _enc=encrypted
    else
        _enc=plaintext
    fi

    if [ "$_enc" = absent ]; then
        _reach=not-ready
    elif config_works "$CONFIG"; then
        _reach=verified
    else
        _reach=unreachable
    fi

    if ! doc_get > "$TMP/fleet" 2>/dev/null; then
        _fleet=absent
    elif [ "$_enc" = absent ]; then
        _fleet=unknown
    else
        RCLONE_CONFIG="$CONFIG"    rclone config show > "$TMP/local.plain" 2>/dev/null || true
        RCLONE_CONFIG="$TMP/fleet" rclone config show > "$TMP/fleet.plain" 2>/dev/null || true
        if cmp -s "$TMP/local.plain" "$TMP/fleet.plain"; then _fleet='in sync'; else _fleet=differs; fi
    fi

    printf 'config: %s, %s; fleet: %s\n' "$_enc" "$_reach" "$_fleet"
}

case "${1:-status}" in
    bootstrap) cmd_bootstrap ;;
    pull)      cmd_pull ;;
    push)      cmd_push ;;
    status)    cmd_status ;;
    *)         echo "usage: $0 {bootstrap|pull|push|status}" >&2; exit 2 ;;
esac
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
chmod +x scripts/gatherd-icloud-config
tests/icloud
```

Expected: `34 passed, 0 failed`.

The `cfg_env 2` test ("pull replaces an unreachable local config with a working fleet one") requires the rclone fake to report the *fleet* copy reachable while the local one is not. If it fails, adjust the fake so `lsd` keys on the contents of `$RCLONE_CONFIG` — `grep -q FLEET "$RCLONE_CONFIG" && exit 0; exit 1` — rather than on a marker file. Adjust the fake, not the script.

- [ ] **Step 5: Run T5 from spec §11.1 — self-healing**

This is the test that decides whether R1 matters. With a real 1Password and a real remote:

```bash
gatherd-icloud-config status
cp ~/.config/rclone/rclone.conf /tmp/rclone.conf.bak
printf 'CORRUPT' > ~/.config/rclone/rclone.conf
gatherd-icloud-config pull
gatherd-icloud-config status
```

Expected: the `pull` restores a working config from the fleet document with **no 2FA prompt**, and `status` returns to `config: encrypted, verified; fleet: in sync`.

This can only run after Task 8 has published the fleet document. If Task 8 has not run yet, note that and return here.

Restore on any failure: `cp /tmp/rclone.conf.bak ~/.config/rclone/rclone.conf`

- [ ] **Step 6: Install via the role**

Append to `roles/icloud/tasks/core.yml`:

```yaml
- name: Install the iCloud config plumbing
  ansible.builtin.copy:
    src: "{{ setup_dir }}/scripts/gatherd-icloud-config"
    dest: "{{ target_home }}/.local/bin/gatherd-icloud-config"
    mode: '0755'
    remote_src: true
```

- [ ] **Step 7: Lint and commit**

```bash
ansible-lint
git add tests/icloud scripts/gatherd-icloud-config roles/icloud/tasks/core.yml
git commit -m "Distribute the encrypted rclone config through 1Password

Push compares decrypted contents, not ciphertext: rclone's config encryption
is nonce-randomised, so identical configs differ byte-for-byte and a naive
comparison would re-upload on every run.

Two guards matter. Push refuses to publish a config that cannot reach iCloud,
so a broken machine cannot poison the fleet. Pull refuses to overwrite a
broken local config with an equally broken fleet one, which would look like
progress while destroying the only copy a human could still repair."
```

---

### Task 6: Wire the triggers

**Files:**
- Modify: `tests/icloud`
- Create: `scripts/gatherd-prompt-icloud`
- Modify: `scripts/gatherd-session-helpers`
- Modify: `roles/desktop/templates/gtklock-config.ini.j2`
- Modify: `roles/icloud/tasks/core.yml`

**Interfaces:**
- Consumes: `gatherd-icloud-config pull` and `gatherd-icloud-sync --init-if-empty` (Tasks 4–5).
- Produces: `gatherd-prompt-icloud`, launched as a `gatherd-session-helpers` cohort child. Honours `GATHERD_ICLOUD_DEADLINE` (seconds, default 300) so tests need not wait five minutes.

- [ ] **Step 1: Write the failing tests**

Insert into `tests/icloud` before the `── summary ──` block:

```sh
# ── gatherd-prompt-icloud ─────────────────────────────────────────────────────

prompt_env() {
    P="$WORK/p$1"
    rm -rf "$P"; mkdir -p "$P"
    export GATHERD_ICLOUD_DEADLINE=2
    export PROMPT_TRACE="$P/trace"
}

prompt_env 1
fake_bin op 'exit 1'
fake_bin gatherd-icloud-config 'echo "config $*" >> "$PROMPT_TRACE"'
fake_bin gatherd-icloud-sync   'echo "sync $*" >> "$PROMPT_TRACE"'
assert_ok 'prompt gives up quietly when 1Password never answers' gatherd-prompt-icloud
assert_fail 'prompt did no work without 1Password' test -f "$P/trace"

prompt_env 2
fake_bin op 'exit 0'
fake_bin gatherd-icloud-config 'echo "config $*" >> "$PROMPT_TRACE"'
fake_bin gatherd-icloud-sync   'echo "sync $*" >> "$PROMPT_TRACE"'
assert_ok 'prompt runs once 1Password answers' gatherd-prompt-icloud
assert_out 'prompt pulled then synced' 'config pull
sync --init-if-empty' cat "$P/trace"

unset GATHERD_ICLOUD_DEADLINE PROMPT_TRACE
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `tests/icloud`
Expected: 34 pass, the 4 new ones FAIL.

- [ ] **Step 3: Write the prompt script**

Create `scripts/gatherd-prompt-icloud`:

```sh
#!/bin/sh
# Sway autostart helper: fetches the fleet iCloud config once 1Password is
# usable, then establishes any missing local folder copies.
#
# Same readiness problem as gatherd-prompt-pia: `op whoami` is not a usable
# check under desktop-app integration (it only reports an explicit `op signin`),
# so poll an actual read instead — it starts succeeding once the app is running,
# unlocked, and CLI access is authorised.

set -eu

: "${GATHERD_OP_VAULT:=Private}"
: "${GATHERD_OP_PASSWORD_ITEM:=rclone config}"
DEADLINE_SECS="${GATHERD_ICLOUD_DEADLINE:-300}"

command -v op >/dev/null 2>&1 || exit 0

_deadline=$(( $(date +%s) + DEADLINE_SECS ))
until op item get "$GATHERD_OP_PASSWORD_ITEM" --vault "$GATHERD_OP_VAULT" >/dev/null 2>&1; do
    [ "$(date +%s)" -lt "$_deadline" ] || exit 0
    sleep 5
done

# Both are quiet on the paths that are merely "not ready yet", so a machine that
# has not been bootstrapped produces no noise at every login.
gatherd-icloud-config pull >/dev/null 2>&1 || exit 0
gatherd-icloud-sync --init-if-empty >/dev/null 2>&1 || exit 0
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
chmod +x scripts/gatherd-prompt-icloud
tests/icloud
```

Expected: `38 passed, 0 failed`.

- [ ] **Step 5: Add it to the session cohort**

In `scripts/gatherd-session-helpers`, add after the `run "$bin/gatherd-prompt-pia"` line:

```sh
run "$bin/gatherd-prompt-icloud"
```

No change is needed to the stale-standalone-`exec` removal loop in `roles/desktop/tasks/core.yml`: that loop exists to clean up helpers that once had their own sway `exec` line, and `gatherd-prompt-icloud` never did.

- [ ] **Step 6: Add the unlock trigger**

In `roles/desktop/templates/gtklock-config.ini.j2`, add to the `[main]` section:

```ini
unlock-command={{ target_home }}/.local/bin/gatherd-icloud-sync --if-due
```

Put it in `config.ini` rather than in the three `swayidle` handlers: every path to a locked screen — idle timeout, lid close via `gatherd-handle-lid`, `before-sleep`, `after-resume` — routes through `gtklock -d` and so picks this up from one place. Add that as a comment above the line.

- [ ] **Step 7: Install the prompt script via the role**

Append to `roles/icloud/tasks/core.yml`:

```yaml
- name: Install the iCloud login helper
  ansible.builtin.copy:
    src: "{{ setup_dir }}/scripts/gatherd-prompt-icloud"
    dest: "{{ target_home }}/.local/bin/gatherd-prompt-icloud"
    mode: '0755'
    remote_src: true
```

- [ ] **Step 8: Converge and verify the wiring**

```bash
ansible-lint
ansible-playbook -i inventory site-core.yml
grep unlock-command ~/.config/gtklock/config.ini
grep gatherd-prompt-icloud ~/.local/bin/gatherd-session-helpers
```

Expected: one line each.

- [ ] **Step 9: Commit**

```bash
git add tests/icloud scripts/gatherd-prompt-icloud scripts/gatherd-session-helpers \
        roles/desktop/templates/gtklock-config.ini.j2 roles/icloud/tasks/core.yml
git commit -m "Trigger iCloud sync at login and on screen unlock

Unlock is a better trigger than a timer, and not only conveniently: op cannot
decrypt the config while the session is locked, so a session unlock is the
best available signal that a human is present and 1Password is reachable.

The hook goes in gtklock's config.ini rather than the swayidle handlers
because every path to a locked screen routes through gtklock -d."
```

---

### Task 7: Update the post-setup notes

**Files:**
- Modify: `scripts/gatherd-post-setup-notes`

**Interfaces:**
- Consumes: `$HOME/.local/state/gatherd/icloud-fleet-ok` (Task 5) and `icloud-needs-reauth` (Task 4).
- Produces: no interface for later tasks.

- [ ] **Step 1: Replace the state detector**

In the "App state detection" block, replace:

```sh
icloud_configured()     { rclone listremotes 2>/dev/null | grep -q '^icloud:'; }
```

with:

```sh
# Sentinels rather than a live probe: this script runs at every login, and
# `rclone listremotes` now shells out to op for the config password, which
# blocks on a locked 1Password. Both files are written by gatherd-icloud-config
# and gatherd-icloud-sync.
_icloud_state="$HOME/.local/state/gatherd"
icloud_fleet_ok()    { [ -f "$_icloud_state/icloud-fleet-ok" ]; }
icloud_needs_reauth() { [ -f "$_icloud_state/icloud-needs-reauth" ]; }
```

- [ ] **Step 2: Rewrite the iCloud section handler**

Replace the body of `section_other_logins` with:

```sh
section_other_logins() {
    # Two mutually exclusive iCloud lines, both self-pruning. Bootstrap is a
    # once-per-fleet step, so it only appears on a machine that has never seen a
    # fleet config. Re-auth is periodic and unavoidable — the session token
    # expires whatever we do — so it appears whenever a sync hits an auth error
    # and disappears on the next success.
    b_bootstrap='iCloud: run `gatherd-icloud-config bootstrap` (once per fleet; needs `rclone config` + 2FA first if this is the very first machine)'
    b_reauth='iCloud needs re-authentication: run `rclone config reconnect icloud:` and complete 2FA — every other machine picks it up automatically'

    if icloud_fleet_ok; then
        prune_section 'Other Logins' "$b_bootstrap"
    else
        section_present 'Other Logins' || h 'Other Logins'
        li "$b_bootstrap"
    fi

    if icloud_needs_reauth; then
        section_present 'Other Logins' || h 'Other Logins'
        li "$b_reauth"
    else
        prune_section 'Other Logins' "$b_reauth"
    fi
}
```

Read the existing `prune_section`, `section_present`, `h`, and `li` helpers first and match their exact calling conventions — the snippet above assumes `prune_section SECTION BULLET…` and `section_present SECTION`, which is what the current code does, but confirm before relying on it.

- [ ] **Step 3: Add the verify items**

Add two `li` items to `section_verify`:

```sh
    li 'iCloud sync: `gatherd-icloud-config status` prints `config: encrypted, verified; fleet: in sync`; `gatherd-icloud-sync FSNotes` exits 0 and `tail -3 ~/.local/state/gatherd/rclone-icloud-FSNotes.log` ends with a successful bisync; `ls ~/Documents/iCloud/FSNotes | wc -l` is non-zero'
    li 'iCloud unlock trigger: `grep -c unlock-command ~/.config/gtklock/config.ini` prints 1; note `stat -c %Y ~/.local/state/gatherd/icloud-sync.stamp`, lock the screen and unlock it, then re-run — the value has advanced'
```

- [ ] **Step 4: Verify the notes render**

```bash
sh -n scripts/gatherd-post-setup-notes
scripts/gatherd-post-setup-notes
cat /etc/gatherd/post-setup-notes 2>/dev/null || echo "(check the script for its output path)"
```

Expected: no syntax errors; the bootstrap line appears (the fleet document does not exist until Task 8); no re-auth line; both verify items present.

- [ ] **Step 5: Count the checklist**

```bash
awk '/^section_verify\(\)/,/^}/' scripts/gatherd-post-setup-notes | grep -c '^ *li '
```

Expected: `9`. `CLAUDE.md` asks for a repave suggestion above 10 — note in the commit message that this lands at 9 and the next feature crosses the line.

- [ ] **Step 6: Commit**

```bash
git add scripts/gatherd-post-setup-notes
git commit -m "Replace the iCloud rclone-config nag with fleet-aware prompts

Bootstrap is a once-per-fleet step, so its line only appears on a machine
that has never seen a fleet config. Re-auth is periodic and unavoidable, so
it appears on an auth error and prunes itself on the next success.

Both read sentinel files rather than probing rclone: this script runs at
every login, and rclone now shells out to op for the config password, which
blocks on a locked 1Password.

section_verify is now at 9 items; the next feature crosses CLAUDE.md's
repave-suggestion threshold."
```

---

### Task 8: Publish the fleet config and migrate `~/notes`

The live cutover. Everything before this is inert; nothing before this touches real data.

**Files:** none — this is operational work, plus a cleanup commit.

**Interfaces:**
- Consumes: all four scripts, installed and converged.
- Produces: the `rclone.conf` document in 1Password; `~/Documents/iCloud/FSNotes` populated with a live baseline.

- [ ] **Step 1: Publish the encrypted config to the fleet**

```bash
gatherd-icloud-config status
gatherd-icloud-config bootstrap
gatherd-icloud-config status
```

Expected: `status` goes from `fleet: absent` to `fleet: in sync`. The password item already exists and the config is already encrypted, so `bootstrap` should do nothing but upload.

- [ ] **Step 2: Run T5 from Task 5 Step 5**

It could not run before the document existed. Run it now, and record the result in the spec's §11.1 if it deviates.

- [ ] **Step 3: Sync `~/notes` one last time with the old script**

```bash
~/.local/bin/fsnotes-sync
```

Expected: exit 0. The migration is safe precisely because both sides are in sync; make that true immediately before the move rather than assuming it.

- [ ] **Step 4: Move the tree**

```bash
ls ~/notes | wc -l
mv ~/notes/* ~/notes/.[!.]* ~/Documents/iCloud/FSNotes/ 2>/dev/null || true
ls ~/Documents/iCloud/FSNotes | wc -l
rmdir ~/notes
```

Expected: the second count equals the first. `mv` of a glob rather than the directory itself, because Task 2 already created `~/Documents/iCloud/FSNotes`.

- [ ] **Step 5: Build the new baseline**

The local directory is now populated, so `--init-if-empty` will correctly refuse. Use the explicit form and watch it:

```bash
gatherd-icloud-sync --init FSNotes
echo "exit: $?"
tail -5 ~/.local/state/gatherd/rclone-icloud-FSNotes.log
ls ~/Documents/iCloud/FSNotes | wc -l
```

Expected: exit 0, a successful bisync in the log, and a file count matching Step 4. If the count *dropped*, stop — the backup of anything deleted is under `~/.local/share/gatherd/icloud-backup/FSNotes`.

- [ ] **Step 6: Confirm a plain sync round-trips**

```bash
date > ~/Documents/iCloud/FSNotes/gatherd-migration-test.md
gatherd-icloud-sync FSNotes
rclone lsf icloud:FSNotes | grep gatherd-migration-test
rm ~/Documents/iCloud/FSNotes/gatherd-migration-test.md
gatherd-icloud-sync FSNotes
rclone lsf icloud:FSNotes | grep -c gatherd-migration-test
```

Expected: the file appears remotely after the first sync, and the final count is `0`.

- [ ] **Step 7: Retire the old script and filter**

```bash
rm ~/.local/bin/fsnotes-sync ~/.config/rclone/fsnotes.filter ~/.config/rclone/fsnotes.filter.md5
rm -rf ~/.cache/rclone/bisync
ls ~/.local/share/notes-backup 2>/dev/null && echo "(old backup dir — keep until you trust the new one)"
```

`~/.cache/rclone/bisync` holds the old baseline keyed to `~/notes`, which no longer exists; the new baselines live under `~/.local/state/gatherd/bisync/`.

- [ ] **Step 8: Commit the cutover**

Nothing in the repo changed in this task, so commit only if Step 2 or Step 5 forced a code fix. Otherwise record the cutover in the spec:

```bash
git commit --allow-empty -m "Cut over from fsnotes-sync to gatherd-managed iCloud sync

~/notes moved to ~/Documents/iCloud/FSNotes, a fresh baseline built with
--init, the encrypted config published to the fleet, and the old script,
filter, and bisync cache removed."
```

---

### Task 9: Leave T4 running, then close it out

**Files:**
- Modify: `roles/desktop/templates/gtklock-config.ini.j2` (temporarily)
- Later: delete `tests/icloud-shadow`

**Interfaces:**
- Consumes: `tests/icloud-shadow log` from Task 1; the unlock trigger from Task 6.
- Produces: `~/.local/state/gatherd/icloud-shadow/probe.log`, the evidence for spec §11.1 T4.

- [ ] **Step 1: Attach the shadow logger to the unlock trigger**

Temporarily extend the `unlock-command` line in `roles/desktop/templates/gtklock-config.ini.j2`:

```ini
unlock-command=sh -c '{{ target_home }}/.local/bin/gatherd-icloud-sync --if-due; {{ setup_dir }}/tests/icloud-shadow log'
```

Add a comment marking it temporary and naming the spec section, so it is not mistaken for permanent design:

```ini
# TEMPORARY (spec 2026-08-10-icloud-sync §11.1 T4): the shadow logger rides
# along on unlock to accumulate shared-session-token evidence without
# attention. Remove this and tests/icloud-shadow once T4 concludes.
```

- [ ] **Step 2: Converge and seed the log**

```bash
ansible-lint
ansible-playbook -i inventory site-core.yml
tests/icloud-shadow log
cat ~/.local/state/gatherd/icloud-shadow/probe.log
```

Expected: one line like `2026-08-10T18:00:00Z real=ok shadow=ok configs=identical`.

- [ ] **Step 3: Commit**

```bash
git add roles/desktop/templates/gtklock-config.ini.j2
git commit -m "Ride the shadow-token logger along on unlock for T4

Accumulates shared-session-token evidence without attention. Temporary —
see the comment in the template and spec §11.1."
```

- [ ] **Step 4: After one to two weeks, read the evidence and close T4**

```bash
cat ~/.local/state/gatherd/icloud-shadow/probe.log
grep -c 'real=fail\|shadow=fail' ~/.local/state/gatherd/icloud-shadow/probe.log
```

Interpretation:

- No `fail` lines → shared tokens hold. Record the result in spec §10 R1.
- `configs=differ` appearing → a refresh rotated one copy. Confirm the *next* line shows both still `ok` (that is §5.3 healing, if a `pull` ran between them) and record it.
- Repeated `shadow=fail` while `real=ok` → siblings do not survive refresh. Not a redesign: record that machines re-pull more often, and consider whether `gatherd-prompt-icloud`'s `pull` should also run on unlock rather than only at login.
- Both failing together with a 2FA demand → the blocking outcome. Revisit spec §10's fallback.

- [ ] **Step 5: Remove the temporary rig**

```bash
git rm tests/icloud-shadow
```

Restore the `unlock-command` line in `roles/desktop/templates/gtklock-config.ini.j2` to the plain form from Task 6, and delete the TEMPORARY comment.

```bash
ansible-lint
ansible-playbook -i inventory site-core.yml
grep unlock-command ~/.config/gtklock/config.ini
rm -rf ~/.local/state/gatherd/icloud-shadow
```

- [ ] **Step 6: Update the spec and commit**

Record the T4 outcome in spec §10 R1 and mark §11.1 complete.

```bash
git add docs/superpowers/specs/2026-08-10-icloud-sync-design.md \
        roles/desktop/templates/gtklock-config.ini.j2
git commit -m "Close out the shared-session-token question and remove the rig

Records the T4 result in the spec and restores the plain unlock trigger."
```

---

## Backlog note

`plans/TODO.md` has no iCloud item to delete — the manual `rclone config` step lived only in `gatherd-post-setup-notes`, and Task 7 removes it there. Per `CLAUDE.md`, the verify steps added in Task 7 are what record this work as done; git log is the rest.

Deferred, and deliberately not in this plan: scheduled/timer-driven sync, the NetworkManager `dispatcher.d` trigger, and any folder beyond `FSNotes`. The last of those is a `group_vars` list edit once the mechanism has held for a while.
