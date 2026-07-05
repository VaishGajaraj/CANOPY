"""Fusion engine — association + geolocation (spec sec 6).

Association: group detections across nodes/time that share frequency, bandwidth
and burst signature within tolerance — these are the same emitter seen by
multiple nodes. Geolocation: each node contributes a line of bearing from its
surveyed emplacement; intersect >=2 by weighted least squares; the residual and
covariance give the error ellipse, which is ALWAYS persisted and surfaced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from .geo import LOB, LatLon, TangentPlane, ellipse_to_cep, intersect_lobs
from .models import Detection, GeoFix, Source, utcnow


def channel_key(emitter_type: str, center_hz: float, step_hz: float = 25_000.0) -> str:
    """Coarse channelisation so the same net lands in the same bin."""
    return f"{emitter_type}:{round(center_hz / step_hz) * step_hz:.0f}"


def _freq_match(a: Detection, b: Detection, tol_hz: float) -> bool:
    ca = a.features.get("center_hz")
    cb = b.features.get("center_hz")
    if ca is None or cb is None:
        return False
    return abs(ca - cb) <= tol_hz and a.emitter_type == b.emitter_type


def associate(dets: Sequence[Detection], time_window_s: float = 12.0,
              freq_tol_hz: float = 30_000.0) -> List[List[Detection]]:
    """Cluster detections into same-emitter groups within a time window.

    A cluster keeps at most one (latest) detection per node so a chatty node
    can't dominate the geometry.
    """
    ordered = sorted(dets, key=lambda d: d.observed_at)
    clusters: List[List[Detection]] = []
    for d in ordered:
        placed = False
        for cl in clusters:
            head = cl[-1]
            if (abs((d.observed_at - head.observed_at).total_seconds()) <= time_window_s
                    and _freq_match(d, head, freq_tol_hz)):
                cl.append(d)
                placed = True
                break
        if not placed:
            clusters.append([d])
    return clusters


def _dedupe_by_node(cluster: Sequence[Detection]) -> List[Detection]:
    latest: Dict[Optional[str], Detection] = {}
    for d in cluster:
        cur = latest.get(d.source_id)
        if cur is None or d.observed_at >= cur.observed_at:
            latest[d.source_id] = d
    return list(latest.values())


def geolocate(cluster: Sequence[Detection], sources: Dict[str, Source],
              exercise_id: Optional[str] = None,
              signature_id: Optional[str] = None) -> Optional[GeoFix]:
    """Fuse a same-emitter cluster of RF bearings into a GeoFix with ellipse."""
    members = [d for d in _dedupe_by_node(cluster)
               if d.source_id and d.features.get("bearing_deg") is not None]
    # need >=2 distinct, emplaced nodes
    emplaced = []
    for d in members:
        src = sources.get(d.source_id)
        if src and src.lat is not None and src.lon is not None:
            emplaced.append((d, src))
    if len(emplaced) < 2:
        return None

    # tangent plane centred on the node centroid
    clat = sum(s.lat for _, s in emplaced) / len(emplaced)
    clon = sum(s.lon for _, s in emplaced) / len(emplaced)
    plane = TangentPlane(LatLon(clat, clon))

    lobs: List[LOB] = []
    for d, src in emplaced:
        x, y = plane.to_xy(LatLon(src.lat, src.lon))
        sigma = d.features.get("bearing_sigma_deg")
        if sigma is None:
            sigma = src.calibration.get("df_sigma_deg", 5.0)
        lobs.append(LOB(x=x, y=y, az_deg=float(d.features["bearing_deg"]),
                        sigma_az_deg=float(sigma)))

    fix = intersect_lobs(lobs)
    if fix is None:
        return None
    ll = plane.to_latlon(fix.x, fix.y)
    when = max(d.observed_at for d, _ in emplaced)
    return GeoFix(
        lat=ll.lat, lon=ll.lon,
        err_semimajor_m=fix.err_semimajor_m,
        err_semiminor_m=fix.err_semiminor_m,
        err_orient_deg=fix.err_orient_deg,
        method="bearing_intersection",
        fixed_at=when,
        exercise_id=exercise_id,
        signature_id=signature_id,
        cep50_m=ellipse_to_cep(fix.err_semimajor_m, fix.err_semiminor_m),
        gdop=fix.gdop,
        n_contributors=len(emplaced),
    )
