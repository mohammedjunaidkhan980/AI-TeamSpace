from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

NotificationType = Literal[
    "connection_request",
    "connection_accepted",
    "group_invitation",
    "group_membership",
    "group_member_added",
    "new_group_message",
    "ai_response",
    "document_processing_completed",
    "document_processing_failed",
]


class NotificationResponse(BaseModel):
    notification_id: str
    type: NotificationType
    title: str
    description: str
    related_entity_id: str | None = None
    related_entity_type: str | None = None
    group_id: str | None = None
    is_read: bool
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    limit: int
    next_cursor: str | None = None
    unread_count: int


class NotificationUnreadCount(BaseModel):
    unread_count: int


class NotificationReadResult(BaseModel):
    updated_count: int
