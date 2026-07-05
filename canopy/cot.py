"""Cursor-on-Target (CoT) export (spec sec 6).

pytak speaks CoT to a TAK Server in production; for the MVP we emit the same
CoT 2.0 event XML with stdlib so the wire format is real and inspectable. The
honest-uncertainty rule is enforced here: the fix's error ellipse is written
into the CoT ``ce`` (circular error) attribute, so a downstream ATAK operator
sees the uncertainty, not a false pinpoint.

SAR detections travel this same path (spec sec 8) — same event schema, a
different ``type`` — which is the multi-INT proof in one output format.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

from .geo import ellipse_to_cep
from .models import Detection, GeoFix

# MIL-STD-2525-ish CoT type codes (coarse; refine per customer).
COT_TYPE = {
    "tac_vhf": "a-h-G-E-S",       # hostile ground equipment, SIGINT/emitter
    "tac_uhf": "a-h-G-E-S",
    "cellular": "a-h-G-E-S",
    "bt_region": "a-h-G-E-S",
    "gps_anomaly": "a-h-G-E-S-J",  # jammer
    "wideband": "a-h-G-E-S",
    "sar_disturbance": "a-h-G-E-S-D",  # SAR-derived disturbance
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def fix_to_cot(fix: GeoFix, emitter_type: str, label: str,
               stale_after_s: float = 300.0) -> str:
    """Serialise a fused fix as a CoT event with honest circular error."""
    now = fix.fixed_at
    # ce: circular error at ~1-sigma from the ellipse; le unknown.
    ce = fix.cep50_m if fix.cep50_m is not None else ellipse_to_cep(
        fix.err_semimajor_m, fix.err_semiminor_m)

    evt = ET.Element("event", {
        "version": "2.0",
        "uid": f"CANOPY.{emitter_type}.{fix.id}",
        "type": COT_TYPE.get(emitter_type, "a-u-G"),
        "how": "m-g",
        "time": _iso(now),
        "start": _iso(now),
        "stale": _iso(now + timedelta(seconds=stale_after_s)),
    })
    ET.SubElement(evt, "point", {
        "lat": f"{fix.lat:.7f}",
        "lon": f"{fix.lon:.7f}",
        "hae": "9999999.0",
        "ce": f"{ce:.1f}",
        "le": "9999999.0",
    })
    detail = ET.SubElement(evt, "detail")
    ET.SubElement(detail, "contact", {"callsign": label})
    ET.SubElement(detail, "remarks").text = (
        f"emitter={emitter_type} method={fix.method} "
        f"ellipse={fix.err_semimajor_m:.0f}x{fix.err_semiminor_m:.0f}m "
        f"@{fix.err_orient_deg:.0f}deg gdop={fix.gdop:.1f} "
        f"(uncertainty is real; do not treat as a point target)"
    )
    ET.SubElement(detail, "__canopy", {
        "source_int": "rf" if fix.method == "bearing_intersection" else "sar",
        "cep50_m": f"{ce:.1f}",
    })
    return ET.tostring(evt, encoding="unicode")


def detection_to_cot(det: Detection, label: Optional[str] = None,
                     stale_after_s: float = 300.0) -> Optional[str]:
    """Serialise a single detection (used for SAR patches with polygon geom)."""
    geom = det.geom or {}
    coords = geom.get("coordinates")
    if geom.get("type") == "Point" and coords:
        lon, lat = coords[0], coords[1]
    elif geom.get("type") == "Polygon" and coords:
        ring = coords[0]
        lon = sum(p[0] for p in ring) / len(ring)
        lat = sum(p[1] for p in ring) / len(ring)
    else:
        return None
    now = det.observed_at
    etype = det.emitter_type or "wideband"
    evt = ET.Element("event", {
        "version": "2.0",
        "uid": f"CANOPY.det.{det.id}",
        "type": COT_TYPE.get(etype, "a-u-G"),
        "how": "m-g",
        "time": _iso(now),
        "start": _iso(now),
        "stale": _iso(now + timedelta(seconds=stale_after_s)),
    })
    ET.SubElement(evt, "point", {
        "lat": f"{lat:.7f}", "lon": f"{lon:.7f}", "hae": "9999999.0",
        "ce": f"{det.features.get('area_m2', 250.0) ** 0.5:.1f}", "le": "9999999.0",
    })
    detail = ET.SubElement(evt, "detail")
    ET.SubElement(detail, "contact", {"callsign": label or etype})
    ET.SubElement(detail, "__canopy", {"source_int": det.source_int})
    return ET.tostring(evt, encoding="unicode")
