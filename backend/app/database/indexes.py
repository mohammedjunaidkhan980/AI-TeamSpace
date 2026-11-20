from typing import Any

from pymongo.database import Database


async def ensure_user_indexes(database: Database[dict[str, Any]]) -> None:
    users = database["users"]
    await users.create_index("email", unique=True)
    await users.create_index("username", unique=True)
    await users.create_index("full_name")


async def ensure_revoked_token_indexes(
    database: Database[dict[str, Any]],
) -> None:
    await database["revoked_tokens"].create_index(
        "expires_at",
        expireAfterSeconds=0,
    )


async def ensure_connection_indexes(
    database: Database[dict[str, Any]],
) -> None:
    connections = database["connections"]
    await connections.create_index("pair_key", unique=True)
    await connections.create_index([("recipient_id", 1), ("status", 1), ("created_at", -1)])
    await connections.create_index([("sender_id", 1), ("status", 1), ("created_at", -1)])


async def ensure_group_indexes(
    database: Database[dict[str, Any]],
) -> None:
    groups = database["groups"]
    await groups.create_index("creator_id")
    await groups.create_index("members.user_id")
    await groups.create_index("created_at")
    await groups.create_index(
        "nexconn_channel_id",
        unique=True,
        partialFilterExpression={"nexconn_channel_id": {"$type": "string"}},
    )


async def ensure_message_indexes(
    database: Database[dict[str, Any]],
) -> None:
    messages = database["messages"]
    await messages.create_index([("group_id", 1), ("created_at", -1)])
    await messages.create_index([("group_id", 1), ("_id", 1)])
    await messages.create_index("sender_id")
    await messages.create_index(
        "nexconn_message_id",
        unique=True,
        partialFilterExpression={"nexconn_message_id": {"$type": "string"}},
    )
    await messages.create_index("ai_processing_status")
    await messages.create_index(
        [("sender_id", 1), ("idempotency_key", 1)],
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )
    await messages.create_index(
        [
            ("group_id", 1),
            ("is_deleted", 1),
            ("created_at", -1),
            ("_id", -1),
        ]
    )

    events = database["message_processing_events"]
    await events.create_index("message_id", unique=True)
    await events.create_index([("status", 1), ("created_at", 1)])


async def ensure_nexconn_webhook_indexes(
    database: Database[dict[str, Any]],
) -> None:
    await database["nexconn_webhook_nonces"].create_index(
        "expires_at",
        expireAfterSeconds=0,
    )


async def ensure_agent_indexes(
    database: Database[dict[str, Any]],
) -> None:
    agents = database["agents"]
    await agents.create_index("group_id")
    await agents.create_index([("group_id", 1), ("enabled", 1)])
    await agents.create_index(
        [("group_id", 1), ("template_id", 1)],
        unique=True,
        partialFilterExpression={"deleted_at": {"$type": "null"}},
    )
    await agents.create_index("created_by")
    await agents.create_index("created_at")


async def ensure_orchestration_indexes(
    database: Database[dict[str, Any]],
) -> None:
    runs = database["orchestration_runs"]
    await runs.create_index("message_id", unique=True)
    await runs.create_index([("group_id", 1), ("started_at", -1)])
    await runs.create_index("status")
    await runs.create_index("orchestration_id", unique=True)
    messages = database["messages"]
    existing_indexes = await messages.index_information()
    legacy_index = existing_indexes.get("orchestration_id_1")
    if legacy_index and legacy_index.get("unique"):
        await messages.update_many(
            {
                "orchestration_id": {"$type": "string"},
                "delivery_key": {"$exists": False},
            },
            [{"$set": {"delivery_key": "$orchestration_id"}}],
        )
        await messages.drop_index("orchestration_id_1")
    await messages.create_index("orchestration_id")
    await messages.create_index(
        "delivery_key",
        unique=True,
        partialFilterExpression={"delivery_key": {"$type": "string"}},
    )


async def ensure_document_indexes(database: Database[dict[str, Any]]) -> None:
    documents = database["documents"]
    await documents.create_index([("group_id", 1), ("created_at", -1)])
    await documents.create_index([("group_id", 1), ("status", 1)])
    await documents.create_index([("uploader_id", 1), ("created_at", -1)])


async def ensure_mongo_document_storage_indexes(
    database: Database[dict[str, Any]],
) -> None:
    await database["document_chunks"].create_index(
        [("group_id", 1), ("document_id", 1), ("chunk_index", 1)],
        unique=True,
    )
    await database["document_files.files"].create_index(
        "metadata.storage_key",
        unique=True,
        partialFilterExpression={"metadata.storage_key": {"$type": "string"}},
    )


async def ensure_notification_indexes(database: Database[dict[str, Any]]) -> None:
    notifications = database["notifications"]
    await notifications.create_index(
        "event_key",
        unique=True,
        partialFilterExpression={"event_key": {"$type": "string"}},
    )
    await notifications.create_index(
        [("recipient_id", 1), ("created_at", -1), ("_id", -1)]
    )
    await notifications.create_index([("recipient_id", 1), ("read_at", 1)])
