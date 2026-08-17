# Tablet Mode Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A manually-triggered tablet mode — rotate to portrait, silence the built-in keyboard and touchpad, escape via the edge power button — plus a composer-then-score picker that opens sheet music fullscreen at the piano.

**Architecture:** One mechanism script (`gatherd-tablet-mode`) is the only thing that touches sway state; every trigger is a caller. `gatherd-music-stand` layers score selection on top, fed by `gatherd-music-index`, which decodes composer metadata out of forScore's backup. `gatherd-power-button` dispatches on tablet state so the escape hatch works with no keyboard. Phase 2 (hinge-angle daemon) will land as one more caller and is out of scope here.

**Tech Stack:** POSIX `sh` for the runtime scripts, Python 3 stdlib (`zlib`, `plistlib`) for the index decoder, `jq` for sway IPC JSON, `fuzzel --dmenu` for touch pickers, Ansible for installation.

**Spec:** `docs/superpowers/specs/2026-08-16-tablet-mode-design.md`

## Global Constraints

- **No new packages except `papers`.** `core_packages` must stay `[]`; `scripts/gatherd-check-package-tiers` enforces this. Everything but the viewer is CORE tier and must converge with no network.
- **Runtime deps are already installed and already packaged:** `jq` (group_vars line 110), `fuzzel`, `python3`. Do not add them.
- **The resting output transform is `90`, not `normal`.** wlroots applies the DRM panel-orientation quirk itself. Portrait is `normal` (857×1371); landscape is `90` (1371×857). `off` must restore the *recorded* transform, never a hardcoded one.
- **Disable built-in input only.** Built-in keyboards are the ones whose sway identifier starts `1:1:` (i8042). External and Bluetooth keyboards — including page-turner pedals — must keep working.
- **FQCN in all Ansible tasks:** `ansible.builtin.*`, `community.general.*`.
- **Task names read like imperative sentences.**
- **Comments explain *why*, never *what*.**
- Run `ansible-lint` before committing any Ansible change.
- Scripts live in `scripts/` with no extension and install to `{{ target_home }}/.local/bin/`.
- Shell style: `#!/bin/sh`, `set -eu`, a header comment citing the spec.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/gatherd-tablet-mode` | **Create.** The mechanism: rotate + suppress built-in input. Only file that mutates sway state. |
| `scripts/gatherd-music-index` | **Create.** Decode `Automatic Backup.4sb` → composer/title/filename TSV. Isolates the proprietary format. |
| `scripts/gatherd-music-stand` | **Create.** Two-level MRU picker; calls the mechanism, launches the viewer. |
| `scripts/gatherd-power-button` | **Create.** Dispatch on tablet state: power menu when unfolded, exit menu when folded. |
| `tests/tablet-mode` | **Create.** POSIX-sh unit tests with faked `swaymsg`/`fuzzel`, following `tests/icloud`. |
| `roles/desktop/templates/tablet-mode.conf.j2` | **Create.** Config sourced by the scripts (transform, viewer, root). |
| `roles/desktop/tasks/tablet_mode.yml` | **Create.** Installs the above. Imported from `desktop/tasks/core.yml`. |
| `roles/machine_facts/defaults/main.yml` | **Modify.** Add `has_touchscreen`, `has_accelerometer` defaults. |
| `roles/machine_facts/tasks/main.yml` | **Modify.** Add both probes; publish both facts. |
| `roles/desktop/tasks/core.yml` | **Modify.** Import `tablet_mode.yml`; make the `XF86PowerOff` binding conditional. |
| `group_vars/all/main.yml` | **Modify.** Add feature vars; add `papers` to `rest_packages`. |
| `scripts/gatherd-post-setup-notes` | **Modify.** Add verify items. |

---

### Task 1: Capability facts

**Files:**
- Modify: `roles/machine_facts/defaults/main.yml`
- Modify: `roles/machine_facts/tasks/main.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: host facts `has_touchscreen` (bool) and `has_accelerometer` (bool), available to later plays. Task 6 gates on them.

- [ ] **Step 1: Verify the probes return `true` on this machine before writing any Ansible**

Run both probe bodies directly. This is the "failing test" equivalent — an Ansible fact has no unit-test harness, so prove the shell logic first.

```bash
for d in /dev/input/event*; do
  udevadm info "$d" 2>/dev/null | grep -q "ID_INPUT_TOUCHSCREEN=1" && { echo true; exit 0; }
done; echo false
```

Expected: `true`

```bash
ls /sys/bus/iio/devices/*/in_accel_x_raw >/dev/null 2>&1 && echo true || echo false
```

Expected: `true`

- [ ] **Step 2: Add the defaults**

In `roles/machine_facts/defaults/main.yml`, add these two lines in the existing alphabetical-ish `has_*` block (after `has_thinkpad_trackpoint: false`):

```yaml
has_accelerometer: false
has_touchscreen: false
```

- [ ] **Step 3: Add the probes**

In `roles/machine_facts/tasks/main.yml`, insert before the `Detect has_plenty_of_ram` task:

```yaml
# A convertible is not identifiable from DMI here: the MiniBook X reports
# chassis_type 10 (Notebook), not 31 (Convertible). Touchscreen plus
# accelerometer is the honest proxy — a laptop with both is a convertible or a
# tablet in practice.
- name: Check for a touchscreen input device
  ansible.builtin.shell: |
    for d in /dev/input/event*; do
      udevadm info "$d" 2>/dev/null | grep -q "ID_INPUT_TOUCHSCREEN=1" && { echo true; exit 0; }
    done
    echo false
  register: _touchscreen
  changed_when: false

- name: Detect has_touchscreen
  ansible.builtin.set_fact:
    has_touchscreen: true
  when: _touchscreen.stdout == 'true'

- name: Check for an IIO accelerometer
  ansible.builtin.shell: |
    ls /sys/bus/iio/devices/*/in_accel_x_raw >/dev/null 2>&1 && echo true || echo false
  register: _accelerometer
  changed_when: false

- name: Detect has_accelerometer
  ansible.builtin.set_fact:
    has_accelerometer: true
  when: _accelerometer.stdout == 'true'
```

- [ ] **Step 4: Publish both facts**

