# A measured ledger for migration tasks

**Status:** Approved design; implementation plan pending.

## Problem

The playbook accumulates work that exists only to carry old machines forward.
When `/etc/profile.d/gatherd-local-bin.sh` was replaced by `pam_env`, the
replacement shipped with a task to delete the file machines already had. Same
for the environment.d askpass files, the gatherd path units, and — as of
`dc7b12b` — the `claude-desktop-bin` package.

Each is correct when written. Some become useless once every machine has
converged past them; others never do. Nothing records which is which, so they
accumulate the way the `verify_li` list did.

## Why this design records rather than retires

Four earlier designs tried to identify and delete the spent ones. Each broke on
one of two facts, both measured.

**Classification is sometimes ill-posed.** The taxonomy those designs used — a
removal targets either gatherd's own former output or upstream's, never both —
is false. `Remove the now-orphaned polkit autostart comment` uses
`regexp: '^# Auth with polkit'`, which is anchored at the start but *not at the
end*. Upstream EndeavourOS ships a line it matches:

    $ curl -sS https://raw.githubusercontent.com/EndeavourOS-Community-Editions/\
    sway/main/.config/sway/config.d/autostart_applications | grep -nE '^# Auth with polkit'
    4:# Auth with polkit-gnome:

and `ea8623d` rewrote that same line on older machines to `# Auth with polkit
(fuzzel via gatherd-polkit-agent):`, which also matches. So one `state: absent`
regexp strips gatherd's own former output on old machines *and* upstream's
original on every fresh install, forever. No marker, tag, or ledger field can
express "retire half of this task's job."

Note the reference state that claim depends on: `postinstall` pipes
`setup_sway_isomode.bash` from upstream's **`main`** at install time, so what a
fresh machine receives tracks a branch no repo artifact pins. Any check against
that file can change meaning with no commit here.

**Getting it wrong fails silently.** Most of these are `state: absent` on files:
delete the task and stale state simply persists, with `/etc/gatherd/last-run`
still recording `ok`. `Remove obsolete gatherd path units` carries
`failed_when: false` and `changed_when: false` and cannot report anything at
all. The loud-failure case that started this work — `Remove the superseded
claude-desktop-bin` — is REST-tier, the tier where nothing notifies.

A low reward (deleting dead code) against silent, months-delayed breakage on
machines that cannot be enumerated is a bad trade. **So this design records and
measures; it does not retire.** A measured entry becomes a deletion candidate
only for someone already working in that file.

## Design

### The census is mechanical, not curated

A script enumerates removal-shaped tasks — `state: absent`, `force: true` with
`state: link`, `enabled: false`, `masked: true` — across `roles/`, `tasks/` and
`site-*.yml`. On the tree at `da1e871` this yields **46**, against the nineteen
an earlier draft of this document listed by hand.

That gap is the point. Hand curation produced three misclassifications in
nineteen and a list nobody could reproduce from the document. The census is
therefore generated, never typed, and **this design does not pre-classify it**.
Classification is the output of measurement, below.

