"""Streaming loudness meter implementing ITU-R BS.1770-4 / EBU R128.

Readouts: momentary (400 ms), short-term (3 s), integrated (gated),
loudness range (EBU Tech 3342), true-peak maximum, max momentary/short-term,
plus stereo correlation and mid/side levels for the display.

All public state is updated from :meth:`LoudnessMeter.process`; the UI
thread reads a consistent copy through :meth:`LoudnessMeter.snapshot`.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

import numpy as np

from .filters import KWeighting, TruePeak

ABSOLUTE_GATE_LUFS = -70.0
RELATIVE_GATE_LU = -10.0
LRA_RELATIVE_GATE_LU = -20.0
CELLS_PER_SECOND = 10  # 100 ms accumulation cells
MOMENTARY_CELLS = 4  # 400 ms
SHORT_TERM_CELLS = 30  # 3 s
NEG_INF = float("-inf")


def power_to_lufs(p):
    """Convert mean-square power (channel-weighted sum) to LUFS."""
    return -0.691 + 10.0 * np.log10(np.maximum(p, 1e-30))


def lin_to_db(v: float) -> float:
    return 20.0 * math.log10(v) if v > 1e-12 else NEG_INF


class _GrowArray:
    """Append-only float array with amortised growth."""

    def __init__(self, capacity: int = 8192):
        self._buf = np.zeros(capacity)
        self.n = 0

    def append(self, v: float) -> None:
        if self.n == len(self._buf):
            self._buf = np.concatenate([self._buf, np.zeros(len(self._buf))])
        self._buf[self.n] = v
        self.n += 1

    def view(self) -> np.ndarray:
        return self._buf[: self.n]


@dataclass
class Snapshot:
    """Copy of meter state handed to the UI."""

    momentary: float = NEG_INF
    short_term: float = NEG_INF
    integrated: float = NEG_INF
    lra: float = 0.0
    max_momentary: float = NEG_INF
    max_short_term: float = NEG_INF
    true_peak_max: float = NEG_INF  # dBTP, max over channels
    true_peak_max_ch: np.ndarray = field(default_factory=lambda: np.full(2, NEG_INF))
    true_peak_recent_ch: np.ndarray = field(default_factory=lambda: np.full(2, NEG_INF))
    correlation: float = 0.0
    mid_db: float = NEG_INF
    side_db: float = NEG_INF
    balance: float = 0.0
    elapsed_s: float = 0.0
    peak_alert: bool = False
    loud_alert: bool = False
    radar: np.ndarray = field(default_factory=lambda: np.full(720, NEG_INF))
    radar_head: float = 0.0  # 0..1 fraction of a revolution
    spectrum_buffer: np.ndarray = field(default_factory=lambda: np.zeros(8192))
    fs: int = 48000

    @property
    def plr(self) -> float:
        """Peak-to-loudness ratio in dB."""
        if self.true_peak_max == NEG_INF or self.integrated == NEG_INF:
            return NEG_INF
        return self.true_peak_max - self.integrated


class LoudnessMeter:
    def __init__(
        self,
        fs: float,
        channels: int = 2,
        radar_seconds: float = 60.0,
        radar_slots: int = 720,
        target_lufs: float = -24.0,
        peak_alert_dbtp: float = -1.0,
        loud_alert_margin_lu: float = 5.0,
    ):
        self.fs = int(round(fs))
        self.channels = channels
        # BS.1770 channel weights for L, R, C, Ls, Rs (LFE excluded upstream).
        weights = np.array([1.0, 1.0, 1.0, 1.41, 1.41])
        self.weights = weights[:channels] if channels <= 5 else np.ones(channels)
        self.cell_len = int(round(self.fs / CELLS_PER_SECOND))
        self.kw = KWeighting(self.fs, channels)
        self.tp = TruePeak(self.fs, channels)
        self.corr_tau = 0.3
        self.target_lufs = target_lufs
        self.peak_alert_dbtp = peak_alert_dbtp
        self.loud_alert_margin_lu = loud_alert_margin_lu
        self.radar_slots = radar_slots
        self.spectrum_len = 8192
        self.lock = threading.Lock()
        self.set_radar_seconds(radar_seconds)
        self.reset()

    # ------------------------------------------------------------------ setup
    def set_radar_seconds(self, seconds: float) -> None:
        self.radar_seconds = float(seconds)
        self.radar_cells_per_rev = max(1, int(round(seconds * CELLS_PER_SECOND)))
        with self.lock:
            self._radar = np.full(self.radar_slots, NEG_INF)
            self._radar_cell = 0
            self._radar_slot = 0

    def reset(self) -> None:
        with self.lock:
            self.kw.reset()
            self.tp.reset()
            self._cell_acc = np.zeros(self.channels)
            self._cell_fill = 0
            self._cells = np.zeros(SHORT_TERM_CELLS)
            self._ncells = 0
            self._blocks = _GrowArray()
            self._st_blocks = _GrowArray()
            self.momentary = NEG_INF
            self.short_term = NEG_INF
            self.integrated = NEG_INF
            self.lra = 0.0
            self.max_momentary = NEG_INF
            self.max_short_term = NEG_INF
            self._tp_max_lin = np.zeros(self.channels)
            self._tp_recent_lin = np.zeros(self.channels)
            self.samples = 0
            self._radar = np.full(self.radar_slots, NEG_INF)
            self._radar_cell = 0
            self._radar_slot = 0
            self._ll = self._rr = self._lr = 0.0
            self._mid = self._side = 0.0
            self.correlation = 0.0
            self.peak_alert = False
            self.loud_alert = False
            self._spec = np.zeros(self.spectrum_len)

    # -------------------------------------------------------------- processing
    def process(self, x: np.ndarray) -> None:
        """Feed a block shaped (frames, channels) of float samples in [-1, 1]."""
        n = x.shape[0]
        if n == 0:
            return
        if x.dtype != np.float64:
            x = x.astype(np.float64)
        with self.lock:
            self._process_locked(x, n)

    def _process_locked(self, x: np.ndarray, n: int) -> None:
        # True peak
        pk = self.tp.process(x)
        self._tp_max_lin = np.maximum(self._tp_max_lin, pk)
        self._tp_recent_lin = np.maximum(self._tp_recent_lin, pk)
        if lin_to_db(float(pk.max())) > self.peak_alert_dbtp:
            self.peak_alert = True

        # Correlation and mid/side on the raw stereo pair
        if self.channels >= 2:
            left = x[:, 0]
            right = x[:, 1]
            a = 1.0 - math.exp(-n / (self.fs * self.corr_tau))
            self._ll += a * (float(np.dot(left, left)) / n - self._ll)
            self._rr += a * (float(np.dot(right, right)) / n - self._rr)
            self._lr += a * (float(np.dot(left, right)) / n - self._lr)
            denom = math.sqrt(self._ll * self._rr)
            self.correlation = self._lr / denom if denom > 1e-12 else 0.0
            mid = 0.5 * (left + right)
            side = 0.5 * (left - right)
            self._mid += a * (float(np.dot(mid, mid)) / n - self._mid)
            self._side += a * (float(np.dot(side, side)) / n - self._side)
            mono = mid
        else:
            mono = x[:, 0]

        # Rolling buffer for the RTA view
        if n >= self.spectrum_len:
            self._spec[:] = mono[-self.spectrum_len :]
        else:
            self._spec = np.roll(self._spec, -n)
            self._spec[-n:] = mono

        # K-weighting and 100 ms cell accumulation
        sq = self.kw.process(x)
        sq *= sq
        i = 0
        while i < n:
            take = min(self.cell_len - self._cell_fill, n - i)
            self._cell_acc += sq[i : i + take].sum(axis=0)
            self._cell_fill += take
            i += take
            if self._cell_fill == self.cell_len:
                self._finish_cell()
        self.samples += n

    def _finish_cell(self) -> None:
        p = float(np.dot(self.weights, self._cell_acc) / self.cell_len)
        self._cell_acc[:] = 0.0
        self._cell_fill = 0
        self._cells[self._ncells % SHORT_TERM_CELLS] = p
        self._ncells += 1

        if self._ncells >= MOMENTARY_CELLS:
            idx = [(self._ncells - 1 - k) % SHORT_TERM_CELLS for k in range(MOMENTARY_CELLS)]
            mp = float(self._cells[idx].mean())
            self.momentary = float(power_to_lufs(mp))
            self._blocks.append(mp)
            self.max_momentary = max(self.max_momentary, self.momentary)
            self._update_integrated()

        if self._ncells >= SHORT_TERM_CELLS:
            sp = float(self._cells.mean())
            self.short_term = float(power_to_lufs(sp))
            self._st_blocks.append(sp)
            self.max_short_term = max(self.max_short_term, self.short_term)
            if self.short_term > self.target_lufs + self.loud_alert_margin_lu:
                self.loud_alert = True
            if self._ncells % 5 == 0:
                self._update_lra()

        # Radar history: short-term loudness around one revolution. Every slot
        # between the previous write position and this one is filled so the
        # display has no gaps when slots outnumber cells per revolution; cells
        # sharing a slot keep the maximum.
        rev = self.radar_cells_per_rev
        n_slots = self.radar_slots
        slot = int((self._radar_cell % rev) / rev * n_slots) % n_slots
        value = self.short_term
        if self._radar_cell == 0:
            self._radar[slot] = value
        elif slot == self._radar_slot:
            self._radar[slot] = max(self._radar[slot], value)
        else:
            k = (self._radar_slot + 1) % n_slots
            while True:
                self._radar[k] = value
                if k == slot:
                    break
                k = (k + 1) % n_slots
        self._radar_slot = slot
        self._radar_cell += 1

    def _update_integrated(self) -> None:
        blocks = self._blocks.view()
        if blocks.size == 0:
            self.integrated = NEG_INF
            return
        lk = power_to_lufs(blocks)
        abs_mask = lk > ABSOLUTE_GATE_LUFS
        if not abs_mask.any():
            self.integrated = NEG_INF
            return
        rel_thresh = float(power_to_lufs(blocks[abs_mask].mean())) + RELATIVE_GATE_LU
        mask = abs_mask & (lk > rel_thresh)
        if not mask.any():
            self.integrated = NEG_INF
            return
        self.integrated = float(power_to_lufs(blocks[mask].mean()))

    def _update_lra(self) -> None:
        st = self._st_blocks.view()
        if st.size < 2:
            self.lra = 0.0
            return
        lk = power_to_lufs(st)
        abs_mask = lk > ABSOLUTE_GATE_LUFS
        if not abs_mask.any():
            self.lra = 0.0
            return
        rel_thresh = float(power_to_lufs(st[abs_mask].mean())) + LRA_RELATIVE_GATE_LU
        gated = lk[abs_mask & (lk > rel_thresh)]
        if gated.size < 2:
            self.lra = 0.0
            return
        lo, hi = np.percentile(gated, [10.0, 95.0])
        self.lra = float(hi - lo)

    # ------------------------------------------------------------------ output
    def snapshot(self) -> Snapshot:
        with self.lock:
            tp_max_ch = np.array([lin_to_db(float(v)) for v in self._tp_max_lin])
            tp_recent_ch = np.array([lin_to_db(float(v)) for v in self._tp_recent_lin])
            self._tp_recent_lin[:] = 0.0
            lr_sum = self._ll + self._rr
            balance = (self._rr - self._ll) / lr_sum if lr_sum > 1e-12 else 0.0
            head = (self._radar_cell % self.radar_cells_per_rev) / self.radar_cells_per_rev
            return Snapshot(
                momentary=self.momentary,
                short_term=self.short_term,
                integrated=self.integrated,
                lra=self.lra,
                max_momentary=self.max_momentary,
                max_short_term=self.max_short_term,
                true_peak_max=float(tp_max_ch.max()) if tp_max_ch.size else NEG_INF,
                true_peak_max_ch=tp_max_ch,
                true_peak_recent_ch=tp_recent_ch,
                correlation=self.correlation,
                mid_db=10.0 * math.log10(self._mid) if self._mid > 1e-24 else NEG_INF,
                side_db=10.0 * math.log10(self._side) if self._side > 1e-24 else NEG_INF,
                balance=balance,
                elapsed_s=self.samples / self.fs,
                peak_alert=self.peak_alert,
                loud_alert=self.loud_alert,
                radar=self._radar.copy(),
                radar_head=head,
                spectrum_buffer=self._spec.copy(),
                fs=self.fs,
            )
