# Targetability score — methodology

The single 0–100 number is what makes the after-action report demoable **and**
what a skeptical S2 will attack ("72 out of what?"). So it is defined here, in
prose, and in `canopy/scoring.py` in code, and echoed verbatim into every
report. If the score were a black box it would read as theatre.

> **What it is:** a *relative detectability ranking* of a friendly unit's
> emitters. **What it is not:** a probability of being killed. It ranks who the
> adversary's SIGINT would notice first, and why.

## Per-emitter score (0–100)

```
score = 100 × (0.35·persistence + 0.30·range + 0.35·phase)
```

| Term | Definition | Intuition |
| --- | --- | --- |
| **persistence** | `clamp(duty × (0.5 + 0.5·activity_fraction), 0, 1)` where `duty` is the mean transmit duty cycle and `activity_fraction` is the share of the exercise the emitter was ever up | a radio keyed constantly all exercise scores high; a disciplined burst-and-move emitter scores low |
| **range** | `clamp(log10(det_range / R_MIN) / log10(R_MAX / R_MIN), 0, 1)` where `det_range` is the adversary detection radius from the propagation model, `R_MIN=200 m`, `R_MAX=20 km` | a loud, far-detectable emitter is more targetable than a whisper |
| **phase** | fraction of the exercise's **critical windows** (e.g. the assault) during which the emitter was radiating | radiating *during the assault* is the cardinal sin |

Weights (`0.35 / 0.30 / 0.35`) sum to 1 so the score is a clean 0–100. They are
tunable per customer — a raid-focused unit may weight `phase` higher.

### Detection range (the `range` term)

`canopy/propagation.py` inverts a log-distance path-loss model:

```
received(d) = EIRP − FSPL(f, 1 m) − 10·n·log10(d)
det_range   = distance where received(d) == adversary_sensitivity
```

with `n` the path-loss exponent (2 = free space, ~3.1–4 = cluttered/vegetated)
and nominal per-type EIRP documented in `NOMINAL_EIRP_DBM`. **EIRP and adversary
sensitivity are documented assumptions, not measurements** — the report says so.

## Exercise score

```
overall = 0.5 × (worst emitter score) + 0.5 × (mean emitter score)
```

The `0.5·worst` term refuses to let one catastrophic emitter hide behind many
quiet ones; the `0.5·mean` term keeps a single loud outlier from pinning the
whole unit at 100. It is always reported next to the worst-offenders list, so
the number is never divorced from its drivers.

## Honesty rules

1. **Every fix carries its error ellipse.** The score's `range` term and the map
   both surface uncertainty; a fix is never a pinpoint.
2. **SAR is excluded from EMCON scoring.** `sar_disturbance` rows are pattern-of-
   life evidence, not active emissions, so they do not inflate a unit's score.
3. **Assumptions are printed in the report** (weights, range band, path-loss
   exponent, adversary sensitivity, per-type EIRP). Reproducible or it doesn't
   ship.
