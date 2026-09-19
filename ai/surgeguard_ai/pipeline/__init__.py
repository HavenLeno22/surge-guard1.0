"""Pipeline orchestration.

Two pipelines with separate lifecycles:

``PerceptionPipeline``
    Stages 1-3. Owns a frame source, a model and a dedicated thread, and runs a
    real-time frame loop.

``AnalysisPipeline``
    Stages 4-7. Owns only arithmetic, so it can be reset, replaced or run twice
    without disturbing the loop keeping up with a camera.

Each composes and resets its own stages. A shared ``PipelineComponents``
container existed here to do that uniformly and was never constructed by
either - the two pipelines have different stage sets and different lifecycles,
which is precisely why they are two pipelines.
"""

from __future__ import annotations

from .analysis_pipeline import AnalysisPipeline
from .perception_pipeline import (
    PerceptionPipeline,
    PerceptionPipelineConfig,
    PerceptionResultHandler,
)
from .pipeline import Pipeline, PipelineStatus

__all__ = [
    "AnalysisPipeline",
    "PerceptionPipeline",
    "PerceptionPipelineConfig",
    "PerceptionResultHandler",
    "Pipeline",
    "PipelineStatus",
]
