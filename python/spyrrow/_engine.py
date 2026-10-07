"""The only module that talks to the native layer ``spyrrow._core``."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, Any

from . import _core, events as ev
from .config import SolverConfig
from .errors import (
    InvalidConfigError,
    InvalidInstanceError,
    InvalidSolutionError,
    SolveInterrupted,
    SolverError,
    StopSolving,
)
from .model import PlacedItem, StripPackingInstance, StripPackingSolution

# Must match src/engine.rs
_MASK_PHASE, _MASK_SOLUTION, _MASK_SEPARATION, _MASK_COMPRESSION = 1, 2, 4, 8

_MASKS: dict[type, int] = {
    ev.PhaseStarted: _MASK_PHASE,
    ev.SolutionReported: _MASK_SOLUTION,
    ev.SeparationProgress: _MASK_SEPARATION,
    ev.SeparationFinished: _MASK_SEPARATION,
    ev.CompressionStep: _MASK_COMPRESSION,
}

_ERRORS = {
    "invalid_instance": InvalidInstanceError,
    "invalid_config": InvalidConfigError,
    "invalid_solution": InvalidSolutionError,
    "solver": SolverError,
}


def _raise_if_error(result: dict[str, Any]) -> None:
    if result["status"] != "ok":
        raise _ERRORS.get(result["kind"], SolverError)(result["message"])


def _config_json(config: SolverConfig, seed: int) -> str:
    return json.dumps(config._to_engine(seed))


def validate(instance: StripPackingInstance, config: SolverConfig | None) -> None:
    config = config if config is not None else SolverConfig()
    if not instance.items:
        return
    _raise_if_error(json.loads(_core.validate(instance.to_json_str(), _config_json(config, 0))))


def _check_warm_start(instance: StripPackingInstance, solution: StripPackingSolution) -> None:
    if not isinstance(solution, StripPackingSolution):
        raise InvalidSolutionError(f"initial_solution must be a StripPackingSolution, got {type(solution).__name__}")
    demands = {i.id: i.demand for i in instance.items}
    placed = Counter(p.item_id for p in solution.placed_items)
    unknown = [i for i in placed if i not in demands]
    if unknown:
        raise InvalidSolutionError(f"the initial solution places unknown item ids: {unknown}")
    wrong = {i: (placed.get(i, 0), d) for i, d in demands.items() if placed.get(i, 0) != d}
    if wrong:
        raise InvalidSolutionError(
            "the initial solution must place every item exactly `demand` times, (placed, demand) mismatches: "
            f"{wrong}"
        )


def _decode_solution(
    ext: dict[str, Any],
    by_ext_id: dict[int, int | str],
    *,
    instance: StripPackingInstance,
    feasible: bool,
    run_time: float,
    seed: int,
    interrupted: bool,
) -> StripPackingSolution:
    placed = tuple(
        PlacedItem(
            by_ext_id[p["item_id"]],
            tuple(p["transformation"]["translation"]),
            p["transformation"]["rotation"],
            p["transformation"].get("reflected", False),
        )
        for p in ext["layout"]["placed_items"]
    )
    return StripPackingSolution(
        width=ext["strip_width"],
        density=ext["density"],
        placed_items=placed,
        strip_height=instance.strip_height,
        feasible=feasible,
        run_time=run_time,
        seed=seed,
        interrupted=interrupted,
    )


def solve(
    instance: StripPackingInstance,
    config: SolverConfig | None,
    *,
    initial_solution: StripPackingSolution | None,
    on_event: Callable[[ev.Event], Any] | None,
    events: Collection[type] | None,
    on_interrupt: str,
) -> StripPackingSolution:
    if config is None:
        config = SolverConfig()
    elif not isinstance(config, SolverConfig):
        raise InvalidConfigError(
            f"config must be a spyrrow.SolverConfig, got {type(config).__name__}. "
            "(spyrrow 0.x StripPackingConfig is now SolverConfig, see MIGRATION.md)"
        )
    if on_interrupt not in ("raise", "return"):
        raise InvalidConfigError(f"on_interrupt must be 'raise' or 'return', got {on_interrupt!r}")
    if on_event is not None and not callable(on_event):
        raise TypeError("on_event must be callable")
    seed = config._resolve_seed()

    if not instance.items:
        return StripPackingSolution(
            width=0.0, density=0.0, placed_items=(), strip_height=instance.strip_height, seed=seed
        )
    if initial_solution is not None:
        _check_warm_start(instance, initial_solution)

    ext_ids = instance._ext_ids()
    by_ext_id = {v: k for k, v in ext_ids.items()}

    callback = None
    mask = 0
    if on_event is not None:
        selected = tuple(events) if events is not None else ev.DEFAULT_EVENTS
        unknown = [e for e in selected if e not in _MASKS]
        if unknown:
            raise InvalidConfigError(f"unknown event classes: {unknown}")
        mask = 0
        for e in selected:
            mask |= _MASKS[e]

        def callback(kind: str, elapsed: float, payload: Any) -> bool:
            event = _decode_event(kind, elapsed, payload, instance, by_ext_id, seed)
            if not isinstance(event, selected):
                return False
            try:
                on_event(event)
            except StopSolving:
                return True
            return False

    warm_json = json.dumps(initial_solution.to_dict(instance)) if initial_solution is not None else None
    result = json.loads(
        _core.solve(instance.to_json_str(), _config_json(config, seed), warm_json, callback, mask)
    )
    _raise_if_error(result)

    interrupted = result["interrupted"] != "none"
    solution = _decode_solution(
        result["solution"],
        by_ext_id,
        instance=instance,
        feasible=True,
        run_time=result["run_time"],
        seed=seed,
        interrupted=interrupted,
    )
    if result["interrupted"] == "signal" and on_interrupt == "raise":
        raise SolveInterrupted(solution)
    return solution


def _decode_event(
    kind: str,
    elapsed: float,
    payload: Any,
    instance: StripPackingInstance,
    by_ext_id: dict[int, int | str],
    seed: int,
) -> ev.Event:
    if kind == "phase":
        return ev.PhaseStarted(ev.Phase(payload), elapsed)
    if kind == "compression_step":
        return ev.CompressionStep(payload, elapsed)
    if kind == "separation_progress":
        width, density, iteration, min_loss = payload
        # sparrow reports the density in percent, spyrrow everywhere as a fraction
        return ev.SeparationProgress(width, density / 100.0, iteration, min_loss, elapsed)
    if kind == "separation_result":
        return ev.SeparationFinished(*payload, elapsed)
    report = ev.ReportKind(kind)
    data = json.loads(payload)
    solution = _decode_solution(
        data["solution"],
        by_ext_id,
        instance=instance,
        feasible=report.feasible,
        run_time=data["run_time"],
        seed=seed,
        interrupted=False,
    )
    return ev.SolutionReported(report, solution, elapsed)
