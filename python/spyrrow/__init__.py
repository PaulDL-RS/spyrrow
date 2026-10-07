"""spyrrow: Python wrapper of the sparrow 2D irregular strip packing solver.

The 1.0 API lives here. The spyrrow 0.x API is available, frozen and deprecated, as
``spyrrow.v0``: ``import spyrrow.v0 as spyrrow``.
"""

from __future__ import annotations

import importlib
import json
from importlib import metadata as _metadata
from pathlib import Path
from typing import Any

from . import _core, errors, events
from .config import Preset, SolverConfig
from .errors import (
    InvalidConfigError,
    InvalidInstanceError,
    InvalidSolutionError,
    SolveInterrupted,
    SolverError,
    SpyrrowError,
    StopSolving,
)
from .model import Item, PlacedItem, Rotation, StripPackingInstance, StripPackingSolution

try:
    __version__ = _metadata.version("spyrrow")
except _metadata.PackageNotFoundError:  # pragma: no cover - not installed
    __version__ = _core.__version__

__all__ = [
    "Item",
    "Rotation",
    "StripPackingInstance",
    "StripPackingSolution",
    "PlacedItem",
    "SolverConfig",
    "Preset",
    "read_json",
    "write_json",
    "errors",
    "events",
    "SpyrrowError",
    "InvalidInstanceError",
    "InvalidConfigError",
    "InvalidSolutionError",
    "SolverError",
    "SolveInterrupted",
    "StopSolving",
    "__version__",
]


def read_json(path: str | Path) -> tuple[StripPackingInstance, StripPackingSolution | None]:
    """Read a sparrow JSON file: an instance, or a sparrow output (instance + solution).

    Returns:
        the instance and the solution it contains (``None`` for a bare instance)
    """
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    instance = StripPackingInstance.from_dict(data)
    solution = StripPackingSolution.from_dict(data, instance) if "solution" in data else None
    return instance, solution


def write_json(path: str | Path, instance: StripPackingInstance, solution: StripPackingSolution | None = None) -> None:
    """Write the instance (and the solution, if given) in the sparrow JSON format.

    The result can be passed to the sparrow CLI (``-i``), also as a warm start when it holds a solution.
    """
    text = solution.to_json_str(instance) if solution is not None else instance.to_json_str()
    Path(path).write_text(text, encoding="utf-8")


_REMOVED = {
    "StripPackingConfig": "spyrrow.SolverConfig",
    "ProgressQueue": "the `on_event` callback of StripPackingInstance.solve and spyrrow.events",
    "ReportType": "spyrrow.events.ReportKind",
}


def __getattr__(name: str) -> Any:
    if name == "v0":
        return importlib.import_module("spyrrow.v0")
    if name in _REMOVED:
        raise AttributeError(
            f"spyrrow.{name} was removed in spyrrow 1.0, use {_REMOVED[name]} instead. "
            "See MIGRATION.md, or keep the old API with `import spyrrow.v0 as spyrrow`."
        )
    raise AttributeError(f"module 'spyrrow' has no attribute {name!r}")
