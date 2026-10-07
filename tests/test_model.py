"""Pure Python tests of the 1.0 value objects (no solver run)."""

import copy
import dataclasses
import math
import pickle

import pytest

import spyrrow
from spyrrow import Item, PlacedItem, Rotation, StripPackingInstance, StripPackingSolution
from spyrrow.errors import InvalidInstanceError

SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]
TRIANGLE = [(0, 0), (1, 0), (1, 1)]


# --- Rotation ---------------------------------------------------------------------------------


def test_rotation_constructors():
    assert Rotation.none() == Rotation.discrete([0])
    assert Rotation.discrete([0, 90]).angles == (0.0, 90.0)
    assert Rotation.stepped(90).expand() == (0.0, 90.0, 180.0, 270.0)
    assert Rotation.continuous().expand() is None
    assert Rotation.stepped(0.1).mode == "stepped"


@pytest.mark.parametrize("step", [0, -1, 7, 361, float("nan"), float("inf")])
def test_rotation_invalid_step(step):
    with pytest.raises(InvalidInstanceError):
        Rotation.stepped(step)


def test_rotation_invalid_discrete():
    with pytest.raises(InvalidInstanceError):
        Rotation.discrete([])
    with pytest.raises(InvalidInstanceError):
        Rotation.discrete([float("nan")])


def test_rotation_from_allowed_orientations():
    assert Rotation.from_allowed_orientations(None) == Rotation.continuous()
    assert Rotation.from_allowed_orientations([]) == Rotation.none()
    assert Rotation.from_allowed_orientations([0, 90]) == Rotation.discrete([0, 90])


# --- Item -------------------------------------------------------------------------------------


def test_item_defaults():
    item = Item("a", SQUARE)
    assert item.demand == 1
    assert item.rotation == Rotation.none()
    assert item.reflection_axes == ()
    assert item.area == pytest.approx(1.0)


def test_item_rotation_shorthand_and_closing_point():
    item = Item(3, SQUARE + [(0, 0)], 2, rotation=[0, 180])
    assert item.rotation == Rotation.discrete([0, 180])
    assert item.area == pytest.approx(1.0)


def test_item_is_frozen_hashable_and_replaceable():
    item = Item("a", SQUARE, 2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.demand = 3  # type: ignore[misc]
    assert dataclasses.replace(item, demand=3).demand == 3
    assert hash(item) == hash(Item("a", SQUARE, 2))
    assert copy.deepcopy(item) == item
    assert pickle.loads(pickle.dumps(item)) == item


def test_item_rotation_none_is_rejected_with_hint():
    with pytest.raises(InvalidInstanceError, match="Rotation.continuous"):
        Item("a", SQUARE, rotation=None)  # type: ignore[arg-type]


def test_item_allowed_orientations_keyword_is_gone():
    with pytest.raises(TypeError):
        Item("a", SQUARE, 1, allowed_orientations=[0])  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(id=-1, shape=SQUARE),
        dict(id=1.5, shape=SQUARE),
        dict(id=True, shape=SQUARE),
        dict(id="a", shape=SQUARE, demand=0),
        dict(id="a", shape=SQUARE, demand=1.5),
        dict(id="a", shape=[(0, 0), (1, 1)]),
        dict(id="a", shape=[(0, 0), (1, 1), (2, 2)]),
        dict(id="a", shape=[(0, 0), (1, 0), (float("nan"), 1)]),
        dict(id="a", shape=SQUARE, reflection_axes=[float("inf")]),
    ],
)
def test_item_validation(kwargs):
    with pytest.raises(InvalidInstanceError):
        Item(**kwargs)


def test_item_errors_are_value_errors():
    with pytest.raises(ValueError):
        Item("a", SQUARE, 0)


