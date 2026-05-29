# clight: enable and verify

clight is currently **installed but intentionally disabled** —
`roles/hardware/tasks/ambient_light.yml` installs `iio-sensor-proxy` + `clight`,
stops/disables `clightd`, and removes `exec clight` from sway autostart. This
plan is what to do when re-enabling it, plus the verification checklist below.

## Enabling

Reverse the three disabling steps in `ambient_light.yml` (enable `clightd`,
restore the `exec clight` autostart line) once the config below behaves. When it
works, these checks become the `section_verify` entry for clight.

## Post-reboot checklist

1. **Dark room floor** — backlight stays at ≥10% instead of going to 0
2. **DPMS recovery** — if the display does go off after 10 min idle, mouse/keypress
   should wake it normally (no `swaymsg` incantation needed, since this time clight
   will have started cleanly)
3. **Dimmer** — 60s on battery before it dims, and dims to 40% rather than invisibly low

## Tuning

If the dark-room floor still feels too low, raise the first value in `ac_regression_points`:

```
/etc/clight/modules.conf.d/sensor.conf
```

Bump `0.10` toward `0.15` or `0.20` as needed, then `etckeeper commit`.
