"""Frame source construction for each camera.

The sources are built but never opened, so no camera, network or clip is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from surgeguard_ai.contracts import CameraRole, SourceMode
from surgeguard_ai.perception import LiveCameraSource, VideoFileSource

from app.cameras.definitions import CameraDefinition, CameraOrigin, UrlSource
from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.workers import perception_factory
from app.workers.perception_factory import build_frame_source


def _definition(
    camera_id: str = "cam-02",
    stream_url: str | None = "http://192.0.2.10:4747/video",
    demo_video_path: Path | None = None,
) -> CameraDefinition:
    return CameraDefinition(
        camera_id=camera_id,
        name="Team Camera",
        location="",
        role=CameraRole.QUEUE,
        stream_url=stream_url,
        url_source=UrlSource.ENVIRONMENT if stream_url else UrlSource.UNSET,
        demo_video_path=demo_video_path,
        enabled=True,
        coverage_area=None,
        origin=CameraOrigin.ENVIRONMENT,
        is_primary=False,
        order=2,
    )


@pytest.fixture
def live_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"pipeline_source_mode": SourceMode.LIVE})


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """The arguments each live source was built with."""
    calls: list[dict[str, object]] = []

    class _Recording(LiveCameraSource):
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)
            super().__init__(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(perception_factory, "LiveCameraSource", _Recording)
    return calls


def test_a_network_camera_gets_timeouts_and_a_quick_handover_to_recovery(
    live_settings: Settings, captured: list[dict[str, object]]
) -> None:
    source = build_frame_source(live_settings, definition=_definition())

    assert isinstance(source, LiveCameraSource)
    (kwargs,) = captured
    assert kwargs["device"] == "http://192.0.2.10:4747/video"
    assert kwargs["open_timeout_ms"] == int(live_settings.live_camera_open_timeout_seconds * 1000)
    assert kwargs["read_timeout_ms"] == int(live_settings.live_camera_read_timeout_seconds * 1000)
    assert kwargs["max_stall_seconds"] == live_settings.live_camera_stall_seconds
    # One in-place attempt absorbs a blip; anything longer is the worker's to
    # recover, where the reason is reported and "Reconnect now" works.
    assert kwargs["reconnect_attempts"] == 1


def test_a_local_device_index_is_opened_exactly_as_before(
    live_settings: Settings, captured: list[dict[str, object]]
) -> None:
    build_frame_source(live_settings.model_copy(update={"live_camera_device": "0"}))

    (kwargs,) = captured
    assert kwargs["device"] == 0
    network_only = ("open_timeout_ms", "read_timeout_ms", "max_stall_seconds", "reconnect_attempts")
    for name in network_only:
        assert name not in kwargs


def test_a_live_camera_without_an_address_is_a_configuration_error(
    live_settings: Settings,
) -> None:
    with pytest.raises(ConfigurationError, match="no stream address"):
        build_frame_source(live_settings, definition=_definition(stream_url=None))


def test_an_additional_camera_in_demonstration_mode_needs_its_own_clip(
    settings: Settings, tmp_path: Path
) -> None:
    demo = settings.model_copy(update={"pipeline_source_mode": SourceMode.DEMO})

    with pytest.raises(ConfigurationError):
        build_frame_source(demo, definition=_definition())

    clip = tmp_path / "queue.mp4"
    clip.write_bytes(b"not decoded until opened")
    source = build_frame_source(demo, definition=_definition(demo_video_path=clip))
    assert isinstance(source, VideoFileSource)
