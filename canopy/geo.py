"""Geodesy and small-matrix linear algebra — pure stdlib.

Everything the geolocation kill-criterion (KC-1) needs lives here:

* a local tangent-plane projection good to a few km (training-area scale),
* least-squares intersection of >=2 lines of bearing (LOBs),
* an *honest* error ellipse from inverse-variance weighting.

No numpy — the matrices are 2x2, so closed form is clearer and has no deps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# WGS84 mean-ish earth radius. At training-area scales the ellipsoid vs sphere
# error is well under the metre level we care about here.
_R_EARTH_M = 6_378_137.0
_DEG = math.pi / 180.0

# Chi-square (2 dof) scale factors from 1-sigma ellipse to a confidence radius.
CHI2_2DOF = {
    0.50: 1.1774,   # ~CEP-ish
    0.90: 2.1460,
    0.95: 2.4477,
    0.99: 3.0349,
}


@dataclass(frozen=True)
class LatLon:
    lat: float
    lon: float


class TangentPlane:
    """Equirectangular tangent plane centred on an origin.

    x = east metres, y = north metres. Exact enough for the few-km spans of a
    training area; do not use it for theatre-scale geometry.
    """

    def __init__(self, origin: LatLon):
        self.origin = origin
        self._coslat0 = math.cos(origin.lat * _DEG)

    def to_xy(self, p: LatLon) -> Tuple[float, float]:
        x = (p.lon - self.origin.lon) * _DEG * _R_EARTH_M * self._coslat0
        y = (p.lat - self.origin.lat) * _DEG * _R_EARTH_M
        return x, y

    def to_latlon(self, x: float, y: float) -> LatLon:
        lat = self.origin.lat + (y / (_R_EARTH_M * _DEG))
        lon = self.origin.lon + (x / (_R_EARTH_M * _DEG * self._coslat0))
        return LatLon(lat, lon)


def bearing_unit(az_deg: float) -> Tuple[float, float]:
    """Unit direction (east, north) for an azimuth clockwise from true north."""
    a = az_deg * _DEG
    return math.sin(a), math.cos(a)


def haversine_m(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in metres (used for ground-truth error checks)."""
    dlat = (b.lat - a.lat) * _DEG
    dlon = (b.lon - a.lon) * _DEG
    la1 = a.lat * _DEG
    la2 = b.lat * _DEG
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * _R_EARTH_M * math.asin(min(1.0, math.sqrt(h)))


# --- 2x2 linear algebra (a,b / b,c is symmetric; general 2x2 for solve) -----

def _solve2(m: Sequence[Sequence[float]], v: Sequence[float]) -> Optional[Tuple[float, float]]:
    (a, b), (c, d) = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        return None
    return ((v[0] * d - b * v[1]) / det, (a * v[1] - c * v[0]) / det)


def _inv2_sym(a: float, b: float, c: float) -> Optional[Tuple[float, float, float]]:
    det = a * c - b * b
    if abs(det) < 1e-18:
        return None
    return (c / det, -b / det, a / det)


def eig2_sym(a: float, b: float, c: float) -> Tuple[float, float, float]:
    """Eigen-decompose symmetric [[a,b],[b,c]].

    Returns (lambda_major, lambda_minor, orient_deg) where orient_deg is the
    azimuth (clockwise from north) of the major axis.
    """
    tr = a + c
    disc = math.sqrt(max(0.0, (0.5 * (a - c)) ** 2 + b * b))
    lam1 = 0.5 * tr + disc  # major
    lam2 = 0.5 * tr - disc  # minor
    # Eigenvector for lam1.
    if abs(b) > 1e-15:
        ex, ey = (lam1 - c, b)
    elif a >= c:
        ex, ey = (1.0, 0.0)
    else:
        ex, ey = (0.0, 1.0)
    # ex is the east component, ey the north component -> azimuth from north.
    orient = math.degrees(math.atan2(ex, ey)) % 180.0
    return lam1, lam2, orient


@dataclass
class LOB:
    """A line of bearing from a node."""
    x: float            # node east (m)
    y: float            # node north (m)
    az_deg: float       # azimuth clockwise from north
    sigma_az_deg: float  # 1-sigma angular uncertainty (deg)


@dataclass
class Fix:
    x: float
    y: float
    err_semimajor_m: float   # 1-sigma
    err_semiminor_m: float   # 1-sigma
    err_orient_deg: float
    residual_m: float        # RMS perpendicular residual of LOBs to the fix
    n_lobs: int
    gdop: float              # geometric dilution: semimajor / mean cross-range sigma


