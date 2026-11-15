from pydantic import BaseModel, Field
from typing import Any


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class CompareRequest(BaseModel):
    study_ids: list[str] = Field(min_length=2, max_length=4)


class ExplainRequest(BaseModel):
    study_id: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict[str, Any]] = []


class UploadMetadata(BaseModel):
    filename: str
    content_type: str | None = None
