"""Plane geometry helpers. Map coordinates are Azgaar pixels; y grows southwards."""
from __future__ import annotations

import math
from typing import Iterable, Sequence

Point = Sequence[float]

COMPASS = ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"]


def polyline_length(points: Sequence[Point]) -> float:
    return sum(math.dist(points[i][:2], points[i + 1][:2]) for i in range(len(points) - 1))


def project_on_segment(p: Point, a: Point, b: Point) -> tuple[float, float]:
    """Return (distance from p to segment ab, fraction t along ab of the nearest point)."""
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy)), t


def locate_on_polyline(p: Point, points: Sequence[Point]) -> tuple[float, float]:
    """Return (offset, along): shortest distance from p to the polyline and the
    distance along the polyline to the nearest point, both in map pixels."""
    if len(points) == 1:
        return math.dist(p[:2], points[0][:2]), 0.0
    best_offset, best_along, run = math.inf, 0.0, 0.0
    for i in range(len(points) - 1):
        seg = math.dist(points[i][:2], points[i + 1][:2])
        offset, t = project_on_segment(p, points[i], points[i + 1])
        if offset < best_offset:
            best_offset, best_along = offset, run + t * seg
        run += seg
    return best_offset, best_along


def bearing_to_compass(a: Point, b: Point) -> str:
    """Eight-point compass direction from a to b (map y axis points south)."""
    angle = math.degrees(math.atan2(a[1] - b[1], b[0] - a[0])) % 360
    return COMPASS[int((angle + 22.5) // 45) % 8]


def ring_area(ring: Sequence[Point]) -> float:
    """Shoelace area of a ring; works whether or not the ring is closed."""
    n = len(ring)
    return abs(sum(ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1] for i in range(n))) / 2


def ring_centroid(ring: Sequence[Point]) -> tuple[float, float]:
    """Vertex mean; adequate for the small convex-ish rings in Watabou output."""
    pts = ring[:-1] if len(ring) > 1 and tuple(ring[0]) == tuple(ring[-1]) else ring
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def nearest(p: Point, candidates: Iterable[tuple[object, Point]]) -> tuple[object, float]:
    best, best_d = None, math.inf
    for key, q in candidates:
        d = math.dist(p[:2], q[:2])
        if d < best_d:
            best, best_d = key, d
    return best, best_d
