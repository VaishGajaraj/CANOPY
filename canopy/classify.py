"""Rule-based emitter classifier — the closed asset (spec sec 5, sec 12).

No learned model: rules first, because there is no labelled data yet and the
field captures you collect *are* the training set later (v1). The rule table is
keyed on band membership + bandwidth + burst/duty, covering the six v0 emitter
types. It returns a type and a calibrated-ish confidence from how cleanly the
feature vector lands inside a rule's box.

KC-2 (spec sec 9) tests this table's separability on noisy field-like features;
the goal is >= ~80% correct before the after-action report's per-emitter claims
can be called honest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

MHZ = 1_000_000.0
KHZ = 1_000.0

# GPS L1 — a *quiet* band. Energy here is an anomaly (jamming/interference),
# which is arguably a second wedge on its own (spec sec 2, sec 11).
GPS_L1_HZ = 1_575_420_000.0


@dataclass(frozen=True)
class Rule:
    emitter_type: str
    f_lo: float          # band edge (Hz)
    f_hi: float
    bw_lo: float         # occupied bandwidth window (Hz)
    bw_hi: float
    duty_lo: float       # duty-cycle window (0..1)
    duty_hi: float
    note: str = ""


# Ordered most-specific first. Native RTL-SDR coverage is VHF/UHF/cellular/GPS;
# bt_region (2.4 GHz) needs the v1 HackRF wideband front-end and is kept here
# for schema completeness (spec sec 2 vs sec 5).
RULES: List[Rule] = [
    Rule("tac_vhf",  30 * MHZ,   88 * MHZ,   8 * KHZ,   50 * KHZ,  0.02, 0.55,
         "SINCGARS-class VHF combat net, narrowband bursty FM"),
    Rule("tac_uhf",  225 * MHZ,  450 * MHZ,  8 * KHZ,   50 * KHZ,  0.02, 0.55,
         "UHF tactical / SATCOM uplink, narrowband bursty"),
    Rule("cellular", 700 * MHZ,  915 * MHZ,  180 * KHZ, 10 * MHZ,  0.15, 1.0,
         "cellular uplink (LTE/5G FR1 low band)"),
    Rule("cellular", 1_710 * MHZ, 1_785 * MHZ, 180 * KHZ, 20 * MHZ, 0.15, 1.0,
         "cellular uplink (AWS/PCS)"),
    Rule("gps_anomaly", GPS_L1_HZ - 6 * MHZ, GPS_L1_HZ + 6 * MHZ, 1 * MHZ, 40 * MHZ, 0.4, 1.0,
         "elevated energy in the GPS L1 band -> probable jamming/interference"),
    Rule("bt_region", 2_400 * MHZ, 2_483 * MHZ, 900 * KHZ, 2 * MHZ, 0.001, 0.5,
         "2.4 GHz ISM frequency-hopping region (needs v1 HackRF front-end)"),
]

# Catch-all for wide occupied bands that match no specific rule.
WIDEBAND_BW = 5 * MHZ


def _score_rule(rule: Rule, center_hz: float, bw_hz: float, duty: float) -> float:
    """0..1 membership score: 1 dead-centre, decaying to 0 at the box edges."""
    if not (rule.f_lo <= center_hz <= rule.f_hi):
        return 0.0

    def band_pos(v: float, lo: float, hi: float) -> float:
        if hi <= lo:
            return 1.0 if abs(v - lo) < 1e-9 else 0.0
        if v < lo or v > hi:
            # soft margin: allow 25% overshoot with linear falloff
            span = hi - lo
            if v < lo:
                return max(0.0, 1.0 - (lo - v) / (0.25 * span))
            return max(0.0, 1.0 - (v - hi) / (0.25 * span))
        # inside: 1.0 at centre, 0.6 at the edges
        mid = 0.5 * (lo + hi)
        half = 0.5 * (hi - lo)
        return 1.0 - 0.4 * (abs(v - mid) / half)

    bw_s = band_pos(bw_hz, rule.bw_lo, rule.bw_hi)
    duty_s = band_pos(duty, rule.duty_lo, rule.duty_hi)
    if bw_s == 0.0 or duty_s == 0.0:
        return 0.0
    # in-band frequency membership counts too, but weakly (bands are wide)
    return 0.15 + 0.85 * (0.5 * bw_s + 0.5 * duty_s)


def classify(center_hz: float, bw_hz: float, burst_ms: float, duty: float
             ) -> Tuple[str, float]:
    """Return (emitter_type, confidence in 0..1)."""
    best_type = "wideband"
    best_score = 0.0
    for rule in RULES:
        s = _score_rule(rule, center_hz, bw_hz, duty)
        if s > best_score:
            best_score = s
            best_type = rule.emitter_type

    if best_score <= 0.0:
        # Nothing matched a specific rule. A very wide band is 'wideband';
        # otherwise it is an unknown narrow emitter we still flag as wideband
        # at low confidence (honest: we don't know what it is).
        if bw_hz >= WIDEBAND_BW:
            return "wideband", 0.55
        return "wideband", 0.30

    return best_type, round(min(0.99, best_score), 3)


def emitter_types() -> List[str]:
    seen = []
    for r in RULES:
        if r.emitter_type not in seen:
            seen.append(r.emitter_type)
    seen.append("wideband")
    return seen
