# Dante LUFS

A cross-platform (macOS / Windows) stereo loudness meter that mirrors the layout of the
TC Electronic Clarity M. Pick a stereo input (Core Audio on macOS, ASIO or WASAPI on
Windows), pick a loudness target (default −24 LUFS-I) and watch the radar.

What it measures (ITU-R BS.1770-4 / EBU R128):

- Program loudness (integrated, gated), momentary (400 ms) and short-term (3 s)
- Loudness range (EBU Tech 3342)
- True-peak max per channel (4× over-sampled, BS.1770-4 Annex 2)
- Max momentary loudness, peak-to-loudness ratio
- Stereo correlation and a mid/side triangle
- Optional 1/3-octave RTA in place of the radar

The DSP is checked against the EBU Tech 3341 test cases in `tests/`.

## Downloads

- **Windows**: `releases/DanteLUFS.exe` (single file, no install). SmartScreen may warn because
  the binary is unsigned: choose "More info" → "Run anyway".
- **macOS**: `DanteLUFS.dmg` is produced by the GitHub Actions workflow in
  `.github/workflows/build.yml` (it needs a macOS runner, so it cannot be built on Windows).
  Download it from the workflow's artifacts, or from the Release page when a `v*` tag is pushed.
  The app is ad-hoc signed, not notarised, so on first launch right-click → Open, or run
  `xattr -dr com.apple.quarantine "/Applications/Dante LUFS.app"`.

## Run from source

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS: source .venv/bin/activate
pip install -e ".[dev]"
python -m dante_lufs
```

- **Space** pause / resume, **R** reset, **F** full screen.
- **Target** opens the preset list (ATSC A/85 −24, EBU R128 −23, streaming presets, custom).
- **SYS** picks the input device, stereo pair (1-2, 3-4, …), sample rate, radar time and alert thresholds.
- **RTA** switches the radar for a 1/3-octave analyser.

The selected device and settings persist between runs.

## Audio back ends

Everything goes through PortAudio via `sounddevice`.

- **macOS**: Core Audio. Dante Virtual Soundcard / Dante Via show up as Core Audio devices.
  The first time you run it, macOS asks for microphone permission for the terminal or app.
- **Windows**: ASIO is enabled automatically (`SD_ENABLE_ASIO=1` is set before `sounddevice`
  is imported, which loads the ASIO-capable PortAudio DLL shipped in the wheel). Dante
  Virtual Soundcard in ASIO mode, or any other ASIO driver, appears under the ASIO host API.
  WASAPI, WDM-KS, DirectSound and MME devices are also listed as fall-backs.

Multi-channel ASIO / Core Audio devices expose every stereo pair; the meter opens only the
chosen pair using ASIO channel selectors or a Core Audio channel map.

## Tests

```bash
pytest -q
```

## Packaging

```bash
pip install pyinstaller
# Windows
pyinstaller --noconfirm --windowed --name "Dante LUFS" --collect-all sounddevice -p . run.py
# macOS
pyinstaller --noconfirm --windowed --name "Dante LUFS" --collect-all sounddevice -p . run.py
```

where `run.py` is:

```python
from dante_lufs.__main__ import main
raise SystemExit(main())
```

On macOS add `NSMicrophoneUsageDescription` to the generated `Info.plist` so the bundled
app can request input access.
