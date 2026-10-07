"""Solver configuration.

``SolverConfig`` mirrors sparrow's ``SparrowConfig``. The nested classes carry the same field
names as sparrow's ``ExplorationConfig``, ``CompressionConfig``, ``SeparatorConfig``,
``SampleConfig`` and jagua-rs' ``CDEConfig``. Every default is read from the sparrow version
spyrrow was built against, not copied here.
"""

from __future__ import annotations

import enum
import json
import math
import secrets
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any, Literal

from . import _core
from .errors import InvalidConfigError

__all__ = [
    "Preset",
    "SolverConfig",
    "ExplorationConfig",
    "CompressionConfig",
    "SeparatorConfig",
    "SampleConfig",
    "ShrinkDecay",
    "CDEConfig",
    "ShapeConfig",
]

_D: dict[str, Any] = json.loads(_core.sparrow_defaults())
_EXPL: dict[str, Any] = _D["exploration"]
_CMPR: dict[str, Any] = _D["compression"]
_EARLY: dict[str, Any] = _D["early_termination"]


def _check(cond: bool, message: str) -> None:
    if not cond:
        raise InvalidConfigError(message)


def _positive_finite(value: float, name: str) -> None:
    _check(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0,
        f"{name} must be a finite number > 0, got {value!r}",
    )


