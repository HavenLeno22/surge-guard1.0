"""Compute device selection for model inference.

Private to :mod:`surgeguard_ai.perception`. Kept separate from the detector so
that device resolution has one owner, can be tested without loading a model, and
- most importantly - so that a **CPU fallback is reported rather than silently
taken**. A pipeline that quietly drops to CPU looks identical to one that did
not, right up until the frame rate does not meet the budget on demonstration
day.

The performance budget in ``02_Hackathon_Execution_Plan.md`` assumes CUDA. When
CUDA is unavailable the platform still runs; it simply runs slower, and
:attr:`DeviceInfo.fallback_reason` records why.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

__all__ = ["DeviceInfo", "resolve_device"]

logger = logging.getLogger(__name__)

#: Compute capability at which half precision is worth enabling. Tensor cores
#: arrive at 7.0 (Volta); below that FP16 is emulated and can be slower than
#: FP32 while still costing accuracy. The RTX 4060 Laptop target is 8.9.
_MIN_FP16_CAPABILITY = (7, 0)


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """The device inference will actually run on, and how that was decided.

    Attributes:
        device: Torch device string - ``"cuda:0"`` or ``"cpu"``.
        is_cuda: Whether inference runs on a GPU.
        name: Human-readable device name, for logs and health reporting.
        total_memory_mb: GPU memory in mebibytes. ``None`` on CPU.
        supports_fp16: Whether half-precision inference is worth enabling.
        torch_version: Installed PyTorch version, or ``None`` if absent.
        cuda_version: CUDA toolkit version PyTorch was built against.
        requested: What the caller asked for, before resolution.
        fallback_reason: Why the request could not be honoured. ``None`` when
            the resolved device is what was asked for.
    """

    device: str
    is_cuda: bool
    name: str
    total_memory_mb: int | None
    supports_fp16: bool
    torch_version: str | None
    cuda_version: str | None
    requested: str
    fallback_reason: str | None

    @property
    def is_fallback(self) -> bool:
        """Whether the requested device could not be used."""
        return self.fallback_reason is not None

    def describe(self) -> str:
        """One-line summary suitable for an operator-facing log."""
        memory = f", {self.total_memory_mb} MiB" if self.total_memory_mb else ""
        precision = "FP16" if self.supports_fp16 else "FP32"
        return f"{self.device} ({self.name}{memory}, {precision})"


def _cpu(
    *,
    requested: str,
    fallback_reason: str | None,
    torch_version: str | None = None,
    cuda_version: str | None = None,
) -> DeviceInfo:
    """Build the CPU :class:`DeviceInfo`, recording why CPU was chosen."""
    return DeviceInfo(
        device="cpu",
        is_cuda=False,
        name="CPU",
        total_memory_mb=None,
        supports_fp16=False,
        torch_version=torch_version,
        cuda_version=cuda_version,
        requested=requested,
        fallback_reason=fallback_reason,
    )


def resolve_device(requested: str = "auto") -> DeviceInfo:
    """Decide which device inference will run on.

    Args:
        requested: ``"auto"`` to prefer CUDA when present, ``"cpu"`` to force
            CPU, or an explicit ``"cuda"`` / ``"cuda:N"``.

    Returns:
        The resolved device. This function never raises: an unavailable GPU
        yields a CPU :class:`DeviceInfo` carrying a ``fallback_reason``, because
        degrading to CPU is a documented behaviour (``05:889-897``) and refusing
        to start would be worse than running slowly.
    """
    wanted = requested.strip().lower() or "auto"

    try:
        import torch
    except ImportError:
        return _cpu(
            requested=wanted,
            fallback_reason="PyTorch is not installed; inference will run on CPU",
        )

    torch_version = str(torch.__version__)
    cuda_version = torch.version.cuda

    if wanted == "cpu":
        return _cpu(requested=wanted, fallback_reason=None, torch_version=torch_version)

    if not torch.cuda.is_available():
        reason = (
            "CUDA is not available to PyTorch"
            if cuda_version
            else "PyTorch was installed without CUDA support"
        )
        # An explicit CUDA request that cannot be honoured is a misconfiguration
        # worth warning about. "auto" resolving to CPU is expected on a machine
        # without a GPU, so it is only worth an informational note.
        if wanted.startswith("cuda"):
            logger.warning("Requested %s but %s; falling back to CPU", wanted, reason)
        else:
            logger.info("No CUDA device available; inference will run on CPU")
        return _cpu(
            requested=wanted,
            fallback_reason=reason,
            torch_version=torch_version,
            cuda_version=cuda_version,
        )

    index = 0
    if wanted.startswith("cuda:"):
        suffix = wanted.split(":", 1)[1]
        if suffix.isdigit():
            index = int(suffix)

    if index >= torch.cuda.device_count():
        logger.warning(
            "CUDA device %d was requested but only %d are present; using cuda:0",
            index,
            torch.cuda.device_count(),
        )
        index = 0

    properties = torch.cuda.get_device_properties(index)
    capability = torch.cuda.get_device_capability(index)

    return DeviceInfo(
        device=f"cuda:{index}",
        is_cuda=True,
        name=str(properties.name),
        total_memory_mb=int(properties.total_memory // (1024 * 1024)),
        supports_fp16=capability >= _MIN_FP16_CAPABILITY,
        torch_version=torch_version,
        cuda_version=cuda_version,
        requested=wanted,
        fallback_reason=None,
    )