def intersect_lobs(lobs: Sequence[LOB], iters: int = 3) -> Optional[Fix]:
    """Inverse-variance-weighted least-squares intersection of >=2 LOBs.

    Each LOB constrains the fix to lie on its line; we minimise the sum of
    weighted squared perpendicular distances. Weights are 1/sigma_perp^2 where
    sigma_perp = range * sin(sigma_az) is the cross-range spread at that node —
    a distant node with a tight bearing pins the fix, a near node with a loose
    bearing barely does. The covariance of that estimate IS the error ellipse.
    """
    if len(lobs) < 2:
        return None

    # Unweighted seed so we can compute per-node ranges for the weights.
    est = _weighted_solve(lobs, weights=[1.0] * len(lobs))
    if est is None:
        return None

    for _ in range(iters):
        weights = []
        for lob in lobs:
            rng = math.hypot(est[0] - lob.x, est[1] - lob.y)
            rng = max(rng, 1.0)
            sigma_perp = max(rng * math.sin(lob.sigma_az_deg * _DEG), 0.5)
            weights.append(1.0 / (sigma_perp * sigma_perp))
        nxt = _weighted_solve(lobs, weights)
        if nxt is None:
            break
        if math.hypot(nxt[0] - est[0], nxt[1] - est[1]) < 1e-3:
            est = nxt
            break
        est = nxt

    x, y = est

    # Covariance = (sum w_i P_i)^-1 with the final weights.
    saa = sbb = sab = 0.0
    resid_sq = 0.0
    cross_sigmas = []
    for lob in lobs:
        dx, dy = bearing_unit(lob.az_deg)
        # Perpendicular projector P = I - d d^T -> [[1-dx^2, -dx dy],[-dx dy, 1-dy^2]]
        rng = max(math.hypot(x - lob.x, y - lob.y), 1.0)
        sigma_perp = max(rng * math.sin(lob.sigma_az_deg * _DEG), 0.5)
        cross_sigmas.append(sigma_perp)
        w = 1.0 / (sigma_perp * sigma_perp)
        saa += w * (1 - dx * dx)
        sbb += w * (1 - dy * dy)
        sab += w * (-dx * dy)
        # perpendicular residual of the fix to this LOB
        rx, ry = x - lob.x, y - lob.y
        perp = rx * (1 - dx * dx) * rx + 2 * rx * (-dx * dy) * ry + ry * (1 - dy * dy) * ry
        resid_sq += max(perp, 0.0)

    cov = _inv2_sym(saa, sab, sbb)
    if cov is None:
        return None
    cxx, cxy, cyy = cov
    lam1, lam2, orient = eig2_sym(cxx, cxy, cyy)
    semimajor = math.sqrt(max(lam1, 0.0))
    semiminor = math.sqrt(max(lam2, 0.0))
    residual = math.sqrt(resid_sq / len(lobs))
    mean_cross = sum(cross_sigmas) / len(cross_sigmas)
    gdop = semimajor / mean_cross if mean_cross > 0 else float("inf")

    return Fix(
        x=x, y=y,
        err_semimajor_m=semimajor,
        err_semiminor_m=semiminor,
        err_orient_deg=orient,
        residual_m=residual,
        n_lobs=len(lobs),
        gdop=gdop,
    )


def _weighted_solve(lobs: Sequence[LOB], weights: Sequence[float]) -> Optional[Tuple[float, float]]:
    saa = sbb = sab = 0.0
    bx = by = 0.0
    for lob, w in zip(lobs, weights):
        dx, dy = bearing_unit(lob.az_deg)
        p00 = 1 - dx * dx
        p01 = -dx * dy
        p11 = 1 - dy * dy
        saa += w * p00
        sab += w * p01
        sbb += w * p11
        # (P p) accumulation for RHS = sum w P_i p_i
        bx += w * (p00 * lob.x + p01 * lob.y)
        by += w * (p01 * lob.x + p11 * lob.y)
    return _solve2([[saa, sab], [sab, sbb]], [bx, by])


def ellipse_to_cep(semimajor_m: float, semiminor_m: float) -> float:
    """Approximate 50% circular error probable from a 1-sigma ellipse.

    Uses the standard near-circular approximation CEP ~= 0.75*(sx+sy)/... we use
    the widely cited CEP ~= 0.59*(sigma_major + sigma_minor) which is accurate
    to a few percent for aspect ratios up to ~3:1.
    """
    return 0.59 * (semimajor_m + semiminor_m)
