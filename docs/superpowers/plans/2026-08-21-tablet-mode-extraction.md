# Tablet Mode Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the tablet-mode mechanism out of gatherd into a standalone
`chuwi-minibook-tablet-mode` repo with history preserved, and have gatherd
consume it at a pinned tag.

**Architecture:** `git filter-repo` reduces a scratch clone of gatherd to the
mechanism's files, then rewrites `gatherd-*` to `minibook-*` across blobs and
messages. The new repo installs via a POSIX `install.sh`. gatherd gains a role
that clones it at a pinned tag, runs the installer, and templates the config —
including the folded-menu entries that used to be hardcoded.

**Tech Stack:** POSIX sh, Python 3 (stdlib only), Ansible, git-filter-repo, jq,
sway.

## Global Constraints

- **The machine must keep working throughout.** gatherd is not modified at all
  until Task 7. Tasks 1–6 only create files elsewhere.
- **No repave available this week.** Verification is `tests/tablet-mode`, a
  converge, and manual checks — never "a repave will catch it".
- Commands are prefixed `minibook-`; the repo is `chuwi-minibook-tablet-mode`.
- Config lives at `$XDG_CONFIG_HOME/minibook-tablet-mode/config`; key names
  unchanged from `tablet-mode.conf`.
- Folded-menu entries live in a **separate** file,
  `$XDG_CONFIG_HOME/minibook-tablet-mode/menu`, one `label|command` per line,
  split on the FIRST `|` only, `#` and blank lines ignored. They cannot live in
  `config`: that file is shell-sourced `key=value`, so repeated keys would
  overwrite each other.
- Runtime dependencies stay: sh, python3 stdlib, jq, fuzzel, setsid, swaymsg.
  Do not add any.
- Every script keeps its existing comments verbatim except where a name
  changes. The comments carry the measurements and the reasoning.
- `git filter-repo` operates ONLY on a scratch clone under `/tmp`. Never run it
  against `/home/schmonz/.autofs-mounts/code/trees/gatherd`.
- **The new repo lives on LOCAL disk: `/home/schmonz/src/`.** `~/trees` and
  `~/.autofs-mounts` are the same NFS mount, reached over Tailscale at 131ms
  RTT with packet loss; `git status` there takes 47 seconds against 0.00s
  locally. `/tmp` is tmpfs, so work in progress there does not survive a
  reboot — Task 6 moves it to local disk promptly for that reason.
- The human creates the GitHub repo and pushes. Do not create remotes, do not
  push.

---

### Task 1: Scratch clone and filter-repo down to the mechanism

**Files:**
- Create: `/tmp/extract/chuwi-minibook-tablet-mode` (working area)

**Interfaces:**
- Produces: a git repo whose history contains only the mechanism's files, still
  under their gatherd paths and names.

- [ ] **Step 1: Install git-filter-repo**

```bash
sudo -A pacman -S --needed --noconfirm git-filter-repo
git filter-repo --version
```

Expected: a version number (2.47.0 or newer).

- [ ] **Step 2: Make the scratch clone**

```bash
rm -rf /tmp/extract && mkdir -p /tmp/extract
git clone /home/schmonz/.autofs-mounts/code/trees/gatherd \
    /tmp/extract/chuwi-minibook-tablet-mode
cd /tmp/extract/chuwi-minibook-tablet-mode
git log --oneline | wc -l
```

Expected: a commit count in the hundreds. Record it; Step 4 compares against it.

- [ ] **Step 3: Filter to the mechanism's paths**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
git filter-repo --force \
  --path scripts/gatherd-compositor \
  --path scripts/gatherd-tablet-mode \
  --path scripts/gatherd-hinge-daemon \
  --path scripts/gatherd-power-button \
  --path scripts/gatherd-bind-hinge-sensor \
  --path services/system/gatherd-hinge-sensor.service \
  --path tests/tablet-mode \
  --path docs/superpowers/specs/2026-08-16-tablet-mode-design.md
