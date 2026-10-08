import json
import time

import pytest
import spyrrow

from validity import assert_valid_solution

SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
TRIANGLE = [(0, 0), (1, 0), (1, 1), (0, 0)]


def make_instance():
    return spyrrow.StripPackingInstance(
        "test",
        strip_height=2.001,
        items=[
            spyrrow.Item("rectangle", SQUARE, 4, [0]),
            spyrrow.Item("triangle", TRIANGLE, 6, [0, 90, 180, -90]),
        ],
    )


def budget_config(max_evaluations=300_000, **kwargs):
    return spyrrow.StripPackingConfig(total_computation_time=3600, num_workers=2, seed=0, max_evaluations=max_evaluations, **kwargs)


def placements(sol):
    return sorted((pi.id, pi.translation, pi.rotation) for pi in sol.placed_items)


@pytest.mark.parametrize("early_termination", [True, False])
def test_same_budget_same_result(early_termination):
    instance = make_instance()
    sol1 = instance.solve(budget_config(early_termination=early_termination))
    sol2 = instance.solve(budget_config(early_termination=early_termination))
    assert_valid_solution(instance, sol1)
    assert sol1.width == sol2.width
    assert placements(sol1) == placements(sol2)


def test_budget_stops_before_time_limit():
    instance = make_instance()
    start = time.monotonic()
    sol = instance.solve(budget_config(early_termination=False))
    # far from the 3600 s time limit, even on slow emulated runners
    assert time.monotonic() - start < 1200
    assert_valid_solution(instance, sol)


def test_budget_with_progress():
    instance = make_instance()
    queue = spyrrow.ProgressQueue()
    sol = instance.solve(budget_config(), progress=queue)
    assert_valid_solution(instance, sol)
    reports = queue.drain()
    assert reports[-1][0] == spyrrow.ReportType.Final
    assert placements(reports[-1][1]) == placements(sol)


def test_zero_budget_raises():
    with pytest.raises(ValueError):
        budget_config(max_evaluations=0)


def test_default_is_no_budget():
    config = spyrrow.StripPackingConfig()
    assert config.max_evaluations is None
    # JSON unchanged when unused
    assert "max_evaluations" not in json.loads(config.to_json_str())
    config.max_evaluations = 1000
    assert config.max_evaluations == 1000
    assert json.loads(config.to_json_str())["max_evaluations"] == 1000
