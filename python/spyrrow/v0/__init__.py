"""The spyrrow 0.x API, frozen, as it was in spyrrow 0.10.

Deprecated: it will be removed in spyrrow 2.0. Migrate to the 1.0 API (see MIGRATION.md).
The classes are implemented natively (``src/v0.rs``) and behave exactly as in 0.10.
"""

import warnings as _warnings

from spyrrow import _core

_warnings.warn(
    "spyrrow.v0 is the deprecated spyrrow 0.x API and will be removed in spyrrow 2.0. "
    "Migrate to the 1.0 API, see MIGRATION.md.",
    DeprecationWarning,
    stacklevel=2,
)

Item = _core.V0Item
PlacedItem = _core.V0PlacedItem
StripPackingInstance = _core.V0StripPackingInstance
StripPackingConfig = _core.V0StripPackingConfig
StripPackingSolution = _core.V0StripPackingSolution
ReportType = _core.V0ReportType
ProgressQueue = _core.V0ProgressQueue

__version__ = _core.__version__

__all__ = [
    "Item",
    "PlacedItem",
    "StripPackingInstance",
    "StripPackingConfig",
    "StripPackingSolution",
    "ReportType",
    "ProgressQueue",
]