In the `Publish hardware facts for cross-play use` task in the same file, add two lines to the `set_fact` mapping:

```yaml
    has_accelerometer: "{{ has_accelerometer }}"
    has_touchscreen: "{{ has_touchscreen }}"
```

- [ ] **Step 5: Lint**

Run: `ansible-lint roles/machine_facts/`
Expected: no new findings.

- [ ] **Step 6: Commit**

```bash
git add roles/machine_facts/defaults/main.yml roles/machine_facts/tasks/main.yml
git commit -m "Detect touchscreen and accelerometer capability

DMI cannot identify this convertible: the MiniBook X reports chassis_type
10 (Notebook), not 31. Touchscreen plus accelerometer is the honest proxy."
```

---

### Task 2: The tablet-mode mechanism

**Files:**
- Create: `scripts/gatherd-tablet-mode`
- Create: `tests/tablet-mode`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `gatherd-tablet-mode on|off|toggle|status`. `status` exits 0 when active, 1 when not — Task 5 branches on this. Reads optional config `${XDG_CONFIG_HOME:-$HOME/.config}/gatherd/tablet-mode.conf` (Task 6 installs it), which may set `transform=`. Env `GATHERD_TABLET_TRANSFORM` overrides for tests. State file: `${XDG_RUNTIME_DIR:-/tmp}/gatherd/tablet-mode`.

- [ ] **Step 1: Write the failing test**

Create `tests/tablet-mode`:

```sh
#!/bin/sh
# Unit tests for gatherd-tablet-mode.
#
# Fakes swaymsg so the decision logic — record-then-restore of the real resting
# transform, and disabling ONLY built-in input — is exercised without a running
# compositor. Those two are the parts that must not be discovered to be wrong
# while the machine is folded on a music stand.
#
# Usage: tests/tablet-mode

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

XDG_RUNTIME_DIR="$WORK/run"
XDG_CONFIG_HOME="$WORK/config"
mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME"
export XDG_RUNTIME_DIR XDG_CONFIG_HOME

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }

assert_out() {
    _d=$1; _want=$2; shift 2
    _got=$("$@" 2>/dev/null || true)
    if [ "$_got" = "$_want" ]; then ok "$_d"; else bad "$_d (want [$_want] got [$_got])"; fi
}
assert_ok()   { _d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$_d"; else bad "$_d (expected success)"; fi; }
assert_fail() { _d=$1; shift; if "$@" >/dev/null 2>&1; then bad "$_d (expected failure)"; else ok "$_d"; fi; }

# The resting transform is 90, not normal: wlroots applies the DRM
# panel-orientation quirk on this rotated panel. Seeding the fake with 90 is
# what makes the restore test meaningful.
printf '90' > "$WORK/transform"

cat > "$WORK/inputs.json" <<'JSON'
[
  {"identifier":"1:1:AT_Translated_Set_2_keyboard","type":"keyboard"},
  {"identifier":"0:1:Power_Button","type":"keyboard"},
  {"identifier":"1234:5678:AirTurn_PEDpro","type":"keyboard"},
  {"identifier":"2321:21128:XXXX0000:05_0911:5288_Touchpad","type":"touchpad"},
  {"identifier":"1046:9110:Goodix_Capacitive_TouchScreen","type":"touch"}
]
JSON

cat > "$FAKEBIN/swaymsg" <<EOF
#!/bin/sh
WORK='$WORK'
case "\$1" in
  -t)
    case "\$2" in
      get_outputs)
        printf '[{"name":"DSI-1","transform":"%s","rect":{"width":1371,"height":857}}]' "\$(cat "\$WORK/transform")" ;;
      get_inputs) cat "\$WORK/inputs.json" ;;
    esac ;;
  output)
    printf '%s\n' "\$*" >> "\$WORK/swaymsg.log"
    printf '%s' "\$4" > "\$WORK/transform" ;;
  input)
    printf '%s\n' "\$*" >> "\$WORK/swaymsg.log" ;;
esac
EOF
chmod +x "$FAKEBIN/swaymsg"

log_has() { grep -qF "$1" "$WORK/swaymsg.log" 2>/dev/null; }
reset_log() { : > "$WORK/swaymsg.log"; }

# ── status before anything ────────────────────────────────────────────────────

assert_fail 'status exits non-zero when inactive' gatherd-tablet-mode status

# ── on ────────────────────────────────────────────────────────────────────────

reset_log
assert_ok 'on succeeds' gatherd-tablet-mode on
assert_out 'on rotates to portrait' 'normal' cat "$WORK/transform"
assert_ok 'on records the resting transform' test "$(cat "$XDG_RUNTIME_DIR/gatherd/tablet-mode")" = 90
assert_ok 'status exits zero when active' gatherd-tablet-mode status

if log_has 'input 1:1:AT_Translated_Set_2_keyboard events disabled'; then
    ok 'on disables the built-in keyboard'
else
    bad 'on disables the built-in keyboard'
fi
if log_has 'input type:touchpad events disabled'; then
    ok 'on disables the touchpad'
else
    bad 'on disables the touchpad'
fi
if log_has 'AirTurn'; then
    bad 'on leaves external keyboards alone'
else
    ok 'on leaves external keyboards alone'
fi

# ── on is idempotent ──────────────────────────────────────────────────────────

assert_ok 'on again succeeds' gatherd-tablet-mode on
assert_ok 'on again does not clobber the recorded transform' \
    test "$(cat "$XDG_RUNTIME_DIR/gatherd/tablet-mode")" = 90

# ── off ───────────────────────────────────────────────────────────────────────

reset_log
assert_ok 'off succeeds' gatherd-tablet-mode off
assert_out 'off restores the recorded 90, not a hardcoded normal' '90' cat "$WORK/transform"
assert_fail 'status exits non-zero after off' gatherd-tablet-mode status
if log_has 'input 1:1:AT_Translated_Set_2_keyboard events enabled'; then
    ok 'off re-enables the built-in keyboard'
else
    bad 'off re-enables the built-in keyboard'
fi

assert_ok 'off again is a no-op' gatherd-tablet-mode off

# ── toggle ────────────────────────────────────────────────────────────────────

assert_ok 'toggle turns on' gatherd-tablet-mode toggle
assert_out 'toggle rotated to portrait' 'normal' cat "$WORK/transform"
assert_ok 'toggle turns off' gatherd-tablet-mode toggle
assert_out 'toggle restored landscape' '90' cat "$WORK/transform"

# ── config file ───────────────────────────────────────────────────────────────

mkdir -p "$XDG_CONFIG_HOME/gatherd"
printf 'transform=180\n' > "$XDG_CONFIG_HOME/gatherd/tablet-mode.conf"
assert_ok 'on with config succeeds' gatherd-tablet-mode on
assert_out 'config file sets the transform' '180' cat "$WORK/transform"
gatherd-tablet-mode off >/dev/null 2>&1 || true

# ── bad usage ─────────────────────────────────────────────────────────────────

assert_fail 'unknown subcommand fails' gatherd-tablet-mode wibble

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

```bash
chmod +x tests/tablet-mode
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `tests/tablet-mode`
Expected: FAIL — every assertion errors because `gatherd-tablet-mode` does not exist yet (`sh: gatherd-tablet-mode: not found`), and the script exits non-zero.

