# SPDX-FileCopyrightText: 2026 Joel Greenberg
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Configuration and preset management adhering to XDG specs and security guidelines.

Provides Pydantic models for strobe tuner presets and application settings,
along with isolated filesystem operations in accordance with XDG Base Directory
specifications and POSIX permission standards (CWE-22, CWE-502, CWE-732).
"""

import os
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

APP_NAME = "acu-gtune"


class TunerPreset(BaseModel):
    """Schema-validated tuner preset definition and DSP configuration parameters.

    Attributes:
        name: Unique preset identifier.
        instrument: Target instrument category (e.g. 'guitar_6', 'bass_4', 'chromatic').
        tuning: Tuning preset name (e.g. 'standard', 'drop_d', 'dadgad').
        a4_calibration: Concert A4 reference frequency in Hertz (400.0 to 480.0 Hz).
        tolerance_cents: Lock tolerance window in cents (default +/-0.1c).
        cents_resolution: Display quantization step size in cents.
        noise_gate: RMS amplitude threshold below which audio is gated as silence.
        strobe_mode: Visual strobe rendering mode ('disc' or 'bars').
        theme: Interface visual theme ('auto', 'light', or 'dark').
        max_items: Maximum items displayed in history and list views.
        enable_cache: Flag enabling local temporary file caching.
    """

    name: str = Field(default="default", description="Preset name")
    instrument: str = Field(
        default="guitar_6",
        description="Target instrument: 'guitar_6', 'guitar_7', 'bass_4', 'bass_5', 'chromatic'",
    )
    tuning: str = Field(
        default="standard",
        description="Tuning preset name: 'standard', 'drop_d', 'dadgad', 'open_g', etc.",
    )
    a4_calibration: float = Field(
        default=440.0,
        ge=400.0,
        le=480.0,
        description="Concert A4 reference frequency in Hertz (400.0 to 480.0)",
    )
    tolerance_cents: float = Field(
        default=0.1,
        ge=0.01,
        le=5.0,
        description="In-tune lock tolerance window in cents (default: +/-0.1c)",
    )
    cents_resolution: float = Field(
        default=0.2,
        ge=0.05,
        le=2.0,
        description="Display quantization step size in cents (default: 0.2c)",
    )
    noise_gate: float = Field(
        default=0.005,
        ge=0.0001,
        le=0.5,
        description="RMS threshold below which audio is gated as silence",
    )
    strobe_mode: str = Field(
        default="disc",
        description="Visual strobe style: 'disc' (Peterson rotating wheel) or 'bars' (linear)",
    )
    theme: str = Field(default="auto", description="UI theme: 'auto', 'light', or 'dark'")
    max_items: int = Field(default=50, ge=1, le=1000, description="Maximum items for list views")
    enable_cache: bool = Field(default=True, description="Enable local temporary caching")


# Backward compatibility alias
ToolPreset = TunerPreset


class AppConfig(BaseModel):
    """Global application configuration model.

    Attributes:
        version: Configuration schema version number.
        default_preset: Name of the active or fallback preset.
        preset: Default tuner preset settings.
    """

    version: int = Field(default=1, description="Configuration schema version")
    default_preset: str = Field(default="default", description="Active preset name")
    preset: TunerPreset = Field(default_factory=TunerPreset)


def sanitize_log_path(path: str) -> str:
    """Scrub local username and home directory from log strings to protect privacy.

    Args:
        path: Raw filesystem path string.

    Returns:
        Sanitized path string with the user's home directory replaced by '~<USER>'.
    """
    # SECURITY: Privacy protection. Scrub local usernames and home directory paths
    # before emitting diagnostic logs to prevent leaking identity on shared systems.
    home_dir = str(Path.home())
    if home_dir and path.startswith(home_dir):
        return path.replace(home_dir, "~<USER>", 1)
    return path


def get_config_dir() -> Path:
    """Return the platform-appropriate configuration directory adhering to XDG specs.

    Returns:
        Path to the application configuration directory.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        config_root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        config_root = Path(base) if base else Path.home() / ".config"

    target_dir = config_root / APP_NAME
    # SECURITY: Restrict directory permissions to owner-only (mode 0700 / rwx------)
    # on POSIX platforms to prevent unauthorized local users from reading or tampering with presets.
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(target_dir, 0o700)
            except OSError:
                pass
    return target_dir


