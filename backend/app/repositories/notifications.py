from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.database.indexes import ensure_notification_indexes


async def create_notification(
    database: Database[dict[str, Any]],
    *,
    recipient_id: ObjectId,
    event_key: str,
    notification_type: str,
    title: str,
    description: str,
    related_entity_id: str | None = None,
    related_entity_type: str | None = None,
    group_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await ensure_notification_indexes(database)
    now = datetime.now(timezone.utc)
    document = {
        "recipient_id": recipient_id,
        "event_key": event_key,
        "type": notification_type,
        "title": title,
        "description": description,
        "related_entity_id": related_entity_id,
        "related_entity_type": related_entity_type,
        "group_id": group_id,
        "read_at": None,
        "created_at": now,
        "metadata": metadata or {},
    }
    try:
        result = await database["notifications"].insert_one(document)
        document["_id"] = result.inserted_id
        return document
    except DuplicateKeyError:
        existing = await database["notifications"].find_one({"event_key": event_key})
        if existing is None:
            raise
        return existing


async def list_notifications(
    database: Database[dict[str, Any]],
    *,
    recipient_id: ObjectId,
    limit: int,
    before: str | None,
) -> tuple[list[dict[str, Any]], str | None, int]:
    await ensure_notification_indexes(database)
    query: dict[str, Any] = {"recipient_id": recipient_id}
    if before is not None:
        if not ObjectId.is_valid(before):
            return [], None, await database["notifications"].count_documents(
                {"recipient_id": recipient_id, "read_at": None}
            )
        cursor = await database["notifications"].find_one(
            {"_id": ObjectId(before), "recipient_id": recipient_id},
            projection={"created_at": 1},
        )
        if cursor is None:
            return [], None, await database["notifications"].count_documents(
                {"recipient_id": recipient_id, "read_at": None}
            )
        query["$or"] = [
            {"created_at": {"$lt": cursor["created_at"]}},
            {"created_at": cursor["created_at"], "_id": {"$lt": cursor["_id"]}},
        ]
    documents = await (
        database["notifications"]
        .find(query)
        .sort([("created_at", -1), ("_id", -1)])
        .limit(limit + 1)
        .to_list(length=limit + 1)
    )
    has_more = len(documents) > limit
    page = documents[:limit]
    next_cursor = str(page[-1]["_id"]) if has_more and page else None
    unread_count = await database["notifications"].count_documents(
        {"recipient_id": recipient_id, "read_at": None}
    )
    return page, next_cursor, unread_count


async def mark_notification_read(
    database: Database[dict[str, Any]], *, recipient_id: ObjectId, notification_id: str
) -> bool:
    if not ObjectId.is_valid(notification_id):
        return False
    identity = {"_id": ObjectId(notification_id), "recipient_id": recipient_id}
    result = await database["notifications"].update_one(
        {**identity, "read_at": None},
        {"$set": {"read_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 1:
        return True
    return await database["notifications"].find_one(
        identity, projection={"_id": 1}
    ) is not None


async def mark_all_notifications_read(
    database: Database[dict[str, Any]], *, recipient_id: ObjectId
) -> int:
    result = await database["notifications"].update_many(
        {"recipient_id": recipient_id, "read_at": None},
        {"$set": {"read_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count


async def delete_notification(
    database: Database[dict[str, Any]], *, recipient_id: ObjectId, notification_id: str
) -> bool:
    if not ObjectId.is_valid(notification_id):
        return False
    result = await database["notifications"].delete_one(
        {"_id": ObjectId(notification_id), "recipient_id": recipient_id}
    )
    return result.deleted_count == 1
