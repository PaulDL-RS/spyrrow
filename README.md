# Spyrrow

`spyrrow` is a Python wrapper on the Rust project [`sparrow`](https://github.com/JeroenGar/sparrow).
It enables to solve 2D [Strip packing problems](https://en.wikipedia.org/wiki/Strip_packing_problem). 

The documentation is hosted [here](https://spyrrow.readthedocs.io/). 

## Installation

Spyrrow is hosted on [PyPI](https://pypi.org/project/spyrrow/).

You can install with the package manager of your choice, using the PyPI package index.

For example, with `pip`, the default Python package:
```bash
pip install spyrrow
```

## Examples
```python
import spyrrow

rectangle1 = spyrrow.Item(
    "rectangle", [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=[0]
)
triangle1 = spyrrow.Item(
    "triangle",
    [(0, 0), (1, 0), (1, 1), (0, 0)],
    demand=6,
    allowed_orientations=[0, 90, 180, -90],
)

instance = spyrrow.StripPackingInstance(
    "test", strip_height=2.001, items=[rectangle1, triangle1]
)
config = spyrrow.StripPackingConfig(early_termination=False,total_computation_time=60,num_wokers=3,seed=0)
sol = instance.solve(config)
print(sol.width) # 4.0 +/- 5%
print(sol.density)
print("\n")
for pi in sol.placed_items:
    print(pi.id)
    print(pi.rotation)
    print(pi.translation)
    print("\n")
```

## Progress Monitoring

You can monitor the solver's progress in real time using a `ProgressQueue`.
Since `solve()` releases the GIL internally, the main thread is free to drain
the queue while the solver runs:

```python
import threading
import spyrrow

# ... set up instance and config ...

queue = spyrrow.ProgressQueue()
result = [None]

def run():
    result[0] = instance.solve(config, progress=queue)

thread = threading.Thread(target=run)
thread.start()
while thread.is_alive():
    for report_type, solution in queue.drain():
        print(f"{report_type.phase_name()}: width={solution.width:.1f}, density={solution.density:.1%}")
    thread.join(timeout=0.5)

solution = result[0]
```

Each report includes a `ReportType` enum value (`ExplFeas`, `ExplInfeas`, `ExplImproving`,
`CmprFeas`, `Final`) along with a full `StripPackingSolution` containing width, density,
and placed items. Use `report_type.phase_name()` for a grouped label ("exploring",
"compressing", "final") or match on the specific variant for finer control.

## Contributing

Spyrrow is open to contributions.
The first target should be to reach  Python open sources packages standards and practices. 
Second, a easier integration with the package `shapely` is envsionned.

Please use GitHub issues to request features. 
They will be considered relative to what is already implemented in the parent library `sparrow`. 
If necessary, they can be forwarded to it. 

### Tests

The tests come in two tiers:

- hardware independent tests check that every solution is a valid layout (all items placed, allowed rotations, inside the strip, no overlap). They pass whatever the speed of the machine.
- quality tests, marked `@pytest.mark.quality`, assert how narrow the strip gets. They stop on a budget of evaluations (`max_evaluations`) with a fixed seed and number of workers, so they reach the same width on any machine; slow machines (emulated CI runners) only take longer, which is why they are skipped there.

```bash
maturin develop --release
pytest -n auto                    # everything
pytest -n auto -m "not quality"   # hardware independent tests only, as on the emulated CI runners
```

New solve tests should call `assert_valid_solution` from `tests/validity.py`, and keep strip width targets in `quality` tests.

### Type stubs and documentation

`spyrrow.pyi` is generated from the Rust sources (signatures, types and `///` docstrings) by PyO3's introspection and maturin, do not edit it by hand:

```bash
uv run python scripts/generate_stubs.py           # regenerate after changing the Python API
uv run python scripts/generate_stubs.py --check   # what CI runs
```

The documentation on [Read the Docs](https://spyrrow.readthedocs.io/) is built from the sources of each version (not from the latest PyPI release), with the same docstrings. To build it locally:

```bash
uv run maturin develop
uv run python -m sphinx -W -b html docs docs/_build/html
```
