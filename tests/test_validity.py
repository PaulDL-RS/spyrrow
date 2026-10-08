"""Hardware independent correctness tests.

Short time budgets on purpose: whatever the speed of the machine (emulated CI runners included),
the solver must return a valid layout. Quality targets are asserted in tests marked `quality`.
"""

import pytest
import spyrrow

from validity import assert_valid_solution, polygon_area, polygons_overlap, triangulate

SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
TRIANGLE = [(0, 0), (1, 0), (1, 1), (0, 0)]
CONCAVE_1 = [(0, 0), (3, 0), (4, 1), (3, 2), (0, 2), (1, 1), (0, 0)]
CONCAVE_2 = [(0, 0), (1, 0), (1, 2), (3, 2), (3, 0), (4, 0), (4, 3), (0, 3), (0, 0)]

INSTANCES = {
    "mixed": (2.001, [("rectangle", SQUARE, 4, [0]), ("triangle", TRIANGLE, 6, [0, 90, 180, -90])]),
    "one_item": (2.001, [("triangle", TRIANGLE, 3, [0, 90, 180, 270])]),
    "one_demand_45": (2.001, [("triangle", TRIANGLE, 1, [0, 45, 90, 135, 180, -45, -90, -135])]),
    "continuous": (2.001, [("rectangle", SQUARE, 4, None), ("triangle", TRIANGLE, 6, None)]),
    "no_rotation": (2.001, [("triangle", TRIANGLE, 6, [])]),
    "concave": (4.001, [("0", CONCAVE_1, 2, [0, 90, 180, 270]), ("1", CONCAVE_2, 3, [0, 90, 180, 270])]),
}


def make_instance(name: str) -> spyrrow.StripPackingInstance:
    height, items = INSTANCES[name]
    return spyrrow.StripPackingInstance(
        name, strip_height=height, items=[spyrrow.Item(id, shape, demand, orientations) for id, shape, demand, orientations in items]
    )


@pytest.mark.parametrize("name", INSTANCES)
def test_solution_is_valid(name):
    instance = make_instance(name)
    config = spyrrow.StripPackingConfig(early_termination=True, total_computation_time=4, num_workers=2, seed=0)
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)


def test_solution_is_valid_with_separation():
    instance = make_instance("mixed")
    config = spyrrow.StripPackingConfig(
        early_termination=True, total_computation_time=4, num_workers=2, seed=0, min_items_separation=0.05
    )
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    # 4 squares in a 2.001 high strip need two columns, and separation forbids exact fits
    assert sol.width > 2


def test_progress_solutions_are_valid():
    instance = make_instance("mixed")
    queue = spyrrow.ProgressQueue()
    config = spyrrow.StripPackingConfig(early_termination=True, total_computation_time=4, num_workers=2, seed=0)
    instance.solve(config, progress=queue)
    reports = queue.drain()
    feasible = (spyrrow.ReportType.ExplFeas, spyrrow.ReportType.CmprFeas, spyrrow.ReportType.Final)
    checked = [sol for report_type, sol in reports if report_type in feasible]
    assert checked
    for sol in checked:
        assert_valid_solution(instance, sol)


# Self tests of the checker, so that a broken checker can not make the tests above pass silently

UNIT = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def shifted(poly, dx, dy):
    return [(x + dx, y + dy) for x, y in poly]


@pytest.mark.parametrize(
    "other, overlap",
    [
        (shifted(UNIT, 1, 0), False),  # sharing an edge
        (shifted(UNIT, 1, 1), False),  # sharing a corner
        (shifted(UNIT, 2, 0), False),  # apart
        (shifted(UNIT, 0.5, 0.5), True),  # crossing edges
        (shifted(UNIT, 0, 0), True),  # identical
        ([(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)], True),  # contained
        (shifted(UNIT, 0.5, 0), True),  # collinear edges, half overlap
    ],
)
def test_overlap_checker(other, overlap):
    assert polygons_overlap(UNIT, other, 1e-6) is overlap
    assert polygons_overlap(other, UNIT, 1e-6) is overlap


U_SHAPE = [(0.0, 0.0), (1.0, 0.0), (1.0, 2.0), (3.0, 2.0), (3.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)]


@pytest.mark.parametrize(
    "other, overlap",
    [
        ([(1.5, 0.5), (2.5, 0.5), (2.5, 1.5), (1.5, 1.5)], False),  # inside the notch
        ([(1.0, 0.0), (3.0, 0.0), (3.0, 2.0), (1.0, 2.0)], False),  # filling the notch exactly
        ([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)], True),  # overlapping an arm
    ],
)
def test_overlap_checker_concave(other, overlap):
    assert polygons_overlap(U_SHAPE, other, 1e-6) is overlap
    assert polygons_overlap(other, U_SHAPE, 1e-6) is overlap


@pytest.mark.parametrize("poly", [UNIT, U_SHAPE, CONCAVE_1[:-1], CONCAVE_2[:-1], list(reversed(U_SHAPE))])
def test_triangulation_preserves_area(poly):
    assert sum(polygon_area(t) for t in triangulate(poly)) == pytest.approx(polygon_area(poly))
