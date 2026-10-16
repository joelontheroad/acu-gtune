# SPDX-FileCopyrightText: 2026 Joel Greenberg
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Configuration and preset management adhering to XDG specs and security guidelines."""

import os
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

APP_NAME = "acu-gtune"


class TunerPreset(BaseModel):
    """Schema-validated tuner preset definition."""
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
    """Global application configuration model."""
    version: int = Field(default=1, description="Configuration schema version")
    default_preset: str = Field(default="default", description="Active preset name")
    preset: TunerPreset = Field(default_factory=TunerPreset)


def sanitize_log_path(path: str) -> str:
    """Scrub local username and home directory from log strings to protect privacy."""
    home_dir = str(Path.home())
    if home_dir and path.startswith(home_dir):
        return path.replace(home_dir, "~<USER>", 1)
    return path


def get_config_dir() -> Path:
    """Return the platform-appropriate configuration directory (XDG compliant)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        config_root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        config_root = Path(base) if base else Path.home() / ".config"

    target_dir = config_root / APP_NAME
    # Enforce POSIX mode 0700 (rwx------)
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(target_dir, 0o700)
            except OSError:
                pass
    return target_dir


def get_presets_dir() -> Path:
    """Return the presets subfolder within the config directory."""
    presets_dir = get_config_dir() / "presets"
    if not presets_dir.exists():
        presets_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(presets_dir, 0o700)
            except OSError:
                pass
    return presets_dir


def safe_resolve_preset_path(preset_name: str) -> Path:
    """
    Safely resolve a preset file path, preventing directory traversal attacks (CWE-22).
    """
    clean_name = preset_name.strip()
    if not clean_name.endswith(".yaml"):
        clean_name += ".yaml"

    base_dir = get_presets_dir().resolve()
    target_path = (base_dir / clean_name).resolve()

    # Prevent escaping allowed base directory
    try:
        target_path.relative_to(base_dir)
    except ValueError as exc:
        msg = f"Access denied: Preset '{preset_name}' escapes allowed directory"
        raise PermissionError(msg) from exc

    return target_path


def load_preset(preset_name: str = "default") -> ToolPreset:
    """Load and validate a YAML preset file using safe deserialization (CWE-502)."""
    preset_path = safe_resolve_preset_path(preset_name)

    if not preset_path.exists():
        # Create and persist default preset if missing
        default_preset = ToolPreset(name=preset_name)
        save_preset(default_preset)
        return default_preset

    try:
        with open(preset_path, "r", encoding="utf-8") as f:
            # Strictly use safe_load
            raw_data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in preset '{preset_name}': {exc}") from exc

    try:
        return ToolPreset.model_validate(raw_data)
    except ValidationError as exc:
        raise ValueError(f"Invalid preset schema in '{preset_name}': {exc}") from exc


def save_preset(preset: ToolPreset) -> Path:
    """Save a preset to disk with secure POSIX permissions (mode 0600)."""
    preset_path = safe_resolve_preset_path(preset.name)
    data = preset.model_dump()

    # Convert to commented YAML representation
    yaml_content = (
        f"# Preset: {preset.name}\n"
        f"# Auto-generated configuration file adhering to open-source standards.\n"
        + yaml.dump(data, sort_keys=False)
    )

    # Secure write with mode 0600 (rw-------)
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
    # Reinitialize default
    load_preset("default")
