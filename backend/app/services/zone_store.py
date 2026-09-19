"""Persistence for operator-defined camera zones.

Zones are what make Queue Intelligence possible at all: without a QUEUE zone
there is no queue to measure, and without a COUNTER zone the platform cannot
tell a person who was served from a person who gave up. They are therefore
operator configuration of the most consequential kind, and they must survive a
restart - an operator who redraws their queue boundary after every deployment
will stop drawing it.

They are stored as JSON on disk rather than in the database because they are
configuration rather than observation: a zone is a statement about the venue,
not a record of something that happened. Keeping them out of the time-series
tables also means the zone an old observation was measured against can be read
without joining against a table that is being written to ten times a second.

The file is the source of truth and is written atomically, so a crash during a
save leaves the previous definition intact rather than a truncated one.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from surgeguard_ai.contracts import CameraZone, ImagePoint, ImagePolygon, ZoneType

__all__ = ["ZoneStore", "ZoneStoreError"]

logger = logging.getLogger(__name__)

#: Bumped when the on-disk shape changes, so an old file is rejected with a
#: clear message rather than parsed into something subtly wrong.
SCHEMA_VERSION = 1


class ZoneStoreError(RuntimeError):
    """A zone definition could not be read or written."""


class ZoneStore:
    """Reads and writes the zone set for one camera."""

    def __init__(self, directory: Path, camera_id: str) -> None:
        self._directory = directory
        self._camera_id = camera_id
        self._path = directory / f"{camera_id}.json"
        self._zones: tuple[CameraZone, ...] = ()
        self._loaded = False

    @property
    def path(self) -> Path:
        """Where this camera's zones live on disk."""
        return self._path

    @property
    def zones(self) -> tuple[CameraZone, ...]:
        """The current zone set, loading it on first access."""
        if not self._loaded:
            self.load()
        return self._zones

    # -- Reading ------------------------------------------------------------

    def load(self) -> tuple[CameraZone, ...]:
        """Load zones from disk.

        A missing file is not an error: a camera with no zones defined yet is
        an ordinary state, and the platform reports Queue Intelligence as
        unconfigured rather than refusing to start.
        """
        self._loaded = True

        if not self._path.exists():
            logger.info(
                "No zone definition for camera %s at %s - Queue Intelligence "
                "will report itself unconfigured until zones are drawn",
                self._camera_id,
                self._path,
            )
            self._zones = ()
            return self._zones

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ZoneStoreError(
                f"Could not read zone definition at {self._path}: {error}"
            ) from error

        version = raw.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ZoneStoreError(
                f"Zone definition at {self._path} has schema version {version!r}, "
                f"expected {SCHEMA_VERSION}. Refusing to guess at its meaning."
            )

        try:
            self._zones = tuple(
                _zone_from_dict(entry) for entry in raw.get("zones", [])
            )
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise ZoneStoreError(
                f"Zone definition at {self._path} is malformed: {error}"
            ) from error

        logger.info(
            "Loaded %d zone(s) for camera %s: %s",
            len(self._zones),
            self._camera_id,
            ", ".join(f"{z.name} ({z.zone_type.value})" for z in self._zones) or "none",
        )
        return self._zones

    # -- Writing ------------------------------------------------------------

    def save(self, zones: tuple[CameraZone, ...]) -> tuple[CameraZone, ...]:
        """Replace the zone set and write it to disk atomically.

        Written to a temporary file in the same directory and then renamed, so a
        crash mid-write leaves the previous definition intact. A partially
        written zone file would silently change where a queue is measured.
        """
        _reject_duplicate_ids(zones)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "camera_id": self._camera_id,
            "updated_at": datetime.now(UTC).isoformat(),
            "zones": [_zone_to_dict(zone) for zone in zones],
        }

        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._directory,
                prefix=f".{self._camera_id}.",
                suffix=".tmp",
                delete=False,
            )
            try:
                json.dump(payload, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            os.replace(handle.name, self._path)
        except OSError as error:
            raise ZoneStoreError(
                f"Could not write zone definition to {self._path}: {error}"
            ) from error

        self._zones = tuple(zones)
        self._loaded = True

        logger.info(
            "Saved %d zone(s) for camera %s", len(self._zones), self._camera_id
        )
        return self._zones

    # -- Convenience --------------------------------------------------------

    def of_type(self, zone_type: ZoneType) -> tuple[CameraZone, ...]:
        return tuple(zone for zone in self.zones if zone.zone_type is zone_type)

    @property
    def has_queue_zone(self) -> bool:
        """Whether Queue Intelligence has anything to measure."""
        return bool(self.of_type(ZoneType.QUEUE))


def _reject_duplicate_ids(zones: tuple[CameraZone, ...]) -> None:
    seen: set[str] = set()
    for zone in zones:
        if zone.zone_id in seen:
            raise ZoneStoreError(
                f"Duplicate zone id {zone.zone_id!r}. Zone ids address a zone in "
                "recommendations and measurements; two zones sharing one would "
                "make both unaddressable."
            )
        seen.add(zone.zone_id)


def _zone_to_dict(zone: CameraZone) -> dict:
    return {
        "zone_id": zone.zone_id,
        "name": zone.name,
        "zone_type": zone.zone_type.value,
        "width_m": zone.width_m,
        "polygon": [{"x": point.x, "y": point.y} for point in zone.polygon.points],
    }


def _zone_from_dict(entry: dict) -> CameraZone:
    return CameraZone(
        zone_id=entry["zone_id"],
        name=entry["name"],
        zone_type=ZoneType(entry["zone_type"]),
        width_m=entry.get("width_m"),
        polygon=ImagePolygon(
            points=tuple(
                ImagePoint(x=float(point["x"]), y=float(point["y"]))
                for point in entry["polygon"]
            )
        ),
    )