```

- [ ] **Step 4: Verify the filter kept history and dropped everything else**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
git ls-files
git log --oneline | wc -l
git log --oneline -- scripts/gatherd-hinge-daemon | wc -l
```

Expected: exactly the eight paths listed above and nothing else; a commit count
smaller than Step 2's but greater than 20; at least 10 commits touching the
daemon. If the daemon shows 0 commits, the filter is wrong — stop and fix
before continuing.

- [ ] **Step 5: Verify the reasoning survived**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
git log --oneline | grep -ci "rotation\|calibrat\|noise\|threshold"
git log --all --format=%B | grep -c "267"
```

Expected: several matches for the first, at least one for the second. This is
the check that history preservation actually bought what it was for.

---

### Task 2: Move files into the new layout

**Files:**
- Modify (rename): all eight paths from Task 1

**Interfaces:**
- Consumes: the filtered repo from Task 1.
- Produces: `bin/`, `systemd/`, `tests/`, `docs/` layout with `minibook-*`
  command names.

- [ ] **Step 1: Create the layout and move the files**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
mkdir -p bin systemd etc docs
git mv scripts/gatherd-compositor          bin/minibook-compositor
git mv scripts/gatherd-tablet-mode         bin/minibook-tablet-mode
git mv scripts/gatherd-hinge-daemon        bin/minibook-hinge-daemon
git mv scripts/gatherd-power-button        bin/minibook-power-button
git mv scripts/gatherd-bind-hinge-sensor   bin/minibook-bind-hinge-sensor
git mv services/system/gatherd-hinge-sensor.service \
       systemd/minibook-hinge-sensor.service
git mv docs/superpowers/specs/2026-08-16-tablet-mode-design.md docs/design.md
rmdir -p scripts services/system docs/superpowers/specs 2>/dev/null || true
```

- [ ] **Step 2: Verify the tree**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode && git status --short && git ls-files
```

Expected: five files under `bin/`, one under `systemd/`, `tests/tablet-mode`,
`docs/design.md`. No `scripts/` or `services/` directories remain.

- [ ] **Step 3: Commit the move**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
git add -A
git commit -m "Move into the standalone layout

bin/ for the commands, systemd/ for the unit, docs/ for the design. The
gatherd- prefix is corrected in the following commit, which rewrites it
across all of history rather than only here."
```

---

### Task 3: Rewrite gatherd-* to minibook-* across all history

**Files:**
- Modify: every file, every commit message

**Interfaces:**
- Produces: a repo where no blob or message says `gatherd-tablet-mode`,
  `gatherd-hinge-daemon`, `gatherd-power-button`, `gatherd-compositor` or
  `gatherd-bind-hinge-sensor`.

- [ ] **Step 1: Write the replacement rules**

```bash
cat > /tmp/extract/replacements.txt <<'EOF'
gatherd-tablet-mode==>minibook-tablet-mode
gatherd-hinge-daemon==>minibook-hinge-daemon
gatherd-power-button==>minibook-power-button
gatherd-compositor==>minibook-compositor
gatherd-bind-hinge-sensor==>minibook-bind-hinge-sensor
gatherd-hinge-sensor.service==>minibook-hinge-sensor.service
GATHERD_HINGE_==>MINIBOOK_HINGE_
GATHERD_TABLET_==>MINIBOOK_TABLET_
EOF
```

Note: the trailing entries cover the env-var overrides
(`GATHERD_HINGE_ENTER`, `GATHERD_HINGE_EXIT`, `GATHERD_HINGE_POLL_INTERVAL`,
`GATHERD_HINGE_POLL_INTERVAL_IDLE`, `GATHERD_HINGE_MOTION_*`,
`GATHERD_HINGE_ROTATION_REFERENCE`, `GATHERD_HINGE_LID_DEVICE`,
`GATHERD_HINGE_BASE_DEVICE`, `GATHERD_HINGE_LID_STATE`,
`GATHERD_TABLET_TRANSFORM`), which the tests set and the daemon reads.

