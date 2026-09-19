"""Keep the local SurgeGuard deployment running until it is told to stop.

Every 15 s:
  * backend (127.0.0.1:8001, real backend/.env): started if nothing listens there;
    restarted if it stops answering /health for 45 s.
  * frontend dev server (127.0.0.1:5180): started if nothing listens there.
  * cameras: any enabled camera that has not been ONLINE for 45 s gets a retry
    (at most once a minute per camera), the same as the Retry button.
  * alert hardware: logged; the backend service reconnects COM8 on its own.

Stop everything by creating the file `scripts/STOP_SURGEGUARD`: the supervisor then
stops the backend (the board shows NO_DATA, or link lost if the backend was adopted
from an earlier run) and any frontend server it started itself. Closing the window
only kills the supervisor; the backend keeps running. A backend already listening
on 8001 is adopted rather than restarted, so replacing the supervisor does not
drop the cameras.

Run from the project root:  .venv\\Scripts\\python.exe scripts\\surgeguard_supervisor.py
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "scripts" / "logs"
STOP_FILE = ROOT / "scripts" / "STOP_SURGEGUARD"
BACKEND = "http://127.0.0.1:8001"
# An operator account for camera retries and status. Without it, only processes are supervised.
EMAIL = os.environ.get("SURGEGUARD_SUPERVISOR_EMAIL", "")
PASSWORD = os.environ.get("SURGEGUARD_SUPERVISOR_PASSWORD", "")
TICK = 15
UNHEALTHY_RESTART_S = 45
CAMERA_GRACE_S = 45
CAMERA_RETRY_EVERY_S = 60

LOG_DIR.mkdir(parents=True, exist_ok=True)
_log = (LOG_DIR / "supervisor.log").open("a", encoding="utf-8", buffering=1)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    _log.write(line + "\n")


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_backend() -> subprocess.Popen:
    out = (LOG_DIR / "backend.log").open("a", encoding="utf-8")
    log("starting backend on :8001")
    return subprocess.Popen(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "uvicorn", "app.main:create_app",
         "--factory", "--host", "127.0.0.1", "--port", "8001", "--env-file", ".env"],
        cwd=ROOT / "backend", stdout=out, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def start_frontend() -> subprocess.Popen:
    out = (LOG_DIR / "frontend.log").open("a", encoding="utf-8")
    log("starting frontend dev server on :5180")
    return subprocess.Popen(
        "npm run dev", shell=True, cwd=ROOT / "frontend", stdout=out, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def kill_tree(proc: subprocess.Popen | None) -> None:
    if proc is not None and proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)


def main() -> None:
    STOP_FILE.unlink(missing_ok=True)
    backend_proc: subprocess.Popen | None = None
    frontend_proc: subprocess.Popen | None = None
    unhealthy_since: float | None = None
    last_retry: dict[str, float] = {}
    offline_since: dict[str, float] = {}
    last_summary = ""
    client = httpx.Client(timeout=8)
    signed_in = False
    log("supervisor started")

    try:
        while not STOP_FILE.exists():
            now = time.time()

            # Backend
            if not listening(8001):
                if backend_proc is None or backend_proc.poll() is not None:
                    backend_proc = start_backend()
                    signed_in = False
                    unhealthy_since = None
            else:
                try:
                    healthy = client.get(f"{BACKEND}/health").status_code == 200
                except httpx.HTTPError:
                    healthy = False
                if healthy:
                    unhealthy_since = None
                else:
                    unhealthy_since = unhealthy_since or now
                    if now - unhealthy_since >= UNHEALTHY_RESTART_S:
                        log("backend unresponsive for 45 s; restarting")
                        if backend_proc is not None:
                            kill_tree(backend_proc)
                        else:
                            subprocess.run(
                                ["powershell", "-NoProfile", "-Command",
                                 ("Get-NetTCPConnection -LocalPort 8001 -State Listen | "
                                  "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }")],
                                capture_output=True, check=False,
                            )
                        time.sleep(3)
                        backend_proc = start_backend()
                        signed_in = False
                        unhealthy_since = None

            # Frontend
            if not listening(5180) and (frontend_proc is None or frontend_proc.poll() is not None):
                frontend_proc = start_frontend()

            # Cameras and hardware
            try:
                if not signed_in and EMAIL and PASSWORD:
                    r = client.post(f"{BACKEND}/api/v1/auth/login",
                                    json={"email": EMAIL, "password": PASSWORD})
                    signed_in = r.status_code == 200
                if signed_in:
                    r = client.get(f"{BACKEND}/api/v1/cameras")
                    if r.status_code == 401:
                        signed_in = False
                    else:
                        parts = []
                        for cam in r.json()["data"]["cameras"]:
                            if not cam["enabled"]:
                                continue
                            cid, status = cam["camera_id"], cam["status"]
                            parts.append(f"{cam['name']}={status}")
                            # Tracked here, not from status_since: that resets on every
                            # CONNECTING <-> RECOVERING flap, so it would never reach the grace.
                            if status == "ONLINE":
                                offline_since.pop(cid, None)
                                continue
                            since = offline_since.setdefault(cid, now)
                            if (now - since >= CAMERA_GRACE_S
                                    and now - last_retry.get(cid, 0) >= CAMERA_RETRY_EVERY_S):
                                last_retry[cid] = now
                                rr = client.post(f"{BACKEND}/api/v1/cameras/{cid}/retry")
                                log(f"camera {cam['name']} ({cam['stream_url']}) {status} "
                                    f"for {now - since:.0f}s -> retry {rr.status_code}")
                        hw = client.get(f"{BACKEND}/api/v1/hardware").json()["data"]
                        parts.append(
                            f"arduino={'connected' if hw['connected'] else 'DISCONNECTED'}"
                            f"/{hw['acknowledged']}"
                        )
                        summary = ", ".join(parts)
                        if summary != last_summary:
                            log(summary)
                            last_summary = summary
            except (httpx.HTTPError, KeyError, ValueError) as error:
                log(f"status check failed: {error!r}")
                signed_in = False

            for _ in range(TICK):
                if STOP_FILE.exists():
                    break
                time.sleep(1)
    finally:
        log("stopping: shutting down the backend and any frontend this supervisor started")
        if backend_proc is not None and backend_proc.poll() is None:
            # CTRL_BREAK lets uvicorn run its lifespan shutdown (NO_DATA to the board).
            backend_proc.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                backend_proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                kill_tree(backend_proc)
        elif backend_proc is None and listening(8001):
            # A backend adopted from an earlier run: not our child, so it is force-stopped
            # and the board shows link lost (blinking blue) rather than NO_DATA.
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 ("Get-NetTCPConnection -LocalPort 8001 -State Listen | "
                  "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }")],
                capture_output=True, check=False,
            )
        kill_tree(frontend_proc)
        STOP_FILE.unlink(missing_ok=True)
        log("supervisor stopped")


if __name__ == "__main__":
    sys.exit(main())
