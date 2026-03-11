import enum
from typing import TypeAlias, Optional, Sequence
from datetime import timedelta

Point: TypeAlias = tuple[float, float]

class Item:
    id: str
    demand: int
    shape: list[Point]
    allowed_orientations: list[float]

    def __init__(
        self,
        id: str,
        shape: Sequence[Point],
        demand: int,
        allowed_orientations: Sequence[float] | None,
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
    """

    id: str
    translation: Point
    rotation: float

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

    def phase_name(self) -> str:
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

    def drain(self) -> list[tuple[ReportType, float, float]]:
        """Drain all pending progress reports from the queue.

        Returns:
            A list of (report_type, strip_width, density) tuples.
        """

class StripPackingConfig:
    early_termination: bool
    seed: int
    exploration_time: timedelta
    compression_time: timedelta
    quadtree_depth: int
    num_workers:Optional[int]
    min_items_separation: Optional[float]

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

        Raises:
            ValueError: If the combination of time arguments is invalid.

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

    def solve(self, config: StripPackingConfig, progress: Optional[ProgressQueue] = None) -> StripPackingSolution:
        """
        The method to solve the instance.

        Args:
            config (StripPackingConfig): The configuration object to control how the instance is solved.
            progress (ProgressQueue, optional): If provided, progress reports are pushed to this
              queue during optimization. Use `queue.drain()` from another thread to monitor progress.
              Defaults to None.

        Returns:
            a StripPackingSolution
        """
