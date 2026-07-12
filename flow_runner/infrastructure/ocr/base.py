from pydantic import BaseModel, ConfigDict, Field


class OcrItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    bounds: tuple[int, int, int, int] | None = None
    confidence: float | None = None


class OcrObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    items: list[OcrItem] = Field(default_factory=list)
