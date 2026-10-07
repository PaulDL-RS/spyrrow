# Migrating from spyrrow 0.x to 1.0

spyrrow 1.0 follows the vocabulary of sparrow and jagua-rs more closely and removes
several surprising behaviours of 0.x. Every breaking change is listed in
`docs/design/v1.md` (section 4); this page is the short version.

## Option 1, no code change: keep the 0.x API

```python
import spyrrow.v0 as spyrrow   # was: import spyrrow
```

`spyrrow.v0` is the 0.10 API, unchanged (same classes, signatures, defaults, return values
and `to_json_str()` output). Importing it emits a `DeprecationWarning`; it will be removed in
spyrrow 2.0. It receives no new features (reflection, warm start, events, ... are 1.0 only).
Both APIs can be used in the same program.

## Option 2, move to the 1.0 API

### Items

| 0.x | 1.0 |
|---|---|
| `Item("a", shape, 4, allowed_orientations=[0, 90])` | `Item("a", shape, 4, rotation=[0, 90])` |
| `allowed_orientations=None` (free rotation) | `rotation=Rotation.continuous()` |
| `allowed_orientations=[]` (meant `[0]`) | `rotation=Rotation.none()` or just omit it (the default) |
| every 45 degrees | `rotation=Rotation.stepped(45)` (new) |
| (not possible) | `reflection_axes=[0]` lets the item be mirrored (new; accepted by jagua-rs but not yet used by sparrow 0.3.0, so nothing is reflected today) |
| `item.demand = 3` | `item = dataclasses.replace(item, demand=3)`; items are immutable |

`rotation` is keyword-only and optional, `demand` defaults to 1. Ids can be `int` or `str`.
`Rotation.from_allowed_orientations(old_value)` converts an old value mechanically.

**The default changed from "you must choose" to "no rotation".** Pass `Rotation.continuous()`
explicitly where you relied on `None`.

### Instance

| 0.x | 1.0 |
|---|---|
| `StripPackingInstance("name", 2.5, items)` | `StripPackingInstance(2.5, items, name="name")` |
| `StripPackingConfig(min_items_separation=0.1)` | `StripPackingInstance(2.5, items, min_item_separation=0.1)` |

Items are checked against the strip at construction: an item that cannot fit the strip height in
any allowed orientation raises `InvalidInstanceError` immediately.

### Configuration

`StripPackingConfig` is replaced by `SolverConfig`.

| 0.x | 1.0 |
|---|---|
| `StripPackingConfig(total_computation_time=60)` | `SolverConfig(time_limit=60)` (seconds, `float` or `timedelta`) |
| `exploration_time=48, compression_time=12` | `SolverConfig.from_phase_times(48, 12)` |
| (fixed 80/20 split) | `SolverConfig(time_limit=60, exploration_ratio=0.8)` |
| `early_termination=True` (default) | `SolverConfig()` or `SolverConfig.from_preset(Preset.AUTO)` |
| `early_termination=False` | `SolverConfig.from_preset(Preset.EXHAUSTIVE)` |
| `quadtree_depth=5` | `SolverConfig(cde=CDEConfig(quadtree_depth=5))` |
| `num_workers=3`, `seed=0` | unchanged |
| `config.seed` (random value drawn at construction) | stays `None`; the seed that was used is `solution.seed` |

Configs are immutable: `config.replace(seed=1)`. Advanced sparrow settings (`ExplorationConfig`,
`CompressionConfig`, `SeparatorConfig`, ...) are in `spyrrow.config`.

Behaviour change: narrow concavities of shapes are now closed by default like in sparrow
(`ShapeConfig(narrow_concavity_cutoff=...)`, set to `None` to restore the 0.x behaviour).

### Solving and results

```python
# 0.x
solution = instance.solve(config, progress=queue)
for pi in solution.placed_items: print(pi.id, pi.rotation, pi.translation)

# 1.0
solution = instance.solve(config)                       # config is optional
for pi in solution.placed_items: print(pi.item_id, pi.reflected, pi.rotation, pi.translation)
```

* `PlacedItem.id` is now `PlacedItem.item_id`; `PlacedItem.reflected` is new. The transformation is
  *reflect (y -> -y), rotate (degrees), translate*; `pi.transform(item.shape)` applies it.
* `placed_items` is a tuple. `StripPackingSolution` gained `strip_height`, `feasible`, `run_time`,
  `seed`, `interrupted` and is immutable.
* **Progress**: `ProgressQueue` and `ReportType` are gone. Pass a callback; it runs in the thread
  that called `solve`:

  ```python
  import queue, spyrrow
  from spyrrow import events

  q = queue.Queue()                       # if you want to poll from elsewhere
  instance.solve(config, on_event=q.put)

  def on_event(e):
      if isinstance(e, events.SolutionReported) and e.feasible:
          print(f"{e.kind.name}: width={e.solution.width:.2f}")
  ```

  `ReportType.ExplFeas/ExplInfeas/ExplImproving/CmprFeas/Final` are
  `events.ReportKind.EXPLORATION_FEASIBLE/EXPLORATION_INFEASIBLE/EXPLORATION_IMPROVING/COMPRESSION_FEASIBLE/FINAL`.
  Raise `spyrrow.StopSolving` in the callback to stop gracefully.
* **Ctrl-C** now raises `spyrrow.SolveInterrupted` (a `KeyboardInterrupt`, with the best solution
  in `.solution`). `solve(..., on_interrupt="return")` restores the 0.x behaviour of returning it.
* **Warm start**: `instance.solve(config, initial_solution=previous_solution)`.

### Exceptions

`InvalidInstanceError`, `InvalidConfigError`, `InvalidSolutionError` subclass `ValueError`;
`SolverError` subclasses `RuntimeError`. Existing `except ValueError` / `except RuntimeError`
clauses keep working.

### JSON

`to_json_str()` of the instance now produces the sparrow CLI input format (it used to be a private
dump of the Rust structs). `spyrrow.read_json(path)` / `spyrrow.write_json(path, instance, solution)`
read and write sparrow files, including solutions for warm starting. If you parse the old format,
use `spyrrow.v0`.

### Packaging

The native module is now `spyrrow._core` (private). Wheels are `abi3` (one wheel per platform for
Python >= 3.10); PyPy is not supported anymore.
