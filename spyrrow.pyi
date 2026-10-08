import enum
from typing import TypeAlias, Optional, Sequence, Literal
from datetime import timedelta

Point: TypeAlias = tuple[float, float]

class Item:
    id: str
    demand: int
    shape: list[Point]
    allowed_orientations: list[float]
    reflection_axis: float | None
    rotation_step: float | None

    def __init__(
        self,
        id: str,
        shape: Sequence[Point],
        demand: int,
        allowed_orientations: Sequence[float] | None,
        reflection_axis: float | None = None,
        rotation_step: float | None = None,
    ):
        """
        An Item represents any closed 2D shape by its outer boundary.

        Spyrrow doesn't support hole(s) inside the shape as of yet. Therefore no Item can be nested inside another.

        Args:
            id (str): The Item identifier
              Needs to be unique accross all Items of a StripPackingInstance
            shape: An ordered Sequence of (x,y) defining the shape boundary. The shape is represented as a polygon formed by this Sequence of points.
              The origin point can be included twice as the finishing point. If not, [last point, first point] is infered to be the last straight line of the shape.
            demand: The quantity of identical Items to be placed inside the strip. Should be strictly positive.
            allowed_orientations (Sequence[float]|None): Sequence of angles in degrees allowed.
              An empty Sequence is equivalent to [0.].
              A None value means that the item is free to rotate
              The algorithmn is only very weakly sensible to the length of the Sequence given.
            reflection_axis (float|None): Angle in degrees, from the x axis, of an axis across which the Item may be mirrored. Defaults to None.
              None means that the Item is never reflected.
              When set, the solver is free to place the Item either as is or mirrored across this axis (it is not forced to mirror).
              The axis is taken modulo 180° and is expressed in the Item's own coordinate system, before any rotation.
              The rotations allowed (see `allowed_orientations`) are applied after the reflection.
              For instance, with `allowed_orientations=[]` and `reflection_axis=0.`, the Item can only be mirrored across its x axis.
              Mirrored placements are reported by `PlacedItem.reflected`.
              Note: the sparrow version bundled (0.3.0) only samples the non-reflected orientations, so the solver currently never returns a reflected placement.
              The axis is still imported and validated by the underlying jagua-rs, and will take effect once the solver explores reflections.
            rotation_step (float|None): Angle in degrees of a regular rotation step. Defaults to None.
              The Item is then allowed the angles 0, step, 2*step, ... below 360°.
              Must be in (0, 360] and evenly divide 360° (e.g. 90., 45., 60., 360.). 360. means no rotation.
              Can only be used with `allowed_orientations=None`.

        Raises:
            ValueError: If `reflection_axis` is not finite, if both `allowed_orientations` and `rotation_step` are provided, or if `rotation_step` is not a valid step.
              The attributes can also be set after construction. In this case, the same checks are done by `StripPackingInstance.solve`.
        """

    def to_json_str(self) -> str:
        """Return a string of the JSON representation of the object"""

class PlacedItem:
    """
    An object representing where a copy of an Item was placed inside the strip.

    Attributes:
        id (str): The Item identifier referencing the items of the StripPackingInstance
        rotation (float): The rotation angle in degrees, assuming that the original Item was defined with 0° as its rotation angle.
          Use the origin (0.0,0.0) as the rotation point.
        translation (tuple[float,float]): the translation vector in the X-Y axis. To apply after the rotation
        reflected (bool): Whether the Item is mirrored in this placement. False for Items without a `reflection_axis`.

    The placed shape is obtained from the original Item shape by applying, in this order:

    1. if `reflected`, the mirroring (x, y) -> (x, -y)
    2. the rotation by `rotation` degrees (counter-clockwise), around the origin (0.0,0.0)
    3. the translation by `translation`

    Since mirroring across an axis at angle `a` is the mirroring (x, y) -> (x, -y) followed by a rotation of `2*a`,
    the `rotation` of a reflected placement includes this `2*a` term (modulo 360°).
    """

    id: str
    translation: Point
    rotation: float
    reflected: bool

