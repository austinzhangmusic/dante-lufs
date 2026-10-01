"""Offline measurement of a WAV file with the same meter the GUI uses.

Lets the readings be cross-checked against other loudness meters
(for example ``ffmpeg -i file.wav -af ebur128=peak=true -f null -``)
or the EBU Tech 3341/3342 reference files.
"""
from __future__ import annotations

import numpy as np

from .dsp.loudness import LoudnessMeter


def load_wav(path: str) -> tuple[int, np.ndarray]:
    """Return (fs, float64 samples shaped (frames, channels) in -1..1)."""
    from scipy.io import wavfile

    fs, data = wavfile.read(path)
    if data.ndim == 1:
        data = data[:, None]
    if data.dtype == np.int16:
        x = data.astype(np.float64) / 32768.0
    elif data.dtype == np.int32:
        x = data.astype(np.float64) / 2147483648.0
    elif data.dtype == np.uint8:
        x = (data.astype(np.float64) - 128.0) / 128.0
    else:
        x = data.astype(np.float64)
    return int(fs), x


def measure(path: str, mono_as_dual_mono: bool = True, block: int = 4096) -> dict:
    fs, x = load_wav(path)
    if x.shape[1] == 1 and mono_as_dual_mono:
        x = np.repeat(x, 2, axis=1)
    channels = min(x.shape[1], 5)
    x = x[:, :channels]
    meter = LoudnessMeter(fs, channels)
    for i in range(0, len(x), block):
        meter.process(x[i : i + block])
    meter._update_lra()
    snap = meter.snapshot()
    return {
        "file": path,
        "samplerate": fs,
        "channels": channels,
        "seconds": len(x) / fs,
        "integrated_lufs": snap.integrated,
        "lra_lu": snap.lra,
        "max_momentary_lufs": snap.max_momentary,
        "max_short_term_lufs": snap.max_short_term,
        "true_peak_dbtp": snap.true_peak_max,
        "true_peak_per_channel_dbtp": [float(v) for v in snap.true_peak_max_ch],
    }


def format_report(r: dict) -> str:
    def f(v: float) -> str:
        return "-inf" if v == float("-inf") else f"{v:6.1f}"

    lines = [
        f"{r['file']}",
        f"  {r['samplerate']} Hz, {r['channels']} ch, {r['seconds']:.1f} s",
        f"  Integrated loudness : {f(r['integrated_lufs'])} LUFS",
        f"  Loudness range      : {f(r['lra_lu'])} LU",
        f"  Max momentary       : {f(r['max_momentary_lufs'])} LUFS",
        f"  Max short-term      : {f(r['max_short_term_lufs'])} LUFS",
        f"  True peak           : {f(r['true_peak_dbtp'])} dBTP  "
        + " ".join(f(v) for v in r["true_peak_per_channel_dbtp"]),
    ]
    return "\n".join(lines)
