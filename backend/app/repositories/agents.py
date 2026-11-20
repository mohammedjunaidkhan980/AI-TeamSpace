from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.database.indexes import ensure_agent_indexes

AGENTS_COLLECTION = "agents"
GROUPS_COLLECTION = "groups"


class DuplicateGroupAgentError(Exception):
    """Raised when a group already has an active agent for this template."""


async def create_group_agent(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    template_id: str,
    name: str,
    description: str,
    system_prompt: str,
    model: str,
    temperature: float,
    capabilities: list[str],
    configuration: dict[str, Any],
    created_by: ObjectId,
) -> dict[str, Any]:
    await ensure_agent_indexes(database)
    now = datetime.now(timezone.utc)
    document = {
        "group_id": group_id,
        "template_id": template_id,
        "name": name,
        "description": description,
        "system_prompt": system_prompt,
        "model": model,
        "temperature": temperature,
        "capabilities": capabilities,
        "configuration": configuration,
        "enabled": True,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await database[AGENTS_COLLECTION].insert_one(document)
    except DuplicateKeyError as exc:
        raise DuplicateGroupAgentError from exc
    document["_id"] = result.inserted_id
    return document


async def list_group_agents(
    database: Database[dict[str, Any]],
    group_id: ObjectId,
) -> list[dict[str, Any]]:
    await ensure_agent_indexes(database)
    cursor = (
        database[AGENTS_COLLECTION]
        .find({"group_id": group_id, "deleted_at": {"$exists": False}})
        .sort("created_at", 1)
    )
    return await cursor.to_list(length=500)


async def get_group_agent(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    agent_id: str,
) -> dict[str, Any] | None:
    if not ObjectId.is_valid(agent_id):
        return None
    await ensure_agent_indexes(database)
    return await database[AGENTS_COLLECTION].find_one(
        {
            "_id": ObjectId(agent_id),
            "group_id": group_id,
            "deleted_at": {"$exists": False},
        }
    )


async def update_group_agent(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    agent_id: ObjectId,
    changes: dict[str, Any],
) -> dict[str, Any] | None:
    await ensure_agent_indexes(database)
    changes["updated_at"] = datetime.now(timezone.utc)
    return await database[AGENTS_COLLECTION].find_one_and_update(
        {
            "_id": agent_id,
            "group_id": group_id,
            "deleted_at": {"$exists": False},
        },
        {"$set": changes},
        return_document=True,
    )


async def set_group_agent_enabled(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    agent_id: ObjectId,
    enabled: bool,
) -> dict[str, Any] | None:
    return await update_group_agent(
        database,
        group_id=group_id,
        agent_id=agent_id,
        changes={"enabled": enabled},
    )


async def soft_delete_group_agent(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    agent_id: ObjectId,
) -> dict[str, Any] | None:
    await ensure_agent_indexes(database)
    now = datetime.now(timezone.utc)
    return await database[AGENTS_COLLECTION].find_one_and_update(
        {
            "_id": agent_id,
            "group_id": group_id,
            "deleted_at": {"$exists": False},
        },
        {
            "$set": {
                "enabled": False,
                "deleted_at": now,
                "updated_at": now,
            }
        },
        return_document=True,
    )


async def list_enabled_group_agents(
    database: Database[dict[str, Any]], group_id: ObjectId
) -> list[dict[str, Any]]:
    await ensure_agent_indexes(database)
    cursor = database[AGENTS_COLLECTION].find(
        {
            "group_id": group_id,
            "enabled": True,
            "deleted_at": {"$exists": False},
        }
    ).sort("created_at", 1)
    return await cursor.to_list(length=500)


async def sync_group_agent_summary(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    agent_id: ObjectId,
    enabled: bool,
) -> None:
    summary = {"agent_id": str(agent_id), "enabled": True}
    if enabled:
        await database[GROUPS_COLLECTION].update_one(
            {"_id": group_id},
            {"$addToSet": {"ai_agents": summary}},
        )
    else:
        await database[GROUPS_COLLECTION].update_one(
            {"_id": group_id},
            {"$pull": {"ai_agents": {"agent_id": str(agent_id)}}},
        )
