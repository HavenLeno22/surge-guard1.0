"""Spatial primitives for queue structure analysis.

Pure functions over point sets. No contracts, no configuration, no state - so
each one is testable against a hand-worked example, which matters because these
are the measurements the queue-versus-crowd distinction rests on.

Everything here works in **image space** (pixels). Ground-space equivalents are
obtained by projecting the inputs first; the mathematics is identical and the
functions do not need to know which space they were handed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from ..contracts.geometry import ImagePoint, ImagePolygon

__all__ = [
    "point_in_polygon",
    "polygon_centroid",
    "PrincipalAxis",
    "principal_axis",
    "spacing_along_axis",
    "spacing_regularity",
    "heading_coherence",
    "axis_alignment",
]


def point_in_polygon(point: ImagePoint, polygon: ImagePolygon) -> bool:
    """Whether ``point`` lies inside ``polygon``.

    Crossing-number (ray casting) test: cast a ray in +X and count edge
    crossings, inside being an odd count. Handles concave polygons, which
    matters because an operator drawing a queue zone around a corner produces
    one.

    A point exactly on an edge may fall either way. That is acceptable here -
    the alternative is an epsilon that would have to be tuned per resolution,
    and a person's foot point is never meaningfully "on" a hand-drawn boundary.
    """
    vertices = polygon.points
    inside = False
    count = len(vertices)

    j = count - 1
    for i in range(count):
        yi, yj = vertices[i].y, vertices[j].y
        # Does this edge straddle the horizontal ray through `point`?
        if (yi > point.y) != (yj > point.y):
            xi, xj = vertices[i].x, vertices[j].x
            # X coordinate where the edge crosses the ray.
            crossing_x = xi + (point.y - yi) / (yj - yi) * (xj - xi)
            if point.x < crossing_x:
                inside = not inside
        j = i

    return inside


def polygon_centroid(polygon: ImagePolygon) -> ImagePoint:
    """Centroid of a polygon's vertices.

    The vertex mean rather than the area centroid: zone polygons are drawn as a
    handful of points around a region, and the difference between the two is far
    below the precision anything downstream claims.
    """
    points = polygon.points
    return ImagePoint(
        x=sum(p.x for p in points) / len(points),
        y=sum(p.y for p in points) / len(points),
    )


class PrincipalAxis:
    """The dominant direction through a set of points, and how dominant it is.

    Produced by :func:`principal_axis`. Holds the results of a 2x2 principal
    component analysis in a form the queue analyser can use directly.
    """

    __slots__ = ("centre", "direction", "major_sigma", "minor_sigma")

    def __init__(
        self,
        centre: tuple[float, float],
        direction: tuple[float, float],
        major_sigma: float,
        minor_sigma: float,
    ) -> None:
        self.centre = centre
        self.direction = direction
        """Unit vector along the major axis."""
        self.major_sigma = major_sigma
        """Standard deviation along the major axis, in input units."""
        self.minor_sigma = minor_sigma
        """Standard deviation across it."""

    @property
    def linearity(self) -> float:
        """How line-like the point set is, in ``[0, 1]``.

        ``1 - minor/major`` on the standard deviations, so the figure is a ratio
        of axis *lengths* rather than of variances - a set twice as long as it is
        wide reads 0.5, which is what an operator would expect from the phrase.

        A degenerate set (every point coincident) reads 0.0 rather than raising:
        it is not a line, and that is the honest answer.
        """
        if self.major_sigma <= 1e-9:
            return 0.0
        return max(0.0, min(1.0, 1.0 - (self.minor_sigma / self.major_sigma)))

    @property
    def angle_deg(self) -> float:
        """Orientation of the major axis, degrees in ``[0, 180)``.

        An axis has no head or tail, so directions 180 degrees apart are the same
        axis and fold onto one value.
        """
        angle = math.degrees(math.atan2(self.direction[1], self.direction[0]))
        return angle % 180.0


def principal_axis(points: Sequence[ImagePoint]) -> PrincipalAxis | None:
    """Principal component analysis of a point set.

    Returns ``None`` for fewer than three points, where "the direction this set
    lies along" is not a meaningful question: two points always lie perfectly on
    a line, and reporting linearity 1.0 for any pair would make every pair of
    passers-by look like a queue.

    Solved in closed form rather than through a general eigensolver - the matrix
    is 2x2 and the closed form is both faster and easier to verify by hand.
    """
    if len(points) < 3:
        return None

    coords = np.array([[p.x, p.y] for p in points], dtype=np.float64)
    centre = coords.mean(axis=0)
    centred = coords - centre

    # Population covariance. ddof=0 because this is the spread of the observed
    # set itself, not an estimate of a wider population's spread.
    cov = (centred.T @ centred) / len(points)
    a, b, c = cov[0, 0], cov[0, 1], cov[1, 1]

    trace = a + c
    discriminant = math.sqrt(max(0.0, (a - c) ** 2 + 4.0 * b * b))
    major_var = (trace + discriminant) / 2.0
    minor_var = (trace - discriminant) / 2.0

    # Eigenvector for the major eigenvalue. Both (b, major_var - a) and
    # (major_var - c, b) are valid; whichever has the larger magnitude is the
    # numerically stable choice.
    v1 = (b, major_var - a)
    v2 = (major_var - c, b)
    vec = v1 if (v1[0] ** 2 + v1[1] ** 2) >= (v2[0] ** 2 + v2[1] ** 2) else v2

    norm = math.hypot(vec[0], vec[1])
    if norm <= 1e-12:
        # Isotropic spread: no axis dominates. Any direction is as good as
        # another, so report +X and let linearity (which will be ~0) say so.
        direction = (1.0, 0.0)
    else:
        direction = (vec[0] / norm, vec[1] / norm)

    return PrincipalAxis(
        centre=(float(centre[0]), float(centre[1])),
        direction=direction,
        major_sigma=math.sqrt(max(0.0, major_var)),
        minor_sigma=math.sqrt(max(0.0, minor_var)),
    )


def spacing_along_axis(
    points: Sequence[ImagePoint], axis: PrincipalAxis
) -> tuple[float, ...]:
    """Gaps between consecutive points projected onto ``axis``, in input units.

    Projecting collapses the queue to one dimension - its own length - which is
    the only dimension along which "the gap between two people in the line" has
    a meaning. Returns an empty tuple for fewer than two points.
    """
    if len(points) < 2:
        return ()

    dx, dy = axis.direction
    cx, cy = axis.centre
    projections = sorted((p.x - cx) * dx + (p.y - cy) * dy for p in points)
    return tuple(
        projections[i + 1] - projections[i] for i in range(len(projections) - 1)
    )


def spacing_regularity(gaps: Sequence[float]) -> float | None:
    """How evenly sized a set of gaps is, in ``[0, 1]``.

    ``1 - min(1, sigma/mu)`` on the gaps: a queue whose members stand at
    consistent intervals reads high, a cluster with one person far off to the
    side reads low. ``None`` for fewer than two gaps (three people), below which
    regularity is not measurable.

    Uses the coefficient of variation rather than raw standard deviation so the
    figure is scale-free - a queue seen from further away has smaller gaps in
    pixels but the same regularity.
    """
    if len(gaps) < 2:
        return None

    mean = sum(gaps) / len(gaps)
    if mean <= 1e-9:
        return None

    variance = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    cv = math.sqrt(variance) / mean
    return max(0.0, min(1.0, 1.0 - cv))


def heading_coherence(velocities: Sequence[tuple[float, float]]) -> float | None:
    """Agreement in direction among a set of velocity vectors, in ``[0, 1]``.

    The resultant length of the unit heading vectors: 1.0 when everything moves
    the same way, near 0.0 when directions are spread evenly. Speed is discarded
    deliberately - a queue shuffling forward slowly and a queue walking briskly
    are equally coherent, and weighting by speed would let one fast walker
    outvote ten shufflers.

    Vectors with negligible magnitude carry no direction and are skipped. If
    that leaves fewer than two, returns ``None``: a single heading agrees with
    itself trivially, which is not information.
    """
    units: list[tuple[float, float]] = []
    for dx, dy in velocities:
        magnitude = math.hypot(dx, dy)
        if magnitude > 1e-6:
            units.append((dx / magnitude, dy / magnitude))

    if len(units) < 2:
        return None

    sum_x = sum(u[0] for u in units)
    sum_y = sum(u[1] for u in units)
    return max(0.0, min(1.0, math.hypot(sum_x, sum_y) / len(units)))


def axis_alignment(
    axis: PrincipalAxis, target: ImagePoint
) -> float:
    """How closely ``axis`` points at ``target``, in ``[0, 1]``.

    ``|cos(angle)|`` between the axis direction and the vector from the axis
    centre to the target. Absolute because an axis is undirected: a queue
    pointing at a counter and the same queue described from the other end are
    the same queue.

    Returns 0.0 when the target coincides with the axis centre, where the angle
    is undefined - reporting "not aligned" rather than raising, so a badly placed
    zone degrades the confidence instead of stopping the analysis.
    """
    cx, cy = axis.centre
    to_target = (target.x - cx, target.y - cy)
    magnitude = math.hypot(to_target[0], to_target[1])
    if magnitude <= 1e-9:
        return 0.0

    dx, dy = axis.direction
    cosine = (to_target[0] * dx + to_target[1] * dy) / magnitude
    return max(0.0, min(1.0, abs(cosine)))