def test_item_min_height():
    # unit square: 1 at 0 degrees, sqrt(2) at 45 degrees
    assert Item("a", SQUARE).min_height() == pytest.approx(1.0)
    assert Item("a", SQUARE, rotation=[45]).min_height() == pytest.approx(math.sqrt(2))
    # right triangle with legs 1: minimum width is the altitude on the hypotenuse
    assert Item("t", TRIANGLE, rotation=Rotation.continuous()).min_height() == pytest.approx(math.sqrt(2) / 2)
    # 3 x 1 rectangle: 1 with free rotation, 3 when it cannot rotate by 90
    rect = [(0, 0), (3, 0), (3, 1), (0, 1)]
    assert Item("r", rect).min_height() == pytest.approx(1.0)
    assert Item("r", rect, rotation=[90]).min_height() == pytest.approx(3.0)


# --- Instance ---------------------------------------------------------------------------------


def make_instance(**kwargs):
    items = [Item("sq", SQUARE, 4), Item("tri", TRIANGLE, 6, rotation=Rotation.stepped(90), reflection_axes=[0])]
    return StripPackingInstance(2.001, items, **kwargs)


def test_instance_basics():
    inst = make_instance(name="n", min_item_separation=0.1)
    assert inst.name == "n"
    assert inst.min_item_separation == pytest.approx(0.1)
    assert inst.total_demand == 10
    assert inst.total_item_area == pytest.approx(4 + 3)
    assert isinstance(inst.items, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        inst.strip_height = 3  # type: ignore[misc]


def test_instance_keyword_call_of_0x_still_works():
    inst = StripPackingInstance(name="test", strip_height=2.001, items=[Item("a", SQUARE)])
    assert inst.name == "test"


def test_instance_0x_positional_signature_gives_a_hint():
    with pytest.raises(TypeError):  # three positional arguments
        StripPackingInstance("test", 2.001, [Item("a", SQUARE)])  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="0.x"):  # the name is taken for the height
        StripPackingInstance("test", [Item("a", SQUARE)])  # type: ignore[arg-type]


def test_instance_duplicate_ids():
    with pytest.raises(InvalidInstanceError, match="unique"):
        StripPackingInstance(2.0, [Item("a", SQUARE), Item("a", TRIANGLE)])


@pytest.mark.parametrize("height", [0, -1, float("nan")])
def test_instance_invalid_height(height):
    with pytest.raises(InvalidInstanceError):
        StripPackingInstance(height, [Item("a", SQUARE)])


def test_instance_item_too_big_for_strip():
    with pytest.raises(InvalidInstanceError, match="'big'"):
        StripPackingInstance(1.0, [Item("big", [(0, 0), (3, 0), (3, 2), (0, 2)])])
    # fits only if it can rotate
    rect = [(0, 0), (3, 0), (3, 1), (0, 1)]
    with pytest.raises(InvalidInstanceError):
        StripPackingInstance(1.5, [Item("r", rect, rotation=[90])])
    StripPackingInstance(1.5, [Item("r", rect, rotation=[0, 90])])
    StripPackingInstance(1.5, [Item("r", rect, rotation=Rotation.continuous())])
    # reflecting across a 45 degrees axis turns the 90 degrees orientation into 180 degrees (height 1)
    StripPackingInstance(1.5, [Item("r", rect, rotation=[90], reflection_axes=[45])])
    with pytest.raises(InvalidInstanceError):
        StripPackingInstance(1.5, [Item("r", rect, rotation=[90], reflection_axes=[90])])


def test_instance_separation_larger_than_strip():
    with pytest.raises(InvalidInstanceError):
        StripPackingInstance(2.0, [Item("a", SQUARE)], min_item_separation=5.0)
    with pytest.raises(InvalidInstanceError):
        StripPackingInstance(2.0, [Item("a", SQUARE)], min_item_separation=1.5)


def test_empty_instance_is_allowed():
    inst = StripPackingInstance(2.0, [])
    assert inst.total_demand == 0


# --- JSON -------------------------------------------------------------------------------------


