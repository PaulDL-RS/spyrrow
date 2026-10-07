import dataclasses
import json
from datetime import timedelta

import pytest

import spyrrow
from spyrrow import Preset, SolverConfig, _core
from spyrrow.config import (
    CDEConfig,
    CompressionConfig,
    ExplorationConfig,
    SampleConfig,
    SeparatorConfig,
    ShapeConfig,
    ShrinkDecay,
)
from spyrrow.errors import InvalidConfigError

DEFAULTS = json.loads(_core.sparrow_defaults())


def test_defaults_follow_the_default_of_the_0x_api():
    cfg = SolverConfig()
    assert cfg.time_limit == 600.0
    assert cfg.exploration_time == pytest.approx(480.0)
    assert cfg.compression_time == pytest.approx(120.0)
    assert cfg.seed is None
    assert cfg.num_workers is None
    # early termination is on by default, like in 0.x
    assert cfg.exploration.max_conseq_failed_attempts == DEFAULTS["early_termination"]["max_conseq_failed_attempts"]
    assert cfg.compression.shrink_decay == ShrinkDecay.failure_based(DEFAULTS["early_termination"]["fail_decay_ratio"])


def test_config_is_the_engine_schema_of_sparrow():
    """Drift test: the keys and values sent to Rust are those of sparrow's defaults."""
    engine = SolverConfig(seed=1)._to_engine(1)
    for phase in ("exploration", "compression"):
        assert engine[phase].keys() == DEFAULTS[phase].keys()
        assert engine[phase]["separator"] == DEFAULTS[phase]["separator"]
    assert engine["cde"] == DEFAULTS["cde"]
    assert engine["shape"]["simplify_tolerance"] == DEFAULTS["shape"]["simplify_tolerance"]
    assert engine["shape"]["narrow_concavity_cutoff"] == pytest.approx(DEFAULTS["shape"]["narrow_concavity_cutoff"])


def test_exhaustive_preset_is_sparrow_default():
    cfg = SolverConfig.from_preset(Preset.EXHAUSTIVE, time_limit=30, seed=3)
    engine = cfg._to_engine(3)
    assert engine["exploration"]["max_conseq_failed_attempts"] == DEFAULTS["exploration"]["max_conseq_failed_attempts"]
    assert engine["compression"]["shrink_decay"] == DEFAULTS["compression"]["shrink_decay"]
    assert engine["compression"]["shrink_range"] == pytest.approx(DEFAULTS["compression"]["shrink_range"])
    assert cfg.time_limit == 30.0 and cfg.seed == 3
    assert SolverConfig.from_preset(Preset.AUTO) == SolverConfig()


def test_time_split():
    cfg = SolverConfig(time_limit=timedelta(seconds=100), exploration_ratio=0.5)
    assert cfg.time_limit == 100.0
    assert cfg.exploration_time == 50.0 and cfg.compression_time == 50.0
    cfg = SolverConfig.from_phase_times(48, 12, seed=1)
    assert cfg.time_limit == pytest.approx(60) and cfg.exploration_ratio == pytest.approx(0.8)
    assert cfg.exploration_time == pytest.approx(48) and cfg.compression_time == pytest.approx(12)


def test_config_is_frozen_and_replaceable():
    cfg = SolverConfig(seed=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.seed = 2  # type: ignore[misc]
    assert cfg.replace(seed=2).seed == 2
    assert cfg.seed == 1


def test_seed_none_stays_none_and_is_drawn_per_run():
    cfg = SolverConfig()
    assert cfg.seed is None
    assert {cfg._resolve_seed() for _ in range(5)} != {None}
    assert len({cfg._resolve_seed() for _ in range(5)}) > 1
    assert SolverConfig(seed=0)._resolve_seed() == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(time_limit=0),
        dict(time_limit=-3),
        dict(time_limit=float("nan")),
        dict(exploration_ratio=0),
        dict(exploration_ratio=1),
        dict(num_workers=0),
        dict(num_workers=1.5),
        dict(seed=-1),
        dict(seed=2**64),
        dict(seed=True),
    ],
)
def test_invalid_config(kwargs):
    with pytest.raises(InvalidConfigError):
        SolverConfig(**kwargs)


def test_invalid_config_is_a_value_error():
    with pytest.raises(ValueError):
        SolverConfig(time_limit=0)


def test_sub_configs_validate():
    with pytest.raises(InvalidConfigError):
        ShrinkDecay.failure_based(1.5)
    with pytest.raises(InvalidConfigError):
        CDEConfig(quadtree_depth=0)
    with pytest.raises(InvalidConfigError):
        ExplorationConfig(max_conseq_failed_attempts=0)
    with pytest.raises(InvalidConfigError):
        SampleConfig(n_coord_descents=-1)
    with pytest.raises(InvalidConfigError):
        SeparatorConfig(strike_limit=0)
    with pytest.raises(InvalidConfigError):
        ShapeConfig(simplify_tolerance=-1.0)
    with pytest.raises(InvalidConfigError):
        CompressionConfig(shrink_range=(0.1,))  # type: ignore[arg-type]


def test_advanced_options_reach_the_solver():
    # the Rust side rejects unknown / ill-typed fields, so a successful validate proves the schema matches
    cfg = SolverConfig(
        cde=CDEConfig(quadtree_depth=5, cd_threshold=32),
        shape=ShapeConfig(simplify_tolerance=None, narrow_concavity_cutoff=None),
        exploration=ExplorationConfig(
            shrink_step=0.002, max_conseq_failed_attempts=None, separator=SeparatorConfig(iter_no_imprv_limit=50)
        ),
        compression=CompressionConfig(shrink_decay=ShrinkDecay.time_based()),
    )
    inst = spyrrow.StripPackingInstance(2.0, [spyrrow.Item("a", [(0, 0), (1, 0), (1, 1), (0, 1)])])
    inst.validate(cfg)


def test_solve_rejects_a_0x_config():
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import spyrrow.v0 as v0
    inst = spyrrow.StripPackingInstance(2.0, [spyrrow.Item("a", [(0, 0), (1, 0), (1, 1), (0, 1)])])
    with pytest.raises(InvalidConfigError, match="SolverConfig"):
        inst.solve(v0.StripPackingConfig(total_computation_time=1))  # type: ignore[arg-type]
