"""Camera configuration read from the environment.

The primary camera is configured exactly as it always was
(``SURGEGUARD_CAMERA_ID/NAME/LOCATION`` and ``SURGEGUARD_LIVE_CAMERA_DEVICE``).
Every further camera is declared with indexed variables -
``SURGEGUARD_CAMERA_2_URL``, ``SURGEGUARD_CAMERA_3_NAME`` - so adding a camera, or
following a phone whose IP address changed, is an edit to ``.env`` and never an
edit to source code.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from surgeguard_ai.contracts import CameraRole

from app.core.config import Settings, normalise_camera_id


def _clear_camera_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any indexed camera variables a developer's shell might carry."""
    import os

    for key in list(os.environ):
        if key.upper().startswith("SURGEGUARD_CAMERA_") and key.upper()[18:19].isdigit():
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_camera_environment(monkeypatch)


def test_the_primary_camera_is_described_by_the_existing_settings() -> None:
    settings = Settings(
        _env_file=None,
        camera_id="cam-01",
        camera_name="Main Entrance",
        camera_location="Hall A",
        live_camera_device="http://10.0.0.5:4747/video",
    )

    primary = settings.primary_camera_seed
    assert primary.index == 1
    assert primary.camera_id == "cam-01"
    assert primary.name == "Main Entrance"
    assert primary.location == "Hall A"
    assert primary.url == "http://10.0.0.5:4747/video"
    assert settings.additional_cameras == ()
    assert [seed.camera_id for seed in settings.camera_seeds] == ["cam-01"]


def test_an_indexed_camera_is_read_from_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SURGEGUARD_CAMERA_2_ID", "CAM-02")
    monkeypatch.setenv("SURGEGUARD_CAMERA_2_NAME", "Team Camera")
    monkeypatch.setenv("SURGEGUARD_CAMERA_2_URL", "http://172.18.225.59:4747/video")
    monkeypatch.setenv("SURGEGUARD_CAMERA_2_ROLE", "QUEUE")

    settings = Settings(_env_file=None)

    (seed,) = settings.additional_cameras
    assert seed.index == 2
    # Identifiers are canonical lowercase slugs - they name files and URLs - and
    # the interface is free to display them in upper case.
    assert seed.camera_id == "cam-02"
    assert seed.name == "Team Camera"
    assert seed.url == "http://172.18.225.59:4747/video"
    assert seed.role is CameraRole.QUEUE
    assert seed.enabled is True


def test_an_indexed_camera_is_read_from_a_dotenv_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SURGEGUARD_CAMERA_3_NAME=Counter View\n"
        "SURGEGUARD_CAMERA_3_URL=http://192.168.1.40:4747/video\n"
        "SURGEGUARD_CAMERA_3_ENABLED=false\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    (seed,) = settings.additional_cameras
    # An omitted identifier and name are derived from the index rather than
    # refused, so the shortest useful declaration is a single URL line.
    assert seed.camera_id == "cam-03"
    assert seed.name == "Counter View"
    assert seed.enabled is False


def test_the_process_environment_wins_over_the_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SURGEGUARD_CAMERA_2_URL=http://old-address:4747/video\n", encoding="utf-8"
    )
    monkeypatch.setenv("SURGEGUARD_CAMERA_2_URL", "http://new-address:4747/video")

    settings = Settings(_env_file=env_file)

    assert settings.additional_cameras[0].url == "http://new-address:4747/video"


def test_cameras_are_ordered_by_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SURGEGUARD_CAMERA_4_URL", "http://d:4747/video")
    monkeypatch.setenv("SURGEGUARD_CAMERA_2_URL", "http://b:4747/video")

    settings = Settings(_env_file=None)

    assert [seed.index for seed in settings.additional_cameras] == [2, 4]
    assert [seed.camera_id for seed in settings.camera_seeds] == [
        "cam-01",
        "cam-02",
        "cam-04",
    ]


def test_index_one_is_reserved_for_the_primary_camera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two ways to configure one camera would eventually disagree."""
    monkeypatch.setenv("SURGEGUARD_CAMERA_1_URL", "http://a:4747/video")

    with pytest.raises(ValidationError, match="SURGEGUARD_LIVE_CAMERA_DEVICE"):
        Settings(_env_file=None)


def test_a_misspelt_camera_variable_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo must fail at startup, not leave a camera silently unconfigured."""
    monkeypatch.setenv("SURGEGUARD_CAMERA_2_ULR", "http://a:4747/video")

    with pytest.raises(ValidationError, match="ulr"):
        Settings(_env_file=None)


def test_a_camera_may_not_reuse_another_cameras_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SURGEGUARD_CAMERA_2_ID", "cam-01")

    with pytest.raises(ValidationError, match="cam-01"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("cam-02", "cam-02"), ("CAM-02", "cam-02"), ("  Queue_Side ", "queue_side")],
)
def test_camera_ids_are_normalised_to_lowercase_slugs(raw: str, expected: str) -> None:
    assert normalise_camera_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "cam 02", "cam/02", "-cam", "x" * 40])
def test_unusable_camera_ids_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="camera id"):
        normalise_camera_id(raw)
