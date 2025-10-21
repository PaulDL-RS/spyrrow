import spyrrow
import pytest
import math

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
    config = spyrrow.StripPackingConfig(early_termination=False,total_computation_time=60,num_wokers=3,seed=0)
    sol = instance.solve(config)
    assert sol.width == pytest.approx(4,rel=0.05)

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
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=600,num_wokers=3,seed=0)
    sol = instance.solve(config)
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
        config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=60,num_wokers=3,seed=0)
        sol = instance.solve(config)
        assert sol.width == pytest.approx(1,rel=0.05)

def test_no_items():
    instance = spyrrow.StripPackingInstance(
            "test", strip_height=2.001, items=[]
        )
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=60,num_wokers=3,seed=0)
    sol = instance.solve(config)
    assert sol.width == 0
    assert sol.density == 0
    assert not sol.placed_items

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
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=60,num_wokers=3,seed=0)
    sol = instance.solve(config)
    assert sol.width == pytest.approx(1,rel=0.05)

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
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=60,num_wokers=3,seed=0)
    sol = instance.solve(config)
    assert sol.width == pytest.approx(math.cos(math.radians(45)),rel=0.05)



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
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=10,seed=0)
    sol = instance.solve(config)
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=30,seed=0)
    sol = instance.solve(config)
    assert sol.width == pytest.approx(4,rel=0.05)

def test_concave_polygons():
    poly1 = spyrrow.Item("0",[(0, 0), (3, 0), (4, 1), (3, 2), (0, 2), (1, 1), (0, 0)],demand=2,allowed_orientations=[0,90,180,270])
    poly2 = spyrrow.Item("1",[(0, 0), (1, 0), (1, 2), (3, 2), (3, 0), (4, 0), (4, 3), (0, 3), (0, 0)], demand=3, allowed_orientations=[0,90,180,270])
    instance = spyrrow.StripPackingInstance(
        "test", strip_height=4.001, items=[poly1, poly2]
    )
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=30,seed=0)
    sol = instance.solve(config)
    assert sol.width

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
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=90,seed=0)
    sol = instance.solve(config)
    print(sol.width)
    assert sol.width >= 3.5
    assert sol.width < 4

if __name__ == '__main__':
    test_continuous_rotation()