from typing import Annotated, Any, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pymongo.database import Database

from app.core.security import get_current_user
from app.database.mongodb import get_database
from app.repositories.connections import (
    delete_accepted_connection,
    delete_pending_request,
    get_request,
    list_accepted_connections,
    list_pending_requests,
    send_friend_request,
    update_pending_request,
)
from app.repositories.users import get_user_by_id, get_users_by_ids
from app.schemas.auth import AuthenticatedUser
from app.schemas.connections import (
    ConnectionRequestResponse,
    ConnectionRequestsPage,
    ConnectionsPage,
    FriendRequestActionResponse,
    FriendRequestCreate,
)
from app.schemas.users import PublicUserProfile
from app.services.notifications import notify_user_best_effort

router = APIRouter()


def _public_profile(user: dict[str, Any]) -> PublicUserProfile:
    return PublicUserProfile(
        id=str(user["_id"]),
        username=user["username"],
        full_name=user["full_name"],
        profile_picture_url=user.get("profile_picture_url"),
        bio=user.get("bio"),
        status_message=user.get("status_message"),
        created_at=user["created_at"],
    )


def _request_response(
    relationship: dict[str, Any],
    profiles: dict[ObjectId, PublicUserProfile],
) -> ConnectionRequestResponse | None:
    sender = profiles.get(relationship["sender_id"])
    recipient = profiles.get(relationship["recipient_id"])
    if sender is None or recipient is None:
        return None
    return ConnectionRequestResponse(
        id=str(relationship["_id"]),
        sender=sender,
        recipient=recipient,
        status=relationship["status"],
        created_at=relationship["created_at"],
        updated_at=relationship["updated_at"],
    )


@router.post(
    "/requests",
    response_model=FriendRequestActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a friend request",
)
async def create_friend_request(
    payload: FriendRequestCreate,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    response: Response,
) -> FriendRequestActionResponse:
    if payload.recipient_id.lower() == current_user.id.lower():
        raise HTTPException(status_code=400, detail="Cannot send a request to yourself")
    recipient = await get_user_by_id(database, payload.recipient_id)
    if recipient is None:
        raise HTTPException(status_code=404, detail="Recipient user not found")

    outcome, relationship = await send_friend_request(
        database, current_user.id, str(recipient["_id"])
    )
    if outcome == "duplicate_pending":
        raise HTTPException(status_code=409, detail="Friend request is already pending")
    if outcome == "already_connected":
        raise HTTPException(status_code=409, detail="Users are already connected")
    if outcome == "conflict" or relationship is None:
        raise HTTPException(
            status_code=409,
            detail="Friend request state changed; please retry",
        )

    automatically_accepted = outcome == "accepted"
    if outcome == "created":
        created_at = relationship["created_at"].isoformat()
        recipient_id = str(relationship["recipient_id"])
        await notify_user_best_effort(
            database,
            recipient_id=relationship["recipient_id"],
            event_key=(
                f"connection:{relationship['_id']}:request:{recipient_id}:{created_at}"
            ),
            notification_type="connection_request",
            title="New connection request",
            description="You received a connection request.",
            related_entity_id=str(relationship["_id"]),
            related_entity_type="connection",
        )
    elif automatically_accepted:
        # The existing request's sender is the requester whose request was accepted.
        requester_id = str(relationship["sender_id"])
        created_at = relationship["created_at"].isoformat()
        await notify_user_best_effort(
            database,
            recipient_id=relationship["sender_id"],
            event_key=(
                f"connection:{relationship['_id']}:accepted:{requester_id}:{created_at}"
            ),
            notification_type="connection_accepted",
            title="Connection request accepted",
            description="Your connection request was accepted.",
            related_entity_id=str(relationship["_id"]),
            related_entity_type="connection",
        )
    if automatically_accepted:
        response.status_code = status.HTTP_200_OK
    return FriendRequestActionResponse(
        id=str(relationship["_id"]),
        status=relationship["status"],
        message=(
            "Opposite pending request automatically accepted"
            if automatically_accepted
            else "Friend request sent"
        ),
    )


