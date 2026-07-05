"""Bearing estimation (spec sec 5, step 5).

Production: read the KrakenSDR's MUSIC azimuth estimate for each active band
(five coherent channels give super-resolution DF out of the box). MVP: derive a
geometry-truth bearing with realistic angular noise, matching what MUSIC would
report for a given array SNR.
"""

from __future__ import annotations

import math
import random
from typing import Optional


def music_azimuth_stub(true_bearing_deg: float, snr_db: float,
                       base_sigma_deg: float = 4.0, rng: Optional[random.Random] = None
                       ) -> "tuple[float, float]":
    """Return (bearing_deg, sigma_deg). Angular error tightens with SNR."""
    rng = rng or random.Random()
    snr_gain = max(1.0, snr_db / 12.0)
    sigma = base_sigma_deg / math.sqrt(snr_gain)
    return (true_bearing_deg + rng.gauss(0, sigma)) % 360.0, sigma
