import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class NexconnAPIError(Exception):
    """Raised when Nexconn rejects a request or cannot be reached."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class NexconnMessageReceipt:
    channel_id: str
    message_id: str

class NexconnClient:
    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(
            base_url=settings.nexconn_api_base_url,
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(max_keepalive_connections=0),
        )
        self._owns_http_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    def _signed_headers(self) -> dict[str, str]:
        nonce = uuid4().hex[:18]
        timestamp = str(int(time.time() * 1000))
        signature = hashlib.sha1(
            f"{self._settings.nexconn_app_secret}{nonce}{timestamp}".encode("utf-8")
        ).hexdigest()
        return {
            "App-Key": self._settings.nexconn_app_key,
            "Nonce": nonce,
            "Timestamp": timestamp,
            "Signature": signature,
            "X-Request-ID": str(uuid4()),
        }

    async def _post(
        self, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            response = await self._http.post(
                path,
                json=payload,
                headers=self._signed_headers(),
            )
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as exc:
            retryable = (
                exc.response.status_code == 429
                or exc.response.status_code >= 500
            )
            logger.warning(
                "Nexconn request failed [%s %s] %s",
                exc.response.status_code,
                path,
                exc.response.text[:500],
            )
            raise NexconnAPIError(
                "Nexconn request failed",
                retryable=retryable,
            ) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning(
                "Nexconn request failed",
                extra={
                    "endpoint": path,
                    "error_type": type(exc).__name__,
                    "retryable": True,
                    "detail": str(exc),
                },
            )
            raise NexconnAPIError(
                "Nexconn request failed",
                retryable=True,
            )
        except ValueError as exc:
            logger.warning(
                "Nexconn returned an invalid response",
                extra={"endpoint": path, "error_type": type(exc).__name__, "detail": str(exc)},
            )
            raise NexconnAPIError("Nexconn request failed") from exc

        if not isinstance(result, dict) or result.get("code") != 0:
            logger.warning(
                "Nexconn returned an unsuccessful response",
                extra={"endpoint": path, "code": result.get("code") if isinstance(result, dict) else None, "body": str(result)[:300]},
            )
            raise NexconnAPIError("Nexconn request was rejected")
        return result

    async def issue_access_token(
        self,
        *,
        user_id: str,
        name: str,
        avatar_url: str | None,
    ) -> str:
        payload: dict[str, Any] = {"userId": user_id, "name": name}
        if avatar_url:
            payload["avatarUrl"] = avatar_url
        response = await self._post("/v4/auth/access-token/issue", payload)
        result = response.get("result")
        token = result.get("accessToken") if isinstance(result, dict) else None
        result_user_id = result.get("userId") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token or (
            result_user_id is not None and result_user_id != user_id
        ):
            logger.warning(
                "Nexconn token response did not match the requested user",
                extra={"endpoint": "/v4/auth/access-token/issue"},
            )
            raise NexconnAPIError("Nexconn returned an invalid token response")
        return token

    async def update_user(
        self, *, user_id: str, name: str, avatar_url: str | None
    ) -> None:
        payload: dict[str, Any] = {"userId": user_id, "name": name}
        if avatar_url:
            payload["avatarUrl"] = avatar_url
        await self._post("/v4/user/update", payload)

    async def send_group_message(
        self,
        *,
        sender_user_id: str,
        channel_id: str,
        content: str,
    ) -> NexconnMessageReceipt:
        if len(content.encode("utf-8")) > 10 * 1024:
            raise NexconnAPIError("Nexconn message content exceeds 10 KB")
        response = await self._post(
            "/v4/group-channel/message/send",
            {
                "fromUserId": sender_user_id,
                "toChannelIds": [channel_id],
                "messageType": "RC:TxtMsg",
                "content": json.dumps({"content": content, "extra": ""}),
                "shouldPersist": 1,
                "isEchoToSender": 0,
            },
        )
        result = response.get("result")
        message_ids = result.get("messageIds") if isinstance(result, dict) else None
        if not isinstance(message_ids, list):
            raise NexconnAPIError("Nexconn returned an invalid message receipt")
        receipt = next(
            (
                item
                for item in message_ids
                if isinstance(item, dict) and item.get("channelId") == channel_id
            ),
            None,
        )
        message_id = receipt.get("messageId") if receipt else None
        if not isinstance(message_id, str) or not message_id:
            raise NexconnAPIError("Nexconn returned an invalid message receipt")
        return NexconnMessageReceipt(channel_id=channel_id, message_id=message_id)

    async def create_group_channel(
        self,
        *,
        channel_id: str,
        name: str,
        owner: str,
        user_ids: list[str],
        description: str | None,
        picture_url: str | None,
    ) -> None:
        group_profile: dict[str, Any] = {}
        if description:
            group_profile["introduction"] = description
        if picture_url:
            group_profile["portraitUrl"] = picture_url
        payload: dict[str, Any] = {
            "channelId": int(channel_id),
            "name": name,
            "owner": owner,
        }
        if user_ids:
            payload["userIds"] = user_ids
        if group_profile:
            payload["groupProfile"] = group_profile
        await self._post("/v4/group-channel/create", payload)

    async def join_group_channel(
        self, *, channel_id: str, user_ids: list[str]
    ) -> None:
        if user_ids:
            await self._post(
                "/v4/group-channel/join",
                {"channelId": int(channel_id), "userIds": user_ids},
            )

    async def remove_group_members(
        self, *, channel_id: str, user_ids: list[str]
    ) -> None:
        if user_ids:
            await self._post(
                "/v4/group-channel/leave",
                {"channelId": int(channel_id), "userIds": user_ids},
            )

    async def update_group_channel_profile(
        self,
        *,
        channel_id: str,
        description: str | None,
        picture_url: str | None,
    ) -> None:
        await self._post(
            "/v4/group-channel/profile/update",
            {
                "channelId": int(channel_id),
                "groupProfile": {
                    "introduction": description,
                    "portraitUrl": picture_url,
                },
            },
        )
