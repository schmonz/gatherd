# Quiet boot on EndeavourOS (GRUB + dracut)

System: EndeavourOS, GRUB, dracut, greetd, LUKS.

> **Bootloader note.** An earlier draft of this plan targeted systemd-boot
> (`/etc/kernel/cmdline`, `reinstall-kernels`, `/efi/loader/entries/*.conf`).
> This machine now boots with **GRUB**, so the cmdline source of truth is
> `/etc/default/grub` (`GRUB_CMDLINE_LINUX_DEFAULT`) and entries are regenerated
> with `grub-mkconfig`. dracut is still the initramfs generator, so the
> Plymouth half (Tier 2) is largely unchanged.

Two tiers:

- **Tier 1** — suppress boot messages with no new packages (quick, reversible)
- **Tier 2** — add Plymouth for a graphical splash like Manjaro/Mint (more involved)

Tier 1 is a prerequisite for Tier 2.

## Playbook fit

`roles/hardware/tasks/zswap.yml` already edits `GRUB_CMDLINE_LINUX_DEFAULT` with
`ansible.builtin.replace`, gated `when: has_grub`, and notifies the existing
`Rebuild grub` handler (`grub-mkconfig -o /boot/grub/grub.cfg`). Tier 1 follows
that exact pattern — a new tiny task file under `roles/hardware/tasks/` (e.g.
`quiet_boot.yml`) appending the quiet params and reusing the `Rebuild grub`
handler.

