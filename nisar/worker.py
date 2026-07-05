"""NISAR L-band coherence-change worker (built last, deliberately minimal).

Production: pull free NISAR L-band SLC pairs from Earthdata (ASF DAAC), compute
interferometric coherence over one AOI with ISCE2/MintPy or SNAP, threshold the
coherence drop, and write patches as detections. This MVP substitutes a
synthetic coherence field (no Earthdata credentials required) but keeps the
exact output contract: a coherence-loss patch becomes a Detection with
``source_int='sar'``, ``emitter_type='sar_disturbance'``, a Polygon geom, and
``features={'coh_drop','area_m2'}`` — the SAME row shape as an RF detection.

Honest caveats carried from prior analysis (spec sec 8):
  * NISAR forward-processed products are PROVISIONAL through much of 2026.
  * L1-L3 latency is ~36-72 h on a ~12-day revisit. This is campaign /
    pattern-of-life monitoring, NOT tactical alerting. CoT is an output format;
    SAR is never framed as real-time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from canopy.geo import LatLon, TangentPlane
from canopy.models import Detection
from canopy.pipeline import Pipeline

PROVISIONAL_NOTE = ("NISAR L-band coherence; product PROVISIONAL (2026); "
                    "latency ~36-72h on ~12-day revisit; pattern-of-life, not tactical.")


@dataclass
class CoherencePatch:
    center: LatLon
    coh_drop: float          # 0..1 loss of coherence vs the reference pair
    area_m2: float
    polygon: List[List[float]]  # [[lon,lat],...] closed ring


def synth_coherence_patches(aoi_center: LatLon, seed: int = 99,
                            n_patches: int = 3) -> List[CoherencePatch]:
    """Stand-in for ISCE2/MintPy coherence output over one AOI.

    Emulates disturbed ground (vehicle tracks, digging, vegetation change) as
    coherence-loss patches. Deterministic given the seed.
    """
    rng = random.Random(seed)
    plane = TangentPlane(aoi_center)
    patches: List[CoherencePatch] = []
    for _ in range(n_patches):
        east = rng.uniform(-1500, 1500)
        north = rng.uniform(-1500, 1500)
        half = rng.uniform(40, 120)  # metres
        c = plane.to_latlon(east, north)
        ring_xy = [(-half, -half), (half, -half), (half, half), (-half, half), (-half, -half)]
        ring = []
        for dx, dy in ring_xy:
            ll = plane.to_latlon(east + dx, north + dy)
            ring.append([ll.lon, ll.lat])
        patches.append(CoherencePatch(
            center=c,
            coh_drop=round(rng.uniform(0.35, 0.85), 3),
            area_m2=round((2 * half) ** 2, 1),
            polygon=ring,
        ))
    return patches


def run(pipeline: Pipeline, exercise_id: str, aoi_center: LatLon,
        observed_at: Optional[datetime] = None, coh_threshold: float = 0.4,
        seed: int = 99) -> List[Detection]:
    """Compute coherence patches and write those over threshold into the library.

    Returns the Detection rows written (source_int='sar').
    """
    observed_at = observed_at or datetime.now(timezone.utc)
    patches = synth_coherence_patches(aoi_center, seed=seed)
    written: List[Detection] = []
    for p in patches:
        if p.coh_drop < coh_threshold:
            continue
        det = Detection(
            source_int="sar",                       # <-- same table, different modality
            observed_at=observed_at,
            features={
                "coh_drop": p.coh_drop,
                "area_m2": p.area_m2,
                "band": "L",
                "provisional": True,
                "note": PROVISIONAL_NOTE,
            },
            confidence=round(min(0.95, p.coh_drop), 3),
            exercise_id=exercise_id,
            geom={"type": "Polygon", "coordinates": [p.polygon]},
            emitter_type="sar_disturbance",
        )
        written.append(pipeline.ingest_detection(det))
    return written
