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

instance = spyrrow.StripPackingInstance("test", strip_height=2.001, items=[rectangle1,triangle1])
sol:spyrrow.StripPackingSolution = instance.solve(30)
print(sol.width)
print(sol.density)
print("\n")
for pi in sol.placed_items:
    print(pi.id)
    print(pi.rotation)
    print(pi.translation)
    print("\n")
```

## Contributing

Spyrrow is open to contributions.
The first target should be to reach  Python open sources packages standards and practices. 
Second, a easier integration with the package `shapely` is envsionned.

Please use GitHub issues to request features. 
They will be considered relative to what is already implemented in the parent library `sparrow`. 
If necessary, they can be forwarded to it. 
