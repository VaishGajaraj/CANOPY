"""Pipeline — the streaming spine that ties the platform together.

ingest()  : take an edge node report (or a SAR patch), write a sensor-agnostic
            Detection, upsert its Signature, store it. This is the real-time
            path used by the edge loop, the HTTP POST endpoint, and NISAR.
fuse()    : associate recent detections and emit GeoFixes with error ellipses.
report()  : build the after-action report (targetability score + offenders +
            timeline) from whatever is in the library.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import fusion, scoring
from .cot import fix_to_cot
from .geo import ellipse_to_cep
from .models import (
    Detection,
    Exercise,
    GeoFix,
    Signature,
    Source,
    utcnow,
)
from .propagation import NOMINAL_EIRP_DBM, PropagationModel
from .store import Store


@dataclass
class NodeReport:
    """What an edge node POSTs (spec sec 5, step 6)."""
    node_id: str
    observed_at: datetime
    center_hz: float
    bw_hz: float
    burst_ms: float
    duty: float
    bearing_deg: Optional[float]
    emitter_type: str
    confidence: float
    bearing_sigma_deg: Optional[float] = None
    snr_db: Optional[float] = None


class Pipeline:
    def __init__(self, store: Store, prop: Optional[PropagationModel] = None) -> None:
        self.store = store
        self.prop = prop or PropagationModel()

    # --- streaming ingest --------------------------------------------------
    def ingest(self, report: NodeReport, exercise_id: str) -> Detection:
        src = self.store.get_source(report.node_id)
        # signature upsert (find-or-create by modality + type + channel)
        tol = max(25_000.0, 0.6 * report.bw_hz)
        sig = self.store.find_signature("rf", report.emitter_type, report.center_hz, tol)
        if sig is None:
            sig = Signature(
                source_int="rf",
                emitter_type=report.emitter_type,
                feature_vector={"center_hz": report.center_hz, "bw_hz": report.bw_hz},
                first_seen=report.observed_at,
                last_seen=report.observed_at,
                times_seen=1,
            )
            self.store.upsert_signature(sig)
        else:
            sig.times_seen += 1
            sig.last_seen = report.observed_at
            if sig.first_seen is None or report.observed_at < sig.first_seen:
                sig.first_seen = report.observed_at
            self.store.upsert_signature(sig)

        geom = None
        if report.bearing_deg is not None and src and src.lat is not None:
            geom = _bearing_linestring(src.lat, src.lon, report.bearing_deg)

        det = Detection(
            source_int="rf",
            observed_at=report.observed_at,
            features={
                "center_hz": report.center_hz,
                "bw_hz": report.bw_hz,
                "burst_ms": report.burst_ms,
                "duty": report.duty,
                "bearing_deg": report.bearing_deg,
                "bearing_sigma_deg": report.bearing_sigma_deg,
                "snr_db": report.snr_db,
            },
            confidence=report.confidence,
            exercise_id=exercise_id,
            source_id=report.node_id,
            geom=geom,
            emitter_type=report.emitter_type,
            signature_id=sig.id,
        )
        return self.store.add_detection(det)

    def ingest_detection(self, det: Detection) -> Detection:
        """Direct insert for non-RF modalities (e.g. NISAR SAR patches).

        Same door, same table — this is the platform claim in one method.
        """
        if det.signature_id is None and det.emitter_type:
            sig = Signature(
                source_int=det.source_int,
                emitter_type=det.emitter_type,
                feature_vector=dict(det.features),
                first_seen=det.observed_at,
                last_seen=det.observed_at,
                times_seen=1,
            )
            self.store.upsert_signature(sig)
            det.signature_id = sig.id
        return self.store.add_detection(det)

    # --- fusion ------------------------------------------------------------
    def fuse(self, exercise_id: str, time_window_s: float = 12.0) -> List[GeoFix]:
        dets = [d for d in self.store.detections_for(exercise_id)
                if d.source_int == "rf" and d.features.get("bearing_deg") is not None]
        clusters = fusion.associate(dets, time_window_s=time_window_s)
        fixes: List[GeoFix] = []
        seen_bins = set()
        for cl in clusters:
            sig_id = cl[0].signature_id
            # one fix per (signature, coarse time-bin) to avoid duplicates
            tbin = int(cl[-1].observed_at.timestamp() // time_window_s)
            key = (sig_id, tbin)
            if key in seen_bins:
                continue
            fix = fusion.geolocate(cl, self.store.sources, exercise_id, sig_id)
            if fix is not None:
                seen_bins.add(key)
                self.store.add_fix(fix)
                fixes.append(fix)
        return fixes

    # --- CoT ---------------------------------------------------------------
    def cot_events(self, exercise_id: str) -> List[str]:
        out = []
        for f in self.store.fixes_for(exercise_id):
            sig = self.store.signatures.get(f.signature_id) if f.signature_id else None
            etype = sig.emitter_type if sig else "wideband"
            label = (sig.label if sig and sig.label else etype)
            out.append(fix_to_cot(f, etype, label))
        return out

    # --- after-action report ----------------------------------------------
    def report(self, exercise_id: str) -> Dict:
        return build_report(self.store, exercise_id, self.prop)


def _bearing_linestring(lat: float, lon: float, az_deg: float,
                        length_m: float = 8_000.0):
    import math
    from .geo import LatLon, TangentPlane, bearing_unit
    plane = TangentPlane(LatLon(lat, lon))
    dx, dy = bearing_unit(az_deg)
    end = plane.to_latlon(dx * length_m, dy * length_m)
    return {"type": "LineString", "coordinates": [[lon, lat], [end.lon, end.lat]]}


def build_report(store: Store, exercise_id: str, prop: PropagationModel) -> Dict:
    ex = store.get_exercise(exercise_id)
    dets = store.detections_for(exercise_id)
    fixes = store.fixes_for(exercise_id)
    if not dets:
        return {"exercise": ex.name if ex else exercise_id, "empty": True,
                "targetability_score": 0.0, "worst_offenders": [], "timeline": []}

    span_start = min(d.observed_at for d in dets)
    span_end = max(d.observed_at for d in dets)
    span_s = max((span_end - span_start).total_seconds(), 1.0)

    crit_windows = ex.critical_windows if ex else []

    # aggregate per signature (per emitter instance)
    by_sig: Dict[str, List[Detection]] = {}
    for d in dets:
        by_sig.setdefault(d.signature_id or f"anon:{d.emitter_type}", []).append(d)

    activities: List[scoring.EmitterActivity] = []
    for sig_id, rows in by_sig.items():
        rows.sort(key=lambda r: r.observed_at)
        etype = rows[0].emitter_type or "wideband"
        if etype == "sar_disturbance":
            continue  # not an active emitter; excluded from EMCON scoring
        duties = [r.features.get("duty", 0.0) or 0.0 for r in rows]
        duty_mean = sum(duties) / len(duties)
        center = rows[0].features.get("center_hz", 0.0)
        # critical-window hit fraction
        crit_hits = 0
        for w in crit_windows:
            if any(w.start <= r.observed_at <= w.end for r in rows):
                crit_hits += 1
        crit_frac = (crit_hits / len(crit_windows)) if crit_windows else 0.0
        sig = store.signatures.get(sig_id)
        label = (sig.label if sig and sig.label else
                 f"{etype}@{center/1e6:.3f}MHz")
        activities.append(scoring.EmitterActivity(
            key=sig_id,
            emitter_type=etype,
            label=label,
            duty_mean=duty_mean,
            first_seen=rows[0].observed_at,
            last_seen=rows[-1].observed_at,
            eirp_dbm=NOMINAL_EIRP_DBM.get(etype, 40.0),
            center_hz=center,
            n_detections=len(rows),
            critical_hit_fraction=crit_frac,
        ))

    result = scoring.score_exercise(activities, span_s, prop)

    # map fixes to their emitter for the worst-offenders "detection range" view
    fix_by_sig: Dict[str, GeoFix] = {}
    for f in fixes:
        if f.signature_id:
            cur = fix_by_sig.get(f.signature_id)
            if cur is None or f.err_semimajor_m < cur.err_semimajor_m:
                fix_by_sig[f.signature_id] = f

    offenders = []
    for es in result.per_emitter:
        f = fix_by_sig.get(es.key)
        offenders.append({
            "label": es.label,
            "emitter_type": es.emitter_type,
            "score": es.score,
            "persistence": es.persistence,
            "range_term": es.range_term,
            "phase": es.phase,
            "duty": es.duty,
            "detection_range_m": es.det_range_m,
            "n_detections": es.n_detections,
            "drivers": es.drivers,
            "best_fix": None if f is None else {
                "lat": round(f.lat, 6), "lon": round(f.lon, 6),
                "err_semimajor_m": round(f.err_semimajor_m, 1),
                "err_semiminor_m": round(f.err_semiminor_m, 1),
                "err_orient_deg": round(f.err_orient_deg, 1),
                "cep50_m": round(f.cep50_m or 0.0, 1),
                "gdop": round(f.gdop or 0.0, 2),
            },
        })

    # timeline: detections per coarse bin + peak-detectability window
    n_bins = 24
    bin_s = span_s / n_bins
    bins = [0] * n_bins
    bin_score = [0.0] * n_bins
    for d in dets:
        if d.emitter_type == "sar_disturbance":
            continue
        idx = min(n_bins - 1, int((d.observed_at - span_start).total_seconds() / bin_s))
        bins[idx] += 1
        bin_score[idx] += (d.features.get("duty", 0.0) or 0.0)
    peak_idx = max(range(n_bins), key=lambda i: bin_score[i]) if any(bin_score) else 0
    timeline = [{
        "t": (span_start + timedelta(seconds=i * bin_s)).isoformat(),
        "detections": bins[i],
        "activity": round(bin_score[i], 2),
    } for i in range(n_bins)]

    sar_rows = [d for d in dets if d.source_int == "sar"]

    return {
        "exercise": ex.name if ex else exercise_id,
        "unit": ex.unit if ex else None,
        "window": {"start": span_start.isoformat(), "end": span_end.isoformat(),
                   "duration_s": round(span_s, 1)},
        "targetability_score": result.overall,
        "worst": (None if result.worst is None else {
            "label": result.worst.label, "score": result.worst.score}),
        "worst_offenders": offenders,
        "timeline": timeline,
        "peak_window": {
            "start": (span_start + timedelta(seconds=peak_idx * bin_s)).isoformat(),
            "end": (span_start + timedelta(seconds=(peak_idx + 1) * bin_s)).isoformat(),
        },
        "counts": {
            "detections": len(dets),
            "rf_detections": len([d for d in dets if d.source_int == "rf"]),
            "sar_detections": len(sar_rows),
            "fixes": len(fixes),
            "signatures": len(by_sig),
        },
        "methodology": result.methodology,
        "multi_int": {
            "source_ints": sorted({d.source_int for d in dets}),
            "note": "RF bearings and SAR coherence patches are the same "
                    "Detection row shape written through the same door.",
        },
    }
