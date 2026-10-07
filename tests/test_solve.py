"""End-to-end tests of the 1.0 API. Short budgets, at most 2 workers."""

import math
import os
import signal
import threading
import time

import pytest

import spyrrow
from spyrrow import Item, Preset, Rotation, SolverConfig, StripPackingInstance, StripPackingSolution
from spyrrow import events as ev
from spyrrow.errors import (
    InvalidInstanceError,
    InvalidSolutionError,
    SolveInterrupted,
    StopSolving,
)

SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]
TRIANGLE = [(0, 0), (1, 0), (1, 1)]
SCALENE = [(0, 0), (2, 0), (0.5, 1)]  # chiral convex shape


def cfg(seconds=3.0, **kwargs):
    kwargs.setdefault("seed", 0)
    kwargs.setdefault("num_workers", 2)
    return SolverConfig(time_limit=seconds, **kwargs)


def basic_instance(**kwargs):
    items = [
        Item("rectangle", SQUARE, 4),
        Item("triangle", TRIANGLE, 6, rotation=[0, 90, 180, -90]),
    ]
    return StripPackingInstance(2.001, items, **kwargs)


# --- validity checker (convex shapes only) ----------------------------------------------------


def _axes(poly):
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        yield (y1 - y2, x2 - x1)


def _overlap_depth(a, b):
    """Penetration depth of two convex polygons (<= 0 if they do not overlap)."""
    depth = math.inf
    for ax, ay in list(_axes(a)) + list(_axes(b)):
        n = math.hypot(ax, ay)
        pa = [(x * ax + y * ay) / n for x, y in a]
        pb = [(x * ax + y * ay) / n for x, y in b]
        depth = min(depth, min(max(pa), max(pb)) - max(min(pa), min(pb)))
    return depth


def assert_valid(instance, solution, tol=2e-3):
    """Every demand is placed, inside the strip, without overlap (all items must be convex)."""
    by_id = {i.id: i for i in instance.items}
    counts = {}
    polys = []
    sep = instance.min_item_separation
    for p in solution.placed_items:
        counts[p.item_id] = counts.get(p.item_id, 0) + 1
        poly = p.transform(by_id[p.item_id].shape)
        polys.append(poly)
        xs = [x for x, _ in poly]
        ys = [y for _, y in poly]
        assert min(xs) >= -tol and max(xs) <= solution.width + tol, (p, solution.width)
        assert min(ys) >= -tol and max(ys) <= instance.strip_height + tol, p
    assert counts == {i.id: i.demand for i in instance.items}
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            assert _overlap_depth(polys[i], polys[j]) <= tol + 0 * sep, (i, j)


# --- solving ----------------------------------------------------------------------------------


def test_solve_basic():
    instance = basic_instance()
    sol = instance.solve(cfg(5, seed=0))
    assert isinstance(sol, StripPackingSolution)
    assert sol.width == pytest.approx(4, rel=0.05)
    assert sol.feasible and not sol.interrupted
    assert sol.seed == 0
    assert sol.strip_height == instance.strip_height
    assert 0 < sol.run_time < 30
    assert 0 < sol.density <= 1
    assert_valid(instance, sol)


def test_solve_default_config_uses_a_random_seed_and_reports_it():
    inst = StripPackingInstance(2.0, [Item("a", SQUARE, 2)])
    sol = inst.solve(SolverConfig(time_limit=2, num_workers=1))
    assert isinstance(sol.seed, int)
    again = inst.solve(SolverConfig(time_limit=2, num_workers=1, seed=sol.seed))
    assert again.seed == sol.seed


def test_empty_instance():
    sol = StripPackingInstance(2.0, []).solve(cfg())
    assert sol.width == 0 and sol.density == 0 and not sol.placed_items


def test_two_consecutive_solves():
    inst = basic_instance()
    inst.solve(cfg(2))
    assert inst.solve(cfg(4)).width == pytest.approx(4, rel=0.1)


def test_rotation_none_is_the_default_and_means_no_rotation():
    inst = StripPackingInstance(2.001, [Item("t", TRIANGLE, 6)])
    sol = inst.solve(cfg(3))
    assert all(p.rotation == pytest.approx(0) and not p.reflected for p in sol.placed_items)


