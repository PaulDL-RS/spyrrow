import enum
from typing import TypeAlias, Optional, Sequence, Literal
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

    def phase_name(self) -> Literal["exploring", "compressing", "final"]:
        """Return a human-readable phase name.

        Returns:
            One of "exploring", "compressing", or "final".
        """

class OptimizationPhase(enum.IntEnum):
    """A phase of the optimization, as announced by a `PhaseEvent`.

    Attributes:
        Exploration: The solver is searching for a feasible strip width.
        Compression: The solver is squeezing the best feasible solution.
    """
    Exploration = 0
    Compression = 1

class PhaseEvent:
    """The solver entered a new optimization phase.

    Attributes:
        phase: the phase that just started.
    """
    phase: OptimizationPhase

class SeparationProgressEvent:
    """Progress of one separation attempt (the solver tries to remove all overlaps at a given strip width).

    Emitted once for the initial layout (`iteration == 0`), then after each completed iteration.
    This is a high-frequency event.

    Attributes:
        strip_width: the strip width being separated.
        density: the density of the layout, as a fraction in [0, 1] (same convention as `StripPackingSolution.density`).
        iteration: the iteration counter within the separation attempt.
        min_loss: the lowest overlap loss found so far in this attempt; 0.0 means the layout is feasible.
    """
    strip_width: float
    density: float
    iteration: int
    min_loss: float

class SeparationResultEvent:
    """Outcome of a finished separation attempt.

    Attributes:
        success: whether all overlaps were removed.
        elapsed_seconds: wall-clock duration of the attempt.
        total_evals: number of placement evaluations performed.
        total_moves: number of item moves performed.
        iterations: number of iterations performed.
    """
    success: bool
    elapsed_seconds: float
    total_evals: int
    total_moves: int
    iterations: int

class CompressionProgressEvent:
    """The compression phase starts a new attempt to shrink the strip.

    Attributes:
        shrink_step: the relative shrink of the strip width attempted (0.001 means 0.1%).
    """
    shrink_step: float

ProgressEvent: TypeAlias = (
    PhaseEvent | SeparationProgressEvent | SeparationResultEvent | CompressionProgressEvent
)

class ProgressQueue:
    """A thread-safe queue that collects progress reports from the solver.

    Create one before calling `solve()` and pass it as the `progress` argument.
    While the solver runs (in a background thread), call `drain()` to retrieve
    any new reports.

    With `detailed=True`, the queue additionally records fine-grained solver events
    (phase changes, separation progress, compression attempts), retrieved with `drain_events()`.
    These are kept apart from `drain()`, which is never affected by `detailed`.
    Separation progress events are high-frequency (one per solver iteration, typically
    hundreds to thousands per second), so the event buffer is bounded: when it holds
    `max_events` events, the oldest one is dropped to make room. Call `drain_events()`
    regularly to avoid losing events; `dropped_events` counts what was lost.
    The reports retrieved by `drain()` are not bounded.

    Example::

        queue = spyrrow.ProgressQueue(detailed=True)
        # run solve in a thread, passing progress=queue
        for report_type, solution in queue.drain():
            print(f"{report_type.phase_name()}: width={solution.width:.1f}")
        for event in queue.drain_events():
            if isinstance(event, spyrrow.PhaseEvent):
                print(f"entered {event.phase}")
    """

    detailed: bool
    max_events: int
    dropped_events: int

    def __init__(self, detailed: bool = False, max_events: int = 10000) -> None:
        """
        Args:
            detailed: Whether to also record fine-grained events. Defaults to False.
            max_events: Capacity of the event buffer. Must be strictly positive.
              Only used if `detailed` is True. Defaults to 10000.

        Raises:
            ValueError: If `max_events` is zero.
        """

    def drain(self) -> list[tuple[ReportType, StripPackingSolution]]:
        """Drain all pending progress reports from the queue.

        Returns:
            A list of (report_type, solution) tuples.
        """

    def drain_events(self) -> list[ProgressEvent]:
        """Drain all pending detailed events from the queue, oldest first.

        Always empty if the queue was not created with `detailed=True`.
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
              queue during optimization. Use `queue.drain()` (and `queue.drain_events()` for a detailed queue)
              from another thread to monitor progress.
              Defaults to None.

        Returns:
            a StripPackingSolution

        Raises:
            ValueError: If the instance can not be imported by the solver (invalid shape, separation larger than the strip height, ...)
            RuntimeError: If the solver fails to build an initial solution
        """
