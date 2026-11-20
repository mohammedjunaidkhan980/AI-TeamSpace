from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DocumentStatus = Literal["uploaded", "pending", "processing", "completed", "failed"]


class DocumentResponse(BaseModel):
    document_id: str
    group_id: str
    filename: str
    file_type: str
    file_size: int
    uploader_id: str
    uploader_name: str
    created_at: datetime
    updated_at: datetime
    status: DocumentStatus
    processing_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    limit: int
    next_cursor: str | None = None


class DocumentRetryResponse(BaseModel):
    document_id: str
    status: DocumentStatus


class DocumentCitation(BaseModel):
    document_id: str
    filename: str
    chunk_index: int
    page_number: int | None = None
    excerpt: str

