from typing import TYPE_CHECKING
import json

if TYPE_CHECKING:
    from spyrrow import StripPackingInstance

def convert_to_sparrow_json_instance(instance:"StripPackingInstance")->dict:
    json_str = instance.to_json_str()
    data_object = json.loads(json_str)
    for idx, item in enumerate(data_object["items"]):
        item["id"] = idx
        points = item["shape"]
        item["shape"] = {"type":"simple_polygon","data":points}
        item["orientation"] = {"rotation": to_sparrow_rotation(item.pop("allowed_orientations"))}
    return data_object


def to_sparrow_rotation(allowed_orientations: list[float] | None) -> dict:
    """Mirror of spyrrow's mapping onto jagua-rs >= 1.0 rotation modes"""
    if allowed_orientations is None:
        return {"mode": "continuous"}
    return {"mode": "discrete", "angles": allowed_orientations or [0.0]}