def test_stepped_rotation_is_respected():
    inst = StripPackingInstance(2.001, [Item("t", TRIANGLE, 6, rotation=Rotation.stepped(90))])
    sol = inst.solve(cfg(3))
    for p in sol.placed_items:
        assert round(p.rotation) % 90 == 0 and abs(p.rotation - round(p.rotation)) < 1e-2
    assert_valid(inst, sol)


def test_discrete_rotation_is_respected():
    inst = StripPackingInstance(2.001, [Item("t", TRIANGLE, 6, rotation=[0, 90])])
    sol = inst.solve(cfg(3))
    for p in sol.placed_items:
        assert min((p.rotation - a) % 360 for a in (0, 90)) < 1e-2 or min((a - p.rotation) % 360 for a in (0, 90)) < 1e-2
    assert_valid(inst, sol)


def test_continuous_rotation():
    items = [Item("rectangle", SQUARE, 4, rotation=Rotation.continuous()), Item("t", TRIANGLE, 6, rotation=Rotation.continuous())]
    inst = StripPackingInstance(2.001, items)
    sol = inst.solve(cfg(10, seed=0, num_workers=2))
    assert 3.4 <= sol.width < 4.05
    assert_valid(inst, sol)


def test_reflection_transforms_are_geometrically_valid():
    """The reflected / rotated / translated shapes must not overlap and stay inside the strip."""
    inst = StripPackingInstance(1.5, [Item("s", SCALENE, 6, rotation=Rotation.stepped(180), reflection_axes=[0])])
    sol = inst.solve(cfg(4))
    assert_valid(inst, sol)
    # sparrow 0.3.0 never reflects items (jagua-rs accepts the axes); do not expect reflected placements
    assert all(isinstance(p.reflected, bool) for p in sol.placed_items)


def test_reflection_with_stepped_rotation_valid_for_mixed_items():
    items = [
        Item("s", SCALENE, 4, rotation=Rotation.stepped(90), reflection_axes=[0]),
        Item("sq", SQUARE, 2),
    ]
    inst = StripPackingInstance(2.0, items)
    sol = inst.solve(cfg(4))
    assert_valid(inst, sol)


def test_min_item_separation_on_the_instance():
    inst = StripPackingInstance(2.5, [Item("r", SQUARE, 4)], min_item_separation=0.2)
    sol = inst.solve(cfg(4))
    assert sol.width >= 2.4 - 1e-3


def test_concave_polygons():
    poly1 = Item("0", [(0, 0), (3, 0), (4, 1), (3, 2), (0, 2), (1, 1), (0, 0)], 2, rotation=[0, 90, 180, 270])
    poly2 = Item("1", [(0, 0), (1, 0), (1, 2), (3, 2), (3, 0), (4, 0), (4, 3), (0, 3), (0, 0)], 3, rotation=[0, 90, 180, 270])
    sol = StripPackingInstance(4.001, [poly1, poly2]).solve(cfg(5))
    assert sol.width > 0
    assert len(sol.placed_items) == 5


def test_integer_ids_round_trip():
    inst = StripPackingInstance(2.0, [Item(10, SQUARE, 2), Item(4, TRIANGLE, 2)])
    sol = inst.solve(cfg(2))
    assert {p.item_id for p in sol.placed_items} == {10, 4}


def test_mixed_ids_round_trip():
    inst = StripPackingInstance(2.0, [Item("a", SQUARE, 2), Item(1, TRIANGLE, 2)])
    sol = inst.solve(cfg(2))
    assert {p.item_id for p in sol.placed_items} == {"a", 1}


def test_preset_exhaustive_runs():
    inst = StripPackingInstance(2.001, [Item("a", SQUARE, 3)])
    sol = inst.solve(SolverConfig.from_preset(Preset.EXHAUSTIVE, time_limit=5, num_workers=2, seed=0))
    assert sol.width == pytest.approx(2.0, rel=0.2)
    assert_valid(inst, sol)


# --- errors -----------------------------------------------------------------------------------


def test_invalid_shape_is_reported_by_validate_and_solve():
    # (1, 0) appears twice, not consecutively: rejected by jagua-rs at import
    bad = Item("bad", [(0, 0), (1, 0), (1, 1), (0.5, 0.5), (1, 0), (0, 1)])
    inst = StripPackingInstance(2.0, [bad])
    with pytest.raises(InvalidInstanceError):
        inst.validate()
    with pytest.raises(ValueError):
        inst.solve(cfg(1))


