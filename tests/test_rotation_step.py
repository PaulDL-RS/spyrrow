import json

import pytest
import spyrrow

SQUARE = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]


def solve(items, height=6.0, seed=0):
    instance = spyrrow.StripPackingInstance("test", strip_height=height, items=items)
    config = spyrrow.StripPackingConfig(
        total_computation_time=5, num_workers=2, seed=seed
    )
    return instance.solve(config)


def is_multiple(angle, step, tol=1e-2):
    r = angle % step
    return min(r, step - r) < tol


@pytest.mark.parametrize("step", [90.0, 45.0])
def test_step_rotations(step):
    item = spyrrow.Item("r", SQUARE, 5, None, rotation_step=step)
    assert item.allowed_orientations is None
    assert item.rotation_step == step
    sol = solve([item])
    assert len(sol.placed_items) == 5
    assert all(is_multiple(p.rotation, step) for p in sol.placed_items)


def test_step_360_means_no_rotation():
    item = spyrrow.Item("r", SQUARE, 3, None, 360.0)
    sol = solve([item])
    assert all(is_multiple(p.rotation, 360.0) for p in sol.placed_items)


def test_step_uses_rotation_when_useful():
    # A long bar in a strip too low for it flat: only the 90 degrees rotation fits
    bar = spyrrow.Item("bar", [(0, 0), (5, 0), (5, 1), (0, 1)], 2, None, rotation_step=90.0)
    sol = solve([bar], height=5.01)
    assert len(sol.placed_items) == 2
    assert all(is_multiple(p.rotation, 90.0) for p in sol.placed_items)


@pytest.mark.parametrize(
    "bad",
    [0.0, -90.0, 361.0, 100.0, 7.0, float("nan"), float("inf"), float("-inf"), 1e-6],
)
def test_invalid_step_raises(bad):
    with pytest.raises(ValueError):
        spyrrow.Item("r", SQUARE, 1, None, rotation_step=bad)


@pytest.mark.parametrize("orientations", [[0.0, 90.0], []])
def test_conflict_raises(orientations):
    with pytest.raises(ValueError):
        spyrrow.Item("r", SQUARE, 1, orientations, rotation_step=90.0)


def test_valid_non_integer_steps():
    for step in [0.5, 1.5, 22.5, 120.0, 180.0, 360.0 / 7.0]:
        spyrrow.Item("r", SQUARE, 1, None, rotation_step=step)


def test_invalid_set_after_construction_raises_at_solve():
    item = spyrrow.Item("r", SQUARE, 1, None, rotation_step=90.0)
    item.rotation_step = 100.0
    with pytest.raises(ValueError):
        solve([item])
    item.rotation_step = 90.0
    item.allowed_orientations = [0.0]
    with pytest.raises(ValueError):
        solve([item])


def test_attribute_and_repr():
    item = spyrrow.Item("r", SQUARE, 1, None)
    assert item.rotation_step is None
    assert "rotation_step" not in repr(item)
    item.rotation_step = 30.0
    assert item.rotation_step == 30.0
    assert "rotation_step=30.0" in repr(item)


def test_json_unchanged_without_step():
    item = spyrrow.Item("r", SQUARE, 2, allowed_orientations=[0, 90])
    assert item.to_json_str() == (
        '{"id":"r","demand":2,"allowed_orientations":[0.0,90.0],'
        '"shape":[[0.0,0.0],[2.0,0.0],[2.0,1.0],[0.0,1.0]]}'
    )
    stepped = spyrrow.Item("r", SQUARE, 2, None, rotation_step=90.0)
    assert json.loads(stepped.to_json_str())["rotation_step"] == 90.0


def test_deepcopy_keeps_step():
    import copy

    item = spyrrow.Item("r", SQUARE, 1, None, rotation_step=45.0)
    assert copy.deepcopy(item).rotation_step == 45.0


def test_allowed_orientations_still_required():
    # same contract as spyrrow 0.10: allowed_orientations has no default
    with pytest.raises(TypeError):
        spyrrow.Item("x", [(0, 0), (1, 0), (1, 1)], 1)
