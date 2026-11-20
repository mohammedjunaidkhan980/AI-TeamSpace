from datetime import datetime, timezone
import re
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.database.indexes import ensure_document_indexes


async def insert_document(
    database: Database[dict[str, Any]], document: dict[str, Any]
) -> dict[str, Any]:
    await ensure_document_indexes(database)
    result = await database["documents"].insert_one(document)
    document["_id"] = result.inserted_id
    return document


async def get_document(
    database: Database[dict[str, Any]], document_id: str
) -> dict[str, Any] | None:
    if not ObjectId.is_valid(document_id):
        return None
    await ensure_document_indexes(database)
    return await database["documents"].find_one({"_id": ObjectId(document_id)})


async def list_group_documents(
    database: Database[dict[str, Any]],
    *,
    group_id: ObjectId,
    limit: int,
    before: str | None,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    await ensure_document_indexes(database)
    query: dict[str, Any] = {"group_id": group_id}
    if search:
        query["filename"] = {"$regex": re.escape(search), "$options": "i"}
    if before:
        if not ObjectId.is_valid(before):
            return [], None
        cursor = await database["documents"].find_one(
            {"_id": ObjectId(before), "group_id": group_id},
            projection={"created_at": 1},
        )
        if cursor is None:
            return [], None
        query["$or"] = [
            {"created_at": {"$lt": cursor["created_at"]}},
            {"created_at": cursor["created_at"], "_id": {"$lt": cursor["_id"]}},
        ]
    documents = await (
        database["documents"]
        .find(query)
        .sort([("created_at", -1), ("_id", -1)])
        .limit(limit + 1)
        .to_list(length=limit + 1)
    )
    has_more = len(documents) > limit
    page = documents[:limit]
    return page, str(page[-1]["_id"]) if has_more and page else None


async def list_documents(
    database: Database[dict[str, Any]],
    *,
    group_ids: list[ObjectId],
    limit: int,
    before: str | None,
    group_id: ObjectId | None = None,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    await ensure_document_indexes(database)
    if group_id is not None:
        group_ids = [group_id] if group_id in group_ids else []
    query: dict[str, Any] = {"group_id": {"$in": group_ids}}
    if search:
        query["filename"] = {"$regex": re.escape(search), "$options": "i"}
    if before:
        if not ObjectId.is_valid(before):
            return [], None
        cursor = await database["documents"].find_one(
            {"_id": ObjectId(before), "group_id": {"$in": group_ids}},
            projection={"created_at": 1},
        )
        if cursor is None:
            return [], None
        query["$or"] = [
            {"created_at": {"$lt": cursor["created_at"]}},
            {"created_at": cursor["created_at"], "_id": {"$lt": cursor["_id"]}},
        ]
    documents = await (
        database["documents"]
        .find(query)
        .sort([("created_at", -1), ("_id", -1)])
        .limit(limit + 1)
        .to_list(length=limit + 1)
    )
    has_more = len(documents) > limit
    page = documents[:limit]
    return page, str(page[-1]["_id"]) if has_more and page else None


async def set_document_status(
    database: Database[dict[str, Any]],
    *,
    document_id: ObjectId,
    status: str,
    processing_error: str | None = None,
) -> None:
    changes: dict[str, Any] = {
        "status": status,
        "updated_at": datetime.now(timezone.utc),
        "processing_error": processing_error,
    }
    if status == "completed":
        changes["processed_at"] = datetime.now(timezone.utc)
    await database["documents"].update_one(
        {"_id": document_id},
        {"$set": changes},
    )
