"""Persistence for the site topology - how camera zones connect.

A link says that people in one zone go on to another: the entrance feeds the
waiting area, the waiting area feeds the queue. It is venue configuration,
drawn by an operator, and stored the way zones are: as a small JSON file,
written atomically, never overwritten if it could not be read.

References are not checked against the live camera set here. A link naming a
zone that has since been redrawn is still the operator's statement about the
venue; the site layer reports it as unavailable rather than this store
silently deleting it.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from surgeguard_ai.contracts import FlowLinkConfig

from ..core.config import normalise_camera_id

__all__ = ["TopologyStore", "TopologyStoreError"]

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class TopologyStoreError(RuntimeError):
    """The topology could not be read or written."""


class TopologyStore:
    """Reads and writes the site's zone links."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._links: tuple[FlowLinkConfig, ...] = ()
        self._load_error: str | None = None
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def links(self) -> tuple[FlowLinkConfig, ...]:
        return self._links

    def save(self, links: Iterable[FlowLinkConfig]) -> tuple[FlowLinkConfig, ...]:
        """Replace every link, dropping duplicates and refusing self-links."""
        if self._load_error is not None:
            raise TopologyStoreError(
                f"The topology at {self._path} could not be read ({self._load_error}), "
                "so it will not be overwritten."
            )

        unique: dict[str, FlowLinkConfig] = {}
        for link in links:
            normalised = _normalised(link)
            if (
                normalised.from_camera_id == normalised.to_camera_id
                and normalised.from_zone_id == normalised.to_zone_id
            ):
                raise TopologyStoreError(
                    f"A zone cannot feed itself ({normalised.link_id})."
                )
            unique.setdefault(normalised.link_id, normalised)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": datetime.now(UTC).isoformat(),
            "links": [link.model_dump(mode="json") for link in unique.values()],
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=".topology.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(payload, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self._path)
        except OSError as error:
            raise TopologyStoreError(
                f"Could not write the topology to {self._path}: {error}"
            ) from error

        self._links = tuple(unique.values())
        logger.info("Saved %d zone link(s)", len(self._links))
        return self._links

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if raw.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(
                    f"schema version {raw.get('schema_version')!r}, expected {SCHEMA_VERSION}"
                )
            self._links = tuple(
                _normalised(FlowLinkConfig.model_validate(entry))
                for entry in raw.get("links", [])
            )
        except (OSError, ValueError, TypeError, AttributeError, ValidationError) as error:
            self._load_error = str(error)
            logger.error("Topology at %s could not be read: %s", self._path, error)


def _normalised(link: FlowLinkConfig) -> FlowLinkConfig:
    return FlowLinkConfig(
        from_camera_id=normalise_camera_id(link.from_camera_id),
        from_zone_id=link.from_zone_id,
        to_camera_id=normalise_camera_id(link.to_camera_id),
        to_zone_id=link.to_zone_id,
    )
