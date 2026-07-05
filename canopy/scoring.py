"""Targetability score — the credibility hinge (spec sec 7, sec 11).

A single 0-100 number is what makes the after-action report demoable AND what a
skeptical S2 will attack ("72 out of what?"). So the formula is defined here, in
code, and echoed verbatim into the report. If the score were a black box it
would read as theatre.

PER-EMITTER SCORE (0-100)
  score = 100 * (W_PERSIST * persistence + W_RANGE * range_term + W_PHASE * phase)

  persistence  = clamp(duty * activity_fraction, 0, 1)
                 duty            : mean transmit duty cycle of the emitter
                 activity_fraction: fraction of the exercise it was ever active
                 -> something that keys up constantly scores high; a
                    disciplined burst-and-move emitter scores low.

  range_term   = clamp(log10(det_range / R_MIN) / log10(R_MAX / R_MIN), 0, 1)
                 det_range : adversary detection radius from propagation.py
                 R_MIN,R_MAX: the range band we map onto 0..1 (documented)
                 -> a loud, far-detectable emitter is more targetable.

  phase        = fraction of the exercise's CRITICAL windows (e.g. the assault)
                 during which the emitter was radiating
                 -> radiating during the assault is the cardinal sin; a radio
                    that only talks in the assembly area scores low here.

Weights (documented, tunable per customer): persistence 0.35, range 0.30,
phase 0.35. They sum to 1 so the score is a clean 0-100.

EXERCISE SCORE
  A blend that refuses to hide a single catastrophic emitter behind many quiet
  ones: 0.5 * (worst emitter) + 0.5 * (mean of all emitters). Reported alongside
  the worst-offenders list so the number is never divorced from its drivers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .propagation import NOMINAL_EIRP_DBM, PropagationModel

W_PERSIST = 0.35
W_RANGE = 0.30
W_PHASE = 0.35

R_MIN_M = 200.0     # below this detection radius, range term -> 0
R_MAX_M = 20_000.0  # at/above this, range term -> 1


import math


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def range_term(det_range_m: float) -> float:
    if det_range_m <= R_MIN_M:
        return 0.0
    return _clamp(math.log10(det_range_m / R_MIN_M) / math.log10(R_MAX_M / R_MIN_M))


@dataclass
class EmitterScore:
    key: str
    emitter_type: str
    label: str
    persistence: float
    range_term: float
    phase: float
    det_range_m: float
    duty: float
    activity_fraction: float
    n_detections: int
    score: float
    drivers: Dict[str, float] = field(default_factory=dict)


@dataclass
class ExerciseScore:
    overall: float
    worst: Optional[EmitterScore]
    per_emitter: List[EmitterScore]
    methodology: Dict[str, object]


@dataclass
class EmitterActivity:
    """Aggregated per-emitter evidence the scorer consumes."""
    key: str
    emitter_type: str
    label: str
    duty_mean: float
    first_seen: datetime
    last_seen: datetime
    eirp_dbm: float
    center_hz: float
    n_detections: int
    # fraction of critical windows during which this emitter radiated
    critical_hit_fraction: float


def score_emitter(act: EmitterActivity, exercise_span_s: float,
                  prop: PropagationModel) -> EmitterScore:
    activity_fraction = 0.0
    if exercise_span_s > 0:
        span = (act.last_seen - act.first_seen).total_seconds()
        activity_fraction = _clamp(span / exercise_span_s)
    persistence = _clamp(act.duty_mean * (0.5 + 0.5 * activity_fraction))

    det_range = prop.detection_range_m(act.eirp_dbm, act.center_hz)
    rng = range_term(det_range)
    phase = _clamp(act.critical_hit_fraction)

    score = 100.0 * (W_PERSIST * persistence + W_RANGE * rng + W_PHASE * phase)
    return EmitterScore(
        key=act.key,
        emitter_type=act.emitter_type,
        label=act.label,
        persistence=round(persistence, 3),
        range_term=round(rng, 3),
        phase=round(phase, 3),
        det_range_m=round(det_range, 1),
        duty=round(act.duty_mean, 3),
        activity_fraction=round(activity_fraction, 3),
        n_detections=act.n_detections,
        score=round(score, 1),
        drivers={
            "persistence_x_w": round(W_PERSIST * persistence, 3),
            "range_x_w": round(W_RANGE * rng, 3),
            "phase_x_w": round(W_PHASE * phase, 3),
        },
    )


def score_exercise(activities: List[EmitterActivity], exercise_span_s: float,
                   prop: Optional[PropagationModel] = None) -> ExerciseScore:
    prop = prop or PropagationModel()
    per = [score_emitter(a, exercise_span_s, prop) for a in activities]
    per.sort(key=lambda e: e.score, reverse=True)
    if per:
        worst = per[0]
        mean = sum(e.score for e in per) / len(per)
        overall = round(0.5 * worst.score + 0.5 * mean, 1)
    else:
        worst = None
        overall = 0.0
    return ExerciseScore(
        overall=overall,
        worst=worst,
        per_emitter=per,
        methodology={
            "formula": "100 * (0.35*persistence + 0.30*range + 0.35*phase)",
            "weights": {"persistence": W_PERSIST, "range": W_RANGE, "phase": W_PHASE},
            "range_band_m": {"R_MIN": R_MIN_M, "R_MAX": R_MAX_M},
            "exercise_blend": "0.5*worst + 0.5*mean",
            "propagation": {
                "path_loss_exponent": prop.path_loss_exponent,
                "adversary_sensitivity_dbm": prop.adversary_sensitivity_dbm,
            },
            "nominal_eirp_dbm": NOMINAL_EIRP_DBM,
            "caveat": "EIRP and adversary sensitivity are documented assumptions, "
                      "not measurements; the score ranks relative detectability, "
                      "it is not a probability of being killed.",
        },
    )
