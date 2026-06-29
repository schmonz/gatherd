# Quiet Boot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

> **Domain note on "tests":** Ansible/GRUB/dracut project; verification uses `ansible-lint`, `--syntax-check`, idempotent re-run (zero `changed`), inspection of `/etc/default/grub` + `/boot/grub/grub.cfg`, and an actual reboot. Not pytest.

**Goal:** A clean, quiet boot on the GRUB+dracut+greetd+LUKS fleet — suppress console chatter (Tier 1), with an optional graphical Plymouth splash (Tier 2).

**Architecture:** Tier 1 appends quiet kernel params to `GRUB_CMDLINE_LINUX_DEFAULT` via the same idempotent, quote-agnostic `ansible.builtin.replace` + `Rebuild grub` handler pattern `roles/hardware/tasks/zswap.yml` already uses, gated `when: has_grub`. Tier 2 (optional) adds Plymouth as a dracut module with a greetd hand-off drop-in.

**Tech Stack:** Ansible (FQCN), GRUB (`/etc/default/grub`, `grub-mkconfig`), dracut, Plymouth.

**Source:** supersedes `plans/QUIET-BOOT.md` (removed in the conversion commit). System context: EndeavourOS/Arch, GRUB, dracut, greetd, LUKS; `loglevel=3` is already on the cmdline.

## Global Constraints

- **FQCN; tiny task files; `ansible-lint` clean before commit; idempotent** (`CLAUDE.md`).
- **Reuse the existing GRUB-edit pattern** (`roles/hardware/tasks/zswap.yml`): quote-agnostic regexp with a negative-lookahead so re-runs don't duplicate params; `notify: Rebuild grub`; `when: has_grub`.
- **Keep `loglevel=3`** — already present; do not remove it.
- **Preserve an escape hatch** — this system sets `GRUB_DISABLE_RECOVERY='true'`, so rely on GRUB's one-shot `e`-edit (remove `quiet`, Ctrl-X) rather than maintaining a verbose entry.

## File Structure

- `roles/hardware/tasks/quiet_boot.yml` (new) — Tier 1 cmdline params (+ optional menu-hide).
- `roles/hardware/tasks/main.yml` (modify) — import the new task file alongside the zswap import.
- `roles/hardware/tasks/plymouth.yml` (new, Tier 2, optional) — Plymouth module + greetd drop-in.
- `group_vars/all/main.yml` (modify) — `quiet_boot_hide_menu` (default `false`), `quiet_boot_plymouth` (default `false`).
- `scripts/gatherd-post-setup-notes` (modify) — `section_verify` lines.

---

## Task 1: Tier 1 — quiet kernel params

**Files:**
- Create: `roles/hardware/tasks/quiet_boot.yml`
- Modify: `roles/hardware/tasks/main.yml`

**Interfaces:**
- Consumes: `has_grub` fact (already used by zswap). Produces: a quiet `GRUB_CMDLINE_LINUX_DEFAULT`.

- [ ] **Step 1: Write `roles/hardware/tasks/quiet_boot.yml`**

```yaml
---
# Suppress boot-console chatter on GRUB systems. loglevel=3 is already on the
# cmdline (kept); add the remaining three. Same quote-agnostic, negative-lookahead
# replace as zswap.yml so re-runs never duplicate the params. Targets
# GRUB_CMDLINE_LINUX_DEFAULT (not recovery). Escape hatch: GRUB's one-shot `e`
# edit (remove `quiet`), since GRUB_DISABLE_RECOVERY=true here.
- name: Quiet the boot console in GRUB
  ansible.builtin.replace:
    path: /etc/default/grub
    regexp: '^(GRUB_CMDLINE_LINUX_DEFAULT=(["''])(?!.*rd\.systemd\.show_status=).*)\2\s*$'
    replace: '\1 quiet rd.udev.log_level=3 rd.systemd.show_status=auto\2'
  notify: Rebuild grub
  when: has_grub

- name: Hide the GRUB menu (optional)
  # Only when explicitly opted in; the menu is still reachable by holding Shift
  # (BIOS) or pressing Esc after firmware handoff.
  ansible.builtin.replace:
    path: /etc/default/grub
    regexp: "{{ item.regexp }}"
    replace: "{{ item.replace }}"
  loop:
    - { regexp: '^GRUB_TIMEOUT=.*$',        replace: "GRUB_TIMEOUT='0'" }
    - { regexp: '^GRUB_TIMEOUT_STYLE=.*$',  replace: 'GRUB_TIMEOUT_STYLE=hidden' }
  notify: Rebuild grub
  when:
    - has_grub
    - quiet_boot_hide_menu | default(false) | bool
```

(The negative-lookahead keys on `rd.systemd.show_status=` — the last param added — so the whole group lands once and re-runs are no-ops.)

- [ ] **Step 2: Import it in the hardware role**

```bash
grep -n "zswap.yml" roles/hardware/tasks/main.yml   # find the existing import
```
Add next to it:
```yaml
- name: Configure quiet boot
  ansible.builtin.import_tasks: quiet_boot.yml
```

- [ ] **Step 3: Add the var**

In `group_vars/all/main.yml`: `quiet_boot_hide_menu: false`.

- [ ] **Step 4: Verify**

```
ansible-lint && ansible-playbook --syntax-check site.yml
# Apply, then:
grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub   # has quiet + loglevel=3 + rd.udev.log_level=3 + rd.systemd.show_status=auto, once
grep -o 'quiet.*' /boot/grub/grub.cfg | head        # present in generated config
# Idempotency: re-run -> the replace task reports OK (not changed); no duplicate params.
# Reboot: console is quiet through to greeter; a forced-verbose `e`-edit still works.
```

