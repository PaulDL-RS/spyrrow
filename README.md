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
from spyrrow import Item, Rotation, SolverConfig, StripPackingInstance

rectangle = Item("rectangle", [(0, 0), (1, 0), (1, 1), (0, 1)], demand=4)  # not rotated by default
triangle = Item(
    "triangle",
    [(0, 0), (1, 0), (1, 1)],
    demand=6,
    rotation=[0, 90, 180, -90],  # or Rotation.stepped(90), Rotation.continuous()
    reflection_axes=[],  # [0] declares the item mirrorable (not yet used by sparrow 0.3.0)
)

instance = StripPackingInstance(strip_height=2.001, items=[rectangle, triangle])
config = SolverConfig(time_limit=60, num_workers=3, seed=0)
solution = instance.solve(config)

print(solution.width)  # 4.0 +/- 5%
print(solution.density)
for pi in solution.placed_items:
    print(pi.item_id, pi.reflected, pi.rotation, pi.translation)
```

`solve` blocks for at most `time_limit` seconds (early termination is on by default, use
`SolverConfig.from_preset(spyrrow.Preset.EXHAUSTIVE)` to spend the whole budget). Press Ctrl-C to
stop it: `SolveInterrupted` (a `KeyboardInterrupt`) carries the best solution found so far.

## Progress monitoring and warm start

`solve` calls an `on_event` callback in the calling thread while the solver runs:

```python
from spyrrow import events

def on_event(event):
    if isinstance(event, events.SolutionReported) and event.feasible:
        print(f"{event.elapsed:5.1f}s  width={event.solution.width:.3f}  density={event.solution.density:.1%}")

solution = instance.solve(config, on_event=on_event)

# continue from a previous solution (the sparrow CLI can read the file too)
better = instance.solve(config, initial_solution=solution)
spyrrow.write_json("instance_and_solution.json", instance, better)
```

Raise `spyrrow.StopSolving` in the callback to stop gracefully. See `spyrrow.events` for the other events
(`PhaseStarted`, `SeparationProgress`, ...) and `spyrrow.config` for the advanced sparrow settings.

## Upgrading from 0.x

spyrrow 1.0 changes the API, see [MIGRATION.md](MIGRATION.md). To keep running 0.x code unchanged:

```python
import spyrrow.v0 as spyrrow  # deprecated, removed in 2.0
```

## Contributing

Spyrrow is open to contributions.
The first target should be to reach  Python open sources packages standards and practices. 
Second, a easier integration with the package `shapely` is envsionned.

Please use GitHub issues to request features. 
They will be considered relative to what is already implemented in the parent library `sparrow`. 
If necessary, they can be forwarded to it. 
