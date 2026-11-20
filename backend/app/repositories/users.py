from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.database.indexes import ensure_user_indexes

USERS_COLLECTION = "users"


def _profile_from_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(document["_id"]),
        "username": document["username"],
        "full_name": document["full_name"],
        "email": document["email"],
        "created_at": document["created_at"],
    }


async def create_user(
    database: Database[dict[str, Any]],
    *,
    username: str,
    full_name: str,
    email: str,
    password_hash: str,
) -> dict[str, Any]:
    await ensure_user_indexes(database)
    document = {
        "username": username,
        "full_name": full_name,
        "email": email,
        "password_hash": password_hash,
        "created_at": datetime.now(timezone.utc),
    }
    result = await database[USERS_COLLECTION].insert_one(document)
    document["_id"] = result.inserted_id
    return _profile_from_document(document)


async def get_user_by_email(
    database: Database[dict[str, Any]], email: str
) -> dict[str, Any] | None:
    return await database[USERS_COLLECTION].find_one({"email": email})


async def get_user_by_id(
    database: Database[dict[str, Any]], user_id: str
) -> dict[str, Any] | None:
    if not ObjectId.is_valid(user_id):
        return None
    return await database[USERS_COLLECTION].find_one({"_id": ObjectId(user_id)})


async def find_user_conflict(
    database: Database[dict[str, Any]], *, username: str, email: str
) -> bool:
    return (
        await database[USERS_COLLECTION].find_one(
            {"$or": [{"email": email}, {"username": username}]},
            projection={"_id": 1},
        )
        is not None
    )


async def update_user_profile(
    database: Database[dict[str, Any]],
    user_id: str,
    changes: dict[str, Any],
) -> dict[str, Any] | None:
    if not ObjectId.is_valid(user_id):
        return None
    return await database[USERS_COLLECTION].find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$set": changes},
        return_document=True,
    )


async def search_users(
    database: Database[dict[str, Any]],
    *,
    query: str,
    exclude_user_id: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    cursor = (
        database[USERS_COLLECTION]
        .find(
            {
                "_id": {"$ne": ObjectId(exclude_user_id)},
                "$or": [
                    {"username": {"$regex": query, "$options": "i"}},
                    {"full_name": {"$regex": query, "$options": "i"}},
                    {"email": {"$regex": query, "$options": "i"}},
                ],
            },
            projection={
                "password_hash": 0,
                "password": 0,
                "token_id": 0,
                "token_expires_at": 0,
                "auth": 0,
            },
        )
        .sort("username", 1)
        .skip(offset)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def get_users_by_ids(
    database: Database[dict[str, Any]], user_ids: list[ObjectId]
) -> list[dict[str, Any]]:
    if not user_ids:
        return []
    cursor = database[USERS_COLLECTION].find(
        {"_id": {"$in": user_ids}},
        projection={
            "_id": 1,
            "username": 1,
            "full_name": 1,
            "profile_picture_url": 1,
            "bio": 1,
            "status_message": 1,
            "created_at": 1,
            "nexconn_sync_status": 1,
            "nexconn_synced_at": 1,
            "nexconn_synced_profile": 1,
        },
    )
    return await cursor.to_list(length=len(user_ids))
