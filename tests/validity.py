"""Hardware independent checks of a StripPackingSolution.

These only assert what must hold for any valid layout, whatever the time budget and the speed of the machine:
every item placed `demand` times, allowed rotations, items inside the strip, no overlap between items.
Quality targets (how narrow the strip is) belong in tests marked with `@pytest.mark.quality`.
"""

import math
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spyrrow import Item, PlacedItem, StripPackingInstance, StripPackingSolution

Polygon = list[tuple[float, float]]


def item_polygon(item: "Item") -> Polygon:
    points = [tuple(p) for p in item.shape]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return points


def placed_polygon(item: "Item", placed: "PlacedItem") -> Polygon:
    """Apply the documented transformation: rotation around the origin, then translation."""
    angle = math.radians(placed.rotation)
    cos, sin = math.cos(angle), math.sin(angle)
    tx, ty = placed.translation
    return [(x * cos - y * sin + tx, x * sin + y * cos + ty) for x, y in item_polygon(item)]


def polygon_area(poly: Polygon) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]))) / 2


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def triangulate(poly: Polygon) -> list[Polygon]:
    """Ear clipping triangulation of a simple polygon."""
    pts = list(poly)
    if sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])) < 0:
        pts.reverse()  # counter clockwise
    triangles = []
    while len(pts) > 3:
        n = len(pts)
        for i in range(n):
            prev, cur, nxt = pts[i - 1], pts[i], pts[(i + 1) % n]
            turn = _cross(prev, cur, nxt)
            if turn == 0:  # collinear vertex, no area
                pts.pop(i)
                break
            if turn < 0:  # reflex vertex
                continue
            others = (p for p in pts if p not in (prev, cur, nxt))
            if any(_cross(prev, cur, p) >= 0 and _cross(cur, nxt, p) >= 0 and _cross(nxt, prev, p) >= 0 for p in others):
                continue
            triangles.append([prev, cur, nxt])
            pts.pop(i)
            break
        else:
            raise ValueError(f"could not triangulate {poly}")
    if len(pts) == 3 and _cross(*pts) != 0:
        triangles.append(pts)
    return triangles


def _convex_overlap(a: Polygon, b: Polygon, tol: float) -> bool:
    """Separating axis test: overlapping with positive area iff the penetration exceeds tol on every edge normal."""
    for poly in (a, b):
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
            nx, ny = y1 - y2, x2 - x1
            norm = math.hypot(nx, ny)
            if norm == 0:
                continue
            proj_a = [(x * nx + y * ny) / norm for x, y in a]
            proj_b = [(x * nx + y * ny) / norm for x, y in b]
            if min(max(proj_a), max(proj_b)) - max(min(proj_a), min(proj_b)) <= tol:
                return False
    return True


def polygons_overlap(a: Polygon, b: Polygon, tol: float) -> bool:
    """True if a and b share an area wider than tol. Touching edges or corners are not overlaps."""
    (ax0, ay0), (ax1, ay1) = _bbox(a)
    (bx0, by0), (bx1, by1) = _bbox(b)
    if ax1 <= bx0 + tol or bx1 <= ax0 + tol or ay1 <= by0 + tol or by1 <= ay0 + tol:
        return False
    return any(_convex_overlap(ta, tb, tol) for ta in triangulate(a) for tb in triangulate(b))


def _bbox(poly: Polygon):
    xs, ys = [x for x, _ in poly], [y for _, y in poly]
    return (min(xs), min(ys)), (max(xs), max(ys))


def _rotation_allowed(rotation: float, allowed: list[float] | None, tol: float = 1e-3) -> bool:
    if allowed is None:
        return True
    allowed = allowed or [0.0]
    return any(abs((rotation - a + 180) % 360 - 180) <= tol for a in allowed)


def assert_valid_solution(instance: "StripPackingInstance", solution: "StripPackingSolution") -> None:
    items = {item.id: item for item in instance.items}
    height = instance.strip_height
    width = solution.width
    tol = 1e-4 * max(width, height, 1.0)

    counts = Counter(pi.id for pi in solution.placed_items)
    assert counts == {item.id: item.demand for item in instance.items}, f"placed counts {counts}"

    total_area = sum(polygon_area(item_polygon(item)) * item.demand for item in instance.items)
    assert width >= total_area / height - tol, f"width {width} below the area lower bound"
    assert 0 < solution.density <= 1 + 1e-4

    polygons = []
    for pi in solution.placed_items:
        item = items[pi.id]
        assert _rotation_allowed(pi.rotation, item.allowed_orientations), (
            f"{pi.id}: rotation {pi.rotation} not in {item.allowed_orientations}"
        )
        poly = placed_polygon(item, pi)
        (x0, y0), (x1, y1) = _bbox(poly)
        assert x0 >= -tol and y0 >= -tol and x1 <= width + tol and y1 <= height + tol, (
            f"{pi.id} outside the strip [0, {width}]x[0, {height}]: {poly}"
        )
        polygons.append((pi.id, poly))

    for i, (id_a, a) in enumerate(polygons):
        for id_b, b in polygons[i + 1 :]:
            assert not polygons_overlap(a, b, tol), f"{id_a} overlaps {id_b}: {a} / {b}"
