"""SurgeGuard AI Pipeline.

Transforms live CCTV frames into structured crowd intelligence
(``05_AI_Pipeline.md``).

This package is bounded by two abstractions and knows nothing about either
end of the system:

- :class:`surgeguard_ai.perception.FrameSource` supplies frames.
- :class:`surgeguard_ai.sinks.AnalysisSink` receives results.

It must never import from the backend, the database, or the frontend.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