Note the current cmdline **already contains `loglevel=3`**, so only the
remaining three params below need adding (and the `replace` regexp must be
idempotent against the value already present, like zswap's negative-lookahead).

---

## Tier 1 — Suppress boot messages

### Step 1 — Add the quiet params to the GRUB cmdline

Append to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`:

```
quiet rd.udev.log_level=3 rd.systemd.show_status=auto
```

(`loglevel=3` is already present on this system; keep it.)

| Parameter | Effect |
|---|---|
| `quiet` | Tells the kernel to suppress most console messages |
| `loglevel=3` | Kernel ring-buffer print threshold = ERR; only genuine errors surface |
| `rd.udev.log_level=3` | Same ERR threshold for udev during the dracut initrd phase (suppresses device-enumeration chatter around LUKS unlock) |
| `rd.systemd.show_status=auto` | In-initrd systemd prints unit status only on failure; clean boots stay silent, broken boots show what failed |

### Step 2 — Regenerate the GRUB config

```bash
sudo grub-mkconfig -o /boot/grub/grub.cfg
```

Verify the change landed:

```bash
grep -o 'quiet.*' /boot/grub/grub.cfg | head
```

### Step 3 — Escape hatch (no separate verbose entry needed)

This system sets `GRUB_DISABLE_RECOVERY='true'`, so there is **no** standing
verbose recovery entry to maintain (unlike systemd-boot's fallback `.conf`).
The escape hatch when a boot goes wrong is GRUB's one-shot edit:

- At the GRUB menu, press **e** on the entry, find the `linux …` line, remove
  `quiet` (and/or change `loglevel=3` to `loglevel=7`), then **Ctrl-X** to boot
  once verbosely. Nothing is persisted.

If you'd rather have a permanent verbose entry, set
`GRUB_DISABLE_RECOVERY='false'` and re-run `grub-mkconfig`; a "(recovery mode)"
entry appears that boots without the quiet params.

### Step 4 (optional) — Hide the boot menu

`/etc/default/grub` currently has `GRUB_TIMEOUT='5'` and
`GRUB_TIMEOUT_STYLE=menu`, so the menu shows for 5s every boot. To skip it (like
Mint/Manjaro hide their menu):

```
GRUB_TIMEOUT='0'
GRUB_TIMEOUT_STYLE=hidden
```

Re-run `grub-mkconfig`. The menu is still reachable by **holding Shift** (BIOS)
or **pressing Esc repeatedly** right after firmware handoff.

---

## Tier 2 — Plymouth graphical splash (optional)

Plymouth puts an animated logo/spinner on screen from early in the initrd
through to the greeter, covering residual console output — what Mint/Manjaro do.

Complexity on this system comes from three sources (unchanged from the
systemd-boot draft except where noted):

1. **dracut** instead of mkinitcpio — Plymouth is a dracut module, not a HOOK
2. **LUKS** — Plymouth must own the screen before the passphrase prompt
3. **greetd** — unlike GDM/SDDM/LightDM, greetd does not natively signal
   Plymouth to quit; a small drop-in is needed

### Step 5 — Install Plymouth and a theme

```bash
sudo pacman -S plymouth
plymouth-set-default-theme --list
```

BGRT (firmware OEM logo, no AUR) needs no download; the EndeavourOS theme is in
the AUR:

```bash
# Option A — OEM/firmware logo (no AUR)
sudo plymouth-set-default-theme bgrt

# Option B — EndeavourOS branded theme
paru -S plymouth-theme-endeavouros
sudo plymouth-set-default-theme endeavouros
```

### Step 6 — Add Plymouth to dracut

Create `/etc/dracut.conf.d/plymouth.conf`:

```bash
sudo tee /etc/dracut.conf.d/plymouth.conf <<'EOF'
# Load Plymouth in the initrd so it owns the screen before LUKS unlock.
# sd-plymouth must come before sd-encrypt in the module chain;
# dracut handles ordering automatically when both are declared here.
add_dracutmodules+=" plymouth "
EOF
```

### Step 7 — Add `splash` to the GRUB cmdline

Add `splash` alongside `quiet` in `GRUB_CMDLINE_LINUX_DEFAULT`
(`/etc/default/grub`, the same line edited in Tier 1 Step 1):

```
... quiet splash loglevel=3 rd.udev.log_level=3 rd.systemd.show_status=auto
```

`splash` is the signal Plymouth watches for; without it Plymouth installs into
the initrd but stays inactive.

### Step 8 — Rebuild the initramfs and GRUB config

```bash
sudo reinstall-kernels          # reruns dracut with the Plymouth module baked in
sudo grub-mkconfig -o /boot/grub/grub.cfg   # picks up the new cmdline
```

(On GRUB the cmdline change requires the `grub-mkconfig` step explicitly —
unlike systemd-boot, where `reinstall-kernels` rewrote the entries in one pass.)

### Step 9 — Tell greetd to hand off to Plymouth cleanly

greetd does not call `plymouth quit` on its own. Without this, Plymouth lingers
and the login screen never appears. Add a systemd drop-in:

```bash
sudo mkdir -p /etc/systemd/system/greetd.service.d
sudo tee /etc/systemd/system/greetd.service.d/plymouth-quit.conf <<'EOF'
[Service]
# Quit Plymouth and hand control of the VT to greetd.
ExecStartPre=/usr/bin/plymouth quit --retain-splash
EOF
```

`--retain-splash` keeps the splash a moment longer while greetd initialises,
avoiding a flash of console text.

### Step 10 — Enable the Plymouth systemd units

```bash
sudo systemctl enable plymouth-start.service
sudo systemctl enable plymouth-read-write.service
sudo systemctl enable plymouth-quit-wait.service
```

### Verify

Reboot. The sequence should be:

1. Firmware POST
2. GRUB selects the entry (instantly if `GRUB_TIMEOUT=0`, else after the menu)
3. Plymouth splash appears — covers the LUKS passphrase prompt graphically
4. After unlock: spinner continues while the OS comes up
5. Plymouth fades out as greetd presents the login prompt
6. Log in; desktop loads normally

If the splash does not appear, boot verbosely (Step 3 escape hatch) and check:

```bash
journalctl -b 0 | grep -i plymouth
```

---

## Reverting

```bash
# Remove quiet/splash params from the cmdline
sudo nano /etc/default/grub   # drop: quiet splash rd.udev.log_level=3 rd.systemd.show_status=auto
                              # (leave loglevel=3 — it was there originally)

# Remove Plymouth dracut config (if added)
sudo rm -f /etc/dracut.conf.d/plymouth.conf

# Remove greetd drop-in (if added)
sudo rm -f /etc/systemd/system/greetd.service.d/plymouth-quit.conf

# Rebuild both
sudo reinstall-kernels
sudo grub-mkconfig -o /boot/grub/grub.cfg

# Restore the boot menu (if changed)
sudo nano /etc/default/grub   # restore: GRUB_TIMEOUT='5', GRUB_TIMEOUT_STYLE=menu
sudo grub-mkconfig -o /boot/grub/grub.cfg
```
