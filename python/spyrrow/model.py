"""Value objects: ``Rotation``, ``Item``, ``StripPackingInstance``, ``PlacedItem``, ``StripPackingSolution``."""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal

from . import _geometry
from .errors import InvalidInstanceError, InvalidSolutionError

if TYPE_CHECKING:
    from .config import SolverConfig
    from .events import Event

__all__ = ["Rotation", "Item", "StripPackingInstance", "PlacedItem", "StripPackingSolution"]

Point = tuple[float, float]
_MAX_ANGLES = 65_536
_U64 = 2**64
_F32_EPS = 1.1920929e-07


def _f32(x: float) -> float:
    try:
        return struct.unpack("f", struct.pack("f", x))[0]
    except OverflowError:
        return math.inf


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# --------------------------------------------------------------------------------------------
# Rotation
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rotation:
    """The rotations an item may take (jagua-rs ``ExtRotation``). Angles are degrees, counter-clockwise.

    Build it with the constructors :meth:`none`, :meth:`discrete`, :meth:`stepped`, :meth:`continuous`.

    Attributes:
        mode: ``"discrete"``, ``"stepped"`` or ``"continuous"``
        angles: the allowed angles (``discrete`` only)
        step: the increment (``stepped`` only)
    """

    mode: Literal["discrete", "stepped", "continuous"]
    angles: tuple[float, ...] | None = None
    step: float | None = None

    def __post_init__(self) -> None:
        if self.mode == "discrete":
            if self.angles is None or self.step is not None:
                raise InvalidInstanceError("a discrete rotation needs `angles` and no `step`")
            angles = tuple(self.angles)
            if not 1 <= len(angles) <= _MAX_ANGLES:
                raise InvalidInstanceError(f"a discrete rotation needs 1 to {_MAX_ANGLES} angles, got {len(angles)}")
            if not all(_is_number(a) and math.isfinite(a) for a in angles):
                raise InvalidInstanceError("rotation angles must be finite numbers")
            object.__setattr__(self, "angles", tuple(float(a) for a in angles))
        elif self.mode == "stepped":
            if self.step is None or self.angles is not None:
                raise InvalidInstanceError("a stepped rotation needs `step` and no `angles`")
            step = self.step
            if not (_is_number(step) and math.isfinite(step) and 0 < step <= 360):
                raise InvalidInstanceError(f"the rotation step must be in (0, 360], got {step!r}")
            count = round(360.0 / _f32(step))
            if count > _MAX_ANGLES or abs(count * _f32(step) - 360.0) > 360.0 * _F32_EPS:
                raise InvalidInstanceError(f"the rotation step {step!r} must divide 360 into at most {_MAX_ANGLES} angles")
            object.__setattr__(self, "step", float(step))
        elif self.mode == "continuous":
            if self.angles is not None or self.step is not None:
                raise InvalidInstanceError("a continuous rotation takes no argument")
        else:
            raise InvalidInstanceError(f"unknown rotation mode {self.mode!r}")

    @classmethod
    def none(cls) -> Rotation:
        """Only the original orientation (0 degrees)."""
        return cls("discrete", angles=(0.0,))

    @classmethod
    def discrete(cls, angles: Iterable[float]) -> Rotation:
        """An explicit, non-empty list of angles. Zero is *not* implicit."""
        return cls("discrete", angles=tuple(angles))

    @classmethod
    def stepped(cls, step: float) -> Rotation:
        """0, step, 2*step, ... up to 360 (excluded). ``step`` must divide 360."""
        return cls("stepped", step=step)

    @classmethod
    def continuous(cls) -> Rotation:
        """Any angle."""
        return cls("continuous")

    @classmethod
    def from_allowed_orientations(cls, allowed_orientations: Sequence[float] | None) -> Rotation:
        """Convert a spyrrow 0.x ``allowed_orientations`` value: ``None`` -> continuous, ``[]`` -> none."""
        if allowed_orientations is None:
            return cls.continuous()
        angles = tuple(allowed_orientations)
        return cls.discrete(angles) if angles else cls.none()

    def expand(self) -> tuple[float, ...] | None:
        """The explicit list of angles, ``None`` for continuous rotation."""
        if self.mode == "discrete":
            return self.angles
        if self.mode == "stepped":
            assert self.step is not None
            count = round(360.0 / _f32(self.step))
            return tuple(i * 360.0 / count for i in range(count))
        return None

    def to_dict(self) -> dict[str, Any]:
        """The jagua-rs / sparrow JSON form."""
        if self.mode == "discrete":
            return {"mode": "discrete", "angles": list(self.angles or ())}
        if self.mode == "stepped":
            return {"mode": "stepped", "step": self.step}
        return {"mode": "continuous"}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rotation:
        mode = data.get("mode")
        if mode == "discrete":
            return cls.discrete(data["angles"])
        if mode == "stepped":
            return cls.stepped(data["step"])
        if mode == "continuous":
            return cls.continuous()
        raise InvalidInstanceError(f"unknown rotation mode {mode!r}")


