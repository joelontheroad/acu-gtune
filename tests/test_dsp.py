# SPDX-FileCopyrightText: 2026 Joel Greenberg
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Test suite verifying high-precision DSP pitch detection, intonation, and cents accuracy."""

import math

import numpy as np
import pytest

from app.dsp import (
    TUNING_PRESETS,
    analyze_audio_frame,
    calculate_cents,
    calculate_intonation_delta,
    estimate_pitch_yin,
    estimate_signal_rms,
    frequency_to_nearest_note,
    midi_to_frequency,
    midi_to_note_name,
    note_name_to_frequency,
    note_name_to_midi,
    quantize_cents,
)


def _generate_harmonic_signal(
    freq: float,
    duration: float = 0.5,
    sr: int = 44100,
) -> np.ndarray:
    """Generate realistic string audio containing fundamental and upper harmonics."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    signal = (
        1.0 * np.sin(2 * np.pi * freq * t) +
        0.6 * np.sin(2 * np.pi * 2 * freq * t + 0.3) +
        0.3 * np.sin(2 * np.pi * 3 * freq * t + 0.7) +
        0.15 * np.sin(2 * np.pi * 4 * freq * t + 1.2)
    )
    return signal


def test_note_midi_conversions():
    """Verify standard MIDI note number and name calculations."""
    assert note_name_to_midi("A4") == 69
    assert note_name_to_midi("C4") == 60
    assert note_name_to_midi("E2") == 40
    assert note_name_to_midi("E1") == 28
    assert note_name_to_midi("B0") == 23

    assert midi_to_note_name(69) == "A4"
    assert midi_to_note_name(60) == "C4"
    assert midi_to_note_name(40) == "E2"

    assert round(midi_to_frequency(69), 2) == 440.0
    assert round(note_name_to_frequency("E2"), 4) == 82.4069
    assert round(note_name_to_frequency("E1"), 4) == 41.2034


def test_calculate_cents():
    """Verify logarithmic cents equation."""
    # An octave is 1200 cents
    assert round(calculate_cents(880.0, 440.0), 1) == 1200.0
    assert round(calculate_cents(440.0, 440.0), 4) == 0.0

    # 1 semitone is 100 cents
    semitone_up = 440.0 * (2.0 ** (1.0 / 12.0))
    assert round(calculate_cents(semitone_up, 440.0), 1) == 100.0

    # +0.1 cent shift
    cent_tenth_up = 440.0 * (2.0 ** (0.1 / 1200.0))
    assert round(calculate_cents(cent_tenth_up, 440.0), 2) == 0.10


def test_frequency_to_nearest_note():
    """Verify matching detected frequency to target notes and tuning presets."""
    note, target_hz, cents = frequency_to_nearest_note(440.0, a4_ref=440.0)
    assert note == "A4"
    assert target_hz == 440.0
    assert abs(cents) < 1e-4

    # Test with string filter
    guitar_strings = TUNING_PRESETS["guitar_6"]["standard"]
    note_e2, target_e2, cents_e2 = frequency_to_nearest_note(
        freq=82.5,
        a4_ref=440.0,
        allowed_notes=guitar_strings,
    )
    assert note_e2 == "E2"
    assert round(target_e2, 4) == 82.4069
    assert cents_e2 > 0  # slightly sharp


@pytest.mark.parametrize(
    "note_name,target_freq",
    [
        ("B0", 30.8677),   # 5-String Bass low B
        ("E1", 41.2034),   # 4-String Bass low E
        ("E2", 82.4069),   # Guitar Low E
        ("A2", 110.0000),  # Guitar A
        ("D3", 146.8324),  # Guitar D
        ("G3", 195.9977),  # Guitar G
        ("B3", 246.9417),  # Guitar B
        ("E4", 329.6276),  # Guitar High E
    ],
)
@pytest.mark.parametrize("cent_offset", [+0.10, -0.10, +0.05, -0.05])
def test_precision_yin_tenth_cent(note_name: str, target_freq: float, cent_offset: float):
    """Verify YIN pitch detection resolves offsets down to +/-0.05 cent."""
    f_input = target_freq * (2.0 ** (cent_offset / 1200.0))
    sr = 44100
    signal = _generate_harmonic_signal(freq=f_input, duration=0.4, sr=sr)

    f_est = estimate_pitch_yin(
        signal=signal,
        sample_rate=sr,
        min_freq=25.0,
        max_freq=1200.0,
    )

    detected_cents = 1200.0 * math.log2(f_est / target_freq)
    error_cents = abs(detected_cents - cent_offset)

    # Error must be well beneath the 0.1-cent tolerance (typically < 0.04 cents)
    assert error_cents < 0.05, (
        f"{note_name} at offset {cent_offset}c: detected {detected_cents:.4f}c "
        f"with error {error_cents:.5f}c (exceeds 0.05c limit)"
    )


def test_noise_gate_and_silence():
    """Verify silence below noise gate returns None."""
    silence = np.zeros(4096, dtype=np.float64)
    assert estimate_signal_rms(silence) == 0.0

    res = analyze_audio_frame(silence, noise_gate=0.005)
    assert res is None


def test_analyze_audio_frame_in_tune():
    """Verify complete frame analysis pipeline reports in_tune=True within 0.1 cent."""
    sr = 44100
    # Exactly in-tune A2 (110.0 Hz)
    sig = _generate_harmonic_signal(freq=110.0, duration=0.4, sr=sr)
    res = analyze_audio_frame(
        signal=sig,
        sample_rate=sr,
        allowed_notes=["E2", "A2", "D3", "G3", "B3", "E4"],
        a4_ref=440.0,
        tolerance_cents=0.1,
    )
    assert res is not None
    assert res.target_note == "A2"
    assert abs(res.cents) <= 0.1
    assert res.in_tune is True
    assert abs(res.slip_cps) < 0.05


