# Self-Naming Hostname Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Domain note on "tests":** Ansible project; verification uses `ansible-lint`, `ansible-playbook --syntax-check`, a sandbox dry-run of the lookup, **idempotent re-run = zero `changed`**, and the `section_verify` sequence in `scripts/gatherd-post-setup-notes` — not pytest.

**Goal:** A freshly-imaged machine names itself on first boot by looking its hostname up from a map keyed on stable hardware identifiers — working offline, never stomping a hand-chosen name, never failing the run.

**Architecture:** A `machine_facts` probe exposes a list of stable identifiers (`machine_identifiers`). A CORE-tier task in `site.yml`'s Detect play looks the machine up in an in-repo map (`hostnames.yml`, optional HTTPS override), and — only if the current name is a known installer default — applies it via `ansible.builtin.hostname` + `/etc/hosts`, then re-gathers facts so the existing hostname consumers see the new name on the first run. Every failure path keeps the current name.

**Tech Stack:** Ansible (FQCN only), `ethtool`/sysfs/DMI for identifiers.

**Parent spec:** `docs/superpowers/specs/2026-06-29-travel-repave-design.md` (sub-project 3, Unattended completion; decision D10 — self-naming with offline fallback). **Supersedes `plans/HOSTNAME-LOOKUP.md`, removed in the conversion commit.**

## Global Constraints

- **FQCN always**; tiny task files; imperative task names (`CLAUDE.md`).
- **CORE-tier / network-optional:** resolution must succeed offline from the in-repo map; the HTTPS source is a best-effort override. No network dependency, no hang (travel-repave invariant).
- **Fail-open (SP1 gate):** any failure — no map, no match, fetch error, decrypt error — keeps the current hostname and does **not** fail the play.
- **Never stomp a hand-set name:** apply only when the current hostname is a known installer default (`hostname_installer_defaults`).
- **No me-specific defaults in the repo (D11):** the real `hostnames.yml` is user data (git-ignored); only `hostnames.yml.example` is committed. The HTTPS source is a var (`hostname_map_url`) defaulting to unset.
- **`ansible-lint` clean before each commit**; idempotent (the `hostname` module no-ops when the name already matches).

## Decisions locked for this plan (flag on review)

- **v1 keys the map on RAW identifiers, not `sha256(salt+id)`.** The salted-hash scheme in the source design existed only to publish the map *publicly* without leaking MACs/UUIDs. There is no public map source today, and a secret salt would couple early hostname-setting to vault decryption (the vault may be deferred to the desktop prompt). **YAGNI:** stay raw + private map now; switch to salted-hash with a vault-sourced salt *if and when* a public source appears. (Noted in the task file as a comment.)
- **Map precedence:** in-repo `hostnames.yml` is the offline default; a successful `hostname_map_url` fetch overrides it.

## File Structure

- `roles/machine_facts/tasks/main.yml` (modify) — add the `machine_identifiers` probe block.
- `tasks/hostname.yml` (new) — resolve + guard + apply; included by `site.yml` play 1.
- `site.yml` (modify) — add a `tasks:` block to play 1: include `tasks/hostname.yml`, then `ansible.builtin.setup` to refresh facts.
- `group_vars/all/main.yml` (modify) — `hostname_map_url` (default `''`), `hostname_installer_defaults`.
- `hostnames.yml.example` (new) + `.gitignore` (modify) — the user map shape + ignore the real file.

---

## Task 1: `machine_identifiers` probe

