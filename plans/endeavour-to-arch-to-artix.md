# Plan: Migrate from EndeavourOS, to Arch, to Artix

## Context

gatherd currently automates first-boot configuration atop EndeavourOS
Sway Community Edition, which is not itself a fully automated install.
We want full install automation without needing to bake custom ISOs,
so we want to rebase onto Arch with `archinstall`.

(When all that's working reliably, we'll want to replace `systemd` with
`s6`, which probably means rebasing onto Artix.)

The EOS-specific surface is smaller than expected, with one deep
dependency: the `desktop` role only *patches* Sway config files that
`sway-install.sh` lays down. Making gatherd self-contained requires
internalizing those base configs before removing the EOS trigger.

---

## Inventory of EOS-specific dependencies

| What | Where | Notes |
|------|-------|-------|
| Calamares hook + `sway-install.sh` call | `postinstall` | The install trigger; Sway base config source |
| "Disable EOS greeter" task (`EOS-greeter.conf`) | `roles/desktop/tasks/main.yml:67-75` | EOS-only file |
| Sway base configs (default, autostart_applications, waybar, foot) | *not in repo* | Created by `sway-install.sh` |
| Broadcom `wl` driver detection + install | *not in repo* | EOS live ISO detects and offers this; gatherd needs to own it |

---

## Steps

### Step 1 — Replace the EOS greeter task with a generic greetd config
*Removes a dead task; adds the Arch equivalent.*

Files: `roles/desktop/tasks/main.yml`
- Remove "Disable EOS greeter" block (lines 67–75, writes `~/.config/EOS-greeter.conf`)
- Add task to write `/etc/greetd/config.toml` configuring autologin to Sway for the target user

**Test:** greetd auto-logs in to Sway after first-boot setup on a clean Arch VM.

---

### Step 2 — Handle Broadcom `wl` driver
*EOS live install detects Broadcom wifi and offers to install the out-of-tree driver. Vanilla
Arch won't do this, so gatherd must detect and install it, and the bootstrap must handle the
live-environment chicken-and-egg problem.*

**Post-install (Ansible side):**

- `roles/machine_facts/tasks/main.yml`: add `has_broadcom_wifi` probe using `lspci -n`.
  Broadcom wifi PCI IDs include `14e4:4311`, `14e4:4312`, `14e4:4313`, `14e4:4315`,
  `14e4:4318`, `14e4:4319`, `14e4:431a`, `14e4:4320`, `14e4:4324`, `14e4:4325`,
  `14e4:4328`, `14e4:4329`, `14e4:432b`, `14e4:432c`, `14e4:432d`, `14e4:4331`,
  `14e4:4335`, `14e4:4339`, `14e4:43a0`, `14e4:43b1` — match with a regex
  `'14e4:(43[0-9a-f]{2}|431[0-9a-f]|43[0-9a-f]{2})'` or a curated whitelist.

- `roles/hardware/tasks/broadcom_wifi.yml` (new file): install `broadcom-wl-dkms` (AUR),
  write `/etc/modprobe.d/broadcom-wl.conf` to blacklist conflicting `b43`, `b43legacy`,
  `ssb`, `bcma`, `brcmsmac`, `brcmfmac` modules, and run `modprobe wl`.

- `roles/hardware/tasks/main.yml`: add dispatch block mirroring the existing pattern:
  ```yaml
  - name: Import Broadcom wifi tasks
    ansible.builtin.import_tasks: broadcom_wifi.yml
    when: has_broadcom_wifi
  ```

**During bootstrap (live environment):**

The Arch ISO does not ship the `wl` module. If the target machine has only Broadcom wifi
(no ethernet), the bootstrap script cannot reach the network to run `pacstrap`.

Options in order of preference:
1. **Use ethernet for bootstrap** — document this as a requirement in `bootstrap.sh` and
   README; the Ansible role handles wifi after first boot.
2. **Auto-detect and load `wl` in `bootstrap.sh`** — before any network operations, probe
   `lspci -n` for Broadcom PCI IDs, and if found: install `broadcom-wl` (available in
   `archlinux-keyring` / AUR, or carry it on a second USB), blacklist conflicting modules,
   run `modprobe wl`. This is fragile on the live ISO but avoids the ethernet requirement.
3. **Use a custom Arch ISO** with `broadcom-wl` pre-loaded — most robust but requires
   maintaining an ISO build.

Option 1 is the starting point; document the constraint clearly. Option 2 can be added
later if needed.

**Test:** On a machine with a Broadcom wifi card (no ethernet), run `bootstrap.sh` via
ethernet, reboot, confirm wifi is working in the Sway session (NetworkManager / `wl`
module loaded, no conflicting modules).

---

### Step 3 — Replace `postinstall` with an Arch bootstrap
*Swaps the Calamares trigger for a fully scriptable Arch install.*

- Keep `postinstall` intact (rename to `postinstall.eos`) until this step is proven
- **Ethernet required** for bootstrap if the machine has Broadcom wifi (see Step 2).
  Document this prominently at the top of `bootstrap.sh`.

**Disk layout — mirrors what EOS Calamares creates:**

```
sda1  EFI         ~512 MB   unencrypted, vfat
sda2  LUKS2       rest      → btrfs root (@, @home, @log, @pkg, @snapshots)
sda3  LUKS2       ≥ RAM     → swap partition
```

