from typing import Annotated, Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pymongo.database import Database

from app.core.security import get_current_user
from app.database.mongodb import get_database
from app.repositories.notifications import (
    delete_notification,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
from app.schemas.auth import AuthenticatedUser
from app.schemas.notifications import (
    NotificationListResponse,
    NotificationReadResult,
    NotificationResponse,
    NotificationUnreadCount,
)

router = APIRouter()


def _notification_response(document: dict[str, Any]) -> NotificationResponse:
    return NotificationResponse(
        notification_id=str(document["_id"]),
        type=document["type"],
        title=document["title"],
        description=document["description"],
        related_entity_id=document.get("related_entity_id"),
        related_entity_type=document.get("related_entity_type"),
        group_id=document.get("group_id"),
        is_read=document.get("read_at") is not None,
        created_at=document["created_at"],
        metadata=document.get("metadata", {}),
    )


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: Annotated[str | None, Query()] = None,
) -> NotificationListResponse:
    page, next_cursor, unread_count = await list_notifications(
        database,
        recipient_id=ObjectId(current_user.id),
        limit=limit,
        before=before,
    )
    return NotificationListResponse(
        items=[_notification_response(item) for item in page],
        limit=limit,
        next_cursor=next_cursor,
        unread_count=unread_count,
    )


@router.get("/unread-count", response_model=NotificationUnreadCount)
async def get_unread_count(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> NotificationUnreadCount:
    return NotificationUnreadCount(
        unread_count=await database["notifications"].count_documents(
            {"recipient_id": ObjectId(current_user.id), "read_at": None}
        )
    )


@router.put("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_notification(
    notification_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> Response:
    updated = await mark_notification_read(
        database,
        recipient_id=ObjectId(current_user.id),
        notification_id=notification_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/read-all", response_model=NotificationReadResult)
async def read_all_notifications(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> NotificationReadResult:
    updated_count = await mark_all_notifications_read(
        database,
        recipient_id=ObjectId(current_user.id),
    )
    return NotificationReadResult(updated_count=updated_count)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_notification(
    notification_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> Response:
    removed = await delete_notification(
        database,
        recipient_id=ObjectId(current_user.id),
        notification_id=notification_id,
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Notification not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