def test_instance_json_is_the_sparrow_format():
    data = make_instance(min_item_separation=0.5).to_dict()
    assert data["strip_height"] == 2.001
    assert data["min_item_separation"] == 0.5
    tri = data["items"][1]
    assert tri["id"] == 1  # string ids are replaced by positions ...
    assert tri["label"] == "tri"  # ... and kept as labels
    assert tri["orientation"] == {"rotation": {"mode": "stepped", "step": 90.0}, "reflection_axes": [0.0]}
    assert tri["shape"] == {"type": "simple_polygon", "data": [list(map(float, p)) for p in TRIANGLE]}
    assert data["items"][0]["orientation"] == {"rotation": {"mode": "discrete", "angles": [0.0]}}


def test_integer_ids_are_written_verbatim():
    inst = StripPackingInstance(2.0, [Item(7, SQUARE), Item(3, TRIANGLE)])
    data = inst.to_dict()
    assert [i["id"] for i in data["items"]] == [7, 3]
    assert all("label" not in i for i in data["items"])


@pytest.mark.parametrize("ids", [("a", "b"), (7, 3), ("a", 5)])
def test_instance_json_round_trip(ids):
    items = [
        Item(ids[0], SQUARE, 2, rotation=Rotation.continuous()),
        Item(ids[1], TRIANGLE, 3, rotation=[0, 90], reflection_axes=[0, 90]),
    ]
    inst = StripPackingInstance(2.5, items, name="rt", min_item_separation=0.1)
    again = StripPackingInstance.from_json_str(inst.to_json_str())
    assert again == inst


def test_read_write_json(tmp_path):
    inst = make_instance(name="file")
    path = tmp_path / "instance.json"
    spyrrow.write_json(path, inst)
    instance, solution = spyrrow.read_json(path)
    assert instance == inst
    assert solution is None

    sol = StripPackingSolution(
        width=4.0,
        density=0.5,
        placed_items=(PlacedItem("sq", (0.5, 0.5), 0.0), PlacedItem("tri", (1.0, 1.0), 90.0, True)),
        strip_height=2.001,
    )
    spyrrow.write_json(path, inst, sol)
    instance2, solution2 = spyrrow.read_json(path)
    assert instance2 == inst
    assert solution2 is not None
    assert solution2.placed_items == sol.placed_items
    assert solution2.width == 4.0


def test_solution_dict_follows_jagua_format():
    inst = make_instance()
    sol = StripPackingSolution(
        width=4.0, density=0.5, placed_items=(PlacedItem("tri", (1.0, 2.0), 90.0, True),), strip_height=2.001
    )
    d = sol.to_dict(inst)
    assert d["strip_width"] == 4.0
    assert d["layout"]["placed_items"] == [
        {"item_id": 1, "transformation": {"rotation": 90.0, "translation": [1.0, 2.0], "reflected": True}}
    ]
    with pytest.raises(spyrrow.InvalidSolutionError):
        sol.to_dict()  # string ids need the instance


# --- PlacedItem -------------------------------------------------------------------------------


def test_placed_item_transform():
    p = PlacedItem("a", (10.0, 20.0), 90.0, False)
    out = p.transform([(1, 0), (0, 1)])
    assert out[0] == pytest.approx((10.0, 21.0))
    assert out[1] == pytest.approx((9.0, 20.0))
    # reflection (y -> -y) happens before the rotation
    r = PlacedItem("a", (0.0, 0.0), 90.0, True)
    assert r.transform([(1, 2)])[0] == pytest.approx((2.0, 1.0))
    assert PlacedItem("a", (1.0, 1.0), 0.0, True).transform([(3, 4)])[0] == pytest.approx((4.0, -3.0))


def test_removed_0x_names_explain_themselves():
    for name in ("StripPackingConfig", "ProgressQueue", "ReportType"):
        with pytest.raises(AttributeError, match="spyrrow.v0"):
            getattr(spyrrow, name)
    with pytest.raises(AttributeError):
        spyrrow.does_not_exist


def test_exact_fit_is_rejected_early():
    # sparrow cannot build an initial layout when an item is exactly as high as the strip
    with pytest.raises(InvalidInstanceError, match="strictly"):
        StripPackingInstance(1.0, [Item("a", SQUARE)])
    StripPackingInstance(1.001, [Item("a", SQUARE)])
