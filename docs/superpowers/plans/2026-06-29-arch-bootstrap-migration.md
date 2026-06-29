# EOS → Arch Bootstrap Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

> **Domain note on "tests":** this is provisioning/installer work. Verification is QEMU boots of the Arch ISO running `bootstrap.sh`, `ansible-lint`/`--syntax-check`, idempotent converge, and observed first-boot behavior — not pytest. The riskiest steps are validated in a VM before any real machine.

**Goal:** Replace the EndeavourOS Calamares install path with a fully scriptable Arch bootstrap, so gatherd provisions a machine end-to-end from the stock Arch ISO with zero custom-ISO maintenance — and over WiFi, with no ethernet assumption.

**Architecture:** A `bootstrap.sh` run from the Arch ISO partitions/encrypts the disk, `pacstrap`s (or `archinstall`s) a base system, seeds one working network connection, installs ansible + gatherd, and enables `gatherd.service`; gatherd's roles then converge on first boot exactly as today. EOS-specific surface is internalized first so removing the EOS trigger doesn't lose base Sway config.

**Tech Stack:** Arch ISO tooling (`iwctl`, `pacstrap`/`archinstall`, `arch-chroot`, `sgdisk`, `cryptsetup`, `mkfs.btrfs`), GRUB, dracut/mkinitcpio, Ansible.

**Source:** supersedes `plans/ARTIX.md` (removed in the conversion commit). **Scope:** the EOS→Arch migration (the actionable part). The subsequent Arch→Artix/s6 move stays a documented future program (see §Future). Per the travel-repave north-star (`docs/superpowers/specs/2026-06-29-travel-repave-design.md`), this plan **owns install-time disk/swap/hibernate correctness**.

## Global Constraints

- **FQCN; tiny task files; `ansible-lint` clean before commit; idempotent** (`CLAUDE.md`).
- **No ethernet assumption** — bootstrap and first boot must come up over WiFi (Step/Task 3 below). Broadcom `wl` is the one card class that needs the driver staged on the USB.
- **Keep the EOS path working until the Arch path is proven** — rename `postinstall` → `postinstall.eos`, don't delete it until `bootstrap.sh` is proven on multiple machines.
- **Validate the riskiest steps in QEMU first** — especially the disk-layout/archinstall path (Task 1 spike) before any real hardware.
- **No new systemd coupling** beyond what exists; keep runtime logic in POSIX scripts (eases the later Artix/s6 move).

## EOS-specific surface to internalize (the migration's real work)

| What | Where | Action |
|---|---|---|
| Calamares hook + `sway-install.sh` call | `postinstall` | Replaced by `bootstrap.sh` (Task 4) |
| "Disable EOS greeter" task (`EOS-greeter.conf`) | `roles/desktop/tasks/main.yml` | Replace with generic greetd config (Task 2) |
| Sway base configs (default, autostart, waybar, foot) | *not in repo* — created by `sway-install.sh` | `bootstrap.sh` clones + runs `sway-install.sh`; gatherd patches on top (Task 4) |
| Broadcom `wl` driver detection/install | EOS live ISO does this | gatherd must own it (Task 3) |

---

## Task 1: Phase-0 spike — disk layout + WiFi-in-ISO capability

*Resolve the one open unknown before writing `bootstrap.sh`: it forks Step 3's partition path. Cheap; do it first.*

**Files:** none (a recorded finding appended to this plan).

**Interfaces:** Produces a decision — **archinstall-handles-two-LUKS** (use `archinstall --config --creds`) vs **manual partitioning** (`sgdisk`/`cryptsetup`/`mkfs` then archinstall filesystem-only, or raw `pacstrap`).

- [ ] **Step 1: Determine archinstall's two-LUKS support**

In a QEMU VM booted from the current Arch ISO, test whether `archinstall --config <json> --creds <json>` can produce the target layout: EFI (unencrypted vfat) + LUKS2→btrfs root (`@,@home,@log,@pkg,@snapshots`) + **separate LUKS2 swap partition** (≥ RAM, for hibernate). Record whether it supports the two-container layout natively.

- [ ] **Step 2: Confirm WiFi-in-ISO for the common card**

Confirm `iwctl --passphrase "$PSK" station wlan0 connect "$SSID"` works from the ISO for an in-kernel-driver card, and that `pacstrap` then runs over WiFi. Record.

- [ ] **Step 3: Record the decision in this plan**

Append under this task: **PATH A** (archinstall does it all) or **PATH B** (manual partition block, archinstall fs-only / raw pacstrap). Task 4 follows the chosen path. **Result:** ______

---

