# Classical Signal-Processing Approach for Background Music Removal

**Status:** Planning document — no code implemented yet
**Created:** 2026-09-16
**Target project:** ClearVoice (`bgmusicremove`) as an alternative to the current Demucs-based pipeline
**Purpose:** Design a vocal-isolation method built entirely on classical DSP that is dramatically cheaper and easier to host, and define where its quality trade-offs are acceptable.

---

## 0. Executive Summary

The current ClearVoice pipeline isolates vocals with Demucs v4 (`htdemucs_ft`), which delivers
the best quality but demands torch, GPU-class hardware for speed, and multi-GB deployments.
This document plans a **classical signal-processing alternative** — stereo center extraction,
frequency masking, harmonic/percussive separation, and repetition-based accompaniment
estimation, fused with soft spectral masks — implementable with `numpy`, `scipy`, `librosa`,
and `soundfile` alone.

**Expected outcome:** noticeably lower separation quality than Demucs (roughly 4–8 dB vs
13–16 dB SDR on vocals), but processing that runs **tens of times faster than real time on the
existing 4-core VPS**, in a Docker image an order of magnitude smaller, with zero model
downloads. Recommended positioning: a "fast preview" tier, a fallback provider, and a
privacy/local mode — not a full replacement for the AI pipeline.

---

## 1. Methodology Overview

### 1.1 Why classical separation works at all

Mainstream stereo pop productions obey a set of mixing conventions that classical DSP can
exploit. Every technique below relies on one or more of these assumptions:

- **A1 — Center vocals:** Lead vocals are almost always panned to the center, so left and
  right channels carry the vocal at near-equal amplitude. Many instruments (guitars, keys,
  synths, backing vocals) are panned wide.
- **A2 — Vocal band:** Vocal energy lives mostly between ~100 Hz and ~8 kHz, with the
  strongest content between ~200 Hz and ~4 kHz (fundamentals 85–255 Hz plus harmonics).
- **A3 — Harmonic vs percussive:** Vocals are sustained, harmonic signals; drums and
  percussive transients are noise-like bursts spread across frequency.
- **A4 — Repetition asymmetry:** Instrumental accompaniment repeats (loops, riffs, chord
  cycles); the lead vocal almost never repeats exactly.

When a track violates these assumptions (mono files, vocals panned wide, dense modern
mixes, heavy reverb), classical methods degrade quickly — this is the core trade-off against
Demucs, which learns content instead of relying on conventions.

### 1.2 Technique 1 — Center-channel (mid/side) extraction (uses A1)

Convert the stereo signal to mid/side:

    mid(t)  = (L(t) + R(t)) / 2        side(t) = (L(t) - R(t)) / 2

A per-time-frequency-bin **center-dominance cue** measures how "mono" (centered) each bin is:

    C(f, t) = 1 - |L(f,t) - R(f,t)| / (|L(f,t) + R(f,t)| + eps)

- Classic karaoke machines do the inverse (`L - R`) to *remove* the center channel; we use
  `C(f,t)` as a keep-weight to *retain* centered content, which is where the vocal lives.
- **Known bleed:** bass, kick, snare, and lead guitar are also frequently centered, so this
  cue alone leaks them into the vocal output. It must be combined with the band and
  percussive cues below (bass removed by band weighting, drums by HPSS).

### 1.3 Technique 2 — Frequency-band weighting (uses A2)

Apply a soft spectral weighting that emphasizes the vocal band (e.g., gentle passband
120 Hz–8 kHz with smooth, not brick-wall, rolloffs). This removes basslines and sub content
almost entirely. Limitation: cymbals and bright synths overlap the top of the vocal band and
survive — acceptable bleed, further reduced by HPSS.

### 1.4 Technique 3 — Harmonic/percussive separation — HPSS (uses A3)

Median-filter the magnitude spectrogram two ways (Fitzgerald, 2010):

- Median across **time** (per frequency bin) → keeps sustained/harmonic content
- Median across **frequency** (per time frame) → keeps transients/percussive content

`librosa.decompose.hpss` implements this directly. Vocals belong to the harmonic component;
kick, snare, and toms fall into the percussive component, so the percussive ratio is used to
**suppress drums** in the vocal mask. Optional enhancement: the soft-mask variant
(`librosa.decompose.nn_filter`-style Wiener filtering between the two components).

### 1.5 Technique 4 — Repetition-based accompaniment estimation — REP-SIM (uses A4)

