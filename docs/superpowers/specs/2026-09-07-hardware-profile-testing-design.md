# Testing hardware-gated code — design

## The problem, in the repo's own words

`CLAUDE.md`, on `tests/test`:

> **One hardware profile.** The VM has no backlight, no keyboard LED, no
> ThinkPad EC, no Apple SMC, no fingerprint reader, no IR receiver and no
> rotated panel, so every `when: has_*` task is dead code in the test. The
> `hardware` role is very nearly untested, and a change there is reviewed by
> reading and by the next repave — nothing else.

`tests/test`, on why the health-assertion section exists:

> That shipped and reached a real machine, because the first task to trip over
> it was gated on `has_screen_backlight` — and this VM has no backlight, so
> neither run touched it.

Two of the three bugs found in the September 2026 AUR-dependency work lived
behind `when:`. `gsl` broke the `has_screen_backlight` clight chain and cost a
repave. The AVX preflight guard, added in `8950c0b`, would have failed the whole
slow tier on a pre-AVX machine; nothing in the repo could have caught it, and a
directed adversarial review did.

26 `has_*` flags are declared in `roles/machine_facts/defaults/main.yml`. All but
three default false, and the VM sets none of them true.

## What this does not try to do

**It does not simulate hardware.** There is no way to give QEMU an Apple SMC or a
fingerprint reader, and pretending otherwise would produce a test that passes for
the wrong reason.

What it exercises is **convergence** of a gated path: packages resolve and build,
files get written, units get enabled, and run 2 is still clean. That is precisely
where both known bugs lived — build and install time, not hardware-interaction
time. A forced flag would have caught both.

Tasks that genuinely cannot converge without the device (starting a unit that
opens a device node, reading a `/sys` attribute that does not exist) are expected.
They get triaged per flag, and a flag that cannot be forced is recorded with the
reason rather than quietly skipped.

## Mechanism

Ansible extra-vars outrank `set_fact`. Measured on this machine:

```
$ ansible-playbook -i localhost, pv.yml          # set_fact sets it true
    "msg": "has_thing=True"
$ ansible-playbook -i localhost, -e has_thing=false pv.yml
    "msg": "has_thing=false"
$ ansible-playbook -i localhost, -e @prof.yml pv.yml
    "msg": "has_thing=False"
```

So `-e @<file>` overrides detection without touching `machine_facts`. The repo
already uses this shape: `tests/test` passes `-e sway_guard_override=true`.

A **profile** is a YAML file of `has_*` overrides naming a machine class. The VM
runs the same playbooks it always did, with one more `-e`.

Where real hardware is free, prefer it to a forced flag. `has_avx` is detected
from `/proc/cpuinfo`; `tests/test` invokes `qemu-system-x86_64` with no `-cpu`,
so the guest gets the default model and no AVX. This host has `avx avx2`, so
`-cpu host` makes `has_avx` true by detection — a real signal, not an assertion
about one.

## Why profiles rather than one all-flags-on run

Flags interact with the machine, not just with tasks: `has_grub` and
`has_extlinux` are mutually exclusive, and `has_luks_btrfs_root` describes a disk
layout the snapshot does not have. Grouping by machine class keeps each run
coherent and lets flags be adopted incrementally, one green profile at a time.

## Keeping it honest

The failure mode to design against is a new `has_*` flag being added and silently
never tested — the same shape as a gate with no test, which `tests/gates` now
refuses. So: every flag declared in `machine_facts/defaults/main.yml` must appear
either in a profile or in an exclusions file with a reason, and `tests/gates`
checks that. Adding a flag then forces a decision instead of allowing an
omission.

## Scope

Phase 1 is the mechanism, `-cpu host`, and three profiles covering the two AUR
chains that have already broken (backlight/clight, fingerprint/python-validity)
plus ThinkPad. Remaining flags land in the exclusions file with reasons, to be
converted to profiles as anyone touches them.
