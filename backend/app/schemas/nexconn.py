from typing import Literal

from pydantic import BaseModel


class NexconnTokenResponse(BaseModel):
    nexconn_token: str
    nexconn_user_id: str
    app_key: str


class NexconnStatusResponse(BaseModel):
    enabled: bool
    status: Literal["enabled", "disabled"]


class GroupChatChannelResponse(BaseModel):
    group_id: str
    channel_id: str
    sync_status: Literal["synced"]
