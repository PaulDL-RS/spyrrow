type Point = tuple[float,float]

type ItemId = int

class Item:
    demand:int
    shape:list[Point]
    allowed_orientations: list[float] |None

    def __init__(self, shape:list[Point], demand:int,allowed_orientations: list[float] |None): ...

class PlacedItem:
    id:int
    shape:list[Point]
    translation: Point
    rotation:float

class StripPackingSolution:
    width: float
    density: float
    placed_items: list[PlacedItem]

class StripPackingInstance:
    name:str
    height:float
    items: list[Item]

    def __init__(self, name:str, height:float, items:list[Item]): ...

    def solve(self, computation_time:int|None)-> StripPackingSolution: ...