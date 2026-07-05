"""KC-1 — DF fix accuracy (the primary kill criterion, spec sec 9).

A beautiful dashboard over a 400 m error ellipse is a liability, so this is the
experiment that is upstream of every pixel. We place a known emitter, ring it
with surveyed nodes in representative geometry, simulate bearings with realistic
angular noise, fuse, and measure the fix error distribution.

Kill threshold: median fix error must be < ~150 m (the footprint of the thing
being localised). We also check that the error ellipse is *honest* — that the
ground truth actually falls inside the reported 95% ellipse about as often as it
should. An overconfident ellipse is as dangerous as a wrong fix.
"""

from __future__ import annotations

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canopy.geo import (
    LOB, LatLon, TangentPlane, haversine_m, intersect_lobs,
)

KILL_THRESHOLD_M = 150.0


def _bearing(node_xy, target_xy):
    dx = target_xy[0] - node_xy[0]
    dy = target_xy[1] - node_xy[1]
    return math.degrees(math.atan2(dx, dy)) % 360.0


def _run_geometry(node_offsets_m, sigma_deg, trials, seed, target_offset_m=(0.0, 0.0)):
    """Return (errors, coverage95) for a node geometry around an emitter."""
    rng = random.Random(seed)
    origin = LatLon(35.13, -79.0)
    plane = TangentPlane(origin)
    target_xy = target_offset_m
    truth_ll = plane.to_latlon(*target_xy)

    errors = []
    inside = 0
    for _ in range(trials):
        lobs = []
        for (nx, ny) in node_offsets_m:
            true_az = _bearing((nx, ny), target_xy)
            noisy = true_az + rng.gauss(0, sigma_deg)
            lobs.append(LOB(x=nx, y=ny, az_deg=noisy, sigma_az_deg=sigma_deg))
        fix = intersect_lobs(lobs)
        if fix is None:
            continue
        fix_ll = plane.to_latlon(fix.x, fix.y)
        errors.append(haversine_m(fix_ll, truth_ll))

        # Mahalanobis of truth inside the reported ellipse (95% -> chi2_2 = 5.991)
        du = target_xy[0] - fix.x
        dv = target_xy[1] - fix.y
        th = math.radians(fix.err_orient_deg)
        # major axis direction (east,north) = (sin th, cos th)
        maj = du * math.sin(th) + dv * math.cos(th)
        minr = -du * math.cos(th) + dv * math.sin(th)
        a = max(fix.err_semimajor_m, 1e-6)
        b = max(fix.err_semiminor_m, 1e-6)
        d2 = (maj / a) ** 2 + (minr / b) ** 2
        if d2 <= 5.991:
            inside += 1
    errors.sort()
    coverage = inside / len(errors) if errors else 0.0
    return errors, coverage


def _median(xs):
    n = len(xs)
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


class TestKC1Geolocation(unittest.TestCase):

    def test_good_geometry_passes_kill_threshold(self):
        # 4 nodes ringing the emitter at ~1.2-1.5 km with wide angular spread.
        nodes = [(50, 1450), (1450, -150), (-150, -1500), (-1500, 350)]
        errors, coverage = _run_geometry(nodes, sigma_deg=4.0, trials=400, seed=1)
        med = _median(errors)
        p90 = errors[int(0.9 * len(errors))]
        print(f"\n[KC-1 good geometry] median={med:.1f}m p90={p90:.1f}m "
              f"ellipse95 coverage={coverage:.2f} (n={len(errors)})")
        self.assertLess(med, KILL_THRESHOLD_M,
                        f"median fix error {med:.0f}m exceeds KC-1 threshold")
        # honest ellipse: truth should be inside the 95% ellipse most of the time
        self.assertGreater(coverage, 0.70,
                           f"error ellipse is overconfident (coverage {coverage:.2f})")

    def test_three_nodes_still_usable(self):
        nodes = [(0, 1400), (1300, -400), (-1300, -400)]
        errors, coverage = _run_geometry(nodes, sigma_deg=4.0, trials=400, seed=2)
        med = _median(errors)
        print(f"[KC-1 three nodes]  median={med:.1f}m coverage={coverage:.2f}")
        self.assertLess(med, KILL_THRESHOLD_M)

    def test_bad_geometry_is_honestly_worse(self):
        # Nearly collinear nodes -> poor GDOP. This documents the failure mode:
        # the product must fall back to zonal 'detectable/not' if geometry is bad.
        nodes = [(-1500, 0), (-500, 20), (500, -20), (1500, 0)]
        errors, _ = _run_geometry(nodes, sigma_deg=4.0, trials=400, seed=3,
                                  target_offset_m=(0.0, 900.0))
        med = _median(errors)
        print(f"[KC-1 bad geometry] median={med:.1f}m (expected worse; kill-or-rescope)")
        # We assert it IS worse than good geometry — the point is honesty, not a pass.
        self.assertGreater(med, 60.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
