"""Shared Pydantic base for every SurgeGuard data contract.

Contracts are the structured data that crosses module and process boundaries
(``04:511``, ``07:444``). They are deliberately immutable: once a stage has
produced a result, no downstream stage may mutate it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["Contract"]


class Contract(BaseModel):
    """Immutable, strictly-validated base model for all SurgeGuard contracts.

    Configuration rationale:

    - ``frozen`` - a contract that has crossed a stage boundary is a record of
      what was observed. Mutating it downstream would make the pipeline
      untraceable.
    - ``extra="forbid"`` - an unexpected field is a contract drift bug, and
      failing loudly at the boundary is cheaper than debugging a silently
      ignored field later.
    - ``validate_assignment`` - defence in depth for the frozen guarantee.
    - ``use_enum_values=False`` - enum members are preserved so downstream code
      compares against the enum rather than raw strings.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        use_enum_values=False,
        str_strip_whitespace=True,
    )
