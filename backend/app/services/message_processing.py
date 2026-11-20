import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database

from app.database.indexes import ensure_message_indexes
from app.repositories.messages import MESSAGES_COLLECTION

logger = logging.getLogger(__name__)


class MessageProcessor(Protocol):
    async def process(self, message: dict[str, Any]) -> str | None: ...


class MessageProcessingService:
    def __init__(
        self,
        database: Database[dict[str, Any]],
        processor: MessageProcessor | None = None,
    ) -> None:
        self._database = database
        self._processor = processor

    async def enqueue(self, message: dict[str, Any]) -> None:
        if message["ai_processing_status"] != "pending":
            return
        await ensure_message_indexes(self._database)
        now = datetime.now(timezone.utc)
        await self._database["message_processing_events"].update_one(
            {"message_id": message["_id"]},
            {
                "$setOnInsert": {
                    "message_id": message["_id"],
                    "group_id": message["group_id"],
                    "status": "pending",
                    "created_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
        )

    async def process_message(self, message_id: str) -> None:
        if self._processor is None or not ObjectId.is_valid(message_id):
            return
        await ensure_message_indexes(self._database)
        identifier = ObjectId(message_id)
        now = datetime.now(timezone.utc)
        message = await self._database[MESSAGES_COLLECTION].find_one_and_update(
            {
                "_id": identifier,
                "is_deleted": False,
                "ai_processing_status": "pending",
            },
            {"$set": {"ai_processing_status": "processing", "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if message is None:
            return

        await self._database["message_processing_events"].update_one(
            {"message_id": identifier, "status": "pending"},
            {"$set": {"status": "processing", "updated_at": now}},
        )
        current = await self._database[MESSAGES_COLLECTION].find_one(
            {
                "_id": identifier,
                "is_deleted": False,
                "ai_processing_status": "processing",
            }
        )
        if current is None:
            await self._database["message_processing_events"].update_one(
                {"message_id": identifier, "status": "processing"},
                {
                    "$set": {
                        "status": "cancelled",
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )
            return
        try:
            outcome = await self._processor.process(message)
        except Exception:
            logger.exception(
                "Message processing failed",
                extra={"message_id": message_id},
            )
            status = "failed"
        else:
            if outcome == "not_required":
                status = "not_required"
            elif outcome == "failed":
                status = "failed"
            elif outcome == "processing":
                status = "processing"
            else:
                status = "completed"
        finished_at = datetime.now(timezone.utc)
        result = await self._database[MESSAGES_COLLECTION].update_one(
            {"_id": identifier, "is_deleted": False},
            {"$set": {"ai_processing_status": status, "updated_at": finished_at}},
        )
        if result.modified_count != 1:
            status = "cancelled"
        event_status = "completed" if status == "not_required" else status
        await self._database["message_processing_events"].update_one(
            {"message_id": identifier},
            {"$set": {"status": event_status, "updated_at": finished_at}},
        )
