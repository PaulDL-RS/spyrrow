import json

import pytest
import spyrrow

from validity import assert_valid_solution

# Runs compared for equality stop on a budget of evaluations, not on the clock,
# so that they do the same work on any machine, however slow or loaded (emulated CI runners included).
# Kept small: emulated CI runners do this work 10-100 times slower.
BUDGET = dict(total_computation_time=3600, max_evaluations=50_000)

OLD_KEYS = {
    "early_termination",
    "seed",
    "exploration_time",
    "compression_time",
    "quadtree_depth",
    "min_items_separation",
    "num_workers",
}


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


def signature(sol):
    return (
        sol.width,
        [(p.id, p.rotation, p.translation) for p in sol.placed_items],
    )


def test_defaults_values():
    config = spyrrow.StripPackingConfig(total_computation_time=5, seed=0)
    assert config.narrow_concavity_cutoff is None
    assert config.poly_simpl_tolerance == pytest.approx(0.001)
    assert config.max_conseq_failed_attempts is None
    assert config.compression_failure_decay_ratio is None
    assert config.iter_no_imprv_limit is None
    assert config.strike_limit is None
    assert config.n_container_samples == 50
    assert config.n_focussed_samples == 25
    assert config.cd_threshold == 64


def test_json_is_additive():
    config = spyrrow.StripPackingConfig(total_computation_time=5, seed=0)
    data = json.loads(config.to_json_str())
    assert OLD_KEYS <= set(data)
    assert set(data) - OLD_KEYS == {
        "narrow_concavity_cutoff",
        "poly_simpl_tolerance",
        "max_conseq_failed_attempts",
        "compression_failure_decay_ratio",
        "iter_no_imprv_limit",
        "strike_limit",
        "n_container_samples",
        "n_focussed_samples",
        "cd_threshold",
    }
    config = spyrrow.StripPackingConfig(
        total_computation_time=5, narrow_concavity_cutoff=(0.02, 0.03), strike_limit=7
    )
    data = json.loads(config.to_json_str())
    assert data["narrow_concavity_cutoff"] == pytest.approx([0.02, 0.03])
    assert data["strike_limit"] == 7


def test_explicit_defaults_reproduce_implicit_defaults():
    instance = make_instance()
    kwargs = dict(**BUDGET, num_workers=1, seed=42)
    implicit = instance.solve(spyrrow.StripPackingConfig(**kwargs))
    implicit_again = instance.solve(spyrrow.StripPackingConfig(**kwargs))
    explicit = instance.solve(
        spyrrow.StripPackingConfig(
            **kwargs,
            narrow_concavity_cutoff=None,
            poly_simpl_tolerance=0.001,
            max_conseq_failed_attempts=None,
            compression_failure_decay_ratio=None,
            iter_no_imprv_limit=None,
            strike_limit=None,
            n_container_samples=50,
            n_focussed_samples=25,
            cd_threshold=64,
        )
    )
    assert signature(implicit) == signature(implicit_again), "run is not reproducible, comparison is moot"
    assert signature(explicit) == signature(implicit)


def test_early_termination_values_are_the_implicit_ones():
    # max_conseq_failed_attempts=10 and decay ratio 0.9 are what early_termination=True implies
    instance = make_instance()
    kwargs = dict(**BUDGET, num_workers=1, seed=7)
    implicit = instance.solve(spyrrow.StripPackingConfig(**kwargs))
    explicit = instance.solve(
        spyrrow.StripPackingConfig(
            **kwargs, max_conseq_failed_attempts=10, compression_failure_decay_ratio=0.9
        )
    )
    assert signature(explicit) == signature(implicit)


def exploration_evaluations(queue):
    phase, evaluations = None, 0
    for event in queue.drain_events():
        if isinstance(event, spyrrow.PhaseEvent):
            phase = event.phase
        elif isinstance(event, spyrrow.SeparationResultEvent) and phase == spyrrow.OptimizationPhase.Exploration:
            evaluations += event.total_evals
    assert queue.dropped_events == 0
    return evaluations