def test_decaying_signal_continuity():
    """Verify that decaying signal with ambient low-frequency hum maintains pitch continuity."""
    sr = 44100
    duration = 0.4
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)

    f_string = 110.0  # A2 string
    # Decaying string signal (fading down to small amplitude)
    decay_envelope = np.exp(-t * 6.0) * 0.05
    string_signal = np.sin(2 * np.pi * f_string * t) * decay_envelope

    # Add low-frequency background noise (60 Hz AC electrical hum)
    hum_noise = 0.008 * np.sin(2 * np.pi * 60.0 * t)
    mixed_signal = string_signal + hum_noise

    # Without continuity, 60 Hz hum might overpower weak decaying tail
    # With continuity (expected_freq=110.0), it locks onto the true string frequency
    est_freq = estimate_pitch_yin(
        signal=mixed_signal,
        sample_rate=sr,
        min_freq=25.0,
        max_freq=1200.0,
        expected_freq=f_string,
    )

    cents_error = abs(1200.0 * math.log2(est_freq / f_string))
    # Must remain locked onto A2 (within 5c) rather than dropping to 60 Hz hum (>1000c away)
    assert cents_error < 5.0, f"Decaying signal drifted: est={est_freq:.2f} Hz vs {f_string:.2f} Hz"


def test_calculate_intonation_delta():
    """Verify bridge saddle calculation rules for intonation adjustment."""
    # Within +/-0.1 cent tolerance: Perfect
    delta_perfect, advice_perfect = calculate_intonation_delta(
        harmonic_cents=0.0, fretted_cents=0.05, tolerance=0.1
    )
    assert abs(delta_perfect - 0.05) < 1e-4
    assert advice_perfect == "PERFECT"

    # Fretted note is sharp: String is too short -> Move saddle back
    delta_sharp, advice_sharp = calculate_intonation_delta(
        harmonic_cents=0.2, fretted_cents=2.7, tolerance=0.1
    )
    assert abs(delta_sharp - 2.5) < 1e-4
    assert advice_sharp == "MOVE_BACK"

    # Fretted note is flat: String is too long -> Move saddle forward
    delta_flat, advice_flat = calculate_intonation_delta(
        harmonic_cents=0.5, fretted_cents=-1.8, tolerance=0.1
    )
    assert abs(delta_flat - (-2.3)) < 1e-4
    assert advice_flat == "MOVE_FORWARD"


def test_frequency_to_nearest_note_octave_harmonics():
    """Verify that multi-octave matching correctly identifies 12th fret and harmonics."""
    guitar_strings = TUNING_PRESETS["guitar_6"]["standard"]

    # Open E2 (~82.41 Hz)
    note_open, target_open, cents_open = frequency_to_nearest_note(
        freq=82.4069, allowed_notes=guitar_strings, allow_octaves=True
    )
    assert note_open == "E2"
    assert round(target_open, 2) == 82.41
    assert abs(cents_open) < 0.01

    # 12th fret E2 harmonic / fretted note (2x freq = 164.81 Hz)
    note_12th, target_12th, cents_12th = frequency_to_nearest_note(
        freq=164.8138, allowed_notes=guitar_strings, allow_octaves=True
    )
    assert note_12th == "E2"
    assert round(target_12th, 2) == 164.81
    assert abs(cents_12th) < 0.01

    # High E4 string 12th fret (2x 329.63 Hz = 659.26 Hz)
    note_e4_12th, target_e4_12th, cents_e4_12th = frequency_to_nearest_note(
        freq=659.255, allowed_notes=guitar_strings, allow_octaves=True
    )
    assert note_e4_12th == "E4"
    assert round(target_e4_12th, 2) == 659.26
    assert abs(cents_e4_12th) < 0.01


def test_estimate_pitch_yin_extended_range_3200hz():
    """Verify YIN pitch estimation handles frequencies up to 3200 Hz accurately."""
    sr = 44100
    # Test high harmonic at 2000 Hz (tau ~ 22 samples at 44.1kHz)
    f_test = 2000.0
    signal = _generate_harmonic_signal(freq=f_test, duration=0.25, sr=sr)
    f_est = estimate_pitch_yin(
        signal=signal,
        sample_rate=sr,
        min_freq=25.0,
        max_freq=3200.0,
    )
    cents_err = abs(1200.0 * math.log2(f_est / f_test))
    assert cents_err < 2.5, f"YIN high frequency error: {cents_err:.4f} cents"


def test_quantize_cents():
    """Verify that cents quantizing rounds cleanly to 0.2 and 0.5 step sizes."""
    # 0.2 cent stepping
    assert quantize_cents(0.04, step=0.2) == 0.0
    assert quantize_cents(0.12, step=0.2) == 0.2
    assert quantize_cents(0.28, step=0.2) == 0.2
    assert quantize_cents(0.31, step=0.2) == 0.4
    assert quantize_cents(-0.19, step=0.2) == -0.2
    assert quantize_cents(-0.32, step=0.2) == -0.4

    # 0.5 cent stepping
    assert quantize_cents(0.24, step=0.5) == 0.0
    assert quantize_cents(0.26, step=0.5) == 0.5
    assert quantize_cents(-0.76, step=0.5) == -1.0