- [ ] **Step 3: Write the implementation**

Create `scripts/gatherd-tablet-mode`:

```sh
#!/bin/sh
# Put the session into (or out of) tablet mode: rotate the internal panel to
# portrait and stop the built-in keyboard and touchpad from typing against
# whatever the folded machine is resting on.
#
# This is the only thing that touches sway state. The keybinding, the power
# button and (later) a hinge-angle daemon are all callers — which is what lets
# the trigger change without reopening the mechanism. See
# docs/superpowers/specs/2026-08-16-tablet-mode-design.md.
set -eu

state_dir="${XDG_RUNTIME_DIR:-/tmp}/gatherd"
state_file="$state_dir/tablet-mode"
config="${XDG_CONFIG_HOME:-$HOME/.config}/gatherd/tablet-mode.conf"

transform=normal
# shellcheck source=/dev/null
[ -r "$config" ] && . "$config"
transform="${GATHERD_TABLET_TRANSFORM:-$transform}"

# Matched by connector name rather than index because the resting transform is
# NOT necessarily "normal": where the panel is physically mounted rotated,
# wlroots applies the DRM panel-orientation quirk itself and upright landscape
# is transform 90. We record whatever we find and restore that.
internal_output() {
    swaymsg -t get_outputs \
        | jq -r 'first(.[] | select(.name | test("^(eDP|DSI|LVDS)")) | .name) // empty'
}

# Built-in keyboards only: the i8042 controller enumerates as 1:1:*. An external
# or Bluetooth keyboard has a real vendor:product id and must keep working while
# folded — a page-turner pedal presents as exactly that, and silencing it would
# defeat the point of using this at a piano.
builtin_keyboards() {
    swaymsg -t get_inputs \
        | jq -r '.[] | select(.type == "keyboard")
                     | select(.identifier | startswith("1:1:"))
                     | .identifier' \
        | sort -u
}

set_builtin_events() {
    for _id in $(builtin_keyboards); do
        swaymsg input "$_id" events "$1" >/dev/null
    done
    swaymsg input type:touchpad events "$1" >/dev/null
}

is_on() { [ -f "$state_file" ]; }

turn_on() {
    if is_on; then return 0; fi
    _output=$(internal_output)
    if [ -z "$_output" ]; then
        echo "gatherd-tablet-mode: no internal output found" >&2
        exit 1
    fi
    mkdir -p "$state_dir"
    # Written before rotating, so `off` restores the real resting transform.
    swaymsg -t get_outputs \
        | jq -r --arg o "$_output" 'first(.[] | select(.name == $o) | .transform)' \
        > "$state_file"
    swaymsg output "$_output" transform "$transform" >/dev/null
    set_builtin_events disabled
}

turn_off() {
    if ! is_on; then return 0; fi
    _output=$(internal_output)
    _prior=$(cat "$state_file")
    [ -n "$_prior" ] || _prior=normal
    if [ -n "$_output" ]; then
        swaymsg output "$_output" transform "$_prior" >/dev/null
    fi
    set_builtin_events enabled
    rm -f "$state_file"
}

case "${1:-toggle}" in
    on)     turn_on ;;
    off)    turn_off ;;
    toggle) if is_on; then turn_off; else turn_on; fi ;;
    status) is_on ;;
    *)      echo "usage: $0 on|off|toggle|status" >&2; exit 2 ;;
esac
```

```bash
chmod +x scripts/gatherd-tablet-mode
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `tests/tablet-mode`
Expected: `20 passed, 0 failed`, exit 0.

- [ ] **Step 5: Check shell style**

Run: `shellcheck scripts/gatherd-tablet-mode tests/tablet-mode`
Expected: no warnings. (`shellcheck` is already in `rest_packages`.)

- [ ] **Step 6: Commit**

```bash
git add scripts/gatherd-tablet-mode tests/tablet-mode
git commit -m "Add the tablet-mode mechanism

Rotates the internal panel to portrait and silences built-in input.
Restores the recorded resting transform rather than a hardcoded normal:
where the panel is mounted rotated, wlroots applies the DRM orientation
quirk itself and upright landscape is transform 90, so hardcoding would
leave the machine sideways.

Disables only i8042 (1:1:*) keyboards, so a Bluetooth page-turner pedal
keeps working while folded."
```

---

### Task 3: The forScore index decoder

**Files:**
- Create: `scripts/gatherd-music-index`
- Modify: `tests/tablet-mode`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `gatherd-music-index [--print]`. Writes `${XDG_STATE_HOME:-$HOME/.local/state}/gatherd/music-index.tsv` with `composer<TAB>title<TAB>filename` rows, one per PDF, **sorted by (composer, title)** — case-insensitively, which is what lets Task 4's picker read both levels straight off the file without re-sorting; `--print` writes to stdout instead. Reads `MUSIC_STAND_ROOT` (default `~/Documents/forscore`). Task 4 consumes this file.

- [ ] **Step 1: Write the failing test**

Append to `tests/tablet-mode`, immediately before the final `printf '\n%d passed...'` line:

```sh
# ── gatherd-music-index ───────────────────────────────────────────────────────