## Task 2: Generic greetd config (replace the EOS greeter)

**Files:**
- Modify: `roles/desktop/tasks/main.yml` (remove the "Disable EOS greeter" block that writes `~/.config/EOS-greeter.conf`)
- Create: a task writing `/etc/greetd/config.toml` for autologin to Sway as the target user

**Interfaces:** Produces a vendor-neutral greetd autologin, independent of EOS.

- [ ] **Step 1: Remove the EOS greeter task**

```bash
grep -n "EOS-greeter\|Disable EOS greeter" roles/desktop/tasks/main.yml
```
Delete that block.

- [ ] **Step 2: Add a generic greetd config task** (tiny task file, e.g. `roles/system/tasks/greetd.yml` or within the desktop role per where greetd is configured today) writing `/etc/greetd/config.toml` with an `initial_session` autologin to `sway` for `{{ target_user }}` and a `default_session` greeter. Match the current greetd behavior already observed on the fleet (vt1, autologin).

- [ ] **Step 3: Verify**

```
ansible-lint && ansible-playbook --syntax-check site.yml
# On a clean Arch VM: greetd auto-logs in to Sway after first-boot setup.
```

- [ ] **Step 4: Commit** — `git commit -m "Replace EOS greeter task with a generic greetd autologin config"`

---

## Task 3: WiFi during bootstrap + Broadcom driver ownership

*Three places must get online, solved separately; Broadcom `wl` is the one sub-case needing the USB.*

**Files:**
- Create: `roles/machine_facts/` probe `has_broadcom_wifi`; `roles/hardware/tasks/broadcom_wifi.yml`; dispatch in `roles/hardware/tasks/main.yml`
- (`bootstrap.sh` WiFi seeding lands in Task 4)

**Interfaces:** Produces `has_broadcom_wifi` + a post-install driver install path. The USB-staging side shares the stick built by the robust-convergence offline-cache plan.

- [ ] **Step 1: `has_broadcom_wifi` probe** in `machine_facts` (one `lspci -n` read — already collected as `_lspci` — + `set_fact`), matching Broadcom wifi PCI IDs (`14e4:43xx` family; use the curated list from the source plan or a `14e4:43..` regex).

- [ ] **Step 2: `roles/hardware/tasks/broadcom_wifi.yml`** — install `broadcom-wl-dkms` (AUR), write `/etc/modprobe.d/broadcom-wl.conf` blacklisting `b43 b43legacy ssb bcma brcmsmac brcmfmac`, `modprobe wl`. Dispatch from `roles/hardware/tasks/main.yml` `when: has_broadcom_wifi`.

- [ ] **Step 3: Verify** — `ansible-lint`; on a Broadcom box, `wl` loads and no conflicting modules; on others the task is skipped.

- [ ] **Step 4: Commit** — `git commit -m "Own Broadcom wifi driver install (probe + hardware task)"`

(The three online-points — ISO `iwctl`, installed-system seeded connection, steady-state `wifi.yml` — are realized in `bootstrap.sh`, Task 4; `wifi.yml` already handles steady state.)

---

## Task 4: `bootstrap.sh` (replace `postinstall`)

*The core deliverable. Follows the Task 1 spike's PATH A/B for partitioning. Validate in QEMU before any real machine.*

**Files:**
- Create: `bootstrap.sh`
- Rename: `postinstall` → `postinstall.eos` (keep until proven)

**Interfaces:** Produces a from-ISO installer that lands a first-bootable, online Arch system with `gatherd.service` enabled.

- [ ] **Step 1: Rename the EOS hook** — `git mv postinstall postinstall.eos`.

