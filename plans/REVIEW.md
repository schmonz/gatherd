# Project Review

## What would make it more obviously correct

The biggest gap is that there are no idempotency checks. You can't know the playbook is correct until you repave — which you've been doing repeatedly this session. Running it twice and asserting the second run has zero changes would catch most bugs without hardware. Related: ansible-lint is configured and thoughtful, but there's no CI enforcing it on push, so lint regressions only surface when you remember to run it manually.

The `machine_facts` role is the best-documented part of the codebase — each probe has a comment explaining *why*, not just what. The rest of the roles don't hold that standard. The desktop role in particular is a long sequential list where it's hard to tell which tasks are load-bearing and which are cosmetic tweaks.

## Smaller concepts struggling to be freed

`machine_facts` is genuinely portable. It has zero dependencies on gatherd's specific packages or configuration — it's pure hardware detection for Arch-family Linux. Someone provisioning a Pinebook Pro or MacBook on Arch would want exactly this. It could be published as a standalone Galaxy role.

The `gatherd-*` scripts are a small Sway session utility library. They're independently useful and could live as a separate package or AUR entry — people running Sway on Arch without your provisioning setup might still want `gatherd-launch-systray`, `gatherd-prompt-captiveportal`, etc.

The `postinstall` script and the Ansible playbook are conceptually distinct artifacts that happen to live in the same repo. That's probably fine, but it's worth being explicit: postinstall is a Calamares hook that runs once during install; Ansible is the convergence engine. They have different audiences if you ever share this.

## Testability

`vm/test` boots the Arch Linux cloud image under QEMU, runs `site.yml`, then runs it again and asserts `changed=0`. Run it before repaving. Next step: extend to cover `site-user-async.yml` and `site-vault.yml`, and eventually the full `postinstall` → service chain.

`bats` is installed but there are no tests for the shell scripts. The `gatherd-show-slow-progress` logic, `gatherd-prompt-*`, and the systray scripts have real testable behavior.

## Deferred

- **Tags**: no tags within phases. Tags let you re-run just the waybar config, or just AUR packages, without the full playbook. Worth doing once there's a converge/re-run story.
- **`become: false` hygiene**: some tasks run as root that don't need to. Audit which tasks don't need root and add `become: false` explicitly.

## What you should want given your goals

The most notable missing piece is an **update story**. Right now the sentinel file means Ansible runs exactly once, forever. Config drift on an existing machine has no automated remedy — you either repave or manually remove the sentinel and re-run. A `gatherd-converge` script that re-runs just the config parts (desktop role, system config, no package installs) on demand would let you push a dotfile change and apply it to all machines without repaving. This is the core value proposition of Ansible and it's currently only half-realized.

Related: there's no record of *when* or *which version* of the playbook ran on a given machine. A file written during provisioning with the git SHA would let you answer "is this machine current?"

Finally — secrets management for future credentials (iCloud tokens, etc.): use vault rather than committing them plaintext.
