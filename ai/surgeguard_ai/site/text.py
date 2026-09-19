"""Small helpers for the operator-facing sentences site intelligence writes."""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["join_names", "plural", "sentence_list"]


def join_names(names: Sequence[str]) -> str:
    """'A', 'A and B', 'A, B and C'."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def sentence_list(statements: Sequence[str]) -> str:
    """Each statement as its own sentence."""
    return " ".join(f"{statement}." for statement in statements)


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    """'1 counter', '2 counters'."""
    word = singular if count == 1 else (plural_form or f"{singular}s")
    return f"{count} {word}"
