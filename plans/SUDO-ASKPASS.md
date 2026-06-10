# sudo: shared credential cache for agent subprocesses

## Status

**The graphical askpass half is already done.** `SUDO_ASKPASS` is set via
`pam_env` (`/etc/security/pam_env.conf`) to `~/.local/bin/gatherd-askpass`,
which gives sudo a Wayland (fuzzel) dialog when invoked with no terminal.
`environment.d` is a black hole in greetd's sway session and is not used.

What's left is the credential-caching behaviour described below.

## The problem

By default sudo caches credentials per-TTY. Each subprocess invocation (e.g.
from an agent shelling out repeatedly) gets its own cache and so triggers a
separate password prompt. We want one shared cache for the user.

## The change

Add a drop-in under `/etc/sudoers.d/` (root-owned, mode `0440`, validated with
`visudo -cf` before install):

```
Defaults:schmonz timestamp_type=global
Defaults:schmonz timestamp_timeout=2
```

- `timestamp_type=global` — share the credential cache across all of the user's
  processes instead of per-TTY, so subprocesses reuse one authentication.
- `timestamp_timeout=2` — shorten the cache window to 2 minutes as a modest
  security tradeoff.

## Implementing in the playbook

- Lives in the `system` role (root-owned `/etc` config).
- Use `ansible.builtin.copy`/`template` with `validate: visudo -cf %s` so a
  malformed drop-in can never break sudo.
- `target_user` is parameterised elsewhere; template the username rather than
  hardcoding `schmonz`.
- Add a `section_verify` step once it works: from a fresh shell, `sudo -K`, run
  one `sudo` command and authenticate, then confirm a second `sudo` from a
  *different* terminal/subprocess within 2 minutes does **not** re-prompt.
