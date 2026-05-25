# Remote GUI access via VNC

Goal: connect to the same user session I'd see at the console, with
discovery via mDNS so hosts appear in Finder's Network tab, and
in-protocol TLS doing the encryption. Authentication against Unix
accounts.

## Architecture decision: in-protocol TLS, not SSH tunneling

Initial plan was VNC-bound-to-localhost + SSH tunneling (the macOS
Screens "Secure Connection" model as I understood it). Turned out
Screens' Secure Connection is usually negotiating **VNC's own TLS
extension** (VeNCrypt-style), not opening an SSH tunnel — same as
Apple's built-in Screen Sharing does when connecting Mac-to-Mac.

Implications:
- Finder's "Share Screen" button doesn't know how to SSH-tunnel.
  If I want Finder discovery to actually connect, the VNC service has
  to be reachable on the network with in-protocol encryption.
- SSH tunneling still works fine and is arguably more paranoid (SSH
  crypto is more battle-tested than VNC server TLS implementations),
  but it forecloses Finder discovery and forces Screens-only.

Chose Finder convenience + in-protocol TLS. Tradeoff accepted: VNC port
is on the network (Tailscale or LAN), but TLS-wrapped and authenticated
against the Unix account database.

## EndeavourOS / Sway / Wayland (fleet)

wayvnc **does** support PAM authentication (against Unix accounts),
contrary to my earlier impression. It's a build-time option
(`enable_pam` in meson, auto-enabled when libpam is present) and a
runtime config option (`enable_pam=true`).

The Arch `wayvnc` package installs `/etc/pam.d/wayvnc` (using
`pam_unix.so`) starting in pkgrel 0.8.0-2 (Aug 2024). Current EOS
should have it. Verify before relying on it:

```
pacman -Ql wayvnc | grep pam
# expect: /etc/pam.d/wayvnc
```

If missing, copy the upstream config:

```
sudo tee /etc/pam.d/wayvnc <<'PAM'
auth required pam_unix.so nodelay deny=3 unlock_time=600
account required pam_unix.so nodelay deny=3 unlock_time=600
PAM
```

`~/.config/sway/config.d/autostart_applications`, after existing exec lines:

```
exec wayvnc 0.0.0.0 5900
```

### Install / mDNS

```
sudo pacman -S wayvnc avahi nss-mdns
sudo systemctl enable --now avahi-daemon
```

Add `mdns_minimal` to `/etc/nsswitch.conf` hosts line for `.local`
resolution from the box itself.

### TLS + PAM config

Generate a cert (per upstream README — uses ECDSA, more modern than
the old RSA recipe):

```
mkdir -p ~/.config/wayvnc
cd ~/.config/wayvnc
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:secp384r1 \
  -sha384 -days 3650 -nodes \
  -keyout tls_key.pem -out tls_cert.pem \
  -subj "/CN=$(hostname)" \
  -addext "subjectAltName=DNS:$(hostname),DNS:$(hostname).local"
chmod 600 tls_key.pem
```

`~/.config/wayvnc/config`:

```
address=0.0.0.0
enable_auth=true
enable_pam=true
private_key_file=/home/schmonz/.config/wayvnc/tls_key.pem
certificate_file=/home/schmonz/.config/wayvnc/tls_cert.pem
```

With `enable_pam=true`, the `username` and `password` config options
are ignored — auth goes through `/etc/pam.d/wayvnc`, which means real
Unix credentials.

### Avahi announcements

`/etc/avahi/services/rfb.service`:

```xml
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi.dtd">
<service-group>
  <name replace-wildcards="yes">%h</name>
  <service>
    <type>_rfb._tcp</type>
    <port>5900</port>
  </service>
</service-group>
```

Also worth adding SSH for Screens-sidebar discovery and as a fallback
if VNC-over-TLS hits a client-compatibility snag:

`/etc/avahi/services/ssh.service`:

```xml
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi.dtd">
<service-group>
  <name replace-wildcards="yes">%h</name>
  <service>
    <type>_ssh._tcp</type>
    <port>22</port>
  </service>
</service-group>
```

Avahi picks these up without restart. Verify from the Mac:

```
dns-sd -B _rfb._tcp local.
```

### macOS Screen Sharing compatibility gotcha

The wayvnc README notes that macOS Screen Sharing historically requires
DES-based VNC auth, which is **incompatible with PAM** (per the
wayvnc(1) man page: "DES authentication does not work when enable_pam
is enabled, as PAM overrides password-based authentication").

In practice, modern macOS Screen Sharing negotiates more capable
security types (VeNCrypt/TLS + Apple Diffie-Hellman, or RSA-AES) before
falling back to DES. Whether `enable_pam=true` + TLS works seamlessly
from Finder needs to be tested on the actual macOS version in use.

Fallback options if Finder won't connect to wayvnc with PAM:
1. Use Screens instead of Finder — its security-type negotiation is
   more flexible.
2. Disable PAM, set `username`/`password` in config, accept the
   "separate credential" tradeoff. Keep TLS.
3. SSH tunnel + VNC client from the Mac — bypasses all the
   security-type negotiation issues.

### Connect

Finder → Network → host → Share Screen. TLS cert prompt on first
connection, then Unix username/password (handled by PAM), then in.

## Client setup

### Screens / Finder (macOS, iOS)

- Hosts auto-appear via mDNS once `_rfb._tcp` is announced.
- First connection: trust the self-signed cert.
- Then: Unix username/password on both Mint and Sway machines.

### Linux client

Same model — point a VNC client that supports VeNCrypt/TLS at the
host:port. `remmina` works; TigerVNC's `vncviewer` does too.

## Tailscale ACL implication

VNC is now on the network (not localhost-only), but bound to TLS +
Unix auth. ACLs can still scope which devices can reach port 5900 —
useful to restrict to my own devices on the tailnet.

