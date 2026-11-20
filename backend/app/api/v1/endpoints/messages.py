import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Annotated, Any

from bson import ObjectId
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from pymongo.database import Database

from app.core.security import get_current_user
from app.database.mongodb import get_database
from app.repositories.groups import get_group, get_member_role, valid_object_id
from app.repositories.messages import (
    create_message,
    get_group_by_nexconn_channel_id,
    get_group_message_history,
    get_group_message_stats,
    get_message,
    soft_delete_message,
)
from app.repositories.users import get_user_by_id
from app.schemas.auth import AuthenticatedUser
from app.schemas.messages import (
    CreateMessageRequest,
    GroupMessageStats,
    MessageHistoryResponse,
    MessageResponse,
    MessageSender,
    NexconnMessageData,
    NexconnMessageWebhook,
    NexconnWebhookResponse,
)
from app.services.message_processing import MessageProcessingService
from app.repositories.orchestrations import (
    create_orchestration_run,
    get_orchestration_run,
)
from app.schemas.orchestration import (
    OrchestrationAccepted,
    OrchestrationRunResponse,
)
from app.services.orchestration import OrchestrationMessageProcessor
from pymongo import ReturnDocument
from app.services.messaging import AIMessageDeliveryService
from app.services.notifications import notify_group_members_best_effort
from app.schemas.orchestration import (
    AIMessageDeliveryAccepted,
    AIMessageDeliveryStatus,
)

group_router = APIRouter()
message_router = APIRouter()
webhook_router = APIRouter()
DELETED_MESSAGE_CONTENT = "This message was deleted"
MAX_WEBHOOK_TIMESTAMP_SKEW_MS = 5 * 60 * 1000

