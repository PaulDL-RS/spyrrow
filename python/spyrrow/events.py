"""Progress events delivered to the ``on_event`` callback of ``StripPackingInstance.solve``.

They mirror sparrow's ``SolutionListener``: ``report_phase`` -> :class:`PhaseStarted`,
``report`` (``ReportType``) -> :class:`SolutionReported` (:class:`ReportKind`),
``report_separation_progress`` -> :class:`SeparationProgress`, ``report_separation_result`` ->
:class:`SeparationFinished`, ``report_compression_progress`` -> :class:`CompressionStep`.

``elapsed`` is the time in seconds since the start of ``solve``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from .model import StripPackingSolution

__all__ = [
    "Phase",
    "ReportKind",
    "PhaseStarted",
    "SolutionReported",
    "SeparationProgress",
    "SeparationFinished",
    "CompressionStep",
    "Event",
    "DEFAULT_EVENTS",
]


class Phase(enum.Enum):
    """sparrow ``OptimizationPhase``."""

    EXPLORATION = "exploration"
    COMPRESSION = "compression"


class ReportKind(enum.Enum):
    """sparrow ``ReportType``."""

    EXPLORATION_FEASIBLE = "expl_feas"
    """A feasible solution reached by the exploration phase."""
    EXPLORATION_INFEASIBLE = "expl_infeas"
    """An infeasible solution reached by the exploration phase."""
    EXPLORATION_IMPROVING = "expl_improving"
    """An (infeasible) intermediate solution closer to feasibility than the previous one."""
    COMPRESSION_FEASIBLE = "cmpr_feas"
    """A feasible solution found by the compression phase."""
    FINAL = "final"
    """The final solution."""

    @property
    def feasible(self) -> bool:
        return self in (ReportKind.EXPLORATION_FEASIBLE, ReportKind.COMPRESSION_FEASIBLE, ReportKind.FINAL)

    @property
    def phase(self) -> Phase | None:
        """The phase that produced the report (``None`` for ``FINAL``)."""
        if self is ReportKind.FINAL:
            return None
        if self is ReportKind.COMPRESSION_FEASIBLE:
            return Phase.COMPRESSION
        return Phase.EXPLORATION


@dataclass(frozen=True, slots=True)
class PhaseStarted:
    phase: Phase
    elapsed: float


@dataclass(frozen=True, slots=True)
class SolutionReported:
    """A solution reported by the solver. ``solution.feasible`` is ``kind.feasible``."""

    kind: ReportKind
    solution: StripPackingSolution
    elapsed: float

    @property
    def feasible(self) -> bool:
        return self.kind.feasible


@dataclass(frozen=True, slots=True)
class SeparationProgress:
    """Progress inside one separation call. Iteration 0 describes the initial layout. Frequent."""

    strip_width: float
    density: float
    iteration: int
    min_loss: float
    elapsed: float


@dataclass(frozen=True, slots=True)
class SeparationFinished:
    """Result of one separation call (sparrow ``SeparationResult``). ``duration`` is sparrow's ``elapsed_seconds``."""

    success: bool
    duration: float
    total_evals: int
    total_moves: int
    iterations: int
    elapsed: float


@dataclass(frozen=True, slots=True)
class CompressionStep:
    """The compression phase attempts a new shrink step (ratio of the strip width)."""

    shrink_step: float
    elapsed: float


Event = Union[PhaseStarted, SolutionReported, SeparationProgress, SeparationFinished, CompressionStep]

DEFAULT_EVENTS: tuple[type, ...] = (PhaseStarted, SolutionReported, CompressionStep)
"""Event classes delivered when ``events`` is not given (the per-iteration separation events are opt-in)."""