class StripPackingSolution:
    """
    An object representing the solution to a given StripPackingInstance.

    Can not be directly instanciated. Result from StripPackingInstance.solve.

    Attributes:
        width (float): the width of the strip found to contains all Items. In the same unit as input.
        placed_items (list[PlacedItem]): a list of all PlacedItems, describing how Items are placed in the solution
        density (float): the fraction of the final strip used by items.
    """

    width: float
    density: float
    placed_items: list[PlacedItem]

    def to_json_str(self) -> str:
        """Return a string of the JSON representation of the object"""

class ReportType(enum.IntEnum):
    """The type of progress report emitted by the solver.

    Attributes:
        ExplFeas: Feasible solution found during exploration.
        ExplInfeas: Infeasible solution during exploration.
        ExplImproving: Improving solution during exploration (not yet feasible).
        CmprFeas: Feasible solution found during compression.
        Final: The final solution.
    """
    ExplFeas = 0
    ExplInfeas = 1
    ExplImproving = 2
    CmprFeas = 3
    Final = 4

    def phase_name(self) -> Literal["exploring", "compressing", "final"]:
        """Return a human-readable phase name.

        Returns:
            One of "exploring", "compressing", or "final".
        """

class ProgressQueue:
    """A thread-safe queue that collects progress reports from the solver.

    Create one before calling `solve()` and pass it as the `progress` argument.
    While the solver runs (in a background thread), call `drain()` to retrieve
    any new reports.
    """

    def __init__(self) -> None: ...

    def drain(self) -> list[tuple[ReportType, StripPackingSolution]]:
        """Drain all pending progress reports from the queue.

        Returns:
            A list of (report_type, solution) tuples.
        """

class StripPackingConfig:
    early_termination: bool
    seed: int
    exploration_time: timedelta
    compression_time: timedelta
    quadtree_depth: int
    num_workers:Optional[int]
    min_items_separation: Optional[float]
    max_evaluations: Optional[int]

    def __init__(
        self,
        early_termination: bool = True,
        quadtree_depth: int = 4,
        min_items_separation: Optional[float] = None,
        total_computation_time: Optional[int] = 600,
        exploration_time: Optional[int] = None,
        compression_time: Optional[int] = None,
        num_workers:Optional[int]= None,
        seed: Optional[int] = None,
        max_evaluations: Optional[int] = None,
    ) -> None:
        """Initializes a configuration object for the strip packing algorithm.

        Either `total_computation_time`, or both `exploration_time` and `compression_time`, must be provided. 
          Providing all three or only one of the latter two raises an error.
        If `total_computation_time` is provided, 80% of it is allocated to exploration and 20% to compression.
        If `seed` is not provided, a random seed will be generated.

        
        Args:
            early_termination (bool, optional): Whether to allow early termination of the algorithm. Defaults to True.
            quadtree_depth (int, optional): Maximum depth of the quadtree used by the collision detection engine jagua-rs. 
              Must be positive, common values are 3,4,5. Defaults to 4.
            min_items_separation (Optional[float], optional): Minimum required distance between packed items. Defaults to None.
            total_computation_time (Optional[int], optional): Total time budget in seconds. 
              Used if `exploration_time` and `compression_time` are not provided. Defaults to 600.
            exploration_time (Optional[int], optional): Time in seconds allocated to exploration. Defaults to None.
            compression_time (Optional[int], optional): Time in seconds allocated to compression. Defaults to None.
            num_workers (Optional[int], optional): Number of threads used by the collision detection engine during exploration.
              When set to None, detect the number of logical CPU cores on the execution plateform. Defaults to None.
            seed (Optional[int], optional): Optional random seed to give reproductibility. If None, a random seed is generated. Defaults to None.
            max_evaluations (Optional[int], optional): Budget of evaluations (candidate placements evaluated by sparrow), split between
              exploration and compression in the same proportion as their times. Each phase stops at its budget or its time limit,
              whichever comes first. The budget is checked after each separation, so a phase can slightly exceed it.
              Unlike time, the work done for a given budget does not depend on the speed of the machine:
              with a fixed `seed` and a time limit large enough not to be reached, a run gives the same result on any machine
              (up to floating point differences between CPU architectures).
              When set, compression shrinks its steps after failures (as with `early_termination`) instead of over time.
              Must be strictly positive. Defaults to None (no budget).

        Raises:
            ValueError: If the combination of time arguments is invalid, or if `max_evaluations` is 0.

        """

    def to_json_str(self)->str:
        """Return a string of the JSON representation of the object

        Returns:
            str
        """