# --------------------------------------------------------------------------------------------
# Item
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Item:
    """A closed 2D shape defined by its outer boundary, to be packed ``demand`` times (jagua-rs ``ExtItem``).

    Holes are not supported by jagua-rs for strip packing, therefore no item can be nested in another.

    Args:
        id: identifier, unique among the items of an instance. A non-negative ``int`` or a ``str``.
        shape: ordered (x, y) vertices of the boundary. The first point may be repeated at the end.
        demand: number of copies to pack, strictly positive. Defaults to 1.
        rotation: allowed rotations, a :class:`Rotation` or a sequence of angles in degrees
            (shorthand for ``Rotation.discrete``). Defaults to ``Rotation.none()``: the item is not rotated.
        reflection_axes: **accepted and validated by jagua-rs, but not used by sparrow 0.3.0**: the solver never
            reflects items, so ``PlacedItem.reflected`` is always ``False`` for now.
            Axes (degrees, counter-clockwise from the item's x axis, through its origin)
            across which the item may be mirrored. ``[0]`` allows the flip (x, y) -> (x, -y); ``[90]``
            allows (x, y) -> (-x, y). Empty (default): the item is never mirrored.
    """

    id: int | str
    shape: tuple[Point, ...]
    demand: int = 1
    rotation: Rotation = field(default_factory=Rotation.none, kw_only=True)
    reflection_axes: tuple[float, ...] = field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        if isinstance(self.id, bool) or not isinstance(self.id, (int, str)):
            raise InvalidInstanceError(f"Item.id must be an int or a str, got {self.id!r}")
        if isinstance(self.id, int) and not 0 <= self.id < _U64:
            raise InvalidInstanceError(f"integer Item.id must be in [0, 2**64), got {self.id}")
        if isinstance(self.demand, bool) or not isinstance(self.demand, int) or self.demand < 1:
            raise InvalidInstanceError(f"item {self.id!r}: demand must be an integer >= 1, got {self.demand!r}")
        try:
            shape = tuple((float(x), float(y)) for x, y in self.shape)
        except (TypeError, ValueError) as e:
            raise InvalidInstanceError(f"item {self.id!r}: shape must be a sequence of (x, y) pairs") from e
        if not all(math.isfinite(c) for p in shape for c in p):
            raise InvalidInstanceError(f"item {self.id!r}: shape coordinates must be finite")
        ring = shape[:-1] if len(shape) > 1 and shape[0] == shape[-1] else shape
        if len(set(ring)) < 3:
            raise InvalidInstanceError(f"item {self.id!r}: shape needs at least 3 distinct points")
        if _geometry.signed_area(ring) == 0.0:
            raise InvalidInstanceError(f"item {self.id!r}: shape has zero area")
        object.__setattr__(self, "shape", shape)

        rotation = self.rotation
        if rotation is None:
            raise InvalidInstanceError(
                f"item {self.id!r}: rotation=None is not accepted. Use Rotation.none() (no rotation) "
                "or Rotation.continuous() (free rotation)"
            )
        if not isinstance(rotation, Rotation):
            rotation = Rotation.discrete(rotation)
            object.__setattr__(self, "rotation", rotation)
        axes = tuple(self.reflection_axes)
        if not all(_is_number(a) and math.isfinite(a) for a in axes):
            raise InvalidInstanceError(f"item {self.id!r}: reflection axes must be finite numbers")
        object.__setattr__(self, "reflection_axes", tuple(float(a) for a in axes))

    @property
    def area(self) -> float:
        """Area of the shape."""
        ring = self.shape[:-1] if self.shape[0] == self.shape[-1] else self.shape
        return abs(_geometry.signed_area(ring))

    def min_height(self) -> float:
        """The smallest height (y extent) the item can take over all its allowed orientations."""
        angles = self.rotation.expand()
        if angles is None:
            return _geometry.min_width(self.shape)
        best = math.inf
        for a in angles:
            best = min(best, _geometry.height_at(self.shape, a, False))
        for axis in self.reflection_axes:
            for a in angles:
                best = min(best, _geometry.height_at(self.shape, a + 2.0 * axis, True))
        return best

    def to_dict(self, ext_id: int | None = None, *, with_label: bool = False) -> dict[str, Any]:
        """The jagua-rs / sparrow JSON form. ``ext_id`` overrides the numeric id and ``with_label`` keeps
        the original id in an extra ``label`` field (see ``StripPackingInstance``)."""
        orientation: dict[str, Any] = {"rotation": self.rotation.to_dict()}
        if self.reflection_axes:
            orientation["reflection_axes"] = list(self.reflection_axes)
        out: dict[str, Any] = {
            "id": self.id if ext_id is None else ext_id,
            "demand": self.demand,
            "orientation": orientation,
            "shape": {"type": "simple_polygon", "data": [list(p) for p in self.shape]},
        }
        if with_label or isinstance(self.id, str):
            out["label"] = self.id
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Item:
        if data.get("min_quality") is not None:
            raise InvalidInstanceError("min_quality is not supported")
        shape = data["shape"]
        kind = shape.get("type")
        if kind == "simple_polygon":
            points = shape["data"]
        elif kind == "polygon" and not shape["data"].get("inner"):
            points = shape["data"]["outer"]
        elif kind == "rectangle":
            r = shape["data"]
            x, y, w, h = r["x_min"], r["y_min"], r["width"], r["height"]
            points = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        else:
            raise InvalidInstanceError(f"unsupported shape type {kind!r} (only polygons without holes)")
        orientation = data["orientation"]
        return cls(
            data.get("label", data["id"]),
            [tuple(p) for p in points],
            data.get("demand", 1),
            rotation=Rotation.from_dict(orientation["rotation"]),
            reflection_axes=tuple(orientation.get("reflection_axes", ())),
        )