- [ ] **Step 2: Apply it across history**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
git filter-repo --force --replace-text /tmp/extract/replacements.txt
```

- [ ] **Step 3: Verify no old names survive anywhere**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
git grep -l 'gatherd-tablet-mode\|gatherd-hinge-daemon\|gatherd-power-button\|gatherd-compositor\|gatherd-bind-hinge-sensor' $(git rev-list --all) | head
git log --all --format=%B | grep -c 'gatherd-tablet-mode' || true
```

Expected: no output from the first command, `0` from the second.

- [ ] **Step 4: Verify the daemon's env overrides were renamed consistently**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
grep -c 'MINIBOOK_HINGE_' bin/minibook-hinge-daemon
grep -c 'GATHERD_' bin/minibook-hinge-daemon tests/tablet-mode || true
```

Expected: a non-zero count of `MINIBOOK_HINGE_`; zero `GATHERD_` anywhere.

---

### Task 4: Fix the paths the tests use, and get the suite green

**Files:**
- Modify: `tests/tablet-mode` (14 references to `$REPO/scripts`)

**Interfaces:**
- Consumes: the renamed repo from Task 3.
- Produces: a passing suite in the new layout — the proof that the extraction
  changed nothing behavioural.

- [ ] **Step 1: Run the suite and watch it fail**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode && ./tests/tablet-mode 2>&1 | tail -5
```

Expected: failures, because the suite still looks for the commands in
`$REPO/scripts` which no longer exists.

