# Architecture

```
  Commodity sensors (swappable)        The platform (the company)          Delivery (commodity)
  ┌───────────────────────────┐        ┌──────────────────────────┐        ┌────────────────────┐
  │ RF nodes (KrakenSDR+Pi)   │──┐     │  Fusion engine           │    ┌──▶ │ ATAK feed (CoT)    │
  │ NISAR slice (L-band SAR)  │──┼───▶ │  associate + geolocate   │────┤    └────────────────────┘
  │ Future INTs (dashed)      │──┘     │  ┌────────────────────┐  │    │    ┌────────────────────┐
  └───────────────────────────┘        │  │ SIGNATURE LIBRARY  │  │    └──▶ │ After-action report│
                                       │  │ the moat, compounds │  │         └────────────────────┘
                                       │  └────────────────────┘  │
                                       └──────────────────────────┘
```

## Layer responsibilities

| Layer | Package | Responsibility |
| --- | --- | --- |
| **Edge** (per node) | `edge/` | capture IQ → detect (CFAR) → features → classify (rules) → bearing (MUSIC) → POST a detection. Stateless; all state lives in the library. |
| **Backend / fusion** | `canopy/` | ingest detections, associate across nodes/time, intersect bearings into fixes with error ellipses, persist to the library, score targetability, export CoT, push live over SSE. |
| **Frontend** | `frontend/` | live overlay (DF web, fixes with visible error ellipses, SAR patches) + after-action report with the targetability score. |
| **NISAR worker** | `nisar/` | batch job computes L-band coherence change and writes `detections` rows with `source_int='sar'` — same table, same downstream. |

## Data flow

```
edge.run.process_block ─┐
                        ├─▶ pipeline.ingest ─▶ store.detections ─▶ pipeline.fuse ─▶ store.fixes
nisar.worker.run ───────┘         │                                    │
(source_int='sar')                └─▶ store.signatures (the moat)       ├─▶ pipeline.report ─▶ frontend
                                                                        └─▶ pipeline.cot_events ─▶ TAK
```

## The load-bearing invariant

`store.detections` is **one collection for every modality**. RF bearings and SAR
coherence patches are the same `Detection` dataclass (`canopy/models.py`),
distinguished only by `source_int` and the contents of `features`. The
executable guard is `tests/test_schema_parity.py` — it fails the day someone
adds a SAR-only code path. That single invariant is the difference between "a
platform" and "an RF tool."

## Module map

```
canopy/
  models.py       schema-shaped dataclasses (mirror db/schema.sql)
  store.py        in-memory signature library (swap for a psycopg repo in prod)
  dsp.py          radix-2 FFT + Welch PSD (stdlib)
  detect.py       CA-CFAR energy detection
  features.py     center/bw/burst/duty extraction
  classify.py     rule-based emitter classifier (the closed asset)
  geo.py          tangent plane + weighted-LS bearing intersection + error ellipse
  fusion.py       association across nodes/time + geolocation
  propagation.py  path-loss / detection-range model
  scoring.py      targetability score (documented formula)
  cot.py          Cursor-on-Target export
  pipeline.py     ingest → fuse → report orchestration
  server.py       stdlib HTTP + SSE backend serving the live UI
edge/             simulator + real capture→detect→classify→report loop
nisar/            multi-INT proof: SAR coherence patches into the same library
```

## MVP vs. production

| Concern | MVP (this repo) | Production |
| --- | --- | --- |
| Sensors | `edge/simulate.py` synthetic world | KrakenSDR + Heimdall DAQ nodes |
| Library | `canopy/store.py` in-memory | Postgres + PostGIS + TimescaleDB (`db/schema.sql`, `docker-compose.yml`) |
| API | stdlib `http.server` + SSE | FastAPI + WebSocket |
| CoT | stdlib XML | `pytak` → TAK Server |
| Map | offline canvas SIGINT plot | MapLibre GL + deck.gl |
| SAR | synthetic coherence field | Earthdata/ASF NISAR L-band via ISCE2/MintPy |

Everything in the MVP column runs on the **Python 3.9+ standard library with no
installs**, so the fusion math — the part the whole thesis rests on — is
independently verifiable.
