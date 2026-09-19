"""Pipeline orchestration contract.

Interface only. The processing loop is Phase 2 work.

A pipeline reads frames from a :class:`~surgeguard_ai.perception.FrameSource`,
passes them through the stages in
:class:`~surgeguard_ai.pipeline.stages.PipelineComponents`, and emits results to
an :class:`~surgeguard_ai.sinks.AnalysisSink`. It knows nothing about either end.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..contracts.enums import SourceMode
from ..perception.frame_source import FrameSource

__all__ = ["PipelineStatus", "Pipeline"]


@dataclass(frozen=True, slots=True)
class PipelineStatus:
    """A snapshot of pipeline health, for the System Health panel (``06:872-896``)."""

    running: bool
    source_id: str | None
    source_mode: SourceMode | None
    frames_processed: int
    frames_dropped: int
    achieved_fps: float
    last_frame_ts: str | None
    degraded: bool
    degraded_reason: str | None


class Pipeline(ABC):
    """Orchestrates the AI Pipeline stages over a frame source.

    **Mode switching.** Live Camera Mode and Demonstration Mode differ only in
    which :class:`FrameSource` is attached. There is no branch on
    :class:`SourceMode` anywhere in this package - the mode travels to the sink
    as provenance and nothing more. :meth:`swap_source` is the entire mechanism.

    **Reset semantics.** :meth:`swap_source` and :meth:`reset` both discard the
    accumulated state of every stateful stage via
    :meth:`PipelineComponents.reset_all`. This is not optional bookkeeping: a
    tracker carrying identities from the previous clip, or a stability assessor
    carrying its smoothing window across a scenario change, would report the old
    material's crowd as though it were the new one's.

    That shared requirement is also why One-Click Reset (``11:619-629``) is
    :meth:`reset` and not a separate mechanism.
    """

    # -- Lifecycle ----------------------------------------------------------

    @abstractmethod
    async def start(self, source: FrameSource) -> None:
        """Open the source and begin processing frames.

        Args:
            source: Where frames come from. Whether this is a camera or a
                recording is not the pipeline's concern.

        Raises:
            PipelineError: Already running, or the components are not ready.
            SourceUnavailableError: The source could not be opened.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop processing and release the current source. Idempotent."""

    @abstractmethod
    async def swap_source(self, source: FrameSource) -> None:
        """Replace the current frame source.

        Closes the existing source, resets every stateful stage, then opens and
        begins reading the new one. The stages themselves are untouched: no
        model is reloaded and no configuration changes.

        This is the whole of Live/Demo switching, and the whole of scenario
        selection.

        Args:
            source: The replacement source.

        Raises:
            SourceUnavailableError: The new source could not be opened. The
                pipeline is left stopped rather than half-switched.
        """

    @abstractmethod
    async def reset(self) -> None:
        """Discard accumulated state without changing the source.

        Backs One-Click Reset (``11:619-629``): the demonstration returns to its
        initial state - CSI, trends, hysteresis and tracking history all cleared
        - without restarting the application or reloading the model.
        """

    # -- Observation --------------------------------------------------------

    @property
    @abstractmethod
    def status(self) -> PipelineStatus:
        """Current pipeline health, for the System Health panel."""

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the pipeline is currently processing frames."""
