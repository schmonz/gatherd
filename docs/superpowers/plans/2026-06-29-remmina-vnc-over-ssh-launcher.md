# Remmina VNC-over-SSH launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user open one app-menu entry, type a hostname, and get a VNC-over-SSH Remmina connection — with no machine names baked into the playbook or saved in Remmina.

**Architecture:** A POSIX-sh launcher (`gatherd-remmina-connect`) prompts for a host via fuzzel (with recent-host history), substitutes the host into a fixed VNC-over-SSH `.remmina` template, and runs `remmina -c <tmpfile>` against a throwaway profile it deletes on exit. A `.desktop` entry execs it. An Ansible task in the desktop role installs both.

**Tech Stack:** POSIX shell, fuzzel (dmenu mode), Remmina (`-c` connect-to-file), Ansible (`ansible.builtin.copy`/`template`, `import_tasks`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-29-remmina-vnc-over-ssh-launcher-design.md`.
- No machine names in the playbook or in Remmina's saved profile list. The generated profile is ephemeral (`mktemp`, deleted on exit); `remmina -c` connects without importing.
- Runtime scripts live in `scripts/` with no extension and are installed to `{{ target_home }}/.local/bin/` via `ansible.builtin.copy` with `remote_src: true` (mirror the existing `gatherd-polkit-agent` install task). The user play runs under `become_user: {{ target_user }}`, so installed files are owned by the user — do NOT set `owner`/`group`.
- Templates are `.j2` in `roles/<role>/templates/`.
- Task names read like imperative sentences. Use FQCN (`ansible.builtin.*`).
- Run `ansible-lint` before committing Ansible changes; the `noqa` marker is a last resort.
- Fixed VNC-over-SSH profile fields (from the working `pet-power-plant` profile): `protocol=VNC`, `server=localhost:5900`, blank `username`/`password`, `ignore-tls-errors=1`, `ssh_tunnel_enabled=1`, `ssh_tunnel_auth=2` (pubkey), `ssh_tunnel_username=<user>`, `ssh_tunnel_server=<host>:<port>`.
- Target parse grammar: `[user@]host[:port]`; defaults `user=${USER:-$(id -un)}`, `port=22`; host passed verbatim (no name canonicalisation).

---

### Task 1: The launcher script with `--print`

**Files:**
- Create: `scripts/gatherd-remmina-connect`

**Interfaces:**
- Produces: an executable that, with `--print [user@]host[:port]`, writes a `.remmina` profile to stdout and exits 0 (no fuzzel/remmina needed); with no args, prompts via fuzzel and launches `remmina -c`. Used by the `.desktop` entry (Task 2) and the verify item (Task 4).

- [ ] **Step 1: Write the failing test**

Create a scratch check (not committed) at `/tmp/claude-1000/-home-schmonz--autofs-mounts-code-trees-gatherd/11f02fde-13a0-43f2-8f90-671ec5e47a15/scratchpad/t1.sh`:

```sh
#!/bin/sh
set -eu
s=scripts/gatherd-remmina-connect
out=$("$s" --print testhost)
echo "$out" | grep -qx 'protocol=VNC'
echo "$out" | grep -qx 'server=localhost:5900'
echo "$out" | grep -qx 'ssh_tunnel_enabled=1'
echo "$out" | grep -qx 'ssh_tunnel_auth=2'
echo "$out" | grep -qx 'ssh_tunnel_server=testhost:22'
echo "$out" | grep -qx "ssh_tunnel_username=$(id -un)"
echo "$out" | grep -qx 'password='
echo "$out" | grep -qx 'name=testhost'
# user@host:port override
out2=$("$s" --print schmonz@host:2222)
echo "$out2" | grep -qx 'ssh_tunnel_username=schmonz'
echo "$out2" | grep -qx 'ssh_tunnel_server=host:2222'
echo "ALL PASS"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `sh /tmp/claude-1000/-home-schmonz--autofs-mounts-code-trees-gatherd/11f02fde-13a0-43f2-8f90-671ec5e47a15/scratchpad/t1.sh`
Expected: FAIL — `scripts/gatherd-remmina-connect: No such file or directory`.

- [ ] **Step 3: Write the script**

Create `scripts/gatherd-remmina-connect`:

```sh
#!/bin/sh
# Open a VNC-over-SSH Remmina connection to a host typed at a fuzzel prompt,
# without any saved per-machine profile. The VNC server is always the SSH host's
# own localhost:5900 (wayvnc, no auth), so only the SSH tunnel host varies — a
# fixed template with the host substituted is the whole difference between
# machines. We drive Remmina with `remmina -c` against an ephemeral profile
# (deleted on exit) rather than Remmina's GUI, which cannot set up an SSH tunnel
# from its quick-connect bar. See
# docs/superpowers/specs/2026-06-29-remmina-vnc-over-ssh-launcher-design.md.
set -eu

state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/gatherd"
history_file="$state_dir/remmina-hosts"
max_history=20

# Emit a .remmina profile for one host on stdout. Args: user host port name.
emit_profile() {
    cat <<EOF
[remmina]
name=$4
protocol=VNC
server=localhost:5900
username=
password=
ignore-tls-errors=1
disablepasswordstoring=0
colordepth=32
quality=2
viewmode=1
ssh_tunnel_enabled=1
ssh_tunnel_auth=2
ssh_tunnel_username=$1
ssh_tunnel_server=$2:$3
ssh_tunnel_loopback=0
EOF
}

# Parse [user@]host[:port] into globals user/host/port (user/port defaulted).
parse_target() {
    _spec=$1
    user=${USER:-$(id -un)}
    port=22
    case $_spec in
        *@*) user=${_spec%%@*}; _spec=${_spec#*@} ;;
    esac
    case $_spec in
        *:*) port=${_spec##*:}; _spec=${_spec%:*} ;;
    esac
    host=$_spec
}

# --print [user@]host[:port]: emit the would-be profile and exit (no GUI deps).
if [ "${1:-}" = "--print" ]; then
    [ $# -ge 2 ] || { echo "usage: $0 --print [user@]host[:port]" >&2; exit 2; }
    parse_target "$2"
    emit_profile "$user" "$host" "$port" "$host"
    exit 0
fi

# Prompt for a host, offering recent ones. fuzzel --dmenu returns the typed text
# on Enter even when it matches no list entry (same behavior gatherd-askpass
# relies on), so a brand-new host works alongside picking a remembered one.
history=""
[ -r "$history_file" ] && history=$(cat "$history_file")
target=$(printf '%s\n' "$history" | fuzzel --dmenu --prompt 'host: ') || exit 0
[ -n "$target" ] || exit 0

parse_target "$target"

# Record the raw target most-recent-first (dedup, cap). Best-effort.
mkdir -p "$state_dir" 2>/dev/null && {
    { printf '%s\n' "$target"; printf '%s\n' "$history"; } \
        | awk 'NF && !seen[$0]++' | head -n "$max_history" > "$history_file.tmp" \
        && mv "$history_file.tmp" "$history_file"
} || true

tmp=$(mktemp --suffix=.remmina) || exit 1
trap 'rm -f "$tmp"' EXIT
emit_profile "$user" "$host" "$port" "$host" > "$tmp"
remmina -c "$tmp"
```

- [ ] **Step 4: Make it executable and verify the test passes**

Run:
```bash
chmod +x scripts/gatherd-remmina-connect
sh /tmp/claude-1000/-home-schmonz--autofs-mounts-code-trees-gatherd/11f02fde-13a0-43f2-8f90-671ec5e47a15/scratchpad/t1.sh
```
Expected: `ALL PASS`.

- [ ] **Step 5: Lint the shell**

Run: `bash -n scripts/gatherd-remmina-connect && command -v shellcheck >/dev/null && shellcheck scripts/gatherd-remmina-connect || echo "shellcheck absent — bash -n only"`
Expected: no syntax errors. Fix any shellcheck warnings that are real (quoting); `# shellcheck disable` only as a last resort.

- [ ] **Step 6: Commit**

```bash
git add scripts/gatherd-remmina-connect
git commit -m "Add gatherd-remmina-connect VNC-over-SSH launcher"
```

---

### Task 2: The app-menu entry

**Files:**
- Create: `roles/desktop/templates/remote-desktop-vnc-over-ssh.desktop.j2`

**Interfaces:**
- Consumes: the installed launcher path `{{ target_home }}/.local/bin/gatherd-remmina-connect` (Task 1's artifact, installed in Task 3).
- Produces: a `.desktop` file the fuzzel app launcher lists as "Remote Desktop (VNC over SSH)".

- [ ] **Step 1: Write the template**

Create `roles/desktop/templates/remote-desktop-vnc-over-ssh.desktop.j2`:

```ini
[Desktop Entry]
Type=Application
Name=Remote Desktop (VNC over SSH)
Comment=Connect to a host's desktop over VNC through an SSH tunnel
Exec={{ target_home }}/.local/bin/gatherd-remmina-connect
Icon=remmina
Terminal=false
Categories=Network;RemoteAccess;
```

- [ ] **Step 2: Validate the rendered entry**

Run (renders with a sample home, then validates if the tool exists):
```bash
sed 's#{{ target_home }}#/home/schmonz#' roles/desktop/templates/remote-desktop-vnc-over-ssh.desktop.j2 > /tmp/claude-1000/-home-schmonz--autofs-mounts-code-trees-gatherd/11f02fde-13a0-43f2-8f90-671ec5e47a15/scratchpad/rd.desktop
command -v desktop-file-validate >/dev/null && desktop-file-validate /tmp/claude-1000/-home-schmonz--autofs-mounts-code-trees-gatherd/11f02fde-13a0-43f2-8f90-671ec5e47a15/scratchpad/rd.desktop && echo VALID || grep -q '^Exec=/home/schmonz/.local/bin/gatherd-remmina-connect$' /tmp/claude-1000/-home-schmonz--autofs-mounts-code-trees-gatherd/11f02fde-13a0-43f2-8f90-671ec5e47a15/scratchpad/rd.desktop && echo "OK (no validator)"
```
Expected: `VALID` or `OK (no validator)`.

- [ ] **Step 3: Commit**

```bash
git add roles/desktop/templates/remote-desktop-vnc-over-ssh.desktop.j2
git commit -m "Add Remote Desktop app-menu entry template"
```

---

### Task 3: Install via the desktop role

**Files:**
- Create: `roles/desktop/tasks/remmina.yml`
- Modify: `roles/desktop/tasks/main.yml` (append an `import_tasks` line)

**Interfaces:**
- Consumes: `scripts/gatherd-remmina-connect` (Task 1), `remote-desktop-vnc-over-ssh.desktop.j2` (Task 2), the role facts `setup_dir`, `target_home`.

- [ ] **Step 1: Write the task file**

Create `roles/desktop/tasks/remmina.yml`:

```yaml
---
- name: Install the Remmina VNC-over-SSH launcher
  ansible.builtin.copy:
    src: "{{ setup_dir }}/scripts/gatherd-remmina-connect"
    dest: "{{ target_home }}/.local/bin/gatherd-remmina-connect"
    mode: '0755'
    remote_src: true

- name: Install the Remote Desktop app-menu entry
  ansible.builtin.template:
    src: remote-desktop-vnc-over-ssh.desktop.j2
    dest: "{{ target_home }}/.local/share/applications/Remote Desktop (VNC over SSH).desktop"
    mode: '0644'
```

- [ ] **Step 2: Wire it into the desktop role**

Append to the end of `roles/desktop/tasks/main.yml`:

```yaml
- name: Configure the Remmina VNC-over-SSH launcher
  ansible.builtin.import_tasks: remmina.yml
```

- [ ] **Step 3: Lint and syntax-check**

Run:
```bash
ansible-lint roles/desktop/tasks/remmina.yml
ansible-playbook --syntax-check site.yml 2>&1 | grep -iE 'remmina|desktop' || echo "no remmina/desktop syntax errors"
```
Expected: ansible-lint reports `Passed` / 0 failures. (A pre-existing `kewlfft.aur.aur` collection-resolution error from `roles/hardware` is unrelated and may appear in the full syntax-check; it must not reference `remmina.yml` or `desktop`.)

- [ ] **Step 4: Commit**

```bash
git add roles/desktop/tasks/remmina.yml roles/desktop/tasks/main.yml
git commit -m "Install Remmina VNC-over-SSH launcher from the desktop role"
```

---

### Task 4: Verify item

**Files:**
- Modify: `scripts/gatherd-post-setup-notes` (add one `li` to `section_verify`)

**Interfaces:**
- Consumes: the installed `gatherd-remmina-connect --print` behavior (Task 1).

- [ ] **Step 1: Add the verify item**

In `scripts/gatherd-post-setup-notes`, inside `section_verify()`, add a new `li` immediately after the existing `Remote GUI via VNC over SSH` item (the one mentioning `wayvnc`). Use this exact line:

```sh
    li 'Remmina VNC-over-SSH launcher templates by hostname (no machine names saved). Mechanical: `gatherd-remmina-connect --print testhost` prints a profile with `protocol=VNC`, `server=localhost:5900`, `ssh_tunnel_enabled=1`, `ssh_tunnel_auth=2`, `ssh_tunnel_server=testhost:22`, `ssh_tunnel_username=`whoami``, and an empty `password=` (no stored VNC secret) — `gatherd-remmina-connect --print testhost | grep -qx ssh_tunnel_server=testhost:22 && echo OK`. The `[user@]host[:port]` grammar works: `gatherd-remmina-connect --print schmonz@host:2222` shows `ssh_tunnel_username=schmonz` and `ssh_tunnel_server=host:2222`. The app-menu entry exists and points at the launcher: `grep -qx Exec=$HOME/.local/bin/gatherd-remmina-connect "$HOME/.local/share/applications/Remote Desktop (VNC over SSH).desktop" && echo OK`. Functional: Mod-D lists "Remote Desktop (VNC over SSH)"; launching it pops a fuzzel `host:` prompt that offers recent hosts AND accepts a freshly typed one; typing a reachable fleet host lands in its Sway session with no VNC password prompt; afterward Remmina`s own saved-profile list (open Remmina) shows no entry for that host (the ephemeral profile was deleted).'
```

- [ ] **Step 2: Syntax-check the notes script and confirm the item parses**

Run:
```bash
bash -n scripts/gatherd-post-setup-notes && echo "syntax OK"
awk '/^section_verify\(\)/,/^}/' scripts/gatherd-post-setup-notes | grep -c '^\s*li '
```
Expected: `syntax OK`, and the `li` count is one more than before (9).

- [ ] **Step 3: Repave-cadence check**

Per CLAUDE.md, if the `li` count in `section_verify` now exceeds 10, note to the user that it's time to repave and run the checklist. At 9 it does not — no action.

- [ ] **Step 4: Commit**

```bash
git add scripts/gatherd-post-setup-notes
git commit -m "Add verify item for the Remmina VNC-over-SSH launcher"
```

---

## Self-Review

**Spec coverage:**
- Launcher script + fuzzel prompt + history + ephemeral profile + `--print` → Task 1. ✓
- Fixed VNC-over-SSH template fields → Task 1 `emit_profile`. ✓
- `[user@]host[:port]` parsing with defaults → Task 1 `parse_target`. ✓
- App-menu `.desktop` entry, stock Remmina kept → Task 2 (adds a new entry, removes nothing). ✓
- Install in desktop role, owned by user via the play's `become_user` → Task 3. ✓
- Verify item (mechanical + functional) → Task 4. ✓
- Recent-host history capped ~20 → Task 1 `max_history=20`. ✓

**Placeholder scan:** No TBD/TODO; every code/step block is complete. ✓

**Type/name consistency:** `gatherd-remmina-connect`, `--print`, `emit_profile`, `parse_target`, the dest paths, and the `.desktop` Exec line are identical across Tasks 1–4. ✓

**Out of scope (unchanged from spec):** programmatic fleet list, Mac Screen Sharing, sway keybind.
