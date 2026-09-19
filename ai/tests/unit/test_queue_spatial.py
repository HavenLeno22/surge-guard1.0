"""The spatial primitives queue detection rests on.

These are tested against hand-worked arrangements rather than recorded data,
because the whole value of the queue/crowd distinction is that each signal means
something specific. A linearity figure that does not fall when a line becomes a
blob is worse than no figure at all.
"""

from __future__ import annotations

import math

import pytest

from surgeguard_ai.contracts import ImagePoint, ImagePolygon
from surgeguard_ai.queue._spatial import (
    axis_alignment,
    heading_coherence,
    point_in_polygon,
    polygon_centroid,
    principal_axis,
    spacing_along_axis,
    spacing_regularity,
)


def square(x1: float, y1: float, x2: float, y2: float) -> ImagePolygon:
    return ImagePolygon(
        points=(
            ImagePoint(x=x1, y=y1),
            ImagePoint(x=x2, y=y1),
            ImagePoint(x=x2, y=y2),
            ImagePoint(x=x1, y=y2),
        )
    )


class TestPointInPolygon:
    def test_point_inside_a_square_is_inside(self) -> None:
        assert point_in_polygon(ImagePoint(x=50.0, y=50.0), square(0, 0, 100, 100))

    @pytest.mark.parametrize(
        ("x", "y"),
        [(150.0, 50.0), (-10.0, 50.0), (50.0, 150.0), (50.0, -10.0)],
    )
    def test_points_beyond_each_edge_are_outside(self, x: float, y: float) -> None:
        assert not point_in_polygon(ImagePoint(x=x, y=y), square(0, 0, 100, 100))

    def test_concave_polygon_excludes_its_notch(self) -> None:
        """An operator drawing a queue zone around a pillar produces a concave
        polygon, and a point in the notch is genuinely outside the queue."""
        l_shape = ImagePolygon(
            points=(
                ImagePoint(x=0.0, y=0.0),
                ImagePoint(x=100.0, y=0.0),
                ImagePoint(x=100.0, y=40.0),
                ImagePoint(x=40.0, y=40.0),
                ImagePoint(x=40.0, y=100.0),
                ImagePoint(x=0.0, y=100.0),
            )
        )
        assert point_in_polygon(ImagePoint(x=20.0, y=20.0), l_shape)
        assert point_in_polygon(ImagePoint(x=80.0, y=20.0), l_shape)
        assert not point_in_polygon(ImagePoint(x=80.0, y=80.0), l_shape)

    def test_centroid_of_a_square_is_its_centre(self) -> None:
        centre = polygon_centroid(square(0, 0, 100, 60))
        assert centre.x == pytest.approx(50.0)
        assert centre.y == pytest.approx(30.0)


class TestPrincipalAxis:
    def test_fewer_than_three_points_has_no_axis(self) -> None:
        """Two points are always perfectly collinear. Reporting linearity 1.0
        for any pair would make every two passers-by look like a queue."""
        assert principal_axis([]) is None
        assert principal_axis([ImagePoint(x=0.0, y=0.0)]) is None
        assert (
            principal_axis([ImagePoint(x=0.0, y=0.0), ImagePoint(x=10.0, y=0.0)]) is None
        )

    def test_a_straight_line_reads_as_highly_linear(self) -> None:
        points = [ImagePoint(x=float(i) * 20.0, y=100.0) for i in range(8)]
        axis = principal_axis(points)
        assert axis is not None
        assert axis.linearity == pytest.approx(1.0, abs=1e-6)
        assert axis.angle_deg == pytest.approx(0.0, abs=1e-6)

    def test_a_circular_cluster_reads_as_barely_linear(self) -> None:
        points = [
            ImagePoint(
                x=100.0 + 50.0 * math.cos(i * math.pi / 6),
                y=100.0 + 50.0 * math.sin(i * math.pi / 6),
            )
            for i in range(12)
        ]
        axis = principal_axis(points)
        assert axis is not None
        assert axis.linearity < 0.1

    def test_a_diagonal_line_reports_its_angle(self) -> None:
        points = [ImagePoint(x=float(i) * 10.0, y=float(i) * 10.0) for i in range(6)]
        axis = principal_axis(points)
        assert axis is not None
        assert axis.angle_deg == pytest.approx(45.0, abs=0.5)

    def test_an_elongated_cluster_reads_between_the_two(self) -> None:
        """Twice as long as it is wide should read about 0.5 - the figure is a
        ratio of axis lengths, which is what the name promises."""
        points = [
            ImagePoint(x=float(i) * 20.0, y=100.0 + (10.0 if i % 2 else -10.0))
            for i in range(10)
        ]
        axis = principal_axis(points)
        assert axis is not None
        assert 0.5 < axis.linearity < 1.0

    def test_coincident_points_are_not_a_line(self) -> None:
        points = [ImagePoint(x=50.0, y=50.0) for _ in range(5)]
        axis = principal_axis(points)
        assert axis is not None
        assert axis.linearity == 0.0


