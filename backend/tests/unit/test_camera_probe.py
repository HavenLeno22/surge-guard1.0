"""Connection tests and stream diagnosis.

Driven by a real HTTP server on the loopback interface that imitates the
responses a DroidCam phone gives - a video stream, the "DroidCam is Busy" page,
its device endpoints - so the classification is tested against the bytes it
will actually see, not against a mock of urllib.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.cameras.probe import (
    StreamOutcome,
    diagnose_stream,
    fetch_device_info,
    run_connection_test,
    stream_endpoint,
)

BUSY_PAGE = (
    b"<!doctype html><html><head><title>DroidCam</title></head>"
    b"<body><p>DroidCam is Busy</p></body></html>"
)


class _FakeDroidCam(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:  # silence test output
        return

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path == "/video":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                ok, jpeg = cv2.imencode(".jpg", np.zeros((48, 64, 3), dtype=np.uint8))
                assert ok
                for _ in range(3):
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(jpeg.tobytes() + b"\r\n")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        if self.path == "/busy":
            self._text(200, BUSY_PAGE, "text/html; charset=UTF-8")
            return
        if self.path == "/remote":
            self._text(200, b"<html><body>DroidCam Remote</body></html>", "text/html")
            return
        if self.path == "/v1/phone/name":
            self._text(200, b"A015", "text/plain")
            return
        if self.path == "/v1/phone/battery_level":
            self._text(200, b"58", "text/plain")
            return
        self._text(404, b"not found", "text/plain")

    def _text(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def droidcam() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeDroidCam)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_video_stream_is_recognised_without_decoding_it(droidcam: str) -> None:
    diagnosis = diagnose_stream(f"{droidcam}/video")
    assert diagnosis.outcome is StreamOutcome.STREAMING


def test_a_busy_droidcam_is_reported_as_busy_with_what_to_do(droidcam: str) -> None:
    """The field failure: HTTP 200, but the phone already has a client."""
    diagnosis = diagnose_stream(f"{droidcam}/busy")

    assert diagnosis.outcome is StreamOutcome.BUSY
    assert "another client" in diagnosis.detail
    assert "Close the other viewer" in diagnosis.detail


def test_a_web_page_is_not_mistaken_for_a_stream(droidcam: str) -> None:
    diagnosis = diagnose_stream(f"{droidcam}/remote")
    assert diagnosis.outcome is StreamOutcome.NOT_A_STREAM
    assert ":4747/video" in diagnosis.detail


def test_a_wrong_path_is_an_http_error_that_names_the_right_one(droidcam: str) -> None:
    diagnosis = diagnose_stream(f"{droidcam}/mjpegfeed")
    assert diagnosis.outcome is StreamOutcome.HTTP_ERROR
    assert diagnosis.http_status == 404
    assert "/video" in diagnosis.detail


def test_nothing_listening_is_unreachable(closed_port: int) -> None:
    diagnosis = diagnose_stream(f"http://127.0.0.1:{closed_port}/video", timeout_seconds=1.0)
    assert diagnosis.outcome is StreamOutcome.UNREACHABLE


def test_a_device_index_cannot_be_diagnosed_over_http() -> None:
    assert diagnose_stream("0").outcome is StreamOutcome.NOT_DIAGNOSABLE


def test_device_details_come_from_the_droidcam_endpoints(droidcam: str) -> None:
    info = fetch_device_info(f"{droidcam}/video")

    assert info is not None
    assert info.device_name == "A015"
    assert info.battery_percent == 58
    assert info.network_rtt_ms is not None and info.network_rtt_ms >= 0


def test_an_absent_host_has_no_device_details(closed_port: int) -> None:
    assert fetch_device_info(f"http://127.0.0.1:{closed_port}/video", timeout_seconds=1.0) is None


def test_a_connection_test_against_a_busy_camera_fails_with_the_reason(droidcam: str) -> None:
    result = run_connection_test(f"{droidcam}/busy", read_seconds=0.2)

    assert not result.success
    assert result.outcome is StreamOutcome.BUSY
    # Device details are still reported: the phone is reachable, just occupied.
    assert result.device_name == "A015"
    assert result.frames_read == 0


def test_a_connection_test_measures_what_it_reads(tmp_path: Path) -> None:
    """Resolution and frame rate come from frames actually decoded."""
    clip = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"MJPG"), 25.0, (160, 120))
    assert writer.isOpened()
    for index in range(60):
        frame = np.full((120, 160, 3), index * 4 % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    result = run_connection_test(str(clip), read_seconds=0.2)

    assert result.success
    assert result.outcome is StreamOutcome.OK
    assert (result.width, result.height) == (160, 120)
    assert result.frames_read > 1
    assert result.measured_fps is not None and result.measured_fps > 0
    assert result.first_frame_ms is not None


def test_a_missing_source_fails_to_open(tmp_path: Path) -> None:
    result = run_connection_test(str(tmp_path / "absent.avi"), read_seconds=0.1)
    assert not result.success
    assert result.outcome is StreamOutcome.OPEN_FAILED


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://172.18.225.59:4747/video", ("172.18.225.59", 4747)),
        ("HTTP://Phone.Local/video", ("phone.local", 80)),
        ("rtsp://10.0.0.4/stream", ("10.0.0.4", 554)),
        ("0", None),
    ],
)
def test_stream_endpoints_identify_the_device(url: str, expected: tuple[str, int] | None) -> None:
    assert stream_endpoint(url) == expected
