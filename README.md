# acu-gtune

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Standards: 12-Category](https://img.shields.io/badge/Standards-Compliant-emerald.svg)](https://github.com/joelontheroad/Software-standards)

A high-precision stroboscopic guitar and bass tuner accurate to **$\pm 0.1\text{ cent}$**, featuring a vintage 1970's Peterson-style rotating strobe disc visualizer.

This project strictly adheres to the 12 Open Source Software Standards:
- **Zero Telemetry & Local Data**: Presets saved locally in `$XDG_CONFIG_HOME/acu-gtune/presets/`.
- **GNU AGPL-3.0-or-later**: Free and open source with full user rights.
- **Strict Localhost Security**: Web servers default strictly to `127.0.0.1` with ephemeral launch token authentication.
- **Stream Separation**: Machine JSON data to `stdout`, diagnostics and logs to `stderr`.

---

## 3-Step Quickstart

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -e ".[dev,web]"

# 3. Launch the full-screen Peterson Strobe Tuner in your browser
acu-gtune serve
```

---

## Core Features

- **$\pm 0.1\text{ Cent}$ High-Precision DSP Engine**: Sub-sample YIN period extraction and zero-padded parabolic FFT for ultra-precise pitch detection.
- **1970's Peterson Strobe Visualizer**: Full-screen HTML5 Canvas stroboscopic wheel with rotating concentric harmonic rings that lock motionless at in-tune state.
- **Multi-Instrument Support**: Guitars (6-string & 7-string) and Bass Guitars (4-string & 5-string) with standard, Drop D, DADGAD, Open G/D, and Half Step Down tunings, plus full Chromatic mode.
- **Microphone Ingestion**: Direct Web Audio microphone access in browser (`getUserMedia`) with real-time zero-latency DSP.
- **CLI Audio Analysis**: `acu-gtune tune [file.wav]` analyzes WAV files or piped stdin (`-`) with clean JSON output.

---

## CLI Flags Reference

| Command / Flag | Description |
|---|---|
| `acu-gtune serve` | Launch the authenticated Peterson strobe web interface on `127.0.0.1:8080` |
| `acu-gtune tune [file]` | Analyze pitch and cents offset from a WAV file or stdin (`-`) |
| `acu-gtune preset list` | List all locally available YAML presets |
| `acu-gtune preset show` | Display active preset configuration in YAML or JSON |
| `--json` | Output machine-readable JSON data to `stdout` |
| `-q, --quiet` | Suppress diagnostic output |
| `--verbose` | Enable verbose diagnostic logging to `stderr` |
| `--reset-config` | Purge local presets and restore factory defaults |
| `-v, --version` | Display version, AGPLv3 license, and source link |
| `-h, --help` | Display usage and subcommand information |

---

## Configuration & Presets

Configuration and presets reside in standard XDG directories:
- **Linux/macOS**: `~/.config/acu-gtune/presets/default.yaml`
- **Windows**: `%APPDATA%\acu-gtune\presets\default.yaml`

Example preset YAML:
```yaml
name: default
instrument: guitar_6
tuning: standard
a4_calibration: 440.0
tolerance_cents: 0.1
noise_gate: 0.005
strobe_mode: disc
theme: auto
max_items: 50
enable_cache: true
```

---

## Security Policy

See [`SECURITY.md`](SECURITY.md) for vulnerability disclosure and reporting guidelines.

---

## License

Licensed under the **GNU Affero General Public License v3.0 or later** (see [`LICENSE`](LICENSE)).  
Source repository: [https://github.com/joelontheroad/acu-gtune](https://github.com/joelontheroad/acu-gtune)
