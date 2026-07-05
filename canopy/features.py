"""Per-candidate feature extraction (spec sec 5, step 3).

From a detected band + the tuner geometry we measure center frequency and
occupied bandwidth. Burst timing / duty cycle come from a short time-domain
occupancy series (a boolean 'on/off' trace the capture layer samples), because
you cannot read duty off a single averaged PSD.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Sequence

from .detect import Band


@dataclass
class Features:
    center_hz: float
    bw_hz: float
    burst_ms: float
    duty: float
    snr_db: float

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


def band_to_freq(band: Band, freqs_hz: Sequence[float], tuner_center_hz: float) -> (
        "tuple[float, float]"):
    """Map PSD bin indices to absolute RF center & bandwidth.

    freqs_hz are baseband bin frequencies (-fs/2..fs/2); tuner_center_hz is where
    the front-end was parked, so absolute = tuner_center + baseband.
    """
    lo_hz = tuner_center_hz + freqs_hz[band.lo_idx]
    hi_hz = tuner_center_hz + freqs_hz[band.hi_idx]
    center = 0.5 * (lo_hz + hi_hz)
    bw = max(hi_hz - lo_hz, freqs_hz[1] - freqs_hz[0] if len(freqs_hz) > 1 else 0.0)
    return center, bw


def duty_from_occupancy(occupancy: Sequence[int], frame_ms: float) -> "tuple[float, float]":
    """Return (burst_ms, duty) from a boolean on/off occupancy trace.

    burst_ms is the mean contiguous 'on' run length; duty is the on fraction.
    """
    n = len(occupancy)
    if n == 0:
        return 0.0, 0.0
    on = sum(1 for v in occupancy if v)
    duty = on / n
    # mean run length of 'on' segments
    runs: List[int] = []
    cur = 0
    for v in occupancy:
        if v:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    burst_frames = (sum(runs) / len(runs)) if runs else 0.0
    return burst_frames * frame_ms, duty


def extract(band: Band, freqs_hz: Sequence[float], tuner_center_hz: float,
            occupancy: Sequence[int], frame_ms: float) -> Features:
    center, bw = band_to_freq(band, freqs_hz, tuner_center_hz)
    burst_ms, duty = duty_from_occupancy(occupancy, frame_ms)
    return Features(center_hz=center, bw_hz=bw, burst_ms=burst_ms, duty=duty,
                    snr_db=band.snr_db)
