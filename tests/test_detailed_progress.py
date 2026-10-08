import pytest
import spyrrow


def make_instance():
    square = spyrrow.Item(
        "square", [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=[0]
    )
    triangle = spyrrow.Item(
        "triangle",
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        demand=6,
        allowed_orientations=[0, 90, 180, -90],
    )
    return spyrrow.StripPackingInstance("test", strip_height=2.001, items=[square, triangle])


def make_config():
    return spyrrow.StripPackingConfig(total_computation_time=5, num_workers=2, seed=0)


def test_detailed_queue_receives_ordered_phases_and_separation_events():
    queue = spyrrow.ProgressQueue(detailed=True)
    assert queue.detailed
    make_instance().solve(make_config(), queue)
    events = queue.drain_events()

    phases = [e.phase for e in events if isinstance(e, spyrrow.PhaseEvent)]
    assert phases == [spyrrow.OptimizationPhase.Exploration, spyrrow.OptimizationPhase.Compression]
    # a phase event is emitted before any event of its phase
    assert isinstance(events[0], spyrrow.PhaseEvent)

    progress = [e for e in events if isinstance(e, spyrrow.SeparationProgressEvent)]
    results = [e for e in events if isinstance(e, spyrrow.SeparationResultEvent)]
    assert progress and results
    assert all(e.strip_width > 0 and 0.0 <= e.density <= 1.0 and e.min_loss >= 0.0 for e in progress)
    assert all(e.iterations >= 0 and e.elapsed_seconds >= 0.0 for e in results)
    assert any(e.success for e in results)
    assert queue.drain_events() == []
    assert queue.dropped_events == 0


def test_compression_events_follow_compression_phase():
    queue = spyrrow.ProgressQueue(detailed=True)
    make_instance().solve(
        spyrrow.StripPackingConfig(total_computation_time=None, exploration_time=2, compression_time=4, num_workers=2, seed=0),
        queue,
    )
    events = queue.drain_events()
    idx = next(
        i
        for i, e in enumerate(events)
        if isinstance(e, spyrrow.PhaseEvent) and e.phase == spyrrow.OptimizationPhase.Compression
    )
    assert not any(isinstance(e, spyrrow.CompressionProgressEvent) for e in events[:idx])
    for e in events:
        if isinstance(e, spyrrow.CompressionProgressEvent):
            assert 0.0 < e.shrink_step < 1.0


def test_non_detailed_queue_has_no_events_and_drain_unchanged():
    plain = spyrrow.ProgressQueue()
    detailed = spyrrow.ProgressQueue(detailed=True)
    assert not plain.detailed
    instance = make_instance()
    instance.solve(make_config(), plain)
    instance.solve(make_config(), detailed)
    assert plain.drain_events() == []
    reports = plain.drain()
    assert reports and reports[-1][0] == spyrrow.ReportType.Final
    for report_type, solution in reports:
        assert isinstance(report_type, spyrrow.ReportType)
        assert isinstance(solution, spyrrow.StripPackingSolution)
    # drain() never contains events, whether or not the queue is detailed
    for report_type, _ in detailed.drain():
        assert isinstance(report_type, spyrrow.ReportType)
    assert plain.drain() == []


def test_event_buffer_is_bounded_and_drops_oldest():
    queue = spyrrow.ProgressQueue(detailed=True, max_events=5)
    assert queue.max_events == 5
    make_instance().solve(make_config(), queue)
    events = queue.drain_events()
    assert len(events) == 5
    assert queue.dropped_events > 0
    # oldest were dropped, newest (the last separation of the run) are kept
    assert not isinstance(events[0], spyrrow.PhaseEvent)


def test_invalid_max_events():
    with pytest.raises(ValueError):
        spyrrow.ProgressQueue(detailed=True, max_events=0)
    with pytest.raises(OverflowError):
        spyrrow.ProgressQueue(max_events=-1)


def test_event_reprs():
    queue = spyrrow.ProgressQueue(detailed=True)
    make_instance().solve(make_config(), queue)
    for event in queue.drain_events():
        assert type(event).__name__ in repr(event)


def test_detailed_queue_does_not_change_budgeted_run():
    # The listener counts evaluations for max_evaluations and forwards events: both must coexist
    def solve(progress):
        config = spyrrow.StripPackingConfig(total_computation_time=3600, num_workers=2, seed=0, max_evaluations=50_000)
        return make_instance().solve(config, progress=progress)

    queue = spyrrow.ProgressQueue(detailed=True)
    with_events = solve(queue)
    without = solve(None)
    assert any(isinstance(e, spyrrow.SeparationResultEvent) for e in queue.drain_events())
    assert sorted((p.id, p.translation, p.rotation) for p in with_events.placed_items) == sorted(
        (p.id, p.translation, p.rotation) for p in without.placed_items
    )
