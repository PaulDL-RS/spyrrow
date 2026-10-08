from typing import TYPE_CHECKING
import json

if TYPE_CHECKING:
    from spyrrow import StripPackingInstance

def convert_to_sparrow_json_instance(instance:"StripPackingInstance")->dict:
    """Sparrow (jagua-rs >= 1.0) JSON instance, as a dict. Thin wrapper around `StripPackingInstance.to_sparrow_json_str`"""
    return json.loads(instance.to_sparrow_json_str())
