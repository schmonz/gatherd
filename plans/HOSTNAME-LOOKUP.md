# Per-machine hostname from an online lookup

Assign a machine its hostname on first boot by looking it up from a designated
source, keyed by a stable hardware identifier — so a freshly-imaged machine
names itself without manual entry at install time.

## Decision: do it in gatherd, not the installer

Hostname *feels* like an install-time decision, which tempts a Calamares hook.
But coupling to Calamares means rebuilding the mechanism for `archinstall`, then
again for Artix's `basestrap`. Instead, **gatherd does the lookup-and-apply on
first boot**, and the same code works across all three eras.

gatherd is well-placed for this: `services/system/gatherd.service` runs
first-boot, **after `network-online.target`, before `greetd.service`**, as root,
from `/usr/local/lib/gatherd`. The network is up (online lookup is viable) and
the repo is already on disk (an in-repo fallback map is viable).

The only per-era difference is the installer's *default* hostname we guard
against — one string, not a mechanism:

| | EndeavourOS (now) | Arch / Artix (later) |
|---|---|---|
| Lookup + apply | gatherd task | identical gatherd task |
| Installer default to guard on | `EndeavourOS` | `archlinux` / `artix` |
| Calamares involvement | none | none |

Tradeoff accepted: the hostname stays the installer default for the brief window
until gatherd's first run. Fine for a personal fleet.

## What gatherd does today

gatherd does **not** set the hostname — it reads whatever the installer baked
in, via `ansible_facts['hostname']`, in a few consumers:

- `roles/system/tasks/main.yml:112` — renames the etckeeper branch to the hostname
- `roles/system/tasks/main.yml:131-145` — `root@{{ hostname }}` git identity
- `roles/desktop/tasks/main.yml:293` — flutter `ls_alias`
- `roles/desktop/tasks/main.yml:311` — conky desktop display

These read facts captured at play start, which constrains ordering (below).

## Design

### 1. The key — a set of stable identifiers, match any

MACs alone are shaky: multiple NICs, USB-ethernet dongles, and Wi-Fi MAC
randomization all move the target. Gather a *set* of candidates and match if
**any** is present in the map:

- all *permanent* MACs — `ethtool -P <if>` (defeats Wi-Fi randomization), or
  `/sys/class/net/*/address` minus virtual interfaces
- `/sys/class/dmi/id/product_uuid` — root-readable, stable, unique; often a
  better key than MAC
- `/sys/class/dmi/id/product_serial` — tiebreaker

This survives a NIC swap and lets each machine be keyed on whatever is most
convenient. (The Lenovo Chromebook's DMI strings are junk — see TODO.md — but
`product_uuid` may still be unique even when `product_name` is "Google Robo".)

Probe in the `machine_facts` role using the established pattern: one read-only
task to gather (`changed_when: false`), one `set_fact`. Expose the candidate
list as a fact, e.g. `machine_identifiers`.

### 2. The source — HTTPS map, authoritative; in-repo file, fallback

- **HTTPS-fetched map** (raw GitHub, a gist, or schmonz.com), keyed
  identifier → hostname: lets you reassign without touching the repo. Fetch with
  `ansible.builtin.uri` (or `curl -fsSL --max-time 10`), and **fall back
  gracefully** — keep the current hostname on any failure — mirroring the
  defensive fetch at `roles/desktop/tasks/main.yml:577`.
- **In-repo file** (`hostnames.yml`) committed alongside the playbook: already
  present at `/usr/local/lib/gatherd`, version-controlled, works offline. Use it
  as the default; let the network fetch override it.

**Privacy:** if the source is public, do **not** publish raw MACs/UUIDs. Key the
map on `sha256(salt + identifier)`. The salt is a secret — deliver it via the
existing vault channel (`gatherd-vault.service` / `scripts/gatherd-prompt-vault`)
rather than committing it.

Rejected: DNS TXT records keyed by a hash — fragile behind captive portals
(which this fleet already fights) and no real upside over an HTTPS GET.

### 3. Applying it

- Use `ansible.builtin.hostname` (sets and persists `/etc/hostname`) and update
  the `127.0.1.1` line in `/etc/hosts`. Root — fits the System play.
- **Policy guard:** only override when the current hostname is a known installer
  default (`EndeavourOS`, `archlinux`, `artix`, …). A machine renamed by hand is
  never stomped, and this guard is the only per-era knob.
- **Idempotent for free:** the `hostname` module no-ops when the name already
  matches, so this is safe in the steady-state run.

### 4. Ordering — set the name before anything reads it

The consumers above read `ansible_facts['hostname']` captured at play start. So:

1. Set the hostname early — in a `pre_task` or the Detect (`machine_facts`) play.
2. Re-gather facts (`ansible.builtin.setup`) before the System/User plays run,
   so the etckeeper branch rename, git identity, conky, and flutter alias all see
   the new name on the *first* run rather than next boot.

## Implementation sketch

- `roles/machine_facts/` — probe candidate identifiers → `machine_identifiers` fact.
- New tiny task file (e.g. `roles/system/tasks/hostname.yml`), included early:
  fetch the map (HTTPS, in-repo fallback), look up by any identifier, and if a
  hostname is assigned **and** the current name is an installer default, set it +
  fix `/etc/hosts`, then refresh facts.
- Map format (`hostnames.yml`), salted-hash keys:
  ```yaml
  hostnames:
    "<sha256(salt+id)>": kunilou
    "<sha256(salt+id)>": some-other-host
  ```
- Per the standalone-scripts preference, if the lookup logic grows beyond a
  couple of Ansible tasks, factor it into a `gatherd-resolve-hostname` script the
  task calls, rather than an inline shell block.

## Verify (add to `section_verify` once it works)

On a fresh image whose identifier is in the map: after gatherd's first run,
`hostnamectl` shows the assigned name, `/etc/hosts` `127.0.1.1` matches, and the
etckeeper branch is named for it. On a machine **not** in the map, the installer
default is left untouched. With the network unreachable, the in-repo fallback
still resolves (or the current name is kept) — no failed run.