- [ ] **Step 5: Commit**

```bash
git add roles/hardware/tasks/quiet_boot.yml roles/hardware/tasks/main.yml group_vars/all/main.yml
git commit -m "Quiet boot Tier 1: suppress console chatter via GRUB cmdline"
```

---

## Task 2: Tier 2 — Plymouth graphical splash (optional)

*Opt-in (`quiet_boot_plymouth: true`). Tier 1 is a prerequisite. Cross-link: this is also the lever for the "sideways GRUB-stage display" TODO — once `/boot` is outside LUKS, Plymouth with `fbcon=rotate:1` could rotate the LUKS prompt the initramfs draws.*

**Files:**
- Create: `roles/hardware/tasks/plymouth.yml`
- Modify: `roles/hardware/tasks/main.yml` (import, gated on the var), `group_vars/all/main.yml`

**Interfaces:**
- Consumes: `has_grub`, `quiet_boot_plymouth`. Produces: Plymouth in the initrd + a greetd hand-off.

- [ ] **Step 1: Write `roles/hardware/tasks/plymouth.yml`**

```yaml
---
# Plymouth graphical splash from initrd through to the greeter. dracut module
# (not a mkinitcpio HOOK); must own the screen before the LUKS prompt; greetd
# needs an explicit quit since it does not signal Plymouth itself.
- name: Install plymouth
  community.general.pacman:
    name: plymouth
    state: present

- name: Set the Plymouth theme
  ansible.builtin.command: plymouth-set-default-theme bgrt
  register: _ply_theme
  changed_when: "'already' not in _ply_theme.stdout | default('')"

- name: Add Plymouth to dracut
  ansible.builtin.copy:
    dest: /etc/dracut.conf.d/plymouth.conf
    content: |
      # Plymouth owns the screen before LUKS unlock; dracut orders sd-plymouth
      # before sd-encrypt automatically when both modules are present.
      add_dracutmodules+=" plymouth "
    mode: '0644'
  notify: Rebuild initramfs

- name: Add splash to the GRUB cmdline
  ansible.builtin.replace:
    path: /etc/default/grub
    regexp: '^(GRUB_CMDLINE_LINUX_DEFAULT=(["''])(?!.*\bsplash\b).*)\2\s*$'
    replace: '\1 splash\2'
  notify: Rebuild grub

- name: Tell greetd to hand off to Plymouth cleanly
  ansible.builtin.copy:
    dest: /etc/systemd/system/greetd.service.d/plymouth-quit.conf
    content: |
      [Service]
      ExecStartPre=/usr/bin/plymouth quit --retain-splash
    mode: '0644'
  notify: Reload systemd

- name: Enable Plymouth units
  ansible.builtin.systemd:
    name: "{{ item }}"
    enabled: true
  loop:
    - plymouth-start.service
    - plymouth-read-write.service
    - plymouth-quit-wait.service
```

- [ ] **Step 2: Add a `Rebuild initramfs` handler if absent**

```bash
grep -n "Rebuild initramfs\|reinstall-kernels\|dracut" roles/hardware/handlers/main.yml
```
If absent, add:
```yaml
- name: Rebuild initramfs
  ansible.builtin.command: reinstall-kernels
  changed_when: false
```

- [ ] **Step 3: Import gated on the var; add the var**

`roles/hardware/tasks/main.yml`:
```yaml
- name: Configure Plymouth splash
  ansible.builtin.import_tasks: plymouth.yml
  when: quiet_boot_plymouth | default(false) | bool
```
`group_vars/all/main.yml`: `quiet_boot_plymouth: false`.

- [ ] **Step 4: Verify**

```
ansible-lint && ansible-playbook --syntax-check site.yml
# With quiet_boot_plymouth=true, apply, reboot. Expect: splash from early initrd,
# covers the LUKS prompt, fades as greetd appears. If not:
journalctl -b 0 | grep -i plymouth
```

- [ ] **Step 5: Commit**

```bash
git add roles/hardware/tasks/plymouth.yml roles/hardware/tasks/main.yml roles/hardware/handlers/main.yml group_vars/all/main.yml
git commit -m "Quiet boot Tier 2 (optional): Plymouth graphical splash"
```

---

## Task 3: Verify steps + retire the source plan

**Files:**
- Modify: `scripts/gatherd-post-setup-notes`
- Delete: `plans/QUIET-BOOT.md`

- [ ] **Step 1: Add `section_verify` lines** — Tier 1: `grep -o 'quiet' /boot/grub/grub.cfg` present and the cmdline carries the four params once; reboot is quiet. Tier 2 (if enabled): the boot sequence shows the splash and `journalctl -b | grep -i plymouth` shows the units ran.
- [ ] **Step 2: Remove the source**
```bash
git rm plans/QUIET-BOOT.md
```
- [ ] **Step 3: Commit**
```bash
git add scripts/gatherd-post-setup-notes
git commit -m "Quiet boot: add verify steps; retire QUIET-BOOT.md"
```

## Self-Review

- **Coverage vs source:** Tier 1 params (`quiet` + `rd.udev.log_level=3` + `rd.systemd.show_status=auto`, `loglevel=3` kept) → Task 1; optional menu-hide → Task 1 Step 1 (gated var); Tier 2 Plymouth (dracut module, `splash`, greetd drop-in, units) → Task 2; escape hatch → Global Constraints; reverting → covered by idempotent re-run with the vars false + the `e`-edit. ✅
- **Placeholders:** all task code complete; the negative-lookahead anchors are concrete.
- **Consistency:** `quiet_boot_hide_menu`, `quiet_boot_plymouth`, `has_grub`, `Rebuild grub`, `Rebuild initramfs` used consistently.
