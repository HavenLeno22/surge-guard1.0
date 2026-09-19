"""A DroidCam emulator, for testing several cameras without several phones.

Serves a video file the way a phone running DroidCam serves its camera:

- ``/video`` - an MJPEG stream (``multipart/x-mixed-replace``), looping the file
  at its own frame rate;
- **one viewer at a time** - a second client receives the same "DroidCam is
  Busy" page a real phone returns, which is the behaviour SurgeGuard's camera
  manager and connection tests are built around;
- ``/v1/phone/name`` and ``/v1/phone/battery_level`` - the small device
  endpoints SurgeGuard uses for latency and battery;
- ``/`` - redirects to ``/remote``, as the app does.

**A development tool, never a demonstration source.** The frames are whatever
file it is given, the device name and battery are made up, and SurgeGuard labels
nothing it produces as coming from a phone. Use it to exercise multi-camera
perception, failure handling (stop one emulator and watch that camera recover
while the other keeps running) and the Camera Network page.

    python scripts/droidcam_emulator.py --port 4801 --name EMU-01
    python scripts/droidcam_emulator.py --port 4802 --name EMU-02 --width 1280 --height 720
"""

from __future__ import annotations

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

DEFAULT_VIDEO = Path(__file__).resolve().parents[1] / "data" / "scenarios" / "00_placeholder.mp4"

BUSY_PAGE = (
    b"<!doctype html><html><head><meta charset='utf-8'><title>DroidCam</title></head>"
    b"<body style='color:white;background:#1b1b1b;text-align:center'>"
    b"<p>DroidCam is Busy</p></body></html>"
)


def build_handler(
    video: Path,
    name: str,
    battery: int,
    size: tuple[int, int] | None,
    quality: int,
) -> type[BaseHTTPRequestHandler]:
    viewer_lock = threading.Lock()

    class DroidCamHandler(BaseHTTPRequestHandler):
        server_version = "DroidCamEmulator/1.0"

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"[{name}] {self.address_string()} {fmt % args}", flush=True)

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            if self.path.startswith("/video"):
                self._stream()
            elif self.path == "/v1/phone/name":
                self._text(name.encode())
            elif self.path == "/v1/phone/battery_level":
                self._text(str(battery).encode())
            elif self.path == "/":
                self.send_response(302)
                self.send_header("Location", "/remote")
                self.end_headers()
            elif self.path == "/remote":
                self._text(b"<html><body>DroidCam Remote (emulated)</body></html>", "text/html")
            else:
                self.send_error(404)

        def _text(self, body: bytes, content_type: str = "text/plain; charset=UTF-8") -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _stream(self) -> None:
            if not viewer_lock.acquire(blocking=False):
                # The behaviour that matters: a phone serves one viewer.
                self._text(BUSY_PAGE, "text/html; charset=UTF-8")
                return
            capture = cv2.VideoCapture(str(video))
            try:
                if not capture.isOpened():
                    self.send_error(500, "video could not be opened")
                    return
                fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
                interval = 1.0 / fps
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

                next_at = time.perf_counter()
                while True:
                    ok, image = capture.read()
                    if not ok:
                        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    if size is not None:
                        image = cv2.resize(image, size, interpolation=cv2.INTER_LINEAR)
                    ok, jpeg = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                    if not ok:
                        continue
                    payload = jpeg.tobytes()
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(payload)).encode()
                        + b"\r\n\r\n"
                        + payload
                        + b"\r\n"
                    )
                    next_at += interval
                    delay = next_at - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                    else:
                        next_at = time.perf_counter()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                capture.release()
                viewer_lock.release()
                print(f"[{name}] viewer disconnected", flush=True)

    return DroidCamHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4747)
    parser.add_argument("--name", default="EMULATOR")
    parser.add_argument("--battery", type=int, default=80)
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--quality", type=int, default=80)
    args = parser.parse_args()

    if not args.video.is_file():
        raise SystemExit(f"Video not found: {args.video}")
    size = (args.width, args.height) if args.width and args.height else None

    handler = build_handler(args.video, args.name, args.battery, size, args.quality)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(
        f"[{args.name}] serving {args.video.name} at http://{args.host}:{args.port}/video "
        "(one viewer at a time)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