**Files:**
- Modify: `roles/machine_facts/tasks/main.yml` (add probe block, following the file's stat/command + `set_fact` pattern)

**Interfaces:**
- Produces: `machine_identifiers` — a deduped, lowercased list of stable ids (permanent NIC MACs + DMI product UUID + serial). Consumed by `tasks/hostname.yml` (Task 3).

- [ ] **Step 1: Add the probe block**

```yaml
# ── Stable machine identifiers (for self-naming; see tasks/hostname.yml) ───────
# A SET of candidates, matched any-of: permanent MACs survive Wi-Fi MAC
# randomization (ethtool -P) and the DMI UUID/serial survive a NIC swap.
- name: Gather permanent NIC MAC addresses
  ansible.builtin.shell: |
    for d in /sys/class/net/*; do
      ifc=${d##*/}
      [ "$ifc" = lo ] && continue
      [ -e "$d/device" ] || continue        # skip virtual interfaces
      mac=$(ethtool -P "$ifc" 2>/dev/null | awk '{print $NF}')
      case "$mac" in ""|00:00:00:00:00:00) mac=$(cat "$d/address" 2>/dev/null) ;; esac
      [ -n "$mac" ] && printf '%s\n' "$mac"
    done
  register: _perm_macs
  changed_when: false

- name: Read DMI product UUID and serial
  ansible.builtin.shell: |
    cat /sys/class/dmi/id/product_uuid 2>/dev/null || true
    cat /sys/class/dmi/id/product_serial 2>/dev/null || true
  register: _dmi_ids
  changed_when: false

- name: Set machine_identifiers fact
  ansible.builtin.set_fact:
    machine_identifiers: >-
      {{ (_perm_macs.stdout_lines + _dmi_ids.stdout_lines)
         | map('trim') | map('lower') | select('string')
         | reject('equalto', '') | list | unique }}
```

- [ ] **Step 2: Verify the fact populates**

```
ansible-lint
ansible-playbook --syntax-check site.yml
# Sandbox dry check on this machine:
ansible localhost -m shell -a 'ethtool -P $(ls -1 /sys/class/net | grep -v lo | head -1); cat /sys/class/dmi/id/product_uuid'
# Expect machine_identifiers to include at least the DMI UUID; confirm with a temporary debug task or -vv.
```

- [ ] **Step 3: Commit**

```bash
git add roles/machine_facts/tasks/main.yml
git commit -m "machine_facts: gather stable machine_identifiers for self-naming"
```

---

## Task 2: The map files and vars

**Files:**
- Create: `hostnames.yml.example`
- Modify: `.gitignore` (ignore the real `hostnames.yml`)
- Modify: `group_vars/all/main.yml`

**Interfaces:**
- Produces: `hostname_map_url` (default `''`), `hostname_installer_defaults` (list), and the on-disk `hostnames.yml` contract consumed by Task 3.

- [ ] **Step 1: Write `hostnames.yml.example`**

```yaml
# Copy to hostnames.yml (git-ignored) and fill in. Keys are raw identifiers from
# `machine_identifiers` (permanent MAC, DMI product_uuid, or product_serial),
# lowercased. Any one matching id assigns the hostname. Reassign freely.
hostnames:
  "dc:a6:32:00:00:00": kunilou
  "12345678-1234-1234-1234-1234567890ab": pet-power-plant
```

- [ ] **Step 2: Ignore the real file**

Add to `.gitignore`:
```
/hostnames.yml
```

- [ ] **Step 3: Add the vars**

In `group_vars/all/main.yml`:
```yaml
# Self-naming (tasks/hostname.yml). No me-specific defaults: the real map is the
# git-ignored hostnames.yml; hostname_map_url is an optional HTTPS override.
hostname_map_url: ''
hostname_installer_defaults:
  - EndeavourOS
  - archlinux
  - artix
```

- [ ] **Step 4: Verify & commit**

```
ansible-lint
git add hostnames.yml.example .gitignore group_vars/all/main.yml
git commit -m "Add hostname map example + self-naming vars"
```

---

## Task 3: Resolve + guard + apply (`tasks/hostname.yml`)

**Files:**
- Create: `tasks/hostname.yml`

**Interfaces:**
- Consumes: `machine_identifiers` (Task 1), `hostname_map_url`/`hostname_installer_defaults` (Task 2), `ansible_facts['hostname']`.
- Produces: the applied hostname + fixed `/etc/hosts`; sets `_resolved_hostname` (else undefined → no-op).

- [ ] **Step 1: Write the task file**

```yaml
---
# Self-name on first boot: look this machine up by any stable identifier and, if
# it currently carries an installer default, apply the assigned hostname. Every
# failure path keeps the current name (CORE-tier, fail-open). v1 keys on RAW
# identifiers; if the map ever goes public, switch to sha256(salt+id) with the
# salt from the vault (the only reason to add that coupling).
- name: Load the in-repo hostname map (user-provided; optional)
  ansible.builtin.include_vars:
    file: "{{ playbook_dir }}/hostnames.yml"
    name: _hostmap_repo
  failed_when: false

- name: Best-effort override from the configured HTTPS map
  ansible.builtin.uri:
    url: "{{ hostname_map_url }}"
    return_content: true
    timeout: 10
  register: _hostmap_http
  failed_when: false
  changed_when: false
  when: hostname_map_url | length > 0

- name: Merge maps (HTTPS overrides in-repo)
  ansible.builtin.set_fact:
    _hostmap: >-
      {{ (_hostmap_repo.hostnames | default({}))
         | combine( (_hostmap_http.content | default('') | from_yaml).hostnames
                    if (_hostmap_http.status | default(0)) == 200 else {} ) }}

- name: Resolve hostname by any identifier (first match wins)
  ansible.builtin.set_fact:
    _resolved_hostname: "{{ _hostmap[item] }}"
  loop: "{{ machine_identifiers | default([]) }}"
  when:
    - item in _hostmap
    - _resolved_hostname is not defined

- name: Apply resolved hostname (only over an installer default)
  ansible.builtin.hostname:
    name: "{{ _resolved_hostname }}"
  when:
    - _resolved_hostname is defined
    - ansible_facts['hostname'] in hostname_installer_defaults

- name: Point 127.0.1.1 at the resolved hostname
  ansible.builtin.lineinfile:
    path: /etc/hosts
    regexp: '^127\.0\.1\.1\b'
    line: "127.0.1.1\t{{ _resolved_hostname }}"
  when:
    - _resolved_hostname is defined
    - ansible_facts['hostname'] in hostname_installer_defaults
```

- [ ] **Step 2: Verify the resolution logic in a sandbox**

```
ansible-playbook --syntax-check site.yml && ansible-lint
# Dry test the lookup without changing the box: create a throwaway hostnames.yml
# whose key is one of THIS machine's machine_identifiers and a current hostname
# in hostname_installer_defaults faked via -e, run with --check -vv on tasks/hostname.yml,
# confirm _resolved_hostname resolves and the apply task WOULD change.
```

- [ ] **Step 3: Commit**

```bash
git add tasks/hostname.yml
git commit -m "Add self-naming hostname resolve/guard/apply task"
```

---

## Task 4: Wire into the Detect play + refresh facts

**Files:**
- Modify: `site.yml` (play 1, "Detect target user and hardware")

**Interfaces:**
- Consumes: `machine_facts` role output (runs before `tasks:`). Produces: hostname set before plays 2–3, with facts re-gathered so `ansible_facts['hostname']` consumers (etckeeper branch rename, `root@host` git identity, conky, flutter alias) see the new name on the first run.

- [ ] **Step 1: Add a `tasks:` block to play 1**

After the `roles: [machine_facts]` of the first play in `site.yml`, add:

```yaml
  tasks:
    - name: Resolve and apply this machine's hostname
      ansible.builtin.include_tasks: tasks/hostname.yml

    - name: Re-gather facts so later plays see the new hostname
      ansible.builtin.setup:
      when: _resolved_hostname is defined
```

(Play 1 has `gather_facts: true`, so the initial facts exist for the guard; the re-gather only runs when a new name was resolved, keeping the converged-machine run cheap.)

- [ ] **Step 2: Verify end-to-end on a test image**

```
ansible-lint && ansible-playbook --syntax-check site.yml
# On a fresh image whose identifier is in the map: after gatherd's first run,
#   hostnamectl                       -> the assigned name
#   grep 127.0.1.1 /etc/hosts         -> matches
#   git -C /etc rev-parse --abbrev-ref HEAD (etckeeper) -> named for the new host
# On a machine NOT in the map: installer default untouched.
# Network unreachable: in-repo map still resolves (or current name kept) — no failed run.
# Idempotent re-run: zero changed.
```

- [ ] **Step 3: Commit**

```bash
git add site.yml
git commit -m "Set the resolved hostname early and refresh facts before later plays"
```

---

## Task 5: Verify step + retire the source plan

**Files:**
- Modify: `scripts/gatherd-post-setup-notes` (`section_verify`)
- Delete: `plans/HOSTNAME-LOOKUP.md`

- [ ] **Step 1: Add the `section_verify` line**

A runnable check, e.g.: on a mapped machine `hostnamectl --static` equals the expected name and `grep -q "^127\.0\.1\.1[[:space:]].*$(hostname)" /etc/hosts` succeeds; on an unmapped machine the installer default is untouched; with `hostname_map_url` set, the HTTPS map overrides the in-repo one.

- [ ] **Step 2: Remove the superseded source plan**

```bash
git rm plans/HOSTNAME-LOOKUP.md
```

- [ ] **Step 3: Commit**

```bash
git add scripts/gatherd-post-setup-notes
git commit -m "Self-naming: add verify step; retire HOSTNAME-LOOKUP.md"
```

---

## Self-Review

**Spec coverage** (vs `HOSTNAME-LOOKUP.md` design + D10):
- Identifier set (MACs via `ethtool -P` + DMI uuid/serial, match-any) → Task 1. ✅
- HTTPS-authoritative + in-repo fallback, graceful failure → Task 3 (merge + `failed_when: false`). ✅
- Apply via `ansible.builtin.hostname` + `/etc/hosts`, installer-default policy guard, idempotent → Task 3. ✅
- Ordering: set early in Detect play, re-gather facts → Task 4. ✅
- Offline fallback (D10) + CORE-tier + fail-open → Global Constraints, Task 3. ✅
- Privacy/salted-hash → intentionally deferred (Decisions locked); raw keys + private map in v1.

**Placeholder scan:** all task files and vars are complete and runnable. The `_resolved_hostname is not defined` first-match-wins pattern and the `combine()` precedence are concrete.

**Type/name consistency:** `machine_identifiers`, `_hostmap`, `_resolved_hostname`, `hostname_map_url`, `hostname_installer_defaults`, `hostnames.yml` are used consistently across tasks.