def _nonneg_int(value: int, name: str, minimum: int = 0) -> None:
    _check(
        isinstance(value, int) and not isinstance(value, bool) and value >= minimum,
        f"{name} must be an integer >= {minimum}, got {value!r}",
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SampleConfig:
    """Sampling budget of a placement search (sparrow ``SampleConfig``)."""

    n_container_samples: int = _EXPL["separator"]["sample_config"]["n_container_samples"]
    n_focussed_samples: int = _EXPL["separator"]["sample_config"]["n_focussed_samples"]
    n_coord_descents: int = _EXPL["separator"]["sample_config"]["n_coord_descents"]

    def __post_init__(self) -> None:
        _nonneg_int(self.n_container_samples, "n_container_samples")
        _nonneg_int(self.n_focussed_samples, "n_focussed_samples")
        _nonneg_int(self.n_coord_descents, "n_coord_descents")


@dataclass(frozen=True, slots=True, kw_only=True)
class SeparatorConfig:
    """Overlap-separation settings (sparrow ``SeparatorConfig``, without ``n_workers``/``log_level``).

    The defaults are those of the exploration phase; ``CompressionConfig`` uses its own.
    """

    iter_no_imprv_limit: int = _EXPL["separator"]["iter_no_imprv_limit"]
    strike_limit: int = _EXPL["separator"]["strike_limit"]
    sample_config: SampleConfig = field(default_factory=SampleConfig)

    def __post_init__(self) -> None:
        _nonneg_int(self.iter_no_imprv_limit, "iter_no_imprv_limit", 1)
        _nonneg_int(self.strike_limit, "strike_limit", 1)

    @classmethod
    def _from_defaults(cls, d: dict[str, Any]) -> SeparatorConfig:
        return cls(
            iter_no_imprv_limit=d["iter_no_imprv_limit"],
            strike_limit=d["strike_limit"],
            sample_config=SampleConfig(**d["sample_config"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "iter_no_imprv_limit": self.iter_no_imprv_limit,
            "strike_limit": self.strike_limit,
            "sample_config": {
                "n_container_samples": self.sample_config.n_container_samples,
                "n_focussed_samples": self.sample_config.n_focussed_samples,
                "n_coord_descents": self.sample_config.n_coord_descents,
            },
        }


@dataclass(frozen=True, slots=True)
class ShrinkDecay:
    """How the compression phase decays its shrink ratio (sparrow ``ShrinkDecayStrategy``).

    Build it with :meth:`time_based` or :meth:`failure_based`.
    """

    kind: Literal["time_based", "failure_based"]
    ratio: float | None = None

    def __post_init__(self) -> None:
        if self.kind == "time_based":
            _check(self.ratio is None, "a time based decay has no ratio")
        elif self.kind == "failure_based":
            _check(
                isinstance(self.ratio, (int, float)) and 0 < self.ratio < 1,
                f"the failure decay ratio must be in (0, 1), got {self.ratio!r}",
            )
        else:
            raise InvalidConfigError(f"unknown shrink decay kind {self.kind!r}")

    @classmethod
    def time_based(cls) -> ShrinkDecay:
        """The shrink ratio decays linearly with the elapsed time."""
        return cls("time_based")

    @classmethod
    def failure_based(cls, ratio: float = _EARLY["fail_decay_ratio"]) -> ShrinkDecay:
        """The shrink ratio is multiplied by ``ratio`` after each failed compression attempt."""
        return cls("failure_based", float(ratio))

    def to_dict(self) -> dict[str, Any]:
        if self.kind == "time_based":
            return {"kind": "time_based"}
        return {"kind": "failure_based", "ratio": self.ratio}


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplorationConfig:
    """Exploration phase (sparrow ``ExplorationConfig``). Its time limit is derived from
    ``SolverConfig.time_limit`` and ``exploration_ratio``.

    Attributes:
        max_conseq_failed_attempts: stop exploring after that many consecutive failed
            attempts to shrink the strip (early termination). ``None`` disables it.
    """

    shrink_step: float = _EXPL["shrink_step"]
    max_conseq_failed_attempts: int | None = _EARLY["max_conseq_failed_attempts"]
    solution_pool_distribution_stddev: float = _EXPL["solution_pool_distribution_stddev"]
    large_item_ch_area_cutoff_percentile: float = _EXPL["large_item_ch_area_cutoff_percentile"]
    separator: SeparatorConfig = field(default_factory=lambda: SeparatorConfig._from_defaults(_EXPL["separator"]))

    def __post_init__(self) -> None:
        _positive_finite(self.shrink_step, "shrink_step")
        if self.max_conseq_failed_attempts is not None:
            _nonneg_int(self.max_conseq_failed_attempts, "max_conseq_failed_attempts", 1)
        _positive_finite(self.solution_pool_distribution_stddev, "solution_pool_distribution_stddev")
        _check(
            isinstance(self.large_item_ch_area_cutoff_percentile, (int, float))
            and 0 <= self.large_item_ch_area_cutoff_percentile <= 1,
            "large_item_ch_area_cutoff_percentile must be in [0, 1]",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CompressionConfig:
    """Compression phase (sparrow ``CompressionConfig``). Its time limit is derived from
    ``SolverConfig.time_limit`` and ``exploration_ratio``.

    Attributes:
        shrink_range: (initial, final) shrink ratio of the strip width.
        shrink_decay: see :class:`ShrinkDecay`.
    """

    shrink_range: tuple[float, float] = tuple(_CMPR["shrink_range"])  # type: ignore[assignment]
    shrink_decay: ShrinkDecay = field(default_factory=ShrinkDecay.failure_based)
    separator: SeparatorConfig = field(default_factory=lambda: SeparatorConfig._from_defaults(_CMPR["separator"]))

    def __post_init__(self) -> None:
        object.__setattr__(self, "shrink_range", tuple(self.shrink_range))
        _check(len(self.shrink_range) == 2, "shrink_range must be a (start, end) pair")
        for v in self.shrink_range:
            _positive_finite(v, "shrink_range values")


@dataclass(frozen=True, slots=True, kw_only=True)
class CDEConfig:
    """Collision detection engine of jagua-rs (``CDEConfig``; the surrogate settings are not exposed).

    Attributes:
        quadtree_depth: maximum depth of the quadtree, common values are 3, 4, 5.
        cd_threshold: stop traversing the quadtree when a node holds fewer edges than this.
    """

    quadtree_depth: int = _D["cde"]["quadtree_depth"]
    cd_threshold: int = _D["cde"]["cd_threshold"]

    def __post_init__(self) -> None:
        _check(
            isinstance(self.quadtree_depth, int) and 1 <= self.quadtree_depth <= 255,
            f"quadtree_depth must be an integer in [1, 255], got {self.quadtree_depth!r}",
        )
        _check(
            isinstance(self.cd_threshold, int) and 0 <= self.cd_threshold <= 255,
            f"cd_threshold must be an integer in [0, 255], got {self.cd_threshold!r}",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ShapeConfig:
    """Approximations applied to item shapes on import (sparrow ``SparrowConfig``).

    All approximations only *inflate* items, solutions stay valid for the original shapes.

    Attributes:
        simplify_tolerance: maximum allowable inflation when simplifying polygons. ``None`` disables.
        narrow_concavity_cutoff: (maximum distance, maximum area) ratios of the concavities
            that are closed. ``None`` disables.
    """

    simplify_tolerance: float | None = _D["shape"]["simplify_tolerance"]
    narrow_concavity_cutoff: tuple[float, float] | None = (
        tuple(_D["shape"]["narrow_concavity_cutoff"]) if _D["shape"]["narrow_concavity_cutoff"] else None  # type: ignore[assignment]
    )

    def __post_init__(self) -> None:
        if self.simplify_tolerance is not None:
            _positive_finite(self.simplify_tolerance, "simplify_tolerance")
        if self.narrow_concavity_cutoff is not None:
            object.__setattr__(self, "narrow_concavity_cutoff", tuple(self.narrow_concavity_cutoff))
            _check(len(self.narrow_concavity_cutoff) == 2, "narrow_concavity_cutoff must be a pair")
            for v in self.narrow_concavity_cutoff:
                _positive_finite(v, "narrow_concavity_cutoff values")


class Preset(enum.Enum):
    """Named starting points for :meth:`SolverConfig.from_preset`.

    Only the two modes that sparrow itself defines are provided.
    """

    AUTO = "auto"
    """sparrow with early termination (CLI ``-x``): stops when no progress is made
    (``max_conseq_failed_attempts``, failure based shrink decay). The default of ``SolverConfig``."""

    EXHAUSTIVE = "exhaustive"
    """sparrow defaults: uses the whole time budget (no early termination, time based shrink decay)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SolverConfig:
    """Configuration of a solver run (sparrow ``SparrowConfig``).

    Attributes:
        time_limit: total time budget in seconds (``float``) or as a ``timedelta``. Default 600 s.
        exploration_ratio: share of ``time_limit`` given to the exploration phase, the rest goes
            to the compression phase. Default 0.8 (sparrow's ``DEFAULT_EXPLORE_TIME_RATIO``).
        num_workers: threads used by the separator. ``None`` = number of logical cores.
        seed: seed of the random number generator. ``None`` = a fresh random seed per ``solve``,
            reported in ``StripPackingSolution.seed``.
        exploration, compression, cde, shape: advanced settings, see the respective classes.
    """

    time_limit: float | timedelta = 600.0
    exploration_ratio: float = _D["explore_time_ratio"]
    num_workers: int | None = None
    seed: int | None = None
    exploration: ExplorationConfig = field(default_factory=ExplorationConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    cde: CDEConfig = field(default_factory=CDEConfig)
    shape: ShapeConfig = field(default_factory=ShapeConfig)

    def __post_init__(self) -> None:
        tl = self.time_limit
        if isinstance(tl, timedelta):
            tl = tl.total_seconds()
        _positive_finite(tl, "time_limit")
        object.__setattr__(self, "time_limit", float(tl))
        _check(
            isinstance(self.exploration_ratio, (int, float)) and 0 < self.exploration_ratio < 1,
            f"exploration_ratio must be in (0, 1), got {self.exploration_ratio!r}",
        )
        if self.num_workers is not None:
            _nonneg_int(self.num_workers, "num_workers", 1)
        if self.seed is not None:
            _check(
                isinstance(self.seed, int) and not isinstance(self.seed, bool) and 0 <= self.seed < 2**64,
                f"seed must be None or an integer in [0, 2**64), got {self.seed!r}",
            )

    @classmethod
    def from_preset(cls, preset: Preset, **overrides: Any) -> SolverConfig:
        """Build a config from a :class:`Preset`; keyword arguments override ``SolverConfig`` fields."""
        if not isinstance(preset, Preset):
            raise InvalidConfigError(f"expected a spyrrow.Preset, got {preset!r}")
        if preset is Preset.AUTO:
            base = cls()
        else:
            base = cls(
                exploration=ExplorationConfig(max_conseq_failed_attempts=None),
                compression=CompressionConfig(shrink_decay=ShrinkDecay.time_based()),
            )
        return replace(base, **overrides)

    @classmethod
    def from_phase_times(cls, exploration: float | timedelta, compression: float | timedelta, **kwargs: Any) -> SolverConfig:
        """Give the time of each phase instead of a total and a ratio (the 0.x "pair" form)."""
        e = exploration.total_seconds() if isinstance(exploration, timedelta) else exploration
        c = compression.total_seconds() if isinstance(compression, timedelta) else compression
        _positive_finite(e, "exploration")
        _positive_finite(c, "compression")
        return cls(time_limit=e + c, exploration_ratio=e / (e + c), **kwargs)

    def replace(self, **changes: Any) -> SolverConfig:
        """Return a copy with some fields changed (the config is frozen)."""
        return replace(self, **changes)

    @property
    def exploration_time(self) -> float:
        """Seconds given to the exploration phase."""
        return float(self.time_limit) * self.exploration_ratio

    @property
    def compression_time(self) -> float:
        """Seconds given to the compression phase."""
        return float(self.time_limit) * (1.0 - self.exploration_ratio)

    def _resolve_seed(self) -> int:
        return self.seed if self.seed is not None else secrets.randbits(63)

    def _to_engine(self, seed: int) -> dict[str, Any]:
        """The resolved configuration, in the schema of ``_core.solve``."""
        e, c = self.exploration, self.compression
        return {
            "seed": seed,
            "num_workers": self.num_workers,
            "exploration": {
                "time_limit": self.exploration_time,
                "shrink_step": e.shrink_step,
                "max_conseq_failed_attempts": e.max_conseq_failed_attempts,
                "solution_pool_distribution_stddev": e.solution_pool_distribution_stddev,
                "large_item_ch_area_cutoff_percentile": e.large_item_ch_area_cutoff_percentile,
                "separator": e.separator.to_dict(),
            },
            "compression": {
                "time_limit": self.compression_time,
                "shrink_range": list(c.shrink_range),
                "shrink_decay": c.shrink_decay.to_dict(),
                "separator": c.separator.to_dict(),
            },
            "cde": {"quadtree_depth": self.cde.quadtree_depth, "cd_threshold": self.cde.cd_threshold},
            "shape": {
                "simplify_tolerance": self.shape.simplify_tolerance,
                "narrow_concavity_cutoff": list(self.shape.narrow_concavity_cutoff)
                if self.shape.narrow_concavity_cutoff
                else None,
            },
        }
