"""KC-2 — classification separability (spec sec 9).

On field-like feature vectors (not clean lab signals), does the rule table
separate the emitter types at useful accuracy? Kill threshold: < ~80% correct
means the classifier needs rework before the after-action report's per-emitter
claims are honest.

We draw noisy samples from each emitter type's realistic operating point and
score the rule table. Native RTL-SDR coverage is VHF/UHF/cellular/GPS; bt_region
(2.4 GHz) needs the v1 HackRF front end, so the headline metric is over the
natively-covered types, with the full six-way score reported alongside.
"""

from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canopy.classify import GPS_L1_HZ, classify

MHZ = 1_000_000.0
KHZ = 1_000.0

# (type, center_hz, bw_hz, burst_ms, duty) operating points
OPERATING_POINTS = {
    "tac_vhf":     (58 * MHZ, 25 * KHZ, 45.0, 0.30),
    "tac_uhf":     (385 * MHZ, 25 * KHZ, 40.0, 0.12),
    "cellular":    (1_745 * MHZ, 9 * MHZ, 60.0, 0.35),
    "gps_anomaly": (GPS_L1_HZ, 18 * MHZ, 200.0, 0.9),
    "bt_region":   (2_440 * MHZ, 1.2 * MHZ, 3.0, 0.05),
}

NATIVE_TYPES = {"tac_vhf", "tac_uhf", "cellular", "gps_anomaly"}


def _sample(rng, etype):
    c0, bw0, burst0, duty0 = OPERATING_POINTS[etype]
    if etype == "tac_vhf":
        center = rng.uniform(33 * MHZ, 86 * MHZ)
    elif etype == "tac_uhf":
        center = rng.uniform(228 * MHZ, 448 * MHZ)
    elif etype == "cellular":
        center = rng.choice([rng.uniform(704 * MHZ, 912 * MHZ),
                             rng.uniform(1_712 * MHZ, 1_783 * MHZ)])
    elif etype == "gps_anomaly":
        center = GPS_L1_HZ + rng.gauss(0, 1 * MHZ)
    else:
        center = rng.uniform(2_402 * MHZ, 2_480 * MHZ)
    bw = max(1 * KHZ, bw0 * (1 + rng.gauss(0, 0.15)))
    burst = max(1.0, burst0 * (1 + rng.gauss(0, 0.2)))
    duty = min(1.0, max(0.001, duty0 + rng.gauss(0, 0.05)))
    return center, bw, burst, duty


class TestKC2Classification(unittest.TestCase):

    def test_separability(self):
        rng = random.Random(42)
        per_type = {}
        native_correct = native_total = 0
        all_correct = all_total = 0
        for etype in OPERATING_POINTS:
            correct = 0
            n = 300
            for _ in range(n):
                c, bw, burst, duty = _sample(rng, etype)
                pred, _conf = classify(c, bw, burst, duty)
                ok = (pred == etype)
                correct += ok
                all_correct += ok
                all_total += 1
                if etype in NATIVE_TYPES:
                    native_correct += ok
                    native_total += 1
            per_type[etype] = correct / n

        native_acc = native_correct / native_total
        all_acc = all_correct / all_total
        print("\n[KC-2 per-type accuracy]")
        for t, a in per_type.items():
            tag = "" if t in NATIVE_TYPES else "  (needs v1 HackRF front-end)"
            print(f"    {t:<12} {a*100:5.1f}%{tag}")
        print(f"[KC-2 native types] {native_acc*100:.1f}%   [all six] {all_acc*100:.1f}%")

        self.assertGreaterEqual(native_acc, 0.80,
                                f"native-type accuracy {native_acc:.2f} below KC-2 threshold")
        for t in NATIVE_TYPES:
            self.assertGreaterEqual(per_type[t], 0.70,
                                    f"{t} accuracy {per_type[t]:.2f} too low")


if __name__ == "__main__":
    unittest.main(verbosity=2)
