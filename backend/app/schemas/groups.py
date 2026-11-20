from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.schemas.users import PublicUserProfile


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    member_ids: list[str] = Field(default_factory=list, max_length=100)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Group name cannot be blank")
        return value

    @field_validator("member_ids")
    @classmethod
    def validate_member_ids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not len(value) == 24 or any(
                character not in "0123456789abcdefABCDEF" for character in value
            ):
                raise ValueError("Member IDs must be valid MongoDB ObjectIds")
            value = value.lower()
            if value in seen:
                raise ValueError("Member IDs must not contain duplicates")
            seen.add(value)
            normalized.append(value)
        return normalized


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    group_picture_url: HttpUrl | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Group name cannot be null")
        value = value.strip()
        if not value:
            raise ValueError("Group name cannot be blank")
        return value

    @model_validator(mode="after")
    def require_update_fields(self) -> "GroupUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one group field must be provided")
        return self


class AddGroupMembers(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=100)

    model_config = ConfigDict(extra="forbid")

    @field_validator("user_ids")
    @classmethod
    def validate_user_ids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            if len(value) != 24 or any(
                character not in "0123456789abcdefABCDEF" for character in value
            ):
                raise ValueError("User IDs must be valid MongoDB ObjectIds")
            value = value.lower()
            if value in seen:
                raise ValueError("User IDs must not contain duplicates")
            seen.add(value)
            normalized.append(value)
        return normalized


class GroupMember(BaseModel):
    user: PublicUserProfile
    role: Literal["admin", "member"]
    joined_at: datetime


class GroupListItem(BaseModel):
    group_id: str
    name: str
    description: str | None = None
    creator_id: str
    created_at: datetime
    member_count: int
    current_user_role: Literal["admin", "member"]
    last_message_at: datetime | None = None


class GroupListResponse(BaseModel):
    items: list[GroupListItem]
    limit: int
    offset: int


class GroupDetails(BaseModel):
    group_id: str
    name: str
    description: str | None = None
    creator_id: str
    group_picture_url: HttpUrl | None = None
    members: list[GroupMember]
    member_count: int
    created_at: datetime
    updated_at: datetime
    settings: dict[str, object]
    ai_agents: list[dict[str, object]]
    last_message_at: datetime | None = None
    nexconn_channel_id: str | None = None
    nexconn_sync_status: Literal["pending", "synced", "failed", "disabled"] = "disabled"
    nexconn_synced_at: datetime | None = None


class GroupCreatedResponse(GroupDetails):
    pass


class AddedMembersResponse(BaseModel):
    members: list[GroupMember]
    nexconn_sync_status: Literal["pending", "synced", "failed", "disabled"] = "disabled"
