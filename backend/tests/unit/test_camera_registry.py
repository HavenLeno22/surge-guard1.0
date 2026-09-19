"""The camera registry - which cameras exist and where their streams are.

Cameras are seeded from the environment and edited from the Command Center.
The properties that matter:

- Reading never writes. A deployment that has never been edited has no registry
  file at all, and a test suite reading the default path leaves nothing behind.
- An operator edit wins over the environment for exactly the fields it changed,
  and survives a restart - so a phone whose IP changed can be followed from the
  interface without touching ``.env``.
- Removal of an environment-declared camera is remembered; otherwise it would
  reappear on the next restart and the operator would stop trusting the delete.
- The primary camera cannot be removed: the single-camera routes describe it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from surgeguard_ai.contracts import CameraRole

from app.cameras.definitions import (
    CameraChanges,
    CameraOrigin,
    CameraSpec,
    UrlSource,
    normalise_stream_url,
)
from app.cameras.registry import (
    CameraConflictError,
    CameraNotFoundError,
    CameraRegistry,
    CameraRegistryError,
)
from app.core.config import CameraSeed

PRIMARY = CameraSeed(
    index=1,
    camera_id="cam-01",
    name="Main Entrance",
    url="http://172.30.213.172:4747/video",
)
TEAM = CameraSeed(
    index=2,
    camera_id="cam-02",
    name="Team Camera",
    url="http://172.18.225.59:4747/video",
    role=CameraRole.QUEUE,
)


def make_registry(path: Path, seeds: tuple[CameraSeed, ...] = (PRIMARY, TEAM)) -> CameraRegistry:
    return CameraRegistry(path, seeds=seeds, primary_camera_id="cam-01")


def test_environment_cameras_resolve_in_order_with_the_primary_first(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "cameras.json")

    cameras = registry.cameras()

    assert [camera.camera_id for camera in cameras] == ["cam-01", "cam-02"]
    primary, team = cameras
    assert primary.is_primary and not team.is_primary
    assert team.origin is CameraOrigin.ENVIRONMENT
    assert team.url_source is UrlSource.ENVIRONMENT
    assert team.stream_url == "http://172.18.225.59:4747/video"
    assert team.role is CameraRole.QUEUE
    # A camera with no declared coverage area watches an area of its own.
    assert team.coverage_area == "cam-02"


def test_reading_never_creates_the_registry_file(tmp_path: Path) -> None:
    path = tmp_path / "cameras.json"
    make_registry(path).cameras()
    assert not path.exists()


def test_an_operator_camera_is_saved_and_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "cameras.json"
    registry = make_registry(path)

    added = registry.add(
        CameraSpec(
            camera_id="CAM-03",
            name="Counter View",
            stream_url="192.168.1.40:4747",
            role=CameraRole.SERVICE,
        )
    )

    assert added.camera_id == "cam-03"
    assert added.origin is CameraOrigin.OPERATOR
    assert added.url_source is UrlSource.REGISTRY
    assert added.stream_url == "http://192.168.1.40:4747/video"
    assert path.exists()

    reloaded = make_registry(path)
    assert [camera.camera_id for camera in reloaded.cameras()] == [
        "cam-01",
        "cam-02",
        "cam-03",
    ]


def test_an_omitted_id_is_assigned_after_the_highest_existing_one(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "cameras.json")
    added = registry.add(CameraSpec(name="Overflow", stream_url="http://10.0.0.9:4747/video"))
    assert added.camera_id == "cam-03"


def test_an_id_already_in_use_is_refused(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "cameras.json")
    with pytest.raises(CameraConflictError, match="cam-02"):
        registry.add(CameraSpec(camera_id="cam-02", name="Duplicate"))


def test_editing_an_environment_camera_overrides_only_what_changed(tmp_path: Path) -> None:
    path = tmp_path / "cameras.json"
    registry = make_registry(path)

    updated = registry.update(
        "cam-02", CameraChanges(stream_url="http://172.18.230.10:4747/video")
    )

    assert updated.stream_url == "http://172.18.230.10:4747/video"
    assert updated.url_source is UrlSource.REGISTRY
    assert updated.name == "Team Camera", "fields not edited keep their environment value"

    # The edit survives a restart, and wins over the environment value even if
    # the environment still carries the old address.
    reloaded = make_registry(path)
    assert reloaded.get("cam-02").stream_url == "http://172.18.230.10:4747/video"


def test_clearing_an_overridden_url_returns_to_the_environment_value(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "cameras.json")
    registry.update("cam-02", CameraChanges(stream_url="http://172.18.230.10:4747/video"))

    restored = registry.update("cam-02", CameraChanges(stream_url=None))

    assert restored.stream_url == "http://172.18.225.59:4747/video"
    assert restored.url_source is UrlSource.ENVIRONMENT


def test_a_removed_environment_camera_stays_removed_after_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "cameras.json"
    registry = make_registry(path)

    registry.remove("cam-02")

    assert [camera.camera_id for camera in make_registry(path).cameras()] == ["cam-01"]


def test_adding_a_removed_environment_camera_restores_it(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "cameras.json")
    registry.remove("cam-02")

    restored = registry.add(
        CameraSpec(camera_id="cam-02", name="Queue Side", stream_url="http://172.18.225.60:4747/video")
    )

    assert restored.name == "Queue Side"
    assert restored.stream_url == "http://172.18.225.60:4747/video"
    assert restored.origin is CameraOrigin.ENVIRONMENT


def test_the_primary_camera_cannot_be_removed(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "cameras.json")
    with pytest.raises(CameraConflictError, match="disable"):
        registry.remove("cam-01")


def test_an_operator_camera_is_deleted_outright(tmp_path: Path) -> None:
    path = tmp_path / "cameras.json"
    registry = make_registry(path)
    registry.add(CameraSpec(camera_id="cam-03", name="Temporary"))

    registry.remove("cam-03")

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["cameras"] == []
    assert "cam-03" not in stored["removed"]


def test_unknown_cameras_are_reported(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "cameras.json")
    with pytest.raises(CameraNotFoundError):
        registry.update("cam-99", CameraChanges(name="Nobody"))
    with pytest.raises(CameraNotFoundError):
        registry.remove("cam-99")


def test_disabling_is_an_edit_not_a_removal(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "cameras.json")
    disabled = registry.update("cam-01", CameraChanges(enabled=False))
    assert disabled.enabled is False
    assert [camera.camera_id for camera in registry.cameras()] == ["cam-01", "cam-02"]


def test_a_malformed_file_leaves_the_environment_cameras_and_refuses_writes(
    tmp_path: Path,
) -> None:
    """A broken registry must not stop the platform, nor be silently overwritten."""
    path = tmp_path / "cameras.json"
    path.write_text("{not json", encoding="utf-8")

    registry = make_registry(path)

    assert registry.load_error is not None
    assert [camera.camera_id for camera in registry.cameras()] == ["cam-01", "cam-02"]
    with pytest.raises(CameraRegistryError, match="could not be read"):
        registry.update("cam-02", CameraChanges(name="Edited"))
    assert path.read_text(encoding="utf-8") == "{not json"


def test_saving_leaves_no_temporary_files(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "cameras.json")
    registry.update("cam-02", CameraChanges(name="Renamed"))
    assert sorted(item.name for item in tmp_path.iterdir()) == ["cameras.json"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("172.18.225.59", "http://172.18.225.59:4747/video"),
        ("172.18.225.59:4747", "http://172.18.225.59:4747/video"),
        ("172.18.225.59:8080/video", "http://172.18.225.59:8080/video"),
        (" http://172.18.225.59:4747/video ", "http://172.18.225.59:4747/video"),
        ("rtsp://user:pass@10.0.0.4:554/stream1", "rtsp://user:pass@10.0.0.4:554/stream1"),
        ("0", "0"),
        ("", None),
        (None, None),
    ],
)
def test_stream_urls_are_normalised(raw: str | None, expected: str | None) -> None:
    assert normalise_stream_url(raw) == expected


@pytest.mark.parametrize("raw", ["ftp://10.0.0.4/video", "not a camera", "http://"])
def test_unusable_stream_urls_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="stream"):
        normalise_stream_url(raw)
