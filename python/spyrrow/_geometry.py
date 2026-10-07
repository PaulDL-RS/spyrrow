"""Small pure-Python geometry helpers (no dependency)."""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]


def signed_area(shape: Sequence[Point]) -> float:
    """Shoelace formula. Positive for counter-clockwise polygons."""
    n = len(shape)
    total = 0.0
    for i in range(n):
        x1, y1 = shape[i]
        x2, y2 = shape[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def height_at(shape: Sequence[Point], angle_deg: float, reflected: bool) -> float:
    """Height (y extent) of the shape after an optional reflection (y -> -y) then a rotation."""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    lo = math.inf
    hi = -math.inf
    for x, y in shape:
        if reflected:
            y = -y
        v = x * s + y * c
        lo = min(lo, v)
        hi = max(hi, v)
    return hi - lo


def convex_hull(points: Sequence[Point]) -> list[Point]:
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def min_width(shape: Sequence[Point]) -> float:
    """Minimum width of the shape over all directions (rotating calipers on the convex hull).

    It is the minimum height reachable by *any* rotation of the shape.
    """
    hull = convex_hull(shape)
    n = len(hull)
    if n < 3:
        return 0.0
    best = math.inf
    for i in range(n):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % n]
        ex, ey = x2 - x1, y2 - y1
        norm = math.hypot(ex, ey)
        if norm == 0:
            continue
        # distance of the farthest vertex from the edge line
        width = max(abs((px - x1) * ey - (py - y1) * ex) / norm for px, py in hull)
        best = min(best, width)
    return best
