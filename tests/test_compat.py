"""The compatibility layer: spyrrow.v0 is the 0.x API, deprecated."""

import importlib
import subprocess
import sys
import textwrap

import pytest

import spyrrow


def test_v0_import_emits_a_deprecation_warning():
    import spyrrow.v0

    with pytest.warns(DeprecationWarning, match="removed in spyrrow 2.0"):
        importlib.reload(spyrrow.v0)


def test_v0_warning_is_shown_to_a_script_by_default():
    """DeprecationWarning is hidden by default except when attributed to __main__: check the attribution."""
    code = textwrap.dedent(
        """
        import spyrrow.v0 as spyrrow
        """
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert "DeprecationWarning" in out.stderr and "spyrrow.v0" in out.stderr


def test_v0_is_reachable_as_an_attribute():
    assert spyrrow.v0.StripPackingConfig is not None


def test_v0_and_v1_classes_are_distinct_and_usable_together():
    import spyrrow.v0 as old

    assert old.Item is not spyrrow.Item
    old_item = old.Item("a", [(0, 0), (1, 0), (1, 1)], 2, allowed_orientations=None)
    new_item = spyrrow.Item("a", [(0, 0), (1, 0), (1, 1)], 2, rotation=spyrrow.Rotation.from_allowed_orientations(old_item.allowed_orientations))
    assert new_item.rotation == spyrrow.Rotation.continuous()
    assert old_item.demand == new_item.demand


def test_v0_solve_still_works_quickly():
    import spyrrow.v0 as old

    item = old.Item("t", [(0, 0), (1, 0), (1, 1)], 3, allowed_orientations=[0, 90, 180, 270])
    instance = old.StripPackingInstance("x", 2.001, [item])
    config = old.StripPackingConfig(total_computation_time=5, num_workers=2, seed=0)
    sol = instance.solve(config)
    assert sol.width == pytest.approx(1, rel=0.1)
    assert hasattr(sol.placed_items[0], "id")


def test_native_module_is_private_and_version_is_pep440():
    assert not hasattr(spyrrow, "spyrrow")
    assert spyrrow.__version__.startswith("1.0.0")
