import spyrrow
import pytest
import math

from validity import assert_valid_solution

# Quality tests stop on a budget of evaluations rather than on time: with a fixed seed and number of workers,
# they do the same work and reach the same width on any machine, however fast or loaded.
# The time limit is only a safety net.
QUALITY_BUDGET = 5_000_000


def quality_config(early_termination: bool = True, max_evaluations: int = QUALITY_BUDGET) -> spyrrow.StripPackingConfig:
    return spyrrow.StripPackingConfig(
        early_termination=early_termination,
        total_computation_time=3600,
        num_workers=2,
        seed=0,
        max_evaluations=max_evaluations,
    )

@pytest.mark.quality
def test_basic():
    rectangle1 = spyrrow.Item(
        "rectangle", [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=[0]
    )
    triangle1 = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=6,
        allowed_orientations=[0, 90, 180, -90],
    )

    instance = spyrrow.StripPackingInstance(
        "test", strip_height=2.001, items=[rectangle1, triangle1]
    )
    config = quality_config(early_termination=False)
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    assert sol.width == pytest.approx(4,rel=0.05)

@pytest.mark.quality
def test_early_termination():
    rectangle1 = spyrrow.Item(
        "rectangle", [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=[0]
    )
    triangle1 = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=6,
        allowed_orientations=[0, 90, 180, -90],
    )

    instance = spyrrow.StripPackingInstance(
        "test", strip_height=2.001, items=[rectangle1, triangle1]
    )
    config = quality_config()
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    assert sol.width == pytest.approx(4,rel=0.05)

def test_zero_demand():
    with pytest.raises(ValueError):
        triangle1 = spyrrow.Item(
            "triangle",
            [(0, 0), (1, 0), (1, 1), (0, 0)],
            demand=0,
            allowed_orientations=[0, 90, 180, -90],
        )

        instance = spyrrow.StripPackingInstance(
            "test", strip_height=2.001, items=[triangle1]
        )
        config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=60,num_workers=3,seed=0)
        sol = instance.solve(config)
        assert sol.width == pytest.approx(1,rel=0.05)

def test_no_items():
    instance = spyrrow.StripPackingInstance(
            "test", strip_height=2.001, items=[]
        )
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=60,num_workers=3,seed=0)
    sol = instance.solve(config)
    assert sol.width == 0
    assert sol.density == 0
    assert not sol.placed_items

@pytest.mark.quality
def test_one_item():
    triangle1 = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1)],
        demand=3,
        allowed_orientations=[0, 90, 180, 270],
    )

    instance = spyrrow.StripPackingInstance(
        "test", strip_height=2.001, items=[triangle1]
    )
    config = quality_config()
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    assert sol.width == pytest.approx(1,rel=0.05)

@pytest.mark.quality
def test_one_demand():
    triangle1 = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=1,
        allowed_orientations=[0, 45, 90, 135,180,-45, -90, -135],
    )

    instance = spyrrow.StripPackingInstance(
        "test", strip_height=2.001, items=[triangle1]
    )
    config = quality_config()
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    assert sol.width == pytest.approx(math.cos(math.radians(45)),rel=0.05)



@pytest.mark.quality
def test_2_consecutive_calls():
    # Test corresponding to crash on the second consecutive call of solve method
    rectangle1 = spyrrow.Item(
        "rectangle", [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=[0]
    )
    triangle1 = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=6,
        allowed_orientations=[0, 90, 180, -90],
    )

    instance = spyrrow.StripPackingInstance(
        "test", strip_height=2.001, items=[rectangle1, triangle1]
    )
    config = quality_config(max_evaluations=1_000_000)
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    config = quality_config()
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    assert sol.width == pytest.approx(4,rel=0.05)

def test_concave_polygons():
    poly1 = spyrrow.Item("0",[(0, 0), (3, 0), (4, 1), (3, 2), (0, 2), (1, 1), (0, 0)],demand=2,allowed_orientations=[0,90,180,270])
    poly2 = spyrrow.Item("1",[(0, 0), (1, 0), (1, 2), (3, 2), (3, 0), (4, 0), (4, 3), (0, 3), (0, 0)], demand=3, allowed_orientations=[0,90,180,270])
    instance = spyrrow.StripPackingInstance(
        "test", strip_height=4.001, items=[poly1, poly2]
    )
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=30,seed=0)
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    assert sol.width

@pytest.mark.quality
def test_continuous_rotation():
    rectangle1 = spyrrow.Item(
        "rectangle", [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=None
    )
    triangle1 = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=6,
        allowed_orientations=None,
    )

    instance = spyrrow.StripPackingInstance(
        "test", strip_height=2.001, items=[rectangle1, triangle1]
    )
    config = quality_config()
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    print(sol.width)
    assert sol.width >= 3.5
    assert sol.width < 4

def test_empty_orientations_means_no_rotation():
    triangle1 = spyrrow.Item("triangle", [(0, 0), (1, 0), (1, 1), (0, 0)], demand=6, allowed_orientations=[])
    instance = spyrrow.StripPackingInstance("test", strip_height=2.001, items=[triangle1])
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=10,seed=0)
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    assert all(pi.rotation == pytest.approx(0) for pi in sol.placed_items)

def test_discrete_orientations_are_respected():
    triangle1 = spyrrow.Item("triangle", [(0, 0), (1, 0), (1, 1), (0, 0)], demand=6, allowed_orientations=[0, 90, 180, -90])
    instance = spyrrow.StripPackingInstance("test", strip_height=2.001, items=[triangle1])
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=10,seed=0)
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    for pi in sol.placed_items:
        # angles are returned modulo 360
        assert any(math.isclose((pi.rotation - a) % 360, 0, abs_tol=1e-3) or math.isclose((pi.rotation - a) % 360, 360, abs_tol=1e-3) for a in [0, 90, 180, -90])

def test_min_items_separation():
    rectangle1 = spyrrow.Item("rectangle", [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=[0])
    instance = spyrrow.StripPackingInstance("test", strip_height=2.5, items=[rectangle1])
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=10,min_items_separation=0.2,seed=0)
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    # 2 columns of 2 squares, with a gap of at least 0.2 between and around them
    assert sol.width >= 2.4 - 1e-3

def test_impossible_separation_raises():
    rectangle1 = spyrrow.Item("rectangle", [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=[0])
    instance = spyrrow.StripPackingInstance("test", strip_height=2.0, items=[rectangle1])
    config = spyrrow.StripPackingConfig(total_computation_time=10,min_items_separation=5.0,seed=0)
    with pytest.raises(ValueError):
        instance.solve(config)

if __name__ == '__main__':
    test_continuous_rotation()