class StripPackingInstance:
    name: str
    strip_height: float
    items: list[Item]

    def __init__(self, name: str, strip_height: float, items: Sequence[Item]):
        """
        An Instance of a Strip Packing Problem.

        Args:
            name (str): The name of the instance. Required by the underlying sparrow library.
              An empty string '' can be used, if the user doesn't have a use for this name.
            strip_height (float): the fixed height of the strip. The unit should be compatible with the Item
            items (Sequence[Item]): The Items which defines the instances. All Items should be defined with the same scale ( same length unit).
         Raises:
            ValueError
        """
    def to_json_str(self) -> str:
        """Return a string of the JSON representation of the object"""

    def to_sparrow_json_str(
        self,
        config: Optional[StripPackingConfig] = None,
        solution: Optional[StripPackingSolution] = None,
    ) -> str:
        """
        Return a JSON string in the input format of the sparrow command line tool (and Sparrow Studio),
        to reproduce or debug a spyrrow run outside of Python.

        Without `solution`, the result is an instance file, to be given to `sparrow -i`.
        With `solution`, the instance and the solution are put in a single document (the format of
        the output of sparrow), which `sparrow -i` uses as a warm start.
        Items are identified by their index in `items` (the string ids are not exported).
        Only `min_items_separation` of the configuration is part of the instance;
        the time limits, seed, number of workers, ... are options of the sparrow command line.

        Warning: the solution is exported as is. If `config` has a `min_items_separation` (or the instance a
        `strip_height`) different from the one the solution was computed with, the exported warm start is
        infeasible, and the sparrow command line handles an infeasible start poorly (it may run far past its
        time limit, or return the infeasible layout). Export a solution with the config it was solved with.

        Args:
            config (StripPackingConfig, optional): If given, its `min_items_separation` is exported
              as the minimum separation of the instance. Defaults to None, meaning no separation.
            solution (StripPackingSolution, optional): A solution of this instance to export along with it.
              Defaults to None.

        Raises:
            ValueError: If the solution places an item which is not an item of the instance.
        """

    def solve(
        self,
        config: StripPackingConfig,
        progress: Optional[ProgressQueue] = None,
        initial_solution: Optional[StripPackingSolution] = None,
    ) -> StripPackingSolution:
        """
        The method to solve the instance.

        Args:
            config (StripPackingConfig): The configuration object to control how the instance is solved.
            progress (ProgressQueue, optional): If provided, progress reports are pushed to this
              queue during optimization. Use `queue.drain()` from another thread to monitor progress.
              Defaults to None.
            initial_solution (StripPackingSolution, optional): A solution to warm start from, instead of
              building one from scratch. Typically the result of a previous `solve` of the same instance.
              It must place every item exactly `demand` times, using the ids of this instance.
              Its width is used as the starting strip width, and the solver then tries to shrink it:
              if the solution is feasible, the returned width is not larger than its width.
              The strip height is always the one of this instance, and is not checked against the solution:
              a solution computed for another strip height or another set of items is not meaningful.
              The solution must be feasible for this instance and this config (no overlap, items inside the strip,
              `min_items_separation` respected), otherwise a ValueError is raised: the solver assumes a feasible start.
              A solution computed with a smaller separation or another strip height is typically not feasible.
              Ignored for an instance without items (which must then be given an empty solution).
              Defaults to None.

        Returns:
            a StripPackingSolution

        Raises:
            ValueError: If the instance can not be imported by the solver (invalid shape, separation larger than the strip height, ...),
              or if the initial solution is not valid for this instance (unknown item id, item count different from the demand, invalid width, infeasible layout, ...)
            RuntimeError: If the solver fails to build an initial solution
        """
