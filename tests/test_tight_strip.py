import math

import pytest
import spyrrow


def ellipse_like(n):
    """A smooth part with many vertices, the kind polygon simplification works on."""
    pts = [
        (120 * (1 + math.cos(t)), 40 * (1 + math.sin(t)) ** 1.1)
        for t in (2 * math.pi * k / n for k in range(n))
    ]
    return pts + [pts[0]]


@pytest.mark.parametrize("separation", [None, 3.0])
def test_part_with_fixed_orientation_fits_a_strip_barely_taller_than_it(separation):
    # Before jagua-rs 1.1, simplification could make a part taller than it is
    # (JeroenGar/sparrow#176): a fixed-orientation part was then refused by a strip
    # 0.01 taller than it, and spyrrow could not even build an initial solution.
    shape = ellipse_like(200)
    height = max(y for _, y in shape) - min(y for _, y in shape)
    sep = separation or 0.0
    item = spyrrow.Item("part", shape, demand=3, allowed_orientations=[0])
    instance = spyrrow.StripPackingInstance(
        "tight", strip_height=height + 2 * sep + 1e-3, items=[item]
    )
    config = spyrrow.StripPackingConfig(
        total_computation_time=2, num_workers=1, seed=0, min_items_separation=separation
    )
    sol = instance.solve(config)
    assert len(sol.placed_items) == 3
