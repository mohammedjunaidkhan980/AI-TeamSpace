from datetime import datetime, timezone
from typing import Any, Literal

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from pymongo import ReturnDocument

from app.database.indexes import ensure_connection_indexes

CONNECTIONS_COLLECTION = "connections"
RequestOutcome = Literal[
    "created",
    "accepted",
    "duplicate_pending",
    "already_connected",
    "conflict",
]


def _pair_key(first_id: ObjectId, second_id: ObjectId) -> str:
    return ":".join(sorted((str(first_id), str(second_id))))


async def send_friend_request(
    database: Database[dict[str, Any]],
    sender_id: str,
    recipient_id: str,
) -> tuple[RequestOutcome, dict[str, Any] | None]:
    await ensure_connection_indexes(database)
    sender = ObjectId(sender_id)
    recipient = ObjectId(recipient_id)
    pair_key = _pair_key(sender, recipient)
    now = datetime.now(timezone.utc)
    collection = database[CONNECTIONS_COLLECTION]

    existing = await collection.find_one({"pair_key": pair_key})
    if existing is None:
        document = {
            "pair_key": pair_key,
            "sender_id": sender,
            "recipient_id": recipient,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        try:
            result = await collection.insert_one(document)
            document["_id"] = result.inserted_id
            return "created", document
        except DuplicateKeyError:
            existing = await collection.find_one({"pair_key": pair_key})
            if existing is None:
                return "conflict", None

    if existing["status"] == "accepted":
        return "already_connected", existing

    if existing["status"] == "pending":
        if existing["sender_id"] == sender:
            return "duplicate_pending", existing
        accepted = await collection.find_one_and_update(
            {"_id": existing["_id"], "status": "pending"},
            {"$set": {"status": "accepted", "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if accepted is not None:
            return "accepted", accepted
        current = await collection.find_one({"pair_key": pair_key})
        if current is not None and current["status"] == "accepted":
            return "already_connected", current
        return "conflict", current

    if existing["status"] == "rejected":
        reset = await collection.find_one_and_update(
            {"_id": existing["_id"], "status": "rejected"},
            {
                "$set": {
                    "sender_id": sender,
                    "recipient_id": recipient,
                    "status": "pending",
                    "created_at": now,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if reset is not None:
            return "created", reset
        return "conflict", await collection.find_one({"pair_key": pair_key})

    return "conflict", existing


async def list_pending_requests(
    database: Database[dict[str, Any]],
    *,
    user_id: str,
    direction: Literal["incoming", "outgoing"],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    user = ObjectId(user_id)
    field = "recipient_id" if direction == "incoming" else "sender_id"
    cursor = (
        database[CONNECTIONS_COLLECTION]
        .find({field: user, "status": "pending"})
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def get_request(
    database: Database[dict[str, Any]], request_id: str
) -> dict[str, Any] | None:
    if not ObjectId.is_valid(request_id):
        return None
    return await database[CONNECTIONS_COLLECTION].find_one(
        {"_id": ObjectId(request_id)}
    )


async def update_pending_request(
    database: Database[dict[str, Any]],
    *,
    request_id: str,
    user_id: str,
    role: Literal["sender", "recipient"],
    status: Literal["accepted", "rejected"],
) -> dict[str, Any] | None:
    if not ObjectId.is_valid(request_id):
        return None
    role_field = "sender_id" if role == "sender" else "recipient_id"
    return await database[CONNECTIONS_COLLECTION].find_one_and_update(
        {
            "_id": ObjectId(request_id),
            role_field: ObjectId(user_id),
            "status": "pending",
        },
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


async def delete_pending_request(
    database: Database[dict[str, Any]], *, request_id: str, sender_id: str
) -> bool:
    if not ObjectId.is_valid(request_id):
        return False
    result = await database[CONNECTIONS_COLLECTION].delete_one(
        {
            "_id": ObjectId(request_id),
            "sender_id": ObjectId(sender_id),
            "status": "pending",
        }
    )
    return result.deleted_count == 1


async def list_accepted_connections(
    database: Database[dict[str, Any]],
    user_id: str,
    *,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    user = ObjectId(user_id)
    cursor = (
        database[CONNECTIONS_COLLECTION]
        .find(
            {
                "status": "accepted",
                "$or": [{"sender_id": user}, {"recipient_id": user}],
            }
        )
        .sort("updated_at", -1)
        .skip(offset)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def delete_accepted_connection(
    database: Database[dict[str, Any]], user_id: str, other_user_id: str
) -> bool:
    if not ObjectId.is_valid(other_user_id):
        return False
    current = ObjectId(user_id)
    other = ObjectId(other_user_id)
    result = await database[CONNECTIONS_COLLECTION].delete_one(
        {
            "pair_key": _pair_key(current, other),
            "status": "accepted",
        }
    )
    return result.deleted_count == 1
