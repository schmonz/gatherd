# Plan: Robustify convergence — never let a playbook error block multiuser boot

> Plan for a fresh agent. Self-contained. Read "Diagnosis" and "Decisions locked"
> before writing any code. This is an **incremental** plan: each phase lands and is
> testable on its own and leaves the tree better than it found it. Do them in order,
> but ship them one at a time.

## Why this exists

Two properties of the current shape are intolerable, and doubly so for the
traveler-repave case (repaving a laptop on the road, possibly the only machine you
brought, possibly behind a captive portal):

1. **Any syntax or logic error in the playbook tends to prevent multiuser boot.** A
   typo in some peripheral task can leave you staring at a black screen / bare TTY
   instead of a login.
2. **When it does break, you have to go hunting** in `journalctl` to find out what
   and where.

The target state fixes both *and* makes a full convergence possible with little or no
live network.

## Diagnosis

The root problem is that the current design **conflates two states that deserve
opposite treatment**:

- **"Setup isn't finished yet"** — a legitimate reason to make the first login wait;
  the whole thesis is "log into an already-configured desktop."
- **"Setup hit an error"** — *not* a reason to lock you out. A half-configured
  desktop you can log into and fix beats a black screen every time.

Both currently funnel through one mechanism: a synchronous `ansible-playbook site.yml`
run under `any_errors_fatal: true`, ordered `Before=greetd.service`. So a typo and an
in-progress install look identical to the boot path.

**Network is the dominant failure/hang source.** Package installs, AUR (yay compiles +
`curl|gpg` key fetches + source downloads), the dotfiles clone, asset downloads, and
`ansible-galaxy` all need the internet. On a **captive portal** the machine has a DHCP
lease and default route (so `network-online.target` is satisfied and *lies*) but no
real internet until you clear the portal **in a browser** — which needs a login, which
(today) needs gatherd to finish, which needs the network. That is a genuine deadlock:
you can brick yourself in an airport.

**One empirical question to confirm early (Phase 0):** `gatherd.service` only declares
`Before=greetd.service` (pure ordering); greetd has no `Requires=`/`Wants=` on gatherd
(grepped — none). In systemd, pure ordering does **not** propagate a clean failure, so
a playbook that exits nonzero *should* still let greetd start once ansible exits. That
implies a large share of real-world lockouts are **hangs** (ansible blocking on a
prompt — vault/become/`pause`/a `retries:until` loop — on a oneshot with no tty), not
clean failures, plus "greetd did start but the desktop wasn't configured yet so the
session is broken." Confirm this on a deliberately-broken boot before assuming the
mechanism; it changes nothing about the plan (the fixes are robust to either reading)
but it tells us where the pain actually comes from.

## Current state on `main` (2026-06-03)

A snapshot so a fresh agent knows what already exists vs. what this plan still builds:

- **CORE side is still the monolith.** `gatherd.service` is `Type=oneshot`, runs
  `systemd-inhibit … ansible-playbook site.yml` synchronously, with the galaxy install in
  `ExecStartPre`, `ExecCondition=gatherd-needs-run /etc/gatherd/complete`, and
  `Before=greetd.service`. `site.yml` is the three-play monolith under
  `any_errors_fatal: true`. **Phase 0 and the Diagnosis above apply unchanged.**
- **REST side already has the target portable shape.** `gatherd-async.service` is
  `Type=simple` → `gatherd-await-and-run /etc/gatherd/async-complete site-async.yml`.
  `gatherd-await-and-run` already bundles, in POSIX sh, the wait, the `gatherd-needs-run`
  check, the `ansible-galaxy` install, and the `systemd-inhibit` — and its comment states
  this keeps the unit "portable to non-systemd inits." That is exactly the
  fail-open-wrapper pattern; **Phase 0 brings CORE to the parity REST already has.**
- **`site-async.yml` exists** with three plays (detect → `roles/system/tasks/slow.yml`
  → `roles/aur/tasks/slow.yml`) and writes the `async-complete` sentinel. Phase 2's REST
  work expands those includes and repoints them; it does **not** build new plumbing.
- **Package lists are still inline** in the tasks. `group_vars/all/main.yml` already
  holds list-shaped config (`web_apps`, wallpaper paths) — the precedent location for
  Phase 1's `*_packages` vars.
- **`CAPTIVE-PORTAL.md` Phase 1 is executed**: the connectivity watcher runs from sway
  autostart with an internal self-restart loop (off the old systemd user service).
  Phase 3 reuses that connectivity logic.
- Both `site.yml` and `site-async.yml` still carry `any_errors_fatal: true`. For the REST
  tier, Phase 2 should drop it so one failed package doesn't abort the remainder of a
  post-login convergence.

