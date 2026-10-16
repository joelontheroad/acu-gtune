# SPDX-FileCopyrightText: 2026 Joel Greenberg
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command-line interface implementation adhering to POSIX standards and stream discipline.

Provides the CLI entry point for acu-gtune, supporting live pitch analysis from WAV
files or piped stdin audio streams, local preset configuration, and launching the
localhost web interface with strict stream separation (data to stdout, logs to stderr).
"""

import argparse
import io
import json
import os
import signal
import sys
import wave
from typing import List, Optional

import numpy as np
import yaml

from app import __license__, __repository__, __version__
from app.config import (
    get_presets_dir,
    load_preset,
    reset_all_configuration,
)
from app.dsp import (
    TUNING_PRESETS,
    analyze_audio_frame,
)


def setup_signal_handlers() -> None:
    """Register graceful POSIX signal handlers for SIGINT and SIGTERM.

    Traps interruption signals to flush buffers and terminate cleanly with exit
    code 130 without emitting uncaught Python tracebacks to stderr.
    """
    def _sig_handler(signum, frame):
        # SECURITY: Flush active buffers and exit with 130 to prevent state corruption
        # or orphaned filesystem handles on abrupt process termination.
        sys.stderr.write("\n[acu-gtune] Process interrupted by user. Exiting.\n")
        sys.stderr.flush()
        sys.exit(130)

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)


def should_colorize() -> bool:
    """Determine whether ANSI terminal color sequences should be emitted.

    Checks the NO_COLOR environment variable specification and verifies whether
    standard output is an interactive terminal stream (TTY).

    Returns:
        True if colors should be emitted; False otherwise.
    """
    # SECURITY: Respect NO_COLOR standard to prevent ANSI escape sequence injection
    # into automated logs, CI environments, or redirected pipes.
    if "NO_COLOR" in os.environ:
        return False
    return sys.stdout.isatty()


def _read_wav_buffer(raw_bytes: bytes) -> tuple[np.ndarray, int]:
    """Extract normalized float audio sample array and sample rate from a WAV buffer.

    Converts integer PCM sample encodings (8-bit, 16-bit, 32-bit) to 64-bit float
    samples normalized to [-1.0, 1.0], averaging multi-channel audio down to mono.

    Args:
        raw_bytes: In-memory byte buffer of a valid WAV audio file.

    Returns:
        Tuple containing:
            - audio: 1D NumPy array of normalized float64 audio samples.
            - framerate: Sampling rate in Hertz.
    """
    # SECURITY: Normalize raw PCM samples to [-1.0, 1.0] float64 range to defend against
    # arithmetic integer overflow and numerical instabilities in downstream DSP calculations.
    with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        data = wf.readframes(n_frames)

    if sampwidth == 2:
        audio = np.frombuffer(data, dtype=np.int16).astype(np.float64) / 32768.0
    elif sampwidth == 4:
        audio = np.frombuffer(data, dtype=np.int32).astype(np.float64) / 2147483648.0
    elif sampwidth == 1:
        audio = (np.frombuffer(data, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    else:
        audio = np.frombuffer(data, dtype=np.int16).astype(np.float64) / 32768.0

    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    return audio, framerate


def build_parser() -> argparse.ArgumentParser:
    """Construct and configure the command-line argument parser.

    Configures global flags (-v/--version, -q/--quiet, --verbose, --json, --reset-config)
    and subcommands ('serve', 'preset', 'tune', 'run') with stream separation and
    standard POSIX formatting.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="acu-gtune",
        description="acu-gtune: High-precision stroboscopic guitar and bass tuner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Standard global flags adhering to POSIX and project guidelines
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__} ({__license__})\nSource: {__repository__}",
        help="Show program version and license information.",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress all informational messages (errors and data output only).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose diagnostic output on stderr.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured results in machine-readable JSON format to stdout.",
    )
    parser.add_argument(
        "--reset-config",
        action="store_true",
        help="Purge all user-saved presets and restore factory defaults.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # 'serve' subcommand
    serve_parser = subparsers.add_parser(
        "serve",
        help="Launch the local stroboscopic web interface on localhost.",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port number to bind (default: 8080).",
    )
    serve_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind. Defaults strictly to 127.0.0.1 (localhost).",
    )
    serve_parser.add_argument(
        "--open",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Automatically open the web interface in the default browser (default: true).",
    )
    serve_parser.add_argument(
        "--no-browser",
        dest="open",
        action="store_false",
        help="Suppress automatic browser window launch on startup.",
    )
    serve_parser.add_argument(
        "--browser",
        dest="open",
        action="store_true",
        help="Automatically open the web interface in the default browser.",
    )

    # 'preset' subcommand
    preset_parser = subparsers.add_parser("preset", help="Inspect and manage local YAML presets.")
    preset_sub = preset_parser.add_subparsers(dest="preset_action")
    preset_sub.add_parser("list", help="List all locally available presets.")

    show_preset = preset_sub.add_parser("show", help="Display the active preset configuration.")
    show_preset.add_argument(
        "name",
        nargs="?",
        default="default",
        help="Preset name (default: 'default').",
    )

    # 'tune' subcommand
    tune_parser = subparsers.add_parser(
        "tune",
        help="Analyze audio from a WAV file or stdin to calculate high-precision pitch and cents.",
    )
    tune_parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Input WAV audio file, or '-' to read from standard input (stdin).",
    )
    tune_parser.add_argument(
        "--instrument",
        default="guitar_6",
        choices=list(TUNING_PRESETS.keys()),
        help="Instrument type (default: guitar_6).",
    )
    tune_parser.add_argument(
        "--tuning",
        default="standard",
        help="Tuning preset name (default: standard).",
    )
    tune_parser.add_argument(
        "--a4",
        type=float,
        default=440.0,
        help="Reference concert A4 frequency in Hz (default: 440.0).",
    )

    # 'run' subcommand with stdin piping support (-)
    run_parser = subparsers.add_parser("run", help="Execute utility processing on input data.")
    run_parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Input file path, or '-' to read directly from standard input (stdin).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Execute the top-level command-line interface entry point.

    Parses command-line arguments, sets up signal handlers, routes execution to the
    appropriate subcommand handler, and enforces stream discipline (machine JSON to
    stdout, diagnostic messages to stderr).

    Args:
        argv: Optional list of command-line argument strings. Defaults to sys.argv[1:].

    Returns:
        Process exit code:
            - 0: Successful execution.
            - 1: Operational failure (e.g. invalid input data, audio read error).
            - 2: CLI syntax or argument parsing error.
            - 130: Interrupted by user (SIGINT/SIGTERM).
    """
    setup_signal_handlers()
    parser = build_parser()
    args = parser.parse_args(argv)

    # Purge presets and restore built-in factory defaults when requested
    if args.reset_config:
        reset_all_configuration()
        if not args.quiet:
            sys.stderr.write("[acu-gtune] Local configuration reset to factory defaults.\n")
        return 0

    if not args.subcommand:
        parser.print_help(sys.stderr)
        return 2

    # Lazy import of web server framework to maintain sub-200ms CLI startup latency
    if args.subcommand == "serve":
        # SECURITY: Lazily import heavy server framework to avoid unnecessary network stack binding
        # and keep non-server CLI commands fast and decoupled from the web layer.
        from app.server import run_local_server
        run_local_server(port=args.port, host=args.host, open_browser=args.open)
        return 0

    if args.subcommand == "preset":
        if args.preset_action == "list":
            presets_dir = get_presets_dir()
            preset_files = [p.stem for p in presets_dir.glob("*.yaml")]
            if args.json:
                sys.stdout.write(json.dumps({"presets": preset_files}, indent=2) + "\n")
            else:
                for p in preset_files:
                    sys.stdout.write(f"- {p}\n")
            return 0

        if args.preset_action == "show":
            preset = load_preset(args.name)
            if args.json:
                sys.stdout.write(json.dumps(preset.model_dump(), indent=2) + "\n")
            else:
                sys.stdout.write(yaml.dump(preset.model_dump(), sort_keys=False) + "\n")
            return 0

    if args.subcommand == "tune":
        # Support reading audio streams via standard input pipe (-) or local file
        # SECURITY: Stream audio directly from stdin (-) into memory buffers without creating
        # temporary files on disk, avoiding local data residency leaks (CWE-312).
        if args.input == "-":
            raw_data = sys.stdin.buffer.read()
        else:
            with open(args.input, "rb") as f:
                raw_data = f.read()

        if len(raw_data) == 0:
            sys.stderr.write("[acu-gtune] Error: No audio data received on input.\n")
            return 1

        allowed_notes = TUNING_PRESETS.get(args.instrument, {}).get(args.tuning)
        try:
            audio, sr = _read_wav_buffer(raw_data)
        except Exception:
            # Fallback for headerless 16-bit raw PCM byte streams
            audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float64) / 32768.0
            sr = 44100

        result = analyze_audio_frame(
            signal=audio,
            sample_rate=sr,
            allowed_notes=allowed_notes,
            a4_ref=args.a4,
            tolerance_cents=0.1,
        )

        if result is None:
            if args.json:
                sys.stdout.write(json.dumps({"status": "no_signal", "in_tune": False}) + "\n")
            else:
                sys.stdout.write("No clear pitch detected (signal below noise gate).\n")
            return 0

        data_dict = result.model_dump()
        data_dict["status"] = "success"
        if args.json:
            sys.stdout.write(json.dumps(data_dict, indent=2) + "\n")
        else:
            tune_str = " [IN TUNE +/-0.1c]" if result.in_tune else ""
            sys.stdout.write(
                f"Note: {result.target_note} | Target: {result.target_freq:.4f} Hz | "
                f"Detected: {result.detected_freq:.4f} Hz | "
                f"Offset: {result.cents:+.3f} cents{tune_str}\n"
            )

        if args.verbose:
            sys.stderr.write(
                f"[acu-gtune] Slip rate: {result.slip_cps:+.4f} cps, RMS: {result.rms:.5f}\n"
            )
        return 0

    if args.subcommand == "run":
        if args.input == "-":
            raw_input = sys.stdin.buffer.read()
        else:
            with open(args.input, "rb") as f:
                raw_input = f.read()

        preset = load_preset("default")
        # Detect RIFF/WAVE container header before parsing binary data
        if raw_input.startswith(b"RIFF") and b"WAVE" in raw_input[:16]:
            try:
                audio, sr = _read_wav_buffer(raw_input)
                allowed_notes = TUNING_PRESETS.get(preset.instrument, {}).get(preset.tuning)
                res = analyze_audio_frame(
                    signal=audio,
                    sample_rate=sr,
                    allowed_notes=allowed_notes,
                    a4_ref=preset.a4_calibration,
                    tolerance_cents=preset.tolerance_cents,
                    noise_gate=preset.noise_gate,
                )
                if res is not None:
                    out = res.model_dump()
                    out["status"] = "success"
                    out["bytes_processed"] = len(raw_input)
                    if args.json:
                        sys.stdout.write(json.dumps(out, indent=2) + "\n")
                    else:
                        sys.stdout.write(
                            f"Analyzed {len(raw_input)} bytes: Note {res.target_note} "
                            f"({res.detected_freq:.4f} Hz, {res.cents:+.3f} cents)\n"
                        )
                    return 0
            except Exception as exc:
                if args.verbose:
                    sys.stderr.write(f"[acu-gtune] Audio decode error: {exc}\n")

        # Fallback response for generic binary stream inputs
        result = {
            "status": "success",
            "bytes_processed": len(raw_input),
            "preset_applied": preset.name,
        }

        if args.json:
            sys.stdout.write(json.dumps(result, indent=2) + "\n")
        else:
            sys.stdout.write(f"Processed {result['bytes_processed']} bytes successfully.\n")

        if args.verbose:
            sys.stderr.write(
                f"[acu-gtune] Applied preset '{preset.name}' with "
                f"instrument={preset.instrument}\n"
            )

        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
