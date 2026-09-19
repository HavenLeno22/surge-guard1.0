"""The Evidence Engine - explainable observations (``17_Evidence_Engine_Specification.md``).

Sits between crowd analysis and the Operational Decision Engine. It says what
the platform is observing and why; it never says what to do about it.
"""

from __future__ import annotations

from .config import EvidenceConfig
from .engine import EvidenceEngine
from .observations import ObservationContext
from .rule_evidence_engine import RuleEvidenceEngine

__all__ = [
    "EvidenceConfig",
    "EvidenceEngine",
    "ObservationContext",
    "RuleEvidenceEngine",
]
