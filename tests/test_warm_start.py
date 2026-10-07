import pytest
import spyrrow


def make_instance(demand_rect=4, rect_id="rectangle", height=2.001):
    rectangle = spyrrow.Item(
        rect_id,
        [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
        demand=demand_rect,
        allowed_orientations=[0],
    )
    triangle = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=6,
        allowed_orientations=[0, 90, 180, -90],
    )
    return spyrrow.StripPackingInstance(
        "warm", strip_height=height, items=[rectangle, triangle]
    )


def config(seconds=4, **kwargs):
    return spyrrow.StripPackingConfig(
        total_computation_time=seconds, num_workers=2, seed=0, **kwargs
    )


def test_warm_start_not_worse():
    instance = make_instance()
    first = instance.solve(config(4))
    second = instance.solve(config(4), initial_solution=first)
    assert len(second.placed_items) == 10
    # The solver starts from the given (feasible) solution and only keeps improvements.
    assert second.width <= first.width * (1 + 1e-4)


def test_warm_start_with_progress_and_separation():
    instance = make_instance()
    first = instance.solve(config(3, min_items_separation=0.01))
    queue = spyrrow.ProgressQueue()
    second = instance.solve(
        config(3, min_items_separation=0.01), progress=queue, initial_solution=first
    )
    assert second.width <= first.width * (1 + 1e-4)
    reports = queue.drain()
    # first report is the warm start itself
    assert reports[0][1].width == pytest.approx(first.width, rel=1e-4)


def test_unknown_id():
    solution = make_instance().solve(config(2))
    other = make_instance(rect_id="other")
    with pytest.raises(ValueError, match="rectangle"):
        other.solve(config(2), initial_solution=solution)


def test_demand_mismatch():
    solution = make_instance().solve(config(2))
    with pytest.raises(ValueError, match="demand"):
        make_instance(demand_rect=5).solve(config(2), initial_solution=solution)


def test_empty_instance():
    empty = spyrrow.StripPackingInstance("empty", strip_height=2.0, items=[])
    empty_solution = empty.solve(config(1))
    assert empty.solve(config(1), initial_solution=empty_solution).placed_items == []
    solution = make_instance().solve(config(2))
    with pytest.raises(ValueError):
        empty.solve(config(1), initial_solution=solution)