(The enumerator must attribute a shape to the task that owns it, not to an
enclosing `block:`. A first pass that dumped whole task bodies credited block
parents with their children's shapes — e.g. `Build and install aurutils from the
vendored PKGBUILD` — which is why the count needs a real walker.)

### The ledger

`MIGRATIONS.md` at the repo root, one entry per **removed thing**, not per task.
Granularity matters because several tasks loop over items of mixed provenance:
`roles/desktop/tasks/core.yml` loops eight autostart regexps in one task and
four in another, mixing `^exec conky$` with `^exec (?:.*/)?gatherd-polkit-agent$`.
One verdict cannot cover items that legitimately differ.

Each entry carries a check and **its expected result stated explicitly**:

    - roles/system/tasks/user_path.yml — /etc/profile.d/gatherd-local-bin.sh,
      replaced by pam_env
      check: test -e /etc/profile.d/gatherd-local-bin.sh
      fresh-install expectation: absent (pure migration)

Stating the expectation per entry rather than relying on an absent-means-migration
convention is required because the polarity inverts for additive tasks: a check
like `grep -q zswap.enabled /etc/default/grub` returns *present* on a fresh
install precisely when the task is a no-op there.

Two constraints on writing a check, both from measured failure modes:

- **Never copy a task's regexp into `grep -E`.** Ansible regexps are Python
  `re`. `(?:...)` and `(?!...)` are errors under `grep -E` (GNU grep 3.12 warns
  and exits 1) and work only under `-P`. A copied check silently returns the
  wrong answer.
- **Never use `~` or a bare relative path.** Checks run as root in the
  measurement context, where `~` is `/root`. Write the absolute path or
  interpolate the target user's home explicitly.

### Measurement runs against the base VM image, not a repave

`tests/create-base` boots the real EndeavourOS ISO, a human drives real Calamares
("Online install → Sway desktop"), and the result persists as
`$GATHERD_VM_DIR/eos-base.qcow2`. It never runs gatherd's `postinstall`, so it is
a machine provisioned by Calamares and nothing else — exactly the reference state
the check asks about.

This matters because `postinstall` is gatherd's own code, so a machine that has
run it is *not* Calamares-only. An earlier draft used the strict sense to reject
the VM and the loose sense to admit four tasks (`zswap.yml`, `rotated_panel.yml`,
`phantom_display.yml`, `Enable the early vault console prompt`) to the census.
Under the strict sense those four are not migrations at all — they are the
Ansible halves of twinned bash/Ansible preseeds carrying a documented sync
obligation, and `zswap.yml`'s own comment records that when both twins shared a
bug the Ansible half was the only one that could retro-fix installed machines.
They are excluded.

So the measurement pass is: boot a snapshot of `eos-base.qcow2`, run every
entry's check, record the result and the date against the entry. No repave, no
window to race against `gatherd.service` (which gates greetd and starts
unattended, leaving at most the ~60s of `gatherd-prompt-vault-console`), and no
contention with the 23 `verify_li` items a repave already carries. It is
repeatable, so a check found wrong can be fixed and re-run.

Every entry stays regardless of verdict, including one measured `present`.
`scripts/gatherd-check-migrations` requires every removal-shaped task to have an
entry, so the ledger is a classification record for all of them rather than a
list of migrations only.

A result that contradicts the stated expectation is the finding: it means either
the check is wrong or the belief in the task's comment is. Both are worth
knowing; neither is resolved by editing a comment to match, which an earlier
draft wrongly prescribed.

**A failing check must not read as a negative result.** A missing binary, a bad
regex dialect, or an unexpected path all exit nonzero, which under a naive
reading is the "pure migration" answer — the one that licenses deletion. So a
check is trusted only once it has been *calibrated*: demonstrated returning the
"still does work" answer somewhere it should. An uncalibrated check is recorded
as unmeasured, not as absent.

### The rule

Two halves, in `CLAUDE.md`:

1. **Writing a migration adds an entry**, with its check and expectation. This
   sits beside the existing rule about adding a `verify_li` step when a feature
   lands.
2. **Any unmeasured entry means the ledger is due for a pass** — not a count
   over a threshold. A count cannot work here: unlike a `verify_li` step, which
   is spent once exercised and deleted, a measured migration entry *stays*. A
   ">10" rule would therefore be permanently true and never clearable, which is
   the exact pathology the `verify_li` count is a cautionary tale about (it
   stands at 23 against a threshold of 10 and has never come down).

## Known limits

**A migration written with no entry is invisible.** Nothing detects it. Four
designs tried to close this mechanically and none survived review.

**The ledger has no referential integrity.** Entries are keyed by file path and
prose. `662364d` moved 41 tasks between files, and nothing would detect such a
move, a rename, or a deletion. Unlike `verify_li` steps, which live inside a
script that runs at every login, `MIGRATIONS.md` is inert prose. This also sits
in tension with the repo's stated philosophy that git log is the record of what
was done — the defence is that this file records what is *currently true and
unverified*, which git log cannot answer.

**Checks measure the wrong half of the deletion question.** A check answers
"does this do work on a fresh install?" It does not answer "has every extant
machine converged past this?", which is what actually gates deletion and which
the next limit makes unknowable. An entry marked measured licenses nothing on
its own, and the word must not be read as permission.

**Fleet state is not monotonic.** `roles/system/tasks/timeshift.yml` configures
daily btrfs snapshots of `/` with `include_btrfs_home_for_backup: false`. A
rollback restores `/etc` and `/etc/gatherd/core-complete` while leaving `/home`,
so the machine reports converged via `gatherd-needs-run` and quietly carries old
root-tier state again.

## Rejected alternatives, and why

**Dating tasks from git.** `git log -S"<name>"` with no pathspec dates `Remove
the obsolete ssh host-key float rule` to `e9a65d8`, a *plan document* quoting the
task verbatim, rather than `462b4c5` which added it (both 2026-08-21, so the
observed error here is zero days; the repo keeps dated plans for months). A
pathspec fixes that and `--pickaxe-regex` fixes `-S` being a substring match.
`git blame` is worse: nine of seventeen removals land on `662364d`, a pure file
move. Good enough to seed, never to trigger deletion — which is why no date
appears in the ledger format above.

**A per-task marker plus a checker.** A `# migration:` comment is invisible to
`yaml.safe_load`. An Ansible `tags: migration` marker is inherited from a
`block:` at runtime but attaches to the block dict when parsed. Default-deny
over shapes does not discriminate: `force: true` with `state: link` matches five
tasks, of which one is a migration and four are the ordinary symlink idiom
(`resolv.conf` twice, `~/trees`, the aurutils repo database).

**A watermark date.** "Every machine reinstalled since D" is a *minimum* over the
fleet, but the natural rule — move it when the last machine is reinstalled —
computes the *maximum*, marking spent every migration written during the sweep
while machines reinstalled earlier still need them. The repo also repaves one
machine at a time, so there is no "last machine" event.

**A fleet ledger of converged commits.** `head -1 /etc/gatherd/core-complete` is
exact, free and offline, and the human is at the machine when reinstalling it —
an earlier objection that this needs NFS collection was wrong. Not adopted
because it serves automated retirement, which the silent-failure finding rules
out however good the fleet data is.

**Inferring classification from `tests/test` run output.** Run 1 is executed with
no `tee` and no log, only run 2 is captured, and tasks with `changed_when: false`
can never report `changed`. (An earlier draft also claimed the output cannot be
joined to a file, which is false: `ansible-playbook -vv` prints
`task path: <file>:<line>`.) Running the checks directly against the base image,
as above, avoids all of this.
