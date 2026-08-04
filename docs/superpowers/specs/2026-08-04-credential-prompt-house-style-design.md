# Credential prompt house style (crimson)

## Problem

Every elevated-credential prompt in the session — `sudo -A`, ssh passphrases,
polkit, and the vault password — is drawn by `gatherd-askpass` calling
`fuzzel --dmenu --password --prompt-only`. With no per-invocation styling, that
box inherits `~/.config/fuzzel/fuzzel.ini` wholesale: the same indigo palette,
the same geometry, the same font as picking an application from the launcher.

Typing a root password into a window that is visually indistinguishable from the
app launcher is the problem. We want the credential box to be unmistakably its
own thing at a glance, while still reading as part of the gatherd family.

## Goal and non-goal

**Goal:** a memorable house style. A fixed, striking look that separates "gatherd
is asking me for a credential" from every other window in the session.

**Explicit non-goal:** a *verifiable* identity. We are not defending against a
hostile process in the session drawing a convincing copy — any layer-shell client
could reproduce a look that is described in a public repo. A per-machine secret
token in the prompt was considered and rejected as more machinery than the threat
warrants for a single-user desktop.

## Approach

Red-shift the existing palette. The launcher's background `08052b` becomes
`2b0508` — the same colors, channel-swapped — so the credential box reads as kin
to the launcher while being impossible to confuse with it. A heavy opaque salmon
border and a tighter box do the rest.

Two members of the family, both drawn by `gatherd-askpass`:

- the **fuzzel box**, for every password and passphrase
- the **foot window**, for the SSH host-key (TOFU) prompt, which is a multi-line
  security decision rather than a password and so needs a real terminal

### What carries the identity

Color and border only. No header line, no added glyph beyond the `❯` prompt.

An informational header (`--mesg 'gatherd — authentication required'`) was
prototyped and rejected: on screen it was verbose, and the source tag already in
the prompt (`[sudo]`, `[polkit]`, `[vault]`) says everything the header would.

### Sizing: inherit, do not interpolate

The box uses the **same font and padding as the launcher** — `--font` and the
padding flags are simply omitted, so `fuzzel.ini` supplies them.

This was arrived at the long way and the reasoning matters, because the obvious
alternative is wrong:

Scaling the credential box up (1.2x–2x the launcher font) was prototyped on
screen. 2x was much too big; 1.0x was chosen. Since `fuzzel.ini`'s font size is
itself templated from the per-machine `foot_font_size` fact, *inheriting* it is
automatically correct on every panel and can never drift from the launcher,
whereas interpolating `foot_font_size` into the script would duplicate a value
that already exists one file away.

Consequently `scripts/gatherd-askpass` stays a **plain script installed by
`copy`**. An earlier decision to convert it to a `.j2` template existed only to
carry a doubled font size; when the multiplier became 1.0x, the reason for
templating evaporated.

### Latent bug fixed by the same reasoning

The foot window currently pins `--override 'main.font=JetBrains Mono:size=10'`.
That hardcoded `10` ignores `foot_font_size` entirely, so on any panel where the
computed size is not 10 the host-key window renders too small — precisely the
window whose whole purpose is making a ~90-character fingerprint legible.

Deleting the override fixes it: the window then inherits the user's `foot.ini`,
which is `JetBrainsMono-Regular` at the correct per-machine size. Same font
family as before, right size everywhere, one fewer thing to keep in sync.

## Palette

| Role | Value | Note |
|---|---|---|
| background | `2b0508dd` | `08052b` red-shifted; alpha unchanged |
| text | `e3e3eaff` | unchanged |
| prompt | `ff7f7fff` | unchanged salmon |
| input | `ff7f7fff` | unchanged salmon |
| border | `ff7f7fff` | opaque, 4px, radius 10 |

Values live inline in `scripts/gatherd-askpass`, as the foot branch's colors
already do. Nothing else consumes them, so `group_vars` would be indirection
without a second reader.

## Changes

### `scripts/gatherd-askpass` — fuzzel box

Flags added to the existing invocation:

```
--prompt-only "❯  $prompt "
--width=24
--background-color=2b0508dd
--text-color=e3e3eaff
--prompt-color=ff7f7fff
--input-color=ff7f7fff
--border-width=4
--border-color=ff7f7fff
--border-radius=10
```

- `--prompt-only "❯  $prompt "` restores the `❯` glyph. `--prompt-only` *replaces*
  `fuzzel.ini`'s `prompt="❯  "` rather than prefixing it, so today's box shows a
  bare `[sudo] `. Restoring it matches the foot window's prompt line.