## Target state

Three structural moves, each independently valuable:

1. **Two tiers split on the network axis.**
   - **CORE** = local-only, zero-network operations. Completes on a freshly-booted,
     internet-less, portal-trapped machine without hanging. This is the *only* thing
     that gates greetd.
   - **REST** = everything that touches the network. Runs *after* login, where the
     user can clear a captive portal (`captive-browser`) and where retries are cheap
     and non-fatal. Already has machinery (`gatherd-await-and-run`, the async service,
     `gatherd-show-slow-progress`, the systray, post-setup-notes).

2. **Fail-open via a POSIX-sh wrapper** (not systemd knobs). A `gatherd-run-core`
   script runs ansible non-interactively with a timeout, records success/failure to a
   marker, and **always `exit 0`**. The init unit just execs it. This is the variant
   that ports directly to Artix/s6 (see "Portability").

3. **Offline USB cache** feeds the REST tier. A prepared stick carries the package
   closure (official + prebuilt AUR as a `file://` local repo), vendored galaxy
   collections, a dotfiles bundle, GPG keys, and assets. With the stick present, a
   full convergence needs **zero internet**; without it, REST falls back to network.

### The boundary, concretely

| Tier | Contents |
|------|----------|
| **CORE** (local, gates greetd) | `detect_user` + `machine_facts`; system `/etc` essentials (DNS/`systemd-resolved`, etckeeper init, macOS keyboard layout, logind/sleep, greetd-PAM keyring, `pam_env` PATH); gatherd's own **config templates** (sway/waybar/foot/fuzzel/mako fonts, keybindings, gtklock, wallpaper, `gatherd-*` helper scripts + session-helper autostart); enabling already-installed services. **No packages, no AUR, no downloads, no dotfiles clone.** |
| **REST** (network or USB cache, post-login) | All `pacman` installs; **all** AUR (yay bootstrap, 1Password, Helium, GPG fetches); the **dotfiles git clone**; `system/slow.yml` + `aur/slow.yml`; all hardware-specific tweaks (zswap, grub background, thinkpad, chromebook, mac — these need a reboot to take effect anyway); service config needing packages (tailscaled, cups, bluetooth, tlp), NFS/autofs, Timeshift, fingerprint driver, web-app favicons, firmware. |

Note: the dotfiles *clone* (your gitconfig/tmux/ssh keys) moves to REST because it's
network; gatherd's own templated config stays in CORE, so the first session still
looks and feels like yours (fonts, keybindings, power behavior, keyring unlock) even
before the portal is cleared.

## Decisions locked (with the human, this conversation)

- **Two-tier split** is the chosen shape (over fail-soft-in-place or per-task
  aggregation).
- **"Usable beats complete"** — making the first login wait for a *fully* configured
  desktop is **negotiable**. A usable session you can't be locked out of wins.
- **Cut on the network axis, not the importance axis.** This is the captive-portal
  decision: the blocking tier must complete with no internet.
- **Separate playbooks, not tags.** Ansible parses the whole file before tag filtering,
  so a syntax error in a `rest`-tagged task still fails the parse of a core run. Only
  separate files give the parse-isolation that kills "a typo bricks boot."
- **Fail-open in a POSIX-sh wrapper, always `exit 0`.** This is the s6-portable
  variant; systemd `TimeoutStartSec=`/`OnFailure=`/ordering-failure semantics do not
  port. The `exit 0` is also what keeps greetd-gating safe under *both* systemd and
  s6-rc (a failed oneshot blocks dependents in both).
- **Offline cache prefers prebuilt AUR.** Building AUR once on a reference machine and
  shipping `.pkg.tar.zst` flips AUR from the slowest/riskiest step into a plain package
  install — and sidesteps Artix build-time systemd-assumption snags.
- **Second USB stick first; baked-into-ISO later.** Single-medium (cache on the install
  ISO) is natural follow-on once a custom Artix ISO exists, not the first cut.

## Phases

Each phase is independently landable and testable. Run `ansible-lint` (config:
`.ansible-lint`) before committing each; prefer fixing over `noqa`. When a phase is
done and verified, fold its check into `section_verify` in
`scripts/gatherd-post-setup-notes` and prune the corresponding `plans/TODO.md` item
(per CLAUDE.md "Finishing a TODO item").

### Phase 0 — Safety net first (fail-open wrapper around the *current* monolith)

*Highest value, lowest risk, no refactor. Kills "a typo bricks boot" immediately,
before any restructuring, and establishes the portable wrapper pattern the core will
reuse.*

