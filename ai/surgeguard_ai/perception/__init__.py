"""Perception - Stages 1 to 3 of the AI Pipeline.

Frame acquisition, person detection, person tracking (``05:281-381``).

:class:`FrameSource` is the boundary that makes Live Camera Mode and
Demonstration Mode interchangeable without any change to the pipeline.
"""

from __future__ import annotations

from ._device import DeviceInfo, resolve_device
from .bytetrack_tracker import ByteTrackTracker
from .detector import Detector
from .frame_source import Frame, FrameSource
from .live_camera_source import LiveCameraSource
from .tracker import Tracker
from .video_file_source import VideoFileSource
from .yolo_detector import DetectorStats, YoloDetector

__all__ = [
    "ByteTrackTracker",
    "Detector",
    "DetectorStats",
    "DeviceInfo",
    "Frame",
    "FrameSource",
    "LiveCameraSource",
    "Tracker",
    "VideoFileSource",
    "YoloDetector",
    "resolve_device",
]
