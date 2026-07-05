"""Synthetic RF world — friendly-unit emitters seen by passive nodes.

Produces a timeline of NodeReports. Bearings are computed from real
node->emitter geometry plus each node's DF angular noise; feature measurements
(center/bw/duty) carry explicit measurement error. Emitter *type* is recovered
by the real classifier, so the same rule table the KC-2 test scores is in the
loop here.

Also provides synth_iq(): a genuine complex-baseband generator used by the DSP
demonstration and test, so the FFT -> Welch -> CFAR -> features path is proven
on planted signals, not asserted.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from canopy.classify import GPS_L1_HZ, classify
from canopy.geo import LatLon, TangentPlane, haversine_m
from canopy.pipeline import NodeReport
from canopy.propagation import NOMINAL_EIRP_DBM, PropagationModel

MHZ = 1_000_000.0
KHZ = 1_000.0


@dataclass
class SimEmitter:
    label: str
    emitter_type: str
    lat: float
    lon: float
    center_hz: float
    bw_hz: float
    duty: float                      # base transmit duty when active
    active_windows: List[Tuple[float, float]]  # (start_s, end_s) rel to t0
    eirp_dbm: float = 40.0
    owner: str = ""                  # which element owns this emitter

    def is_active(self, t_s: float) -> bool:
        return any(a <= t_s <= b for a, b in self.active_windows)


@dataclass
class SimNode:
    label: str
    lat: float
    lon: float
    df_sigma_deg: float = 4.0        # this node's direction-finding accuracy
    sensitivity_dbm: float = -112.0


@dataclass
class SimConfig:
    t0: datetime
    duration_s: float = 1800.0       # 30-minute exercise
    step_s: float = 10.0
    seed: int = 1234


def true_bearing_deg(node: SimNode, em: SimEmitter) -> float:
    """Azimuth clockwise from north, node -> emitter."""
    plane = TangentPlane(LatLon(node.lat, node.lon))
    x, y = plane.to_xy(LatLon(em.lat, em.lon))
    return math.degrees(math.atan2(x, y)) % 360.0


def received_power_dbm(em: SimEmitter, node: SimNode, prop: PropagationModel) -> float:
    d = max(haversine_m(LatLon(node.lat, node.lon), LatLon(em.lat, em.lon)), 1.0)
    pl_ref = prop.fspl_db(em.center_hz, prop.ref_distance_m)
    return em.eirp_dbm - pl_ref - 10 * prop.path_loss_exponent * math.log10(
        d / prop.ref_distance_m)


class World:
    def __init__(self, nodes: List[SimNode], emitters: List[SimEmitter],
                 cfg: SimConfig, prop: Optional[PropagationModel] = None) -> None:
        self.nodes = nodes
        self.emitters = emitters
        self.cfg = cfg
        self.prop = prop or PropagationModel()
        self.rng = random.Random(cfg.seed)

    def run(self) -> List[Tuple[str, NodeReport]]:
        """Return (node_id_label, NodeReport) pairs across the timeline.

        node_id_label is the node label; the caller maps it to a Source id.
        """
        out: List[Tuple[str, NodeReport]] = []
        n_steps = int(self.cfg.duration_s / self.cfg.step_s)
        for k in range(n_steps):
            t_s = k * self.cfg.step_s
            when = self.cfg.t0 + timedelta(seconds=t_s)
            for em in self.emitters:
                if not em.is_active(t_s):
                    continue
                # per-step keying: not every active step transmits (duty)
                if self.rng.random() > em.duty:
                    continue
                for node in self.nodes:
                    rp = received_power_dbm(em, node, self.prop)
                    if rp < node.sensitivity_dbm:
                        continue  # below this node's noise floor -> not heard
                    snr = rp - node.sensitivity_dbm
                    out.append((node.label, self._measure(em, node, when, snr)))
        return out

    def _measure(self, em: SimEmitter, node: SimNode, when: datetime,
                 snr_db: float) -> NodeReport:
        rng = self.rng
        # measurement noise on features
        center = em.center_hz + rng.gauss(0, 2 * KHZ)
        bw = max(em.bw_hz * (1 + rng.gauss(0, 0.08)), 1 * KHZ)
        duty_meas = min(1.0, max(0.001, em.duty + rng.gauss(0, 0.04)))
        burst_ms = max(1.0, 40.0 * (1 + rng.gauss(0, 0.15)))
        # DF error shrinks with SNR: sigma_eff = sigma / sqrt(snr_linear-ish)
        snr_gain = max(1.0, (snr_db / 12.0))
        sigma_eff = node.df_sigma_deg / math.sqrt(snr_gain)
        bearing = (true_bearing_deg(node, em) + rng.gauss(0, sigma_eff)) % 360.0

        etype, conf = classify(center, bw, burst_ms, duty_meas)
        return NodeReport(
            node_id=node.label,          # remapped to Source id by caller
            observed_at=when,
            center_hz=center,
            bw_hz=bw,
            burst_ms=burst_ms,
            duty=duty_meas,
            bearing_deg=bearing,
            emitter_type=etype,
            confidence=conf,
            bearing_sigma_deg=round(sigma_eff, 2),
            snr_db=round(snr_db, 1),
        )


# --- genuine IQ synthesis for the DSP demonstration -------------------------

def synth_iq(fs: float, n: int, center_offset_hz: float, bw_hz: float,
             snr_db: float, seed: int = 7) -> List[complex]:
    """Complex baseband: an occupied band of width bw_hz centred at
    center_offset_hz, plus complex AWGN scaled to snr_db.
    """
    rng = random.Random(seed)
    n_tones = max(3, int(bw_hz / (fs / n)) // 4 + 3)
    amp = 10 ** (snr_db / 20.0)
    tones = []
    for i in range(n_tones):
        f = center_offset_hz + (i / max(1, n_tones - 1) - 0.5) * bw_hz
        ph = rng.random() * 2 * math.pi
        tones.append((f, ph))
    iq: List[complex] = []
    for k in range(n):
        s = 0j
        for f, ph in tones:
            s += cmath_exp(2 * math.pi * f * k / fs + ph)
        s *= amp / math.sqrt(n_tones)
        noise = complex(rng.gauss(0, 0.7071), rng.gauss(0, 0.7071))
        iq.append(s + noise)
    return iq


def cmath_exp(theta: float) -> complex:
    return complex(math.cos(theta), math.sin(theta))


# --- a canned, representative friendly-unit scenario ------------------------

def default_scenario(t0: datetime) -> Tuple[List[SimNode], List[SimEmitter], SimConfig]:
    """A rifle company in a training-area defence, plus a GPS-jamming event.

    Node geometry surrounds the unit's AO; emitters model realistic EMCON
    discipline (and the lack of it). The assault window is 1200-1500 s.
    """
    # AO centre (synthetic training area)
    base = LatLon(35.1300, -79.0000)
    plane = TangentPlane(base)

    def at(east_m: float, north_m: float) -> Tuple[float, float]:
        ll = plane.to_latlon(east_m, north_m)
        return ll.lat, ll.lon

    # Passive nodes ringing the friendly AO at ~1.3-1.6 km with good angular
    # spread (low GDOP). This is a friendly emissions audit, so nodes can sit
    # inside/around the unit's own area.
    nodes = [
        SimNode("node-N", *at(50, 1450), df_sigma_deg=3.5),
        SimNode("node-E", *at(1450, -150), df_sigma_deg=4.0),
        SimNode("node-S", *at(-150, -1500), df_sigma_deg=4.5),
        SimNode("node-W", *at(-1500, 350), df_sigma_deg=4.0),
    ]

    assault = [(1200.0, 1500.0)]
    emitters = [
        # Command post VHF net — chatty, up the whole exercise incl. assault.
        SimEmitter("CP VHF net", "tac_vhf", *at(-150, 120),
                   center_hz=51.5 * MHZ, bw_hz=25 * KHZ, duty=0.42,
                   active_windows=[(0.0, 1800.0)], eirp_dbm=44.0,
                   owner="HQ / CP"),
        # 1st platoon UHF — disciplined, bursts, mostly early.
        SimEmitter("1PLT UHF", "tac_uhf", *at(600, -300),
                   center_hz=385.0 * MHZ, bw_hz=25 * KHZ, duty=0.10,
                   active_windows=[(0.0, 900.0), (1200.0, 1350.0)], eirp_dbm=40.0,
                   owner="1st Platoon"),
        # A soldier's personal phone left on — cellular uplink, incl. assault.
        # At a rural training area with poor coverage the handset transmits at
        # max uplink power (~1 W / 30 dBm), which is what makes it detectable.
        SimEmitter("Pers. cell (uplink)", "cellular", *at(-40, -260),
                   center_hz=1_745.0 * MHZ, bw_hz=9 * MHZ, duty=0.30,
                   active_windows=[(300.0, 1800.0)], eirp_dbm=30.0,
                   owner="2nd Platoon (unauthorised device)"),
        # GPS jamming event during the assault (detected as L1 anomaly).
        SimEmitter("GPS L1 anomaly", "gps_anomaly", *at(250, -650),
                   center_hz=GPS_L1_HZ, bw_hz=20 * MHZ, duty=0.95,
                   active_windows=assault, eirp_dbm=50.0,
                   owner="OPFOR jammer (detected)"),
    ]
    cfg = SimConfig(t0=t0, duration_s=1800.0, step_s=10.0, seed=20260702)
    return nodes, emitters, cfg
