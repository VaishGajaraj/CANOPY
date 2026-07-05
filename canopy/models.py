"""In-memory mirror of the signature-library schema (see db/schema.sql).

These dataclasses are the row shapes. The load-bearing invariant of the whole
company is here: a Detection is modality-agnostic. An RF bearing and a SAR
coherence-loss patch are the *same* Detection — only ``source_int`` and the
contents of the ``features`` dict differ. If you ever feel the urge to add a
``SarDetection`` subclass, the platform claim is breaking (spec sec 4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SourceInt = str        # 'rf' | 'sar' (extensible)
EmitterType = str      # tac_vhf | tac_uhf | cellular | bt_region | gps_anomaly | wideband | sar_disturbance


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Source:
    """A sensor/node of any modality."""
    label: str
    source_int: SourceInt
    lat: Optional[float] = None       # node emplacement; null for spaceborne
    lon: Optional[float] = None
    calibration: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class Exercise:
    """A campaign container: an exercise or an AOI-monitoring period."""
    name: str
    unit: Optional[str] = None
    aoi: Optional[List[List[float]]] = None   # polygon as [[lon,lat],...]
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    # Critical-phase windows (e.g. the assault) drive the targetability score.
    critical_windows: List["CriticalWindow"] = field(default_factory=list)
    id: str = field(default_factory=new_id)


@dataclass
class CriticalWindow:
    label: str
    start: datetime
    end: datetime


@dataclass
class Signature:
    """The compounding asset: what a thing looks like, so it is re-findable."""
    source_int: SourceInt
    emitter_type: EmitterType
    feature_vector: Dict[str, Any]
    label: Optional[str] = None
    analyst_confirmed: bool = False
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    times_seen: int = 0
    id: str = field(default_factory=new_id)


@dataclass
class Detection:
    """Atomic, sensor-agnostic detection. Same shape for every modality."""
    source_int: SourceInt
    observed_at: datetime
    features: Dict[str, Any]              # RF: {center_hz,bw_hz,burst_ms,duty,bearing_deg,...}
                                          # SAR: {coh_drop, area_m2, ...}
    confidence: float
    exercise_id: Optional[str] = None
    source_id: Optional[str] = None
    # Geometry: a Point for a fix, a LineString for a bearing, a Polygon for a
    # SAR patch. Stored as GeoJSON-ish dict {'type':..., 'coordinates':...}.
    geom: Optional[Dict[str, Any]] = None
    emitter_type: Optional[EmitterType] = None
    signature_id: Optional[str] = None
    id: str = field(default_factory=new_id)


@dataclass
class GeoFix:
    """A fused geolocation fix from >=2 detections. Honest uncertainty always."""
    lat: float
    lon: float
    err_semimajor_m: float
    err_semiminor_m: float
    err_orient_deg: float
    method: str                          # 'bearing_intersection' | 'coherence_patch'
    fixed_at: datetime
    exercise_id: Optional[str] = None
    signature_id: Optional[str] = None
    cep50_m: Optional[float] = None
    gdop: Optional[float] = None
    n_contributors: int = 0
    id: str = field(default_factory=new_id)


@dataclass
class Watch:
    """A persistent standing query — the flywheel seed."""
    signature_id: str
    aoi: Optional[List[List[float]]] = None
    active: bool = True
    created_at: datetime = field(default_factory=utcnow)
    id: str = field(default_factory=new_id)


@dataclass
class WatchHit:
    watch_id: str
    detection_id: str
    fired_at: datetime = field(default_factory=utcnow)
    id: str = field(default_factory=new_id)
