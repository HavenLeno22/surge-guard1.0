"""Camera connection tests and stream diagnosis.

Three jobs, all run on demand or on a slow timer, never in a loop against a
stream:

``diagnose_stream``
    Why a stream address does or does not deliver video. OpenCV reports only
    "could not open"; an operator needs to know whether the phone is off the
    network, whether the address is a web page, or - the case that cost time in
    the field - whether **DroidCam is busy** because another client already
    holds the phone's single stream.

``fetch_device_info``
    DroidCam's small device endpoints (``/v1/phone/name``,
    ``/v1/phone/battery_level``). They answer while the video stream is in use,
    so they measure network round-trip time and battery without competing for
    the stream.

``run_connection_test``
    Open a stream, read frames for a few seconds, measure resolution and frame
    rate, release it. Used only for an address no running camera owns: DroidCam
    serves one client per phone, and a test that opened a second connection to
    a camera SurgeGuard is already reading would steal the stream it is testing.

Everything here blocks and is meant to run on a worker thread.
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlsplit

import cv2

__all__ = [
    "CameraDeviceInfo",
    "ConnectionTestResult",
    "StreamDiagnosis",
    "StreamOutcome",
    "diagnose_stream",
    "fetch_device_info",
    "is_network_url",
    "run_connection_test",
    "stream_endpoint",
]

#: Bytes of a text response inspected for a busy message. DroidCam's busy page
#: is under 1 KB; reading more would only delay the answer.
_BODY_SAMPLE_BYTES = 4096


class StreamOutcome(StrEnum):
    """What a stream address turned out to be."""

    OK = "OK"
    """Frames were received."""

    STREAMING = "STREAMING"
    """The address serves a video stream (diagnosis only - no frames read)."""

    BUSY = "BUSY"
    """The camera serves one client and another client already has the stream."""

    UNREACHABLE = "UNREACHABLE"
    """Nothing answered at the address."""

    NOT_A_STREAM = "NOT_A_STREAM"
    """Something answered, but with a web page rather than video."""

    HTTP_ERROR = "HTTP_ERROR"
    """The server refused the request."""

    OPEN_FAILED = "OPEN_FAILED"
    """The stream could not be opened for decoding."""

    NO_FRAMES = "NO_FRAMES"
    """The stream opened but delivered no decodable frame."""

    NOT_DIAGNOSABLE = "NOT_DIAGNOSABLE"
    """The address is not HTTP, so there is nothing to inspect without opening it."""


@dataclass(frozen=True, slots=True)
class StreamDiagnosis:
    """The outcome of inspecting a stream address, in operator terms."""

    outcome: StreamOutcome
    detail: str
    http_status: int | None = None
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class CameraDeviceInfo:
    """What a DroidCam phone reports about itself."""

    network_rtt_ms: float | None
    device_name: str | None = None
    battery_percent: int | None = None


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    """Everything a connection test measured."""

    url: str
    success: bool
    outcome: StreamOutcome
    detail: str
    tested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_seconds: float = 0.0
    width: int | None = None
    height: int | None = None
    reported_fps: float | None = None
    measured_fps: float | None = None
    first_frame_ms: float | None = None
    frames_read: int = 0
    failed_reads: int = 0
    network_rtt_ms: float | None = None
    device_name: str | None = None
    battery_percent: int | None = None
    live_measurement: bool = False
    """True when these figures came from SurgeGuard's own running connection
    to the camera rather than a second, competing one."""


def is_network_url(target: str | None) -> bool:
    """Whether a stream address is an HTTP(S) URL that can be inspected."""
    if not target:
        return False
    return urlsplit(target).scheme.lower() in {"http", "https"}


def stream_endpoint(target: str) -> tuple[str, int] | None:
    """The ``(host, port)`` a network stream is served from, for ownership checks."""
    parts = urlsplit(target)
    if parts.scheme.lower() not in {"http", "https", "rtsp", "rtsps"} or not parts.hostname:
        return None
    default_port = {"http": 80, "https": 443, "rtsp": 554, "rtsps": 322}[parts.scheme.lower()]
    return parts.hostname.lower(), parts.port or default_port


def diagnose_stream(url: str, *, timeout_seconds: float = 3.0) -> StreamDiagnosis:
    """Inspect a stream address without decoding any video.

    Reads the response headers and, for a text response, a small sample of the
    body. A video response is closed as soon as its content type is known, so
    the camera is held for no longer than one request.
    """
    if not is_network_url(url):
        return StreamDiagnosis(
            StreamOutcome.NOT_DIAGNOSABLE,
            "Only HTTP stream addresses can be inspected before opening.",
        )

    request = urllib.request.Request(url, headers={"User-Agent": "SurgeGuard-Probe/1.0"})
    host = _host_label(url)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - operator-supplied camera address
            status = int(response.status)
            content_type = (response.headers.get("Content-Type") or "").lower()

            if content_type.startswith("multipart/x-mixed-replace") or content_type.startswith(
                "video/"
            ):
                return StreamDiagnosis(
                    StreamOutcome.STREAMING,
                    f"{host} is serving a video stream.",
                    status,
                    content_type,
                )

            sample = response.read(_BODY_SAMPLE_BYTES).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return StreamDiagnosis(
            StreamOutcome.HTTP_ERROR,
            f"{host} answered HTTP {error.code}"
            + (" - check the path; DroidCam streams at /video." if error.code == 404 else "."),
            error.code,
            (error.headers.get("Content-Type") if error.headers else None),
        )
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        reason = getattr(error, "reason", error)
        return StreamDiagnosis(
            StreamOutcome.UNREACHABLE,
            f"No response from {host}: {_describe_network_error(reason)}. Check that the "
            "phone is on the same network and DroidCam is open.",
        )

    if "busy" in sample.lower():
        return StreamDiagnosis(
            StreamOutcome.BUSY,
            f"DroidCam at {host} is busy: another client is already connected to its "
            "stream. Close the other viewer (DroidCam PC client, OBS or a browser tab) "
            "and SurgeGuard will connect.",
            status,
            content_type,
        )

    return StreamDiagnosis(
        StreamOutcome.NOT_A_STREAM,
        f"{host} answered with a web page, not a video stream. For DroidCam the "
        "stream address is http://<phone-ip>:4747/video.",
        status,
        content_type,
    )


def fetch_device_info(url: str, *, timeout_seconds: float = 2.0) -> CameraDeviceInfo | None:
    """Ask a DroidCam phone for its name and battery, timing the round trip.

    Returns ``None`` when the host does not answer at all. A host that answers
    but is not DroidCam yields a round-trip time with no name or battery - the
    latency is real even when the device details are not available.
    """
    if not is_network_url(url):
        return None

    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"

    started = time.perf_counter()
    name, reachable = _get_text(f"{base}/v1/phone/name", timeout_seconds)
    rtt_ms = (time.perf_counter() - started) * 1000.0
    if not reachable:
        return None

    battery_text, _ = _get_text(f"{base}/v1/phone/battery_level", timeout_seconds)
    battery: int | None = None
    if battery_text is not None and battery_text.strip().isdigit():
        value = int(battery_text.strip())
        battery = value if 0 <= value <= 100 else None

    device_name = name.strip() if name and name.strip() and len(name.strip()) <= 64 else None
    return CameraDeviceInfo(network_rtt_ms=rtt_ms, device_name=device_name, battery_percent=battery)


def run_connection_test(
    target: str,
    *,
    read_seconds: float = 3.0,
    open_target: int | str | None = None,
) -> ConnectionTestResult:
    """Open a stream, read it briefly, measure it and release it.

    Args:
        target: The stream address as configured.
        read_seconds: How long to read frames for after the first one.
        open_target: What OpenCV should actually open, when that differs from
            ``target`` - a device index is the integer ``0``, not the string.
    """
    started = time.perf_counter()
    device = fetch_device_info(target) if is_network_url(target) else None

    if is_network_url(target):
        diagnosis = diagnose_stream(target)
        if diagnosis.outcome is not StreamOutcome.STREAMING:
            return ConnectionTestResult(
                url=target,
                success=False,
                outcome=diagnosis.outcome,
                detail=diagnosis.detail,
                duration_seconds=time.perf_counter() - started,
                network_rtt_ms=device.network_rtt_ms if device else None,
                device_name=device.device_name if device else None,
                battery_percent=device.battery_percent if device else None,
            )

    capture = cv2.VideoCapture(open_target if open_target is not None else target)
    try:
        if not capture.isOpened():
            return _failed(
                target,
                StreamOutcome.OPEN_FAILED,
                "The stream could not be opened for decoding.",
                started,
                device,
            )

        opened_at = time.perf_counter()
        ok, image = capture.read()
        if not ok or image is None:
            return _failed(
                target,
                StreamOutcome.NO_FRAMES,
                "The stream opened but delivered no frame.",
                started,
                device,
            )
        first_frame_ms = (time.perf_counter() - opened_at) * 1000.0
        height, width = image.shape[:2]
        reported = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)

        frames = 0
        failures = 0
        window_started = time.perf_counter()
        while time.perf_counter() - window_started < read_seconds:
            ok, image = capture.read()
            if ok and image is not None:
                frames += 1
            else:
                failures += 1
                if failures >= 30:
                    break
        elapsed = max(time.perf_counter() - window_started, 1e-6)
    finally:
        capture.release()

    measured = frames / elapsed if frames else 0.0
    return ConnectionTestResult(
        url=target,
        success=frames > 0,
        outcome=StreamOutcome.OK if frames > 0 else StreamOutcome.NO_FRAMES,
        detail=(
            f"Connected: {width}x{height} at {measured:.1f} fps."
            if frames > 0
            else "The stream delivered one frame and then stopped."
        ),
        duration_seconds=time.perf_counter() - started,
        width=int(width),
        height=int(height),
        reported_fps=reported if reported > 0 else None,
        measured_fps=measured,
        first_frame_ms=first_frame_ms,
        frames_read=frames + 1,
        failed_reads=failures,
        network_rtt_ms=device.network_rtt_ms if device else None,
        device_name=device.device_name if device else None,
        battery_percent=device.battery_percent if device else None,
    )


# -- Internals ----------------------------------------------------------------


def _failed(
    target: str,
    outcome: StreamOutcome,
    detail: str,
    started: float,
    device: CameraDeviceInfo | None,
) -> ConnectionTestResult:
    return ConnectionTestResult(
        url=target,
        success=False,
        outcome=outcome,
        detail=detail,
        duration_seconds=time.perf_counter() - started,
        network_rtt_ms=device.network_rtt_ms if device else None,
        device_name=device.device_name if device else None,
        battery_percent=device.battery_percent if device else None,
    )


def _get_text(url: str, timeout_seconds: float) -> tuple[str | None, bool]:
    """GET a small text resource. Returns ``(text or None, host_answered)``."""
    request = urllib.request.Request(url, headers={"User-Agent": "SurgeGuard-Probe/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - operator-supplied camera address
            return response.read(256).decode("utf-8", errors="replace"), True
    except urllib.error.HTTPError:
        return None, True
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return None, False


def _host_label(url: str) -> str:
    parts = urlsplit(url)
    return parts.netloc or url


def _describe_network_error(reason: object) -> str:
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timed out"
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    text = str(reason)
    return text if text else reason.__class__.__name__