- Add `scripts/gatherd-run-core` (POSIX sh, mirrors `gatherd-await-and-run`'s shape —
  which already does the needs-run check, the galaxy install, and the inhibit, so model
  on it):
  1. `ansible-playbook --syntax-check <playbook>` first; on failure, record the error
     to a failure marker and `exit 0` **without attempting the run** — a syntax error
     can then never even try to brick the machine.
  2. Run the playbook non-interactively: redirect `</dev/null`, wrap in `timeout <N>`
     so a hang can't wedge boot, force any vault via `--vault-password-file`.
  3. Record outcome (success / failure / timeout + a log path) to
     `/etc/gatherd/last-run` (or similar). **Always `exit 0`.**
- Repoint `gatherd.service` at the wrapper: `ExecStart=gatherd-run-core site.yml`,
  absorbing the galaxy install (today's `ExecStartPre`) and the `systemd-inhibit`
  (today's `ExecStart`) into the script — exactly as `gatherd-await-and-run` already
  does for the async unit. Keep `Before=greetd.service`. The unit gets thin and portable.
- Surface failures at login: have a `gatherd-prompt-*` script read the failure marker
  and show "setup failed at X — log here, re-run with Y" (notification + a
  post-setup-notes line). This is the complaint-#2 fix.
- **Confirm the empirical question** from Diagnosis: deliberately introduce a failing
  task, boot, and observe whether greetd comes up (clean failure) or hangs. Record the
  finding here.

**Test:** Introduce a syntax error → boot still reaches greetd; failure surfaces at
login; next boot retries. Introduce a hanging task → `timeout` fires, greetd still
comes up. A clean run is unchanged (`/etc/gatherd/complete` written, no re-run).

### Phase 1 — Package lists as single source of truth

*Pure refactor, no behavior change. Prerequisite for both the split and the offline
builder.*

- Lift the inline package lists out of the tasks into vars, in `group_vars/all/main.yml`
  alongside the existing `web_apps`/wallpaper config (or role `vars/`): e.g.
  `core_packages`, `rest_packages`, `aur_packages`, `aur_slow_packages`. Tasks install
  `{{ rest_packages }}` etc. The offline builder (Phase 4) downloads the same lists. No
  drift.

**Test:** Full idempotent run reports zero changes vs. before the refactor; `ansible-lint`
clean.

### Phase 2 — The core/rest split on the network axis

*The big structural move. Implements the boundary table above.*

- Split each role's `main.yml` into a `core.yml` + a `rest.yml` task file (honoring the
  "tiny task files" convention). `dotfiles`-clone, `aur`, and `hardware` become
  entirely REST; system `/etc` essentials and desktop config templates are CORE.
- Create `site-core.yml` (local-only; the three plays trimmed to CORE includes). Fold
  the REST includes into the existing `site-async.yml` (whose three plays already pull
  in `roles/system/tasks/slow.yml` and `roles/aur/tasks/slow.yml` and write the
  `async-complete` sentinel — expand and repoint, don't replumb). Drop
  `any_errors_fatal: true` from the REST plays so one failed package doesn't abort the
  rest of a post-login convergence.
- Re-aim the Phase 0 wrapper at the core playbook: `gatherd-run-core site-core.yml`. REST
  stays on the existing `gatherd-async.service` / `gatherd-await-and-run`.
- Two sentinels: `/etc/gatherd/core-complete` + `/etc/gatherd/async-complete`
  (`gatherd-needs-run` already takes the sentinel path as an arg).

**Test:** On a repave with the **network cable pulled**, greetd comes up after CORE
alone (no hang); first session has your fonts/keybindings/keyring. Reattach network,
log in → REST converges in the background (progress visible via
`gatherd-show-slow-progress`). A forced failure in any REST task does not affect the
booted session.

### Phase 3 — REST tier connectivity-awareness (real internet, not the portal lie)

*Make REST wait for actual connectivity or proceed offline, so it survives a captive
portal instead of failing against `network-online.target`.*

- Teach the REST runner to wait for *real* connectivity — an active probe (fetch a
  known check URL), reusing the connectivity logic from `CAPTIVE-PORTAL.md` — **or**
  proceed immediately if the offline cache is present (Phase 4). Same wait-loop shape
  as `gatherd-await-and-run` already uses.

**Test:** Boot behind a simulated portal (see `CAPTIVE-PORTAL.md` Phase 2 local
validation for the NM connectivity-override trick). REST waits rather than failing;
after the portal is cleared in-session, REST proceeds and converges.

### Phase 4 — Offline USB cache feeds REST

*Independent; bolts onto the now-isolated REST tier. Subsumes the TODO "USB package
mirror" + "travel-repave behind a captive portal" items and ties into `ARTIX.md` Step 2
(the same stick can carry the Broadcom `wl` driver).*

- `machine_facts`: add `has_offline_cache` probe (look for a labeled USB — e.g. fs
  label `GATHERD` or a `gatherd-offline/manifest` sentinel). `has_*` idiom.
- Source-switch the network steps in REST with `when: has_offline_cache`:
  - **pacman:** add the stick as a `file://` local repo in `pacman.conf` (a directory
    of `.pkg.tar.zst` + a `repo-add`-generated `.db`), or `--cachedir`.
  - **AUR:** install the **prebuilt** `.pkg.tar.zst` from the same local repo (no yay
    compile, no upstream GPG on the road). yay itself prebuilt.
  - **galaxy:** point `ANSIBLE_COLLECTIONS_PATH` at vendored collections on the stick;
    skip the online `ansible-galaxy install` the services run.
  - **dotfiles:** clone from a `git bundle`, then reset the real remote.
  - **GPG keys / wallpapers / web-app icons:** import/copy from stick files instead of
    `curl`.
- `scripts/gatherd-build-offline-cache`: resolves the official-package closure
  (`pacman -Syw` into the repo dir), builds the AUR set in a clean chroot
  (`devtools`/`makechrootpkg`), `repo-add`s everything, vendors collections, bundles
  dotfiles, copies keys/assets, and writes a **manifest stamped with the git HEAD it
  was built from** (mirrors the `complete`-sentinel pattern). The converger compares
  stick-HEAD to deployed HEAD and notes staleness in post-setup-notes; fetches the
  delta online if connected.
- Trust: a self-built repo with `SigLevel = Optional TrustAll` is acceptable;
  optionally sign the repo db with your own key.

**Test:** Build a stick from `gatherd-build-offline-cache`. Repave with the stick
inserted and **no network at all**; confirm REST installs everything (incl. AUR) from
the stick and converges fully offline. Remove the stick → REST falls back to network
unchanged.

### Phase 5 — Catch errors before the laptop (CI), optional/ongoing

*Attacks complaint #2 at the root: errors surface in CI with line numbers, on a machine
that isn't your travel laptop.*

- The `--syntax-check` gate already lands in Phase 0's wrapper.
- Add CI (GitHub Actions, Arch container): `ansible-lint` + `--syntax-check` + ideally
  a full convergence run in the container (molecule-style). The same Arch-container
  infra can build the Phase 4 offline cache as a downloadable artifact before a trip —
  one pipeline validates the playbook *and* produces the stick.

**Test:** A pushed syntax error fails CI before it ever reaches a machine.

## Portability (Artix / s6)

The whole plan is built to port (consistent with `ARTIX.md` and the existing
"logic in POSIX scripts + `has_*` facts" philosophy):

- **Wrapper-based fail-open** (`gatherd-run-core`): init unit just execs it. systemd
  `ExecStart=gatherd-run-core …`; s6 run script `exec gatherd-run-core …`. The
  always-`exit 0` keeps greetd-gating safe under both systemd ordering and s6-rc
  dependencies (a failed oneshot blocks dependents in both — so never fail at the init
  level; record real status in a marker file instead). This is not hypothetical:
  `gatherd-async.service` + `gatherd-await-and-run` already do exactly this on `main`
  (POSIX sh holding the wait, needs-run check, galaxy install, and inhibit), with a unit
  comment stating the goal is non-systemd portability. Phase 0 generalizes that proven
  pattern to the CORE service.
- **CORE local-only** means the gate is short and can't hang on network, so "block
  greetd briefly" is cheap and safe on either init; `Before=greetd.service` becomes an
  s6-rc dependency.
- **Offline cache** (pacman `file://` repo, prebuilt AUR, bundle, asset-copy, manifest)
  is entirely init-agnostic; pacman is identical on Artix; prebuilt AUR sidesteps
  Artix's build-time systemd assumptions because you build on a matching reference
  machine.
- No phase adds a new systemd dependency.

## Cross-references

- `plans/ARTIX.md` — the EOS→Arch→Artix migration. Step 2's USB driver staging shares
  the stick this plan builds; the `bootstrap.sh` work is upstream of CORE.
- `plans/CAPTIVE-PORTAL.md` — the init-agnostic connectivity watcher; Phase 3 reuses
  its connectivity logic and local-simulation trick.
- `plans/TODO.md` — the "Automate preparing a local package mirror on a USB stick" and
  "Travel-repave behind a captive portal" items are subsumed by Phases 3–4; prune them
  as those phases land.

## Out of scope / do not do

- Do not implement the split with **tags** (no parse isolation — see Decisions locked).
- Do not let the wrapper exit nonzero at the init level (blocks dependents under both
  systemd and s6).
- Do not put any network operation in the CORE tier.
- Do not bake the cache onto the install ISO in the first cut (second stick first).
</content>
</invoke>