- [ ] **Step 2: Point the suite at bin/**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
sed -i 's|\$REPO/scripts|$REPO/bin|g' tests/tablet-mode
grep -c '\$REPO/bin' tests/tablet-mode
```

Expected: `14`.

- [ ] **Step 3: Fix the boundary assertion's script list**

The loop that asserts no script reaches past the adapter still names the
music-stand and music-index scripts, which did not move. Replace that list:

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
python3 - <<'PY'
p = "tests/tablet-mode"
s = open(p).read()
old = """for _script in minibook-tablet-mode minibook-power-button gatherd-music-stand \\
               gatherd-music-index minibook-hinge-daemon; do"""
new = """for _script in minibook-tablet-mode minibook-power-button \\
               minibook-bind-hinge-sensor minibook-hinge-daemon; do"""
assert old in s, "boundary loop not found - inspect it by hand"
open(p, "w").write(s.replace(old, new, 1))
print("boundary loop updated")
PY
```

- [ ] **Step 4: Remove the music-stand tests**

`gatherd-music-stand` and `gatherd-music-index` did not move, so every
assertion about picking scores, the MRU, the viewer pid file and the `.4sb`
index belongs to gatherd, not here. Delete those sections. Identify them by
their banner comments:

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
grep -n '^# ── ' tests/tablet-mode
```

Delete exactly these eight sections, each running from its banner to the line
before the next banner:

| Line (at time of writing) | Banner |
| --- | --- |
| 309 | `gatherd-music-index` |
| 435 | `gatherd-music-stand` |
| 601 | `Exit music stand stops the viewer it started` |
| 718 | `gatherd-music-stand: cancel escape` |
| 766 | `gatherd-music-stand: viewer preflight` |
| 794 | `gatherd-music-stand: stale MRU rows` |
| 857 | `gatherd-music-stand: viewer flag` |
| 879 | `gatherd-music-stand: touch target font` |

Delete with them the fixtures that exist only for those sections: `$SCORES`
and the score files it creates, the `fakeviewer` heredoc, `VIEWER_LOG`,
`VIEWER_CHILD`, `viewer_log()`, and the `MUSIC_STAND_*` environment exports.
KEEP `reset_picker()` and the `fuzzel` fake — the folded-menu tests use both.

Keep every other section. In particular keep `the score fills the screen while
folded` and `a score opened while already folded still fills the screen`: those
test `minibook-tablet-mode`'s fullscreen behaviour, not the music stand, and
they only need a window with the configured app_id to exist in the fake tree.
Their calls to `gatherd-music-stand on` must become the configured-entry
mechanism from Task 5, or be reduced to calling
`minibook-tablet-mode fullscreen-viewer` directly.

- [ ] **Step 5: Run the suite until green**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode && ./tests/tablet-mode 2>&1 | tail -3
```

Expected: `N passed, 0 failed`, where N is smaller than 297 because the
music-stand assertions are gone. Record N.

- [ ] **Step 6: Prove the suite still catches a real regression**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
cp bin/minibook-tablet-mode /tmp/extract/tm.bak
sed -i 's|^    gatherd-compositor restore-all-input$|    true|; s|^    minibook-compositor restore-all-input$|    true|' bin/minibook-tablet-mode
./tests/tablet-mode 2>&1 | grep -E "^FAIL|passed," | head -3
cp /tmp/extract/tm.bak bin/minibook-tablet-mode
./tests/tablet-mode 2>&1 | tail -1
```

Expected: failures with the mutation (including the re-enable assertions),
then green again. A suite that stays green here has been broken by the move.

- [ ] **Step 7: Commit**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
git add -A
git commit -m "Point the suite at bin/ and drop the music-stand assertions

The sheet-music application stayed in gatherd, so its tests go with it. What
remains covers the mechanism: the compositor boundary, fold detection,
rotation, input suppression and the escape menu."
```

---

### Task 5: Config-driven folded menu

**Files:**
- Modify: `bin/minibook-power-button`
- Modify: `tests/tablet-mode`
- Create: `etc/config.example`
- Create: `etc/menu.example`

**Interfaces:**
- Consumes: the green suite from Task 4.
- Produces: a menu that reads entries from
  `$XDG_CONFIG_HOME/minibook-tablet-mode/menu`, so the mechanism no longer
  names any particular application.

- [ ] **Step 1: Write the failing tests**

Add to `tests/tablet-mode`, before the `# ── gatherd-power-button` section
(rename that banner to `minibook-power-button` if Task 3 did not):

```sh
# ── the folded menu's entries come from configuration ────────────────────────
# The mechanism must not name any particular application. gatherd supplies its
# music-stand entries this way; a stranger supplies whatever they read.

printf 'viewer_app_id=luajit\n' > "$XDG_CONFIG_HOME/minibook-tablet-mode/config"
printf '%s\n' '󰈙 Open a thing|touch "$WORK/entry-ran"' \
    > "$XDG_CONFIG_HOME/minibook-tablet-mode/menu"
minibook-tablet-mode on >/dev/null 2>&1
rm -f "$WORK/entry-ran"
reset_picker '󰈙 Open a thing'
assert_ok 'the power button works with configured entries' minibook-power-button
if grep -q 'Open a thing' "$WORK/fuzzel.in"; then
    ok 'a configured entry appears in the folded menu'
else
    bad 'a configured entry appears in the folded menu'
fi
assert_ok 'choosing a configured entry runs its command' test -f "$WORK/entry-ran"

# A command containing a pipe must survive: entries split on the FIRST | only.
printf '%s\n' 'Piped|sh -c "echo a | cat > $WORK/piped"' \
    > "$XDG_CONFIG_HOME/minibook-tablet-mode/menu"
rm -f "$WORK/piped"
reset_picker 'Piped'
assert_ok 'an entry whose command contains a pipe works' minibook-power-button
assert_ok 'the command after the first pipe ran intact' test -s "$WORK/piped"

# Built-in entries are properties of the mechanism, not of any application.
: > "$XDG_CONFIG_HOME/minibook-tablet-mode/menu"
reset_picker 'Cancel'
assert_ok 'the menu works with no configured entries at all' minibook-power-button
if grep -q 'Cancel' "$WORK/fuzzel.in" && grep -q 'Auto-rotate' "$WORK/fuzzel.in"; then
    ok 'Cancel and the auto-rotate toggle are always offered'
else
    bad 'Cancel and the auto-rotate toggle are always offered'
fi
minibook-tablet-mode off >/dev/null 2>&1 || true
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode && ./tests/tablet-mode 2>&1 | grep -E "^FAIL" | head -5
```

Expected: failures about configured entries not appearing.

- [ ] **Step 3: Read the entries in the power button**

In `bin/minibook-power-button`, replace the hardcoded `Pick another score` and
`Close score` lines and their `case` arms with:

```sh
# Entries are configuration, not code. The mechanism knows how to fold, rotate
# and silence a keyboard; it has no business knowing what the human reads.
# One `label|command` per line, split on the FIRST | only so a command may
# contain pipes. Comments and blank lines ignored.
menu_file="${XDG_CONFIG_HOME:-$HOME/.config}/minibook-tablet-mode/menu"

configured_entries() {
    [ -r "$menu_file" ] || return 0
    while IFS= read -r _line; do
        case "$_line" in ''|'#'*) continue ;; esac
        printf '%s\n' "${_line%%|*}"
    done < "$menu_file"
}

command_for_entry() {
    [ -r "$menu_file" ] || return 1
    while IFS= read -r _line; do
        case "$_line" in ''|'#'*) continue ;; esac
        if [ "${_line%%|*}" = "$1" ]; then
            printf '%s\n' "${_line#*|}"
            return 0
        fi
    done < "$menu_file"
    return 1
}
```

Build the entry list from `configured_entries` plus the two built-ins:

```sh
if minibook-tablet-mode rotation-status; then
    rotation_entry='󰑦 Auto-rotate: on'
else
    rotation_entry='󰑧 Auto-rotate: off'
fi

entries=$(configured_entries)
entries=$(printf '%s\n%s\n%s' "$entries" "$rotation_entry" '󰅖 Cancel' \
    | grep -c . >/dev/null && printf '%s\n%s\n%s' "$entries" "$rotation_entry" '󰅖 Cancel')
# A leading blank line when no entries are configured would render as an empty
# row you can tap and which does nothing, so drop empties.
entries=$(printf '%s\n' "$entries" | grep -v '^$' || true)
_lines=$(printf '%s\n' "$entries" | grep -c .)
```

Pass `--lines "$_lines"` rather than a constant, so the menu is exactly as tall
as it needs to be. Dispatch with:

```sh
case "$selection" in
    *'Auto-rotate'*)  minibook-tablet-mode rotation-toggle ;;
    *'Cancel'*)       : ;;
    *)
        # Not one of ours: look it up. An entry that has vanished from the
        # config since the menu was drawn simply does nothing, which is the
        # same as Cancel and better than an error on a machine with no keyboard.
        _cmd=$(command_for_entry "$selection") || exit 0
        sh -c "$_cmd" ;;
esac
```

Set `--lines` to the number of entries actually offered rather than a constant.

- [ ] **Step 4: Run the tests until green**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode && ./tests/tablet-mode 2>&1 | tail -1
```

Expected: `N passed, 0 failed`.

- [ ] **Step 5: Write the example config files**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
cat > etc/menu.example <<'EOF'
# Entries for the folded power-button menu, one per line:
#
#     label|command
#
# Split on the FIRST | only, so the command may itself contain pipes.
# Blank lines and lines starting with # are ignored.
#
# Cancel and the auto-rotate toggle are always offered and are not listed here.
#
# The example below opens a PDF in whatever your desktop uses. Replace it with
# whatever you actually want to reach while the machine is folded.
󰈙 Open a document|xdg-open "$HOME/Documents"
EOF
```

Copy the current `roles/desktop/templates/tablet-mode.conf.j2` from gatherd
into `etc/config.example`, replacing every `{{ ... }}` with the concrete
default and keeping every comment.

- [ ] **Step 6: Commit**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
git add -A
git commit -m "Read the folded menu's entries from configuration

The two entries baked into this menu named a sheet-music reader, which is one
application out of all the things somebody might want to reach while folded.
The mechanism knows how to fold, rotate and silence a keyboard; what the human
reads is theirs to say."
```

---

### Task 6: Installer and documentation

**Files:**
- Create: `install.sh`, `README.md`, `docs/PORTING.md`

**Interfaces:**
- Produces: a repo a stranger can clone and install, and which gatherd's role
  can drive non-interactively.

- [ ] **Step 1: Write install.sh**

```sh
#!/bin/sh
# Install chuwi-minibook-tablet-mode. POSIX sh on purpose: the project is
# scripts, there is nothing to build, and a stranger should not need make.
set -eu

prefix=/usr/local
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix) prefix="$2"; shift 2 ;;
        --prefix=*) prefix="${1#--prefix=}"; shift ;;
        -h|--help) echo "usage: $0 [--prefix DIR]"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

here="$(cd "$(dirname "$0")" && pwd)"
install -d "$prefix/bin"
for f in "$here"/bin/*; do
    install -m 0755 "$f" "$prefix/bin/$(basename "$f")"
done

# The unit binds the base accelerometer, which is not enumerated by ACPI on
# this hardware. Installed but NOT enabled: enabling a system unit is the
# administrator's decision, and the README says which command to run.
install -d "$prefix/lib/systemd/system"
install -m 0644 "$here"/systemd/minibook-hinge-sensor.service \
    "$prefix/lib/systemd/system/minibook-hinge-sensor.service"

config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/minibook-tablet-mode"
install -d "$config_dir"
for example in config menu; do
    if [ ! -e "$config_dir/$example" ]; then
        install -m 0644 "$here/etc/$example.example" "$config_dir/$example"
        echo "installed $config_dir/$example"
    else
        echo "kept existing $config_dir/$example"
    fi
done

echo "installed to $prefix/bin"
```

- [ ] **Step 2: Verify the installer is idempotent and does not clobber config**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
chmod +x install.sh
rm -rf /tmp/extract/prefix /tmp/extract/cfg
XDG_CONFIG_HOME=/tmp/extract/cfg ./install.sh --prefix /tmp/extract/prefix
echo "CUSTOM" >> /tmp/extract/cfg/minibook-tablet-mode/config
XDG_CONFIG_HOME=/tmp/extract/cfg ./install.sh --prefix /tmp/extract/prefix
grep -c CUSTOM /tmp/extract/cfg/minibook-tablet-mode/config
ls /tmp/extract/prefix/bin
```

Expected: second run prints `kept existing`; `CUSTOM` still present (`1`); five
`minibook-*` commands in `bin`.

- [ ] **Step 3: Write README.md**

Must state, concretely: what hardware is required (a dual-accelerometer
convertible; two IIO accelerometers; the MiniBook X's base sensor is not
ACPI-enumerated, which is why `minibook-bind-hinge-sensor` exists); the runtime
dependencies (sway, jq, python3, fuzzel, setsid); how to install; the two sway
config lines needed (`bindsym XF86PowerOff exec minibook-power-button`, and
starting `minibook-hinge-daemon` from the session); how to enable the sensor
unit; how to calibrate `rotation_reference_deg` INCLUDING the
landscape-versus-portrait trap; and a note that history before the extraction
uses `minibook-*` names that were `gatherd-*` at the time.

- [ ] **Step 4: Write docs/PORTING.md**

Must contain the verb table from the spec, verbatim in substance: the four
rotation verbs are easy everywhere; `window-present`/`set-fullscreen` are easy
on wlroots and X11; the three input-silencing verbs and `inhibit-idle-all` are
the hard ones; other wlroots compositors and X11 are real ports while GNOME and
KDE are not feasible without extensions. State that a port implements the ten
verbs of `minibook-compositor` and changes nothing else, and that the suite's
boundary assertion will catch a port that leaks compositor calls elsewhere.

- [ ] **Step 5: Commit**

```bash
cd /tmp/extract/chuwi-minibook-tablet-mode
git add -A
git commit -m "Add an installer, a README and a porting guide

Says what the hardware and software actually have to be, rather than leaving a
stranger to discover it. PORTING.md is honest about how far 'any Linux'
reaches: two of the ten verbs are the hard ones, and GNOME and KDE cannot do
them from a script at all."
```

- [ ] **Step 6: Move the repo into place and hand off**

```bash
mkdir -p /home/schmonz/src
mv /tmp/extract/chuwi-minibook-tablet-mode \
   /home/schmonz/src/chuwi-minibook-tablet-mode
cd /home/schmonz/src/chuwi-minibook-tablet-mode
git log --oneline | head -5
./tests/tablet-mode 2>&1 | tail -1
```

Then STOP and tell the human: the repo is ready, they create the GitHub repo,
add the remote, push, and tag `v0.1.0`. Do not create remotes or push. Task 7
cannot proceed until the tag exists, because gatherd clones by tag.

---

### Task 7: gatherd consumes the new repo

**Files:**
- Create: `roles/desktop/tasks/tablet_mode_upstream.yml`
- Modify: `roles/desktop/tasks/tablet_mode.yml`
- Modify: `group_vars/all/main.yml`
- Delete: the five moved `scripts/gatherd-*`, `services/system/gatherd-hinge-sensor.service`

**Interfaces:**
- Consumes: a pushed, tagged `chuwi-minibook-tablet-mode`.
- Produces: a gatherd that installs the mechanism from upstream and keeps only
  music-stand.

- [ ] **Step 1: Add the pinned version and the menu entries**

In `group_vars/all/main.yml`:

```yaml
# The tablet-mode mechanism lives in its own repo now - it is a property of the
# hardware, not of this setup. Pinned rather than tracking main so a repave two
# years from now reproduces what runs today; upgrading is a one-line bump.
tablet_mode_upstream_repo: https://github.com/schmonz/chuwi-minibook-tablet-mode.git
tablet_mode_upstream_version: v0.1.0
tablet_mode_upstream_dir: "{{ target_home }}/.local/src/chuwi-minibook-tablet-mode"
# What gatherd puts in the folded menu. The mechanism ships knowing none of
# this; the sheet-music reader is ours.
tablet_mode_menu_entries:
  - label: "󰈙 Pick another score"
    command: gatherd-music-stand on
  - label: "󰎈 Close score"
    command: gatherd-music-stand close
```

- [ ] **Step 2: Write the clone-and-install tasks**

Create `roles/desktop/tasks/tablet_mode_upstream.yml`:

```yaml
---
- name: Clone the tablet-mode mechanism
  ansible.builtin.git:
    repo: "{{ tablet_mode_upstream_repo }}"
    dest: "{{ tablet_mode_upstream_dir }}"
    version: "{{ tablet_mode_upstream_version }}"
    update: true
  register: tablet_mode_clone

- name: Install the tablet-mode mechanism
  ansible.builtin.command:
    cmd: ./install.sh --prefix {{ target_home }}/.local
    chdir: "{{ tablet_mode_upstream_dir }}"
  when: tablet_mode_clone.changed
  changed_when: true

- name: Configure the folded menu
  ansible.builtin.template:
    src: tablet-mode-menu.j2
    dest: "{{ target_home }}/.config/minibook-tablet-mode/menu"
    mode: '0644'
```

Create `roles/desktop/templates/tablet-mode-menu.j2`:

```jinja
# Managed by gatherd. One label|command per line, split on the first pipe.
{% for entry in tablet_mode_menu_entries %}
{{ entry.label }}|{{ entry.command }}
{% endfor %}
```

- [ ] **Step 3: Repoint the rest of gatherd at the new names**

Change these, exactly:

- `roles/desktop/tasks/tablet_mode.yml`: drop the five moved scripts from the
  install loop, keep `gatherd-music-index` and `gatherd-music-stand`; include
  `tablet_mode_upstream.yml`; template the config to
  `{{ target_home }}/.config/minibook-tablet-mode/config`.
- `roles/desktop/tasks/core.yml:124`: `gatherd-power-button` →
  `minibook-power-button`.
- `roles/system/tasks/core.yml:325-341`: the unit is now installed by
  `install.sh` to `~/.local/lib/systemd/system`; link
  `/etc/systemd/system/minibook-hinge-sensor.service` at that path and enable
  `minibook-hinge-sensor.service`.
- `scripts/gatherd-session-helpers:92`: `gatherd-hinge-daemon` →
  `minibook-hinge-daemon`.
- `scripts/gatherd-music-stand`: `gatherd-tablet-mode` → `minibook-tablet-mode`
  (both the `status` call and `fullscreen-viewer`).
- `scripts/gatherd-post-setup-notes`: every moved command name in the verify
  steps.

- [ ] **Step 4: Delete the moved files**

```bash
cd /home/schmonz/.autofs-mounts/code/trees/gatherd
git rm scripts/gatherd-compositor scripts/gatherd-tablet-mode \
       scripts/gatherd-hinge-daemon scripts/gatherd-power-button \
       scripts/gatherd-bind-hinge-sensor \
       services/system/gatherd-hinge-sensor.service
```

- [ ] **Step 5: Reduce gatherd's suite to what it still owns**

`tests/tablet-mode` in gatherd keeps ONLY the music-stand and music-index
assertions — the mirror image of Task 4 Step 4. Rename it `tests/music-stand`.
It must fake `minibook-tablet-mode` rather than call the real one.

```bash
cd /home/schmonz/.autofs-mounts/code/trees/gatherd
git mv tests/tablet-mode tests/music-stand
./tests/music-stand 2>&1 | tail -1
```

Expected: `N passed, 0 failed`.

- [ ] **Step 6: Verify a converge changes nothing behavioural**

```bash
cd /home/schmonz/.autofs-mounts/code/trees/gatherd
ansible-lint 2>&1 | tail -2
```

Expected: the only failure is the pre-existing `site-vault.yml` vault-locked
`internal-error`. Then, with the human present and NOT folded:

```bash
minibook-tablet-mode status; echo "status: $?"
minibook-compositor internal-output
pgrep -x -f 'python3 .*minibook-hinge-daemon' | wc -l
```

Expected: status `1`; the connector name; exactly one daemon.

- [ ] **Step 7: Verify the whole feature by hand**

Fold: portrait, keyboard off. Power button: the two music-stand entries appear.
`Pick another score`: opens fullscreen. Turn the tablet: rotation follows.
Unfold: landscape, keyboard back, score windowed again.

- [ ] **Step 8: Commit**

```bash
cd /home/schmonz/.autofs-mounts/code/trees/gatherd
git add -A
git commit -m "Consume the tablet-mode mechanism from its own repo

The fold detection, rotation, input suppression and escape menu are properties
of the hardware, not of this setup, and now live in
chuwi-minibook-tablet-mode. gatherd clones it at a pinned tag and supplies the
folded menu's entries, which is all that was ever specific to this machine.

The sheet-music reader stays: forScore is Apple-specific and its .4sb backup is
worthless to anyone else."
```

---

## Follow-up, not in this plan

**Convert the suite to BATS.** 372 assertion sites, no behaviour change, and it
blocks nothing. It gets its own plan once this one has landed and the machine
has been folded a few times. Doing it here would mean rewriting the test file
in the same change that proves the extraction was behaviour-preserving, which
would destroy the evidence.
