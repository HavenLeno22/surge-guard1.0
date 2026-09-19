"""The camera registry - the operator's record of which cameras exist.

Two sources are combined, in this order of authority:

1. **Operator edits**, saved to ``data/cameras.json`` from the Command Center.
2. **The environment** - the primary camera's long-standing settings and the
   indexed ``SURGEGUARD_CAMERA_<N>_*`` variables.

An edit to an environment-declared camera is stored as an *override* of just
the fields that changed, so the rest of that camera keeps following ``.env``.
A camera added from the interface is stored whole. Removing an
environment-declared camera records its id, because otherwise the next restart
would quietly bring it back.

The file is written only when an operator changes something, atomically, and is
never overwritten if it could not be read - a registry the platform failed to
parse is evidence to keep, not a blank to fill in.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from surgeguard_ai.contracts import CameraRole

from ..core.config import CameraSeed, normalise_camera_id
from .definitions import (
    CameraChanges,
    CameraDefinition,
    CameraOrigin,
    CameraSpec,
    UrlSource,
    normalise_stream_url,
)

__all__ = [
    "CameraConflictError",
    "CameraNotFoundError",
    "CameraRegistry",
    "CameraRegistryError",
]

logger = logging.getLogger(__name__)

#: Bumped when the file's shape changes, so an old file is refused with a clear
#: message rather than parsed into something subtly different.
SCHEMA_VERSION = 1

#: Operator-added cameras sort after every environment camera, in the order
#: they were added.
_OPERATOR_ORDER_BASE = 1000

#: Fields an override may carry for an environment-declared camera.
_OVERRIDABLE = (
    "name",
    "location",
    "role",
    "stream_url",
    "demo_video_path",
    "enabled",
    "coverage_area",
)

_NUMBERED_ID = re.compile(r"^cam-(\d+)$")


class CameraRegistryError(RuntimeError):
    """The camera registry could not be read or changed."""


class CameraNotFoundError(CameraRegistryError):
    """No camera has the requested id."""


class CameraConflictError(CameraRegistryError):
    """The change conflicts with the current camera set."""


class CameraRegistry:
    """Resolves the camera set and applies operator edits to it."""

    def __init__(
        self,
        path: Path,
        *,
        seeds: Iterable[CameraSeed],
        primary_camera_id: str,
    ) -> None:
        """
        Args:
            path: Where operator edits are stored.
            seeds: Cameras declared in the environment, primary first.
            primary_camera_id: The camera the single-camera routes describe. It
                may be disabled but never removed.
        """
        self._path = path
        self._seeds: dict[str, CameraSeed] = {seed.camera_id: seed for seed in seeds}
        self._primary_camera_id = normalise_camera_id(primary_camera_id)

        self._operator_cameras: list[dict[str, Any]] = []
        self._overrides: dict[str, dict[str, Any]] = {}
        self._removed: set[str] = set()
        self._load_error: str | None = None

        self._load()

    # -- Reading ------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def load_error(self) -> str | None:
        """Why the registry file could not be read, or ``None`` when it was fine."""
        return self._load_error

    @property
    def primary_camera_id(self) -> str:
        return self._primary_camera_id

    def cameras(self) -> tuple[CameraDefinition, ...]:
        """Every camera, environment-declared first in index order."""
        resolved: list[CameraDefinition] = []

        for seed in sorted(self._seeds.values(), key=lambda s: s.index):
            if seed.camera_id in self._removed and seed.camera_id != self._primary_camera_id:
                continue
            resolved.append(self._resolve_seed(seed))

        known = {camera.camera_id for camera in resolved}
        for position, entry in enumerate(self._operator_cameras):
            camera_id = entry["camera_id"]
            if camera_id in known:
                logger.warning(
                    "Camera %s is declared in the environment and also saved as an "
                    "operator camera; the environment declaration is used",
                    camera_id,
                )
                continue
            resolved.append(self._resolve_operator(entry, position))
            known.add(camera_id)

        return tuple(resolved)

    def get(self, camera_id: str) -> CameraDefinition | None:
        wanted = camera_id.strip().lower()
        for camera in self.cameras():
            if camera.camera_id == wanted:
                return camera
        return None

    def require(self, camera_id: str) -> CameraDefinition:
        camera = self.get(camera_id)
        if camera is None:
            raise CameraNotFoundError(f"No camera {camera_id!r} is configured.")
        return camera

    # -- Writing ------------------------------------------------------------

    def add(self, spec: CameraSpec) -> CameraDefinition:
        """Add a camera, or restore a removed environment camera by its id."""
        self._require_writable()

        camera_id = spec.camera_id or self._next_camera_id()
        if self.get(camera_id) is not None:
            raise CameraConflictError(
                f"A camera with id {camera_id!r} already exists. Edit it instead, "
                "or choose another id."
            )

        if camera_id in self._seeds:
            # A removed environment camera coming back: restore it and record
            # what the operator entered as its overrides.
            self._removed.discard(camera_id)
            self._overrides[camera_id] = {
                field: getattr(spec, field) for field in _OVERRIDABLE
            }
        else:
            self._operator_cameras.append(
                {
                    "camera_id": camera_id,
                    **{field: getattr(spec, field) for field in _OVERRIDABLE},
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )

        self._save()
        logger.info("Camera %s added", camera_id)
        return self.require(camera_id)

    def update(self, camera_id: str, changes: CameraChanges) -> CameraDefinition:
        """Apply an operator's edit, keeping every field it does not mention."""
        self._require_writable()
        camera = self.require(camera_id)
        supplied = changes.supplied()
        _reject_nulls(supplied)

        if camera.origin is CameraOrigin.ENVIRONMENT:
            overrides = self._overrides.setdefault(camera.camera_id, {})
            for field, value in supplied.items():
                if field == "stream_url" and value is None:
                    # Back to whatever the environment declares.
                    overrides.pop("stream_url", None)
                else:
                    overrides[field] = value
            if not overrides:
                self._overrides.pop(camera.camera_id, None)
        else:
            entry = self._operator_entry(camera.camera_id)
            entry.update(supplied)

        self._save()
        logger.info(
            "Camera %s updated", camera.camera_id, extra={"fields": sorted(supplied)}
        )
        return self.require(camera.camera_id)

    def remove(self, camera_id: str) -> None:
        """Remove a camera. The primary camera may only be disabled."""
        self._require_writable()
        camera = self.require(camera_id)

        if camera.is_primary:
            raise CameraConflictError(
                f"{camera.display_id} is the primary camera and cannot be removed; "
                "disable it instead."
            )

        if camera.origin is CameraOrigin.ENVIRONMENT:
            self._removed.add(camera.camera_id)
            self._overrides.pop(camera.camera_id, None)
        else:
            self._operator_cameras = [
                entry
                for entry in self._operator_cameras
                if entry["camera_id"] != camera.camera_id
            ]

        self._save()
        logger.info("Camera %s removed", camera.camera_id)

    # -- Resolution ---------------------------------------------------------

    def _resolve_seed(self, seed: CameraSeed) -> CameraDefinition:
        overrides = self._overrides.get(seed.camera_id, {})

        def pick(field: str, default: Any) -> Any:
            return overrides.get(field, default)

        if "stream_url" in overrides:
            stream_url = overrides["stream_url"]
            url_source = UrlSource.REGISTRY if stream_url else UrlSource.UNSET
        else:
            stream_url = seed.url
            url_source = UrlSource.ENVIRONMENT if stream_url else UrlSource.UNSET

        coverage = pick("coverage_area", seed.coverage_area)
        return CameraDefinition(
            camera_id=seed.camera_id,
            name=pick("name", seed.name),
            location=pick("location", seed.location),
            role=CameraRole(pick("role", seed.role)),
            stream_url=stream_url,
            url_source=url_source,
            demo_video_path=_as_path(pick("demo_video_path", seed.demo_video_path)),
            enabled=bool(pick("enabled", seed.enabled)),
            coverage_area=coverage or seed.camera_id,
            origin=CameraOrigin.ENVIRONMENT,
            is_primary=seed.camera_id == self._primary_camera_id,
            order=seed.index,
        )

    def _resolve_operator(self, entry: dict[str, Any], position: int) -> CameraDefinition:
        stream_url = entry.get("stream_url")
        return CameraDefinition(
            camera_id=entry["camera_id"],
            name=entry["name"],
            location=entry.get("location") or "",
            role=CameraRole(entry.get("role") or CameraRole.GENERAL),
            stream_url=stream_url,
            url_source=UrlSource.REGISTRY if stream_url else UrlSource.UNSET,
            demo_video_path=_as_path(entry.get("demo_video_path")),
            enabled=bool(entry.get("enabled", True)),
            coverage_area=entry.get("coverage_area") or entry["camera_id"],
            origin=CameraOrigin.OPERATOR,
            is_primary=entry["camera_id"] == self._primary_camera_id,
            order=_OPERATOR_ORDER_BASE + position,
        )

    def _operator_entry(self, camera_id: str) -> dict[str, Any]:
        for entry in self._operator_cameras:
            if entry["camera_id"] == camera_id:
                return entry
        raise CameraNotFoundError(f"No camera {camera_id!r} is configured.")

    def _next_camera_id(self) -> str:
        """The next ``cam-NN`` after the highest numbered id ever seen here."""
        ids = (
            set(self._seeds)
            | {entry["camera_id"] for entry in self._operator_cameras}
            | self._removed
        )
        highest = max(
            (int(match.group(1)) for match in map(_NUMBERED_ID.match, ids) if match),
            default=1,
        )
        return f"cam-{highest + 1:02d}"

    # -- Persistence --------------------------------------------------------

    def _require_writable(self) -> None:
        if self._load_error is not None:
            raise CameraRegistryError(
                f"The camera registry at {self._path} could not be read "
                f"({self._load_error}), so it will not be overwritten. Fix or "
                "remove the file, then restart."
            )

    def _load(self) -> None:
        if not self._path.exists():
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if raw.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(
                    f"schema version {raw.get('schema_version')!r}, expected {SCHEMA_VERSION}"
                )
            operator = [_validated_entry(entry) for entry in raw.get("cameras", [])]
            overrides = {
                normalise_camera_id(camera_id): _validated_override(fields)
                for camera_id, fields in (raw.get("overrides") or {}).items()
            }
            removed = {normalise_camera_id(camera_id) for camera_id in raw.get("removed", [])}
        except (OSError, ValueError, TypeError, AttributeError, ValidationError) as error:
            self._load_error = str(error)
            logger.error(
                "Camera registry at %s could not be read; continuing with the "
                "environment's cameras only: %s",
                self._path,
                error,
            )
            return

        self._operator_cameras = operator
        self._overrides = overrides
        self._removed = removed

    def _save(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": datetime.now(UTC).isoformat(),
            "cameras": [_serialisable(entry) for entry in self._operator_cameras],
            "overrides": {
                camera_id: _serialisable(fields)
                for camera_id, fields in sorted(self._overrides.items())
            },
            "removed": sorted(self._removed),
        }

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=".cameras.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(payload, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self._path)
        except OSError as error:
            raise CameraRegistryError(
                f"Could not write the camera registry to {self._path}: {error}"
            ) from error


def _validated_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Validate a stored operator camera through the same rules as an add."""
    spec = CameraSpec.model_validate(
        {field: entry.get(field) for field in ("camera_id", *_OVERRIDABLE) if field in entry}
    )
    if spec.camera_id is None:
        raise ValueError("a stored camera has no camera_id")
    return {
        "camera_id": spec.camera_id,
        **{field: getattr(spec, field) for field in _OVERRIDABLE},
        "created_at": entry.get("created_at"),
    }


def _validated_override(fields: dict[str, Any]) -> dict[str, Any]:
    """Validate a stored override, keeping only the fields it actually sets."""
    changes = CameraChanges.model_validate(fields)
    supplied = changes.supplied()
    if "stream_url" in supplied:
        supplied["stream_url"] = normalise_stream_url(supplied["stream_url"])
    return supplied


def _reject_nulls(supplied: dict[str, Any]) -> None:
    for field in ("name", "role", "enabled", "location"):
        if field in supplied and supplied[field] is None:
            raise ValueError(f"{field} cannot be cleared")


def _serialisable(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, Path):
            out[key] = str(value)
        elif isinstance(value, CameraRole):
            out[key] = value.value
        else:
            out[key] = value
    return out


def _as_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, Path) else Path(str(value))
