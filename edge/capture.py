"""IQ capture (spec sec 5, step 1).

Production: SoapySDR / KrakenSDR Heimdall DAQ yields coherent IQ blocks per
channel. MVP: a synthetic source stands in so the node loop is exercisable with
no hardware. The interface is a callable returning (iq, fs, tuner_center_hz).
"""

from __future__ import annotations

from typing import Callable, List, Tuple

from .simulate import synth_iq

CaptureFn = Callable[[], Tuple[List[complex], float, float]]


def synthetic_source(tuner_center_hz: float, fs: float = 2_400_000.0,
                     nsamp: int = 4096, offset_hz: float = 6_000.0,
                     bw_hz: float = 25_000.0, snr_db: float = 18.0,
                     seed: int = 7) -> CaptureFn:
    """A capture function that returns one planted-signal IQ block per call."""
    def _cap() -> Tuple[List[complex], float, float]:
        iq = synth_iq(fs, nsamp, offset_hz, bw_hz, snr_db, seed=seed)
        return iq, fs, tuner_center_hz
    return _cap


def krakensdr_source(*_args, **_kwargs) -> CaptureFn:  # pragma: no cover
    """Placeholder for the real Heimdall DAQ capture (v0 hardware path)."""
    raise NotImplementedError(
        "KrakenSDR capture requires the Heimdall DAQ / SoapySDR runtime; "
        "use synthetic_source() for the hardware-free MVP.")
