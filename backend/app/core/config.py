"""Application configuration.

Every deployment-varying value is read from the environment (or a ``.env`` file)
exactly once, at import of :func:`get_settings`. Nothing in the application
reads ``os.environ`` directly - configuration has a single entry point so that
what a running instance is actually configured with is always answerable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from surgeguard_ai.contracts import CameraRole, SourceMode
from surgeguard_ai.stability import NormalizationCurve

from .constants import DEFAULT_CAMERA_ID

__all__ = [
    "CameraSeed",
    "Environment",
    "LogFormat",
    "Settings",
    "get_settings",
    "normalise_camera_id",
]

#: Repository root, derived from this file's location:
#: backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> root
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

#: A camera identifier names a zone file, a URL segment and a database column, so
#: it is held to a slug: lowercase letters, digits, hyphens and underscores.
_CAMERA_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def normalise_camera_id(value: str) -> str:
    """Return the canonical form of a camera identifier.

    Case-insensitive on input - an operator typing ``CAM-02`` means ``cam-02`` -
    and strict about everything else, because an identifier with a space or a
    slash in it would break the file name and the URL it ends up in.

    Raises:
        ValueError: The value cannot be used as a camera id.
    """
    candidate = value.strip().lower()
    if not _CAMERA_ID_PATTERN.fullmatch(candidate):
        raise ValueError(
            f"{value!r} is not a usable camera id: use 1-32 lowercase letters, "
            "digits, hyphens or underscores, starting with a letter or digit"
        )
    return candidate


class CameraSeed(BaseModel):
    """A camera declared in the environment.

    Seeds are the *starting* camera set. An operator who edits a camera in the
    Command Center has that edit saved to the camera registry, which from then
    on takes precedence for the fields they changed - so a phone whose address
    changed can be followed from the interface as well as from ``.env``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    index: int = Field(
        ge=1,
        description="Position in the environment: 1 is the primary camera.",
    )
    camera_id: str
    name: str
    location: str = ""
    url: str | None = Field(
        default=None,
        description="Device index or stream URL. A DroidCam phone is http://<ip>:4747/video.",
    )
    enabled: bool = True
    role: CameraRole = CameraRole.GENERAL
    coverage_area: str | None = Field(
        default=None,
        description=(
            "Physical area this camera watches. Cameras sharing an area are "
            "treated as overlapping and never simply added together."
        ),
    )
    demo_video_path: Path | None = None

    @model_validator(mode="before")
    @classmethod
    def _derive_identity(cls, data: Any) -> Any:
        """Fill an omitted id and name from the index.

        The shortest useful declaration is then one line -
        ``SURGEGUARD_CAMERA_2_URL=...`` - rather than three.
        """
        if not isinstance(data, dict) or "index" not in data:
            return data
        try:
            index = int(data["index"])
        except (TypeError, ValueError):
            return data
        data = dict(data)
        if not data.get("camera_id"):
            data["camera_id"] = f"cam-{index:02d}"
        if not data.get("name"):
            data["name"] = f"Camera {index:02d}"
        if data.get("url") == "":
            data["url"] = None
        return data

    @field_validator("camera_id")
    @classmethod
    def _normalise_id(cls, value: str) -> str:
        return normalise_camera_id(value)


#: Environment variable fields accepted for an indexed camera, mapped to the
#: :class:`CameraSeed` attribute each one sets.
_INDEXED_CAMERA_FIELDS: dict[str, str] = {
    "id": "camera_id",
    "name": "name",
    "location": "location",
    "url": "url",
    "enabled": "enabled",
    "role": "role",
    "coverage_area": "coverage_area",
    "demo_video_path": "demo_video_path",
}