def test_validate_accepts_a_good_instance():
    basic_instance().validate()


# --- warm start -------------------------------------------------------------------------------


def test_warm_start_does_not_get_worse():
    inst = basic_instance()
    first = inst.solve(cfg(3, seed=1))
    second = inst.solve(cfg(3, seed=2), initial_solution=first)
    assert second.width <= first.width + 1e-3
    assert_valid(inst, second)


def test_warm_start_from_json_file(tmp_path):
    inst = basic_instance(name="warm")
    first = inst.solve(cfg(2))
    path = tmp_path / "out.json"
    spyrrow.write_json(path, inst, first)
    inst2, sol2 = spyrrow.read_json(path)
    assert sol2 is not None
    second = inst2.solve(cfg(2), initial_solution=sol2)
    assert second.width <= first.width + 1e-3


def test_warm_start_first_report_starts_from_the_initial_solution():
    inst = basic_instance()
    first = inst.solve(cfg(3, seed=1))
    seen = []
    inst.solve(cfg(2, seed=2), initial_solution=first, on_event=seen.append)
    widths = [e.solution.width for e in seen if isinstance(e, ev.SolutionReported)]
    # a cold start begins with a wide strip from the constructive heuristic, a warm start with the given width
    assert widths[0] <= first.width * 1.05


def test_warm_start_must_be_complete():
    inst = basic_instance()
    sol = inst.solve(cfg(2))
    partial = StripPackingSolution(sol.width, sol.density, sol.placed_items[:-1], sol.strip_height)
    with pytest.raises(InvalidSolutionError, match="exactly"):
        inst.solve(cfg(1), initial_solution=partial)
    extra = StripPackingSolution(sol.width, sol.density, sol.placed_items + sol.placed_items[:1], sol.strip_height)
    with pytest.raises(InvalidSolutionError):
        inst.solve(cfg(1), initial_solution=extra)
    unknown = StripPackingSolution(
        sol.width, sol.density, (spyrrow.PlacedItem("nope", (0.0, 0.0), 0.0),) + sol.placed_items[1:], sol.strip_height
    )
    with pytest.raises(InvalidSolutionError, match="unknown"):
        inst.solve(cfg(1), initial_solution=unknown)
    with pytest.raises(InvalidSolutionError):
        inst.solve(cfg(1), initial_solution="not a solution")  # type: ignore[arg-type]


def test_warm_start_must_be_feasible_for_the_instance():
    """sparrow 0.3.0 assumes a feasible start and would return it as is: spyrrow checks it."""
    items = [Item("r", SQUARE, 4)]
    first = StripPackingInstance(2.001, items).solve(cfg(3))
    tighter = StripPackingInstance(2.001, items, min_item_separation=0.3)
    with pytest.raises(InvalidSolutionError, match="not feasible"):
        tighter.solve(cfg(2), initial_solution=first)


# --- events -----------------------------------------------------------------------------------


def test_events_default_selection():
    inst = basic_instance()
    seen = []
    sol = inst.solve(cfg(4), on_event=seen.append)
    assert all(isinstance(e, ev.DEFAULT_EVENTS) for e in seen)
    phases = [e.phase for e in seen if isinstance(e, ev.PhaseStarted)]
    assert phases == [ev.Phase.EXPLORATION, ev.Phase.COMPRESSION]
    reports = [e for e in seen if isinstance(e, ev.SolutionReported)]
    assert reports[-1].kind is ev.ReportKind.FINAL
    assert reports[-1].solution.width == pytest.approx(sol.width)
    assert reports[-1].solution.feasible and reports[-1].feasible
    assert {r.kind for r in reports[:-1]} <= set(ev.ReportKind) - {ev.ReportKind.FINAL}
    assert [e.elapsed for e in seen] == sorted(e.elapsed for e in seen)
    for r in reports:
        assert r.solution.feasible == r.kind.feasible
        assert len(r.solution.placed_items) == inst.total_demand
        assert {p.item_id for p in r.solution.placed_items} == {"rectangle", "triangle"}


