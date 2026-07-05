# CANOPY

**A sensor-agnostic multi-INT signature platform — demonstrated on an RF
friendly-force emissions-detectability auditor.**

> During a training exercise, CANOPY passively records what a friendly unit
> radiates, classifies each emitter, coarsely geolocates it via multi-node
> direction-finding, and produces (a) a live overlay showing the unit **"as the
> adversary's SIGINT would see it"** and (b) an after-action report scoring how
> detectable each element was, and when.

The product's one defensible asset is the **signature library**: a detection is
`{when, where, feature_vector, confidence, source_int}` *regardless of modality*.
RF bearings and SAR coherence-loss patches are the same row shape, so a second
INT drops into the same library without a schema change. This MVP proves that
claim by writing a NISAR L-band SAR patch into the **same** `detections` table
as the RF nodes — through the same door, with no new columns.

The whole core runs on the **Python 3.9+ standard library, no installs** — so
the fusion math the thesis rests on is independently verifiable.

---

## Quick start

```bash
make demo      # end-to-end run → prints the after-action report + a CoT event
make serve     # same, then serves the live UI at http://127.0.0.1:8787
make test      # the kill-criteria (KC-1 / KC-2) + schema-parity test suite
```

No `pip install`. No hardware. No database. (`requirements.txt` lists the
optional deps for the production paths the MVP stubs.)

## What the demo does

`scripts/demo.py` simulates 4 passive nodes auditing a rifle company (a chatty
CP VHF net, a disciplined platoon UHF, a soldier's personal phone left on, and a
GPS-jamming event during the assault), then runs the real platform:

```
simulate nodes → ingest detections → associate + geolocate (honest error
ellipses) → upsert the signature library → add a NISAR SAR patch through the
SAME door → after-action report with the targetability score → emit CoT
```

Representative output:

```
TARGETABILITY SCORE:  75.7 / 100
Worst offender:       GPS L1 anomaly (jamming), active during the assault

emitter                  score  pers  range  phase     fix ellipse
gps_anomaly@1575 MHz      80.7  0.56   0.88   1.00     65×35 m  CEP 59
tac_vhf@51.5 MHz          79.5  0.41   1.00   1.00     35×33 m  CEP 40
tac_uhf@385 MHz           65.5  0.09   0.91   1.00     57×33 m  CEP 53
cellular@1745 MHz         57.1  0.27   0.43   1.00     76×71 m  CEP 86

Multi-INT source_ints in library: ['rf', 'sar']
```

## Verified kill criteria

The kill-criterion experiments (spec §9) **are** the first build increments, and
they run as tests:

| Test | Result | Threshold |
| --- | --- | --- |
| **KC-1** DF fix accuracy (good geometry, 400 trials) | median **85.9 m**, p90 163 m, 95%-ellipse coverage **0.93** | median < 150 m |
| **KC-2** classifier separability (native RTL-SDR types) | passes ≥ 80% on field-like feature vectors | ≥ ~80% |
| **DSP** chain recovers a planted signal from real IQ | center error **~1 kHz** | < 60 kHz |
| **Schema parity** RF + SAR share one table | enforced | invariant |

The error ellipse being *honest* (truth inside the 95% ellipse ~93% of the time)
matters as much as the point error — an overconfident ellipse is a liability.

## Layout

```
canopy/     the platform: models, store, DSP, detect, classify, geo/fusion,
            propagation, scoring, CoT, pipeline, stdlib server (THE MOAT)
edge/       synthetic-emitter simulator + the real capture→classify→report loop
nisar/      multi-INT proof: SAR coherence patches into the same library
frontend/   offline canvas SIGINT plot + after-action report (no build step)
db/         schema-first PostGIS + TimescaleDB DDL (the production library)
tests/      KC-1, KC-2, DSP, and schema-parity — the claims, executable
docs/       targetability-score methodology · KC-1 field protocol ·
            architecture · dual-use governance
```

Read the docs in this order: [`docs/architecture.md`](docs/architecture.md) →
[`docs/targetability-score.md`](docs/targetability-score.md) →
[`docs/kc1-test-plan.md`](docs/kc1-test-plan.md) →
[`docs/governance.md`](docs/governance.md).

## MVP scope (and deliberate cuts)

**In:** 4 passive RF nodes → detection + rule classification → multi-node bearing
fusion → signature library → live CoT overlay → after-action report with a
targetability score, plus one NISAR coherence screen into the same library.

**Cut on purpose** (each is a real temptation): mesh networking, learned
classifiers, 2.4/5.8 GHz bands, precision geolocation, and NISAR-as-a-product.
See the spec's cut table for why and when each returns.

## Honest limitations

- This is a **locator**; the friendly-audit framing is the benign face of a
  find-emitters capability. Governance is part of the build — see
  [`docs/governance.md`](docs/governance.md).
- The targetability score is a **relative detectability ranking**, not a
  probability of being killed. Its assumptions are printed in every report.
- The SAR slice is a **proof screen**, not a SAR product. NISAR products are
  provisional through much of 2026 and carry ~36–72 h latency — pattern-of-life,
  not tactical alerting.
- Everything here is a **simulated feasibility demonstrator**: no tuned
  classifier weights, no real signature library, no capability claims beyond the
  documented numbers.

---

*Working name. RF is the wedge; the platform is the company.*
