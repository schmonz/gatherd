# Retiring spent migration tasks

**Status:** Approved design; implementation plan pending.

## Problem

The playbook accumulates work that exists only to carry old machines forward.
When `/etc/profile.d/gatherd-local-bin.sh` was replaced by `pam_env`, the
replacement shipped with a task to delete the file machines already had. Same
for the environment.d askpass files, the gatherd path units, the sudo timestamp
drop-in, and — as of `dc7b12b` — the `claude-desktop-bin` package.

Each is correct when written and useless once every machine has converged past
it. Nothing records when that happens, so they accumulate. The oldest dates to
2026-05-03 and there are nineteen.

This is the failure the repave-cadence rule in `CLAUDE.md` was written to fix
for `verify_li` entries: a list that only grows because nothing says when an
entry is spent.

## The observation this rests on

**A fresh install needs no migration at all.** Every migration exists to fix a
machine that ran an *older* playbook; a machine installed from scratch at HEAD
never had the old state and never needs the fix.

So a full-fleet reinstall does not merely age migrations — it spends **all of
them at once**, every migration that existed at that moment, regardless of when
each was written. No per-task dates are needed, and there is no proxy involved:
the retirement is exact.

The one uncertain input is whether every machine really was reinstalled. That is
not derivable from the repo, from git, or from the machines — the live set is
unknown and `inventory` is just `localhost`. It is a fact only the human holds,
so the design's whole job is to give that fact somewhere to live.

## Design

### The ledger

`MIGRATIONS.md` at the repo root. Two sections:

    # Migrations

    Every machine reinstalled since: 2026-09-01

    ## Live

    - 2026-09-14  roles/aur/tasks/slow.yml — remove claude-desktop-bin,
                  superseded by claude-desktop (dc7b12b)

    ## Spent — delete these

    - 2026-05-29  roles/system/tasks/user_path.yml — remove the profile.d
                  PATH file replaced by pam_env

An entry is one line: the date it was written, where it lives, and what it
carries forward. Entries below the watermark date are spent by the observation
above; entries above it are live.

### The rule

Two halves, both in `CLAUDE.md`:

1. **Writing a migration adds a line** to the Live section, dated that day. This
   sits beside the existing rule about adding a `verify_li` step when a feature
   lands — the same moment, the same habit.
2. **Reinstalling the last machine moves the watermark** to that date. Every
   entry now below it is spent: delete those tasks from the playbook and those
   lines from the ledger, in one commit.

There is no script. Sorting by date makes the split visible, and a human deletes
the tasks either way — the checker in every earlier draft of this design would
only have printed what a reader can already see.

### Backfill

List the nineteen known migrations under Live, with the dates recovered while
investigating this (pathspec-scoped `git log -S"<name>" --reverse -- roles/`,
used once as an aid and not as a mechanism). Leave the watermark unset until the
next full-fleet reinstall, at which point all nineteen retire together.

The known migrations: the environment.d and profile.d PATH/Go files, the
environment.d askpass and sentinel files, the per-user gatherd-askpass, the
gatherd path units and their links, the superseded sudo timestamp drop-in, the
obsolete systray autostart entries, the obsolete gnome-keyring `--unlock`
autostart lines, the superseded autofs ordering drop-ins, the obsolete ssh
host-key float rule, the now-orphaned polkit autostart comment, the per-helper
autostart entries now launched by the session supervisor, the old tablet mode
and music stand keystrokes, the superseded claude-desktop-bin, and `force: true`
on `Link the hinge-sensor udev rule`.

Two classification notes from the investigation, worth keeping because both were
initially got wrong:

- The gnome-keyring **PAM auth line** is upstream's and permanent; the
  gnome-keyring **autostart line** is gatherd's own and a migration. `58f3522`
  added that autostart line, `e3b0612` dropped the feature, `54eade9` added the
  cleanup.
- `Remove vestigial Chromium browser config` was classified permanent on first
  pass; its own comment says it removes files "on already-provisioned machines",
  which makes it a migration. Confirm against `a913393` when writing its entry.