class _IndexedCameraSettingsSource(PydanticBaseSettingsSource):
    """Collects ``SURGEGUARD_CAMERA_<N>_<FIELD>`` variables into camera seeds.

    A settings model cannot declare a field per possible camera, so this reads
    the same two places the standard sources read - the process environment and
    the ``.env`` file, with the environment winning - and assembles
    :attr:`Settings.additional_cameras` from whatever indices are present.

    An unrecognised field name is passed through rather than dropped, so that
    :class:`CameraSeed`'s ``extra="forbid"`` rejects a typo at startup instead
    of leaving a camera silently unconfigured.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
    ) -> None:
        super().__init__(settings_cls)
        self._env_settings = env_settings
        self._dotenv_settings = dotenv_settings
        prefix = str(settings_cls.model_config.get("env_prefix", "")).lower()
        self._pattern = re.compile(rf"^{re.escape(prefix)}camera_(\d+)_([a-z_]+)$")

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:  # pragma: no cover - __call__ is overridden
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        variables: dict[str, str | None] = {}
        # Later updates win: the .env file first, the process environment over it.
        for source in (self._dotenv_settings, self._env_settings):
            variables.update(_variables_of(source))

        by_index: dict[int, dict[str, Any]] = {}
        for key, value in variables.items():
            match = self._pattern.fullmatch(key.lower())
            if match is None or value is None:
                continue
            index = int(match.group(1))
            field = match.group(2)
            entry = by_index.setdefault(index, {"index": index})
            entry[_INDEXED_CAMERA_FIELDS.get(field, field)] = value

        if not by_index:
            return {}
        return {"additional_cameras": [by_index[index] for index in sorted(by_index)]}


def _variables_of(source: PydanticBaseSettingsSource) -> Mapping[str, str | None]:
    """The raw variables a standard environment source has loaded."""
    loaded = getattr(source, "env_vars", None)
    return loaded if isinstance(loaded, Mapping) else {}


class Environment(StrEnum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    DEMONSTRATION = "demonstration"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    """Log output format."""

    CONSOLE = "console"
    JSON = "json"


class Settings(BaseSettings):
    """Runtime configuration, populated from the environment.

    Field names map to ``SURGEGUARD_``-prefixed environment variables, so
    ``SURGEGUARD_LOG_LEVEL=DEBUG`` sets :attr:`log_level`.
    """

    model_config = SettingsConfigDict(
        env_prefix="SURGEGUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Add the indexed camera source after the standard ones.

        Earlier sources take precedence, so explicit constructor arguments still
        win - which is how tests supply a camera set without an environment.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _IndexedCameraSettingsSource(settings_cls, env_settings, dotenv_settings),
            file_secret_settings,
        )

    # -- Application --------------------------------------------------------

    app_name: str = "SurgeGuard"
    app_version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False

    # -- Server -------------------------------------------------------------

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    cors_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("http://localhost:5173", "http://127.0.0.1:5173"),
        description=(
            "Origins permitted to call the API. The Vite dev server by default. "
            "Comma-separated when set from the environment or a .env file."
        ),
    )

    # -- Database -----------------------------------------------------------

    database_url: str = Field(
        default="sqlite+aiosqlite:///./surgeguard.db",
        description=(
            "SQLAlchemy async URL. SQLite for the prototype; the async driver "
            "keeps persistence off the event loop's critical path. Access is "
            "through SQLAlchemy throughout, so a move to PostgreSQL is a URL "
            "change plus a migration run."
        ),
    )
    database_echo: bool = Field(
        default=False,
        description="Log every SQL statement. Diagnostic use only - very noisy.",
    )

    # -- Logging ------------------------------------------------------------

    log_level: str = Field(default="INFO")
    log_format: LogFormat = LogFormat.CONSOLE

    # -- Real-time ----------------------------------------------------------

    ws_heartbeat_seconds: float = Field(
        default=15.0,
        gt=0,
        description="Server-side ping interval, so a dead connection is detected.",
    )

    # -- AI Pipeline --------------------------------------------------------

    analysis_fps: float = Field(
        default=10.0,
        gt=0,
        description=(
            "Target analysis rate. Decoupled from the video display rate: video "
            "streams at source rate while analysis runs at this rate."
        ),
    )
    detection_width: int = Field(default=960, gt=0)
    detection_height: int = Field(default=540, gt=0)
    detection_device: str = Field(
        default="cuda",
        description=(
            "Torch device for inference: 'auto', 'cpu', 'cuda' or 'cuda:N'. An "
            "unavailable device falls back to CPU with the reason recorded, "
            "rather than refusing to start."
        ),
    )
    detection_confidence_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    detection_model: str = Field(
        default="yolo11s.pt",
        description="Checkpoint name or path. Downloaded on first use if absent.",
    )
    detection_image_size: int = Field(
        default=960,
        gt=0,
        description="Inference resolution in pixels. Must be a multiple of 32.",
    )

    # -- Perception pipeline ------------------------------------------------

    pipeline_enabled: bool = Field(
        default=True,
        description=(
            "Whether the perception pipeline starts with the backend. Disabled "
            "in tests and wherever the API is wanted without a camera or GPU."
        ),
    )
    pipeline_source_mode: SourceMode = Field(
        default=SourceMode.LIVE,
        description=(
            "Which frame source the pipeline runs on. LIVE reads the configured "
            "camera; DEMO replays `demo_video_path`. This is the only setting "
            "that differs between the two modes - the pipeline itself is "
            "identical in both."
        ),
    )
    pipeline_restart_delay_seconds: float = Field(
        default=2.0,
        gt=0,
        description="Delay before the first recovery attempt after a failure.",
    )
    pipeline_max_restart_delay_seconds: float = Field(
        default=30.0,
        gt=0,
        description=(
            "Ceiling for the doubling recovery backoff, so an absent camera is "
            "not probed in a tight loop for as long as the platform runs."
        ),
    )
    pipeline_max_restart_attempts: int = Field(
        default=0,
        ge=0,
        description=(
            "Consecutive recovery attempts before the worker gives up. Zero "
            "means never give up, which is what a control room wants: a camera "
            "unplugged for an hour should still recover when it returns."
        ),
    )

    # -- Crowd Stability Index ----------------------------------------------
    #
    # 16:142-168 requires weights to be configurable per deployment and not
    # hardcoded. The AI package holds the full tuning surface (curves,
    # ceilings, confidence thresholds); exposed here are the values a
    # deployment actually varies. Defaults are the specification frozen in
    # 02_Hackathon_Execution_Plan.md section 4 and must sum to 1.

    csi_enabled: bool = Field(
        default=True,
        description=(
            "Whether crowd analysis, the Crowd Stability Index and the Evidence "
            "Engine run. Disabled independently of the perception pipeline so "
            "detections can be observed without an assessment layered on them."
        ),
    )

    csi_weight_density: float = Field(default=0.35, ge=0.0, le=1.0)
    csi_weight_motion: float = Field(default=0.20, ge=0.0, le=1.0)
    csi_weight_egress: float = Field(default=0.20, ge=0.0, le=1.0)
    csi_weight_flow: float = Field(default=0.15, ge=0.0, le=1.0)
    csi_weight_rate: float = Field(default=0.10, ge=0.0, le=1.0)

    csi_smoothing_seconds: float = Field(
        default=10.0,
        gt=0,
        description="Time constant of the moving average applied to the raw index.",
    )
    csi_escalate_windows: int = Field(
        default=3,
        ge=1,
        description="Consecutive windows a more severe band must hold before it is adopted.",
    )
    csi_de_escalate_windows: int = Field(
        default=5,
        ge=1,
        description=(
            "Consecutive windows a less severe band must hold. Higher than the "
            "escalation count on purpose: quicker to warn than to reassure."
        ),
    )

    # Uncalibrated density is people per grid cell - a relative scale the AI
    # package documents as a per-deployment heuristic to be tuned against the
    # actual view. A camera close to the crowd (a phone a few metres away)
    # spreads each person over several cells of the default grid, so its
    # busiest cell rarely holds two and density never registers; a coarser grid
    # and a steeper curve fit that view. Calibrated (p/m2) density is unaffected.
    crowd_grid_rows: int = Field(
        default=6,
        ge=1,
        le=36,
        description="Rows in the density grid laid over each analysed frame.",
    )
    crowd_grid_cols: int = Field(
        default=8,
        ge=1,
        le=64,
        description="Columns in the density grid. Keep cells roughly square for a 16:9 view.",
    )
    csi_relative_density_knots: Annotated[tuple[tuple[float, float], ...], NoDecode] = Field(
        default=((1.0, 0.0), (3.0, 50.0), (4.5, 80.0), (6.0, 100.0)),
        description=(
            "Density pressure for an uncalibrated camera, as `people:pressure` "
            "knots ordered by people per cell - e.g. `1:0,3:50,4.5:80,6:100`. "
            "Linear between knots, held flat outside them."
        ),
    )
    csi_rate_ceiling_relative: float = Field(
        default=0.05,
        gt=0,
        description=(
            "Rise in uncalibrated peak density, people per cell per second, at "
            "which the rate-of-change indicator reaches full pressure."
        ),
    )

    # -- Evidence Engine ----------------------------------------------------

    evidence_max_items: int = Field(
        default=5,
        ge=1,
        description=(
            "Observations shown at once. The platform surfaces what needs "
            "attention rather than everything it can see (03:60-62)."
        ),
    )
    evidence_min_confidence: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Observations below this confidence are suppressed and counted.",
    )
    evidence_history_limit: int = Field(
        default=50,
        ge=1,
        description="Observations retained for the Evidence History.",
    )

    # -- Operational Decision Engine ----------------------------------------
    #
    # 18:99-109 requires the engine to be configurable alongside transparent,
    # explainable, deterministic and auditable. The AI package holds the full
    # rule-threshold surface; exposed here is the policy a deployment varies.

    ode_enabled: bool = Field(
        default=True,
        description=(
            "Whether the Operational Decision Engine runs. Disabled "
            "independently of the assessment: a venue may want the index and "
            "the evidence while its own team decides operational policy."
        ),
    )
    ode_max_actions: int = Field(
        default=4,
        ge=1,
        le=10,
        description=(
            "Most recommendations shown at once. Beyond about four a "
            "prioritised list stops being prioritised (03:60-62)."
        ),
    )
    ode_min_action_confidence: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Recommendations below this confidence are dropped and counted.",
    )
    ode_report_min_interval_seconds: float = Field(
        default=20.0,
        ge=0.0,
        description=(
            "Floor between reports when nothing material has changed. A status "
            "or priority change always bypasses it."
        ),
    )
    decision_history_limit: int = Field(
        default=50,
        ge=1,
        description=(
            "Reports retained by the backend. Bounded because a control-room "
            "process runs for a shift, and an unbounded list is a slow leak "
            "(Architecture Review R14)."
        ),
    )

    # -- Queue Intelligence -------------------------------------------------
    #
    # Measures service queues alongside the Crowd Stability Index rather than
    # instead of it. Disabled independently: a camera watching an open
    # concourse has no queue, and should not be made to report one.

    queue_enabled: bool = Field(
        default=True,
        description=(
            "Whether Queue Intelligence, forecasting and resource allocation "
            "run. Requires at least one QUEUE zone to produce anything; with "
            "none configured it reports itself unconfigured rather than "
            "reporting an empty queue, which would look like a measurement."
        ),
    )
    queue_min_track_age_frames: int = Field(
        default=5,
        ge=1,
        description=(
            "Tracks younger than this are excluded from queue geometry. A "
            "one-frame-old track has no velocity and may be detector flicker; "
            "letting it vote would make noise drive the queue/crowd decision."
        ),
    )
    queue_sparse_threshold: int = Field(
        default=3,
        ge=1,
        description=(
            "At or below this many people no formation is claimed. Three people "
            "standing near each other are always collinear."
        ),
    )
    queue_flow_window_seconds: float = Field(
        default=180.0,
        gt=0,
        description="Rolling window arrivals and departures are counted over.",
    )

    # -- Forecasting --------------------------------------------------------

    forecast_horizons_minutes: str = Field(
        default="5,10,15",
        description=(
            "Comma-separated forecast horizons in minutes. Problem Statement 9 "
            "asks for +5, +10 and +15."
        ),
    )
    forecast_sample_interval_seconds: float = Field(
        default=10.0,
        gt=0,
        description=(
            "Resampling cadence for the forecast series. Frames arrive at "
            "whatever rate the GPU manages; resampling is what stops the trend "
            "depending on frame rate."
        ),
    )
    forecast_alpha: float = Field(
        default=0.3, gt=0.0, le=1.0, description="Holt level smoothing."
    )
    forecast_beta: float = Field(
        default=0.1,
        gt=0.0,
        le=1.0,
        description=(
            "Holt trend smoothing. Below the level constant on purpose - an "
            "over-responsive trend extrapolates a two-person fluctuation into a "
            "crisis."
        ),
    )
    growth_z_threshold: float = Field(
        default=2.5,
        gt=0.0,
        description=(
            "Standard deviations above a queue's own baseline growth rate that "
            "count as abnormal. Keyed to rate, never to size."
        ),
    )
    growth_min_rate_per_min: float = Field(
        default=1.0,
        ge=0.0,
        description=(
            "Absolute growth floor for an abnormal verdict. Without it a "
            "perfectly flat baseline turns one person joining into a crisis."
        ),
    )

    # -- Resource allocation ------------------------------------------------

    allocation_target_wait_minutes: float = Field(
        default=10.0,
        gt=0,
        description=(
            "The wait the venue is trying to stay within. The single most "
            "deployment-specific number here - an outpatient clinic and a "
            "stadium turnstile do not share it."
        ),
    )
    allocation_horizon_minutes: int = Field(
        default=10,
        gt=0,
        description=(
            "How far ahead staffing decisions are made. Long enough that "
            "opening a counter has time to matter."
        ),
    )
    default_total_counters: int = Field(
        default=4,
        ge=0,
        description="Counters a queue zone has, until an operator says otherwise.",
    )
    default_active_counters: int = Field(
        default=2,
        ge=0,
        description="Counters open at startup, until an operator says otherwise.",
    )
    default_service_rate_per_min: float = Field(
        default=2.0,
        gt=0,
        description=(
            "Per-counter service rate assumed until enough departures have been "
            "observed to measure one. An assumption, labelled as one wherever it "
            "reaches the interface."
        ),
    )

    @property
    def forecast_horizons(self) -> tuple[int, ...]:
        """Parsed, validated forecast horizons in ascending order."""
        try:
            horizons = tuple(
                int(part.strip())
                for part in self.forecast_horizons_minutes.split(",")
                if part.strip()
            )
        except ValueError as error:
            raise ValueError(
                f"SURGEGUARD_FORECAST_HORIZONS_MINUTES must be a comma-separated "
                f"list of whole minutes, got "
                f"{self.forecast_horizons_minutes!r}"
            ) from error

        if not horizons:
            raise ValueError("At least one forecast horizon must be configured")
        if any(h <= 0 for h in horizons):
            raise ValueError("Forecast horizons must be positive")

        return tuple(sorted(horizons))

    # -- Timeline and realtime ----------------------------------------------

    timeline_limit: int = Field(
        default=200,
        ge=1,
        description=(
            "Timeline entries retained in memory. Bounded because an unbounded "
            "log on a long-running control-room display is a leak with a "
            "deadline (Architecture Review R14)."
        ),
    )
    stream_jpeg_quality: int = Field(
        default=75,
        ge=1,
        le=100,
        description=(
            "JPEG quality for the live video stream. 75 is visually clean at "
            "control-room size while keeping encoding off the critical path - "
            "it runs on the AI Pipeline thread, where time costs frames."
        ),
    )
    stream_target_fps: float = Field(
        default=15.0,
        gt=0,
        description=(
            "Ceiling on how often a viewer is served a frame. Independent of "
            "the analysis rate: the pipeline may run faster, and there is no "
            "value in sending frames a display cannot show."
        ),
    )

    ws_assessment_min_interval_seconds: float = Field(
        default=0.5,
        ge=0.0,
        description=(
            "Floor between pushed assessment updates. A window carrying a "
            "status change is always sent immediately - delaying a band "
            "transition to save a frame is the wrong trade for a safety display."
        ),
    )

    tracker_lost_track_timeout_seconds: float = Field(
        default=1.0,
        gt=0,
        description=(
            "How long a person may be hidden before their tracking identity is "
            "released. Expressed in seconds because the operational meaning does "
            "not change with frame rate."
        ),
    )

    # -- Camera / source ----------------------------------------------------

    camera_id: str = Field(default=DEFAULT_CAMERA_ID)
    camera_name: str = Field(default="Camera 01")
    camera_location: str = Field(
        default="Platform 3",
        description="Operator-facing location, shown wherever this camera is named.",
    )

    live_camera_device: str = Field(
        default="0",
        description=(
            "Device index or RTSP/HTTP URL for Live Camera Mode. Kept as a "
            "string so a numeric index and a URL share one setting."
        ),
    )
    live_camera_fallback_fps: float = Field(default=30.0, gt=0)
    live_camera_open_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        le=60.0,
        description="How long opening a network camera stream may take before it counts as failed.",
    )
    live_camera_read_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        le=60.0,
        description=(
            "How long a network camera may go without delivering a frame before "
            "a read is abandoned. Without it, a phone that leaves the network "
            "leaves the pipeline blocked in a read while still reporting itself "
            "running."
        ),
    )
    live_camera_stall_seconds: float = Field(
        default=6.0,
        gt=0,
        le=120.0,
        description=(
            "Failed reads for this long declare a network camera lost and start reconnection."
        ),
    )

    demo_video_path: Path | None = Field(
        default=None,
        description=(
            "Clip replayed in Demonstration Mode. Processed by the complete "
            "pipeline exactly as a live feed - nothing is scripted (Rule 7)."
        ),
    )
    demo_video_loop: bool = Field(
        default=False,
        description=(
            "Restart the clip on reaching its end. Off by default so that a "
            "finished clip is reported as finished rather than silently "
            "replayed; a wrap restarts the frame sequence, which the pipeline "
            "treats as a continuity break and resets tracking for."
        ),
    )

    # -- Multi-camera -------------------------------------------------------
    #
    # The camera above is the *primary* camera: it keeps backing every
    # single-camera route the platform has always served. Further cameras are
    # declared with indexed variables (SURGEGUARD_CAMERA_2_URL, ...) and managed
    # at runtime through the camera registry. No camera is special-cased in
    # code; the primary one is simply the camera the older routes describe.

    additional_cameras: tuple[CameraSeed, ...] = Field(
        default=(),
        description=(
            "Cameras 2..N, assembled from SURGEGUARD_CAMERA_<N>_<FIELD> variables "
            "(ID, NAME, LOCATION, URL, ENABLED, ROLE, COVERAGE_AREA, "
            "DEMO_VIDEO_PATH)."
        ),
    )
    camera_role: CameraRole = Field(
        default=CameraRole.GENERAL,
        description="Operational role of the primary camera.",
    )
    camera_coverage_area: str | None = Field(
        default=None,
        description=(
            "Physical area the primary camera watches. Cameras sharing an area "
            "are treated as overlapping. Unset means an area of its own."
        ),
    )
    camera_registry_path: Path = Field(
        default=PROJECT_ROOT / "data" / "cameras.json",
        description=(
            "Operator edits to the camera set - added cameras, changed stream "
            "URLs, disabled cameras. Written only when an operator changes "
            "something; the environment seeds everything else. Holds "
            "deployment-specific network addresses, so it is not committed."
        ),
    )
    topology_path: Path = Field(
        default=PROJECT_ROOT / "data" / "topology.json",
        description=(
            "How camera zones connect - entrance feeds waiting area feeds queue. "
            "Venue configuration, so it lives beside the zone definitions."
        ),
    )
    camera_health_probe_interval_seconds: float = Field(
        default=10.0,
        gt=0,
        description=(
            "How often a network camera's device endpoint is asked for its "
            "round-trip time and battery level. These requests are separate "
            "from the video stream and never compete with it."
        ),
    )
    camera_connection_test_seconds: float = Field(
        default=3.0,
        gt=0,
        le=15.0,
        description=(
            "How long an operator-requested connection test reads frames for. "
            "Long enough to measure a frame rate, short enough to wait for."
        ),
    )

    # -- Site intelligence --------------------------------------------------

    site_update_interval_seconds: float = Field(
        default=1.0,
        gt=0,
        description="How often per-camera measurements are combined into site figures.",
    )
    site_max_observation_age_seconds: float = Field(
        default=10.0,
        gt=0,
        description=(
            "Oldest per-camera analysis that may still enter a site figure. A "
            "camera silent for longer is excluded and the site view says so - "
            "its last reading is never carried forward as though current."
        ),
    )

    # -- Historical persistence ---------------------------------------------

    history_enabled: bool = Field(
        default=True,
        description=(
            "Whether aggregated observations are written to the database. "
            "Buckets of measurements, never individual frames or images."
        ),
    )
    history_bucket_seconds: int = Field(
        default=30,
        ge=5,
        le=3600,
        description="Length of one stored observation bucket.",
    )
    history_retention_days: int = Field(
        default=30,
        ge=1,
        description="Observations older than this are pruned.",
    )
    history_baseline_min_samples: int = Field(
        default=20,
        ge=1,
        description=(
            "Stored buckets required before a historical comparison is shown. "
            "Below this the comparison is withheld rather than drawn from a "
            "handful of samples."
        ),
    )

    # -- Alert hardware -----------------------------------------------------
    #
    # An Arduino with an RGB LED and a buzzer, on USB serial, showing the most
    # urgent priority any camera's Decision Engine currently reports. Firmware:
    # hardware/arduino/surgeguard_alert/surgeguard_alert.ino.

    hardware_enabled: bool = Field(
        default=False,
        description="Drive the alert hardware. Off unless a board is attached.",
    )
    hardware_serial_port: str = Field(
        default="auto",
        min_length=1,
        description=(
            "Serial port of the alert hardware (e.g. COM8, /dev/ttyACM0), or `auto` "
            "to use the first connected Arduino."
        ),
    )
    hardware_baud_rate: int = Field(default=115200, gt=0)
    hardware_keepalive_seconds: float = Field(
        default=3.0,
        gt=0,
        lt=10,
        description=(
            "Resend the current command this often. Must stay under the firmware's "
            "10 s link timeout, after which the LED blinks blue."
        ),
    )
    hardware_reconnect_seconds: float = Field(
        default=5.0,
        gt=0,
        description="Wait this long before reopening a port that failed or was unplugged.",
    )

    # -- Authentication -----------------------------------------------------
    #
    # Operators sign in before the Command Center opens. Role-based access was
    # always part of the production architecture (see constants.py); what the
    # prototype lacked was an operator identity to hang it on, and with it any
    # way to attribute an action on the timeline to the person who took it.

    auth_enabled: bool = Field(
        default=True,
        description=(
            "Whether every API route, video stream and the Command Center socket "
            "require a signed-in operator. Disable only on an isolated demonstration "
            "machine: the platform then opens directly, as the prototype did."
        ),
    )
    session_ttl_hours: float = Field(
        default=12.0,
        gt=0,
        le=24 * 30,
        description="How long a sign-in lasts. A control-room shift by default.",
    )
    session_cookie_name: str = Field(
        default="surgeguard_session",
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
    )
    session_cookie_secure: bool | None = Field(
        default=None,
        description=(
            "Send the session cookie over HTTPS only. Unset means on in production "
            "and off elsewhere, where the platform is usually reached over plain "
            "HTTP on a local network."
        ),
    )
    login_max_failures: int = Field(
        default=5,
        ge=1,
        description="Failed sign-ins allowed for one address and email before a lockout.",
    )
    login_lockout_seconds: float = Field(
        default=300.0,
        gt=0,
        description="How long those failures are remembered, and so how long a lockout lasts.",
    )
    auth_password_iterations: int = Field(
        default=600_000,
        ge=1_000,
        description=(
            "PBKDF2-SHA256 iterations for new password hashes - OWASP's recommendation "
            "by default. Lower only in test suites, where hashing speed matters and "
            "the accounts protect nothing."
        ),
    )

    # -- Database schema -------------------------------------------------------

    database_auto_migrate: bool = Field(
        default=True,
        description=(
            "Bring the database schema up to date at startup. On by default so a "
            "fresh deployment works without a separate `alembic upgrade head`."
        ),
    )

    # -- Web application ---------------------------------------------------------

    frontend_dist_dir: Path = Field(
        default=PROJECT_ROOT / "frontend" / "dist",
        description=(
            "The built Command Center. Served from the same origin as the API when "
            "present, so a production deployment is one process; ignored when absent."
        ),
    )

    # -- Paths --------------------------------------------------------------

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    scenario_manifest: Path = Field(
        default=PROJECT_ROOT / "data" / "scenarios" / "manifest.yaml",
        description=(
            "Demonstration scenarios are declared in a manifest, not in code, so "
            "that adding footage is a file change rather than a code change."
        ),
    )
    snapshot_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "snapshots",
        description=(
            "Crowd Event keyframes. Contains imagery of members of the public: "
            "excluded from version control and subject to a retention window."
        ),
    )
    zones_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "zones",
        description=(
            "Operator-drawn camera zones, one JSON file per camera. "
            "Configuration rather than observation - a statement about the "
            "venue, not a record of something that happened - so it lives on "
            "disk beside the other configuration rather than in the "
            "time-series tables."
        ),
    )

    # -- Validators ---------------------------------------------------------

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        valid = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        upper = value.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {sorted(valid)}, got {value!r}")
        return upper

    @model_validator(mode="after")
    def _validate_csi_weights(self) -> Settings:
        """The five Crowd Stability Index weights must sum to 1.

        Checked here rather than only in the AI package so a misconfigured
        deployment fails at startup with a clear message, instead of on the
        first frame with a stack trace from inside the assessor.
        """
        total = (
            self.csi_weight_density
            + self.csi_weight_motion
            + self.csi_weight_egress
            + self.csi_weight_flow
            + self.csi_weight_rate
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Crowd Stability Index weights must sum to 1.0, got {total:.4f}. "
                "Set SURGEGUARD_CSI_WEIGHT_* so the five values total one."
            )
        return self

    @field_validator("camera_id")
    @classmethod
    def _normalise_primary_camera_id(cls, value: str) -> str:
        """Hold the primary camera to the same identifier rules as every other.

        Normalised here rather than only in the camera seed, so the id the
        older single-camera services are built with is the very string the
        camera manager uses - two spellings of one camera would split its data.
        """
        return normalise_camera_id(value)

    @model_validator(mode="after")
    def _validate_camera_seeds(self) -> Settings:
        """Camera ids must be unique, and index 1 belongs to the primary camera."""
        owners: dict[str, int] = {self.camera_id: 1}
        for seed in self.additional_cameras:
            if seed.index == 1:
                raise ValueError(
                    "SURGEGUARD_CAMERA_1_* variables are not used: camera 1 is the "
                    "primary camera, configured by SURGEGUARD_CAMERA_ID, "
                    "SURGEGUARD_CAMERA_NAME, SURGEGUARD_CAMERA_LOCATION and "
                    "SURGEGUARD_LIVE_CAMERA_DEVICE."
                )
            if seed.camera_id in owners:
                raise ValueError(
                    f"Camera id {seed.camera_id!r} is declared by camera "
                    f"{owners[seed.camera_id]} and camera {seed.index}. Every camera "
                    "needs its own id - zones, history and streams are keyed by it."
                )
            owners[seed.camera_id] = seed.index
        return self

    @field_validator("csi_relative_density_knots", mode="before")
    @classmethod
    def _parse_density_knots(cls, value: object) -> object:
        """Accept `people:pressure` pairs, and refuse a curve the engine would reject.

        Checked here, at startup, by building the same curve the engine uses: a
        malformed curve should stop the service with a named setting rather than
        fail inside the first analysis window.
        """
        if isinstance(value, str):
            pairs: list[tuple[float, float]] = []
            for part in value.split(","):
                if not part.strip():
                    continue
                people, separator, pressure = part.partition(":")
                if not separator:
                    raise ValueError(
                        f"Density knot {part.strip()!r} must be written people:pressure"
                    )
                pairs.append((float(people), float(pressure)))
            value = tuple(pairs)
        if isinstance(value, (tuple, list)):
            knots = tuple((float(people), float(pressure)) for people, pressure in value)
            NormalizationCurve(knots=knots)  # raises ValueError with the reason
            return knots
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated string, since env vars cannot hold a list.

        The field is annotated :class:`NoDecode` so that this validator is what
        parses it. Without that, pydantic-settings sees a complex type and tries
        to JSON-decode the raw value *before* any validator runs - which works
        for a shell environment variable but raises ``SettingsError`` for the
        same value in a ``.env`` file, because ``a,b`` is not valid JSON. The
        two sources must not disagree about what a setting means.
        """
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        return value

    # -- Derived ------------------------------------------------------------

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def cookie_secure(self) -> bool:
        """Whether the session cookie carries the ``Secure`` attribute."""
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.is_production

    @property
    def analysis_interval_seconds(self) -> float:
        """Seconds between analysis windows."""
        return 1.0 / self.analysis_fps

    @property
    def detection_size(self) -> tuple[int, int]:
        """Detector input size as ``(width, height)``."""
        return (self.detection_width, self.detection_height)

    @property
    def primary_camera_seed(self) -> CameraSeed:
        """The primary camera, described by the long-standing camera settings."""
        return CameraSeed(
            index=1,
            camera_id=self.camera_id,
            name=self.camera_name,
            location=self.camera_location,
            url=self.live_camera_device,
            role=self.camera_role,
            coverage_area=self.camera_coverage_area,
            demo_video_path=self.demo_video_path,
        )

    @property
    def camera_seeds(self) -> tuple[CameraSeed, ...]:
        """Every camera the environment declares, primary first."""
        return (self.primary_camera_seed, *self.additional_cameras)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the application settings.

    Cached so that configuration is read once per process and every caller sees
    the same instance. Also the FastAPI dependency for settings injection.
    """
    return Settings()
