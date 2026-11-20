from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.users import PublicUserProfile


class FriendRequestCreate(BaseModel):
    recipient_id: str = Field(pattern=r"^[0-9a-fA-F]{24}$")


class ConnectionRequestResponse(BaseModel):
    id: str
    sender: PublicUserProfile
    recipient: PublicUserProfile
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime
    updated_at: datetime


class ConnectionRequestsPage(BaseModel):
    items: list[ConnectionRequestResponse]
    limit: int
    offset: int


class ConnectionsPage(BaseModel):
    items: list[PublicUserProfile]
    limit: int
    offset: int


class FriendRequestActionResponse(BaseModel):
    id: str
    status: Literal["pending", "accepted", "rejected"]
    message: str

    model_config = ConfigDict(from_attributes=True)
