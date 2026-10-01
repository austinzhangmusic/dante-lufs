"""Conformance checks against ITU-R BS.1770-4 / EBU Tech 3341 and 3342."""
import numpy as np
import pytest

from dante_lufs.dsp.filters import k_weighting_coefficients
from dante_lufs.dsp.loudness import LoudnessMeter

FS = 48000


def sine(freq, dbfs, seconds, fs=FS, phase=0.0):
    t = np.arange(int(seconds * fs)) / fs
    return 10 ** (dbfs / 20) * np.sin(2 * np.pi * freq * t + phase)


def feed(meter, x, block=1024):
    for i in range(0, len(x), block):
        meter.process(x[i : i + block])


def test_k_weighting_matches_bs1770_table_at_48k():
    (b1, a1), (b2, a2) = k_weighting_coefficients(48000)
    np.testing.assert_allclose(b1, [1.53512485958697, -2.69169618940638, 1.19839281085285], atol=1e-6)
    np.testing.assert_allclose(a1, [1.0, -1.69065929318241, 0.73248077421585], atol=1e-6)
    np.testing.assert_allclose(a2, [1.0, -1.99004745483398, 0.99007225036621], atol=1e-6)


@pytest.mark.parametrize("fs", [44100, 48000, 96000])
def test_tech3341_case1_stereo_1khz_minus23(fs):
    x = np.stack([sine(1000, -23.0, 20, fs)] * 2, axis=1)
    m = LoudnessMeter(fs)
    feed(m, x)
    assert abs(m.integrated + 23.0) < 0.1
    assert abs(m.momentary + 23.0) < 0.1
    assert abs(m.short_term + 23.0) < 0.1


def test_tech3341_case3_relative_gate():
    # -36 dBFS 10 s, -23 dBFS 60 s, -36 dBFS 10 s -> integrated -23.0 (quiet parts gated)
    seg = np.concatenate([sine(1000, -36, 10), sine(1000, -23, 60), sine(1000, -36, 10)])
    x = np.stack([seg, seg], axis=1)
    m = LoudnessMeter(FS)
    feed(m, x)
    assert abs(m.integrated + 23.0) < 0.1


def test_absolute_gate_silence_is_minus_inf():
    m = LoudnessMeter(FS)
    feed(m, np.zeros((FS * 5, 2)))
    assert m.integrated == float("-inf")


def test_true_peak_intersample():
    # fs/4 sine with 45 deg phase: sample peak is 0.707 of amplitude, true peak is full amplitude.
    x = sine(FS / 4, -6.0, 1.0, phase=np.pi / 4)
    assert 20 * np.log10(np.abs(x).max()) < -8.5
    m = LoudnessMeter(FS)
    feed(m, np.stack([x, x], axis=1))
    assert abs(m.snapshot().true_peak_max + 6.0) < 0.15


def test_lra_two_level_signal():
    seg = np.concatenate([sine(1000, -20, 20), sine(1000, -30, 20)])
    x = np.stack([seg, seg], axis=1)
    m = LoudnessMeter(FS)
    feed(m, x)
    assert abs(m.lra - 10.0) < 1.0


def test_correlation_and_balance():
    s = sine(440, -12, 2)
    m = LoudnessMeter(FS)
    feed(m, np.stack([s, s], axis=1))
    assert m.snapshot().correlation > 0.99
    m.reset()
    feed(m, np.stack([s, -s], axis=1))
    assert m.snapshot().correlation < -0.99
    m.reset()
    feed(m, np.stack([s, np.zeros_like(s)], axis=1))
    assert m.snapshot().balance < -0.99


def test_peak_and_loud_alerts_latch():
    m = LoudnessMeter(FS, target_lufs=-24.0, peak_alert_dbtp=-1.0, loud_alert_margin_lu=5.0)
    feed(m, np.stack([sine(1000, -3.0, 4)] * 2, axis=1))
    snap = m.snapshot()
    assert snap.peak_alert is False
    assert snap.loud_alert is True
    m.reset()
    feed(m, np.stack([sine(1000, -0.5, 1)] * 2, axis=1))
    assert m.snapshot().peak_alert is True
