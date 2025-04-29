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


# TODOS

## Pay attention to that

- Edition mismatch between jagua-rs ("2024") and the one chosen by maturin new ("2021")

- pay attention to fsize the floating point size changing based on jagua-rs compilation mode

## Mixed project Python/Rust
possibility to add conversion from shapely in a shapely variant
investiguate the possibility of maturin to handle extras

