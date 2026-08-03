# Robust Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Domain note on "tests":** this is an Ansible/systemd/POSIX-sh project. There are no pytest unit tests. The verification at the end of each task uses this project's actual test suite, per `CLAUDE.md`: `ansible-lint` (config `.ansible-lint`), `ansible-playbook --syntax-check`, **idempotent re-run = zero `changed`**, the runnable `section_verify` sequences in `scripts/gatherd-post-setup-notes`, and observed boot/repave behavior. Treat each "Verify" step as the test-first gate: know the expected output before running it.

**Goal:** A playbook error or hang can never block multiuser boot — the machine always reaches a usable, log-in-able Sway desktop — and a full convergence becomes possible with little or no live network.

**Architecture:** Split convergence into two tiers on the *network axis*. **CORE** (local-only, zero-network) is the only thing that gates greetd; it runs behind a fail-open POSIX-sh wrapper (`gatherd-run-core`) that syntax-checks, timeouts, records status, and **always `exit 0`**. **REST** (everything that touches the network) runs after login via the existing `gatherd-await-and-run`/async machinery, where a captive portal can be cleared and retries are cheap and non-fatal. An optional labeled USB cache lets REST install everything (incl. prebuilt AUR) with zero internet.

**Tech Stack:** Ansible (FQCN only), systemd units (Artix/s6-portable POSIX-sh wrappers), `pacman` `file://` local repo + `devtools`/`makechrootpkg` for the offline cache, GitHub Actions (Arch container) for CI.

**Parent spec:** `docs/superpowers/specs/2026-06-29-travel-repave-design.md` (sub-project 1, Robustness floor). Source plan superseded by this document: `plans/ROBUSTIFY.md` (delete on completion of Task 0 of this plan).

## Global Constraints

