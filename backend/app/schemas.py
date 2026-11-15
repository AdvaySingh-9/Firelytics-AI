from pydantic import BaseModel, Field
from typing import Any

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)

class CompareRequest(BaseModel):
    study_ids: list[str] = Field(min_length=2, max_length=4)
    upload_study_id: str | None = None
    uploaded_data: list[dict[str, Any]] = Field(default_factory=list, max_length=200)

class ExplainRequest(BaseModel):
    study_id: str
    session_id: str | None = None
    uploaded_data: list[dict[str, Any]] = Field(default_factory=list, max_length=20)

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict[str, Any]] = Field(default_factory=list)
    session_id: str | None = None

class UploadMetadata(BaseModel):
    filename: str
    content_type: str | None = None

class SessionCreateRequest(BaseModel):
    study_id: str = Field(min_length=3, max_length=40)

class SessionQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[dict[str, Any]] = Field(default_factory=list)
    uploaded_data: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class SessionDatasetRequest(BaseModel):
    question: str = Field(default="Analyze the uploaded experimental dataset and explain its contents and relevance", max_length=2000)
    uploaded_data: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class SessionIngestRequest(BaseModel):
    batch_size: int = Field(default=8, ge=1, le=20)


class SessionDirectDownloadRequest(BaseModel):
    """A fresh direct file URL copied from the official NASA PSI browser."""
    url: str = Field(min_length=20, max_length=8192)
    filename: str | None = Field(default=None, max_length=255)
