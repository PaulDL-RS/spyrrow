import spyrrow
import pytest

def test_basic():
    ## Continuous rotation seems to not be implemented for strip packing
    rectangle1 = spyrrow.Item(
        0, [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=[0]
    )
    triangle1 = spyrrow.Item(
        1,
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=6,
        allowed_orientations=[0, 90, 180, -90],
    )

    instance = spyrrow.StripPackingInstance(
        "test", height=2.001, items=[rectangle1, triangle1]
    )
    sol = instance.solve(30)
    assert sol.width == pytest.approx(4,rel=0.2)

def test_2_consecutive_calls():
    # Test correpsonding to crash on the second consecutive call of solve method
    rectangle1 = spyrrow.Item(
        0, [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=[0]
    )
    triangle1 = spyrrow.Item(
        1,
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=6,
        allowed_orientations=[0, 90, 180, -90],
    )

    instance = spyrrow.StripPackingInstance(
        "test", height=2.001, items=[rectangle1, triangle1]
    )
    sol = instance.solve(10)
    sol = instance.solve(30)
    assert sol.width == pytest.approx(4,rel=0.2)

def test_concave_polygons():
    poly1 = spyrrow.Item(0,[(0, 0), (3, 0), (4, 1), (3, 2), (0, 2), (1, 1), (0, 0)],demand=2,allowed_orientations=[0,90,180,270])
    poly2 = spyrrow.Item(1,[(0, 0), (1, 0), (1, 2), (3, 2), (3, 0), (4, 0), (4, 3), (0, 3), (0, 0)], demand=3, allowed_orientations=[0,90,180,270])
    instance = spyrrow.StripPackingInstance(
        "test", height=4.001, items=[poly1, poly2]
    )
    sol = instance.solve(30)