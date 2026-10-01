"""Audio input via PortAudio (sounddevice): Core Audio on macOS, ASIO/WASAPI on Windows.

``SD_ENABLE_ASIO`` must be set before sounddevice is imported so the
ASIO-enabled PortAudio DLL bundled with the wheel is loaded on Windows.
"""
from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass

os.environ.setdefault("SD_ENABLE_ASIO", "1")

import numpy as np  # noqa: E402
import sounddevice as sd  # noqa: E402

from ..dsp.loudness import LoudnessMeter  # noqa: E402

# Lower rank sorts first in device lists.
API_RANK = {
    "ASIO": 0,
    "Core Audio": 0,
    "Windows WASAPI": 1,
    "Windows WDM-KS": 2,
    "Windows DirectSound": 3,
    "MME": 4,
}


@dataclass(frozen=True)
class InputDevice:
    index: int
    name: str
    hostapi: str
    channels: int
    default_samplerate: float

    @property
    def label(self) -> str:
        return f"{self.name}  [{self.hostapi}]"

    @property
    def key(self) -> str:
        """Stable identifier used for persisting the selection."""
        return f"{self.hostapi}::{self.name}"


def list_input_devices(rescan: bool = False) -> list[InputDevice]:
    """All devices with at least two input channels, pro APIs first.

    ``rescan`` re-initialises PortAudio so hot-plugged devices appear. Only do
    that while no stream is open.
    """
    if rescan:
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
    apis = sd.query_hostapis()
    out: list[InputDevice] = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] >= 2:
            out.append(
                InputDevice(
                    index=i,
                    name=d["name"],
                    hostapi=apis[d["hostapi"]]["name"],
                    channels=int(d["max_input_channels"]),
                    default_samplerate=float(d["default_samplerate"]),
                )
            )
    out.sort(key=lambda d: (API_RANK.get(d.hostapi, 9), d.name.lower()))
    return out


def find_device(devices: list[InputDevice], key: str | None) -> InputDevice | None:
    if key:
        for d in devices:
            if d.key == key:
                return d
    try:
        default_index = sd.default.device[0]
        for d in devices:
            if d.index == default_index:
                return d
    except Exception:
        pass
    return devices[0] if devices else None


class AudioEngine:
    """Owns the input stream, a processing thread and the :class:`LoudnessMeter`."""

    def __init__(self):
        self.meter: LoudnessMeter | None = None
        self.device: InputDevice | None = None
        self.first_channel = 0
        self.mono = False
        self.samplerate = 0
        self.paused = False
        self.xruns = 0
        self.error: str | None = None
        self._stream: sd.InputStream | None = None
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._sel = slice(0, 2)

    # ----------------------------------------------------------------- control
    def start(
        self,
        device: InputDevice,
        first_channel: int = 0,
        samplerate: float | None = None,
        mono: bool = False,
        **meter_kwargs,
    ) -> None:
        """Open ``device``. Stereo: channels first_channel and first_channel+1.
        Mono: the single channel ``first_channel``, metered as dual-mono
        (duplicated to L and R, per EBU Tech 3343)."""
        self.stop()
        self.error = None
        self.device = device
        self.mono = mono
        fs = float(samplerate) if samplerate else device.default_samplerate
        if mono:
            ch = min(max(0, first_channel), device.channels - 1)
            wanted = [ch]
            self.first_channel = ch
        else:
            left, right = first_channel, first_channel + 1
            if right >= device.channels:
                left, right = 0, 1
            wanted = [left, right]
            self.first_channel = left

        attempts = []
        if device.hostapi == "ASIO":
            attempts.append((len(wanted), sd.AsioSettings(channel_selectors=wanted), slice(0, len(wanted))))
        elif device.hostapi == "Core Audio":
            attempts.append((len(wanted), sd.CoreAudioSettings(channel_map=wanted), slice(0, len(wanted))))
        attempts.append((wanted[-1] + 1, None, slice(wanted[0], wanted[-1] + 1)))

        last_exc: Exception | None = None
        for channels, extra, sel in attempts:
            try:
                stream = sd.InputStream(
                    device=device.index,
                    channels=channels,
                    samplerate=fs,
                    dtype="float32",
                    latency="low",
                    callback=self._callback,
                    extra_settings=extra,
                )
                stream.start()
            except Exception as exc:  # try the next strategy
                last_exc = exc
                continue
            self._stream = stream
            self._sel = sel
            break
        if self._stream is None:
            self.error = str(last_exc) if last_exc else "Could not open input"
            raise RuntimeError(self.error)

        self.samplerate = int(round(self._stream.samplerate))
        self.meter = LoudnessMeter(self.samplerate, 2, **meter_kwargs)
        self._running = True
        self._thread = threading.Thread(target=self._worker, name="lufs-dsp", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    @property
    def running(self) -> bool:
        return self._stream is not None and self._running

    def reset(self) -> None:
        if self.meter is not None:
            self.meter.reset()

    # ---------------------------------------------------------------- internals
    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            self.xruns += 1
        if self.paused or self._queue.qsize() > 200:
            return
        block = np.array(indata[:, self._sel], dtype=np.float32, copy=True)
        if self.mono:
            block = np.repeat(block[:, :1], 2, axis=1)
        self._queue.put(block)

    def _worker(self) -> None:
        while self._running:
            try:
                block = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            meter = self.meter
            if meter is not None and not self.paused:
                meter.process(block)
