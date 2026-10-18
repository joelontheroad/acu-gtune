# SPDX-FileCopyrightText: 2026 Joel Greenberg
# SPDX-License-Identifier: AGPL-3.0-or-later

"""High-precision pitch detection and intonation analysis engine for guitar and bass.

Implements time-domain fundamental frequency estimation via the YIN algorithm
with parabolic sub-sample refinement, spectral FFT interpolation, logarithmic
cents deviation calculation, and bridge saddle intonation compensation analysis.

Prior Art & Academic Citations:
    - Fundamental Pitch Extraction (YIN):
      A. de Cheveigné and H. Kawahara (2002), "YIN, a fundamental frequency estimator
      for speech and music," The Journal of the Acoustical Society of America, 111(4),
      pp. 1917–1930. (Public academic literature).
    - Spectral Parabolic Sub-Bin Peak Interpolation:
      T. Grandke (1983), "Interpolation algorithms for discrete Fourier transforms of
      weighted signals," IEEE Trans. Instrum. Meas., IM-32(2), pp. 350-355;
      J.O. Smith and X. Serra (1987), "PARSHL: An analysis/synthesis system for
      polyphonic music," Proc. ICMC.
    - Stroboscopic Multi-Ring Slip Analysis:
      R.W. Young and A. Loomis / C.G. Conn Ltd. (1942), "Stroboscope," U.S. Patent No.
      2,286,030 (expired, public domain);
      D.J. Carpenter / Peterson Electro-Musical Products (2003), "Electronic strobe
      tuning aid," U.S. Patent No. 6,580,024 B2 (expired 2021, public domain).
    - Bridge Saddle Intonation Mechanics:
      Mersenne acoustic law of vibrating strings (f = (1 / 2L) * sqrt(T / mu));
      B. Feiten (1999), "Method and apparatus for fully intonating a stringed instrument,"
      U.S. Patent No. 5,955,689 (expired 2017, public domain).
"""

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

# Standard 12 chromatic note names
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Instrument tuning note maps
TUNING_PRESETS: Dict[str, Dict[str, List[str]]] = {
    "guitar_6": {
        "standard": ["E2", "A2", "D3", "G3", "B3", "E4"],
        "drop_d": ["D2", "A2", "D3", "G3", "B3", "E4"],
        "dadgad": ["D2", "A2", "D3", "G3", "A3", "D4"],
        "open_g": ["D2", "G2", "D3", "G3", "B3", "D4"],
        "open_d": ["D2", "A2", "D3", "F#3", "A3", "D4"],
        "half_step": ["D#2", "G#2", "C#3", "F#3", "A#3", "D#4"],
    },
    "guitar_7": {
        "standard": ["B1", "E2", "A2", "D3", "G3", "B3", "E4"],
        "drop_a": ["A1", "E2", "A2", "D3", "G3", "B3", "E4"],
    },
    "bass_4": {
        "standard": ["E1", "A1", "D2", "G2"],
        "drop_d": ["D1", "A1", "D2", "G2"],
    },
    "bass_5": {
        "standard": ["B0", "E1", "A1", "D2", "G2"],
    },
    "chromatic": {
        "all": [],
    },
}


class TuningResult(BaseModel):
    """Result of high-precision intonation and pitch analysis.

    Attributes:
        detected_freq: Estimated fundamental frequency in Hertz.
        target_note: Target musical note name with octave (e.g. 'E2', 'A4').
        target_freq: Target note reference frequency in Hertz.
        cents: Pitch deviation from target note in cents.
        in_tune: Boolean flag indicating if deviation is within tolerance.
        slip_cps: Stroboscopic slip rate in cycles per second (detected - target).
        rms: Root-mean-square amplitude of analyzed audio buffer.
    """

    detected_freq: float = Field(..., description="Estimated fundamental frequency in Hertz")
    target_note: str = Field(..., description="Target musical note name with octave (e.g. E2)")
    target_freq: float = Field(..., description="Target note reference frequency in Hertz")
    cents: float = Field(..., description="Pitch deviation from target note in cents")
    in_tune: bool = Field(..., description="True if pitch deviation is within tolerance")
    slip_cps: float = Field(..., description="Stroboscopic slip rate in cycles per second")
    rms: float = Field(..., description="Root-mean-square amplitude of analyzed audio buffer")


