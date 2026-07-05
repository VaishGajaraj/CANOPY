"""Minimal DSP — radix-2 FFT and Welch PSD, pure stdlib (spec sec 5).

The spec says: "Start GNU-Radio-free; numpy/scipy is easier to reason about and
sufficient for energy detection." We go one step further for the MVP and stay
numpy-free so the whole chain runs anywhere. Blocks are small (<=4096), so a
pure-Python iterative FFT is plenty fast for energy detection and keeps the
signal path genuine end-to-end.
"""

from __future__ import annotations

import cmath
import math
from typing import List, Sequence, Tuple


def _next_pow2(n: int) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p


def fft(x: Sequence[complex]) -> List[complex]:
    """Iterative radix-2 Cooley-Tukey FFT. Input is zero-padded to a power of 2."""
    n0 = len(x)
    n = _next_pow2(n0)
    a: List[complex] = [complex(v) for v in x] + [0j] * (n - n0)

    # bit-reversal permutation
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]

    length = 2
    while length <= n:
        ang = -2j * math.pi / length
        wlen = cmath.exp(ang)
        half = length >> 1
        for i in range(0, n, length):
            w = 1 + 0j
            for k in range(half):
                u = a[i + k]
                v = a[i + k + half] * w
                a[i + k] = u + v
                a[i + k + half] = u - v
                w *= wlen
        length <<= 1
    return a


def _hann(n: int) -> List[float]:
    if n == 1:
        return [1.0]
    return [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]


def welch_psd(iq: Sequence[complex], fs: float, nfft: int = 1024,
              overlap: float = 0.5) -> Tuple[List[float], List[float]]:
    """Welch PSD of a complex baseband block.

    Returns (freqs_hz, psd_db) with freqs centred on 0 (baseband), i.e.
    -fs/2 .. +fs/2. psd_db is 10*log10(power), un-normalised but consistent so
    CFAR (which is noise-floor-relative) works fine.
    """
    n = len(iq)
    nfft = min(nfft, _next_pow2(n)) if n < nfft else nfft
    win = _hann(nfft)
    win_pow = sum(w * w for w in win)
    step = max(1, int(nfft * (1 - overlap)))

    accum = [0.0] * nfft
    segs = 0
    for start in range(0, max(1, n - nfft + 1), step):
        seg = iq[start:start + nfft]
        if len(seg) < nfft:
            break
        wseg = [seg[i] * win[i] for i in range(nfft)]
        spec = fft(wseg)
        for i in range(nfft):
            accum[i] += (spec[i].real ** 2 + spec[i].imag ** 2)
        segs += 1
    if segs == 0:
        # single short segment fallback
        seg = list(iq) + [0j] * (nfft - n)
        wseg = [seg[i] * win[i] for i in range(nfft)]
        spec = fft(wseg)
        for i in range(nfft):
            accum[i] += (spec[i].real ** 2 + spec[i].imag ** 2)
        segs = 1

    scale = 1.0 / (segs * fs * win_pow + 1e-30)
    # fftshift so DC is centred
    half = nfft // 2
    order = list(range(half, nfft)) + list(range(0, half))
    freqs = [(k - half) * fs / nfft for k in range(nfft)]
    psd_db = []
    for k in order:
        p = accum[k] * scale
        psd_db.append(10.0 * math.log10(p + 1e-30))
    return freqs, psd_db
