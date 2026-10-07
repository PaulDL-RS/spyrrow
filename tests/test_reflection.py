import json
import math

import pytest
import spyrrow

# Scalene triangle: not equal to its mirror image under any rotation, hence chiral
CHIRAL = [(0.0, 0.0), (4.0, 0.0), (1.0, 2.0)]
TOL = 1e-3


def place(points, placed):
    """Apply the documented transformation: mirror (x,y)->(x,-y) if reflected, rotate (degrees, ccw) around origin, translate."""
    c = math.cos(math.radians(placed.rotation))
    s = math.sin(math.radians(placed.rotation))
    tx, ty = placed.translation
    out = []
    for x, y in points:
        if placed.reflected:
            y = -y
        out.append((c * x - s * y + tx, s * x + c * y + ty))
    return out


def signed_area(points):
    n = len(points)
    return 0.5 * sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    )


def proper_cross(p1, p2, q1, q2, eps=1e-4):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return d1 * d2 < -eps and d3 * d4 < -eps


def edges_cross(a, b):
    ea = [(a[i], a[(i + 1) % len(a)]) for i in range(len(a))]
    eb = [(b[i], b[(i + 1) % len(b)]) for i in range(len(b))]
    return any(proper_cross(*e, *f) for e in ea for f in eb)


class Placed:
    """Stand-in for PlacedItem, which can not be instantiated from Python"""

    def __init__(self, rotation, translation=(0.0, 0.0), reflected=False):
        self.rotation = rotation
        self.translation = translation
        self.reflected = reflected


def test_axis_canonicalization_math():
    # Reflecting across the axis at angle a then rotating by r is exported as
    # reflected=True with rotation r + 2a (jagua-rs AllowedOrientations)
    a, r = 20.0, 70.0
    for x, y in CHIRAL:
        # mirror across the axis at angle a, written with the axis direction (cos a, sin a)
        ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
        d = x * ca + y * sa
        mx, my = 2 * d * ca - x, 2 * d * sa - y
        expected = place([(mx, my)], Placed(r))[0]
        got = place([(x, y)], Placed(r + 2 * a, reflected=True))[0]
        assert got == pytest.approx(expected, abs=1e-9)


def solve(item, height=2.01, seed=0):
    instance = spyrrow.StripPackingInstance("test", strip_height=height, items=[item])
    config = spyrrow.StripPackingConfig(
        total_computation_time=5, num_workers=2, seed=seed
    )
    return instance.solve(config)


def check_solution(item, sol, height):
    shapes = []
    for p in sol.placed_items:
        assert isinstance(p.reflected, bool)
        pts = place(item.shape, p)
        # mirroring flips the orientation of the polygon, rotation and translation do not
        sign = -1.0 if p.reflected else 1.0
        assert signed_area(pts) == pytest.approx(
            sign * signed_area(item.shape), rel=1e-3
        )
        for x, y in pts:
            assert -TOL <= x <= sol.width + TOL
            assert -TOL <= y <= height + TOL
        shapes.append(pts)
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            assert not edges_cross(shapes[i], shapes[j])


def test_default_not_reflected():
    item = spyrrow.Item("t", CHIRAL, 4, allowed_orientations=[0, 90, 180, 270])
    assert item.reflection_axis is None
    sol = solve(item, height=4.0)
    assert len(sol.placed_items) == 4
    assert all(p.reflected is False for p in sol.placed_items)
    check_solution(item, sol, 4.0)


def test_reflection_transform_consistent():
    item = spyrrow.Item(
        "t", CHIRAL, 6, allowed_orientations=[0, 180], reflection_axis=0.0
    )
    sol = solve(item)
    assert len(sol.placed_items) == 6
    check_solution(item, sol, 2.01)


def test_reflection_with_free_rotation():
    item = spyrrow.Item("t", CHIRAL, 4, allowed_orientations=None, reflection_axis=30.0)
    sol = solve(item, height=4.0)
    assert len(sol.placed_items) == 4
    check_solution(item, sol, 4.0)


def test_reflection_axis_rotation_canonicalization():
    # Axis at 90 degrees with orientations [] : the only allowed placements are the identity
    # or the mirror across the y axis, i.e. reflected with rotation 2*90 = 180
    item = spyrrow.Item("t", CHIRAL, 3, allowed_orientations=[], reflection_axis=90.0)
    sol = solve(item, height=4.0)
    for p in sol.placed_items:
        rot = p.rotation % 360.0
        if p.reflected:
            assert min(abs(rot - 180.0), 360.0 - abs(rot - 180.0)) < 1e-2
        else:
            assert min(rot, 360.0 - rot) < 1e-2
    check_solution(item, sol, 4.0)


def test_reflected_reported_in_progress():
    item = spyrrow.Item("t", CHIRAL, 4, allowed_orientations=[0, 180], reflection_axis=0.0)
    instance = spyrrow.StripPackingInstance("test", strip_height=2.01, items=[item])
    queue = spyrrow.ProgressQueue()
    config = spyrrow.StripPackingConfig(total_computation_time=3, num_workers=2, seed=0)
    instance.solve(config, progress=queue)
    reports = queue.drain()
    assert reports
    for _, sol in reports:
        for p in sol.placed_items:
            assert isinstance(p.reflected, bool)


def test_reflection_axis_attribute_and_repr():
    item = spyrrow.Item("t", CHIRAL, 1, None)
    assert "reflection_axis" not in repr(item)
    item.reflection_axis = 45.0
    assert item.reflection_axis == 45.0
    assert "reflection_axis=45.0" in repr(item)
    item.reflection_axis = None
    assert item.reflection_axis is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_axis_raises(bad):
    with pytest.raises(ValueError):
        spyrrow.Item("t", CHIRAL, 1, None, reflection_axis=bad)


def test_json_unchanged_without_reflection():
    item = spyrrow.Item("t", CHIRAL, 2, allowed_orientations=[0, 90])
    assert item.to_json_str() == (
        '{"id":"t","demand":2,"allowed_orientations":[0.0,90.0],'
        '"shape":[[0.0,0.0],[4.0,0.0],[1.0,2.0]]}'
    )
    assert "reflection_axis" not in json.loads(item.to_json_str())
    item.reflection_axis = 10.0
    assert json.loads(item.to_json_str())["reflection_axis"] == 10.0


def test_deepcopy_keeps_axis():
    import copy

    item = spyrrow.Item("t", CHIRAL, 1, None, reflection_axis=12.5)
    assert copy.deepcopy(item).reflection_axis == 12.5


def test_allowed_orientations_still_required():
    # same contract as spyrrow 0.10: allowed_orientations has no default
    with pytest.raises(TypeError):
        spyrrow.Item("x", [(0, 0), (1, 0), (1, 1)], 1)
