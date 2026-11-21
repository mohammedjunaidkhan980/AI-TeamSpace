from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MessageType = Literal["text", "file", "image", "system"]
SenderType = Literal["user", "agent", "system"]
AIProcessingStatus = Literal[
    "not_required", "pending", "processing", "completed", "failed"
]


class MessageAttachment(BaseModel):
    type: Literal["file", "image"]
    url: str = Field(max_length=2048)
    name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=255)
    size: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class MessageSender(BaseModel):
    id: str
    type: SenderType
    name: str


class MessageResponse(BaseModel):
    message_id: str
    group_id: str
    nexconn_message_id: str | None = None
    sender: MessageSender
    content: str
    message_type: MessageType
    attachments: list[MessageAttachment] = Field(default_factory=list)
    reply_to_message_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    agent_id: str | None = None
    agent_name: str | None = None
    orchestration_id: str | None = None
    delivery_status: Literal["pending", "sending", "delivered", "failed"] | None = None
    ai_processing_status: AIProcessingStatus = "not_required"


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=65536)
    message_type: Literal["text"] = "text"
    attachments: list[MessageAttachment] = Field(default_factory=list, max_length=10)
    reply_to_message_id: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message content cannot be blank")
        if "\x00" in normalized:
            raise ValueError("Message content contains an invalid null byte")
        return normalized


class MessageHistoryResponse(BaseModel):
    items: list[MessageResponse]
    limit: int
    next_cursor: str | None = None


class GroupMessageStats(BaseModel):
    total_message_count: int
    human_message_count: int
    ai_message_count: int
    latest_message_at: datetime | None = None


class NexconnMessageData(BaseModel):
    user_id: str = Field(alias="userId", min_length=1, max_length=128)
    channel_id: str = Field(alias="channelId", min_length=1, max_length=128)
    message_type: str = Field(alias="messageType", min_length=1, max_length=128)
    content: str = Field(max_length=65536)
    channel_type: int = Field(alias="channelType")
    time: int = Field(gt=0)
    message_id: str = Field(alias="messageId", min_length=1, max_length=256)
    os: str = Field(min_length=1, max_length=64)
    profanity_type: int | None = Field(default=None, alias="profanityType")
    ai_generated: bool | None = Field(default=None, alias="aiGenerated")
    original_message_id: str | None = Field(
        default=None, alias="originalMessageId", max_length=256
    )
    group_user_ids: list[str] | None = Field(
        default=None, alias="groupUserIds", max_length=100
    )

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @field_validator("content")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Message content contains an invalid null byte")
        return value


class NexconnMessageWebhook(BaseModel):
    type: Literal["message:send"]
    id: str = Field(min_length=1, max_length=256)
    time: int = Field(gt=0)
    data: list[NexconnMessageData] = Field(min_length=1, max_length=100)

    model_config = ConfigDict(extra="ignore")


class NexconnWebhookResponse(BaseModel):
    accepted: int
    duplicates: int
