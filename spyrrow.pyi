from typing import TypeAlias

Point: TypeAlias = tuple[float, float]

class Item:
    id: str
    demand: int
    shape: list[Point]
    allowed_orientations: list[float]

    def __init__(
        self,
        id: str,
        shape: list[Point],
        demand: int,
        allowed_orientations: list[float] | None,
    ):
        """
        An Item represents any closed 2D shape by its outer boundary.

        Spyrrow doesn't support hole(s) inside the shape as of yet. Therefore no Item can be nested inside another.

        Args:
            id (str): The Item identifier
              Needs to be unique accross all Items of a StripPackingInstance
            shape: An ordered list of (x,y) defining the shape boundary. The shape is represented as a polygon formed by this list of points.
              The origin point can be included twice as the finishing point. If not, [last point, first point] is infered to be the last straight line of the shape.
            demand: The quantity of identical Items to be placed inside the strip. Should be positive.
            allowed_orientations (list[float]|None): List of angles in degrees allowed.
              An empty list is equivalent to [0.].
              A None value means that the item is free to rotate
              The algorithmn is only very weakly sensible to the length of the list given.

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

class StripPackingInstance:
    name: str
    strip_height: float
    items: list[Item]

    def __init__(self, name: str, strip_height: float, items: list[Item]):
        """
        An Instance of a Strip Packing Problem.

        Args:
            name (str): The name of the instance. Required by the underlying sparrow library.
              An empty string '' can be used, if the user doesn't have a use for this name.
            strip_height (float): the fixed height of the strip. The unit should be compatible with the Item
            items (list[Item]): The Items which defines the instances. All Items should be defined with the same scale ( same length unit).
         Raises:
            ValueError
        """
    def to_json_str(self) -> str:
        """Return a string of the JSON representation of the object"""

    def solve(self, computation_time: int = 600) -> StripPackingSolution:
        """
        The method to solve the instance.

        Args:
            computation_time (int): The total computation time in seconds used to find a solution.
              The algorithm won't exit early.Waht you input is what you get. Default is 600 s = 10 minutes.

        Returns:
            a StripPackingSolution
        """
