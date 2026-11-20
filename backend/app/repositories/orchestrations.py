from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.database.indexes import ensure_orchestration_indexes

ORCHESTRATION_RUNS_COLLECTION = "orchestration_runs"


async def create_orchestration_run(
    database: Database[dict[str, Any]],
    *,
    message_id: ObjectId,
    group_id: ObjectId,
) -> tuple[dict[str, Any], bool]:
    await ensure_orchestration_indexes(database)
    now = datetime.now(timezone.utc)
    document: dict[str, Any] = {
        "orchestration_id": str(uuid4()),
        "message_id": message_id,
        "group_id": group_id,
        "coordinator_plan": None,
        "selected_agent_ids": [],
        "agent_results": [],
        "final_response": None,
        "status": "queued",
        "errors": [],
        "started_at": now,
        "completed_at": None,
        "execution_time": None,
    }
    try:
        result = await database[ORCHESTRATION_RUNS_COLLECTION].insert_one(document)
    except DuplicateKeyError:
        existing = await database[ORCHESTRATION_RUNS_COLLECTION].find_one(
            {"message_id": message_id}
        )
        if existing is None:
            raise
        return existing, False
    document["_id"] = result.inserted_id
    return document, True


async def get_orchestration_run(
    database: Database[dict[str, Any]],
    *,
    orchestration_id: str,
    group_id: ObjectId | None = None,
) -> dict[str, Any] | None:
    await ensure_orchestration_indexes(database)
    query: dict[str, Any] = {"orchestration_id": orchestration_id}
    if group_id is not None:
        query["group_id"] = group_id
    return await database[ORCHESTRATION_RUNS_COLLECTION].find_one(query)


async def claim_orchestration_run(
    database: Database[dict[str, Any]],
    *,
    orchestration_id: str,
    started_at: datetime,
) -> dict[str, Any] | None:
    await ensure_orchestration_indexes(database)
    return await database[ORCHESTRATION_RUNS_COLLECTION].find_one_and_update(
        {"orchestration_id": orchestration_id, "status": "queued"},
        {"$set": {"status": "processing", "started_at": started_at}},
        return_document=ReturnDocument.AFTER,
    )


async def update_orchestration_run(
    database: Database[dict[str, Any]],
    *,
    orchestration_id: str,
    changes: dict[str, Any],
) -> dict[str, Any] | None:
    await ensure_orchestration_indexes(database)
    return await database[ORCHESTRATION_RUNS_COLLECTION].find_one_and_update(
        {"orchestration_id": orchestration_id},
        {"$set": changes},
        return_document=True,
    )
