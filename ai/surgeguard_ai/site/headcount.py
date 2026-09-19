"""The combined count of people across every contributing camera.

Cameras are grouped by the physical area they watch. Areas are independent, so
their counts add. Cameras that share an area may see the same person, so within
an area only the largest single-camera count is used and the plain sum is kept
as the upper bound. No attempt is made to match people between views: that
would need re-identification, which this platform does not do.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..contracts.enums import CountAggregation
from ..contracts.site import CoverageAreaCount, SiteHeadcount
from .observation import CameraContext
from .text import join_names, sentence_list

__all__ = ["HEADCOUNT_LABEL", "combine_headcount", "group_by_area"]

HEADCOUNT_LABEL = "Combined observed count"


def group_by_area(cameras: Sequence[CameraContext]) -> dict[str, list[CameraContext]]:
    """Cameras keyed by coverage area, in first-seen order."""
    areas: dict[str, list[CameraContext]] = {}
    for camera in cameras:
        areas.setdefault(camera.camera.coverage_area, []).append(camera)
    return areas


def combine_headcount(cameras: Sequence[CameraContext]) -> SiteHeadcount:
    """Combine every contributing camera's count, honestly labelled."""
    contributors = [camera for camera in cameras if camera.contributing]
    missing = [camera for camera in cameras if camera.missing]
    missing_ids = tuple(camera.camera_id for camera in missing)

    if not contributors:
        explanation = "No camera is delivering analysis, so there is no count."
        if missing:
            explanation += " " + _missing_sentence(missing, contributors)
        return SiteHeadcount(
            value=None,
            upper_bound=None,
            aggregation=CountAggregation.NO_DATA,
            label=HEADCOUNT_LABEL,
            explanation=explanation,
            missing_camera_ids=missing_ids,
        )

    areas: list[CoverageAreaCount] = []
    for area, members in group_by_area(contributors).items():
        counts = [_count(member) for member in members]
        areas.append(
            CoverageAreaCount(
                coverage_area=area,
                camera_ids=tuple(member.camera_id for member in members),
                value=max(counts),
                upper_bound=sum(counts),
                overlapping=len(members) > 1,
            )
        )

    value = sum(area.value for area in areas)
    upper = sum(area.upper_bound for area in areas)
    overlapping = [area for area in areas if area.overlapping]
    aggregation = (
        CountAggregation.OVERLAP_ADJUSTED if overlapping else CountAggregation.INDEPENDENT_SUM
    )

    parts: list[str] = []
    if len(contributors) == 1:
        parts.append(f"Counted by {contributors[0].display_id}.")
    elif not overlapping:
        parts.append(
            f"The sum of {join_names([c.display_id for c in contributors])}, "
            "which watch separate areas."
        )
    for area in overlapping:
        ids = [camera_id.upper() for camera_id in area.camera_ids]
        together = "both" if len(ids) == 2 else "all"
        parts.append(
            f"{join_names(ids)} {together} watch {area.coverage_area}, so the largest of their "
            "counts is used."
        )
    if overlapping and upper != value:
        parts.append(
            "The same people may appear in more than one view: "
            f"at least {value} and at most {upper}."
        )
    if missing:
        parts.append(_missing_sentence(missing, contributors))

    return SiteHeadcount(
        value=value,
        upper_bound=upper,
        aggregation=aggregation,
        label=HEADCOUNT_LABEL,
        explanation=" ".join(parts),
        areas=tuple(areas),
        contributing_camera_ids=tuple(camera.camera_id for camera in contributors),
        missing_camera_ids=missing_ids,
    )


def _count(camera: CameraContext) -> int:
    analysis = camera.analysis
    assert analysis is not None  # noqa: S101 - only called for contributors
    return analysis.crowd.person_count


def _missing_sentence(
    missing: Sequence[CameraContext], contributors: Sequence[CameraContext]
) -> str:
    """Say what each absent camera means for the count."""
    covered = {camera.camera.coverage_area for camera in contributors}
    statements = []
    for camera in missing:
        area = camera.camera.coverage_area
        if area in covered:
            others = [c.display_id for c in contributors if c.camera.coverage_area == area]
            statements.append(
                f"{camera.display_id} is {camera.status_phrase}; "
                f"{area} is still counted by {join_names(others)}"
            )
        elif camera.owns_coverage_area:
            statements.append(
                f"{camera.display_id} is {camera.status_phrase}, so its view is not counted"
            )
        else:
            statements.append(
                f"{camera.display_id} is {camera.status_phrase}, so {area} is not counted"
            )
    return sentence_list(statements)