- [ ] **Step 2: Scaffold `bootstrap.sh`** (env-var driven, prompt fallback) that:
  1. Accepts `HOSTNAME`/`USERNAME`/`PASSWORD` (+ `WIFI_SSID`/`WIFI_PSK`) as env vars; prompts if absent.
  2. Connects WiFi (`iwctl`) and **verifies connectivity (ping/DNS) before proceeding** so a portal/no-link fails fast with a clear message, not a cryptic `pacstrap` error.
  3. Detects target disk + RAM (`awk '/MemTotal/' /proc/meminfo`, round up to next GiB for swap).
  4. Creates the layout per the spike: EFI + LUKS2 root (btrfs subvols `@,@home,@log,@pkg,@snapshots`) + LUKS2 swap (≥ RAM). **PATH A:** ephemeral `config.json`+`creds.json` → `archinstall --config --creds`. **PATH B:** `sgdisk`/`cryptsetup`/`mkfs.btrfs` then archinstall fs-only or raw `pacstrap`.
  5. `arch-chroot` block — **hibernate** (no swapfile offset needed with a swap partition): generate a keyfile, `cryptsetup luksAddKey` the swap, write `/etc/crypttab` (`cryptswap … luks`), install `mkinitcpio-openswap`, add `openswap`+`resume` hooks, add `resume=/dev/mapper/cryptswap` to the GRUB cmdline, rebuild initramfs.
  6. Seed **one** NetworkManager (or iwd) connection from the bootstrap creds and `systemctl enable NetworkManager` so first boot is already online (gatherd's `wifi.yml` then writes the full set).
  7. Install ansible + git, clone gatherd to `/usr/local/lib/gatherd`, `systemctl enable gatherd`.
  8. Clone EOS Sway CE to `/mnt/tmp/sway-ce`, run `sway-install.sh` with the username injected (deploys upstream Sway base configs + enables greetd; gatherd patches on top).
  9. Wipe creds JSON + `/mnt/tmp/sway-ce`, reboot.

- [ ] **Step 3: Document the ethernet caveat** prominently at the top of `bootstrap.sh` (Broadcom-wifi machines need ethernet or the USB-staged driver for bootstrap).

- [ ] **Step 4: Verify in QEMU** — boot the Arch ISO, run `bootstrap.sh` in env-var mode, reboot: confirm a Sway session; `systemctl hibernate` then resume restores the session; zero keystrokes after launch.

- [ ] **Step 5: Commit** — `git commit -m "Add bootstrap.sh: scriptable Arch install replacing the EOS Calamares hook"`

---

## Task 5: Docs/artifact cleanup

**Files:** `README.md`, `plans/TODO.md`, eventually delete `postinstall.eos`.

- [ ] **Step 1:** `README.md` — replace EOS install steps with Arch bootstrap instructions.
- [ ] **Step 2:** `plans/TODO.md` — prune EOS-specific entries; the no-swap/hibernate item is now owned here (Task 4 step 5).
- [ ] **Step 3:** Delete `postinstall.eos` **only after** `bootstrap.sh` is proven on multiple machines. (Leave it for now; note the gate.)
- [ ] **Step 4:** Verify `grep -rE 'EndeavourOS|endeavour|EOS' . --exclude-dir=.git` returns nothing in active code paths (docs/historical excepted).
- [ ] **Step 5: Commit.**

---

## Task 6: End-to-end verification + retire the source plan

- [ ] **Step 1: Full QEMU run** — boot Arch ISO, `bash <(curl -fsSL …/bootstrap.sh)`, no further input; system reboots, `gatherd.service` fires, playbook completes; Sway usable, services running, hardware quirks applied; `/etc/gatherd/complete` exists; no re-run next boot. Add the key checks to `section_verify`.
- [ ] **Step 2: Retire the source** — `git rm plans/ARTIX.md`.
- [ ] **Step 3: Commit.**

---

## Future (out of scope for this plan): Arch → Artix / s6

Carried from the source plan's migration notes; do NOT start until the Arch path is proven:

- Steps 1–5 leave systemd intact. The already-done renames (`/etc/gatherd/complete`, `/usr/local/lib/gatherd`) keep the first-boot marker and service dir init-neutral.
- `bootstrap.sh` will need a parallel `bootstrap-artix.sh` (basestrap, s6-rc service install) when that migration happens.
- The **early vault prompt** is the one console-coupled piece: swap `systemd-ask-password --no-tty` for an `openvt`-wrapped read loop; ordering becomes an s6-rc dependency edge (see `docs/superpowers/plans/...` vault work and the travel-repave spec).
- The robust-convergence **offline USB cache** is init-agnostic and its driver-staging stick is the same one Task 3 uses for Broadcom `wl`.

## Self-Review

- **Coverage vs source ARTIX.md:** Step 1 (greetd) → Task 2; Step 2 (WiFi/Broadcom) → Task 3 + Task 4 steps 2/6; Step 3 (bootstrap.sh/disk/hibernate, incl. the archinstall unknown) → Task 1 spike + Task 4; Step 4 (cleanup) → Task 5; end-to-end verify → Task 6; Artix/s6 notes → §Future. ✅
- **Placeholder scan:** the one genuine unknown (archinstall two-LUKS) is an explicit Task 1 spike whose result forks Task 4 — not a buried TODO. `bootstrap.sh` is specified as a concrete 9-point scaffold; its exact partition commands depend on the spike and QEMU iteration, flagged honestly rather than fabricated.
- **Consistency:** `has_broadcom_wifi`, `bootstrap.sh`, `postinstall.eos`, PATH A/B used consistently.