Not migrations, and deliberately absent from the ledger: removals of upstream's
own output, which returns on every fresh install (the EndeavourOS wallpapers,
the stock swayidle lines, the waybar network widget, the sway-install.sh gparted
entry, `Remove firefox`, the polkit-gnome agent and package, the EOS logind
drop-in, the clight autostart and clightd service, the gnome-keyring PAM line);
and runtime hygiene that heals a killed run (the stale repository lock, the
aurutils and nowayprompt build artifacts, the partial Vencord bundle discards).

## What this gives up, deliberately

**A forgotten line is invisible.** Nothing detects a migration written without a
ledger entry. Three prior drafts of this design tried to close that hole
mechanically and none succeeded; the record is below, because the reasons are
specific and worth not rediscovering.

**"Every machine" is a human judgement.** A forgotten machine in a closet
invalidates the watermark for exactly the migrations it needed. It then fails
its converge loudly, which is the accepted signal to reinstall it — the same
contract every earlier draft assumed.

Note the asymmetry in how loud that failure is. A **CORE** failure notifies:
`scripts/gatherd-prompt-lastrun` fires `notify-send --urgency=critical` at every
login until a run records `ok`. **REST** is the quiet tier — there is no
`async-complete` equivalent of `last-run`, which is why the 2026-08-31 failure
left no trace outside `systemctl status`. Several migrations are REST-tier,
including `Remove the superseded claude-desktop-bin`. Giving REST a `last-run`
equivalent would make the fallback real, and is the most valuable follow-on to
this work.

## Rejected alternatives, and why

Recorded because each was rejected on evidence, and re-proposing them is the
likely failure mode.

**Dating tasks from git.** `git log -S"<name>"` misattributes: with no pathspec
it dates `Remove the obsolete ssh host-key float rule` to `e9a65d8`, a *plan
document* containing the task verbatim, rather than `462b4c5` which added it.
(Both are 2026-08-21 here, so the observed error is zero days — but this repo
keeps dated plans for months, so the mechanism is unsound even where this
instance is harmless.) `-S` is also a substring match, and `Install clight` is a
substring of `Install clightd`. `git blame` is worse: it puts nine of seventeen
removals on `662364d`, a pure file move; `-w -C -C -M` recovers five of nine.

**A per-task marker plus a checker.** Three drafts, each broken by measurement:

- A `# migration:` comment is invisible to `yaml.safe_load`, and under
  `ruamel.yaml` attaches to three different places depending on the task's
  position.
- An Ansible `tags: migration` marker fares no better: a tag on a `block:` is
  inherited at runtime but `safe_load` puts it on the block dict with the child
  showing no `tags` key — the same ambiguity, plus the checker must reimplement
  tag inheritance.
- Default-deny over "migration-shaped constructs" needs a shape list, and the
  shapes do not discriminate. `force: true` with `state: link` matches five
  tasks in this tree, of which one is a migration and four are the ordinary
  symlink idiom (`resolv.conf` twice, `~/trees`, the aurutils repo database).
  A rule with 1-in-5 precision trains reflexive dismissal.
- A registry keyed by `<file>::<name>` collides today: six tasks named `Flush
  handlers` live in `roles/system/tasks/core.yml`.

**Proving classification in the VM.** `tests/test` boots a fresh EOS snapshot and
runs the playbook twice, which looked like a way to prove no migration is really
a permanent removal. It is not: run 1 is executed with no `tee` and no log (only
run 2 is captured); `ansible-playbook` prints `TASK [role : name]` with no file,
so output cannot be joined to a file-qualified key; and migrations such as
`Remove obsolete gatherd path units` carry `changed_when: false` and can never
report `changed` at all.

**A fleet ledger on shared storage.** Each machine records its converged commit
in `/etc/gatherd/core-complete` and `/etc/gatherd/async-complete`, so collecting
them would give an exact floor. But the NFS mount is REST tier
(`roles/system/tasks/rest.yml:171`) over Tailscale: a machine that cannot reach
the server never reports, and nothing distinguishes a straggler from a
decommissioned machine, so the floor only ever moves down.

**Coupling the trigger to the repave-cadence rule.** That rule counts
`verify_li`, which stands far above its threshold of 10 and so fires
continuously; and it would stop firing entirely if that backlog were worked down,
disabling the migration rule exactly when the repo got healthy. Backlog depth and
fleet state are unrelated quantities. The watermark's trigger is the reinstall
itself, which is the event that actually spends migrations.