- `--width=24` (characters, so font-independent) against the launcher's 50. The
  credential box holds a short tag and a masked string; a narrower box reads as a
  dialog rather than a picker.
- `text`, `prompt`, and `input` colors are set explicitly even though they match
  `fuzzel.ini` today. They are identity-critical, and a security-relevant prompt
  should not depend on the launcher's config to be legible. Font and padding,
  which are *not* identity-critical, are left to inherit.

Everything else about the call is unchanged: `</dev/null` stdin, the fd-3
password passthrough, and the failure logging all stay exactly as they are.

### `scripts/gatherd-askpass` — foot window

- `colors-dark.background` and `colors-light.background`: `08052b` → `2b0508`
- delete the `--override 'main.font=JetBrains Mono:size=10'` line
- heading text unchanged (`SSH host key verification`)
- update the "same askpass family" comment: the family is crimson now, and this
  member inherits its font rather than pinning it (with the reason — the
  fingerprint needs the room).

Recoloring alone was tried first and was not enough: on screen the window was
crimson but still read as a completely different thing, because the family's
identity is as much its *shape* as its palette. A default foot window is 700x500
of mostly-empty background with no border at all, next to a compact bordered
dialog. Two more overrides close the gap:

```
--override main.initial-window-size-chars=84x11
--override csd.preferred=client
--override csd.size=0
--override csd.border-width=4
--override csd.border-color=ffff7f7f
```

- `initial-window-size-chars=84x11` sizes the window to its contents. 84 columns
  keeps the longest fingerprint line unwrapped; 11 rows fits heading, prompt, and
  input with slack.
- foot has no window-border option, but its CSDs do. `csd.preferred=client` is
  required because sway would otherwise server-side-decorate the window and no
  CSD border would be drawn at all — the option is documented as only a *hint* to
  the compositor, and sway honors it. `csd.size=0` drops the titlebar so the
  border is all that remains.
- CSD colors are `AARRGGBB`, unlike the `RRGGBB` used in the colors sections, so
  the salmon border is `ffff7f7f` rather than `ff7f7f`.

**Known and accepted difference:** the fuzzel box has `--border-radius=10`; foot's
CSD border is square and foot offers no corner rounding. The two members match in
color, border weight, and proportion but not in corner shape.

### `scripts/gatherd-post-setup-notes`

One new `section_verify` item, bringing the count to 7 (under the 10-item repave
threshold). Both family members are directly invokable on a converged machine, so
the step is a pasteable command sequence rather than prose:

```
/usr/local/bin/gatherd-askpass '[sudo]'
    → crimson box, salmon border, "❯  [sudo]" prompt, same font as the launcher.
      Typing echoes to stdout; Escape exits non-zero.
/usr/local/bin/gatherd-askpass 'Are you sure you want to continue connecting (yes/no/[fingerprint])?'
    → crimson foot window, heading "SSH host key verification"
```

### Not changed

- `~/.config/fuzzel/fuzzel.ini` — the launcher keeps its look entirely
- `roles/system/tasks/sudo.yml` — still `copy`, not `template`
- `gatherd-polkit-agent`, `gatherd-prompt-vault` — they shell out to
  `gatherd-askpass` and inherit the new look for free
- gtklock (the lock screen) — a different act (proving identity to resume a
  session, not elevating within one), drawn over the wallpaper with a clock, and
  in no danger of being confused with the launcher

## Verification

Both changes are visual, and both are reproducible on demand rather than only
observable during a fresh pave — `gatherd-askpass` can be invoked directly with
either kind of prompt. The design was prototyped by running the real `fuzzel` and
`foot` invocations on a live session before being written down.

`ansible-lint` before committing, per the repo rule, though no task logic changes.

## Follow-ups noted, deliberately out of scope

- **Escape exits 2, not 1.** The instrumentation added at `gatherd-askpass:98`
  logs *every* non-zero exit to `askpass.log`, so every ordinary user cancel is
  recorded next to the "no box drew" failures the log exists to catch. Filtering
  the cancel case would make that log useful again. Pre-existing behavior,
  unrelated to styling.
- **`gatherd-font-size` returns the 1920 fallback on the MiniBook X**, whose DSI
  panel exposes no EDID; only the Ansible-side override in
  `roles/machine_facts/tasks/main.yml` corrects it to 10. Any future script that
  shells out to `gatherd-font-size` directly will be wrong on that machine.