Every task implicitly includes these (from `CLAUDE.md` and the source plan's "Decisions locked" / "Out of scope"):

- **FQCN always** — `ansible.builtin.*`, `community.general.*`; never bare module names.
- **Tiny task files** — one logical unit per file under `roles/<role>/tasks/`; imperative task names.
- **Idempotency** — `command`/`shell` tasks use `creates:`/`changed_when:`/explicit checks; a second converge reports zero `changed`.
- **`ansible-lint` clean before every commit** — config `.ansible-lint`; `noqa` is a last resort.
- **Finish each landed phase per `CLAUDE.md`** — add a runnable check to `section_verify` in `scripts/gatherd-post-setup-notes`, then prune the corresponding `plans/TODO.md` item.
- **Never let the wrapper exit nonzero at the init level** — a failed oneshot blocks dependents under *both* systemd and s6-rc. Record real status in a marker file; `exit 0` always.
- **No network operation in the CORE tier.** CORE must complete on an internet-less, captive-portal-trapped machine without hanging.
- **Separate playbooks, not tags** — Ansible parses the whole file before tag filtering, so a syntax error in a `rest`-tagged task still fails a core run. Only separate files give parse-isolation.
- **Runtime scripts are POSIX sh, init-agnostic** — model on `gatherd-await-and-run`; no systemd-specific calls in the script body. No phase adds a new systemd dependency.

---

## File Structure

New/changed files across the plan, by responsibility:

- `scripts/gatherd-run-core` (new) — fail-open wrapper for the CORE play (syntax-check → timeout'd non-interactive run → status marker → `exit 0`). The portable safety net.
- `services/gatherd.service` (modify) — thin unit that just execs the wrapper.
- `scripts/gatherd-prompt-*` / `scripts/gatherd-post-setup-notes` (modify) — surface a recorded failure at login.
- `group_vars/all/main.yml` (modify) — package lists as single source of truth (`core_packages`, `rest_packages`, `aur_packages`, `aur_slow_packages`).
- `roles/*/tasks/core.yml` + `roles/*/tasks/rest.yml` (new) — the network-axis split per the boundary table.
- `site-core.yml` (new), `site-async.yml` (modify) — CORE-only and REST playbooks.
- `roles/machine_facts/tasks/*` (modify) — `has_offline_cache` probe.
- `scripts/gatherd-build-offline-cache` (new) — builds the USB cache stick.
- `.github/workflows/*.yml` (new) — lint + syntax-check (+ optional convergence) CI.

## The CORE/REST boundary (authority for Tasks 3–5)

Copied verbatim from the source plan; this table is the authority for which tasks move to `core.yml` vs `rest.yml`.

| Tier | Contents |
|------|----------|
| **CORE** (local, gates greetd) | `detect_user` + `machine_facts`; system `/etc` essentials (DNS/`systemd-resolved`, etckeeper init, macOS keyboard layout, logind/sleep, greetd-PAM keyring, `pam_env` PATH); gatherd's own **config templates** (sway/waybar/foot/fuzzel/mako fonts, keybindings, gtklock, wallpaper, `gatherd-*` helper scripts + session-helper autostart); enabling already-installed services. **No packages, no AUR, no downloads, no dotfiles clone.** |
| **REST** (network or USB cache, post-login) | All `pacman` installs; **all** AUR (yay bootstrap, 1Password, Helium, GPG fetches); the **dotfiles git clone**; `system/slow.yml` + `aur/slow.yml`; all hardware-specific tweaks (zswap, grub background, thinkpad, chromebook, mac); service config needing packages (tailscaled, cups, bluetooth, tlp), NFS/autofs, Timeshift, fingerprint driver, web-app favicons, firmware. |

The dotfiles *clone* moves to REST (it's network); gatherd's own templated config stays in CORE, so the first session still looks like yours (fonts, keybindings, power behavior, keyring unlock) before the portal is cleared.

---

## Task 0: Retire the source plan, capture the baseline

**Files:**
- Delete: `plans/ROBUSTIFY.md`
- Reference: `docs/superpowers/plans/2026-06-29-robust-convergence.md` (this file)

**Interfaces:**
- Produces: this plan as the single source of truth for the robustness floor.

- [x] **Step 1: Confirm this plan supersedes the source**

Skim `plans/ROBUSTIFY.md` and confirm every section (Why, Diagnosis, Current state, Target state, Decisions locked, Phases 0–5, Portability, Cross-references, Out of scope) is represented in this document. It is — Decisions/boundary are copied verbatim; Phases 0–5 become Tasks 1–6.

- [x] **Step 2: Delete the source plan**

```bash
git rm plans/ROBUSTIFY.md
```

- [x] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-06-29-robust-convergence.md
git commit -m "Convert ROBUSTIFY.md into a superpowers plan"
```

---

## Task 1: Phase 0 — Fail-open wrapper around the current monolith (safety net first)

*Highest value, lowest risk, no refactor. Kills "a typo bricks boot" immediately and establishes the portable wrapper the CORE tier reuses.* Ship this before any restructuring.

**Files:**
- Create: `scripts/gatherd-run-core`
- Modify: `services/gatherd.service`
- Modify: `scripts/gatherd-post-setup-notes` (failure-surfacing verify line) and the relevant `scripts/gatherd-prompt-*` (login notification)
- Model on: `scripts/gatherd-await-and-run` (the proven fail-open wrapper shape)

**Interfaces:**
- Produces: `scripts/gatherd-run-core <playbook>` — does galaxy install, syntax-check, timeout'd non-interactive run, writes `/etc/gatherd/last-run` (status + log path), always `exit 0`. Tasks 3 re-aims it at `site-core.yml`.
- Produces: `/etc/gatherd/last-run` marker (first line: `ok|failed|timeout|syntax-error`; second line: log path). Consumed by the login surface and by `section_verify`.

- [x] **Step 1: Write `scripts/gatherd-run-core`**

POSIX sh, mirrors `gatherd-await-and-run` (galaxy install + inhibit already proven there). Key differences: a `--syntax-check` gate, a `timeout`, and **always `exit 0`** with status recorded.

```sh
#!/bin/sh
# gatherd-run-core — run a gatherd play fail-open: never block boot/login.
#
# A syntax error or a hang in the playbook must NOT brick the machine. We
# syntax-check first (a bad parse never even attempts a run), bound the run with
# `timeout` (a hang can't wedge boot), record the outcome to a marker, and ALWAYS
# exit 0 — a nonzero exit from a oneshot blocks greetd under both systemd and
# s6-rc, which is the very lockout we are eliminating. Real status lives in the
# marker, surfaced at login, not in the unit's exit code.
#
# POSIX sh, no init-specific bits (model: gatherd-await-and-run) so the Artix/s6
# port only has to `exec` this. Usage: gatherd-run-core <playbook>
set -u

playbook="$1"
gatherd_home=/usr/local/lib/gatherd
vault_pass="$gatherd_home/.vault_pass"
marker=/etc/gatherd/last-run
log=/var/log/gatherd-core.log
timeout_secs=900

[ -f "$playbook" ] || exit 0

record() { printf '%s\n%s\n' "$1" "$log" > "$marker"; }

cd "$gatherd_home" || { record "failed"; exit 0; }

# Galaxy install is best-effort; a missing collection surfaces as a play failure,
# not a wrapper failure.
ansible-galaxy collection install --requirements-file "$gatherd_home/requirements.yml" >>"$log" 2>&1 || true

# 1) Parse gate: a syntax error records and exits WITHOUT attempting the run.
if ! ansible-playbook --syntax-check "$playbook" >>"$log" 2>&1; then
    record "syntax-error"
    exit 0
fi

# 2) Non-interactive, bounded run. </dev/null so a stray prompt can't block;
# --vault-password-file so vault never prompts; timeout so a hang can't wedge boot.
vault_arg=""
[ -f "$vault_pass" ] && vault_arg="--vault-password-file=$vault_pass"

if command -v systemd-inhibit >/dev/null 2>&1; then
    timeout "$timeout_secs" systemd-inhibit --what=sleep --who=gatherd \
        --why="gatherd CORE provisioning in progress" --mode=block \
        ansible-playbook $vault_arg "$playbook" </dev/null >>"$log" 2>&1
else
    timeout "$timeout_secs" ansible-playbook $vault_arg "$playbook" </dev/null >>"$log" 2>&1
fi
rc=$?

# 3) Record outcome; ALWAYS exit 0.
if [ "$rc" -eq 0 ]; then record "ok"
elif [ "$rc" -eq 124 ]; then record "timeout"
else record "failed"
fi
exit 0
```

- [x] **Step 2: Make it executable**

```bash
chmod +x scripts/gatherd-run-core
```

- [x] **Step 3: Repoint `services/gatherd.service` at the wrapper**

The unit gets thin: the galaxy install (today's `ExecStartPre`) and the inhibit (today's `ExecStart`) move into the script. Keep `ExecCondition` and `Before=greetd.service`.

```ini
[Service]
Type=oneshot
WorkingDirectory=/usr/local/lib/gatherd
ExecCondition=/usr/local/lib/gatherd/scripts/gatherd-needs-run /etc/gatherd/complete
ExecStart=/usr/local/lib/gatherd/scripts/gatherd-run-core /usr/local/lib/gatherd/site.yml
RemainAfterExit=no
StandardOutput=journal+console
StandardError=journal+console
```

(Leave `[Unit]` and `[Install]` unchanged for Task 1; the network-decoupling of the `[Unit]` lands in Task 3.)

- [x] **Step 4: Surface a recorded failure at login**

Add a check that reads `/etc/gatherd/last-run`; when its first line is not `ok`, emit a desktop notification ("gatherd setup <status> — see <log>; re-run with `sudo systemctl start gatherd.service`") from the existing first-login prompt path (`scripts/gatherd-prompt-*`), and add a matching `section_verify` line (Step 6). This is the "stop hunting in journalctl" fix.

- [x] **Step 5: Verify — syntax error and hang are both survivable**

```
# Parse gate (no boot needed):
echo 'this: is: not: valid: yaml:::' > /tmp/broken.yml
scripts/gatherd-run-core /tmp/broken.yml; echo "exit=$? (expect 0)"
head -1 /etc/gatherd/last-run   # expect: syntax-error

# Boot tests (on a VM or test machine):
# - Introduce a syntax error in a peripheral task -> boot still reaches greetd;
#   notification shows the failure; next boot retries.
# - Introduce a deliberately hanging task -> `timeout` fires (~900s cap, lower it
#   for the test), greetd still comes up.
# - A clean run is unchanged: /etc/gatherd/complete written, no re-run.
```

Also record the **empirical finding** from the source plan's Diagnosis: on a deliberately-broken boot, does greetd come up (clean failure passes through pure ordering) or hang (ansible blocked on a prompt)? Note the answer in this plan's history; the wrapper is robust to either.

- [x] **Step 6: Lint, add the verify line, commit**

```bash
ansible-lint
# add to section_verify in scripts/gatherd-post-setup-notes a runnable line:
#   `head -1 /etc/gatherd/last-run` is `ok`; a non-`ok` value showed a login
#   notification; `scripts/gatherd-run-core /tmp/broken.yml; echo $?` is `0` and
#   records `syntax-error` (a bad parse can never attempt a run).
git add scripts/gatherd-run-core services/gatherd.service scripts/gatherd-post-setup-notes scripts/gatherd-prompt-*
git commit -m "Phase 0: fail-open wrapper so a playbook error never blocks boot"
```

**As built — deviations from the draft above:**

- The unit is `services/system/gatherd.service` (the repo grew a `services/system/`
  subdirectory after this plan was written), not `services/gatherd.service`.
- The play's output goes through `tee -a "$log"`, not a bare `>>"$log"`. The unit's
  `journal+console` stdout is a repave's only progress display while greetd is
  blocked; swallowing it into the log alone makes a long first boot look bricked.
  POSIX sh has no `pipefail`, so the play's exit code rides out through a status
  file rather than `$?`.
- `timeout_secs` defaults to 3600, not 900, while this still wraps the whole
  monolith `site.yml` — a slow-network first boot legitimately runs that long.
  Drop it to 900 in Task 3, when the gated play is local-only.
- `GATHERD_CORE_TIMEOUT`, `GATHERD_CORE_MARKER`, `GATHERD_CORE_LOG` are
  env-overridable so the verify step can fire all three failure paths on a
  converged machine against a scratch marker, instead of "you had to be there on a
  fresh repave" (`CLAUDE.md`, "Finishing a TODO item"). Nothing in the boot path
  sets them.
- The vault-password test is `-r`, not `-f`: the file is root-only, so an
  unprivileged verify run sees it but cannot read it, and handing it to ansible
  there is a guaranteed hard error.
- The login surface is a new `scripts/gatherd-prompt-lastrun`, registered in
  `scripts/gatherd-session-helpers` and installed by `roles/desktop/tasks/main.yml`.

**Verified locally** (unprivileged, scratch marker): `syntax-error`, `timeout`
(`GATHERD_CORE_TIMEOUT=5`), `ok`, and missing-playbook all exit `0` and record the
expected status; `gatherd-prompt-lastrun` pops the critical toast on a non-`ok`
marker and stays silent on `ok`. `shellcheck` clean on both scripts;
`ansible-lint` clean on `roles/desktop/tasks/main.yml`.

**Still outstanding — boot-level test on a VM or test machine:** deliberately break
a peripheral task and confirm greetd still comes up with the notification showing;
and record the source plan's empirical Diagnosis question (does a broken boot today
reach greetd via pure ordering, or hang on an ansible prompt?). The wrapper is
robust to either answer, so this does not gate Task 2.

---

## Task 2: Phase 1 — Package lists as single source of truth

*Pure refactor, no behavior change. Prerequisite for both the split (Task 3) and the offline builder (Task 5).*

**Files:**
- Modify: `group_vars/all/main.yml` (alongside the existing `web_apps`/wallpaper list config)
- Modify: each role task file that currently inlines a package list

**Interfaces:**
- Produces: `core_packages`, `rest_packages`, `aur_packages`, `aur_slow_packages` list vars. Task 5's builder downloads the exact same lists — no drift.

- [ ] **Step 1: Inventory inline package lists**

```bash
grep -rnE 'name:\s*\[|with_items:|loop:' roles/*/tasks/*.yml | grep -iE 'pkg|package|pacman|aur' 
grep -rn 'community.general.pacman\|ansible.builtin.package\|kewlfft.aur' roles/
```

- [ ] **Step 2: Lift the lists into vars verbatim**

Move each inline list into `group_vars/all/main.yml` under the four names, copying package names **verbatim** (no additions/removals — this step must not change what installs). Example shape:

```yaml
# Package sets — single source of truth. The offline-cache builder (gatherd-build-
# offline-cache) downloads these exact lists, so the stick can never drift from
# what the playbook installs. Tier (core/rest) is enforced by Task 3's lint check.
core_packages: []        # local-only essentials installed in CORE (often empty: CORE prefers already-present pkgs)
rest_packages:           # official packages installed post-login
  - foot
  - waybar
  # …verbatim from the role…
aur_packages:            # fast AUR
  - 1password
  # …
aur_slow_packages:       # long AUR compiles (roles/aur/tasks/slow.yml)
  - …
```

- [ ] **Step 3: Point the tasks at the vars**

Replace each inline list with the var (`loop: "{{ rest_packages }}"` etc.), keeping the module and options identical.

- [ ] **Step 4: Verify — zero behavior change**

```
ansible-lint                                   # expect: clean
ansible-playbook --syntax-check site.yml       # expect: clean
# On a converged machine, a full re-run reports zero changed for package tasks:
sudo systemctl start gatherd.service && head -1 /etc/gatherd/last-run   # ok
# Idempotency: diff the resolved package set before/after the refactor is empty.
```

- [ ] **Step 5: Commit**

```bash
git add group_vars/all/main.yml roles/
git commit -m "Phase 1: package lists as single source of truth"
```

---

## Task 3: Phase 2 — The CORE/REST split on the network axis

*The big structural move. Implements the boundary table. Each role split is mechanical against that table; ship per-role if you prefer smaller commits.*

**Files:**
- Create: `roles/<role>/tasks/core.yml` and/or `roles/<role>/tasks/rest.yml` for each role
- Create: `site-core.yml`
- Modify: `site-async.yml` (expand/repoint its includes; drop `any_errors_fatal: true` from REST plays)
- Modify: `services/gatherd.service` (re-aim wrapper at `site-core.yml`; reset network ordering — see Step 5)
- Modify: each role's `main.yml` (becomes a thin importer of core/rest, or is replaced by the site-level includes)

**Interfaces:**
- Consumes: the `*_packages` vars (Task 2), the `gatherd-run-core` wrapper (Task 1).
- Produces: `site-core.yml` (local-only), the expanded `site-async.yml` (REST), and two sentinels `/etc/gatherd/core-complete` + `/etc/gatherd/async-complete` (`gatherd-needs-run` already takes the sentinel path as an arg).

- [ ] **Step 1: Split each role's tasks by the boundary table**

For every role, move tasks matching the **CORE** column into `roles/<role>/tasks/core.yml` and tasks matching the **REST** column into `roles/<role>/tasks/rest.yml` (honor "tiny task files" — keep already-split files as-is, just route their includes). Per the table: `dotfiles`-clone, all of `aur`, and all of `hardware` become **REST**; system `/etc` essentials and desktop config templates are **CORE**.

- [ ] **Step 2: Add the tier-classification lint gate**

Add a check (a small task asserting at parse time, or a CI script) that **every** entry in `core_packages`+`rest_packages`+`aur_packages`+`aur_slow_packages` carries a tier and that no package is unclassified — an unclassified package is a **hard failure** (decision locked in the north-star spec: lint fails until classified, so offline-core stays complete-by-construction). Example assert:

```yaml
- name: Assert every package declares a tier
  ansible.builtin.assert:
    that:
      - (core_packages | default([])) is iterable
      - (rest_packages | default([])) is iterable
    fail_msg: "Unclassified package(s) found — declare core_packages or rest_packages"
    quiet: true
```

(Refine the assertion to your chosen metadata representation; the requirement is: adding a package without a tier fails the run/CI.)

- [ ] **Step 3: Create `site-core.yml` (local-only)**

Three plays trimmed to CORE includes (detect + machine_facts; system `/etc` essentials; desktop config templates). No package, AUR, download, or dotfiles-clone task. Keep `any_errors_fatal: true` here is acceptable since CORE is small and local — but the wrapper's `exit 0` is the real safety net.

- [ ] **Step 4: Fold REST into `site-async.yml`; drop `any_errors_fatal`**

Expand `site-async.yml`'s existing three plays (which already pull `roles/system/tasks/slow.yml` + `roles/aur/tasks/slow.yml` and write `async-complete`) to include the new `rest.yml` files. **Remove `any_errors_fatal: true`** from the REST plays so one failed package doesn't abort the remainder of a post-login convergence.

- [ ] **Step 5: Re-aim the wrapper and reset network ordering**

```ini
# services/gatherd.service
ExecStart=/usr/local/lib/gatherd/scripts/gatherd-run-core /usr/local/lib/gatherd/site-core.yml
ExecCondition=/usr/local/lib/gatherd/scripts/gatherd-needs-run /etc/gatherd/core-complete
```

Remove `network-online.target` from gatherd's `[Unit]` (CORE is local-only). NOTE from the source Diagnosis: this removes gatherd's path to `network-online.target` but **not** stock `autofs`'s — `graphical.target ← autofs.service` still pulls it in. To fully take the greeter off the network, add an `autofs.service` drop-in that resets the inherited `network-online`/`rpc-statd` ordering (autofs mounts on demand; the nfs4 map needs neither at start). Verify the six-unit reverse-dependency set shrinks:

```
systemctl list-dependencies --reverse network-online.target
```

REST stays on `gatherd-async.service`/`gatherd-await-and-run` (already aimed at `site-async.yml`).

- [ ] **Step 6: Verify — greeter comes up with the network cable pulled**

```
ansible-lint && ansible-playbook --syntax-check site-core.yml && ansible-playbook --syntax-check site-async.yml
# Repave / boot with network DISCONNECTED:
#   greetd comes up after CORE alone (no 60s NetworkManager-wait-online hang);
#   first session has your fonts/keybindings/keyring.
# Reattach network, log in -> REST converges in the background
#   (gatherd-show-slow-progress shows it). A forced failure in any REST task
#   does NOT affect the booted session.
head -1 /etc/gatherd/last-run   # ok (CORE)
test -f /etc/gatherd/core-complete && test -f /etc/gatherd/async-complete && echo OK
```

- [ ] **Step 7: Lint, add verify lines, prune TODO, commit**

```bash
ansible-lint
# section_verify: add "boot offline -> greeter in CORE-only time, no network-online wait"
#                 and "REST task failure leaves the session usable".
git add roles/ site-core.yml site-async.yml services/gatherd.service scripts/gatherd-post-setup-notes
git commit -m "Phase 2: split convergence into CORE (gates greetd) and REST (post-login)"
```

---

## Task 4: Phase 3 — REST waits for *real* connectivity (survive the captive-portal lie)

*Make REST wait for actual internet or proceed offline, instead of trusting `network-online.target` (which a captive portal satisfies while there is no real internet).*

**Files:**
- Modify: the REST runner (`scripts/gatherd-await-and-run`, or a small helper it calls)
- Reference: `plans/CAPTIVE-PORTAL.md` (connectivity-probe logic + local-simulation trick)

**Interfaces:**
- Consumes: `has_offline_cache` is *not yet* available (Task 5); for now the offline shortcut is a stub that is false.
- Produces: a connectivity-gated REST start — proceeds when an active probe to a known check URL succeeds, **or** immediately if the offline cache is present (wired in Task 5).

- [ ] **Step 1: Add an active-connectivity wait to the REST runner**

Before the `ansible-playbook` exec in the REST path, add a bounded wait loop that probes real connectivity (fetch a known check URL — reuse the probe from `CAPTIVE-PORTAL.md`), same wait-loop shape `gatherd-await-and-run` already uses. Proceed on success; also proceed immediately if the offline-cache sentinel exists (Task 5 sets it).

```sh
# proceed if the offline cache is present, else wait for REAL internet (a captive
# portal satisfies the default route but not this probe).
offline_ready() { [ -f /run/gatherd/offline-cache ]; }
online() { curl -fsS --max-time 5 http://connectivitycheck.gstatic.com/generate_204 >/dev/null 2>&1; }
until offline_ready || online; do sleep 5; done
```

- [ ] **Step 2: Verify — REST waits behind a portal, proceeds when cleared**

```
# Using the NM connectivity-override trick from CAPTIVE-PORTAL.md Phase 2 local validation:
#   simulate `portal` state -> REST waits (does not fail against network-online).
#   clear the portal in-session -> probe succeeds -> REST proceeds and converges.
```

- [ ] **Step 3: Lint and commit**

```bash
ansible-lint   # (shell scripts: shellcheck if available)
git add scripts/gatherd-await-and-run scripts/
git commit -m "Phase 3: REST waits for real connectivity, surviving captive portals"
```

---

## Task 5: Phase 4 — Offline USB cache feeds REST

*Independent; bolts onto the now-isolated REST tier. Subsumes the TODO "USB package mirror" + "travel-repave behind a captive portal" items; the same stick can carry the Broadcom `wl` driver from `ARTIX.md` Step 2.*

**Files:**
- Modify: `roles/machine_facts/tasks/` (+ its main include) — `has_offline_cache` probe
- Modify: REST source-steps (pacman/AUR/galaxy/dotfiles/assets) to branch on `has_offline_cache`
- Create: `scripts/gatherd-build-offline-cache`

**Interfaces:**
- Consumes: the `*_packages` vars (Task 2); the REST tier (Task 3).
- Produces: `has_offline_cache` fact (`has_*` idiom); a labeled stick (fs label `GATHERD` or a `gatherd-offline/manifest` sentinel) holding a `file://` pacman repo (official closure + prebuilt AUR `.pkg.tar.zst` + `repo-add` db), vendored galaxy collections, a dotfiles `git bundle`, GPG keys, assets, and a **manifest stamped with the git HEAD it was built from**.

- [ ] **Step 1: Add the `has_offline_cache` probe**

Probe pattern (one read task `changed_when: false` + one `set_fact`): look for the labeled USB (`blkid`/`/dev/disk/by-label/GATHERD`) or the `gatherd-offline/manifest` sentinel; set `has_offline_cache`.

- [ ] **Step 2: Source-switch the REST network steps on `when: has_offline_cache`**

- **pacman:** add the stick as a `file://` repo in `pacman.conf` (dir of `.pkg.tar.zst` + `repo-add` `.db`), or `--cachedir`.
- **AUR:** install the **prebuilt** `.pkg.tar.zst` from the same local repo (no yay compile, no upstream GPG on the road); yay itself prebuilt.
- **galaxy:** point `ANSIBLE_COLLECTIONS_PATH` at the vendored collections; skip the online `ansible-galaxy install`.
- **dotfiles:** clone from the `git bundle`, then reset the real remote.
- **GPG keys / wallpapers / web-app icons:** import/copy from stick files instead of `curl`.
- Set `/run/gatherd/offline-cache` when present so Task 4's REST runner proceeds immediately.

- [ ] **Step 3: Write `scripts/gatherd-build-offline-cache`**

Resolve the official-package closure (`pacman -Syw` into the repo dir over the `*_packages` lists), build the AUR set in a clean chroot (`devtools`/`makechrootpkg`), `repo-add` everything, vendor collections (`ansible-galaxy collection install -p`), bundle dotfiles (`git bundle create`), copy keys/assets, and write a manifest stamped with the source git HEAD (mirrors the `complete`-sentinel pattern). Trust: a self-built repo with `SigLevel = Optional TrustAll` is acceptable; optionally sign the db.

- [ ] **Step 4: Staleness reconciliation**

The converger compares stick-HEAD to deployed HEAD; note staleness in `post-setup-notes`; fetch the delta online if connected.

- [ ] **Step 5: Verify — fully offline repave from the stick**

```
# Build: scripts/gatherd-build-offline-cache -> a labeled GATHERD stick.
# Repave with the stick inserted and NO network at all:
#   REST installs everything (incl. AUR) from the stick and converges fully offline.
# Remove the stick -> REST falls back to network unchanged (Task 4's probe).
```

- [ ] **Step 6: Lint, add verify line, prune TODO items, commit**

```bash
ansible-lint
# prune plans/TODO.md: "Automate preparing a local package mirror on a USB stick"
#                      and "Travel-repave behind a captive portal".
git add roles/machine_facts/ roles/ scripts/gatherd-build-offline-cache scripts/gatherd-post-setup-notes plans/TODO.md
git commit -m "Phase 4: offline USB cache feeds the REST tier"
```

---

## Task 6: Phase 5 — Catch errors before the laptop (CI), optional/ongoing

*Attacks "you have to go hunting" at the root: errors surface in CI with line numbers, on a machine that isn't your travel laptop.*

**Files:**
- Create: `.github/workflows/lint.yml` (Arch container)

**Interfaces:**
- Consumes: the whole repo. Produces: a CI gate failing on lint/syntax errors before they reach a machine. The same Arch-container infra can later build the Task 5 cache as a downloadable pre-trip artifact.

- [ ] **Step 1: Add the CI workflow**

```yaml
name: lint
on: [push, pull_request]
jobs:
  ansible:
    runs-on: ubuntu-latest
    container: archlinux:latest
    steps:
      - run: pacman -Sy --noconfirm ansible ansible-lint git
      - uses: actions/checkout@v4
      - run: ansible-lint
      - run: ansible-playbook --syntax-check site-core.yml site.yml site-async.yml
```

- [ ] **Step 2: Verify — a pushed syntax error fails CI**

Push a branch with a deliberate syntax error; confirm the workflow fails at `--syntax-check`/`ansible-lint` before it ever reaches a machine. (Ideal follow-on: a molecule-style full convergence in the container.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/lint.yml
git commit -m "Phase 5: CI lints and syntax-checks the playbooks"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-06-29-travel-repave-design.md` + source `ROBUSTIFY.md`):
- D7 (failed task degrades, never blocks login) → Task 1 (wrapper, always `exit 0`) + Task 3 (CORE gates greetd, REST non-fatal).
- D2/D3 (local-first, non-fatal network; tier classification lint-enforced) → Task 3 Step 2 (lint gate) + Task 5 (source-switch).
- D1/D12 (USB first-class source; ride-along) → Task 5. Network-axis cut (decision locked) → Task 3 boundary table.
- D8 (verify step + idempotency) → every task's Verify + lint/`section_verify` steps.
- Init-agnostic (Portability) → POSIX-sh wrappers, no new systemd dep (Tasks 1, 4, 5).
- Captive-portal survival → Task 4.

**Placeholder scan:** the empty `core_packages: []` and the assert in Task 3 Step 2 are deliberately representational (the exact tier metadata is chosen at execution against the live roles, which a per-role read will reveal) — they are instructions with concrete acceptance criteria (lint fails on unclassified), not "TODO". All script bodies are complete and runnable. No "implement later".

**Type/name consistency:** `gatherd-run-core <playbook>`, `/etc/gatherd/last-run`, `/etc/gatherd/core-complete`, `/etc/gatherd/async-complete`, `has_offline_cache`, `/run/gatherd/offline-cache` are used consistently across tasks.

**Known fidelity caveat (honest):** Task 3's per-role split and Task 5's per-step source-switch are mechanical against the boundary table but their exact diffs depend on reading each role at execution time — they are intentionally specified as "move tasks matching column X" rather than fabricated full diffs for ten-plus roles. Execute per-role, lint per-role, commit per-role.