def note_name_to_midi(note_str: str) -> int:
    """Convert a musical note string to its standard MIDI note number.

    Args:
        note_str: Note name with octave (e.g. 'E2', 'C#3', 'A4').

    Returns:
        MIDI note number where A4 (440 Hz) is 69 and C-1 is 0.

    Raises:
        ValueError: If the note string format is invalid or pitch name is unknown.
    """
    clean = note_str.strip().upper()
    if clean[-1].isdigit():
        octave = int(clean[-1])
        pitch = clean[:-1]
    else:
        raise ValueError(f"Invalid note format: '{note_str}'")

    if pitch not in NOTE_NAMES:
        raise ValueError(f"Unknown note pitch '{pitch}' in '{note_str}'")

    semitone = NOTE_NAMES.index(pitch)
    # MIDI note 0 is C-1, note 12 is C0, note 69 is A4 (440 Hz)
    return (octave + 1) * 12 + semitone


def midi_to_note_name(midi_number: int) -> str:
    """Convert a MIDI note number to musical note name with octave.

    Args:
        midi_number: MIDI note number (0 to 127).

    Returns:
        Formatted musical note name (e.g. 'A4', 'C4', 'E2').
    """
    octave = (midi_number // 12) - 1
    pitch = NOTE_NAMES[midi_number % 12]
    return f"{pitch}{octave}"


def midi_to_frequency(midi_number: int, a4_ref: float = 440.0) -> float:
    """Convert a MIDI note number to equal-temperament frequency in Hertz.

    Args:
        midi_number: MIDI note number.
        a4_ref: Reference concert pitch calibration in Hertz.

    Returns:
        Calculated frequency in Hertz.
    """
    return a4_ref * (2.0 ** ((midi_number - 69) / 12.0))


def note_name_to_frequency(note_str: str, a4_ref: float = 440.0) -> float:
    """Convert a musical note name string to target frequency in Hertz.

    Args:
        note_str: Musical note name with octave.
        a4_ref: Reference concert pitch calibration in Hertz.

    Returns:
        Target frequency in Hertz.
    """
    midi_num = note_name_to_midi(note_str)
    return midi_to_frequency(midi_num, a4_ref=a4_ref)


def calculate_cents(detected_freq: float, target_freq: float) -> float:
    """Compute pitch deviation in cents: 1200 * log2(detected / target).

    Args:
        detected_freq: Measured frequency in Hertz.
        target_freq: Target reference frequency in Hertz.

    Returns:
        Pitch deviation in cents, where 100 cents equals one equal-temperament semitone.
    """
    # SECURITY: Guard against math domain errors (log2 of zero or negative frequency).
    if detected_freq <= 0 or target_freq <= 0:
        return 0.0
    return 1200.0 * math.log2(detected_freq / target_freq)


def quantize_cents(cents: float, step: float = 0.2) -> float:
    """Quantize cents deviation to a discrete step size for visual stability.

    Stabilizes display readouts against microscopic physical finger pressure
    and wood deflection variations.

    Args:
        cents: Raw calculated pitch deviation in cents.
        step: Display quantization step size (e.g. 0.2 cents).

    Returns:
        Quantized cents value rounded to nearest step multiple.
    """
    if step <= 0.0:
        return cents
    return round(round(cents / step) * step, 4)


def calculate_intonation_delta(
    harmonic_cents: float, fretted_cents: float, tolerance: float = 0.1
) -> Tuple[float, str]:
    """Calculate intonation delta between 12th-fret harmonic and fretted note.

    Computes delta = fretted_cents - harmonic_cents and provides bridge saddle
    compensation advice based on Mersenne string acoustics and lutherie prior art
    (ref. expired U.S. Patent No. 5,955,689).

    Args:
        harmonic_cents: Measured pitch deviation of 12th-fret harmonic in cents.
        fretted_cents: Measured pitch deviation of 12th-fret fretted note in cents.
        tolerance: Matching tolerance threshold in cents.

    Returns:
        Tuple of (delta_cents, saddle_recommendation):
            - "MOVE_BACK": Fretted note sharp (string too short -> lengthen saddle).
            - "MOVE_FORWARD": Fretted note flat (string too long -> shorten saddle).
            - "PERFECT": Intonation matched within tolerance.
    """
    delta = round(fretted_cents - harmonic_cents, 3)
    if delta > tolerance:
        return delta, "MOVE_BACK"
    elif delta < -tolerance:
        return delta, "MOVE_FORWARD"
    return delta, "PERFECT"


def frequency_to_nearest_note(
    freq: float,
    a4_ref: float = 440.0,
    allowed_notes: Optional[List[str]] = None,
    allow_octaves: bool = True,
) -> Tuple[str, float, float]:
    """Find the closest musical note to the given frequency.

    When allow_octaves is True and allowed_notes are specified, candidate frequencies
    include open fundamental, 12th fret octave (2x), and upper harmonics (3x, 4x),
    allowing seamless intonation checking on the selected string.

    Args:
        freq: Detected frequency in Hertz.
        a4_ref: Reference concert pitch calibration in Hertz.
        allowed_notes: Optional list of note names to restrict matching to.
        allow_octaves: Whether to evaluate harmonic multiples of allowed notes.

    Returns:
        Tuple of (note_name, target_freq, cents_deviation).
    """
    if freq <= 0:
        return ("--", 0.0, 0.0)

    if allowed_notes:
        best_note = allowed_notes[0]
        best_target_freq = note_name_to_frequency(best_note, a4_ref=a4_ref)
        min_abs_cents = abs(calculate_cents(freq, best_target_freq))

        multipliers = [1.0, 2.0, 3.0, 4.0] if allow_octaves else [1.0]

        for candidate in allowed_notes:
            cand_base = note_name_to_frequency(candidate, a4_ref=a4_ref)
            for mult in multipliers:
                cand_freq = cand_base * mult
                cents = abs(calculate_cents(freq, cand_freq))
                if cents < min_abs_cents:
                    min_abs_cents = cents
                    best_note = candidate
                    best_target_freq = cand_freq

        cents_dev = calculate_cents(freq, best_target_freq)
        return (best_note, best_target_freq, cents_dev)

    # Chromatic matching
    semitones_from_a4 = 12.0 * math.log2(freq / a4_ref)
    midi_num = int(round(69 + semitones_from_a4))
    midi_num = max(0, min(127, midi_num))
    target_freq = midi_to_frequency(midi_num, a4_ref=a4_ref)
    note_name = midi_to_note_name(midi_num)
    cents_dev = calculate_cents(freq, target_freq)
    return (note_name, target_freq, cents_dev)


def estimate_signal_rms(signal: np.ndarray) -> float:
    """Calculate the Root Mean Square (RMS) amplitude of an audio buffer.

    Args:
        signal: 1D array of audio samples.

    Returns:
        Root-mean-square amplitude value.
    """
    # SECURITY: Defend against division by zero and NaN propagation on empty audio buffers.
    if len(signal) == 0:
        return 0.0
    return float(np.sqrt(np.mean(signal.astype(np.float64) ** 2)))


def estimate_pitch_yin(
    signal: np.ndarray,
    sample_rate: int = 44100,
    min_freq: float = 25.0,
    max_freq: float = 3200.0,
    threshold: float = 0.15,
    expected_freq: Optional[float] = None,
) -> float:
    """Estimate fundamental frequency using the YIN algorithm with parabolic interpolation.

    Computes the Cumulative Mean Normalized Difference Function (CMNDF) via fast correlation,
    locates the dip below the aperiodic threshold, refines the minimum using sub-sample
    parabolic fitting, and optionally restricts search to a continuity window to prevent
    octave hopping on decaying notes.

    Based on the open academic algorithm by A. de Cheveigné & H. Kawahara (JASA 2002).

    Args:
        signal: Audio sample buffer.
        sample_rate: Sampling frequency in Hertz.
        min_freq: Lower frequency search bound in Hertz.
        max_freq: Upper frequency search bound in Hertz.
        threshold: YIN dip threshold (typically 0.10 to 0.15).
        expected_freq: Optional prior frequency in Hertz for continuity locking.

    Returns:
        Estimated fundamental frequency in Hertz, or 0.0 if unvoiced.
    """
    # SECURITY: Guard against empty buffers and constrain lag tau within valid array bounds
    # to prevent index errors and out-of-bounds reads.
    if len(signal) == 0:
        return 0.0

    max_tau = int(sample_rate / min_freq)
    min_tau = int(sample_rate / max_freq)

    needed_len = 2 * max_tau
    if len(signal) < needed_len:
        signal = np.pad(signal, (0, needed_len - len(signal)))

    w = max_tau
    x = signal[:w + max_tau].astype(np.float64)

    # Compute difference function using fast correlation:
    # d(tau) = sum_{j=0}^{w-1} (x[j] - x[j+tau])^2
    x_sq = x ** 2
    x_cum_sq = np.concatenate(([0.0], np.cumsum(x_sq)))

    term1 = x_cum_sq[w] - x_cum_sq[0]
    term2 = x_cum_sq[w: w + max_tau + 1] - x_cum_sq[0: max_tau + 1]

    # Fast cross-term correlation: conv has length max_tau + 1
    conv = np.correlate(x[:w + max_tau], x[:w], mode="valid")

    d = term1 + term2 - 2.0 * conv
    d = np.maximum(d, 0.0)

    # Cumulative Mean Normalized Difference Function (CMNDF)
    cmndf = np.zeros(max_tau + 1, dtype=np.float64)
    cmndf[0] = 1.0
    cumsum = 0.0
    for tau in range(1, max_tau + 1):
        cumsum += d[tau]
        if cumsum > 0:
            cmndf[tau] = (d[tau] * tau) / cumsum
        else:
            cmndf[tau] = 1.0

    # Search window: if expected_freq is provided, prioritize continuity window (+/-60 cents)
    search_min = min_tau
    search_max = max_tau
    if expected_freq and expected_freq > 0:
        exp_tau = sample_rate / expected_freq
        win_min = max(min_tau, int(exp_tau * (2.0 ** (-60.0 / 1200.0))))
        win_max = min(max_tau, int(math.ceil(exp_tau * (2.0 ** (60.0 / 1200.0)))))
        if win_min < win_max:
            for tau in range(win_min, win_max):
                if cmndf[tau] < threshold:
                    while tau + 1 < win_max and cmndf[tau + 1] < cmndf[tau]:
                        tau += 1
                    chosen_tau = tau
                    break
            else:
                chosen_tau = None
        else:
            chosen_tau = None
    else:
        chosen_tau = None

    # Global search across audible bounds if no continuity minimum was resolved
    if chosen_tau is None:
        for tau in range(search_min, search_max):
            if cmndf[tau] < threshold:
                while tau + 1 < search_max and cmndf[tau + 1] < cmndf[tau]:
                    tau += 1
                chosen_tau = tau
                break

    if chosen_tau is None:
        chosen_tau = search_min + int(np.argmin(cmndf[search_min:search_max]))

    # Quadratic / parabolic interpolation around minimum for fractional sample delay
    tau = chosen_tau
    if 0 < tau < max_tau:
        alpha = cmndf[tau - 1]
        beta = cmndf[tau]
        gamma = cmndf[tau + 1]
        denom = 2.0 * (alpha - 2.0 * beta + gamma)
        delta = (alpha - gamma) / denom if abs(denom) > 1e-12 else 0.0
        tau_exact = tau + delta
    else:
        tau_exact = float(tau)

    if tau_exact <= 0:
        return 0.0

    return float(sample_rate / tau_exact)


def estimate_pitch_fft(
    signal: np.ndarray,
    sample_rate: int = 44100,
    zero_pad_factor: int = 8,
) -> float:
    """Refine spectral peak frequency using parabolic-interpolated FFT.

    Applies a Hann window, zero-pads the signal to increase spectral bin density,
    and interpolates around the maximum FFT magnitude bin (Grandke 1983; Smith & Serra 1987).

    Args:
        signal: Audio sample buffer.
        sample_rate: Sampling frequency in Hertz.
        zero_pad_factor: Factor by which to zero-pad the signal for frequency resolution.

    Returns:
        Refined spectral peak frequency in Hertz.
    """
    n = len(signal)
    if n == 0:
        return 0.0

    window = 0.5 * (1.0 - np.cos(2.0 * np.pi * np.arange(n) / (n - 1)))
    windowed = signal.astype(np.float64) * window

    n_pad = n * zero_pad_factor
    spectrum = np.abs(np.fft.rfft(windowed, n=n_pad))

    k_peak = int(np.argmax(spectrum[1:])) + 1
    if 0 < k_peak < len(spectrum) - 1:
        alpha = spectrum[k_peak - 1]
        beta = spectrum[k_peak]
        gamma = spectrum[k_peak + 1]
        denom = alpha - 2.0 * beta + gamma
        delta = 0.5 * (alpha - gamma) / denom if abs(denom) > 1e-12 else 0.0
        exact_bin = k_peak + delta
    else:
        exact_bin = float(k_peak)

    return float(exact_bin * sample_rate / n_pad)


def analyze_audio_frame(
    signal: np.ndarray,
    sample_rate: int = 44100,
    allowed_notes: Optional[List[str]] = None,
    a4_ref: float = 440.0,
    tolerance_cents: float = 0.1,
    noise_gate: float = 0.005,
    expected_freq: Optional[float] = None,
) -> Optional[TuningResult]:
    """Analyze an audio buffer to detect pitch, nearest musical note, and cents offset.

    Returns None if the root-mean-square amplitude is below the noise gate or no
    valid fundamental pitch can be resolved.

    Args:
        signal: Audio sample buffer normalized to [-1.0, 1.0].
        sample_rate: Sampling frequency in Hertz.
        allowed_notes: Filter set of allowed musical note strings (e.g. ['E2', 'A2']).
        a4_ref: Reference concert pitch calibration in Hertz.
        tolerance_cents: In-tune window threshold in cents.
        noise_gate: RMS amplitude threshold below which signal is treated as silence.
        expected_freq: Optional expected frequency in Hertz for continuity tracking.

    Returns:
        Populated TuningResult object, or None if signal is below noise gate or unvoiced.
    """
    rms = estimate_signal_rms(signal)
    # SECURITY: Filter low-amplitude noise below threshold to prevent CPU spikes and
    # false-positive pitch calculations on background acoustic noise.
    if rms < noise_gate:
        return None

    # Estimate fundamental frequency using YIN with continuity tracking
    detected_freq = estimate_pitch_yin(
        signal=signal,
        sample_rate=sample_rate,
        min_freq=25.0,
        max_freq=3200.0,
        expected_freq=expected_freq,
    )

    if detected_freq <= 0:
        return None

    target_note, target_freq, cents_dev = frequency_to_nearest_note(
        freq=detected_freq,
        a4_ref=a4_ref,
        allowed_notes=allowed_notes,
    )

    in_tune = abs(cents_dev) <= tolerance_cents
    slip_cps = detected_freq - target_freq

    return TuningResult(
        detected_freq=round(detected_freq, 4),
        target_note=target_note,
        target_freq=round(target_freq, 4),
        cents=round(cents_dev, 3),
        in_tune=in_tune,
        slip_cps=round(slip_cps, 4),
        rms=round(rms, 5),
    )
