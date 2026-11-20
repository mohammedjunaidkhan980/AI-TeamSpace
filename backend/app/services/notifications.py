import logging
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.repositories.notifications import create_notification

logger = logging.getLogger(__name__)


async def notify_user(
    database: Database[dict[str, Any]],
    *,
    recipient_id: ObjectId | str,
    event_key: str,
    notification_type: str,
    title: str,
    description: str,
    related_entity_id: str | None = None,
    related_entity_type: str | None = None,
    group_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await create_notification(
        database,
        recipient_id=recipient_id if isinstance(recipient_id, ObjectId) else ObjectId(recipient_id),
        event_key=event_key,
        notification_type=notification_type,
        title=title,
        description=description,
        related_entity_id=related_entity_id,
        related_entity_type=related_entity_type,
        group_id=group_id,
        metadata=metadata,
    )


async def notify_group_members(
    database: Database[dict[str, Any]],
    *,
    group: dict[str, Any],
    event_key: str,
    notification_type: str,
    title: str,
    description: str,
    exclude_user_id: ObjectId | str | None = None,
    related_entity_id: str | None = None,
    related_entity_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    excluded = str(exclude_user_id) if exclude_user_id is not None else None
    for member in group.get("members", []):
        recipient_id = member.get("user_id")
        if recipient_id is None or str(recipient_id) == excluded:
            continue
        await notify_user(
            database,
            recipient_id=recipient_id,
            event_key=f"{event_key}:{recipient_id}",
            notification_type=notification_type,
            title=title,
            description=description,
            related_entity_id=related_entity_id,
            related_entity_type=related_entity_type,
            group_id=str(group["_id"]),
            metadata=metadata,
        )


async def notify_user_best_effort(
    database: Database[dict[str, Any]],
    *,
    recipient_id: ObjectId | str,
    event_key: str,
    notification_type: str,
    title: str,
    description: str,
    related_entity_id: str | None = None,
    related_entity_type: str | None = None,
    group_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        await notify_user(
            database,
            recipient_id=recipient_id,
            event_key=event_key,
            notification_type=notification_type,
            title=title,
            description=description,
            related_entity_id=related_entity_id,
            related_entity_type=related_entity_type,
            group_id=group_id,
            metadata=metadata,
        )
    except Exception:
        logger.exception(
            "Notification creation failed",
            extra={"event_key": event_key, "notification_type": notification_type},
        )


async def notify_group_members_best_effort(
    database: Database[dict[str, Any]],
    *,
    group: dict[str, Any],
    event_key: str,
    notification_type: str,
    title: str,
    description: str,
    exclude_user_id: ObjectId | str | None = None,
    related_entity_id: str | None = None,
    related_entity_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        await notify_group_members(
            database,
            group=group,
            event_key=event_key,
            notification_type=notification_type,
            title=title,
            description=description,
            exclude_user_id=exclude_user_id,
            related_entity_id=related_entity_id,
            related_entity_type=related_entity_type,
            metadata=metadata,
        )
    except Exception:
        logger.exception(
            "Group notification creation failed",
            extra={"event_key": event_key, "notification_type": notification_type},
        )
