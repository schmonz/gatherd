# Tablet-mode extraction — handoff

**Written 2026-08-21.** Tasks 1–6 of
`docs/superpowers/plans/2026-08-21-tablet-mode-extraction.md` are complete.
Task 7 is not started and needs a human plus a machine that is not reaching
the repo across an ocean.

## Where the work is

**`/home/schmonz/trees/chuwi-minibook-tablet-mode`** — local btrfs, not the NFS
mount. HEAD `03c972a`, clean tree, **259 assertions passing**, `.git` is 340 KB.

It has never been pushed and has no remote. Nothing here creates one.

```
bin/         minibook-{tablet-mode,hinge-daemon,power-button,compositor,bind-hinge-sensor}
udev/        99-minibook-hinge-sensor.rules
supervisor/  dinit  openrc  runit  s6  systemd     (examples; install.sh installs none)
etc/         config.example  menu.example
tests/       tablet-mode                            (259 assertions)
docs/        design.md  PORTING.md
install.sh   README.md
```

## What a human must do next

1. Create `chuwi-minibook-tablet-mode` on GitHub.
2. `git remote add origin …` and push `main`.
3. Tag it. **Versions are date-based**, e.g. `0.0.20260821.1` — the trailing
   counter distinguishes multiple releases on one day. gatherd pins this exact
   string in `tablet_mode_upstream_version`.

Task 7 cannot start before that: gatherd clones the repo **by tag**.

## Task 7, in one paragraph

Give gatherd a role that clones the new repo at a pinned
`tablet_mode_upstream_version`, runs `install.sh --prefix ~/.local`, and
templates the config plus the folded-menu entries (`label|command`, one per
line) that supply gatherd's music-stand actions. Delete the five moved scripts
from `scripts/`, repoint the remaining references (`roles/desktop/tasks/core.yml`
binds `XF86PowerOff`; `scripts/gatherd-session-helpers` starts the daemon;
`gatherd-music-stand` calls `minibook-tablet-mode`; `gatherd-post-setup-notes`
names the commands in its verify steps), and reduce gatherd's
`tests/tablet-mode` to the music-stand assertions only, renamed
`tests/music-stand`. Full detail in the plan's Task 7.

## Do this on a machine near the NFS server

`/code` is exported from `ap-juicer` and reached over Tailscale. Measured from
here: **131 ms RTT, 25% packet loss, `git status` 47.7 s** against 0.00 s on
local disk. Every gatherd test run, lint and commit pays that. It is also the
most likely explanation for two test "flakes" that were investigated and never
explained — the suite's timing-sensitive assertions poll with 2-second budgets
while invoking repo scripts hundreds of times.

## A 25 GB finding, unrelated to this work

`gatherd/.git` measures 25 GB. It is **not** a history problem — no committed
VM images, no large blobs (largest object in history: 2 MB), and no
`filter-repo` surgery is needed. It is seven abandoned `tmp_pack_*` files of
~3.5 GB each in `.git/objects/pack/`, all dated **May 28**, left by interrupted
repacks, plus a stale `.git/objects/maintenance.lock` from **Aug 19**.

```
rm -f .git/objects/pack/tmp_pack_* .git/objects/maintenance.lock
```

Run it when no git process is touching the repo. Also check
`git config --get maintenance.auto`: background maintenance on a repo behind a
slow link will keep starting repacks it cannot finish, which is presumably how
seven of them accumulated. Real objects total ~25 MB, so this is the entire
difference between a clone that finishes in seconds and one that does not
finish at all.

## Also on the live machine right now

- `/etc/udev/rules.d/99-minibook-hinge-sensor.rules` — installed during the
  spike, and the machine currently depends on it to bind the base
  accelerometer. It is the same file as `udev/` in the new repo.
- `~/.local/bin/gatherd-*` — the currently-running tablet mode. Untouched by
  the extraction; gatherd still owns it until Task 7.
- macOS AppleDouble files (`._.gitignore`, `scripts/._gatherd-*`) are on the
  NFS share and broke a `git clone` during Task 1. Something with that share
  mounted is writing resource forks.

## What review caught, so the next person trusts the same process

Nine defects were found and fixed after their task was "done and green":

- `git filter-repo --replace-text` rewrites blobs ONLY; commit messages need a
  second pass with `--replace-message`. Caught by a verification step written
  so it could actually fail.
- The config path move was specified in the spec AND the plan's constraints,
  and assigned to no task. Both self-reviews missed it.
- A menu file without a trailing newline silently dropped its last entry; a
  line with no `|` became an executable menu entry.
- `minibook-tablet-mode off` could abort under `set -e` before restoring input
   — contradicting the comment directly beneath it.
- A user config with a syntax error disabled BOTH escape routes.
- The shipped `power_menu` default silently killed the power button on any
  non-EndeavourOS machine.
- **CRITICAL:** an unhandled `OSError` in the daemon's sensor read killed the
  process mid-fold, after which unfolding no longer restored the keyboard.
  Confirmed on the real machine during the udev spike: deleting the sensor
  killed the running daemon exactly as predicted.
- A second wave found the same class in two more paths (`subprocess.run` with a
  missing executable, a non-UTF-8 config byte), which is why `loop()` now has a
  last-resort guard that logs and continues rather than dying.

Three assertions that could not fail were found and replaced. Mutation testing
— re-introducing each bug and confirming the new test fails — caught all of it.
Do not trust a green suite here without it.

## Open, not blocking

- BATS conversion of the suite: deliberately deferred to its own plan. Doing it
  inside the extraction would have destroyed the evidence that the extraction
  changed no behaviour.
- `docs/fuzzel-touch-scroll-issue.md` in gatherd: a written, unfiled bug report
  for fuzzel's touch-drag direction.
- gatherd's `section_verify` is at 14 items against its own threshold of 10.
