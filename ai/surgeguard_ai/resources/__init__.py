"""Resource allocation - how many counters should be open.

Consumes measured queue state and its forecast, and recommends the fewest
counters that bring the projected wait within target. Every figure is computed by
re-running the projection at the proposed capacity.
"""

from __future__ import annotations

from .allocator import ResourceAllocator
from .config import AllocationConfig

__all__ = ["ResourceAllocator", "AllocationConfig"]
