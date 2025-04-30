# Spyrrow

Python wrapper on the Rust project [`sparrow`](https://github.com/JeroenGar/sparrow)

## Examples
```python
import spyrrow

rectangle1 = spyrrow.Item([(0,0),(1,0),(1,1),(0,1),(0,0)], demand=4, allowed_orientations=[0])
triangle1 = spyrrow.Item([(0,0),(1,0),(1,1),(0,0)], demand=6, allowed_orientations=[0,90,180,-90])

instance = spyrrow.StripPackingInstance("test", height=2.001, items=[rectangle1,triangle1])
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

## Informations

The algorithmn is  insensitive to rotation angles and shapes complexity (to a certain extend)

# TODOS

## Pay attention to that


use test-profile for local developpment

investiguate the compile options, nightly and SIMD and PyPa target architectures

- add presets for parameters as enums 

## Mixed project Python/Rust
possibility to add conversion from shapely in a shapely variant
investiguate the possibility of maturin to handle extras

