"""End-to-end demo — the whole platform, headless, no hardware, no installs.

Runs: simulate 4 passive nodes auditing a friendly rifle company -> ingest
detections -> associate + geolocate (with honest error ellipses) -> upsert the
signature library -> add a NISAR SAR patch through the SAME door -> build the
after-action report with the targetability score -> emit sample CoT.

    python3 scripts/demo.py            # print the after-action report
    python3 scripts/demo.py --json     # dump the full report as JSON
    python3 scripts/demo.py --serve    # load the store, then start the live UI
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canopy.geo import LatLon
from canopy.models import CriticalWindow, Exercise, Source
from canopy.pipeline import Pipeline
from canopy.propagation import PropagationModel
from canopy.store import Store
from edge.simulate import World, default_scenario
from nisar import worker as nisar_worker

# Semi-open training-area path loss, shared by the detection sim and the score's
# range term so both reason from the same documented assumptions.
PROP = PropagationModel(path_loss_exponent=3.1, adversary_sensitivity_dbm=-112.0)

T0 = datetime(2026, 7, 2, 13, 0, 0, tzinfo=timezone.utc)


def build() -> "tuple[Store, Pipeline, str]":
    store = Store()
    pipeline = Pipeline(store, prop=PROP)

    nodes, emitters, cfg = default_scenario(T0)
    cfg.t0 = T0

    # Exercise with the assault as the critical phase (1200-1500 s).
    ex = Exercise(
        name="EXERCISE TALON GUARD 26-3",
        unit="A Co, 1-505 IN",
        started_at=T0,
        critical_windows=[CriticalWindow(
            label="Assault",
            start=T0.replace() + _delta(1200),
            end=T0.replace() + _delta(1500),
        )],
    )
    store.add_exercise(ex)

    # Register nodes as Sources; map sim labels -> Source ids.
    label_to_id = {}
    for n in nodes:
        s = Source(label=n.label, source_int="rf", lat=n.lat, lon=n.lon,
                   calibration={"df_sigma_deg": n.df_sigma_deg,
                                "sensitivity_dbm": n.sensitivity_dbm})
        store.add_source(s)
        label_to_id[n.label] = s.id

    # Run the world and ingest every node report.
    world = World(nodes, emitters, cfg, prop=PROP)
    reports = world.run()
    for node_label, rep in reports:
        rep.node_id = label_to_id[node_label]
        pipeline.ingest(rep, ex.id)

    # Fuse bearings into fixes with error ellipses.
    pipeline.fuse(ex.id)

    # Multi-INT proof: NISAR SAR patch into the SAME detections table.
    nisar_worker.run(pipeline, ex.id, LatLon(35.1300, -79.0000), observed_at=T0,
                     seed=99)

    return store, pipeline, ex.id


def _delta(seconds: float):
    from datetime import timedelta
    return timedelta(seconds=seconds)


def print_report(report: dict) -> None:
    R = report
    line = "=" * 66
    print(line)
    print(f"AFTER-ACTION REPORT  —  {R['exercise']}")
    if R.get("unit"):
        print(f"Unit: {R['unit']}")
    w = R["window"]
    print(f"Window: {w['start']}  ->  {w['end']}  ({w['duration_s']:.0f} s)")
    print(line)
    print(f"\n  TARGETABILITY SCORE:  {R['targetability_score']:.1f} / 100")
    if R.get("worst"):
        print(f"  Worst offender:       {R['worst']['label']}  "
              f"({R['worst']['score']:.1f})")
    c = R["counts"]
    print(f"\n  Detections: {c['detections']}  "
          f"(RF {c['rf_detections']} / SAR {c['sar_detections']})   "
          f"Fixes: {c['fixes']}   Signatures: {c['signatures']}")
    print(f"  Multi-INT source_ints in library: {R['multi_int']['source_ints']}")

    print("\n  WORST OFFENDERS (ranked)")
    print("  " + "-" * 62)
    hdr = f"  {'emitter':<26}{'score':>6}{'pers':>6}{'range':>7}{'phase':>7}{'fix ellipse':>16}"
    print(hdr)
    for o in R["worst_offenders"]:
        fix = o.get("best_fix")
        if fix:
            ell = f"{fix['err_semimajor_m']:.0f}x{fix['err_semiminor_m']:.0f}m"
            cep = f" CEP{fix['cep50_m']:.0f}"
        else:
            ell, cep = "(no fix)", ""
        name = o["label"][:26]
        print(f"  {name:<26}{o['score']:>6.1f}{o['persistence']:>6.2f}"
              f"{o['range_term']:>7.2f}{o['phase']:>7.2f}{ell:>16}{cep}")

    pw = R["peak_window"]
    print(f"\n  Peak-detectability window: {pw['start']} -> {pw['end']}")
    m = R["methodology"]
    print(f"\n  Score methodology: {m['formula']}")
    print(f"    weights={m['weights']}  range_band_m={m['range_band_m']}")
    print(f"    exercise blend: {m['exercise_blend']}")
    print(f"    caveat: {m['caveat']}")
    print("\n" + line)


def main() -> int:
    store, pipeline, ex_id = build()
    report = pipeline.report(ex_id)

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print_report(report)

    # a sample CoT event so the TAK path is visible
    cots = pipeline.cot_events(ex_id)
    if cots:
        print("\nSample CoT event (pushed to TAK / ATAK):\n")
        print(cots[0])

    if "--serve" in sys.argv:
        from canopy.server import serve
        print("\nStarting live UI at http://127.0.0.1:8787 ...")
        serve(store, pipeline, ex_id, host="127.0.0.1", port=8787)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
