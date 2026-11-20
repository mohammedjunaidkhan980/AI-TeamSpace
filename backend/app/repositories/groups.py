from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database

from app.database.indexes import ensure_group_indexes

GROUPS_COLLECTION = "groups"


def valid_object_id(value: str) -> bool:
    return ObjectId.is_valid(value)


async def create_group(
    database: Database[dict[str, Any]],
    *,
    name: str,
    description: str | None,
    creator_id: str,
    member_ids: list[str],
) -> dict[str, Any]:
    await ensure_group_indexes(database)
    now = datetime.now(timezone.utc)
    creator = ObjectId(creator_id)
    members = [
        {"user_id": creator, "role": "admin", "joined_at": now},
        *[
            {"user_id": ObjectId(user_id), "role": "member", "joined_at": now}
            for user_id in member_ids
            if user_id.lower() != creator_id.lower()
        ],
    ]
    document = {
        "name": name,
        "description": description,
        "creator_id": creator,
        "group_picture_url": None,
        "members": members,
        "settings": {},
        "ai_agents": [],
        "created_at": now,
        "updated_at": now,
        "last_message_at": None,
        "nexconn_channel_id": None,
        "nexconn_member_ids": [],
        "nexconn_sync_status": "disabled",
        "nexconn_synced_at": None,
    }
    result = await database[GROUPS_COLLECTION].insert_one(document)
    document["_id"] = result.inserted_id
    return document


async def list_user_groups(
    database: Database[dict[str, Any]],
    *,
    user_id: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    await ensure_group_indexes(database)
    cursor = (
        database[GROUPS_COLLECTION]
        .find({"members.user_id": ObjectId(user_id)})
        .sort("updated_at", -1)
        .skip(offset)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def get_group(
    database: Database[dict[str, Any]], group_id: str
) -> dict[str, Any] | None:
    await ensure_group_indexes(database)
    if not valid_object_id(group_id):
        return None
    return await database[GROUPS_COLLECTION].find_one({"_id": ObjectId(group_id)})


def get_member_role(group: dict[str, Any], user_id: str) -> str | None:
    user = ObjectId(user_id)
    for member in group.get("members", []):
        if member["user_id"] == user:
            return member["role"]
    return None


async def update_group(
    database: Database[dict[str, Any]],
    group_id: str,
    admin_id: str,
    changes: dict[str, Any],
) -> dict[str, Any] | None:
    if not valid_object_id(group_id) or not valid_object_id(admin_id):
        return None
    changes["updated_at"] = datetime.now(timezone.utc)
    return await database[GROUPS_COLLECTION].find_one_and_update(
        {
            "_id": ObjectId(group_id),
            "members": {
                "$elemMatch": {"user_id": ObjectId(admin_id), "role": "admin"}
            },
        },
        {"$set": changes},
        return_document=ReturnDocument.AFTER,
    )


async def add_group_member(
    database: Database[dict[str, Any]],
    *,
    group_id: str,
    user_id: str,
    admin_id: str,
) -> bool:
    if not all(valid_object_id(value) for value in (group_id, user_id, admin_id)):
        return False
    now = datetime.now(timezone.utc)
    result = await database[GROUPS_COLLECTION].update_one(
        {
            "_id": ObjectId(group_id),
            "members": {
                "$elemMatch": {
                    "user_id": ObjectId(admin_id),
                    "role": "admin",
                }
            },
            "members.user_id": {"$ne": ObjectId(user_id)},
        },
        {
            "$push": {
                "members": {
                    "user_id": ObjectId(user_id),
                    "role": "member",
                    "joined_at": now,
                }
            },
            "$set": {"updated_at": now},
        },
    )
    return result.modified_count == 1


async def remove_group_member(
    database: Database[dict[str, Any]],
    *,
    group_id: str,
    target_user_id: str,
    actor_id: str,
    actor_is_admin: bool,
) -> bool:
    if not all(valid_object_id(value) for value in (group_id, target_user_id, actor_id)):
        return False
    target = ObjectId(target_user_id)
    actor = ObjectId(actor_id)
    now = datetime.now(timezone.utc)
    query: dict[str, Any] = {
        "_id": ObjectId(group_id),
        "creator_id": {"$ne": target},
        "members": {"$elemMatch": {"user_id": target}},
        "$or": [
            {"members": {"$elemMatch": {"user_id": target, "role": "member"}}},
            {
                "$and": [
                    {"members": {"$elemMatch": {"user_id": target, "role": "admin"}}},
                    {
                        "members": {
                            "$elemMatch": {
                                "user_id": {"$ne": target},
                                "role": "admin",
                            }
                        }
                    },
                ]
            },
        ],
    }
    if actor_is_admin and actor != target:
        query["$and"] = [
            {
                "members": {
                    "$elemMatch": {"user_id": actor, "role": "admin"}
                }
            }
        ]
    else:
        query["members"] = {"$elemMatch": {"user_id": actor}}
    result = await database[GROUPS_COLLECTION].update_one(
        query,
        {
            "$pull": {"members": {"user_id": target}},
            "$set": {"updated_at": now},
        },
    )
    return result.modified_count == 1


async def change_member_role(
    database: Database[dict[str, Any]],
    *,
    group_id: str,
    admin_id: str,
    target_user_id: str,
    role: str,
) -> bool:
    if not all(valid_object_id(value) for value in (group_id, admin_id, target_user_id)):
        return False
    target = ObjectId(target_user_id)
    query: dict[str, Any] = {
        "_id": ObjectId(group_id),
        "$and": [
            {"members": {"$elemMatch": {"user_id": target}}},
            {
                "members": {
                    "$elemMatch": {
                        "user_id": ObjectId(admin_id),
                        "role": "admin",
                    }
                }
            },
        ],
    }
    if role == "admin":
        query["$and"].append(
            {"members": {"$elemMatch": {"user_id": target, "role": "member"}}}
        )
    else:
        query["creator_id"] = {"$ne": target}
        query["$and"].extend(
            [
                {"members": {"$elemMatch": {"user_id": target, "role": "admin"}}},
            {
                "members": {
                    "$elemMatch": {
                        "user_id": {"$ne": target},
                        "role": "admin",
                    }
                }
                },
            ]
        )
    result = await database[GROUPS_COLLECTION].update_one(
        query,
        {
            "$set": {
                "members.$[target].role": role,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        array_filters=[{"target.user_id": target}],
    )
    return result.modified_count == 1


async def users_are_connected(
    database: Database[dict[str, Any]], first_user_id: str, second_user_id: str
) -> bool:
    first, second = sorted((first_user_id.lower(), second_user_id.lower()))
    relationship = await database["connections"].find_one(
        {"pair_key": f"{first}:{second}", "status": "accepted"},
        projection={"_id": 1},
    )
    return relationship is not None
