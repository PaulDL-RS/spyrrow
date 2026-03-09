from typing import Literal, Self

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, field_validator

from spyrrow import Item, StripPackingInstance


class SparrowSimplePolygon(BaseModel):
    type: Literal["simple_polygon"]
    data: list[tuple[float, float]]


class SparrowItem(BaseModel):
    id: str = Field(min_length=1)
    demand: PositiveInt
    allowed_orientations: list[float] | None = None
    shape: SparrowSimplePolygon
    min_quality: int | None = None

    @field_validator("min_quality", mode="after")
    @classmethod
    def quality_positive(cls, v: int | None):
        if v is not None and v < 0:
            raise ValueError("If a quality is given, it should be positive")
        return v

    @classmethod
    def from_spyrrow_item(cls, item: Item) -> Self:
        return cls(
            id=item.id,
            demand=item.demand,
            allowed_orientations=item.allowed_orientations,
            shape=SparrowSimplePolygon(type="simple_polygon", data=item.shape),
        )


class SparrowJsonInstance(BaseModel):
    name: str = Field(min_length=1)
    items: list[SparrowItem]
    strip_height: PositiveFloat

    @classmethod
    def from_spyrrow_instance(cls, instance: StripPackingInstance) -> Self:
        return cls(
            name=instance.name,
            strip_height=instance.strip_height,
            items=[SparrowItem.from_spyrrow_item(item) for item in instance.items],
        )
