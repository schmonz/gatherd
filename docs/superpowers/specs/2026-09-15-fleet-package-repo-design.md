# Fleet Package Repository — Design

**Type:** New subsystem. Builds AUR and vendored packages once, for every machine,
and delivers them by USB stick or network through one code path.

**Date:** 2026-09-15
**Status:** Draft. Two decisions open (§6). Not yet implemented.
**Related:** `specs/2026-06-29-travel-repave-design.md` (D1, D2, D9: the stick as a
first-class repave source), `plans/2026-06-29-robust-convergence.md` Task 5
(Phase 4, offline USB cache) and Task 6 (Phase 5, CI),
`specs/2026-09-07-first-login-cohort-design.md` (the session barrier).

---

## 1. Problem

Every machine builds every AUR package into its own `/var/cache/gatherd-aur`
(`aur sync`, a `file://` repo), on every repave and for every upgrade after it.
Many machines are underpowered.

Measured on squirrel-zapper's 2026-09-14 repave (4 cores, 7G; journal of
`gatherd-async.service`, build-directory and package mtimes):

- REST ran 23m49s, 13:46:18 to 14:10:07: 39m59s of CPU, 6.1G memory peak, swap
  touched. The cohort spec's 2026-09-07 repave wrote `async-complete` 16 minutes
  after session start.
- Real compiles: `arch-update` ~4 min (cargo plus its test suite), `nowayprompt`
  3m02s (cargo, vendored since 2026-08-21).
- The other ~26 AUR packages repackage vendor binaries: download, extract, zstd.
  Roughly 6–7 minutes together; `zoom` (366M) ~1 min, `claude-desktop` ~40s
  (Anthropic's `.deb`, 172M).
- Downloads of repo packages were about 3 minutes of task time. The run is bound
  by CPU and memory, not network, so a faster link barely helps.

Separately, the session barrier (`gatherd-await-async`, since 4785c25) holds most
session helpers until `async-complete`, which is written after the slow tiers.
The first session stays sparse for the whole run.

## 2. Goals

- No machine compiles or repackages anything it could have fetched.
- The USB stick alone is enough to bootstrap a machine (travel-repave D1). The
  network is the other delivery of the same artifact, not a second design.
- Packages are trusted by signature, not by who could write to a directory.
- A missing or stale fleet repo degrades to today's behaviour, never to failure.

## 3. Design

### 3.1 The artifact

One tree per architecture, exactly what Phase 4 already specifies for the stick:
a pacman repo (`repo-add` database plus `.pkg.tar.zst`) holding the AUR and
vendored packages, the official-repo closure the offline-core set needs, and a
manifest stamped with the gatherd git HEAD it was built from. Packages and
database are signed with a gatherd key.

### 3.2 Building

One builder runs `aur sync` for everything the `*_packages` vars and vendored
PKGBUILDs name, into that tree. Candidates (§6): CI in an Arch container, which
Phase 5 already anticipates, or the fleet's most powerful machine on a timer.
Underpowered machines never build.

### 3.3 Delivery

- **Stick present:** the tree on the stick.
- **No stick:** REST downloads the same tree into a local cache first. The
  download credential lives in the ansible vault, which is unlocked before REST
  (`vault-complete` 13:46:43 on the repave above).

Either way pacman then reads a `file://` repo, so the two deliveries share one
install path. A package the fleet repo lacks still builds locally, as today.

### 3.4 Trust

The gatherd public key is installed in CORE (no network needed) and the fleet
repo uses `SigLevel = Required`. That also retires the backlog item about
`/var/cache/gatherd-aur` being user-writable while root installs from it.

### 3.5 Upgrades

Machines upgrade AUR packages from the fleet repo too, so `arch-update` stops
rebuilding them per machine.

### 3.6 A third level

`async-complete` currently marks both "the session can start" and "everything is
installed". Split them: a sentinel before the slow plays releases the barrier,
and helpers whose subject is a slow package (PIA and LocalSend trays, the
`arch-update` tray) move to `start_when <command>`. Independent of the fleet
repo, and cheaper, but the fleet repo shrinks what is left to wait for.

## 4. Constraints

- **Hosting must be private.** 1Password, Zoom, Slack, JetBrains Toolbox, PIA and
  the Claude desktop app are proprietary; publishing their repackaged binaries
  (a public GitHub release, say) is redistribution. A home server fails D9 once
  travelling.
- **Hardware-gated packages belong on the stick too.** `broadcom-wl-dkms` is the
  WiFi driver for 802.11ac Broadcom Macs (`has_broadcom_wl`, fb4f940), and today
  it installs in REST from the network. squirrel-zapper only got it because a USB
  Ethernet adapter was plugged in; a MacBook Air has no Ethernet port, so without
  the stick it can never download the driver that would bring its network up.
  `gatherd-check-package-tiers` currently exempts hardware-gated packages because
  "a generic cache stick cannot predict" them; for a package that provides the
  network, the stick has to carry it anyway. EndeavourOS reached the same place:
  its ISO's `run_before_squashfs.sh` (endeavouros-team/EndeavourOS-ISO 60444ea,
  read, not run) pre-downloads `broadcom-wl-dkms` into the image.

## 5. Unmeasured

- How pacman behaves with a `file://` Server whose directory is absent (no stick).
- CI container limits for the largest packages (`zoom` is 366M).
- Whether `arch-update-bin` (AUR 4.4.0, same version as `arch-update`) is an
  acceptable substitute in the meantime.

## 6. Open decisions

1. **Architectures.** `rest_slow_x86_packages` implies at least one aarch64
   machine; each architecture is another build and another tree.
2. **Builder.** CI, or a fleet machine.