async def _group_for_member(
    database: Database[dict[str, Any]],
    group_id: str,
    user_id: str,
) -> tuple[dict[str, Any], str]:
    group = await get_group(database, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    role = get_member_role(group, user_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Group membership required")
    return group, role


def _response_message(message: dict[str, Any]) -> MessageResponse:
    content = (
        DELETED_MESSAGE_CONTENT
        if message.get("is_deleted")
        else message["content"]
    )
    return MessageResponse(
        message_id=str(message["_id"]),
        group_id=str(message["group_id"]),
        nexconn_message_id=message.get("nexconn_message_id"),
        sender=MessageSender(
            id=str(message["sender_id"]) if message.get("sender_id") else "",
            type=message["sender_type"],
            name=message["sender_name"],
        ),
        content=content,
        message_type=message["message_type"],
        attachments=message.get("attachments", []),
        reply_to_message_id=(
            str(message["reply_to_message_id"])
            if message.get("reply_to_message_id")
            else None
        ),
        metadata=message.get("metadata", {}),
        created_at=message["created_at"],
        updated_at=message["updated_at"],
        is_deleted=message.get("is_deleted", False),
        agent_id=message.get("agent_id"),
        agent_name=message.get("agent_name"),
        orchestration_id=message.get("orchestration_id"),
        delivery_status=message.get("delivery_status"),
    )


async def _match_pending_ai_delivery(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    nexconn_user_id: str,
    channel_id: str,
    nexconn_message_id: str,
    content: str,
) -> dict[str, Any] | None:
    pending = await database["messages"].find_one(
        {
            "group_id": group_id,
            "nexconn_channel_id": channel_id,
            "sender_id": nexconn_user_id,
            "content": content,
            "delivery_status": {"$in": ["sending", "delivered"]},
            "nexconn_message_id": None,
        }
    )
    if pending is None:
        return None
    delivered_at = datetime.now(timezone.utc)
    await database["messages"].update_one(
        {"_id": pending["_id"], "nexconn_message_id": None},
        {
            "$set": {
                "nexconn_message_id": nexconn_message_id,
                "delivery_status": "delivered",
                "delivery_error": None,
                "delivered_at": delivered_at,
                "updated_at": delivered_at,
            }
        },
    )
    return await database["messages"].find_one({"_id": pending["_id"]})


async def _match_pending_user_message(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    sender_id: ObjectId,
    channel_id: str,
    nexconn_message_id: str,
    content: str,
) -> dict[str, Any] | None:
    pending = await database["messages"].find_one(
        {
            "group_id": group_id,
            "nexconn_channel_id": channel_id,
            "sender_id": sender_id,
            "content": content,
            "sender_type": "user",
            "delivery_status": {"$in": ["sending", "delivered"]},
            "nexconn_message_id": None,
        }
    )
    if pending is None:
        return None
    now = datetime.now(timezone.utc)
    await database["messages"].update_one(
        {"_id": pending["_id"], "nexconn_message_id": None},
        {
            "$set": {
                "nexconn_message_id": nexconn_message_id,
                "delivery_status": "delivered",
                "delivery_error": None,
                "delivered_at": now,
                "updated_at": now,
            }
        },
    )
    return await database["messages"].find_one({"_id": pending["_id"]})


async def _deliver_user_message(
    database: Database[dict[str, Any]],
    client: Any,
    *,
    group: dict[str, Any],
    message: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    claimed = await database["messages"].find_one_and_update(
        {
            "_id": message["_id"],
            "delivery_status": {"$in": ["pending", "failed"]},
        },
        {"$set": {"delivery_status": "sending", "delivery_error": None, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if claimed is None:
        return await database["messages"].find_one({"_id": message["_id"]}) or message
    message = claimed
    try:
        receipt = await client.send_group_message(
            sender_user_id=str(message["sender_id"]),
            channel_id=group["nexconn_channel_id"],
            content=message["content"],
        )
    except Exception as exc:
        logger = logging.getLogger(__name__)
        logger.warning(
            "Nexconn human message delivery failed",
            extra={"message_id": str(message["_id"]), "error_type": type(exc).__name__},
        )
        await database["messages"].update_one(
            {"_id": message["_id"], "delivery_status": {"$ne": "delivered"}},
            {
                "$set": {
                    "delivery_status": "failed",
                    "delivery_error": "Message delivery failed. Retry is available.",
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
    else:
        delivered_at = datetime.now(timezone.utc)
        await database["messages"].update_one(
            {"_id": message["_id"]},
            {
                "$set": {
                    "nexconn_message_id": receipt.message_id,
                    "delivery_status": "delivered",
                    "delivery_error": None,
                    "delivered_at": delivered_at,
                    "updated_at": delivered_at,
                }
            },
        )
        await notify_group_members_best_effort(
            database,
            group=group,
            event_key=f"message:{message['_id']}",
            notification_type="new_group_message",
            title="New group message",
            description=f"{message['sender_name']} sent a message.",
            exclude_user_id=message["sender_id"],
            related_entity_id=str(message["_id"]),
            related_entity_type="message",
            metadata={"message_id": str(message["_id"])},
        )
    return await database["messages"].find_one({"_id": message["_id"]}) or message


def _nexconn_signature_is_valid(
    request: Request,
    *,
    app_key: str | None,
    nonce: str | None,
    timestamp: str | None,
    signature: str | None,
) -> bool:
    settings = request.app.state.settings
    if not settings.nexconn_enabled:
        return False
    if (
        app_key != settings.nexconn_app_key
        or not nonce
        or len(nonce) > 18
        or not timestamp
        or not timestamp.isdecimal()
        or not signature
    ):
        return False
    try:
        timestamp_ms = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time() * 1000) - timestamp_ms) > MAX_WEBHOOK_TIMESTAMP_SKEW_MS:
        return False
    expected = hashlib.sha1(
        f"{settings.nexconn_app_secret}{nonce}{timestamp}".encode("utf-8")
    ).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def _message_content(data: NexconnMessageData) -> tuple[str, str]:
    if data.message_type == "RC:TxtMsg":
        try:
            parsed = json.loads(data.content)
        except json.JSONDecodeError:
            return "text", data.content
        if isinstance(parsed, dict) and isinstance(parsed.get("content"), str):
            return "text", parsed["content"]
        return "text", data.content
    if data.message_type == "RC:ImgMsg":
        return "image", data.content
    return "file", data.content


def _message_metadata(data: NexconnMessageData) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "nexconn_message_type": data.message_type,
        "os": data.os,
        "channel_type": data.channel_type,
    }
    if data.profanity_type is not None:
        metadata["profanity_type"] = data.profanity_type
    if data.ai_generated is not None:
        metadata["ai_generated"] = data.ai_generated
    if data.original_message_id is not None:
        metadata["original_message_id"] = data.original_message_id
    if data.group_user_ids is not None:
        metadata["group_user_ids"] = data.group_user_ids
    return metadata


def _orchestration_response(
    run: dict[str, Any],
) -> OrchestrationRunResponse:
    return OrchestrationRunResponse(
        orchestration_id=run["orchestration_id"],
        message_id=str(run["message_id"]),
        group_id=str(run["group_id"]),
        status=run["status"],
        coordinator_plan=run.get("coordinator_plan"),
        selected_agent_ids=run.get("selected_agent_ids", []),
        agent_results=run.get("agent_results", []),
        final_response=run.get("final_response"),
        errors=run.get("errors", []),
        started_at=run["started_at"],
        completed_at=run.get("completed_at"),
        execution_time=run.get("execution_time"),
        delivery_status=run.get("delivery_status"),
        citations=run.get("citations", []),
    )


@group_router.post(
    "/{group_id}/messages/{message_id}/ai-process",
    response_model=OrchestrationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue AI orchestration for a group message",
)
async def queue_message_orchestration(
    group_id: str,
    message_id: str,
    background_tasks: BackgroundTasks,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    request: Request,
) -> OrchestrationAccepted:
    group, _ = await _group_for_member(database, group_id, current_user.id)
    message = await get_message(database, message_id)
    if message is None or message["group_id"] != group["_id"]:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.get("is_deleted") or message.get("sender_type") != "user":
        raise HTTPException(
            status_code=409,
            detail="Only active human messages can be AI-processed",
        )
    if message.get("ai_processing_status") == "processing":
        raise HTTPException(status_code=409, detail="Message is already processing")

    run, created = await create_orchestration_run(
        database,
        message_id=message["_id"],
        group_id=group["_id"],
    )
    if not created:
        raise HTTPException(
            status_code=409,
            detail="This message already has an orchestration run",
        )

    queued_at = datetime.now(timezone.utc)
    await database["messages"].update_one(
        {"_id": message["_id"], "is_deleted": False},
        {"$set": {"ai_processing_status": "pending", "updated_at": queued_at}},
    )
    await MessageProcessingService(database).enqueue(
        {**message, "ai_processing_status": "pending"}
    )
    processor = OrchestrationMessageProcessor(
        database,
        request.app.state.settings,
        semaphore=request.app.state.orchestration_semaphore,
        nexconn_client=request.app.state.nexconn_client,
    )
    background_tasks.add_task(
        processor.run_reserved,
        run["orchestration_id"],
        message_id,
    )
    return OrchestrationAccepted(
        orchestration_id=run["orchestration_id"],
        message_id=message_id,
        status="queued",
    )


@group_router.post(
    "/{group_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a human text message to a group",
)
async def send_group_message(
    group_id: str,
    payload: CreateMessageRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)],
) -> MessageResponse:
    group, _ = await _group_for_member(database, group_id, current_user.id)
    if payload.attachments:
        raise HTTPException(
            status_code=422,
            detail="Message attachments are not supported by the configured Nexconn server sender",
        )
    if not request.app.state.settings.nexconn_enabled or request.app.state.nexconn_client is None:
        raise HTTPException(status_code=503, detail="Nexconn messaging is disabled")
    channel_id = group.get("nexconn_channel_id")
    if not isinstance(channel_id, str) or not channel_id.strip():
        raise HTTPException(status_code=409, detail="Group has no Nexconn channel mapping")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", idempotency_key):
        raise HTTPException(status_code=422, detail="Invalid idempotency key")

    sender_id = ObjectId(current_user.id)
    existing = await database["messages"].find_one(
        {"sender_id": sender_id, "idempotency_key": idempotency_key}
    )
    if existing is not None:
        if existing["group_id"] != group["_id"]:
            raise HTTPException(status_code=409, detail="Idempotency key was already used")
        if existing.get("delivery_status") != "delivered":
            existing = await _deliver_user_message(
                database,
                request.app.state.nexconn_client,
                group=group,
                message=existing,
            )
        return _response_message(existing)

    if payload.reply_to_message_id:
        reply_to = await get_message(database, payload.reply_to_message_id)
        if (
            reply_to is None
            or reply_to.get("is_deleted")
            or reply_to["group_id"] != group["_id"]
        ):
            raise HTTPException(status_code=404, detail="Reply message not found")
    else:
        reply_to = None

    user = await get_user_by_id(database, current_user.id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authenticated user not found")
    message, _ = await create_message(
        database,
        group_id=group["_id"],
        nexconn_channel_id=channel_id,
        nexconn_message_id=None,
        sender_id=sender_id,
        sender_type="user",
        sender_name=user["full_name"],
        content=payload.content,
        message_type=payload.message_type,
        attachments=[],
        reply_to_message_id=reply_to["_id"] if reply_to else None,
        metadata={},
        created_at=datetime.now(timezone.utc),
        ai_processing_status="pending" if group.get("ai_agents") else "not_required",
        delivery_status="pending",
        delivery_retry_count=0,
        idempotency_key=idempotency_key,
    )
    delivered = await _deliver_user_message(
        database,
        request.app.state.nexconn_client,
        group=group,
        message=message,
    )
    if delivered.get("delivery_status") == "delivered" and delivered.get("ai_processing_status") == "pending":
        processor = OrchestrationMessageProcessor(
            database,
            request.app.state.settings,
            semaphore=request.app.state.orchestration_semaphore,
            nexconn_client=request.app.state.nexconn_client,
        )
        background_tasks.add_task(
            MessageProcessingService(database, processor).process_message,
            str(delivered["_id"]),
        )
    return _response_message(delivered)


@message_router.post(
    "/{message_id}/retry",
    response_model=MessageResponse,
    summary="Retry sending a persisted group message",
)
async def retry_user_message(
    message_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    request: Request,
) -> MessageResponse:
    message = await get_message(database, message_id)
    if message is None or message.get("sender_type") != "user":
        raise HTTPException(status_code=404, detail="Message not found")
    group, role = await _group_for_member(
        database, str(message["group_id"]), current_user.id
    )
    if str(message.get("sender_id")) != current_user.id and role != "admin":
        raise HTTPException(status_code=403, detail="Only the sender or a group admin can retry delivery")
    if message.get("delivery_status") == "delivered":
        return _response_message(message)
    if not request.app.state.settings.nexconn_enabled or request.app.state.nexconn_client is None:
        raise HTTPException(status_code=503, detail="Nexconn messaging is disabled")
    if group.get("nexconn_channel_id") != message.get("nexconn_channel_id"):
        raise HTTPException(status_code=409, detail="Message channel mapping is no longer valid")
    delivered = await _deliver_user_message(
        database,
        request.app.state.nexconn_client,
        group=group,
        message=message,
    )
    return _response_message(delivered)


@group_router.get(
    "/{group_id}/orchestrations/{orchestration_id}",
    response_model=OrchestrationRunResponse,
    summary="Get group orchestration status and results",
)
async def get_group_orchestration(
    group_id: str,
    orchestration_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> OrchestrationRunResponse:
    group, _ = await _group_for_member(database, group_id, current_user.id)
    run = await get_orchestration_run(
        database,
        orchestration_id=orchestration_id,
        group_id=group["_id"],
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Orchestration not found")
    return _orchestration_response(run)


@group_router.post(
    "/{group_id}/orchestrations/{orchestration_id}/deliver",
    response_model=AIMessageDeliveryAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue or retry delivery of an AI response",
)
async def queue_ai_response_delivery(
    group_id: str,
    orchestration_id: str,
    background_tasks: BackgroundTasks,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    request: Request,
) -> AIMessageDeliveryAccepted:
    group, _ = await _group_for_member(database, group_id, current_user.id)
    run = await get_orchestration_run(
        database,
        orchestration_id=orchestration_id,
        group_id=group["_id"],
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Orchestration not found")
    if run.get("status") != "completed" or not run.get("final_response"):
        raise HTTPException(
            status_code=409,
            detail="Orchestration has no completed AI response",
        )
    delivery = AIMessageDeliveryService(
        database,
        request.app.state.settings,
        request.app.state.nexconn_client,
    )
    try:
        delivery_status, message_id = await delivery.queue_orchestration(
            orchestration_id
        )
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="AI response is not available for delivery",
        ) from None
    if delivery_status != "delivered":
        background_tasks.add_task(
            delivery.deliver_orchestration,
            orchestration_id,
        )
    return AIMessageDeliveryAccepted(
        orchestration_id=orchestration_id,
        delivery_status=delivery_status,
        message_id=message_id,
    )


@group_router.get(
    "/{group_id}/orchestrations/{orchestration_id}/delivery-status",
    response_model=AIMessageDeliveryStatus,
    summary="Get AI response delivery status",
)
async def get_ai_response_delivery_status(
    group_id: str,
    orchestration_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> AIMessageDeliveryStatus:
    group, _ = await _group_for_member(database, group_id, current_user.id)
    run = await get_orchestration_run(
        database,
        orchestration_id=orchestration_id,
        group_id=group["_id"],
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Orchestration not found")
    message = await database["messages"].find_one(
        {
            "orchestration_id": orchestration_id,
            "agent_id": "coordinator",
        }
    )
    if message is None:
        return AIMessageDeliveryStatus(
            orchestration_id=orchestration_id,
            delivery_status=run.get("delivery_status", "pending"),
        )
    return AIMessageDeliveryStatus(
        orchestration_id=orchestration_id,
        delivery_status=run.get(
            "delivery_status",
            message.get("delivery_status", "pending"),
        ),
        message_id=str(message["_id"]),
        sender_name=message.get("sender_name"),
        created_at=message.get("created_at"),
        delivered_at=message.get("delivered_at"),
        retry_count=message.get("delivery_retry_count", 0),
        error_message=message.get("delivery_error"),
    )


async def _persist_nexconn_message(
    database: Database[dict[str, Any]],
    event_data: NexconnMessageData,
) -> tuple[dict[str, Any], bool]:
    if event_data.channel_type != 3:
        raise HTTPException(
            status_code=422,
            detail="Only Nexconn group channel messages are supported",
        )
    group = await get_group_by_nexconn_channel_id(database, event_data.channel_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group channel not found")
    existing = await database["messages"].find_one(
        {"nexconn_message_id": event_data.message_id}
    )
    if existing is not None:
        if (
            existing["group_id"] != group["_id"]
            or str(existing.get("sender_id") or "") != event_data.user_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Nexconn message ID conflicts with an existing message",
            )
        return existing, False

    message_type, content = _message_content(event_data)
    ai_identity_prefix = f"ai{group['_id']}"
    if event_data.user_id.startswith(ai_identity_prefix):
        ai_message = await _match_pending_ai_delivery(
            database,
            group_id=group["_id"],
            nexconn_user_id=event_data.user_id,
            channel_id=event_data.channel_id,
            nexconn_message_id=event_data.message_id,
            content=content,
        )
        if ai_message is None:
            raise HTTPException(
                status_code=403,
                detail="AI sender identity is not associated with a pending group response",
            )
        return ai_message, False

    if not ObjectId.is_valid(event_data.user_id):
        raise HTTPException(status_code=403, detail="Message sender is not authorized")
    sender_id = ObjectId(event_data.user_id)
    pending_message = await _match_pending_user_message(
        database,
        group_id=group["_id"],
        sender_id=sender_id,
        channel_id=event_data.channel_id,
        nexconn_message_id=event_data.message_id,
        content=content,
    )
    if pending_message is not None:
        return pending_message, False
    if sender_id not in {member["user_id"] for member in group.get("members", [])}:
        raise HTTPException(
            status_code=403,
            detail="Message sender is not a member of this group",
        )
    user = await get_user_by_id(database, event_data.user_id)
    if user is None:
        raise HTTPException(status_code=403, detail="Message sender is not authorized")

    is_agent_message = event_data.ai_generated is True
    should_process = bool(group.get("ai_agents")) and not is_agent_message
    message, created = await create_message(
        database,
        group_id=group["_id"],
        nexconn_channel_id=event_data.channel_id,
        nexconn_message_id=event_data.message_id,
        sender_id=sender_id,
        sender_type="agent" if is_agent_message else "user",
        sender_name=user["full_name"],
        content=content,
        message_type=message_type,
        attachments=[],
        reply_to_message_id=None,
        metadata=_message_metadata(event_data),
        created_at=datetime.fromtimestamp(event_data.time / 1000, tz=timezone.utc),
        ai_processing_status="pending" if should_process else "not_required",
    )
    if not created and (
        message["group_id"] != group["_id"]
        or message.get("sender_id") != sender_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Nexconn message ID conflicts with an existing message",
        )
    if should_process:
        processing_service = MessageProcessingService(database)
        await processing_service.enqueue(message)
    if created and not is_agent_message:
        await notify_group_members_best_effort(
            database,
            group=group,
            event_key=f"message:{message['_id']}",
            notification_type="new_group_message",
            title="New group message",
            description=f"{user['full_name']} sent a message.",
            exclude_user_id=sender_id,
            related_entity_id=str(message["_id"]),
            related_entity_type="message",
            metadata={"message_id": str(message["_id"])},
        )
    return message, created


@group_router.get(
    "/{group_id}/messages",
    response_model=MessageHistoryResponse,
    summary="Get group message history",
)
async def get_group_messages(
    group_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: Annotated[str | None, Query()] = None,
) -> MessageHistoryResponse:
    await _group_for_member(database, group_id, current_user.id)
    if before is not None and not valid_object_id(before):
        raise HTTPException(status_code=422, detail="Invalid message cursor")
    page, next_cursor = await get_group_message_history(
        database,
        group_id=ObjectId(group_id),
        limit=limit,
        before=before,
    )
    return MessageHistoryResponse(
        items=[_response_message(message) for message in page],
        limit=limit,
        next_cursor=next_cursor,
    )


@group_router.get(
    "/{group_id}/messages/stats",
    response_model=GroupMessageStats,
    summary="Get group message statistics",
)
async def get_group_messages_stats(
    group_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupMessageStats:
    await _group_for_member(database, group_id, current_user.id)
    return GroupMessageStats(
        **await get_group_message_stats(database, ObjectId(group_id))
    )


@message_router.get(
    "/{message_id}",
    response_model=MessageResponse,
    summary="Get a message",
)
async def get_message_by_id(
    message_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> MessageResponse:
    if not valid_object_id(message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    message = await get_message(database, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    await _group_for_member(database, str(message["group_id"]), current_user.id)
    return _response_message(message)


@message_router.delete(
    "/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a message",
)
async def delete_message_by_id(
    message_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> None:
    if not valid_object_id(message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    message = await get_message(database, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    _, role = await _group_for_member(
        database, str(message["group_id"]), current_user.id
    )
    if (
        str(message.get("sender_id")) != current_user.id
        and role != "admin"
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the sender or a group admin can delete this message",
        )
    if not await soft_delete_message(database, message["_id"]):
        raise HTTPException(status_code=404, detail="Message not found")


@webhook_router.post(
    "/nexconn/messages",
    response_model=NexconnWebhookResponse,
    summary="Receive Nexconn message events",
)
async def receive_nexconn_messages(
    request: Request,
    payload: NexconnMessageWebhook,
    background_tasks: BackgroundTasks,
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    app_key: Annotated[str | None, Header(alias="AppKey")] = None,
    nonce: Annotated[str | None, Header(alias="Nonce")] = None,
    timestamp: Annotated[str | None, Header(alias="Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="Signature")] = None,
) -> NexconnWebhookResponse:
    if not request.app.state.settings.nexconn_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nexconn integration is disabled",
        )
    if not _nexconn_signature_is_valid(
        request,
        app_key=app_key,
        nonce=nonce,
        timestamp=timestamp,
        signature=signature,
    ):
        raise HTTPException(status_code=401, detail="Invalid Nexconn webhook signature")

    accepted = 0
    duplicates = 0
    for event_data in payload.data:
        message, created = await _persist_nexconn_message(database, event_data)
        if created:
            accepted += 1
        else:
            duplicates += 1
        if message["ai_processing_status"] == "pending":
            processor = request.app.state.message_processor
            if processor is None:
                processor = OrchestrationMessageProcessor(
                    database,
                    request.app.state.settings,
                    semaphore=request.app.state.orchestration_semaphore,
                    nexconn_client=request.app.state.nexconn_client,
                )
            background_tasks.add_task(
                MessageProcessingService(
                    database,
                    processor,
                ).process_message,
                str(message["_id"]),
            )
    return NexconnWebhookResponse(accepted=accepted, duplicates=duplicates)
