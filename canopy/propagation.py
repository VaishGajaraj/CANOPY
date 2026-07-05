"""RF propagation — how far away an adversary SIGINT sensor could detect an
emitter. Feeds the 'detection range' term of the targetability score.

We use a log-distance path-loss model with a configurable exponent (n=2 free
space, n~3.5-4 for cluttered/vegetated training areas). Given emitter EIRP and
an assumed adversary receiver sensitivity, we invert for the range at which
received power drops to sensitivity — the detection radius.

This is deliberately simple and its assumptions are surfaced in the report. The
point is an honest, documented number, not a propagation product.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PropagationModel:
    path_loss_exponent: float = 3.5   # cluttered/vegetated default
    ref_distance_m: float = 1.0
    # Reference free-space path loss at ref_distance for a given frequency is
    # computed per call; adversary sensitivity is the detection floor.
    adversary_sensitivity_dbm: float = -110.0

    def fspl_db(self, freq_hz: float, dist_m: float) -> float:
        """Free-space path loss (dB) at the reference distance."""
        d = max(dist_m, 1e-3)
        return 20 * math.log10(d) + 20 * math.log10(freq_hz) + 20 * math.log10(
            4 * math.pi / 299_792_458.0)

    def detection_range_m(self, eirp_dbm: float, freq_hz: float) -> float:
        """Range at which received power == adversary sensitivity."""
        # PL at ref distance (free space), then log-distance beyond it.
        pl_ref = self.fspl_db(freq_hz, self.ref_distance_m)
        # received = eirp - pl_ref - 10 n log10(d/dref) = sensitivity
        margin = eirp_dbm - pl_ref - self.adversary_sensitivity_dbm
        if margin <= 0:
            return self.ref_distance_m
        exponent = margin / (10.0 * self.path_loss_exponent)
        return self.ref_distance_m * (10.0 ** exponent)


# Nominal EIRP by emitter type (dBm), order-of-magnitude, documented in report.
NOMINAL_EIRP_DBM = {
    "tac_vhf": 44.0,       # ~25 W manpack
    "tac_uhf": 40.0,       # ~10 W
    "cellular": 23.0,      # handset uplink ~200 mW-1 W
    "bt_region": 4.0,      # ~2.5 mW class-2-ish
    "gps_anomaly": 50.0,   # a jammer is loud by definition
    "wideband": 40.0,
    "sar_disturbance": float("nan"),  # not an emitter
}
