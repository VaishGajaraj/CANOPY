# KC-1 — DF fix accuracy test plan (the primary kill criterion)

> The dashboard is worthless if the physics underneath doesn't hold. KC-1 is
> upstream of every pixel and it is the cheapest experiment that can end the
> concept. Run it first. Budget: ~$300 and an afternoon.

## Hypothesis

Multi-node bearing intersection produces a fused fix whose **median error is
< 150 m** (≈ the footprint of a CP or unit element) across representative
training-area geometry. If not, the detectability heatmap is not meaningful and
the product dies *in that form* — or is re-scoped to zonal "detectable /
not-detectable" without a point fix.

## Materials

- 3–4 KrakenSDR + Raspberry Pi 5 nodes (or the MVP simulator for a dry run).
- 1 known handheld radio (VHF or UHF), keyed on a known frequency.
- A survey-grade GPS (or RTK) to fix node emplacements **and** the emitter truth
  point to ≤ few metres.

## Procedure

1. Survey and record each node position and the emitter truth position.
2. Emplace nodes in representative geometry around the emitter (~1–2 km, with
   wide angular spread — avoid collinear layouts; see GDOP note).
3. Key the emitter in realistic bursts. Log each node's MUSIC azimuth + SNR.
4. POST detections to the backend; let the fusion engine compute the fix and the
   error ellipse.
5. Repeat across ≥3 geometries (tight ring, wide ring, degraded/collinear) and
   ≥2 sites (open, vegetated).

## Metrics

- **Median fix error** and **CEP** vs. truth (the kill metric).
- **P90 error** and **error-ellipse size**.
- **Ellipse honesty / coverage**: fraction of fixes whose truth falls inside the
  reported 95% ellipse (should be ≈ 0.95 — an overconfident ellipse is a
  liability even if the point error is small).

## Pass / fail

| Result | Decision |
| --- | --- |
| median < 150 m, coverage ≈ 0.9+ | **PASS** — the heatmap is meaningful; proceed |
| median ≥ 150 m but zonal separation holds | **RE-SCOPE** to "detectable in this zone", no point fix |
| median ≫ 150 m and zones overlap | **KILL** the point-fix product form |

## Reproduce the simulated dry run

The MVP models this experiment exactly (real geometry, real angular noise, the
same fusion math). It is wired as a test:

```
make test            # runs tests/test_kc1_geolocation.py among others
```

Representative simulated output (4 nodes, ~1.2–1.5 km ring, σ_az = 4°, n = 400
trials):

```
[KC-1 good geometry]  median = 85.9 m   p90 = 163.1 m   ellipse95 coverage = 0.93
[KC-1 three nodes]    median = 91.6 m   coverage = 0.97
[KC-1 bad geometry]   median = 70.1 m   (documents the GDOP failure mode)
```

The simulator passes KC-1 for good geometry. Real captures are the true test —
this is the protocol to run in the woods, and the field data it produces is
exactly the Phase I feasibility evidence most competitors will not have.

### GDOP note

Fix accuracy is dominated by **geometry**, not just bearing accuracy. Nodes
clustered on one side, or nearly collinear with the target, give a long thin
error ellipse regardless of how good each bearing is. Always report GDOP
(`fix.gdop`) and reject/annotate fixes taken under poor geometry.