@pytest.mark.parametrize("early_termination", [True, False])
def test_explicit_max_conseq_failed_attempts_stops_exploration(early_termination):
    # An explicit limit of 1 must end exploration much sooner than its share of the budget,
    # whatever early_termination says (it never raises the limit, and with False it adds one).
    # Measured in evaluations rather than seconds, to be independent of the machine.
    # Separations give up quickly (strike_limit, iter_no_imprv_limit), so that attempts fail early
    # and a small budget is enough: exploration with the limit stops after ~57k evaluations, ~246k without.
    instance = make_instance()

    def explore(**kwargs):
        config = spyrrow.StripPackingConfig(
            total_computation_time=3600,
            max_evaluations=300_000,
            num_workers=1,
            seed=3,
            early_termination=early_termination,
            strike_limit=1,
            iter_no_imprv_limit=10,
            **kwargs,
        )
        queue = spyrrow.ProgressQueue(detailed=True, max_events=10_000_000)
        instance.solve(config, queue)
        reports = queue.drain()
        return exploration_evaluations(queue), reports

    limited, reports = explore(max_conseq_failed_attempts=1)
    unlimited, _ = explore()
    assert limited < unlimited / 2
    assert sum(1 for rt, _ in reports if rt == spyrrow.ReportType.ExplInfeas) <= 1


@pytest.mark.quality
def test_non_default_values_run():
    instance = make_instance()
    config = spyrrow.StripPackingConfig(
        total_computation_time=3600,
        max_evaluations=1_000_000,
        num_workers=2,
        seed=1,
        narrow_concavity_cutoff=(0.01, 0.01),
        poly_simpl_tolerance=None,
        max_conseq_failed_attempts=3,
        compression_failure_decay_ratio=0.5,
        iter_no_imprv_limit=50,
        strike_limit=2,
        n_container_samples=20,
        n_focussed_samples=0,
        cd_threshold=32,
    )
    sol = instance.solve(config)
    assert_valid_solution(instance, sol)
    assert sol.width == pytest.approx(4, rel=0.15)


def test_narrow_concavity_cutoff_keeps_solution_valid_for_concave_item():
    # a "C" shape with a very narrow slit, which the cutoff closes
    c_shape = spyrrow.Item(
        "c",
        [(0, 0), (4, 0), (4, 4), (2.02, 4), (2.02, 1), (1.98, 1), (1.98, 4), (0, 4), (0, 0)],
        demand=2,
        allowed_orientations=[0, 90, 180, 270],
    )
    instance = spyrrow.StripPackingInstance("c", strip_height=8.0, items=[c_shape])
    for cutoff in (None, (0.05, 0.05)):
        config = spyrrow.StripPackingConfig(
            total_computation_time=5, num_workers=1, seed=0, narrow_concavity_cutoff=cutoff
        )
        sol = instance.solve(config)
        assert len(sol.placed_items) == 2
        assert sol.width >= 4.0 - 1e-3


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(narrow_concavity_cutoff=(-0.1, 0.1)),
        dict(narrow_concavity_cutoff=(0.1, float("nan"))),
        dict(narrow_concavity_cutoff=(float("inf"), 0.1)),
        dict(poly_simpl_tolerance=-1.0),
        dict(poly_simpl_tolerance=float("nan")),
        dict(max_conseq_failed_attempts=0),
        dict(compression_failure_decay_ratio=0.0),
        dict(compression_failure_decay_ratio=1.0),
        dict(compression_failure_decay_ratio=float("nan")),
        dict(iter_no_imprv_limit=0),
        dict(strike_limit=0),
        dict(n_container_samples=0),
    ],
)
def test_invalid_values_raise(kwargs):
    with pytest.raises(ValueError):
        spyrrow.StripPackingConfig(total_computation_time=5, **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [dict(cd_threshold=256), dict(cd_threshold=-1), dict(n_focussed_samples=-1)],
)
def test_out_of_range_integers_raise(kwargs):
    with pytest.raises((OverflowError, ValueError)):
        spyrrow.StripPackingConfig(total_computation_time=5, **kwargs)


def test_zero_focussed_samples_and_zero_tolerance_are_valid():
    config = spyrrow.StripPackingConfig(
        total_computation_time=5, n_focussed_samples=0, poly_simpl_tolerance=0.0, cd_threshold=0
    )
    assert config.n_focussed_samples == 0


def test_setters_and_solve_revalidation():
    config = spyrrow.StripPackingConfig(total_computation_time=5, num_workers=1, seed=0)
    config.strike_limit = 2
    config.narrow_concavity_cutoff = (0.01, 0.01)
    assert config.strike_limit == 2
    assert config.narrow_concavity_cutoff == pytest.approx((0.01, 0.01))
    config.n_container_samples = 0
    with pytest.raises(ValueError):
        make_instance().solve(config)


def test_deepcopy_keeps_advanced_options():
    import copy

    config = spyrrow.StripPackingConfig(
        total_computation_time=5, narrow_concavity_cutoff=(0.02, 0.03), cd_threshold=10
    )
    clone = copy.deepcopy(config)
    assert clone.narrow_concavity_cutoff == pytest.approx((0.02, 0.03))
    assert clone.cd_threshold == 10
