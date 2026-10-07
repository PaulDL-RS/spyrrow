"""Exceptions raised by spyrrow.

The validation errors also inherit from the builtin exception that spyrrow 0.x raised
(``ValueError`` / ``RuntimeError``), so existing ``except`` clauses keep working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import StripPackingSolution

__all__ = [
    "SpyrrowError",
    "InvalidInstanceError",
    "InvalidConfigError",
    "InvalidSolutionError",
    "SolverError",
    "SolveInterrupted",
    "StopSolving",
]


class SpyrrowError(Exception):
    """Base class of all errors raised on purpose by spyrrow."""


class InvalidInstanceError(SpyrrowError, ValueError):
    """An item or an instance is invalid (bad shape, duplicate ids, item too big for the strip, ...)."""


class InvalidConfigError(SpyrrowError, ValueError):
    """A solver configuration value is invalid."""


class InvalidSolutionError(SpyrrowError, ValueError):
    """A solution cannot be used (e.g. as a warm start) with the given instance."""


class SolverError(SpyrrowError, RuntimeError):
    """The sparrow solver itself failed (e.g. it could not build an initial layout)."""


class SolveInterrupted(KeyboardInterrupt):
    """Ctrl-C (SIGINT) was received while solving.

    Attributes:
        solution: the best feasible solution found so far
    """

    def __init__(self, solution: StripPackingSolution | None = None):
        super().__init__("solve() was interrupted")
        self.solution = solution


class StopSolving(Exception):
    """Raise it inside an ``on_event`` callback to stop the solver gracefully.

    ``solve`` then returns the best solution found so far, with ``interrupted=True``.
    """
