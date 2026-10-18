# SPDX-FileCopyrightText: 2026 Joel Greenberg
# SPDX-License-Identifier: AGPL-3.0-or-later

# Technical Disclosure & Defensive Publication: High-Precision Stroboscopic Musical Instrument Pitch & Intonation Analyzer

**Author:** Joel Greenberg  
**Initial Public Disclosure Date:** October 18, 2026  
**Repository:** [https://github.com/joelontheroad/acu-gtune](https://github.com/joelontheroad/acu-gtune)  
**Legal Purpose:** Prior Art Technical Disclosure under **35 U.S.C. § 102(a)(1)** to permanently ensure that the methods, signal processing pipelines, and user interface workflows disclosed herein remain in the public domain and cannot be patented by third parties or non-practicing entities.

---

## 1. Technical Abstract

This publication discloses the mathematical models, digital signal processing (DSP) architecture, and human-computer interface (HCI) state machines implemented in `acu-gtune`, an open-source, high-precision stroboscopic musical instrument tuner and intonation analyzer accurate to $\pm 0.1\text{ cent}$. The system combines sub-sample YIN period extraction, dynamic continuity-window search bounds, decoupled attack-transient unlatching, a visual decay-hold state machine, and a dual-slot harmonic-versus-fretted bridge saddle displacement vector calculation engine.

---

## 2. Signal Processing Pipeline & Algorithms

### 2.1 Sub-Sample Time-Domain Fundamental Pitch Extraction (YIN)

The audio stream is ingested at sampling rate $f_s \ge 44,100\text{ Hz}$. For a sample buffer $x[n]$ of length $W + \tau_{\max}$, the squared difference function $d_t(\tau)$ is computed via fast correlation:

$$d_t(\tau) = \sum_{j=0}^{W-1} \left( x[j] - x[j+\tau] \right)^2$$

The Cumulative Mean Normalized Difference Function (CMNDF) $d'_t(\tau)$ is derived:

$$d'_t(\tau) = \begin{cases} 1, & \tau = 0 \\ \frac{d_t(\tau)}{\frac{1}{\tau} \sum_{j=1}^{\tau} d_t(j)}, & \tau > 0 \end{cases}$$

An aperiodic threshold $\theta = 0.15$ determines voiced periodicity. Sub-sample fractional lag $\tau_{\text{exact}}$ is resolved around the discrete minimum $\tau$ using parabolic peak interpolation:

$$\delta = \frac{d'(\tau - 1) - d'(\tau + 1)}{2 \left( d'(\tau - 1) - 2d'(\tau) + d'(\tau + 1) \right)}$$

$$\tau_{\text{exact}} = \tau + \delta, \quad f_0 = \frac{f_s}{\tau_{\text{exact}}}$$

*(Ref: A. de Cheveigné & H. Kawahara, "YIN, a fundamental frequency estimator for speech and music," JASA 111(4), pp. 1917–1930, 2002).*

---

### 2.2 Dynamic Continuity-Window Tracking with Attack-Transient Unlatching

To prevent octave jumping and sub-harmonic latching during string sustain decay, the algorithm implements a dynamic continuity-locking search window:

1. **Continuity Window Definition**: When an active note is vibrating at prior frequency $f_{\text{prior}}$, the search range $[\tau_{\min}, \tau_{\max}]$ is dynamically restricted to a $\pm 45\text{ cent}$ interval around the expected lag $\tau_{\text{prior}} = f_s / f_{\text{prior}}$:
   $$\tau_{\text{low}} = \max\left(\tau_{\min}, \left\lfloor \tau_{\text{prior}} \cdot 2^{-45/1200} \right\rfloor\right)$$
   $$\tau_{\text{high}} = \min\left(\tau_{\max}, \left\lceil \tau_{\text{prior}} \cdot 2^{45/1200} \right\rceil\right)$$
2. **Attack Transient Detector**: An attack detector continuously computes the Root Mean Square (RMS) energy difference between consecutive analysis frames:
   $$\Delta \text{RMS} = \text{RMS}[k] - \text{RMS}[k-1]$$
   If $\Delta \text{RMS} > 0.003$ and $\text{RMS}[k] \ge 0.005$, an attack transient is triggered, which immediately unlatches the continuity constraint ($\tau_{\text{prior}} = \text{None}$) and restores global wideband search bounds ($25\text{ Hz} \le f_0 \le 3200\text{ Hz}$).

---

### 2.3 Decoupled Audio Ingestion & Visual Decay-Hold State Machine

Decaying vibrating guitar strings experience rapid amplitude attenuation while the vibrational pitch remains stable. Traditional tuners suffer from needle flutter or false flatting as the signal drops into ambient background room noise.

`acu-gtune` implements a 3-state decoupled state machine:
- **`IDLE`**: Awaiting pluck; stroboscopic disc rotates at a gentle idle speed ($\approx 0.35\text{ rev/s}$); needle rests in standby center.
- **`TRACKING`**: RMS $\ge 0.005$; real-time YIN pitch tracking updates the rotational slip velocity $\omega = 2\pi (f_0 - f_{\text{target}}) \cdot 0.3$ and horizontal cents needle position. Exponential Moving Average (EMA, $\alpha = 0.35$) stabilizes display readouts against microscopic finger deflection.
- **`HOLD`**: When RMS drops below tracking threshold, the UI transitions to a freeze latch for a duration of $T_{\text{hold}} = 3000\text{ ms}$. During this window:
  - The stroboscopic pattern remains completely stationary at its last known phase.
  - The cents needle remains frozen at its last stable reading.
  - The underlying Web Audio analysis loop continues running asynchronously, immediately resuming `TRACKING` if a new attack transient is detected.

---

## 3. Dual-Slot Harmonic-vs-Fretted Bridge Saddle Compensation Vector Engine

To facilitate guitar intonation setup without manual string-pair switching:

1. **Dual Storage Slots**: The analyzer maintains two distinct measurement slots: `harmonicCapture` (12th-fret harmonic) and `frettedCapture` (12th-fret fretted note).
2. **Harmonic Tier Recognition**: Target frequencies evaluate harmonic multiples $m \in \{1.0, 2.0, 3.0, 4.0\}$ of the string fundamental:
   - $1.0\times$: Open string fundamental.
   - $2.0\times$: 12th-fret octave / 12th-fret natural harmonic.
   - $3.0\times, 4.0\times$: Upper harmonics.
3. **Intonation Delta Calculation**:
   $$\Delta_{\text{cents}} = \text{Cents}_{\text{fretted}} - \text{Cents}_{\text{harmonic}}$$
4. **Automated Bridge Saddle Motion Advice**:
   - $\Delta_{\text{cents}} > +\text{tolerance} \implies \textbf{"FRETTED IS SHARP} \to \textbf{MOVE SADDLE BACK (Lengthen String)}"$.
   - $\Delta_{\text{cents}} < -\text{tolerance} \implies \textbf{"FRETTED IS FLAT} \to \textbf{MOVE SADDLE FORWARD (Shorten String)}"$.
   - $|\Delta_{\text{cents}}| \le \text{tolerance} \implies \textbf{"INTONATION PERFECT"}$.
5. **Auto-Advance Flow**: Upon detecting note decay after a 12th-harmonic measurement, the interface automatically advances the active slot to `fretted`, ready to capture the fretted note on the next pluck without requiring user touch or keyboard input.

---

## 4. Prior Art & Public Domain Grounding

The methods implemented in this project are grounded in expired patents and public academic literature:
1. **Concentric Stroboscopic Pattern**: C.G. Conn Ltd. / R.W. Young and A. Loomis, *"Stroboscope"*, U.S. Patent No. 2,286,030 (filed 1938, issued 1942; expired, public domain).
2. **Virtual Electronic Strobe Emulation**: Peterson Electro-Musical Products / D.J. Carpenter, *"Electronic strobe tuning aid"*, U.S. Patent No. 6,580,024 B2 (filed Jan 11, 2001, issued Jun 17, 2003; expired Jan 11, 2021, public domain).
3. **Microprocessor Temperament Tables**: Peterson Electro-Musical Products, *"Strobe tuner"*, U.S. Patent No. 5,877,443 A (issued 1999; expired 2017, public domain).
4. **Guitar Intonation Comparison**: B. Feiten, *"Method and apparatus for fully intonating a stringed instrument"*, U.S. Patent No. 5,955,689 (issued 1999; expired 2017, public domain).
5. **YIN Pitch Estimation**: A. de Cheveigné & H. Kawahara, *"YIN, a fundamental frequency estimator for speech and music"*, J. Acoust. Soc. Am., 111(4), pp. 1917–1930, 2002 (unencumbered academic publication).

---

## 5. Licensing & Community Freedom

This technical disclosure and all associated software source code are published under the **GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)**. Under Section 11 of the AGPLv3, all contributors grant downstream users an irrevocable, royalty-free patent license under any essential patent claims, ensuring that the software remains free and unencumbered in perpetuity.