# --------------------------------------------------------------------------------------------
# Solution
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlacedItem:
    """Where a copy of an item was placed (jagua-rs ``ExtPlacedItem`` with its ``ExtTransformation``).

    The transformation applies to the *original* coordinates of the item shape, in this order:
    reflection (if ``reflected``: y -> -y), rotation by ``rotation`` degrees counter-clockwise around
    the origin, then translation.

    Attributes:
        item_id: the ``Item.id``
        reflected: whether the item is mirrored
        rotation: rotation in degrees
        translation: (x, y) translation to apply after the rotation
    """

    item_id: int | str
    translation: Point
    rotation: float
    reflected: bool = False

    def transform(self, points: Iterable[Point]) -> list[Point]:
        """Apply the transformation to points given in the original item coordinates (e.g. ``item.shape``)."""
        a = math.radians(self.rotation)
        c, s = math.cos(a), math.sin(a)
        tx, ty = self.translation
        out = []
        for x, y in points:
            if self.reflected:
                y = -y
            out.append((c * x - s * y + tx, s * x + c * y + ty))
        return out


@dataclass(frozen=True, slots=True)
class StripPackingSolution:
    """The result of ``StripPackingInstance.solve`` (jagua-rs ``ExtSPSolution``).

    Attributes:
        width: width of the strip found to contain all items, same unit as the input
        strip_height: height of the strip (the instance's)
        density: fraction of the strip used by items
        placed_items: how every copy of every item is placed
        feasible: no overlap and everything inside the strip. ``False`` only for intermediate
            solutions delivered in events
        run_time: seconds since the start of ``solve`` at which the solution was found
        seed: the seed of the run (the config's, or the random one that was drawn)
        interrupted: the run was stopped before its time budget by ``StopSolving`` or Ctrl-C
    """

    width: float
    density: float
    placed_items: tuple[PlacedItem, ...]
    strip_height: float | None = None
    feasible: bool = True
    run_time: float = 0.0
    seed: int | None = None
    interrupted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "placed_items", tuple(self.placed_items))

    def to_dict(self, instance: StripPackingInstance | None = None) -> dict[str, Any]:
        """The jagua-rs ``ExtSPSolution`` JSON form. Pass the instance if its ids are not all integers."""
        ext_ids = instance._ext_ids() if instance is not None else None
        placed = []
        for p in self.placed_items:
            if ext_ids is not None:
                item_id = ext_ids[p.item_id]
            elif isinstance(p.item_id, int):
                item_id = p.item_id
            else:
                raise InvalidSolutionError("string item ids need the instance to be exported")
            t: dict[str, Any] = {"rotation": p.rotation, "translation": list(p.translation)}
            if p.reflected:
                t["reflected"] = True
            placed.append({"item_id": item_id, "transformation": t})
        return {
            "strip_width": self.width,
            "layout": {"container_id": 0, "placed_items": placed, "density": self.density},
            "density": self.density,
            "run_time_sec": int(self.run_time),
        }

    def to_json_str(self, instance: StripPackingInstance | None = None) -> str:
        """JSON of the solution. With ``instance``: the sparrow CLI output (instance + solution),
        which the sparrow CLI accepts as a warm start input."""
        if instance is None:
            return json.dumps(self.to_dict())
        return json.dumps({**instance.to_dict(), "solution": self.to_dict(instance)})

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        instance: StripPackingInstance | None = None,
        *,
        strip_height: float | None = None,
    ) -> StripPackingSolution:
        """Read a ``ExtSPSolution`` (or a full sparrow output, whose ``"solution"`` key is used).

        Pass ``instance`` to map the JSON ids back to the ids of its items (needed for ``str`` ids).
        """
        if "solution" in data:
            data = data["solution"]
        by_ext = {v: k for k, v in instance._ext_ids().items()} if instance is not None else None
        placed = []
        for p in data["layout"]["placed_items"]:
            ext_id = p["item_id"]
            t = p["transformation"]
            item_id = by_ext[ext_id] if by_ext is not None and ext_id in by_ext else ext_id
            placed.append(PlacedItem(item_id, tuple(t["translation"]), t["rotation"], t.get("reflected", False)))
        if strip_height is None and instance is not None:
            strip_height = instance.strip_height
        return cls(
            width=data["strip_width"],
            density=data["density"],
            placed_items=tuple(placed),
            strip_height=strip_height,
            run_time=float(data.get("run_time_sec", 0)),
        )

    @classmethod
    def from_json_str(cls, text: str, instance: StripPackingInstance | None = None) -> StripPackingSolution:
        return cls.from_dict(json.loads(text), instance)


