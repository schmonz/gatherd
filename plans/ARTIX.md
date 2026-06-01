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

### Step 2 — Bring up WiFi during bootstrap (no ethernet assumption)
*The original plan assumed ethernet for the live-environment `pacstrap`. That breaks the
travel case the whole machine is built for: the only link may be WiFi. Bootstrap must connect
over WiFi, and the installed system must come up on WiFi **before** gatherd's first package
download. Broadcom's out-of-tree `wl` is a sub-case of this, not the whole story — most cards
just work; the plan has to make the common case automatic and the awkward case possible.*

**Three places to get online, each solved separately:**

**1. Live ISO — before `pacstrap`/`archinstall`.**
The Arch ISO ships `iwd`; `iwctl` connects scriptably, so for any in-kernel-driver card
(the common case, see table) this is the whole job:
```sh
iwctl --passphrase "$WIFI_PSK" station wlan0 connect "$WIFI_SSID"
```
Creds can't come from the Ansible vault yet (not decryptable this early — the
single-credential-bootstrap and vault-on-disk items in TODADO bear on this), so `bootstrap.sh`
takes `WIFI_SSID`/`WIFI_PSK` as env vars or prompts, mirroring its existing headless/prompt
fallback. A **captive portal** in the live environment is out of scope for bootstrap (it needs
a browser — see the captive-portal saga in TODO); assume an open or PSK network here, or
tether. Verify connectivity (`ping`/DNS) before proceeding so a portal/no-link fails fast with
a clear message instead of a cryptic `pacstrap` error.

**2. Installed system, first boot — before gatherd installs packages.**
gatherd needs DNS + network for its very first package tasks, and its own `wifi.yml` runs far
too late to bootstrap connectivity for itself. So the `arch-chroot` block must seed **one**
working connection from the same bootstrap creds and enable the manager:
```sh
# write /etc/NetworkManager/system-connections/<ssid>.nmconnection (mode 0600), then:
systemctl enable NetworkManager
```
This is the minimum to reach a first boot that's already online; gatherd then writes the full
`wifi_networks` set on top. (If the installed system uses iwd rather than NetworkManager,
seed `/var/lib/iwd/<ssid>.psk` instead — pick one manager and be consistent with `wifi.yml`.)

**3. Post-first-boot — steady state.**
Already handled: `roles/system/tasks/wifi.yml` writes every known network from the vault.

**Driver classes — what the ISO can drive vs what needs help:**

| Class | Examples | On Arch ISO? | Action |
|---|---|---|---|
| In-kernel | Intel `iwlwifi`, Atheros `ath9k/10k/11k`, MediaTek `mt76`, most Realtek `rtw88/89` | Yes (firmware in `linux-firmware`) | None — `iwctl` just works |
| Out-of-tree DKMS | Broadcom `wl`, some Realtek USB (`rtl8821au` etc.) | **No** | Chicken-and-egg — see below |

**Out-of-tree driver chicken-and-egg (Broadcom `wl` and friends).**
The card can't reach the network to fetch the driver the network needs. Options, in order of
preference:
1. **Stage the driver on the boot USB.** The Ventoy/USB-mirror TODO ("Automate preparing a
   local package mirror on a USB stick") is the natural carrier: drop `broadcom-wl-dkms` (plus
   `dkms` + kernel headers, or a prebuilt `broadcom-wl` matching the ISO kernel) on the stick;
   `bootstrap.sh` `pacman -U`s it from the USB before any network step, blacklists conflicts,
   `modprobe wl`. Solves travel cleanly with no custom ISO.
2. **Custom Arch ISO** with the driver baked in — most robust, but reintroduces the ISO
   maintenance burden we left EOS to escape.
3. **Tether** (USB phone / USB-ethernet) for bootstrap only — a documented manual fallback,
   not automation.

**Post-install Broadcom driver (Ansible side — for the installed system, unchanged):**

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

**Test (common case):** On an Intel/Atheros laptop with **no ethernet**, boot the Arch ISO,
run `bootstrap.sh` with `WIFI_SSID`/`WIFI_PSK` set; confirm it connects via `iwctl`, `pacstrap`
runs over WiFi, and first boot comes up online (gatherd installs packages with no ethernet ever
attached).
**Test (Broadcom case):** Same on a Broadcom-only laptop with the driver staged on the USB;
confirm `wl` loads from the USB before any network step, the rest proceeds identically, and
WiFi works in the Sway session (`wl` loaded, no conflicting modules).

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
