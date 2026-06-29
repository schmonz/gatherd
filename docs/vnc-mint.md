# Remote GUI access via VNC — Linux Mint 22.3

For the Mac mini ("pet-power-plant") running Mint 22.3 / Cinnamon / Xorg.
Follow manually; the Sway fleet is handled separately via Ansible
(see VNC.md).

## Architecture: VNC over SSH, no in-protocol TLS

The journey: tried in-protocol TLS (VeNCrypt) with Unix-account auth
via `-unixpw`. Got it working with TigerVNC after fighting OpenSSL 3
anon-DH ciphers, but TigerVNC's macOS build is unpleasant. RealVNC
free refuses to negotiate with non-RealVNC servers. Screens 5 doesn't
speak the VeNCrypt Plain auth subtype.

The pragmatic answer for a Screens client is SSH-tunneled VNC. Per
the x11vnc man page:

> Note that use of -localhost with ssh(1) (and no -unixpw) is roughly
> the same as requiring a Unix user login (since a Unix password or
> the user's public key authentication is used by sshd on the machine
> where x11vnc runs and only local connections from that machine are
> accepted).

sshd is the auth boundary. The VNC server presents no auth of its own
because nothing can reach it except processes that already
authenticated to sshd. No second credential to manage, no custom
in-band login panel, no cert trust dance.

## Server setup

### Install

```
sudo apt install x11vnc
```

### Systemd unit

`/etc/systemd/system/x11vnc.service`:

```
[Unit]
Description=x11vnc attached to :0 on localhost only
After=display-manager.service
Requires=display-manager.service

[Service]
Type=simple
ExecStart=/usr/bin/x11vnc \
  -display :0 \
  -auth guess \
  -forever \
  -loop \
  -noxdamage \
  -repeat \
  -localhost \
  -nopw
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Flag notes:
- `-auth guess` finds the active `.Xauthority` (LightDM's before
  login, user's after). Needs root.
- `-localhost` binds to 127.0.0.1 only. Port is off the network.
- `-nopw` explicitly allows no-auth (otherwise x11vnc refuses to
  start without `-rfbauth` or `-unixpw`). Safe because SSH gates
  access to the port.

Enable:

```
sudo systemctl daemon-reload
sudo systemctl enable --now x11vnc
```

Verify:

```
ss -tlnp | grep 5900
# expect: 127.0.0.1:5900 and [::1]:5900
```

### sshd

Nothing special required. Standard sshd with key auth is fine.
TCP port forwarding must be allowed (`AllowTcpForwarding yes`,
which is the default). Verify:

```
sudo sshd -T | grep -i forward
# expect: allowtcpforwarding yes
```

## Client setup (Screens 5 on macOS)

Two tabs of the connection editor matter. Both must be set correctly
or it hangs at "Connecting...".

### Connection tab

- **Operating System**: Linux
- **Protocol**: VNC
- **Address**: `localhost` (NOT `pet-power-plant.local`)
- **Port**: 5900
- **Authentication Type**: None

This tab tells Screens where to make the VNC connection *from inside
the SSH session*. Since x11vnc is on loopback there, the address is
`localhost`. Putting the actual hostname here is the obvious wrong
thing that hangs forever.

### Security tab

- **Use Secure Connections**: ON
- **Enable for Local Connections**: ON
- **Address**: `pet-power-plant.local` (the SSH host)
- **Port**: 22
- **Username**: `schmonz`
- **Password**: leave as "Ask if required", or store, or use SSH key

This tab is where the SSH connection actually goes. The address here
is the real machine; the address on the Connection tab is the
remote-side target after the SSH tunnel is up.

## Cert / fingerprint trust

No TLS cert involved. Standard SSH known-hosts on first connection —
Screens prompts to accept the host fingerprint once, stores it,
silent thereafter.

## Tailscale ACL implication

VNC is bound to localhost — completely off the network. The only
remotely-reachable port is sshd (22). ACL scope is just SSH.