# --------------------------------------------------------------------------------------------
# Instance
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StripPackingInstance:
    """An instance of the 2D irregular strip packing problem (jagua-rs ``ExtSPInstance``).

    Args:
        strip_height: the fixed height of the strip, in the unit of the items
        items: the items, each with its demand. Ids must be unique.
        name: optional name of the instance (informative)
        min_item_separation: minimum distance between items, and between items and the strip border.
            Defaults to 0.

    Raises:
        InvalidInstanceError: duplicate ids, invalid values, or an item that cannot fit the strip
            in any of its allowed orientations.
    """

    strip_height: float
    items: tuple[Item, ...]
    name: str = field(default="", kw_only=True)
    min_item_separation: float = field(default=0.0, kw_only=True)

    def __post_init__(self) -> None:
        if isinstance(self.strip_height, str):
            raise TypeError(
                "StripPackingInstance(strip_height, items, *, name='', ...): the first argument is the strip "
                "height. This looks like the spyrrow 0.x signature (name, strip_height, items), "
                "see MIGRATION.md, or use `import spyrrow.v0 as spyrrow`."
            )
        if not (_is_number(self.strip_height) and math.isfinite(self.strip_height) and self.strip_height > 0):
            raise InvalidInstanceError(f"strip_height must be a finite number > 0, got {self.strip_height!r}")
        if not (_is_number(self.min_item_separation) and math.isfinite(self.min_item_separation) and self.min_item_separation >= 0):
            raise InvalidInstanceError(f"min_item_separation must be a finite number >= 0, got {self.min_item_separation!r}")
        if not isinstance(self.name, str):
            raise InvalidInstanceError(f"name must be a str, got {self.name!r}")
        items = tuple(self.items)
        if not all(isinstance(i, Item) for i in items):
            raise InvalidInstanceError("items must be spyrrow.Item objects")
        ids = [i.id for i in items]
        if len(set(ids)) != len(ids):
            dup = sorted({i for i in ids if ids.count(i) > 1}, key=str)
            raise InvalidInstanceError(f"the item ids are not unique: {dup}")
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "strip_height", float(self.strip_height))
        object.__setattr__(self, "min_item_separation", float(self.min_item_separation))
        usable = self.strip_height - self.min_item_separation
        if items and usable <= 0:
            raise InvalidInstanceError(
                f"min_item_separation ({self.min_item_separation}) leaves no usable strip height ({self.strip_height})"
            )
        for item in items:
            height = item.min_height()
            if height > usable * (1 - 1e-7):
                raise InvalidInstanceError(
                    f"item {item.id!r} cannot be placed in the strip (it must fit strictly: sparrow cannot build an initial layout for an exact fit): its smallest height over its allowed orientations is "
                    f"{height:g} but the usable strip height is {usable:g} (strip_height={self.strip_height:g}"
                    f", min_item_separation={self.min_item_separation:g})"
                )

    @property
    def total_demand(self) -> int:
        """Total number of items to pack."""
        return sum(i.demand for i in self.items)

    @property
    def total_item_area(self) -> float:
        """Sum of the areas of all the items to pack (with their demands)."""
        return sum(i.area * i.demand for i in self.items)

    def _ext_ids(self) -> dict[int | str, int]:
        """User id -> numeric id of the JSON. Integer ids are kept, otherwise positions are used."""
        if all(isinstance(i.id, int) for i in self.items):
            return {i.id: i.id for i in self.items}  # type: ignore[misc]
        return {i.id: n for n, i in enumerate(self.items)}

    def to_dict(self) -> dict[str, Any]:
        """The jagua-rs / sparrow JSON form (``ExtSPInstance``). String ids are kept in a ``label`` field."""
        ext = self._ext_ids()
        positional = any(k != v for k, v in ext.items())
        return {
            "name": self.name,
            "min_item_separation": self.min_item_separation,
            "strip_height": self.strip_height,
            "items": [i.to_dict(ext[i.id], with_label=positional) for i in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StripPackingInstance:
        return cls(
            data["strip_height"],
            tuple(Item.from_dict(i) for i in data["items"]),
            name=data.get("name", ""),
            min_item_separation=data.get("min_item_separation", 0.0),
        )

    def to_json_str(self) -> str:
        """JSON in the format read by the sparrow CLI."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json_str(cls, text: str) -> StripPackingInstance:
        """Read the sparrow CLI input format (a sparrow output file is accepted, its solution is ignored)."""
        return cls.from_dict(json.loads(text))

    def validate(self, config: SolverConfig | None = None) -> None:
        """Run the import checks of jagua-rs (shape validity, ...) without solving.

        Raises:
            InvalidInstanceError: if jagua-rs rejects the instance
        """
        from . import _engine

        _engine.validate(self, config)

    def solve(
        self,
        config: SolverConfig | None = None,
        *,
        initial_solution: StripPackingSolution | None = None,
        on_event: Callable[[Event], Any] | None = None,
        events: Collection[type] | None = None,
        on_interrupt: Literal["raise", "return"] = "raise",
    ) -> StripPackingSolution:
        """Solve the instance with sparrow. Blocks, releasing the GIL.

        Args:
            config: the solver configuration. Defaults to ``SolverConfig()`` (600 s, early termination).
            initial_solution: a complete solution (every item placed ``demand`` times) to start from
                instead of sparrow's constructive heuristic (warm start).
            on_event: called with progress events (:mod:`spyrrow.events`) in the calling thread.
                Raise :class:`~spyrrow.errors.StopSolving` in it to stop gracefully; any other exception
                stops the solver and propagates.
            events: the event classes to deliver, default ``spyrrow.events.DEFAULT_EVENTS``.
            on_interrupt: what to do on Ctrl-C: ``"raise"`` (default) raises ``SolveInterrupted``
                (a ``KeyboardInterrupt`` carrying the best solution in ``.solution``), ``"return"``
                returns the best solution with ``interrupted=True``.

        Returns:
            the best solution found

        Raises:
            InvalidInstanceError: jagua-rs rejects the instance
            InvalidConfigError: invalid configuration
            InvalidSolutionError: ``initial_solution`` does not match the instance
            SolverError: the solver failed
            SolveInterrupted: on Ctrl-C, if ``on_interrupt="raise"``
        """
        from . import _engine

        return _engine.solve(
            self,
            config,
            initial_solution=initial_solution,
            on_event=on_event,
            events=events,
            on_interrupt=on_interrupt,
        )
