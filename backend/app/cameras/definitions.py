"""What a camera is, as the platform configures it.

A :class:`CameraDefinition` is *configuration*: a name, a place, a stream to read.
It says nothing about whether the camera is working - that is
:mod:`app.cameras.status` - and nothing about what it has seen, which is the
analysis pipeline's concern. Keeping the three apart is what lets an operator
edit a camera's address while it is offline, and lets a camera fail without its
configuration being touched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from surgeguard_ai.contracts import CameraRole

from ..core.config import normalise_camera_id

__all__ = [
    "DROIDCAM_DEFAULT_PATH",
    "DROIDCAM_DEFAULT_PORT",
    "CameraChanges",
    "CameraDefinition",
    "CameraOrigin",
    "CameraSpec",
    "UrlSource",
    "mask_credentials",
    "normalise_stream_url",
]

#: DroidCam's MJPEG endpoint and default port. A phone running DroidCam serves
#: its video at ``http://<phone-ip>:4747/video``; the app shows the IP and port.
DROIDCAM_DEFAULT_PORT = 4747
DROIDCAM_DEFAULT_PATH = "/video"

_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*)://(.*)$")
_SUPPORTED_SCHEMES = frozenset({"http", "https", "rtsp", "rtsps"})
_HOST_ONLY = re.compile(
    r"^(?P<host>[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)"
    r"(?::(?P<port>\d{1,5}))?(?P<path>/\S*)?$"
)


def mask_credentials(url: str | None) -> str | None:
    """Hide a password embedded in a stream address before it is displayed.

    ``rtsp://admin:secret@10.0.0.4/stream`` is shown as
    ``rtsp://admin:***@10.0.0.4/stream``. DroidCam addresses carry no
    credentials and pass through unchanged.
    """
    if not url:
        return url
    match = _SCHEME.match(url)
    if match is None:
        return url
    scheme, remainder = match.group(1), match.group(2)
    authority, slash, rest = remainder.partition("/")
    if "@" not in authority:
        return url
    userinfo, _, host = authority.rpartition("@")
    user = userinfo.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}{slash}{rest}"


def normalise_stream_url(value: str | None) -> str | None:
    """Return a stream address OpenCV can open, or ``None`` for no address.

    Accepts what an operator is likely to have in front of them:

    - a device index (``0``) for a camera attached to this machine;
    - a full ``http``/``https``/``rtsp`` URL, used as given;
    - a bare ``host`` or ``host:port`` as DroidCam displays it, completed to
      ``http://host:4747/video``. A convenience, stated here rather than hidden:
      a bare address is assumed to be a DroidCam phone, because that is the
      camera this platform is deployed with.

    Raises:
        ValueError: The value is not a usable stream address.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None

    if candidate.isdigit():
        return candidate

    scheme_match = _SCHEME.match(candidate)
    if scheme_match is not None:
        scheme, remainder = scheme_match.group(1).lower(), scheme_match.group(2)
        if scheme not in _SUPPORTED_SCHEMES:
            raise ValueError(
                f"{value!r} is not a supported stream address: use http, https, "
                "rtsp or rtsps, or a device index"
            )
        if not remainder or remainder.startswith("/"):
            raise ValueError(f"{value!r} is not a usable stream address: it has no host")
        return candidate

    host_match = _HOST_ONLY.fullmatch(candidate)
    if host_match is None:
        raise ValueError(
            f"{value!r} is not a usable stream address: expected a URL such as "
            "http://192.168.1.20:4747/video, or a DroidCam IP and port"
        )
    port = host_match.group("port") or str(DROIDCAM_DEFAULT_PORT)
    path = host_match.group("path") or DROIDCAM_DEFAULT_PATH
    return f"http://{host_match.group('host')}:{port}{path}"


class UrlSource(StrEnum):
    """Where a camera's effective stream address comes from.

    Shown beside the address in the interface, so an operator who edits
    ``.env`` and sees no change can tell that a saved edit is taking precedence.
    """

    ENVIRONMENT = "ENVIRONMENT"
    """Declared in ``.env``."""

    REGISTRY = "REGISTRY"
    """Saved by an operator from the Command Center."""

    UNSET = "UNSET"
    """No address is configured - the camera cannot connect until one is."""


class CameraOrigin(StrEnum):
    """How a camera came to exist."""

    ENVIRONMENT = "ENVIRONMENT"
    """Declared in ``.env``. Edits are saved as overrides; removal is remembered."""

    OPERATOR = "OPERATOR"
    """Added from the Command Center. Held entirely in the registry."""


@dataclass(frozen=True, slots=True)
class CameraDefinition:
    """One camera's resolved configuration - environment and edits combined."""

    camera_id: str
    name: str
    location: str
    role: CameraRole
    stream_url: str | None
    url_source: UrlSource
    demo_video_path: Path | None
    enabled: bool
    coverage_area: str
    origin: CameraOrigin
    is_primary: bool
    order: int

    @property
    def display_id(self) -> str:
        """The identifier as an operator reads it: ``cam-02`` becomes ``CAM-02``."""
        return self.camera_id.upper()


_NAME_FIELD = Field(min_length=1, max_length=60)
_LOCATION_FIELD = Field(default="", max_length=80)
_AREA_FIELD = Field(default=None, max_length=60)


class CameraSpec(BaseModel):
    """A camera an operator is adding."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    camera_id: str | None = Field(
        default=None,
        description="Omit to have the next free id (cam-NN) assigned.",
    )
    name: str = _NAME_FIELD
    location: str = _LOCATION_FIELD
    role: CameraRole = CameraRole.GENERAL
    stream_url: str | None = None
    demo_video_path: Path | None = None
    enabled: bool = True
    coverage_area: str | None = _AREA_FIELD

    @field_validator("camera_id")
    @classmethod
    def _normalise_id(cls, value: str | None) -> str | None:
        return normalise_camera_id(value) if value else None

    @field_validator("stream_url")
    @classmethod
    def _normalise_url(cls, value: str | None) -> str | None:
        return normalise_stream_url(value)

    @field_validator("coverage_area")
    @classmethod
    def _blank_area_is_none(cls, value: str | None) -> str | None:
        return value or None


class CameraChanges(BaseModel):
    """An operator's edit to an existing camera.

    Only fields actually supplied are applied - an absent field is "leave as
    is", which is different from a field explicitly set to ``None``. For a
    camera declared in the environment, ``stream_url=None`` returns it to the
    environment's address rather than removing its address.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=60)
    location: str | None = Field(default=None, max_length=80)
    role: CameraRole | None = None
    stream_url: str | None = None
    demo_video_path: Path | None = None
    enabled: bool | None = None
    coverage_area: str | None = Field(default=None, max_length=60)

    @field_validator("stream_url")
    @classmethod
    def _normalise_url(cls, value: str | None) -> str | None:
        return normalise_stream_url(value)

    @field_validator("coverage_area")
    @classmethod
    def _blank_area_is_none(cls, value: str | None) -> str | None:
        return value or None

    def supplied(self) -> dict[str, object]:
        """The fields this edit actually sets, including those set to ``None``."""
        return {name: getattr(self, name) for name in self.model_fields_set}
