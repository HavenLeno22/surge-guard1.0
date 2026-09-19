"""Structural guards for the AI package.

These protect two architectural invariants that are cheap to break silently and
expensive to discover late:

1. The package imports cleanly - no circular dependencies.
2. ``contracts`` is a dependency-free leaf, so the backend can depend on it
   without inheriting OpenCV or a model runtime.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import surgeguard_ai

MODULES = [
    "surgeguard_ai",
    "surgeguard_ai.contracts",
    "surgeguard_ai.errors",
    "surgeguard_ai.perception",
    "surgeguard_ai.analysis",
    "surgeguard_ai.stability",
    "surgeguard_ai.intelligence",
    "surgeguard_ai.sinks",
    "surgeguard_ai.pipeline",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    """Every subpackage imports without a circular dependency."""
    assert importlib.import_module(module_name) is not None


def test_every_submodule_imports() -> None:
    """Walk the whole package so no module is left unimported by the suite."""
    for info in pkgutil.walk_packages(
        surgeguard_ai.__path__, prefix="surgeguard_ai."
    ):
        importlib.import_module(info.name)


def test_contracts_do_not_depend_on_the_rest_of_the_package() -> None:
    """``contracts`` must remain a leaf.

    If a contract module starts importing from ``perception`` or any other
    sibling, the backend inherits that dependency chain the moment it imports a
    contract - which is how a "shared types" package quietly becomes a runtime
    dependency on OpenCV.
    """
    import surgeguard_ai.contracts as contracts

    for info in pkgutil.walk_packages(contracts.__path__, prefix="contracts."):
        module = importlib.import_module(
            info.name.replace("contracts.", "surgeguard_ai.contracts.", 1)
        )
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            module_name = getattr(attr, "__module__", "") or ""
            if not module_name.startswith("surgeguard_ai."):
                continue
            assert module_name.startswith("surgeguard_ai.contracts"), (
                f"{info.name}.{attr_name} pulls in {module_name}; "
                "contracts must stay a dependency-free leaf"
            )
