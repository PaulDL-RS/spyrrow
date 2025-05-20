from typing import TYPE_CHECKING
import json

if TYPE_CHECKING:
    from spyrrow import StripPackingInstance

def convert_to_sparrow_json_instance(instance:"StripPackingInstance")->dict:
    json_str = instance.to_json_str()
    data_object = json.loads(json_str)
    for item in data_object["items"]:
        points = item["shape"]
        item["shape"] = {"type":"simple_polygon","data":points}
    return data_object