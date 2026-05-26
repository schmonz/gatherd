# Guidelines for this repo

## What this is

Two Ansible playbooks that configure an EndeavourOS/Arch desktop from first boot,
each driven by its own systemd service in `services/`.

**`site.yml`** — run by `gatherd.service` before login (blocks greetd). Three plays:

1. **Detect** (`machine_facts` role) — probes hardware, sets `has_*` boolean facts
2. **System** (`system`, `hardware` roles) — packages, services, `/etc` config as root
3. **User** (`dotfiles`, `aur`, `desktop` roles) — dotfiles, AUR packages, user config
   via `become_user: target_user` using `su` (no sudo needed, runner is root)

Writes `/etc/gatherd/complete` when done; service does not re-run after that.

**`site-user-async.yml`** — run by `gatherd-user-async.service` after `gatherd.service`
completes, in the background. Three plays:

1. **Detect** (same pre_tasks + `machine_facts` as `site.yml`)
2. **Slow system packages** — `roles/system/tasks/slow.yml`
3. **Slow AUR packages** — `roles/aur/tasks/slow.yml`

Writes `/etc/gatherd/user-async-complete` when done.

## Code style

**Task names read like imperative sentences.** A good task name makes the play log
self-documenting. Prefer "Configure swayidle" over "swayidle config task".

**Tiny task files.** Hardware capabilities each get their own file under
`roles/hardware/tasks/`. If a logical unit has a name, give it its own file.

**Use FQCN.** Always `ansible.builtin.*` and `community.general.*` — never bare
module names.

## Conventions

- Hardware capability flags: `has_*` booleans, defaulted false in `machine_facts`,
  set true when detected; gate tasks with `when: has_*`
- Probe pattern: one task to gather data (stat/shell/command + `register`), one task
  to set the fact (`set_fact` with `when:`); `changed_when: false` on all read-only commands
- Runtime scripts (daemons, not setup): live in `scripts/` without extension, installed
  by the playbook
- Systemd service units: live in `services/`, installed by the playbook
- Templates: `.j2` files in `roles/<role>/templates/`
- Handlers: trigger reboots and other post-change actions (e.g. `grub-mkconfig`)
- Slow tasks (long downloads, big compiles): in `roles/<role>/tasks/slow.yml`,
  included by `site-user-async.yml` so they run after login is available

**Idempotency.** Ansible gives this for free with most modules — lean on it.
For `command`/`shell` tasks, use `creates:`, `changed_when:`, or explicit checks.

## Comments

Same rule as always: only explain *why* something is done a non-obvious way — a
hidden constraint, a workaround for a specific bug, a consequence that would
surprise a reader. Don't describe what the task does; the name already does that.

## Linting

`ansible-lint` is configured via `.ansible-lint`. Run it before committing. The
`noqa` marker is a last resort; prefer fixing the lint or restructuring the task.
