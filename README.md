# gatherd

## Why?

I want to be able to USB-boot a random old laptop, install an OS configured to perform reasonably well, keep pace with future adjustments, and not have to click or remember much to accomplish this.

A corollary goal: nothing on a machine should be precious. Because a full working environment is only ever a fresh install and a `git pull` away, I can travel with a wiped or freshly-paved laptop and reconstitute everything once I've arrived — rebuilding a machine from the repo (and one memorized credential) is cheap and routine, so carrying my data along for the ride is optional.

That puts a premium on a repave that survives a hostile or absent network: bootstrapping needs to cope with captive portals, slow links, and the long tail of package downloads, ideally finishing unattended.

## How

1. Boot the EndeavourOS live install environment
2. From the Welcome app, choose "Fetch your install customization file"
3. Enter this URL, then click OK:
```
https://raw.githubusercontent.com/schmonz/gatherd/main/postinstall
```
4. Start the installer, choosing online installation and no desktop
   - Whole disk, encrypted, one big btrfs, swap with hibernate
5. On reboot, once the setup job completes, what you get is primarily [EOS Sway Community Edition](https://github.com/EndeavourOS-Community-Editions/sway)
   -- plus customizations to suit my hardware and personal taste.

The Calamares `postinstall` hook installs Ansible, clones this repo, sorts mirrors by speed (`rate-mirrors`, x86 and ARM), and registers a first-boot systemd service. On first boot, `gatherd.service` runs the playbook before login; a second service installs the slow packages in the background after you're logged in. A pushed change reconverges every machine on its next reboot, so machines keep pace without hand-holding.

## Which hardware?

Tested on:

- Apple MacBook Air 7,1 (11", 2015)
- Apple MacBook Pro 5,2 (17", 2009)
- IBM ThinkPad T60
- Lenovo Chromebook 100e
- Lenovo ThinkPad X270
- Lenovo ThinkPad T470

Everything hardware-specific is autodetected per machine (see below), so an untested laptop should still come up with the common configuration.

## Which customizations?

- **Apps**: 1Password, Helium browser (default), Tailscale, Private Internet Access VPN, LocalSend, Vesktop (Discord), Signal, Slack, Zoom, Teams, LibreOffice/AbiWord, Apostrophe + Dawn (writing), rclone, JetBrains Toolbox, Claude Code + Desktop + Cowork, btop, tmux, tig, etckeeper, fastfetch, glow, the_silver_searcher, github-cli, qemu, and more
- **Web apps**: a shelf of LLM chats installed as standalone Helium web apps (ChatGPT, Gemini, Grok, Perplexity, DeepSeek, Copilot, Le Chat, Meta AI, HuggingChat, Poe, Lumo)
- **System**: Tailscale with DNS push and firewall; PIA VPN; CUPS printing; etckeeper for `/etc`; fastest-mirror sorting; Sway autologin via greetd; Timeshift BTRFS snapshots (hourly + pre-upgrade autosnap); TLP power management; fingerprint auth for `sudo`; `arch-update`; NFS client (autofs over Tailscale); firmware updates via fwupd
- **Desktop**: macOS-style keyboard layout; Helium replaces Firefox as default browser; gtklock screen locker; custom swayidle; waybar shows btop CPU/mem and an mpris media widget; 1Password, Tailscale, and LocalSend autostarted by a session-lifetime supervisor that reaps the whole helper cohort cleanly on logout; gnome-keyring unlocked at login; git/ssh wired to the 1Password SSH agent; `pbcopy`/`pbpaste` wrappers via `wl-copy`/`wl-paste`; wallpaper, lock screen, and GRUB menu share one managed background
- **Captive portals**: at a portal network the captive-browser window pops on its own within a few seconds, already on the portal page, and closes itself once connectivity returns
- **Hardware** (autodetected per machine): Apple fan control and FaceTime HD camera driver; Chromebook function keys, AVS audio, lid-event poller, and OEM marketing-name label; phantom second display fix; software GL for old ATI GPUs; zswap for low-RAM machines; ambient light sensor; keyboard backlight; IR receiver tools; ThinkPad fan control, TrackPoint, ThinkVantage button, and battery charge thresholds; lid and power-button handling
- **Dotfiles**: `gitconfig` and `tmux.conf` symlinked from [schmonz/dotfiles](https://github.com/schmonz/dotfiles)

## After install

A handful of apps still need a one-time interactive sign-in (1Password, Tailscale, Claude, JetBrains, Zoom, iCloud via rclone). On each login gatherd regenerates a personalized post-setup notes file listing exactly which of those steps are still outstanding on this machine, plus a verification checklist — it doubles as the playbook's living test suite for a fresh repave.