def get_presets_dir() -> Path:
    """Return the presets subfolder within the configuration directory.

    Returns:
        Path to the directory containing YAML preset files.
    """
    presets_dir = get_config_dir() / "presets"
    # SECURITY: Enforce mode 0700 (rwx------) on presets storage directory.
    if not presets_dir.exists():
        presets_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(presets_dir, 0o700)
            except OSError:
                pass
    return presets_dir


def safe_resolve_preset_path(preset_name: str) -> Path:
    """Safely resolve a preset file path, preventing directory traversal attacks.

    Args:
        preset_name: Base name or filename of the preset.

    Returns:
        Canonical Path to the preset file within the authorized directory.

    Raises:
        PermissionError: If the resolved path escapes the authorized presets directory (CWE-22).
    """
    clean_name = preset_name.strip()
    if not clean_name.endswith(".yaml"):
        clean_name += ".yaml"

    base_dir = get_presets_dir().resolve()
    target_path = (base_dir / clean_name).resolve()

    # SECURITY: Path traversal defense (CWE-22). Canonicalize paths via resolve()
    # and verify target path remains strictly within the authorized base directory.
    try:
        target_path.relative_to(base_dir)
    except ValueError as exc:
        msg = f"Access denied: Preset '{preset_name}' escapes allowed directory"
        raise PermissionError(msg) from exc

    return target_path


def load_preset(preset_name: str = "default") -> ToolPreset:
    """Load and validate a YAML preset file using safe deserialization.

    Args:
        preset_name: Preset name to load. Defaults to 'default'.

    Returns:
        Validated ToolPreset model instance.

    Raises:
        ValueError: If the YAML syntax is malformed or violates the schema.
    """
    preset_path = safe_resolve_preset_path(preset_name)

    if not preset_path.exists():
        default_preset = ToolPreset(name=preset_name)
        save_preset(default_preset)
        return default_preset

    try:
        with open(preset_path, "r", encoding="utf-8") as f:
            # SECURITY: Defend against arbitrary code execution (CWE-502) by strictly
            # using yaml.safe_load instead of unsafe yaml.load.
            raw_data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in preset '{preset_name}': {exc}") from exc

    try:
        return ToolPreset.model_validate(raw_data)
    except ValidationError as exc:
        raise ValueError(f"Invalid preset schema in '{preset_name}': {exc}") from exc


def save_preset(preset: ToolPreset) -> Path:
    """Save a preset to disk with secure POSIX permissions.

    Args:
        preset: ToolPreset model instance to persist.

    Returns:
        Path to the saved preset file.
    """
    preset_path = safe_resolve_preset_path(preset.name)
    data = preset.model_dump()

    yaml_content = (
        f"# Preset: {preset.name}\n"
        f"# Auto-generated configuration file adhering to open-source standards.\n"
        + yaml.dump(data, sort_keys=False)
    )

    # SECURITY: Enforce owner-only read/write permissions (mode 0600 / rw-------)
    # using atomic O_CREAT with explicit file mode to prevent race conditions (TOCTOU).
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    mode = 0o600

    fd = os.open(str(preset_path), flags, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    return preset_path


def reset_all_configuration() -> None:
    """Purge all user-saved presets and restore factory defaults."""
    config_dir = get_config_dir()
    if config_dir.exists():
        for root, dirs, files in os.walk(config_dir, topdown=False):
            for file in files:
                (Path(root) / file).unlink(missing_ok=True)
            for d in dirs:
                (Path(root) / d).rmdir()
    load_preset("default")