The strongest classical vocal extractor (Rafii & Pardo, "Repeating Pattern Extraction
Technique"):

1. Build a similarity/recurrence matrix over spectral frames
   (`librosa.segment.recurrence_matrix`).
2. For each frame, find its most similar past/future frames (repeats of the backing loop).
3. Take an element-wise **median of the repeating frames** → an estimate of the
   repeating accompaniment alone.
4. Vocal estimate = mixture spectrogram − accompaniment estimate (with floors to avoid
   negative values).

Because the vocal does not repeat, it vanishes from the median and is recovered as the
residual. This is the most computationally expensive stage (O(N²) similarity for N frames,
mitigated by checking only bar-aligned candidates) and the biggest quality lever.

### 1.6 Masking and phase handling

- All cues are converted to **soft ratio masks** in [0, 1] per TF bin (Wiener-style:
  `mask = vocal_est² / (vocal_est² + other_est² + eps)` — soft masks avoid the "musical
  noise" of hard binary gates).
- Masks are applied to the **complex STFT of the mixture**, preserving the original phase,
  then inverted with overlap-add ISTFT (COLA-compliant windowing). Preserving mixture phase
  avoids the metallic warble that naive phase reconstruction produces; a phase vocoder is
  **not** needed for this task (it would only matter for time-stretching, which is out of
  scope). Griffin-Lim re-estimation is a fallback only if future experiments require it.
- Masks are smoothed temporally (median filter over ~3–9 frames) to reduce flickering.

### 1.7 Cue fusion

Final vocal mask = element-wise (geometric) product of the individual cue masks:

    M(f,t) = C(f,t)^a  ·  Band(f,t)^b  ·  (1 - Percussive(f,t))^c  ·  REP-SIM(f,t)^d

with exponents defining **presets**:

| Preset | Behavior | Use case |
|---|---|---|
| Conservative | Gentle attenuation; keeps more bleed | Reference/A-B listening |
| Balanced (default) | Moderate exponents | General use |
| Aggressive | Strong suppression; more vocal distortion | Noisy listening environments |

---

## 2. Library Recommendations

All first-class scientific Python libraries — **no neural network frameworks**.

| Library | Role in this project | Notes |
|---|---|---|
| `numpy` | Arrays, FFTs, masking arithmetic, fusion | Backbone of everything |
| `scipy.signal` | STFT/ISTFT (`stft`, `istft`), resampling (`resample_poly`), band filters (`butter` + `sosfilt`) | Alternative: `librosa.stft` — pick one STFT and stay consistent |
| `scipy.ndimage` | `median_filter` for HPSS and mask smoothing | Fast enough with `(time, freq)` axis selection |
| `librosa` | `load`/`resample`, `decompose.hpss`, `segment.recurrence_matrix`, `pyin` (optional voicing detector), `display` (debug plots) | Pin >= 0.10 |
| `soundfile` | Fast WAV/FLAC read/write (PCM 16/24, float) | No MP3 — MP3 decode stays with ffmpeg |
| `ffmpeg` (external binary, via subprocess) | Decode MP3/M4A/video containers to WAV; MP3 re-encode for downloads | **Already in the ClearVoice pipeline — reused as-is** |
| `matplotlib` (dev-only) | Debug spectrograms/mask visualizations | Not shipped in the runtime path |
| `pytest` | Unit tests (round-trip, cue sanity, presets) | Already used in repo |

**Explicitly excluded:** `torch`, `torchaudio`, `demucs`, `onnxruntime`, any model weights.
**Suggested pins:** `numpy>=1.26`, `scipy>=1.11`, `librosa>=0.10`, `soundfile>=0.12`.

---

## 3. Step-by-Step Implementation Plan

Each phase has a concrete deliverable and acceptance criteria. Phases 0–1 mirror the
existing ClearVoice front-end and are mostly reusable.

### Phase 0 — Audio front-end (decode & normalize)
- Reuse the existing ffmpeg-based ingest: any input (MP3/video/URL) → 44.1 kHz stereo
  float32 WAV.
- **Deliverable:** `load_audio(path)` utility.
- **Acceptance:** byte-identical normalized output for WAV, MP3, and MP4 inputs of the same
  source; duration/guardrail checks still enforced.

### Phase 1 — Analysis front-end (STFT + mid/side)
- STFT with n_fft = 4096, hop = 1024, Hann window; compute mid/side spectra and the
  frequency-band weighting curve.
- **Deliverable:** `analyze(x) -> {complex STFT, mid, side, band weights}`.
- **Acceptance:** analysis → direct inverse round-trip error < 1e-4 (numerically lossless
  scaffolding before any masking is added).

### Phase 2 — Cue extractors
- Implement each cue as an independent function returning a [0, 1] map over (freq, time):
  1. `cue_center()` — center-dominance C(f,t) (§1.2)
  2. `cue_band()` — band weighting (§1.3)
  3. `cue_harmonic()` — 1 − percussive ratio from HPSS (§1.4)
  4. `cue_repeat()` — REP-SIM vocal confidence (§1.5) [most complex; build last]
  5. *(optional)* `cue_voiced()` — `librosa.pyin` pitch-presence gate to suppress
     instrumental-only sections
- **Deliverable:** a `cues` module with a common interface.
- **Acceptance:** visual inspection of each cue map on 3 reference tracks (sparse mix,
  dense mix, mono test) shows plausible vocal-region activation.

### Phase 3 — Mask construction and fusion
- Geometric fusion with preset exponents; per-bin normalization to [0, 1]; temporal median
  smoothing; floor/ceiling clamps.
- **Deliverable:** `build_mask(cues, preset) -> M(f,t)`; presets: conservative / balanced /
  aggressive.
- **Acceptance:** mask statistics (mean, sparsity) within expected ranges per preset; no
  NaN/Inf; audible result on reference tracks.

### Phase 4 — Synthesis
- Apply mask to the complex STFT, ISTFT with overlap-add, peak-safe normalization, short
  edge fades.
- **Deliverable:** `synthesize(stft_masked) -> float32 stereo` (or mono-mid output, test
  both).
- **Acceptance:** output duration matches input; no clipping; no time drift.

### Phase 5 — End-to-end pipeline + CLI
- Chain 0→4; export `vocals.wav` and optionally `music_residual.wav` (mixture − vocal
  estimate); mirror ClearVoice's output naming.
- **Deliverable:** `python -m classical_remove input.wav --preset balanced --out dir/`.
- **Acceptance:** a 4-minute song processes **faster than real time** on the 4-core/8 GB
  VPS (target: < 60 s, excluding decode).

### Phase 6 — Evaluation and tuning
- Build a small evaluation set (5–8 songs of varied genres). Use the existing Demucs
  outputs as *reference* vocal targets; compute SNR/SDR of classical output vs reference
  (optional `museval`), plus structured listening notes per preset per track.
- Tune preset exponents; record a tuning table in this document's Appendix.
- **Acceptance:** balanced preset is subjectively "usable" on ≥ 60% of the set; document
  the failure cases honestly.
- **Kill criterion:** if quality is unusable across the board, stop and keep Demucs as the
  only quality path (the work still yields the fast-preview scaffold).

### Phase 7 — ClearVoice integration
- Add `SEPARATION_PROVIDER=classical` alongside the existing local Demucs provider in
  `backend/app/services/separation.py` (the provider seam already isolates this change).
- Same job stages (ingest → normalize → separate → encode); same API/UI contract; expose
  "Fast (DSP)" vs "High quality (AI)" as a quality choice in the frontend job form.
- **Acceptance:** an E2E job through the existing API completes with the classical provider
  and produces both stems; provider switchable by env var only.

### Phase 8 — Optional future enhancements (not in scope for v1)
- Two-pass REP-SIM (refine accompaniment estimate iteratively).
- Spectral-subtraction refinement using noise floors estimated from vocal-free sections.
- Client-side WASM preview (FFT in browser) for instant, upload-free previews.
- Queue policy: auto-route short/preview jobs to classical, long/final jobs to Demucs.

---

## 4. Feasibility Analysis

### 4.1 Expected quality vs Demucs

| Metric | Classical (this plan) | Demucs v4 `htdemucs_ft` |
|---|---|---|
| Typical vocal SDR | ~4–8 dB (best case on sparse, center-panned mixes) | ~13–16 dB |
| Robustness to dense mixes | Poor — heavy bleed | Good |
| Mono inputs | Center cue unusable; only HPSS + REP-SIM survive | Works |
| Wide-panned vocals | Lost with the "instrumental" side signal | Recovered |
| Reverb tails | Largely remain attached to output | Significantly reduced |
| Artifact type | Bleed + "musical noise" + slight Metallic coloration on aggressive masks | Occasional warble/phantom tones, generally low |

### 4.2 Where the classical approach genuinely wins

1. **Speed:** tens of times faster than real time on CPU (Demucs CPU is ~10× slower than
   real time) → seconds per song, instant previews.
2. **Footprint:** < 500 MB RAM per job, no GPU, no ~170 MB model downloads, deterministic
   and debuggable (every stage is inspectable).
3. **Honest use cases:** fast-preview tier, low-cost fallback when GPU capacity is
   unavailable, privacy mode (no heavy processing needed on server), old/sparse recordings
   where center extraction works well.

### 4.3 Honest positioning

This is **not** a replacement for Demucs for end-user quality expectations. It is a
complement: the plan explicitly defines a kill criterion (Phase 6) so the project can be
demoted to a preview tier or abandoned without sunk-cost pressure.

---

## 5. Deployment Strategy

### 5.1 Why hosting gets simpler

| Dimension | Classical (this plan) | Demucs (current) |
|---|---|---|
| Runtime deps | numpy, scipy, librosa, soundfile, ffmpeg | + torch, torchaudio, demucs, model weights |
| Docker image size | ~300–500 MB | ~4–6 GB (CUDA base or CPU torch) |
| RAM per job | < 500 MB | ~1.5–2 GB |
| Speed on 4-core VPS | ~20–50× faster than real time | ~10× slower than real time |
| GPU required for acceptable UX | No | Effectively yes |
| Concurrency on the existing VPS | Multiple jobs comfortably | One job at a time |
| Cold start / scale-up | Instant | Model load + (first run) weight download |

### 5.2 Practical consequences

- **The existing 4-core/8 GB VPS becomes a genuinely good host:** a 4-minute song processes
  in seconds instead of ~30–40 minutes, and several jobs can run concurrently within 8 GB.
- **Free/cheap tiers become viable** (Fly.io / Railway free instances, small containers):
  the whole worker fits where a torch worker cannot.
- **Image builds and CI get faster and cheaper** (no CUDA base layers, no Hugging Face
  downloads in the image, no GPU-specific Dockerfile variant to maintain).
- **Architecture is unchanged:** the existing FastAPI + queue + storage pipeline, job store,
  SSE progress, and frontend all stay; only the separation engine behind the provider seam
  swaps. ffmpeg remains the single external binary for decode/encode.

### 5.3 Suggested deployment shape (when this ships)

- Same `docker-compose.yml`, worker image built from a slim Python base with
  `numpy/scipy/librosa/soundfile + ffmpeg` (~300–500 MB).
- `SEPARATION_PROVIDER=classical` on CPU hosts; `demucs` on GPU hosts; optional routing
  policy per job size/quality flag (Phase 8).

---

## 6. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Centered instruments (bass/kick/snare) bleed into vocals | Mid-quality output | Band weighting removes bass; HPSS removes drums; residual lead-guitar bleed accepted and documented |
| REP-SIM too slow on long tracks | Phase 5 target missed | Bar-aligned candidate matching, half-resolution spectrogram for the similarity stage, cap duration |
| Aggressive masks sound metallic | User-facing quality | Soft ratio masks, temporal smoothing, presets; keep "conservative" default for previews |
| Mono / wide-vocal inputs fail assumptions | Silent bad output | Detect stereo width and mono files up front; warn or auto-route to Demucs provider |
| Quality gap too large to be useful | Project value | Phase 6 kill criterion; fallback positioning as preview tier only |

## 7. Open Questions

1. Should the classical provider return mono (mid-only) vocals or stereo vocals? (Decide in
   Phase 4 by A/B.)
2. Default preset for the API when the client does not specify one (recommend "balanced").
3. Should URL-ingested jobs (yt-dlp) be allowed to use the classical provider given they are
   typically longer? (Recommendation: yes — it is the provider where long jobs are cheap.)
4. UI copy for the quality tiers ("Fast preview (DSP)" vs "High quality (AI)").

---

## References

- Fitzgerald, D. (2010). *Harmonic/percussive separation using median filtering.* DAFx.
- Rafii, Z., & Pardo, B. (2012/2014). *Repeating Pattern Extraction Technique (REP-SIM) for
  music source separation / audio background and foreground separation.*
- Liutkus, A., et al. — kernel-based (REP-SIM family) separation literature.
- Wiener-style ratio masking and ideal ratio mask literature (time-frequency masking).
- Demucs v4 — Rousseaux, Défossez et al., *Hybrid Transformers for Music Source Separation*
  (the quality benchmark this plan is measured against).
