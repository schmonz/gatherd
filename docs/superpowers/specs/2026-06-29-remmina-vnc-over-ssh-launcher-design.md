# Remmina VNC-over-SSH launcher (hostname-templated)

## Problem

Reaching another machine's desktop today means a per-machine saved Remmina
profile (e.g. `group_vnc_pet-power-plant_localhost-5900.remmina`): VNC to
`localhost:5900` through an SSH tunnel to that host. The pattern is identical
across the fleet — only the hostname changes — yet each machine needs its own
saved profile. Preconfiguring Remmina this way would force the playbook to know
every machine name (and re-converge as the fleet changes), which we explicitly
do not want until there is a programmatic fleet list to converge on.

We want: open one thing, type a hostname, get the right VNC-over-SSH connection —
with no machine names baked into the playbook or persisted in Remmina's profile
list.

## Constraint that shapes the design

Remmina's quick-connect bar only sets the protocol's server; it cannot enable or
configure an SSH tunnel. So "type a host in the Remmina GUI and have it tunnel"
is not possible natively. Instead we drive a connection ourselves: generate an
ephemeral profile and hand it to `remmina -c`.

## Approach

A runtime launcher, `gatherd-remmina-connect`, invoked from an app-menu entry.
It prompts for a host via fuzzel (with recent-host history), substitutes the host
into a fixed VNC-over-SSH profile template, writes a throwaway `.remmina`, and
runs `remmina -c <tmpfile>`. The Remmina startup GUI is never used.

The template is fixed — it mirrors the proven working profile and only the host
(and optionally user/port) is variable:

- `protocol=VNC`, `server=localhost:5900`, no VNC auth (blank password,
  `ignore-tls-errors=1`)
- `ssh_tunnel_enabled=1`, `ssh_tunnel_server=<host>:<port>`,
  `ssh_tunnel_username=<user>`, `ssh_tunnel_auth=2` (public key via the agent)
- `name=<host>` so Remmina's title bar names the connection

## Components

| Artifact | Source | Installed to | Purpose |
|---|---|---|---|
| `gatherd-remmina-connect` | `scripts/` | `~/.local/bin/` | launcher: fuzzel prompt → temp profile → `remmina -c` |
| `Remote Desktop (VNC over SSH).desktop` | `roles/desktop/templates/` | `~/.local/share/applications/` | app-menu entry execing the launcher |
| `roles/desktop/tasks/remmina.yml` | new task file | — | installs the two artifacts; included from `roles/desktop/tasks/main.yml` |
| verify item | `scripts/gatherd-post-setup-notes` | — | mechanical + functional check |

Lives in the **desktop** role because it is per-user session tooling, alongside
`gatherd-polkit-agent` and the other `~/.local/bin` helpers. The stock Remmina
`.desktop` entry is left visible (Remmina stays installed and usable directly).

## Launcher behavior

1. Read MRU history from `~/.local/state/gatherd/remmina-hosts` (one host per
   line) and pipe it to `fuzzel --dmenu --prompt 'host: '`. The user picks an
   existing host or types a new one. fuzzel returns the typed text on Enter even
   when it matches no list entry — the same free-text behavior `gatherd-askpass`
   relies on.
2. Empty or cancelled selection → exit 0, do nothing.
3. Parse the input:
   - optional `user@` prefix → `ssh_tunnel_username` (default: current `$USER`)
   - optional `:port` suffix → SSH port (default: `22`)
   - remainder → host, passed verbatim (SSH config / DNS / tailscale resolve it;
     the launcher never canonicalises or knows names)
   So `pet-power-plant`, `schmonz@ap-juicer`, `host:2222` all work.
4. Prepend the host to the MRU file, de-duplicated, capped at ~20 entries.
   Best-effort: a write failure does not block connecting.
5. `mktemp` a `.remmina` file, fill the template, run `remmina -c <tmpfile>`,
   and delete the temp file when Remmina exits. `-c` connects to a file without
   importing it into the datadir, so no machine name persists in Remmina's saved
   profile list.
6. `--print <host>` flag: emit the generated profile to stdout and exit without
   launching. Lets the verify step assert the generated config mechanically
   instead of requiring a live connection.

## Data flow

```
fuzzel (host) -> parse user@host:port -> temp .remmina -> remmina -c
  -> SSH tunnel to <host>:<port> (pubkey via agent)
  -> localhost:5900 VNC, no auth
  -> live Sway session on the target
```

First connection to a new host shows Remmina's own SSH host-key-trust dialog
(expected, once per host; stored thereafter).

## Error handling

- Empty/cancelled fuzzel: no-op exit.
- Unreachable host / SSH failure / pubkey not authorised: Remmina surfaces its
  own connection error dialog.
- MRU file read/write failure: non-fatal; the prompt still works with no history
  and the connection still proceeds.

## Testing / verification

Added to `section_verify` in `scripts/gatherd-post-setup-notes`:

- **Mechanical:** `gatherd-remmina-connect --print testhost` prints a profile
  containing `protocol=VNC`, `server=localhost:5900`, `ssh_tunnel_enabled=1`,
  `ssh_tunnel_server=testhost:22`, `ssh_tunnel_username=<user>`,
  `ssh_tunnel_auth=2`, and an empty `password=` (no stored VNC secret). With
  `schmonz@host:2222`, the printed `ssh_tunnel_username` is `schmonz` and
  `ssh_tunnel_server` is `host:2222`.
- **Functional:** the app menu (Mod-D) lists "Remote Desktop (VNC over SSH)";
  launching it pops a fuzzel `host:` prompt offering recent hosts; typing a
  reachable fleet host lands in its Sway session with no VNC password prompt;
  Remmina's saved-profile list afterward contains no entry for that host.

## Defaults / decisions

- SSH user defaults to the local `$USER` (= `schmonz`); overridable per-connect
  with a `user@` prefix.
- VNC is always no-auth. Macs (which require a VNC-layer credential) are out of
  scope for this launcher; use Remmina directly for those.
- Recent-host history is capped at ~20.
- The stock Remmina app-menu entry is kept; no sway keybind is added.

## Out of scope

- A programmatic fleet list / self-hostname-lookup (the future state that would
  justify pre-seeding per-machine profiles).
- Mac Screen Sharing connections.
- A sway keybind (app-menu entry only).
