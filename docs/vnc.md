# Remote GUI access via VNC over SSH — EndeavourOS Sway fleet

The machine side is now automated by gatherd: the `wayvnc` server, its
`~/.config/wayvnc/config` (localhost, no auth), the session-cohort launch, and
the Remmina client are installed and configured by the system + desktop roles.
The checks live in the "Remote GUI via VNC over SSH" item of
`scripts/gatherd-post-setup-notes`. What remains here is the human reference:
the design rationale and how to set up the *clients*. The Linux Mint mini is
handled separately and manually (see VNC-MINT.md).

## Architecture: VNC over SSH, no in-protocol TLS

The journey (full prose in VNC-MINT.md): in-protocol TLS works in
theory with VeNCrypt but interop with Screens 5 on macOS is broken
(Screens doesn't speak VeNCrypt Plain auth). TigerVNC on macOS works
but is unpleasant; RealVNC won't negotiate with non-RealVNC servers.

The working answer is VNC bound to localhost + Screens via SSH tunnel.
sshd is the auth boundary; VNC has no auth of its own because nothing
can reach the port except SSH-authenticated processes. No PAM, no
TLS certs, no second credential.

## Client setup (Screens 5 on macOS)

Same two-tab dance as the Mint mini. The non-obvious bit: the
Connection tab address is `localhost`, NOT the hostname. The hostname
goes in the Security tab as the SSH target.

### Connection tab

- **Operating System**: Linux
- **Protocol**: VNC
- **Address**: `localhost`
- **Port**: 5900
- **Authentication Type**: None

### Security tab

- **Use Secure Connections**: ON
- **Enable for Local Connections**: ON
- **Address**: `<hostname>.local` or `<hostname>.<tailnet>.ts.net`
- **Port**: 22
- **Username**: `schmonz`
- **Password / key**: as appropriate

## Connect

After starting a Sway session on the target host, Screens connects
via the saved config. SSH key auth, host fingerprint trust on first
connection, then straight into the running Sway session — no VNC
auth prompt, no cert dialog.

## Client setup (Remmina on Linux)

Remmina is the most pleasant free VNC client on Linux and has
first-class SSH-tunnel support — same conceptual model as Screens.
KRDC is a decent second choice if you're already in KDE-land; it
pulls in fewer dependencies on a KDE desktop than on Sway.

Install (gatherd already installs these on the EOS fleet; this is for
other machines):

```
sudo apt install remmina remmina-plugin-vnc     # Mint / Debian
sudo pacman -S remmina libvncserver              # EOS / Arch
```

(pkgsrc has remmina too if needed on NetBSD.)

### Connecting to a Sway/Mint box (VNC + SSH tunnel)

New connection → VNC protocol. Two tabs of relevance:

**Basic tab:**
- **Server**: `localhost:5900` (the target *inside* the SSH tunnel —
  same Screens gotcha applies here)
- **Username / Password**: blank (no VNC auth)
- **Color depth**: True color (32 bpp) or whatever feels good

**SSH Tunnel tab:**
- **Enable SSH tunnel**: ON
- **Custom**: `<hostname>:22` (or `<hostname>.<tailnet>.ts.net:22`)
- **Username**: `schmonz`
- **Authentication**: Public key (automatic) — Remmina uses
  `~/.ssh/id_*` and the agent

First connection prompts to trust the SSH host key; stored
thereafter. No VNC password ever requested.

### Connecting to a Mac with Screen Sharing + Remote Login

The Mac approach: Remote Login (SSH) is already on, so the SSH
tunnel works. Screen Sharing always wants *some* VNC-layer auth —
there's no "no auth" option in the Mac UI. But the credential it
wants is your macOS account password (via Apple Diffie-Hellman ARD
auth), not a separate VNC password.

Setup on the Mac: System Settings → General → Sharing → Screen
Sharing → enable, "Allow access for: Only these users" → your user
account. Crucially, do NOT set a "VNC viewers may control screen
with password" (the legacy VNC password option in Computer
Settings). That field, when set, exposes RFB 3.3 legacy auth on the
network and is a separate credential to manage.

In Remmina:

**Basic tab:**
- **Server**: `localhost:5900`
- **Username**: your macOS username
- **Password**: your macOS account password (Remmina stores it)
- **Color depth**: True color

**SSH Tunnel tab:**
- **Enable SSH tunnel**: ON
- **Custom**: `<mac-hostname>:22`
- **Username**: your macOS username
- **Authentication**: Public key (set up `~/.ssh/authorized_keys`
  on the Mac first)

Not quite as clean as the Linux "no VNC auth at all" pattern —
Screen Sharing always wants a credential at the VNC layer — but
at least it's your real macOS account password, not a separate
one to maintain. Remmina caches it after first entry.

### KRDC

If preferred: same idea, different UI. New connection → VNC → server
field as above → there's an "Use SSH tunnel" toggle in the connection
options that opens fields for SSH host, port, and username. Works
fine; Remmina just has a more polished saved-connections workflow.

## Tailscale ACL implication

VNC is bound to localhost — off the network entirely. Only sshd is
remotely reachable. Tailscale ACLs only need to scope SSH (port 22).

## Footnote: Wayland pre-login GUI access (state as of 2026)

Sway + greetd still has no clean way to share the greeter session over
VNC and seamlessly continue into the user session — fundamental to
Wayland's compositor-as-consent-boundary design. GNOME 46+ has this
working via GDM + GNOME Remote Desktop (RDP); KDE Plasma has it via
KRdp. Neither helps a Sway fleet.

If pre-login access ever becomes important: SSH in and fix it from the
terminal, or run an SDDM-with-sway-as-greeter setup with its own
wayvnc instance and accept the two-step handoff at login. Hasn't been
necessary so far.