SCORES="$WORK/scores"
mkdir -p "$SCORES"
touch "$SCORES/2 Skazki, Op. 48.pdf" "$SCORES/12 Etudes, Op. 39.pdf" "$SCORES/Untitled.pdf"
# Non-PDF residue forScore leaves in its sync folder; must never be indexed.
touch "$SCORES/syncFolderState" "$SCORES/syncFolderLog"

# Build a synthetic backup in forScore's real container format: an ASCII header,
# then gzip, then a binary plist keyed "<filename>|<field>".
python3 - "$SCORES/Automatic Backup.4sb" <<'PY'
import gzip, plistlib, sys
payload = plistlib.dumps({
    "2 Skazki, Op. 48.pdf|composer": "Medtner",
    "2 Skazki, Op. 48.pdf|title": "Two Skazki",
    "12 Etudes, Op. 39.pdf|composer": "Alkan",
    "12 Etudes, Op. 39.pdf|title": "Twelve Etudes",
    "&SYS;lastLeftMenu": 0,
}, fmt=plistlib.FMT_BINARY)
with open(sys.argv[1], "wb") as f:
    f.write(b"<--4SBV02-->" + b" " * 68)
    f.write(gzip.compress(payload))
PY

MUSIC_STAND_ROOT="$SCORES"
XDG_STATE_HOME="$WORK/state"
export MUSIC_STAND_ROOT XDG_STATE_HOME

assert_out 'index maps composer, title and filename' \
    'Alkan	Twelve Etudes	12 Etudes, Op. 39.pdf
Medtner	Two Skazki	2 Skazki, Op. 48.pdf
Unknown	Untitled	Untitled.pdf' \
    gatherd-music-index --print

assert_ok 'index writes the TSV' gatherd-music-index
assert_ok 'index TSV exists' test -f "$XDG_STATE_HOME/gatherd/music-index.tsv"
assert_out 'index covers every PDF and nothing else' '3' \
    sh -c 'wc -l < "$XDG_STATE_HOME/gatherd/music-index.tsv" | tr -d " "'

# Graceful degradation: a missing or corrupt backup must still list the scores.
mv "$SCORES/Automatic Backup.4sb" "$WORK/backup.bak"
assert_out 'a missing backup still lists every score as Unknown' \
    'Unknown	12 Etudes, Op. 39	12 Etudes, Op. 39.pdf
Unknown	2 Skazki, Op. 48	2 Skazki, Op. 48.pdf
Unknown	Untitled	Untitled.pdf' \
    gatherd-music-index --print
printf 'not a backup' > "$SCORES/Automatic Backup.4sb"
assert_ok 'a corrupt backup does not crash' gatherd-music-index --print
mv "$WORK/backup.bak" "$SCORES/Automatic Backup.4sb"
```

Note: the expected-output blocks above contain **literal tab characters** between fields. Ensure your editor does not convert them to spaces.

- [ ] **Step 2: Run the test to verify it fails**

Run: `tests/tablet-mode`
Expected: the new `index …` assertions FAIL (`gatherd-music-index: not found`); the Task 2 assertions still pass.

- [ ] **Step 3: Write the implementation**

Create `scripts/gatherd-music-index`:

```python
#!/usr/bin/env python3
# Decode forScore's "Automatic Backup.4sb" into a composer/title/filename index.
#
# Composer lives nowhere else: the filenames carry only a work title
# ("2 Skazki, Op. 48.pdf") and the PDFs' own metadata is scanner residue. The
# backup is an ASCII header, then gzip, then an Apple binary plist keyed
# "<filename>|<field>" — both formats are Python stdlib, so this adds no
# packages and the feature stays CORE.
#
# The parse is isolated here on purpose. forScore's format is proprietary and
# may change; when it does the index goes stale rather than the picker breaking,
# and a score with no recoverable metadata still gets listed under "Unknown".
#
# See docs/superpowers/specs/2026-08-16-tablet-mode-design.md.

import os
import plistlib
import sys
import zlib

BACKUP = "Automatic Backup.4sb"
GZIP_MAGIC = b"\x1f\x8b"
FIELDS = ("composer", "title")


def default_root():
    return os.environ.get(
        "MUSIC_STAND_ROOT", os.path.expanduser("~/Documents/forscore")
    )


def index_path():
    state = os.environ.get(
        "XDG_STATE_HOME", os.path.expanduser("~/.local/state")
    )
    return os.path.join(state, "gatherd", "music-index.tsv")


def load_metadata(root):
    """Map filename -> {composer, title}. Empty on any failure: the index must
    degrade to a flat list rather than refuse to produce one."""
    try:
        with open(os.path.join(root, BACKUP), "rb") as handle:
            blob = handle.read()
        # Locate the payload by magic rather than a fixed offset, so a header
        # length change in a future forScore release does not break the parse.
        start = blob.find(GZIP_MAGIC)
        if start < 0:
            return {}
        plist = plistlib.loads(zlib.decompress(blob[start:], 47))
    except Exception:
        return {}

    meta = {}
    for key, value in plist.items():
        name, sep, field = key.rpartition("|")
        if not sep or field not in FIELDS or not isinstance(value, str):
            continue
        meta.setdefault(name, {})[field] = value
    return meta


def clean(text):
    # Tabs and newlines would corrupt the TSV that every consumer splits on.
    return " ".join(text.split())


def rows(root):
    meta = load_metadata(root)
    try:
        names = sorted(n for n in os.listdir(root) if n.lower().endswith(".pdf"))
    except OSError:
        return []
    out = []
    for name in names:
        entry = meta.get(name, {})
        composer = clean(entry.get("composer", "")) or "Unknown"
        title = clean(entry.get("title", "")) or name[:-4]
        out.append((composer, title, name))
    # Composer first so the picker's first level needs no re-sort.
    out.sort(key=lambda r: (r[0].lower(), r[1].lower()))
    return out


