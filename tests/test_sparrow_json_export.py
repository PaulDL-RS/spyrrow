import json
import os
import subprocess

import pytest
import spyrrow

from utils import convert_to_sparrow_json_instance


def make_instance():
    rectangle = spyrrow.Item(
        "rectangle",
        [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
        demand=4,
        allowed_orientations=[0],
    )
    triangle = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=6,
        allowed_orientations=[0, 90, 180, -90],
    )
    free = spyrrow.Item(
        "free", [(0, 0), (1, 0), (0, 1)], demand=1, allowed_orientations=None
    )
    return spyrrow.StripPackingInstance(
        "export", strip_height=2.001, items=[rectangle, triangle, free]
    )


def make_config(**kwargs):
    return spyrrow.StripPackingConfig(
        total_computation_time=3, num_workers=2, seed=0, **kwargs
    )


@pytest.fixture(scope="module")
def solved():
    instance = make_instance()
    return instance, instance.solve(make_config())


def test_instance_structure():
    data = json.loads(make_instance().to_sparrow_json_str())
    assert set(data) == {"name", "min_item_separation", "items", "strip_height"}
    assert data["name"] == "export"
    assert data["min_item_separation"] == 0.0
    assert data["strip_height"] == pytest.approx(2.001)
    assert [i["id"] for i in data["items"]] == [0, 1, 2]
    assert [i["demand"] for i in data["items"]] == [4, 6, 1]
    first = data["items"][0]
    assert first["shape"]["type"] == "simple_polygon"
    assert first["orientation"]["rotation"] == {"mode": "discrete", "angles": [0.0]}
    assert data["items"][2]["orientation"]["rotation"] == {"mode": "continuous"}
    assert "solution" not in data


def test_separation_from_config():
    instance = make_instance()
    data = json.loads(
        instance.to_sparrow_json_str(make_config(min_items_separation=0.25))
    )
    assert data["min_item_separation"] == pytest.approx(0.25)
    data = json.loads(instance.to_sparrow_json_str(make_config()))
    assert data["min_item_separation"] == 0.0


def test_instance_with_solution(solved):
    instance, solution = solved
    data = json.loads(instance.to_sparrow_json_str(solution=solution))
    assert data == {**json.loads(instance.to_sparrow_json_str()), "solution": data["solution"]}
    sol = data["solution"]
    assert sol["strip_width"] == pytest.approx(solution.width)
    placed = sol["layout"]["placed_items"]
    assert len(placed) == 11
    index = {item.id: idx for idx, item in enumerate(instance.items)}
    assert [p["item_id"] for p in placed] == [index[p.id] for p in solution.placed_items]
    for p, spy in zip(placed, solution.placed_items):
        assert p["transformation"]["rotation"] == pytest.approx(spy.rotation)
        assert tuple(p["transformation"]["translation"]) == pytest.approx(spy.translation)
        assert not p["transformation"].get("reflected", False)


def test_unknown_id_in_solution(solved):
    _, solution = solved
    other = spyrrow.StripPackingInstance(
        "other",
        strip_height=2.0,
        items=[spyrrow.Item("a", [(0, 0), (1, 0), (1, 1)], 1, [0])],
    )
    with pytest.raises(ValueError):
        other.to_sparrow_json_str(solution=solution)


def test_utils_wrapper():
    instance = make_instance()
    assert convert_to_sparrow_json_instance(instance) == json.loads(
        instance.to_sparrow_json_str()
    )


def test_solution_to_json_str(solved):
    _, solution = solved
    data = json.loads(solution.to_json_str())
    assert set(data) == {"width", "placed_items", "density"}
    assert data["width"] == pytest.approx(solution.width)
    assert data["density"] == pytest.approx(solution.density)
    assert len(data["placed_items"]) == len(solution.placed_items)
    first = data["placed_items"][0]
    assert set(first) == {"id", "translation", "rotation"}
    assert first["id"] == solution.placed_items[0].id


SPARROW_BIN = os.environ.get("SPARROW_BIN")


@pytest.mark.skipif(not SPARROW_BIN, reason="SPARROW_BIN is not set")
@pytest.mark.parametrize("with_solution", [False, True])
def test_sparrow_cli_accepts_export(tmp_path, solved, with_solution):
    instance, solution = solved
    input_path = tmp_path / "input.json"
    # The solution was computed without separation: exporting it with a separation would make
    # it infeasible, and sparrow's separator then ignores the time limit for a long time.
    config = make_config() if with_solution else make_config(min_items_separation=0.01)
    input_path.write_text(
        instance.to_sparrow_json_str(config, solution if with_solution else None)
    )
    # sparrow writes its results in ./output, so run it in a scratch directory
    result = subprocess.run(
        [SPARROW_BIN, "-i", str(input_path), "-t", "2", "-s", "0", "--workers", "2"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads((tmp_path / "output" / "final_export.json").read_text())
    assert output["name"] == "export"
    assert len(output["solution"]["layout"]["placed_items"]) == 11
    if with_solution:
        assert "warm starting" in result.stdout + result.stderr
        assert output["solution"]["strip_width"] <= solution.width * 1.001
