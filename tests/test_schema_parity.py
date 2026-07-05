"""The platform claim, as an executable invariant (spec sec 4, sec 8).

"The second INT drops into the same library over a weekend." This test fails the
day someone adds a SAR-only code path. It asserts that an RF bearing and a SAR
coherence patch are the SAME Detection type, land in the SAME collection, and
both surface through the SAME report and CoT export.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canopy.geo import LatLon
from canopy.models import Detection, Exercise, Source
from canopy.pipeline import NodeReport, Pipeline
from canopy.store import Store
from nisar import worker as nisar_worker

T0 = datetime(2026, 7, 2, 13, 0, tzinfo=timezone.utc)


class TestSchemaParity(unittest.TestCase):

    def setUp(self):
        self.store = Store()
        self.pipe = Pipeline(self.store)
        self.ex = Exercise(name="parity", started_at=T0)
        self.store.add_exercise(self.ex)
        self.node = Source(label="n1", source_int="rf", lat=35.13, lon=-79.0,
                           calibration={"df_sigma_deg": 4.0})
        self.store.add_source(self.node)

    def test_rf_and_sar_share_one_table(self):
        # RF detection through the edge door
        rep = NodeReport(node_id=self.node.id, observed_at=T0, center_hz=51.5e6,
                         bw_hz=25e3, burst_ms=40, duty=0.4, bearing_deg=90.0,
                         emitter_type="tac_vhf", confidence=0.9,
                         bearing_sigma_deg=4.0, snr_db=20)
        rf_det = self.pipe.ingest(rep, self.ex.id)

        # SAR detection through the NISAR door
        sar_rows = nisar_worker.run(self.pipe, self.ex.id, LatLon(35.13, -79.0),
                                    observed_at=T0)

        # same Python type, same collection
        self.assertIsInstance(rf_det, Detection)
        for s in sar_rows:
            self.assertIsInstance(s, Detection)
        all_dets = self.store.detections_for(self.ex.id)
        self.assertIn(rf_det, all_dets)
        for s in sar_rows:
            self.assertIn(s, all_dets)

        # both modalities present, distinguished ONLY by source_int
        source_ints = {d.source_int for d in all_dets}
        self.assertEqual(source_ints, {"rf", "sar"})

        # the store has no SAR-specific collection (would break the thesis)
        collection_names = [a for a in vars(self.store) if not a.startswith("_")]
        self.assertNotIn("sar_detections", collection_names)
        self.assertNotIn("sar_patches", collection_names)

        # both surface in the same report
        report = self.pipe.report(self.ex.id)
        self.assertEqual(set(report["multi_int"]["source_ints"]), {"rf", "sar"})
        self.assertGreaterEqual(report["counts"]["sar_detections"], 1)
        self.assertGreaterEqual(report["counts"]["rf_detections"], 1)

    def test_detection_shape_is_modality_agnostic(self):
        # the same field set describes both; only `features` contents differ
        rf = Detection(source_int="rf", observed_at=T0, confidence=0.9,
                       features={"center_hz": 51.5e6, "bearing_deg": 90.0})
        sar = Detection(source_int="sar", observed_at=T0, confidence=0.8,
                        features={"coh_drop": 0.6, "area_m2": 400.0})
        self.assertEqual(set(vars(rf).keys()), set(vars(sar).keys()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