def test_events_all_kinds_on_request():
    inst = basic_instance()
    seen = []
    inst.solve(
        cfg(3),
        on_event=seen.append,
        events=(ev.PhaseStarted, ev.SolutionReported, ev.SeparationProgress, ev.SeparationFinished, ev.CompressionStep),
    )
    kinds = {type(e) for e in seen}
    assert ev.SeparationProgress in kinds and ev.SeparationFinished in kinds
    seps = [e for e in seen if isinstance(e, ev.SeparationFinished)]
    assert any(e.total_evals > 0 for e in seps) and all(e.duration >= 0 for e in seps)
    prog = next(e for e in seen if isinstance(e, ev.SeparationProgress))
    assert prog.strip_width > 0 and 0 < prog.density <= 1.0


def test_events_filter_by_class():
    seen = []
    basic_instance().solve(cfg(2), on_event=seen.append, events=(ev.PhaseStarted,))
    assert seen and all(isinstance(e, ev.PhaseStarted) for e in seen)


def test_unknown_event_class_is_rejected():
    with pytest.raises(spyrrow.InvalidConfigError):
        basic_instance().solve(cfg(1), on_event=print, events=(int,))


def test_callback_runs_in_the_calling_thread():
    threads = set()
    basic_instance().solve(cfg(2), on_event=lambda e: threads.add(threading.get_ident()))
    assert threads == {threading.get_ident()}


def test_stop_solving_returns_the_best_solution():
    inst = basic_instance()
    seen = []

    def stop_on_first_feasible(e):
        seen.append(e)
        if isinstance(e, ev.SolutionReported) and e.feasible:
            raise StopSolving

    start = time.monotonic()
    sol = inst.solve(cfg(60, seed=0), on_event=stop_on_first_feasible)
    assert time.monotonic() - start < 20
    assert sol.interrupted and sol.feasible
    assert_valid(inst, sol)


def test_callback_exception_propagates_and_stops_the_solver():
    class Boom(RuntimeError):
        pass

    def boom(e):
        raise Boom("from callback")

    start = time.monotonic()
    with pytest.raises(Boom):
        basic_instance().solve(cfg(60), on_event=boom)
    assert time.monotonic() - start < 20


def test_thread_safe_queue_pattern():
    """Replacement of the 0.x ProgressQueue: put events in a queue from the callback, consume them elsewhere."""
    import queue

    q = queue.Queue()
    result = []
    t = threading.Thread(target=lambda: result.append(basic_instance().solve(cfg(3), on_event=q.put)))
    t.start()
    t.join(timeout=60)
    assert not t.is_alive()
    assert not q.empty()
    assert result[0].width > 0


# --- Ctrl-C -----------------------------------------------------------------------------------


@pytest.fixture
def sigint_handler():
    old = signal.signal(signal.SIGINT, signal.default_int_handler)
    yield
    signal.signal(signal.SIGINT, old)


def _send_sigint_later(delay=1.0):
    timer = threading.Timer(delay, lambda: os.kill(os.getpid(), signal.SIGINT))
    timer.start()
    return timer


@pytest.mark.skipif(os.name == "nt", reason="os.kill(SIGINT) semantics differ on Windows")
def test_ctrl_c_raises_keyboard_interrupt_with_the_partial_solution(sigint_handler):
    inst = basic_instance()
    timer = _send_sigint_later()
    start = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt) as excinfo:
            inst.solve(cfg(120, seed=0))
    finally:
        timer.cancel()
    assert time.monotonic() - start < 30
    assert isinstance(excinfo.value, SolveInterrupted)
    partial = excinfo.value.solution
    assert partial is not None and partial.interrupted and partial.feasible
    assert_valid(inst, partial)


@pytest.mark.skipif(os.name == "nt", reason="os.kill(SIGINT) semantics differ on Windows")
def test_ctrl_c_can_return_the_partial_solution(sigint_handler):
    inst = basic_instance()
    timer = _send_sigint_later()
    try:
        sol = inst.solve(cfg(120, seed=0), on_interrupt="return")
    finally:
        timer.cancel()
    assert sol.interrupted
    assert_valid(inst, sol)


def test_invalid_on_interrupt():
    with pytest.raises(spyrrow.InvalidConfigError):
        basic_instance().solve(cfg(1), on_interrupt="ignore")  # type: ignore[arg-type]
