"""CA-CFAR energy detection over a PSD (spec sec 5, step 2).

Cell-averaging constant-false-alarm-rate detection: for each frequency bin,
estimate the local noise floor from training cells on either side (skipping
guard cells so a strong signal doesn't inflate its own threshold), and declare
occupancy where power exceeds noise + a fixed offset. Adjacent occupied bins are
merged into candidate bands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence


@dataclass
class Band:
    lo_idx: int
    hi_idx: int
    peak_idx: int
    peak_db: float
    floor_db: float

    @property
    def snr_db(self) -> float:
        return self.peak_db - self.floor_db


def ca_cfar(psd_db: Sequence[float], guard: int = 2, train: int = 16,
            offset_db: float = 8.0, min_width: int = 1) -> List[Band]:
    """Return occupied bands. offset_db is the threshold above the local floor."""
    n = len(psd_db)
    occupied = [False] * n
    floor = [0.0] * n
    for i in range(n):
        lo0 = max(0, i - guard - train)
        lo1 = max(0, i - guard)
        hi0 = min(n, i + guard + 1)
        hi1 = min(n, i + guard + train + 1)
        cells = psd_db[lo0:lo1] + psd_db[hi0:hi1]
        if not cells:
            floor[i] = psd_db[i]
            continue
        # trimmed mean: drop the top 25% of training cells so a neighbouring
        # emitter's skirt doesn't raise the floor.
        s = sorted(cells)
        keep = s[: max(1, int(len(s) * 0.75))]
        f = sum(keep) / len(keep)
        floor[i] = f
        occupied[i] = psd_db[i] > f + offset_db

    bands: List[Band] = []
    i = 0
    while i < n:
        if not occupied[i]:
            i += 1
            continue
        j = i
        while j < n and occupied[j]:
            j += 1
        lo, hi = i, j - 1
        if (hi - lo + 1) >= min_width:
            peak_idx = max(range(lo, hi + 1), key=lambda k: psd_db[k])
            bands.append(Band(
                lo_idx=lo, hi_idx=hi, peak_idx=peak_idx,
                peak_db=psd_db[peak_idx],
                floor_db=sum(floor[lo:hi + 1]) / (hi - lo + 1),
            ))
        i = j
    return bands
