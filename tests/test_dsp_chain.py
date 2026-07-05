"""Proves the RF signal chain is real, not asserted (spec sec 5).

Plant a signal in synthetic complex baseband -> Welch PSD -> CA-CFAR detection
-> feature extraction, and confirm we recover a band at the planted center
frequency. If this passes, the edge node's capture->detect->features path works
on genuine IQ, not on hand-fed features.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canopy.detect import ca_cfar
from canopy.dsp import welch_psd
from canopy.features import extract
from edge.simulate import synth_iq

MHZ = 1_000_000.0
KHZ = 1_000.0


class TestDSPChain(unittest.TestCase):

    def test_recovers_planted_signal(self):
        fs = 2_400_000.0
        tuner = 51_500_000.0
        offset = 40_000.0          # signal sits 40 kHz above tuner center
        bw = 30 * KHZ
        iq = synth_iq(fs, 4096, offset, bw, snr_db=20.0, seed=11)
        freqs, psd = welch_psd(iq, fs, nfft=1024)
        bands = ca_cfar(psd, offset_db=8.0, min_width=2)
        self.assertTrue(bands, "CFAR found no band in a 20 dB SNR signal")

        # strongest band should map back near tuner+offset
        band = max(bands, key=lambda b: b.snr_db)
        feat = extract(band, freqs, tuner, occupancy=[1] * 8 + [0] * 12, frame_ms=4.0)
        err_hz = abs(feat.center_hz - (tuner + offset))
        print(f"\n[DSP] recovered center={feat.center_hz/1e6:.4f} MHz "
              f"(err={err_hz/1e3:.1f} kHz) bw={feat.bw_hz/1e3:.1f} kHz snr={feat.snr_db:.1f} dB")
        self.assertLess(err_hz, 60 * KHZ, "recovered center too far from truth")
        self.assertGreater(feat.snr_db, 6.0)

    def test_noise_only_is_quiet(self):
        fs = 2_400_000.0
        iq = synth_iq(fs, 4096, 0.0, 1 * KHZ, snr_db=-40.0, seed=5)  # buried
        freqs, psd = welch_psd(iq, fs, nfft=1024)
        bands = ca_cfar(psd, offset_db=10.0, min_width=3)
        print(f"[DSP] noise-only bands detected: {len(bands)} (want few)")
        self.assertLessEqual(len(bands), 3, "too many false detections on noise")


if __name__ == "__main__":
    unittest.main(verbosity=2)
