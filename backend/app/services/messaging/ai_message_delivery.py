import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Protocol

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.repositories.messages import create_message
from app.repositories.orchestrations import get_orchestration_run
from app.services.nexconn import NexconnAPIError
from app.services.notifications import notify_group_members_best_effort

logger = logging.getLogger(__name__)
AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{1,24}$")


class NexconnMessageSender(Protocol):
    async def issue_access_token(
        self, *, user_id: str, name: str, avatar_url: str | None
    ) -> str: ...

    async def send_group_message(
        self, *, sender_user_id: str, channel_id: str, content: str
    ) -> Any: ...


class AIMessageDeliveryService:
    def __init__(
        self,
        database: Database[dict[str, Any]],
        settings: Settings,
        client: NexconnMessageSender | None,
    ) -> None:
        self._database = database
        self._settings = settings
        self._client = client

    @staticmethod
    def _identity_id(group_id: ObjectId, agent_id: str) -> str:
        if agent_id != "coordinator" and not AGENT_ID_PATTERN.fullmatch(agent_id):
            raise ValueError("Invalid AI agent identity")
        # Nexconn user IDs are alphanumeric and limited to 64 bytes.
        identity = f"ai{group_id}{agent_id}"
        if len(identity.encode("ascii")) > 64:
            raise ValueError("AI identity exceeds Nexconn user ID limit")
        return identity

    async def _prepare_messages(
        self,
        orchestration_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        run = await get_orchestration_run(
            self._database,
            orchestration_id=orchestration_id,
        )
        if run is None:
            raise ValueError("Orchestration run not found")
        if run.get("status") != "completed" or not run.get("final_response"):
            raise ValueError("Orchestration has no completed response")

        group = await self._database["groups"].find_one({"_id": run["group_id"]})
        if group is None:
            raise ValueError("Orchestration group not found")
        channel_id = group.get("nexconn_channel_id")
        if not isinstance(channel_id, str) or not channel_id.strip():
            raise ValueError("Orchestration group has no Nexconn channel mapping")
        messages_to_deliver: list[dict[str, str]] = []
        if self._settings.ai_response_delivery_mode == "agents_and_coordinator":
            for result in run.get("agent_results", []):
                if (
                    result.get("status") == "completed"
                    and result.get("response")
                    and result.get("agent_id")
                    and ObjectId.is_valid(result["agent_id"])
                ):
                    agent = await self._database["agents"].find_one(
                        {
                            "_id": ObjectId(result["agent_id"]),
                            "group_id": run["group_id"],
                            "enabled": True,
                            "deleted_at": {"$exists": False},
                        }
                    )
                    if agent is None:
                        continue
                    messages_to_deliver.append(
                        {
                            "agent_id": result["agent_id"],
                            "agent_name": agent["name"],
                            "content": result["response"],
                        }
                    )
        messages_to_deliver.append(
            {
                "agent_id": "coordinator",
                "agent_name": "AI TeamSpace Coordinator",
                "content": run["final_response"],
            }
        )

        persisted: list[dict[str, Any]] = []
        for item in messages_to_deliver:
            delivery_key = f"{orchestration_id}:{item['agent_id']}"
            existing = await self._database["messages"].find_one(
                {"delivery_key": delivery_key}
            )
            if existing is not None:
                persisted.append(existing)
                continue
            sender_user_id = self._identity_id(run["group_id"], item["agent_id"])
            now = datetime.now(timezone.utc)
            try:
                message, _ = await create_message(
                    self._database,
                    group_id=run["group_id"],
                    nexconn_channel_id=channel_id,
                    nexconn_message_id=None,
                    sender_id=sender_user_id,
                    sender_type="agent",
                    sender_name=item["agent_name"],
                    content=item["content"],
                    message_type="text",
                    attachments=[],
                    reply_to_message_id=run["message_id"],
                    metadata={
                        "orchestration_id": orchestration_id,
                        "agent_id": item["agent_id"],
                        "agent_name": item["agent_name"],
                        "citations": run.get("citations", []),
                    },
                    created_at=now,
                    ai_processing_status="not_required",
                    orchestration_id=orchestration_id,
                    agent_id=item["agent_id"],
                    agent_name=item["agent_name"],
                    delivery_key=delivery_key,
                    delivery_status="pending",
                    delivery_retry_count=0,
                )
            except DuplicateKeyError:
                message = await self._database["messages"].find_one(
                    {"delivery_key": delivery_key}
                )
                if message is None:
                    raise
            persisted.append(message)

        await self._update_run_delivery_status(orchestration_id, persisted)
        return run, persisted

    async def queue_orchestration(
        self,
        orchestration_id: str,
    ) -> tuple[str, str | None]:
        _, messages = await self._prepare_messages(orchestration_id)
        if messages and all(item.get("delivery_status") == "delivered" for item in messages):
            return "delivered", str(messages[-1]["_id"])
        if self._client is None or not self._settings.nexconn_enabled:
            return "pending", str(messages[-1]["_id"]) if messages else None
        return "pending", str(messages[-1]["_id"]) if messages else None

    async def deliver_orchestration(self, orchestration_id: str) -> None:
        try:
            run, messages = await self._prepare_messages(orchestration_id)
        except ValueError as exc:
            logger.warning(
                "AI message delivery was not prepared",
                extra={
                    "orchestration_id": orchestration_id,
                    "error_type": type(exc).__name__,
                },
            )
            return

        group = await self._database["groups"].find_one({"_id": run["group_id"]})
        if self._client is None or not self._settings.nexconn_enabled:
            for message in messages:
                if message.get("delivery_status") != "delivered":
                    await self._mark_failed(
                        message,
                        "Nexconn delivery is disabled or unavailable.",
                        increment_retry=False,
                    )
            await self._update_run_delivery_status(orchestration_id, messages)
            return
        if (
            group is None
            or not isinstance(group.get("nexconn_channel_id"), str)
            or not group["nexconn_channel_id"].strip()
        ):
            for message in messages:
                if message.get("delivery_status") != "delivered":
                    await self._mark_failed(
                        message,
                        "Nexconn channel mapping is unavailable.",
                        increment_retry=False,
                    )
            await self._update_run_delivery_status(orchestration_id, messages)
            return
        if group.get("nexconn_sync_status") not in {"synced", None}:
            for message in messages:
                if message.get("delivery_status") != "delivered":
                    await self._mark_failed(
                        message,
                        "Nexconn channel is not synchronized.",
                        increment_retry=False,
                    )
            await self._update_run_delivery_status(orchestration_id, messages)
            return

        for message in messages:
            if message.get("delivery_status") == "delivered":
                continue
            await self._deliver_message(message, group["nexconn_channel_id"])
        await self._update_run_delivery_status(orchestration_id, messages)

    async def _deliver_message(
        self,
        message: dict[str, Any],
        channel_id: str,
    ) -> None:
        if self._client is None:
            return
        now = datetime.now(timezone.utc)
        claimed = await self._database["messages"].find_one_and_update(
            {
                "_id": message["_id"],
                "delivery_status": {"$in": ["pending", "failed"]},
            },
            {
                "$set": {
                    "delivery_status": "sending",
                    "delivery_error": None,
                    "updated_at": now,
                }
            },
            return_document=True,
        )
        if claimed is None:
            return

        sender_id = claimed.get("sender_id")
        sender_name = claimed.get("sender_name", "AI TeamSpace")[:64]
        if not isinstance(sender_id, str):
            await self._mark_failed(
                claimed,
                "AI sender identity is invalid.",
                increment_retry=False,
            )
            return

        attempts = self._settings.nexconn_delivery_max_retries + 1
        for attempt in range(attempts):
            try:
                await self._client.issue_access_token(
                    user_id=sender_id,
                    name=sender_name,
                    avatar_url=None,
                )
                receipt = await self._client.send_group_message(
                    sender_user_id=sender_id,
                    channel_id=channel_id,
                    content=claimed["content"],
                )
                delivered_at = datetime.now(timezone.utc)
                await self._database["messages"].update_one(
                    {"_id": claimed["_id"]},
                    {
                        "$set": {
                            "delivery_status": "delivered",
                            "delivery_retry_count": attempt,
                            "delivery_error": None,
                            "delivered_at": delivered_at,
                            "nexconn_message_id": receipt.message_id,
                            "updated_at": delivered_at,
                        }
                    },
                )
                if claimed.get("agent_id") == "coordinator":
                    run = await get_orchestration_run(
                        self._database,
                        orchestration_id=claimed.get("orchestration_id", ""),
                    )
                    group = (
                        await self._database["groups"].find_one(
                            {"_id": claimed["group_id"]}
                        )
                        if run is not None
                        else None
                    )
                    source = (
                        await self._database["messages"].find_one(
                            {"_id": run["message_id"]}
                        )
                        if run is not None
                        else None
                    )
                    if group is not None:
                        await notify_group_members_best_effort(
                            self._database,
                            group=group,
                            event_key=f"ai-response:{claimed.get('orchestration_id')}",
                            notification_type="ai_response",
                            title="AI response ready",
                            description=f"{sender_name} responded in {group.get('name', 'your group')}.",
                            exclude_user_id=source.get("sender_id") if source else None,
                            related_entity_id=str(claimed["_id"]),
                            related_entity_type="message",
                            metadata={
                                "message_id": str(claimed["_id"]),
                                "orchestration_id": claimed.get("orchestration_id"),
                            },
                        )
                return
            except NexconnAPIError as exc:
                latest = await self._database["messages"].find_one(
                    {"_id": claimed["_id"]}
                )
                if latest is not None and latest.get("delivery_status") == "delivered":
                    return
                is_last = attempt + 1 == attempts
                if exc.retryable and not is_last:
                    await self._database["messages"].update_one(
                        {"_id": claimed["_id"]},
                        {
                            "$set": {
                                "delivery_status": "sending",
                                "delivery_retry_count": attempt + 1,
                                "updated_at": datetime.now(timezone.utc),
                            }
                        },
                    )
                    await asyncio.sleep(
                        self._settings.nexconn_delivery_retry_base_seconds
                        * (2**attempt)
                    )
                    continue
                await self._mark_failed(
                    claimed,
                    "Nexconn rejected the message or delivery attempts were exhausted.",
                    increment_retry=attempt > 0,
                    retry_count=attempt,
                )
                return
            except Exception as exc:
                logger.exception(
                    "Unexpected AI message delivery error",
                    extra={
                        "message_id": str(claimed["_id"]),
                        "error_type": type(exc).__name__,
                    },
                )
                await self._mark_failed(
                    claimed,
                    "Nexconn delivery failed unexpectedly.",
                    increment_retry=attempt > 0,
                    retry_count=attempt,
                )
                return

    async def _mark_failed(
        self,
        message: dict[str, Any],
        error: str,
        *,
        increment_retry: bool,
        retry_count: int | None = None,
    ) -> None:
        changes: dict[str, Any] = {
            "delivery_status": "failed",
            "delivery_error": error,
            "updated_at": datetime.now(timezone.utc),
        }
        if retry_count is not None:
            changes["delivery_retry_count"] = retry_count
        elif increment_retry:
            changes["delivery_retry_count"] = (
                message.get("delivery_retry_count", 0) + 1
            )
        await self._database["messages"].update_one(
            {"_id": message["_id"]},
            {"$set": changes},
        )

    async def _update_run_delivery_status(
        self,
        orchestration_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        if not messages:
            status = "failed"
        else:
            current: list[dict[str, Any]] = []
            for item in messages:
                latest = await self._database["messages"].find_one(
                    {"_id": item["_id"]}
                )
                if latest is not None:
                    current.append(latest)
            statuses = [item.get("delivery_status") for item in current]
            if statuses and all(value == "delivered" for value in statuses):
                status = "delivered"
            elif any(value == "sending" for value in statuses):
                status = "sending"
            elif any(value == "pending" for value in statuses):
                status = "pending"
            else:
                status = "failed"
        await self._database["orchestration_runs"].update_one(
            {"orchestration_id": orchestration_id},
            {"$set": {"delivery_status": status}},
        )