class TestSpacing:
    def test_evenly_spaced_people_score_high_regularity(self) -> None:
        points = [ImagePoint(x=float(i) * 30.0, y=0.0) for i in range(6)]
        axis = principal_axis(points)
        assert axis is not None
        gaps = spacing_along_axis(points, axis)
        assert len(gaps) == 5
        assert all(gap == pytest.approx(30.0, abs=1e-6) for gap in gaps)
        assert spacing_regularity(gaps) == pytest.approx(1.0, abs=1e-6)

    def test_one_person_far_from_the_rest_lowers_regularity(self) -> None:
        points = [ImagePoint(x=x, y=0.0) for x in (0.0, 10.0, 20.0, 30.0, 400.0)]
        axis = principal_axis(points)
        assert axis is not None
        regularity = spacing_regularity(spacing_along_axis(points, axis))
        assert regularity is not None
        assert regularity < 0.3

    def test_regularity_needs_at_least_two_gaps(self) -> None:
        assert spacing_regularity([]) is None
        assert spacing_regularity([25.0]) is None

    def test_regularity_is_scale_free(self) -> None:
        """The same queue seen from further away has the same regularity."""
        near = [ImagePoint(x=float(i) * 100.0, y=0.0) for i in range(5)]
        far = [ImagePoint(x=float(i) * 10.0, y=0.0) for i in range(5)]
        axis_near, axis_far = principal_axis(near), principal_axis(far)
        assert axis_near is not None and axis_far is not None
        assert spacing_regularity(
            spacing_along_axis(near, axis_near)
        ) == pytest.approx(spacing_regularity(spacing_along_axis(far, axis_far)))


class TestHeadingCoherence:
    def test_everyone_moving_the_same_way_is_fully_coherent(self) -> None:
        assert heading_coherence([(1.0, 0.0)] * 5) == pytest.approx(1.0)

    def test_opposed_headings_cancel(self) -> None:
        coherence = heading_coherence([(1.0, 0.0), (-1.0, 0.0)])
        assert coherence == pytest.approx(0.0, abs=1e-9)

    def test_speed_does_not_affect_coherence(self) -> None:
        """A queue shuffling and a queue striding are equally coherent; letting
        one fast walker outvote ten shufflers would be wrong."""
        assert heading_coherence(
            [(10.0, 0.0), (0.1, 0.0), (0.1, 0.0)]
        ) == pytest.approx(1.0)

    def test_stationary_tracks_carry_no_direction(self) -> None:
        assert heading_coherence([(0.0, 0.0)] * 5) is None

    def test_a_single_heading_is_not_information(self) -> None:
        assert heading_coherence([(1.0, 0.0)]) is None

    def test_scattered_headings_score_low(self) -> None:
        headings = [
            (math.cos(i * math.pi / 4), math.sin(i * math.pi / 4)) for i in range(8)
        ]
        coherence = heading_coherence(headings)
        assert coherence is not None
        assert coherence < 0.1


class TestAxisAlignment:
    def test_an_axis_pointing_at_the_target_aligns_fully(self) -> None:
        points = [ImagePoint(x=float(i) * 20.0, y=0.0) for i in range(5)]
        axis = principal_axis(points)
        assert axis is not None
        assert axis_alignment(axis, ImagePoint(x=500.0, y=0.0)) == pytest.approx(1.0)

    def test_a_target_perpendicular_to_the_axis_does_not_align(self) -> None:
        points = [ImagePoint(x=float(i) * 20.0, y=0.0) for i in range(5)]
        axis = principal_axis(points)
        assert axis is not None
        assert axis_alignment(
            axis, ImagePoint(x=40.0, y=500.0)
        ) == pytest.approx(0.0, abs=1e-6)

    def test_alignment_is_undirected(self) -> None:
        """A queue pointing at a counter and the same queue described from the
        far end are the same queue."""
        points = [ImagePoint(x=float(i) * 20.0, y=0.0) for i in range(5)]
        axis = principal_axis(points)
        assert axis is not None
        assert axis_alignment(axis, ImagePoint(x=500.0, y=0.0)) == pytest.approx(
            axis_alignment(axis, ImagePoint(x=-500.0, y=0.0))
        )

    def test_a_target_on_the_axis_centre_reports_no_alignment(self) -> None:
        points = [ImagePoint(x=float(i) * 20.0, y=0.0) for i in range(5)]
        axis = principal_axis(points)
        assert axis is not None
        centre = ImagePoint(x=axis.centre[0], y=axis.centre[1])
        assert axis_alignment(axis, centre) == 0.0
