from typing import Literal, Self

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, field_validator

from spyrrow import Item, StripPackingInstance


class SparrowSimplePolygon(BaseModel):
    type: Literal["simple_polygon"]
    data: list[tuple[float, float]]


class SparrowRotation(BaseModel):
    mode: Literal["discrete", "stepped", "continuous"]
    angles: list[float] | None = None
    step: float | None = None


class SparrowOrientation(BaseModel):
    rotation: SparrowRotation


class SparrowItem(BaseModel):
    id: int = Field(ge=0)
    demand: PositiveInt
    orientation: SparrowOrientation
    shape: SparrowSimplePolygon
    min_quality: int | None = None

    @field_validator("min_quality", mode="after")
    @classmethod
    def quality_positive(cls, v: int | None):
        if v is not None and v < 0:
            raise ValueError("If a quality is given, it should be positive")
        return v

    @classmethod
    def from_spyrrow_item(cls, idx: int, item: Item) -> Self:
        if item.allowed_orientations is None:
            rotation = SparrowRotation(mode="continuous")
        else:
            rotation = SparrowRotation(mode="discrete", angles=item.allowed_orientations or [0.0])
        return cls(
            id=idx,
            demand=item.demand,
            orientation=SparrowOrientation(rotation=rotation),
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
            items=[SparrowItem.from_spyrrow_item(idx, item) for idx, item in enumerate(instance.items)],
        )
