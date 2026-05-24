# Remote GUI access via VNC-over-SSH

Goal: connect to the same user session I'd see at the console, with VNC
bound to localhost only and SSH (over Tailscale) doing transport and auth.
Mirrors the macOS Screens "Secure Connection" model.

## EndeavourOS / Sway / Wayland (fleet)

wayvnc attaches to the running Sway session. Wayland doesn't have an
equivalent of "share `:0` from before login."

### Install

```
sudo pacman -S wayvnc
```

In `~/.config/sway/config.d/autostart_applications`, after the existing `exec` lines:

```
exec wayvnc 127.0.0.1 5900
```

`wayvnc 127.0.0.1 5900` binds to localhost.
(127.0.0.1 is wayvnc's default address, but being explicit doesn't hurt.)

### Verify localhost-only

```
ss -tlnp | grep 5900
```

`127.0.0.1:5900` only.

## Client setup

### Screens (macOS / iOS)

- Add host with Tailscale hostname (e.g. `squirrel-zapper`)
- Check **Secure Connection** (SSH tunnel)
- SSH user: `schmonz`, key from agent or path to private key
- VNC port: 5900
- Save SSH passphrase to Keychain — one-click after that
- Screens Connect not needed; Tailscale provides discovery

### Linux client

```
ssh -fNL 5900:localhost:5900 <host>
gvncviewer localhost
# or: remmina, vinagre, etc.
```

`-fN` backgrounds the tunnel without running a remote command. Kill
with `pkill -f 'ssh -fNL 5900'` or by PID when done.

## Tailscale ACL implication

VNC is now genuinely off the network. ACLs can restrict these hosts to
port 22 only and remote GUI still works.