async def _list_requests(
    database: Database[dict[str, Any]],
    current_user_id: str,
    direction: Literal["incoming", "outgoing"],
    limit: int,
    offset: int,
) -> ConnectionRequestsPage:
    relationships = await list_pending_requests(
        database,
        user_id=current_user_id,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    user_ids = [
        user_id
        for relationship in relationships
        for user_id in (relationship["sender_id"], relationship["recipient_id"])
    ]
    users = await get_users_by_ids(database, user_ids)
    profiles = {user["_id"]: _public_profile(user) for user in users}
    items = []
    for relationship in relationships:
        item = _request_response(relationship, profiles)
        if item is not None:
            items.append(item)
    return ConnectionRequestsPage(items=items, limit=limit, offset=offset)


@router.get(
    "/requests/incoming",
    response_model=ConnectionRequestsPage,
    summary="List incoming pending friend requests",
)
async def incoming_requests(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConnectionRequestsPage:
    return await _list_requests(database, current_user.id, "incoming", limit, offset)


@router.get(
    "/requests/outgoing",
    response_model=ConnectionRequestsPage,
    summary="List outgoing pending friend requests",
)
async def outgoing_requests(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConnectionRequestsPage:
    return await _list_requests(database, current_user.id, "outgoing", limit, offset)


async def _transition_request(
    request_id: str,
    *,
    action: Literal["accept", "reject"],
    new_status: Literal["accepted", "rejected"],
    current_user: AuthenticatedUser,
    database: Database[dict[str, Any]],
) -> FriendRequestActionResponse:
    relationship = await get_request(database, request_id)
    if relationship is None:
        raise HTTPException(status_code=404, detail="Friend request not found")
    if relationship["recipient_id"] != ObjectId(current_user.id):
        raise HTTPException(
            status_code=403,
            detail="Only the recipient can " + action + " this request",
        )
    if relationship["status"] != "pending":
        raise HTTPException(status_code=409, detail="Friend request is not pending")

    updated = await update_pending_request(
        database,
        request_id=request_id,
        user_id=current_user.id,
        role="recipient",
        status=new_status,
    )
    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="Friend request state changed; please retry",
        )
    if new_status == "accepted":
        requester_id = str(updated["sender_id"])
        created_at = updated["created_at"].isoformat()
        await notify_user_best_effort(
            database,
            recipient_id=updated["sender_id"],
            event_key=(
                f"connection:{updated['_id']}:accepted:{requester_id}:{created_at}"
            ),
            notification_type="connection_accepted",
            title="Connection request accepted",
            description="Your connection request was accepted.",
            related_entity_id=str(updated["_id"]),
            related_entity_type="connection",
        )
    return FriendRequestActionResponse(
        id=str(updated["_id"]),
        status=updated["status"],
        message=f"Friend request {action}ed",
    )


@router.post(
    "/requests/{request_id}/accept",
    response_model=FriendRequestActionResponse,
    summary="Accept an incoming friend request",
)
async def accept_request(
    request_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> FriendRequestActionResponse:
    return await _transition_request(
        request_id,
        action="accept",
        new_status="accepted",
        current_user=current_user,
        database=database,
    )


@router.post(
    "/requests/{request_id}/reject",
    response_model=FriendRequestActionResponse,
    summary="Reject an incoming friend request",
)
async def reject_request(
    request_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> FriendRequestActionResponse:
    return await _transition_request(
        request_id,
        action="reject",
        new_status="rejected",
        current_user=current_user,
        database=database,
    )


@router.delete(
    "/requests/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel an outgoing pending friend request",
)
async def cancel_request(
    request_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> None:
    relationship = await get_request(database, request_id)
    if relationship is None:
        raise HTTPException(status_code=404, detail="Friend request not found")
    if relationship["sender_id"] != ObjectId(current_user.id):
        raise HTTPException(
            status_code=403,
            detail="Only the sender can cancel this request",
        )
    if relationship["status"] != "pending":
        raise HTTPException(status_code=409, detail="Friend request is not pending")
    deleted = await delete_pending_request(
        database, request_id=request_id, sender_id=current_user.id
    )
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Friend request state changed; please retry",
        )


@router.get(
    "",
    response_model=ConnectionsPage,
    summary="List accepted connections",
)
async def list_connections(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConnectionsPage:
    relationships = await list_accepted_connections(
        database,
        current_user.id,
        limit=limit,
        offset=offset,
    )
    current_id = ObjectId(current_user.id)
    friend_ids = [
        relationship["recipient_id"]
        if relationship["sender_id"] == current_id
        else relationship["sender_id"]
        for relationship in relationships
    ]
    users = await get_users_by_ids(database, friend_ids)
    profiles = {user["_id"]: _public_profile(user) for user in users}
    return ConnectionsPage(
        items=[profiles[user_id] for user_id in friend_ids if user_id in profiles],
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an accepted connection",
)
async def remove_connection(
    user_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> None:
    if user_id.lower() == current_user.id.lower():
        raise HTTPException(status_code=400, detail="Cannot remove yourself")
    removed = await delete_accepted_connection(database, current_user.id, user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Connection not found")