This is the same layout EOS Calamares uses and avoids the btrfs swapfile offset
calculation entirely — resume just points to the opened swap device.

archinstall accepts `--config <json>` and `--creds <json>` for fully unattended installs.
It handles LUKS2 encryption, btrfs subvolumes, bootloader config (systemd-boot or GRUB)
with LUKS unlock parameters, and the `encrypt` mkinitcpio hook. Whether it supports a
two-LUKS-container layout (root + separate swap) needs verification; if not, the partition
creation steps run via `sgdisk`/`cryptsetup`/`mkfs` before calling archinstall in
filesystem-only mode, or archinstall is skipped entirely in favour of a raw pacstrap script.

**Parameterization — all scriptable, no prompts needed:**

| Value | Mechanism |
|---|---|
| Hostname | `--config` JSON → `"hostname"` field |
| Username | `--creds` JSON → `!users[0].username` |
| User password | `--creds` JSON → `!users[0].!password` (plaintext, file deleted after install) |
| Disk passphrase | `--creds` JSON → `!encryption-password` (also plaintext) |
| Swap size | `awk '/MemTotal/{print $2}' /proc/meminfo` in `bootstrap.sh`, round up to next GiB |
| Disk device | Auto-detect (largest unpartitioned disk) or specify via env var |

Setting password == passphrase: read one value, write it to both JSON fields.

**Hibernate — what archinstall does NOT do (post-install `arch-chroot` block):**

EOS Calamares sets up the infrastructure but also does not configure `resume=`. The gap
is the same; the fix is simpler than with a swapfile because there is no offset to compute:

1. Generate a keyfile, add it as a LUKS key on `sda3` (swap), embed it in the initramfs
   so swap unlocks automatically after root is unlocked — one passphrase prompt:
   ```sh
   dd if=/dev/urandom of=/mnt/etc/cryptsetup-keys.d/cryptswap.key bs=512 count=4 iflag=fullblock
   chmod 600 /mnt/etc/cryptsetup-keys.d/cryptswap.key
   cryptsetup luksAddKey /dev/sda3 /mnt/etc/cryptsetup-keys.d/cryptswap.key
   ```

2. Write `/etc/crypttab` entry for swap (mirrors what EOS Calamares writes):
   ```
   cryptswap  /dev/sda3  /etc/cryptsetup-keys.d/cryptswap.key  luks
   ```

3. Install `mkinitcpio-openswap`, add `openswap` hook to mkinitcpio after `encrypt`
   and before `resume`, add `resume` hook. Add `resume=/dev/mapper/cryptswap` to the
   bootloader kernel parameters. Run `mkinitcpio -P`.

This entire block runs in `bootstrap.sh` via `arch-chroot` immediately after archinstall.

**Create `bootstrap.sh` that:**
- Accepts hostname, username, password as env vars (fully headless); falls back to prompts
- Detects target disk and RAM size
- Creates partition table (`sgdisk`): EFI + root LUKS + swap LUKS
- Opens both LUKS containers, formats root as btrfs, creates subvolumes, formats swap
- Generates ephemeral `config.json` and `creds.json`, runs `archinstall --config --creds`
  (or raw `pacstrap` if archinstall can't handle pre-formatted devices cleanly)
- `arch-chroot`: keyfile generation, crypttab, openswap hook, resume kernel param,
  mkinitcpio, ansible + git install, gatherd clone, `systemctl enable gatherd`
- Clones EOS Sway CE to `/mnt/tmp/sway-ce` and runs `sway-install.sh` with username
  injected (see Step 2); this deploys all upstream Sway configs and enables greetd.
  gatherd's Ansible patches apply on top at first boot.
- Wipes creds JSON and `/mnt/tmp/sway-ce` before exit, reboots

`gatherd.service` already references `greetd.service` — greetd is enabled by `sway-install.sh`.

**Test:** Boot Arch ISO in QEMU, run `bootstrap.sh` in env-var mode, reboot. Confirm Sway
session. Verify hibernate: `systemctl hibernate`, power off VM, resume — session restored.
Zero keystrokes after launching the script.

---

### Step 4 — Clean up docs and remove EOS artifacts
- `README.md`: replace EOS install steps with Arch bootstrap instructions
- `TODO.md`: prune EOS-specific entries and links
- Delete `postinstall.eos` once `bootstrap.sh` has been proven on multiple machines

**Test:** `grep -rE 'EndeavourOS|endeavour|EOS' . --exclude-dir=.git` returns nothing in
active code paths.

---

## Verification (end-to-end)

1. Boot Arch ISO in QEMU (or bare metal)
2. Run `bash <(curl -fsSL …/bootstrap.sh)` — no further input
3. System reboots, `gatherd.service` fires, playbook completes
4. Sway session is usable, all configured services running, hardware quirks applied
5. `/etc/gatherd/complete` exists; service does not re-run on next boot

---

## Notes for subsequent Artix/s6 migration

Steps 1–4 leave systemd intact. The already-completed renames (`/etc/gatherd/complete`,
`/usr/local/lib/gatherd`) mean the first-boot marker and service directory are already
init-system-neutral. Steps 1–3 do not add new systemd dependencies. Step 3's bootstrap
script will need a parallel `bootstrap-artix.sh` when that migration happens.
