"""Stateful K-weighting (ITU-R BS.1770-4) and true-peak (Annex 2) filters.

Both classes process blocks shaped ``(frames, channels)`` and carry their
filter state across calls so a continuous stream can be fed block by block.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import firwin, lfilter


def k_weighting_coefficients(fs: float):
    """Return ((b1, a1), (b2, a2)) for the two K-weighting biquads at ``fs``.

    Stage 1 is the high-frequency shelf, stage 2 the RLB high-pass. The
    analog prototype parameters reproduce the BS.1770-4 table at 48 kHz
    and give the correct response at any other rate.
    """
    # Stage 1: high shelf, +4 dB above ~1.5 kHz
    f0 = 1681.974450955533
    gain_db = 3.999843853973347
    q = 0.7071752369554196
    k = np.tan(np.pi * f0 / fs)
    vh = 10.0 ** (gain_db / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    b1 = np.array([
        (vh + vb * k / q + k * k) / a0,
        2.0 * (k * k - vh) / a0,
        (vh - vb * k / q + k * k) / a0,
    ])
    a1 = np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0])

    # Stage 2: RLB high-pass at ~38 Hz
    f0 = 38.13547087602444
    q = 0.5003270373238773
    k = np.tan(np.pi * f0 / fs)
    a0 = 1.0 + k / q + k * k
    b2 = np.array([1.0, -2.0, 1.0])
    a2 = np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0])
    return (b1, a1), (b2, a2)


class KWeighting:
    """Streaming K-weighting filter for ``channels`` channels."""

    def __init__(self, fs: float, channels: int):
        (self.b1, self.a1), (self.b2, self.a2) = k_weighting_coefficients(fs)
        self.channels = channels
        self.reset()

    def reset(self) -> None:
        self.z1 = np.zeros((2, self.channels))
        self.z2 = np.zeros((2, self.channels))

    def process(self, x: np.ndarray) -> np.ndarray:
        y, self.z1 = lfilter(self.b1, self.a1, x, axis=0, zi=self.z1)
        y, self.z2 = lfilter(self.b2, self.a2, y, axis=0, zi=self.z2)
        return y


# BS.1770-4 Annex 2: 4x over-sampling interpolator, 48 taps as 4 polyphase
# branches of 12 taps each (one row per phase).
_TP_PHASES_4X = np.array([
    [0.0017089843750, 0.0109863281250, -0.0196533203125, 0.0332031250000,
     -0.0594482421875, 0.1373291015625, 0.9721679687500, -0.1022949218750,
     0.0476074218750, -0.0266113281250, 0.0148925781250, -0.0083007812500],
    [-0.0291748046875, 0.0292968750000, -0.0517578125000, 0.0891113281250,
     -0.1665039062500, 0.4650878906250, 0.7797851562500, -0.2003173828125,
     0.1015625000000, -0.0582275390625, 0.0330810546875, -0.0189208984375],
    [-0.0189208984375, 0.0330810546875, -0.0582275390625, 0.1015625000000,
     -0.2003173828125, 0.7797851562500, 0.4650878906250, -0.1665039062500,
     0.0891113281250, -0.0517578125000, 0.0292968750000, -0.0291748046875],
    [-0.0083007812500, 0.0148925781250, -0.0266113281250, 0.0476074218750,
     -0.1022949218750, 0.9721679687500, 0.1373291015625, -0.0594482421875,
     0.0332031250000, -0.0196533203125, 0.0109863281250, 0.0017089843750],
])


class TruePeak:
    """Streaming true-peak detector.

    Uses 4x over-sampling below 60 kHz, 2x up to 120 kHz and none above,
    as recommended by BS.1770-4. ``process`` returns the absolute true peak
    (linear) per channel for the given block.
    """

    def __init__(self, fs: float, channels: int):
        self.channels = channels
        if fs < 60000:
            self.factor = 4
            self.phases = _TP_PHASES_4X
        elif fs < 120000:
            self.factor = 2
            h = firwin(24, 0.5, window=("kaiser", 5.0)) * 2.0
            self.phases = np.stack([h[0::2], h[1::2]])
        else:
            self.factor = 1
            self.phases = None
        self.reset()

    def reset(self) -> None:
        if self.phases is None:
            self.z = None
        else:
            taps = self.phases.shape[1]
            self.z = [np.zeros((taps - 1, self.channels)) for _ in range(self.factor)]

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.phases is None:
            return np.abs(x).max(axis=0)
        peak = np.abs(x).max(axis=0)
        for p in range(self.factor):
            y, self.z[p] = lfilter(self.phases[p], [1.0], x, axis=0, zi=self.z[p])
            peak = np.maximum(peak, np.abs(y).max(axis=0))
        return peak
