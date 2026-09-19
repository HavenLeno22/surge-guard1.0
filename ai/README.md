# surgeguard-ai

The SurgeGuard AI Pipeline.

Transforms live CCTV frames into structured crowd intelligence
(`05_AI_Pipeline.md`).

## Independence

This package **must never import** from the backend, the database, or the
frontend. Per `07:99-103` the AI Pipeline and the Backend are independent
systems that communicate through structured data.

The package is bounded by exactly two interfaces:

```
FrameSource  ──►  [ AI PIPELINE ]  ──►  AnalysisSink
  (input)          knows neither         (output)
                     end's origin
```

- `surgeguard_ai.perception.FrameSource` — where frames come from.
- `surgeguard_ai.sinks.AnalysisSink` — where results go.

Both are abstract. Concrete sinks live in the consuming application
(`backend/app/ingest/`), so the dependency direction is always
`backend → surgeguard_ai` and never the reverse.

## Live / Demonstration mode

Switching between Live Camera Mode and Demonstration Mode is a matter of
constructing a different `FrameSource`. **There is no `if demo:` branch
anywhere in this package.** `source_mode` is carried through to the sink as a
tag on the result, used only for data separation (Rule 7) and the
Live/Demo indicator — never as a behavioural switch.

## Package layout

| Module | Responsibility | State |
|---|---|---|
| `contracts/` | Serializable data models that cross boundaries. Dependency-free leaf. | Implemented |
| `perception/` | Frame acquisition, person detection, person tracking (Stages 1-3). | **Implemented** |
| `analysis/` | Crowd density, flow and zone occupancy (Stages 4-5). | **Implemented** |
| `stability/` | Crowd Stability Index assessment (Stage 6). | **Implemented** |
| `evidence/` | Explainable observations from measured conditions. | **Implemented** |
| `intelligence/` | Decision Intelligence Engine (Stage 7). | Interface only |
| `sinks/` | Outward result interface. | Implemented |
| `pipeline/` | Stage orchestration. | Perception and analysis wired |

## Perception

Stages 1 to 3 are implemented and run end to end:

```
FrameSource ──► YoloDetector ──► ByteTrackTracker ──► PerceptionResult
```

| Component | Notes |
|---|---|
| `VideoFileSource` | Recorded clips, **paced to the source frame rate**, with decode-error recovery. |
| `LiveCameraSource` | Webcam or IP camera, with reconnection and availability probing. |
| `YoloDetector` | Ultralytics YOLO, person class only. CUDA with FP16 when available, CPU otherwise — and it says which. |
| `ByteTrackTracker` | Persistent identities, lost-track timeout, image-space velocity. |
| `PerceptionPipeline` | Sequential frame loop on one dedicated thread, with per-stage failure isolation. |

## Crowd intelligence

Stages 4 to 6 plus the Evidence Engine run downstream of perception, in a
separate pipeline that consumes a `PerceptionResult`:

```
PerceptionResult ──► GridCrowdAnalyzer ──► WeightedStabilityAssessor ──► RuleEvidenceEngine
                        (metrics)               (CSI)                     (observations)
```

| Component | Notes |
|---|---|
| `GridCrowdAnalyzer` | Density grid, flow, zone occupancy. persons/m² when calibrated, **labelled relative** when not. |
| `WeightedStabilityAssessor` | `CSI = clamp(100 − Σ wᵢ·pᵢ, 0, 100)` over five indicators, with EMA smoothing, band hysteresis and computed Decision Confidence. |
| `RuleEvidenceEngine` | Operator-readable observations, each citing the measurement that produced it. Prioritised, filtered, and kept as history. |
| `AnalysisPipeline` | Composes the three, and discards all accumulated state when frame continuity breaks. |

Weights, normalization curves, thresholds and hysteresis counts are all
configuration (`stability/config.py`, `evidence/config.py`, `analysis/config.py`)
— no number in the engines is hardcoded.

The Operational Intelligence Report and its recommended actions are **not**
produced yet. Evidence explains what is happening; deciding what to do about it
is the Decision Intelligence Engine, one stage later.

### Running it

From the repository root:

```bash
# Demonstration Mode - a recorded clip, processed exactly as a live feed
python scripts/run_perception.py video data/scenarios/00_placeholder.mp4

# Live Camera Mode - the same pipeline, a different frame source
python scripts/run_perception.py camera --device 0

# Which cameras are attached?
python scripts/run_perception.py devices
```

Model weights download on first use into `data/models/`.

## Development

```bash
pip install -e ".[dev]"
pytest
```

GPU inference needs a CUDA build of PyTorch, which is not installed by the
default dependency resolution:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

Without it everything still runs on CPU, roughly 15x slower, and
`DeviceInfo.fallback_reason` records why.

Tests marked `model` need the detection weights and are skipped when absent:

```bash
pytest -m "not model"
```
