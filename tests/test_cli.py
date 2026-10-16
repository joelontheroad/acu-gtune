# SPDX-FileCopyrightText: 2026 Joel Greenberg
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Test suite verifying CLI execution, exit codes, and isolated XDG filesystem safety."""

import io
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from app.cli import main
from app.config import (
    safe_resolve_preset_path,
    sanitize_log_path,
)


@pytest.fixture(autouse=True)
def isolate_xdg_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ensure all tests run strictly against an isolated temporary directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def _create_synthetic_wav(freq: float, duration: float = 0.5, sr: int = 44100) -> bytes:
    """Generate in-memory WAV byte buffer for testing."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    samples = (np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def test_cli_help(capsys: pytest.CaptureFixture):
    """Verify --help exits with code 0 and prints usage."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out or "usage:" in captured.err


def test_cli_version(capsys: pytest.CaptureFixture):
    """Verify --version contains AGPL-3.0 reference and repository URL."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    output = captured.out or captured.err
    assert "AGPL" in output
    assert "Source:" in output


def test_preset_show_json(capsys: pytest.CaptureFixture):
    """Verify preset show with --json outputs valid parseable JSON to stdout."""
    ret = main(["--json", "preset", "show"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["name"] == "default"
    assert data["instrument"] == "guitar_6"
    assert data["tolerance_cents"] == 0.1


def test_path_traversal_prevention():
    """Verify safe_resolve_preset_path blocks path traversal attempts (CWE-22)."""
    with pytest.raises(PermissionError) as excinfo:
        safe_resolve_preset_path("../../etc/passwd")
    assert "escapes allowed directory" in str(excinfo.value)


def test_log_sanitization():
    """Verify sensitive home directory username is scrubbed from logs."""
    home = str(Path.home())
    test_path = f"{home}/projects/secret/file.txt"
    sanitized = sanitize_log_path(test_path)
    assert home not in sanitized
    assert sanitized.startswith("~<USER>")


def test_reset_config(capsys: pytest.CaptureFixture):
    """Verify --reset-config executes cleanly with code 0."""
    ret = main(["--reset-config"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "reset to factory defaults" in captured.err


# Subprocess CLI Tests (Standards Compliance & Stream Separation)


def test_cli_subprocess_help(tmp_path: Path):
    """Verify CLI invoked as subprocess returns exit code 0 on --help."""
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    res = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert res.returncode == 0
    assert "acu-gtune" in res.stdout or "acu-gtune" in res.stderr


def test_cli_subprocess_invalid_arg(tmp_path: Path):
    """Verify CLI invoked with invalid flags returns exit code 2."""
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    res = subprocess.run(
        [sys.executable, "-m", "app.cli", "--nonexistent-flag-xyz"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert res.returncode == 2
    assert "unrecognized arguments" in res.stderr


def test_cli_subprocess_stream_separation_json(tmp_path: Path):
    """Verify strict stream separation: machine JSON to stdout, diagnostics to stderr."""
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    res = subprocess.run(
        [sys.executable, "-m", "app.cli", "--verbose", "--json", "preset", "show"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert res.returncode == 0
    # stdout must be parseable JSON
    data = json.loads(res.stdout)
    assert data["name"] == "default"


def test_cli_subprocess_tune_stdin_wav(tmp_path: Path):
    """Verify tuning analysis via stdin pipe returns valid JSON and in-tune status."""
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    # Low E string target: 82.4069 Hz
    wav_bytes = _create_synthetic_wav(freq=82.4069, duration=0.4, sr=44100)
    res = subprocess.run(
        [sys.executable, "-m", "app.cli", "--json", "tune", "-"],
        input=wav_bytes,
        capture_output=True,
        env=env,
        check=False,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("utf-8"))
    assert data["status"] == "success"
    assert data["target_note"] == "E2"
    assert abs(data["cents"]) <= 0.1
    assert data["in_tune"] is True


def test_cli_serve_argument_parsing():
    """Verify that serve parser correctly recognizes --no-open and --open flags."""
    from app.cli import build_parser

    parser = build_parser()
    args_default = parser.parse_args(["serve"])
    assert args_default.open is True

    args_no_open = parser.parse_args(["serve", "--no-open"])
    assert args_no_open.open is False

    args_explicit_open = parser.parse_args(["serve", "--open"])
    assert args_explicit_open.open is True
