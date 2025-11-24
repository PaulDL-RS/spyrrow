import spyrrow
from copy import deepcopy


def test_item_deepcopy():
    item1 = spyrrow.Item("toto", [(1, 2), (2, 3), (2, 2)], 1, allowed_orientations=None)
    item2 = deepcopy(item1)
    item1.demand = 2

    assert item2.id == item1.id
    assert item2.shape == item1.shape
    assert item2.allowed_orientations == item1.allowed_orientations
    assert item2.demand == 1


def test_config_deepcopy():
    config = spyrrow.StripPackingConfig(
        early_termination=False, total_computation_time=60, num_wokers=3, seed=0
    )
    config2 = deepcopy(config)
    config.early_termination = True
    assert not config2.early_termination
    assert config.compression_time == config2.compression_time
    assert config.exploration_time == config2.exploration_time
    assert config.num_workers == config2.num_workers
    assert config.seed == config2.seed

def test_instance_deepcopy():
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
    instance_copy = deepcopy(instance)
    instance.items[0].demand = 15
    assert instance_copy.items[0].demand == 4

def test_solution_deepcopy():
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
    config = spyrrow.StripPackingConfig(early_termination=True,total_computation_time=10,num_wokers=3,seed=0)
    sol = instance.solve(config)
    sol2 = deepcopy(sol)
    assert sol2



