"""Analysis ingest - the backend's boundary with the AI Pipeline.

The system's primary data path, and one the source documentation never defined
(Architecture Review §5.2). Everything the Command Center displays enters here.

``InProcessPerceptionSink`` receives detections and tracks from Stages 1-3 and
is where every frame's output crosses into the backend.

**There is deliberately no analysis-side sink.** Stages 4-7 do not emit across a
process boundary: the backend *owns* the analysis pipeline and runs it as a
subscriber to perception (:mod:`app.services.crowd_intelligence`), so the seam
is at perception, not after it. An in-process analysis sink existed here until
that design settled and was then constructed at every startup while nothing ever
called it - a dead component in the composition root, which reads as a live data
path to anyone tracing one. :class:`~surgeguard_ai.sinks.AnalysisSink` remains
in the AI package as the documented boundary for the day the analysis stages do
move out of process (Architecture Review §9.5).
"""

from __future__ import annotations

from .perception_sink import InProcessPerceptionSink

__all__ = ["InProcessPerceptionSink"]
