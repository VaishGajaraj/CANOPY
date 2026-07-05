"""Edge node orchestration loop (spec sec 5, run.py).

Reference structure for what runs on each Raspberry Pi 5 + KrakenSDR node:

    capture -> detect (CFAR) -> features -> classify -> bearing -> report

The node is stateless; all state lives in the signature library. This module
runs the REAL chain on one captured block so the node software is proven
end-to-end without hardware, then POSTs a NodeReport to the backend.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import List, Optional

from canopy.classify import classify
from canopy.detect import ca_cfar
from canopy.dsp import welch_psd
from canopy.features import extract
from canopy.pipeline import NodeReport

from .bearing import music_azimuth_stub
from .capture import CaptureFn


def process_block(capture: CaptureFn, node_id: str, when: datetime,
                  true_bearing_deg: float = 0.0, occupancy: Optional[List[int]] = None,
                  frame_ms: float = 4.0, rng: Optional[random.Random] = None
                  ) -> List[NodeReport]:
    """Run one capture block through the full node chain -> NodeReports."""
    iq, fs, tuner_center = capture()
    freqs, psd = welch_psd(iq, fs, nfft=1024)
    bands = ca_cfar(psd, offset_db=8.0, min_width=2)
    occupancy = occupancy if occupancy is not None else [1] * 8 + [0] * 12
    reports: List[NodeReport] = []
    for band in bands:
        feat = extract(band, freqs, tuner_center, occupancy, frame_ms)
        etype, conf = classify(feat.center_hz, feat.bw_hz, feat.burst_ms, feat.duty)
        bearing, sigma = music_azimuth_stub(true_bearing_deg, feat.snr_db, rng=rng)
        reports.append(NodeReport(
            node_id=node_id,
            observed_at=when,
            center_hz=feat.center_hz,
            bw_hz=feat.bw_hz,
            burst_ms=feat.burst_ms,
            duty=feat.duty,
            bearing_deg=bearing,
            emitter_type=etype,
            confidence=conf,
            bearing_sigma_deg=round(sigma, 2),
            snr_db=round(feat.snr_db, 1),
        ))
    return reports


def _now() -> datetime:
    return datetime.now(timezone.utc)
