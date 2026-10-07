"""Stub of the native module. Private: use the ``spyrrow`` package."""

from typing import Any, Callable

__version__: str

def sparrow_defaults() -> str: ...
def validate(instance_json: str, config_json: str) -> str: ...
def solve(
    instance_json: str,
    config_json: str,
    initial_solution_json: str | None = None,
    callback: Callable[[str, float, Any], bool] | None = None,
    event_mask: int = 0,
) -> str: ...

# The frozen 0.x classes, re-exported with their historical names by spyrrow.v0
V0Item: Any
V0PlacedItem: Any
V0StripPackingInstance: Any
V0StripPackingConfig: Any
V0StripPackingSolution: Any
V0ReportType: Any
V0ProgressQueue: Any
