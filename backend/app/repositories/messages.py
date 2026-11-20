from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.database.indexes import ensure_message_indexes

MESSAGES_COLLECTION = "messages"


async def create_message(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    nexconn_channel_id: str | None,
    nexconn_message_id: str | None,
    sender_id: ObjectId | str | None,
    sender_type: str,
    sender_name: str,
    content: str,
    message_type: str,
    attachments: list[dict[str, Any]],
    reply_to_message_id: ObjectId | None,
    metadata: dict[str, Any],
    created_at: datetime,
    ai_processing_status: str,
    orchestration_id: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    delivery_key: str | None = None,
    delivery_status: str | None = None,
    delivery_retry_count: int | None = None,
    delivery_error: str | None = None,
    delivered_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], bool]:
    await ensure_message_indexes(database)
    now = datetime.now(timezone.utc)
    document: dict[str, Any] = {
        "group_id": group_id,
        "nexconn_channel_id": nexconn_channel_id,
        "nexconn_message_id": nexconn_message_id,
        "sender_id": sender_id,
        "sender_type": sender_type,
        "sender_name": sender_name,
        "content": content,
        "message_type": message_type,
        "attachments": attachments,
        "reply_to_message_id": reply_to_message_id,
        "metadata": metadata,
        "created_at": created_at,
        "updated_at": now,
        "is_deleted": False,
        "ai_processing_status": ai_processing_status,
    }
    if orchestration_id is not None:
        document["orchestration_id"] = orchestration_id
    for key, value in (
        ("agent_id", agent_id),
        ("agent_name", agent_name),
        ("delivery_key", delivery_key),
        ("delivery_status", delivery_status),
        ("delivery_retry_count", delivery_retry_count),
        ("delivery_error", delivery_error),
        ("delivered_at", delivered_at),
        ("idempotency_key", idempotency_key),
    ):
        if value is not None:
            document[key] = value
    try:
        result = await database[MESSAGES_COLLECTION].insert_one(document)
    except DuplicateKeyError:
        existing = None
        if nexconn_message_id is not None:
            existing = await database[MESSAGES_COLLECTION].find_one(
                {"nexconn_message_id": nexconn_message_id}
            )
        if existing is None and idempotency_key is not None:
            existing = await database[MESSAGES_COLLECTION].find_one(
                {"sender_id": sender_id, "idempotency_key": idempotency_key}
            )
        if existing is None:
            raise
        return existing, False

    document["_id"] = result.inserted_id
    await database["groups"].update_one(
        {"_id": group_id},
        {"$max": {"last_message_at": created_at}},
    )
    return document, True


async def get_message(
    database: Database[dict[str, Any]], message_id: str
) -> dict[str, Any] | None:
    if not ObjectId.is_valid(message_id):
        return None
    await ensure_message_indexes(database)
    return await database[MESSAGES_COLLECTION].find_one(
        {"_id": ObjectId(message_id)}
    )


async def get_group_message_history(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    limit: int,
    before: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    await ensure_message_indexes(database)
    query: dict[str, Any] = {"group_id": group_id, "is_deleted": False}
    if before is not None:
        if not ObjectId.is_valid(before):
            return [], None
        cursor_message = await database[MESSAGES_COLLECTION].find_one(
            {
                "_id": ObjectId(before),
                "group_id": group_id,
            }
        )
        if cursor_message is None:
            return [], None
        cursor_time = cursor_message["created_at"]
        query["$or"] = [
            {"created_at": {"$lt": cursor_time}},
            {"created_at": cursor_time, "_id": {"$lt": cursor_message["_id"]}},
        ]

    cursor = (
        database[MESSAGES_COLLECTION]
        .find(query)
        .sort([("created_at", -1), ("_id", -1)])
        .limit(limit + 1)
    )
    documents = await cursor.to_list(length=limit + 1)
    has_older = len(documents) > limit
    page = documents[:limit]
    next_cursor = str(page[-1]["_id"]) if has_older and page else None
    page.reverse()
    return page, next_cursor


async def get_group_message_stats(
    database: Database[dict[str, Any]], group_id: ObjectId
) -> dict[str, Any]:
    await ensure_message_indexes(database)
    visible = {"group_id": group_id, "is_deleted": False}
    messages = database[MESSAGES_COLLECTION]
    total = await messages.count_documents(visible)
    humans = await messages.count_documents({**visible, "sender_type": "user"})
    agents = await messages.count_documents({**visible, "sender_type": "agent"})
    latest = await messages.find(visible).sort(
        [("created_at", -1), ("_id", -1)]
    ).limit(1).to_list(length=1)
    return {
        "total_message_count": total,
        "human_message_count": humans,
        "ai_message_count": agents,
        "latest_message_at": latest[0]["created_at"] if latest else None,
    }


async def soft_delete_message(
    database: Database[dict[str, Any]], message_id: ObjectId
) -> bool:
    await ensure_message_indexes(database)
    message = await database[MESSAGES_COLLECTION].find_one(
        {"_id": message_id},
        projection={"group_id": 1},
    )
    if message is None:
        return False
    result = await database[MESSAGES_COLLECTION].update_one(
        {"_id": message_id, "is_deleted": False},
        {
            "$set": {
                "content": "This message was deleted",
                "attachments": [],
                "is_deleted": True,
                "ai_processing_status": "not_required",
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    await database["message_processing_events"].update_one(
        {"message_id": message_id, "status": {"$in": ["pending", "processing"]}},
        {
            "$set": {
                "status": "cancelled",
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    if result.modified_count == 1:
        latest = (
            await database[MESSAGES_COLLECTION]
            .find({"group_id": message["group_id"], "is_deleted": False})
            .sort([("created_at", -1), ("_id", -1)])
            .limit(1)
            .to_list(length=1)
        )
        await database["groups"].update_one(
            {"_id": message["group_id"]},
            {
                "$set": {
                    "last_message_at": latest[0]["created_at"] if latest else None
                }
            },
        )
    return result.modified_count == 1


async def get_group_by_nexconn_channel_id(
    database: Database[dict[str, Any]], channel_id: str
) -> dict[str, Any] | None:
    return await database["groups"].find_one({"nexconn_channel_id": channel_id})
