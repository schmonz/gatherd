# Project Review

## Immediate correctness issues

- ~~`has_plenty_of_ram` is still detected in `machine_facts` but nothing uses it anymore — CLion was its only consumer. Dead fact.~~ Incorrect: it still gates zswap setup in the hardware role.
- `fwupdmgr` runs with `changed_when: false`, so it always reports "ok" even when it installs firmware. Not wrong, but misleading in run output.
- The WiFi PSK is plaintext in the repo: `psk: "whats4dinner?"`. Even for personal use that's in git history forever.
- `site.yml` and `site-slow.yml` have identical pre_tasks blocks. They'll drift apart. Worth extracting into a shared include.

## What would make it more obviously correct

The biggest gap is that there are no idempotency checks. You can't know the playbook is correct until you repave — which you've been doing repeatedly this session. Running it twice and asserting the second run has zero changes would catch most bugs without hardware. Related: ansible-lint is configured and thoughtful, but there's no CI enforcing it on push, so lint regressions only surface when you remember to run it manually.

The `machine_facts` role is the best-documented part of the codebase — each probe has a comment explaining *why*, not just what. The rest of the roles don't hold that standard. The desktop role in particular is a long sequential list where it's hard to tell which tasks are load-bearing and which are cosmetic tweaks.

## Smaller concepts struggling to be freed

`machine_facts` is genuinely portable. It has zero dependencies on gatherd's specific packages or configuration — it's pure hardware detection for Arch-family Linux. Someone provisioning a Pinebook Pro or MacBook on Arch would want exactly this. It could be published as a standalone Galaxy role.

The `gatherd-*` scripts are a small Sway session utility library. They're independently useful and could live as a separate package or AUR entry — people running Sway on Arch without your provisioning setup might still want `gatherd-launch-systray`, `gatherd-prompt-captiveportal`, etc.

The `postinstall` script and the Ansible playbook are conceptually distinct artifacts that happen to live in the same repo. That's probably fine, but it's worth being explicit: postinstall is a Calamares hook that runs once during install; Ansible is the convergence engine. They have different audiences if you ever share this.

## Testability

The transformative improvement would be a QEMU/libvirt VM that runs the full postinstall → `gatherd.service` → `gatherd-slow.service` → greetd chain. Given how much time in this session was spent repaving real hardware to test one-line changes, a VM that does this in 10 minutes instead of 60 would pay for itself immediately. EndeavourOS provides ISOs; Calamares can run unattended with a config file.

Below that: GitHub Actions running ansible-lint on push would at least catch syntax errors and lint regressions before you get to hardware. You have the lint config already; you just need the workflow file.

`bats` is installed but there are no tests for the shell scripts. The `gatherd-show-slow-progress` logic, `gatherd-launch-systray`, and the prompt scripts have real testable behavior.

## What pro Ansible developers look for

- **`defaults/main.yml` in roles**: your variables are set in `machine_facts` tasks rather than documented in a defaults file. Pro practice is to declare every variable a role uses or provides with a default and a comment, even if it's just `false`.
- **Role READMEs**: none of your roles have documentation. For personal use this matters less, but `machine_facts` especially deserves one.
- **`no_log: true`** on the WiFi task that contains the PSK.
- **Vault**: `ansible-vault encrypt_string` for the PSK takes 30 seconds and eliminates the plaintext-in-git problem.
- **Tags**: you now have a structural fast/slow split, but no tags within phases. Tags let you re-run just the waybar config, or just AUR packages, without the full playbook.
- **`become: false` hygiene**: some tasks run as root that don't need to. Not a correctness issue, but principle of least privilege.

## What you should want given your goals

The most notable missing piece is an **update story**. Right now the sentinel file means Ansible runs exactly once, forever. Config drift on an existing machine has no automated remedy — you either repave or manually remove the sentinel and re-run. A `gatherd-converge` script that re-runs just the config parts (desktop role, system config, no package installs) on demand would let you push a dotfile change and apply it to all machines without repaving. This is the core value proposition of Ansible and it's currently only half-realized.

Related: there's no record of *when* or *which version* of the playbook ran on a given machine. A file written during provisioning with the git SHA would let you answer "is this machine current?"

Finally — and this is probably already on your radar — secrets management. Vault for the WiFi PSK, and possibly for any future credentials (iCloud tokens, etc.) that you might be tempted to add. The git history already has the plaintext PSK; a `git filter-repo` pass and a rotation of the password would clean that up.