def main(argv):
    root = default_root()
    lines = ["\t".join(r) for r in rows(root)]
    body = "".join(line + "\n" for line in lines)

    if "--print" in argv[1:]:
        sys.stdout.write(body)
        return 0

    path = index_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.replace(tmp, path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

```bash
chmod +x scripts/gatherd-music-index
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `tests/tablet-mode`
Expected: all assertions pass, exit 0.

- [ ] **Step 5: Verify against the real library**

Run:

```bash
MUSIC_STAND_ROOT=~/Documents/forscore scripts/gatherd-music-index --print | wc -l
MUSIC_STAND_ROOT=~/Documents/forscore scripts/gatherd-music-index --print | cut -f1 | sort -u | wc -l
```

Expected: `98` and `28`. If either differs, the real backup diverges from the synthetic one — investigate before continuing.

- [ ] **Step 6: Commit**

```bash
git add scripts/gatherd-music-index tests/tablet-mode
git commit -m "Decode forScore's backup into a composer index

Composer is in neither the filenames nor the PDFs' metadata; it lives in
Automatic Backup.4sb, which is an ASCII header then gzip then an Apple
binary plist keyed '<filename>|<field>'. Both formats are Python stdlib,
so this stays CORE.

Isolated in its own script because the format is proprietary: when it
changes the index goes stale instead of the picker breaking, and scores
with no recoverable metadata still list under Unknown."
```

---

### Task 4: The music-stand picker

**Files:**
- Create: `scripts/gatherd-music-stand`
- Modify: `tests/tablet-mode`

**Interfaces:**
- Consumes: `gatherd-tablet-mode on|off` (Task 2); `gatherd-music-index` (Task 3) and its TSV.
- Produces: `gatherd-music-stand on|off|toggle`. MRU file `${XDG_STATE_HOME:-$HOME/.local/state}/gatherd/music-stand-scores` with `composer<TAB>title<TAB>filename` rows, newest first, deduped, capped at 20. Task 5 calls `gatherd-music-stand off`.

- [ ] **Step 1: Write the failing test**

Append to `tests/tablet-mode`, before the final `printf` summary line:

```sh
# ── gatherd-music-stand ───────────────────────────────────────────────────────

MUSIC_STAND_VIEWER=fakeviewer
export MUSIC_STAND_VIEWER
cat > "$FAKEBIN/fakeviewer" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >> '$WORK/viewer.log'
EOF
chmod +x "$FAKEBIN/fakeviewer"

# fuzzel replays one canned answer per invocation, so a two-level picker can be
# driven end to end.
cat > "$FAKEBIN/fuzzel" <<EOF
#!/bin/sh
WORK='$WORK'
cat >> "\$WORK/fuzzel.in"
printf -- '---\n' >> "\$WORK/fuzzel.in"
_n=\$(cat "\$WORK/fuzzel.turn" 2>/dev/null || echo 1)
printf '%s' \$((_n + 1)) > "\$WORK/fuzzel.turn"
sed -n "\${_n}p" "\$WORK/fuzzel.answers"
EOF
chmod +x "$FAKEBIN/fuzzel"

reset_picker() {
    : > "$WORK/fuzzel.in"
    : > "$WORK/viewer.log"
    printf '1' > "$WORK/fuzzel.turn"
    printf '%s\n' "$@" > "$WORK/fuzzel.answers"
}

rm -f "$XDG_STATE_HOME/gatherd/music-stand-scores"
reset_picker 'Medtner' 'Two Skazki'
assert_ok 'music-stand on succeeds' gatherd-music-stand on
assert_out 'the viewer opened the chosen score' "$SCORES/2 Skazki, Op. 48.pdf" \
    cat "$WORK/viewer.log"
assert_ok 'music-stand turned tablet mode on' gatherd-tablet-mode status
assert_out 'the pick was recorded in the MRU' \
    'Medtner	Two Skazki	2 Skazki, Op. 48.pdf' \
    cat "$XDG_STATE_HOME/gatherd/music-stand-scores"

# Level 1 offers composers, not scores; level 2 offers that composer's scores.
if grep -q '^Alkan$' "$WORK/fuzzel.in" && grep -q '^Medtner$' "$WORK/fuzzel.in"; then
    ok 'level 1 lists composers'
else
    bad 'level 1 lists composers'
fi
if grep -q '^Two Skazki$' "$WORK/fuzzel.in"; then
    ok 'level 2 lists that composer titles'
else
    bad 'level 2 lists that composer titles'
fi
if grep -q 'Twelve Etudes' "$WORK/fuzzel.in"; then
    bad 'level 2 excludes other composers'
else
    ok 'level 2 excludes other composers'
fi

assert_ok 'music-stand off succeeds' gatherd-music-stand off
assert_fail 'music-stand off left tablet mode off' gatherd-tablet-mode status

# MRU ordering: the most recently played composer must lead level 1.
reset_picker 'Alkan' 'Twelve Etudes'
assert_ok 'second pick succeeds' gatherd-music-stand on
gatherd-music-stand off >/dev/null 2>&1 || true
assert_out 'most recent composer leads the MRU' 'Alkan' \
    sh -c 'head -1 "$XDG_STATE_HOME/gatherd/music-stand-scores" | cut -f1'
assert_out 'level 1 offers the most recent composer first' 'Alkan' \
    sh -c 'head -1 "'"$WORK"'/fuzzel.in"'
assert_out 'the MRU holds both picks without duplicates' '2' \
    sh -c 'wc -l < "$XDG_STATE_HOME/gatherd/music-stand-scores" | tr -d " "'

# Cancelling must not rotate the screen or open anything.
reset_picker ''
assert_ok 'cancelling at level 1 exits cleanly' gatherd-music-stand on
assert_fail 'cancelling left tablet mode off' gatherd-tablet-mode status
assert_out 'cancelling opened nothing' '' cat "$WORK/viewer.log"

# Back at level 2 returns to level 1 rather than opening a score.
reset_picker 'Medtner' '‹ Back' 'Alkan' 'Twelve Etudes'
assert_ok 'back at level 2 returns to level 1' gatherd-music-stand on
assert_out 'after going back, the second choice opened' "$SCORES/12 Etudes, Op. 39.pdf" \
    cat "$WORK/viewer.log"
gatherd-music-stand off >/dev/null 2>&1 || true
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `tests/tablet-mode`
Expected: the `music-stand …` assertions FAIL (`gatherd-music-stand: not found`); Tasks 2 and 3 assertions still pass.

- [ ] **Step 3: Write the implementation**

Create `scripts/gatherd-music-stand`:

```sh
#!/bin/sh
# Read sheet music at the piano: tablet mode, then pick a score by composer and
# open it fullscreen.
#
# The picker is progressive because there is no keyboard in tablet mode and so
# no type-to-filter — one flat list of every score is a long finger-scroll,
# whereas composer-then-score is two short lists, and MRU ordering makes the
# common case two taps with no scrolling at all.
#
# See docs/superpowers/specs/2026-08-16-tablet-mode-design.md.
set -eu

config="${XDG_CONFIG_HOME:-$HOME/.config}/gatherd/tablet-mode.conf"
root="$HOME/Documents/forscore"
viewer=papers
# shellcheck source=/dev/null
[ -r "$config" ] && . "$config"
root="${MUSIC_STAND_ROOT:-$root}"
viewer="${MUSIC_STAND_VIEWER:-$viewer}"

state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/gatherd"
index="$state_dir/music-index.tsv"
mru="$state_dir/music-stand-scores"
max_mru=20
back='‹ Back'

# fuzzel entries are the touch targets here, so they are deliberately taller and
# wider than the launcher's defaults.
pick() {
    fuzzel --dmenu --prompt "$1" --lines 12 --width 40 || true
}

# Regenerate whenever forScore's backup is newer than the index. A stat
# comparison keeps this self-maintaining: no cron, no manual refresh step.
refresh_index() {
    _backup="$root/Automatic Backup.4sb"
    if [ ! -f "$index" ] || { [ -f "$_backup" ] && [ "$_backup" -nt "$index" ]; }; then
        MUSIC_STAND_ROOT="$root" gatherd-music-index || true
    fi
}

# Most-recently-played first, then everything else. awk dedupes in one pass and
# preserves first-seen order, so the MRU head wins without a second sort.
composers() {
    { [ -r "$mru" ] && cut -f1 "$mru"; cut -f1 "$index"; } 2>/dev/null \
        | awk 'NF && !seen[$0]++'
}

titles_for() {
    { [ -r "$mru" ] && awk -F'\t' -v c="$1" '$1 == c { print $2 }' "$mru"
      awk -F'\t' -v c="$1" '$1 == c { print $2 }' "$index"; } 2>/dev/null \
        | awk 'NF && !seen[$0]++'
}

file_for() {
    awk -F'\t' -v c="$1" -v t="$2" '$1 == c && $2 == t { print $3; exit }' "$index"
}

remember() {
    mkdir -p "$state_dir" 2>/dev/null || return 0
    { printf '%s\t%s\t%s\n' "$1" "$2" "$3"
      [ -r "$mru" ] && cat "$mru"; } 2>/dev/null \
        | awk 'NF && !seen[$0]++' | head -n "$max_mru" > "$mru.tmp" \
        && mv "$mru.tmp" "$mru"
}

turn_on() {
    refresh_index
    [ -s "$index" ] || { echo "gatherd-music-stand: no scores indexed" >&2; exit 1; }

    while :; do
        composer=$(composers | pick 'composer: ')
        [ -n "$composer" ] || exit 0

        title=$( { titles_for "$composer"; printf '%s\n' "$back"; } | pick 'score: ')
        [ -n "$title" ] || exit 0
        [ "$title" = "$back" ] || break
    done

    file=$(file_for "$composer" "$title")
    [ -n "$file" ] || { echo "gatherd-music-stand: no file for $title" >&2; exit 1; }

    remember "$composer" "$title" "$file"
    gatherd-tablet-mode on
    # Fullscreen and idle inhibition are sway for_window rules, not flags here:
    # setting them declaratively avoids racing the viewer's own startup.
    "$viewer" "$root/$file" >/dev/null 2>&1 &
}

turn_off() {
    # The viewer is left running: closing a document the human may still want is
    # not this script's business.
    gatherd-tablet-mode off
}

case "${1:-toggle}" in
    on)     turn_on ;;
    off)    turn_off ;;
    toggle) if gatherd-tablet-mode status; then turn_off; else turn_on; fi ;;
    *)      echo "usage: $0 on|off|toggle" >&2; exit 2 ;;
esac
```

```bash
chmod +x scripts/gatherd-music-stand
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `tests/tablet-mode`
Expected: all assertions pass, exit 0.

- [ ] **Step 5: Check shell style**

Run: `shellcheck scripts/gatherd-music-stand`
Expected: no warnings.

- [ ] **Step 6: Commit**

```bash
git add scripts/gatherd-music-stand tests/tablet-mode
git commit -m "Add the composer-then-score music stand picker

Progressive because tablet mode has no keyboard and therefore no
type-to-filter: one flat list of 98 scores is a long finger-scroll, while
composer-then-score is two short lists and MRU ordering makes the common
case two taps.

One MRU file serves both levels, so they cannot disagree."
```

---

### Task 5: The power-button escape hatch

**Files:**
- Create: `scripts/gatherd-power-button`
- Modify: `tests/tablet-mode`

**Interfaces:**
- Consumes: `gatherd-tablet-mode status|off` (Task 2), `gatherd-music-stand off` (Task 4).
- Produces: `gatherd-power-button`, taking no arguments. Execs `$HOME/.config/sway/scripts/power_menu.sh` when not in tablet mode. Task 6 binds `XF86PowerOff` to it.

- [ ] **Step 1: Write the failing test**

Append to `tests/tablet-mode`, before the final `printf` summary:

```sh
# ── gatherd-power-button ──────────────────────────────────────────────────────

mkdir -p "$WORK/home/.config/sway/scripts"
HOME="$WORK/home"
export HOME
cat > "$HOME/.config/sway/scripts/power_menu.sh" <<EOF
#!/bin/sh
printf 'power_menu\n' >> '$WORK/powermenu.log'
EOF
chmod +x "$HOME/.config/sway/scripts/power_menu.sh"

: > "$WORK/powermenu.log"
gatherd-tablet-mode off >/dev/null 2>&1 || true
reset_picker ''
assert_ok 'power button works in laptop mode' gatherd-power-button
assert_out 'laptop mode goes straight to the power menu' 'power_menu' \
    cat "$WORK/powermenu.log"
assert_out 'laptop mode shows no tablet menu' '' cat "$WORK/fuzzel.in"

# In tablet mode the button must offer a touch escape instead.
gatherd-tablet-mode on >/dev/null 2>&1
: > "$WORK/powermenu.log"
reset_picker 'Exit tablet mode'
assert_ok 'power button works in tablet mode' gatherd-power-button
assert_fail 'exit tablet mode left tablet mode off' gatherd-tablet-mode status
assert_out 'tablet mode did not open the power menu' '' cat "$WORK/powermenu.log"

# Power… must still reach the real menu, one tap deeper.
gatherd-tablet-mode on >/dev/null 2>&1
: > "$WORK/powermenu.log"
reset_picker 'Power…'
assert_ok 'power button chains to the power menu' gatherd-power-button
assert_out 'Power… reaches the real power menu' 'power_menu' cat "$WORK/powermenu.log"
gatherd-tablet-mode off >/dev/null 2>&1 || true
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `tests/tablet-mode`
Expected: the `power button …` assertions FAIL (`gatherd-power-button: not found`).

- [ ] **Step 3: Write the implementation**

Create `scripts/gatherd-power-button`:

```sh
#!/bin/sh
# Dispatch the power button on tablet state.
#
# The power button is on an edge of the chassis and stays reachable when the
# machine is folded, which makes it the only usable escape hatch once the
# built-in keyboard is disabled. Unfolded, this is transparent: it execs the
# stock EndeavourOS power menu unchanged, so behaviour on every other machine
# and in every other pose is untouched.
#
# See docs/superpowers/specs/2026-08-16-tablet-mode-design.md.
set -eu

powermenu="$HOME/.config/sway/scripts/power_menu.sh"

if ! gatherd-tablet-mode status; then
    exec "$powermenu"
fi

selection=$(printf '%s\n' \
    '󰊓 Exit tablet mode' \
    '󰎈 Exit music stand' \
    '󰐥 Power…' \
    | fuzzel --dmenu --prompt 'tablet: ' --lines 3 --width 24) || exit 0

case "$selection" in
    *'Exit tablet mode'*) gatherd-tablet-mode off ;;
    *'Exit music stand'*) gatherd-music-stand off ;;
    *'Power'*)            exec "$powermenu" ;;
esac
```

```bash
chmod +x scripts/gatherd-power-button
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `tests/tablet-mode`
Expected: all assertions pass, exit 0.

- [ ] **Step 5: Check shell style**

Run: `shellcheck scripts/gatherd-power-button`
Expected: no warnings.

- [ ] **Step 6: Commit**

```bash
git add scripts/gatherd-power-button tests/tablet-mode
git commit -m "Add the power-button escape hatch

The edge power button is the only control still reachable once the
built-in keyboard is disabled, so it dispatches on tablet state: the stock
power menu unchanged when unfolded, a touch exit menu when folded."
```

---

### Task 6: Install and wire it up

**Files:**
- Create: `roles/desktop/templates/tablet-mode.conf.j2`
- Create: `roles/desktop/tasks/tablet_mode.yml`
- Modify: `roles/desktop/tasks/core.yml` (the `Add XF86PowerOff binding to sway config` task at ~line 115, and the end of the file)
- Modify: `group_vars/all/main.yml`

**Interfaces:**
- Consumes: `has_touchscreen`, `has_accelerometer` (Task 1); all four scripts (Tasks 2–5).
- Produces: installed scripts in `~/.local/bin/`, config at `~/.config/gatherd/tablet-mode.conf`, sway bindings and `for_window` rules, and the var `tablet_mode_supported`.

- [ ] **Step 1: Add the variables**

In `group_vars/all/main.yml`, add near the `icloud_*` block (keep the comment — it carries the non-obvious part):

```yaml
# Tablet mode. Gated on capability rather than model: DMI is useless here, since
# the MiniBook X reports chassis_type 10 (Notebook), not 31 (Convertible).
tablet_mode_supported: "{{ has_touchscreen | default(false) and has_accelerometer | default(false) }}"
# Portrait. NOT 90: where the panel is physically mounted rotated, wlroots
# applies the DRM orientation quirk itself and 90 is upright landscape. Use 180
# if the fold puts the wrong edge at the top.
tablet_mode_transform: normal
music_stand_root: "{{ target_home }}/Documents/forscore"
music_stand_viewer: papers
music_stand_app_id: org.gnome.Papers
```

- [ ] **Step 2: Add the viewer package**

In `group_vars/all/main.yml`, add to `rest_packages` under a fitting comment group:

```yaml
  # sheet music / PDF reading in tablet mode
  - papers
```

- [ ] **Step 3: Create the config template**

Create `roles/desktop/templates/tablet-mode.conf.j2`:

```sh
# Managed by gatherd. Sourced by gatherd-tablet-mode and gatherd-music-stand.
transform={{ tablet_mode_transform }}
root={{ music_stand_root }}
viewer={{ music_stand_viewer }}
```

- [ ] **Step 4: Create the install task file**

Create `roles/desktop/tasks/tablet_mode.yml`:

```yaml
---
- name: Install the tablet-mode scripts
  ansible.builtin.copy:
    src: "{{ setup_dir }}/scripts/{{ item }}"
    dest: "{{ target_home }}/.local/bin/{{ item }}"
    mode: '0755'
    remote_src: true
  loop:
    - gatherd-tablet-mode
    - gatherd-music-index
    - gatherd-music-stand
    - gatherd-power-button

- name: Configure tablet mode
  ansible.builtin.template:
    src: tablet-mode.conf.j2
    dest: "{{ target_home }}/.config/gatherd/tablet-mode.conf"
    mode: '0644'

# `binding`, not `keys`: Jinja2 resolves item.keys to the dict's built-in
# keys() method rather than the value, which fails silently and confusingly.
- name: Bind tablet mode and music stand in sway
  ansible.builtin.lineinfile:
    path: "{{ target_home }}/.config/sway/config.d/default"
    line: "bindsym {{ item.binding }} exec {{ target_home }}/.local/bin/{{ item.script }} toggle"
    regexp: "^\\s*bindsym\\s+{{ item.binding | regex_escape }}\\s"
  loop:
    - binding: $mod+t
      script: gatherd-tablet-mode
    - binding: $mod+Shift+t
      script: gatherd-music-stand

# Declarative rather than flags passed at launch: setting fullscreen and idle
# inhibition as window rules avoids racing the viewer's own startup, and the
# inhibitor cannot leak because sway drops it when the window stops being
# fullscreen.
- name: Keep the score fullscreen and the screen awake
  ansible.builtin.blockinfile:
    path: "{{ target_home }}/.config/sway/config.d/default"
    marker: "# {mark} ANSIBLE MANAGED BLOCK: music stand"
    block: |
      for_window [app_id="{{ music_stand_app_id }}"] fullscreen enable
      for_window [app_id="{{ music_stand_app_id }}"] inhibit_idle fullscreen
```

- [ ] **Step 5: Make the power-button binding conditional**

In `roles/desktop/tasks/core.yml`, replace the existing `Add XF86PowerOff binding to sway config` task (at ~line 115) with:

```yaml
# On a convertible the power button is the only control still reachable once the
# built-in keyboard is disabled, so it routes through our dispatcher there. On
# every other machine it stays bound to the stock menu.
- name: Add XF86PowerOff binding to sway config
  ansible.builtin.lineinfile:
    path: "{{ target_home }}/.config/sway/config.d/default"
    line: >-
      bindsym XF86PowerOff exec
      {{ (target_home ~ '/.local/bin/gatherd-power-button')
         if tablet_mode_supported else '$powermenu' }}
    regexp: '^\s*bindsym\s+XF86PowerOff\b'
```

- [ ] **Step 6: Import the task file**

At the end of `roles/desktop/tasks/core.yml`, after the `Configure the Remmina VNC-over-SSH launcher` task, add:

```yaml
- name: Configure tablet mode
  ansible.builtin.import_tasks: tablet_mode.yml
  when: tablet_mode_supported
```

- [ ] **Step 7: Lint**

Run: `ansible-lint`
Expected: no new findings. Fix any rather than adding `noqa`.

- [ ] **Step 8: Verify the package tier check still passes**

Run: `scripts/gatherd-check-package-tiers .`
Expected: exit `0`. Confirm with `echo $?`. `core_packages` must still be `[]`.

- [ ] **Step 9: Commit**

```bash
git add group_vars/all/main.yml roles/desktop/tasks/tablet_mode.yml \
        roles/desktop/tasks/core.yml roles/desktop/templates/tablet-mode.conf.j2
git commit -m "Install and wire up tablet mode

Everything but the papers package is CORE: scripts and config only, so
the mechanism converges with no network and xreader remains a zero-cost
fallback if the viewer never arrives.

Fullscreen and idle inhibition are sway window rules rather than launch
flags, so they cannot race the viewer's startup and the inhibitor cannot
leak."
```

---

### Task 7: Verification steps

**Files:**
- Modify: `scripts/gatherd-post-setup-notes`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: two `li` entries in `section_verify`.

- [ ] **Step 1: Add the verify items**

In `scripts/gatherd-post-setup-notes`, inside `section_verify()`, after the `iCloud unlock trigger` line, add:

```sh
    li 'Tablet mode rotates and silences built-in input: `gatherd-tablet-mode status; echo $?` prints `1`. Then `gatherd-tablet-mode on` and `swaymsg -t get_outputs | jq -r ".[0] | \"\(.transform) \(.rect.width)x\(.rect.height)\""` prints a portrait size (`normal 857x1371` on the MiniBook X — NOT `90`, which is upright landscape on a rotated panel); `swaymsg -t get_inputs | jq -r ".[] | select(.identifier | startswith(\"1:1:\")) | .libinput.send_events"` prints `disabled`. `gatherd-tablet-mode off` restores the original transform and prints `enabled`. Touch the screen while rotated and confirm the pointer lands under your finger.'
    li 'Music stand picks by composer, then score: `gatherd-music-index && cut -f1 ~/.local/state/gatherd/music-index.tsv | sort -u | wc -l` prints a non-zero composer count, and `wc -l < ~/.local/state/gatherd/music-index.tsv` equals `ls ~/Documents/forscore/*.pdf | wc -l`. `gatherd-music-stand on` offers composers, then that composer'"'"'s scores, and opens the pick fullscreen with the screen no longer blanking; the edge power button then offers `Exit tablet mode`.'
```

- [ ] **Step 2: Verify the notes still render**

Run: `scripts/gatherd-post-setup-notes --help 2>/dev/null || sh -n scripts/gatherd-post-setup-notes`
Expected: `sh -n` reports no syntax error (exit 0). Quoting inside those `li` strings is the likely failure — the second entry deliberately breaks out of single quotes to embed an apostrophe.

- [ ] **Step 3: Count the verify items**

Run: `awk '/^section_verify/,/^}/' scripts/gatherd-post-setup-notes | grep -c "^    li "`
Expected: `11`.

Per `CLAUDE.md`, more than ten verify items is the signal to repave. Report this to the human rather than acting on it: the count is now 11, so a repave and a run through the checklist is due.

- [ ] **Step 4: Commit**

```bash
git add scripts/gatherd-post-setup-notes
git commit -m "Add tablet mode and music stand verify steps

Both are runnable command sequences with expected output. The transform
check spells out that portrait is 'normal' and 90 is upright landscape,
because the rotated panel inverts the intuition."
```

---

## Deferred to phase 2

Not in this plan, tracked in the spec: the udev rule binding the second accelerometer at boot, the hinge-angle daemon (signed rotation about the `y` axis, magnitude filtering, degenerate-pose state holding), and auto-rotation. The `LTSM` firmware path has its own deferral section in the spec.

## Manual check after execution

The plan cannot settle one thing mechanically: whether `normal` or `180` puts the score right-side-up when the machine is actually folded. Fold it, look at it, and if it is upside down set `tablet_mode_transform: 180` in `group_vars/all/main.yml` and re-converge.
