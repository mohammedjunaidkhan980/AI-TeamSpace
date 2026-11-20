import logging
from typing import Annotated, Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pymongo.database import Database

from app.core.security import get_current_user
from app.database.mongodb import get_database
from app.repositories.groups import (
    add_group_member,
    change_member_role,
    create_group,
    get_group,
    get_member_role,
    list_user_groups,
    remove_group_member,
    update_group,
    users_are_connected,
    valid_object_id,
)
from app.repositories.users import get_users_by_ids
from app.schemas.auth import AuthenticatedUser
from app.schemas.groups import (
    AddGroupMembers,
    AddedMembersResponse,
    GroupCreate,
    GroupDetails,
    GroupListItem,
    GroupListResponse,
    GroupMember,
    GroupUpdate,
)
from app.schemas.nexconn import GroupChatChannelResponse
from app.schemas.users import PublicUserProfile
from app.services.nexconn import NexconnAPIError, NexconnClient
from app.services.nexconn_sync import sync_nexconn_group
from app.services.notifications import notify_user_best_effort

router = APIRouter()
logger = logging.getLogger(__name__)


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


async def _group_details(
    database: Database[dict[str, Any]], group: dict[str, Any]
) -> GroupDetails:
    user_ids = [member["user_id"] for member in group.get("members", [])]
    users = await get_users_by_ids(database, user_ids)
    profiles = {user["_id"]: _public_profile(user) for user in users}
    members = [
        GroupMember(
            user=profiles[member["user_id"]],
            role=member["role"],
            joined_at=member["joined_at"],
        )
        for member in group.get("members", [])
        if member["user_id"] in profiles
    ]
    return GroupDetails(
        group_id=str(group["_id"]),
        name=group["name"],
        description=group.get("description"),
        creator_id=str(group["creator_id"]),
        group_picture_url=group.get("group_picture_url"),
        members=members,
        member_count=len(group.get("members", [])),
        created_at=group["created_at"],
        updated_at=group["updated_at"],
        settings=group.get("settings", {}),
        ai_agents=group.get("ai_agents", []),
        last_message_at=group.get("last_message_at"),
        nexconn_channel_id=group.get("nexconn_channel_id"),
        nexconn_sync_status=group.get("nexconn_sync_status", "disabled"),
        nexconn_synced_at=group.get("nexconn_synced_at"),
    )


async def _sync_group_if_enabled(
    request: Request,
    database: Database[dict[str, Any]],
    group: dict[str, Any],
) -> dict[str, Any]:
    client: NexconnClient | None = request.app.state.nexconn_client
    if client is None:
        await database["groups"].update_one(
            {"_id": group["_id"]},
            {"$set": {"nexconn_sync_status": "disabled"}},
        )
        result = group.copy()
        result["nexconn_sync_status"] = "disabled"
        return result
    try:
        return await sync_nexconn_group(database, client, group)
    except NexconnAPIError:
        logger.warning(
            "Group synchronization with Nexconn failed",
            extra={"group_id": str(group["_id"])},
        )
        latest_group = await get_group(database, str(group["_id"]))
        if latest_group is not None:
            return latest_group
        result = group.copy()
        result["nexconn_sync_status"] = "failed"
        return result


async def _require_group(
    database: Database[dict[str, Any]],
    group_id: str,
    user_id: str,
    *,
    admin: bool = False,
) -> tuple[dict[str, Any], str]:
    group = await get_group(database, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    role = get_member_role(group, user_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Group membership required")
    if admin and role != "admin":
        raise HTTPException(status_code=403, detail="Group admin role required")
    return group, role


async def _validate_users_exist(
    database: Database[dict[str, Any]], user_ids: list[str]
) -> list[ObjectId]:
    ids = [ObjectId(user_id) for user_id in user_ids]
    users = await get_users_by_ids(database, ids)
    found = {user["_id"] for user in users}
    if found != set(ids):
        raise HTTPException(status_code=404, detail="One or more users were not found")
    return ids


@router.post(
    "",
    response_model=GroupDetails,
    status_code=status.HTTP_201_CREATED,
    summary="Create a group",
)
async def create_new_group(
    request: Request,
    payload: GroupCreate,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupDetails:
    requested_ids = [
        user_id
        for user_id in payload.member_ids
        if user_id.lower() != current_user.id.lower()
    ]
    object_ids = await _validate_users_exist(database, requested_ids)
    for member_id in requested_ids:
        if not await users_are_connected(database, current_user.id, member_id):
            raise HTTPException(
                status_code=403,
                detail="All initial members must be connected to the group creator",
            )

    group = await create_group(
        database,
        name=payload.name,
        description=payload.description,
        creator_id=current_user.id,
        member_ids=[str(user_id) for user_id in object_ids],
    )
    for member_id in object_ids:
        recipient_id = str(member_id)
        await notify_user_best_effort(
            database,
            recipient_id=member_id,
            event_key=f"group:{group['_id']}:created:member:{recipient_id}",
            notification_type="group_invitation",
            title="Added to a group",
            description=f"You were added to {group['name']}.",
            related_entity_id=str(group["_id"]),
            related_entity_type="group",
            group_id=str(group["_id"]),
        )
    group = await _sync_group_if_enabled(request, database, group)
    return await _group_details(database, group)


@router.get(
    "",
    response_model=GroupListResponse,
    summary="List groups for the current user",
)
async def get_my_groups(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> GroupListResponse:
    groups = await list_user_groups(
        database,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    items = []
    for group in groups:
        role = get_member_role(group, current_user.id)
        if role is None:
            continue
        items.append(
            GroupListItem(
                group_id=str(group["_id"]),
                name=group["name"],
                description=group.get("description"),
                creator_id=str(group["creator_id"]),
                created_at=group["created_at"],
                member_count=len(group.get("members", [])),
                current_user_role=role,
                last_message_at=group.get("last_message_at"),
            )
        )
    return GroupListResponse(items=items, limit=limit, offset=offset)


@router.get(
    "/{group_id}",
    response_model=GroupDetails,
    summary="Get group details",
)
async def get_group_details(
    group_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupDetails:
    group, _ = await _require_group(database, group_id, current_user.id)
    return await _group_details(database, group)


@router.put(
    "/{group_id}",
    response_model=GroupDetails,
    summary="Update group information",
)
async def update_group_details(
    request: Request,
    group_id: str,
    payload: GroupUpdate,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupDetails:
    await _require_group(database, group_id, current_user.id, admin=True)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("group_picture_url") is not None:
        changes["group_picture_url"] = str(changes["group_picture_url"])
    group = await update_group(database, group_id, current_user.id, changes)
    if group is None:
        raise HTTPException(status_code=403, detail="Group admin role required")
    group = await _sync_group_if_enabled(request, database, group)
    return await _group_details(database, group)


@router.post(
    "/{group_id}/members",
    response_model=AddedMembersResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add connected users to a group",
)
async def add_members(
    request: Request,
    group_id: str,
    payload: AddGroupMembers,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> AddedMembersResponse:
    group, _ = await _require_group(database, group_id, current_user.id, admin=True)
    user_ids = [
        user_id
        for user_id in payload.user_ids
        if ObjectId(user_id)
        not in {member["user_id"] for member in group.get("members", [])}
    ]
    object_ids = await _validate_users_exist(database, user_ids)
    for user_id in user_ids:
        if not await users_are_connected(database, current_user.id, user_id):
            raise HTTPException(
                status_code=403,
                detail="All added users must be connected to the adding admin",
            )

    added_ids: list[ObjectId] = []
    for user_id in object_ids:
        if await add_group_member(
            database,
            group_id=group_id,
            user_id=str(user_id),
            admin_id=current_user.id,
        ):
            added_ids.append(user_id)
    users = await get_users_by_ids(database, added_ids)
    user_map = {user["_id"]: user for user in users}
    updated_group = await get_group(database, group_id)
    joined_at_by_id = {
        member["user_id"]: member["joined_at"]
        for member in updated_group.get("members", [])
    } if updated_group is not None else {}
    if updated_group is not None:
        for member_id in added_ids:
            joined_at = joined_at_by_id.get(member_id)
            if joined_at is None:
                continue
            recipient_id = str(member_id)
            await notify_user_best_effort(
                database,
                recipient_id=member_id,
                event_key=(
                    f"group:{updated_group['_id']}:member_added:{recipient_id}:"
                    f"{joined_at.isoformat()}"
                ),
                notification_type="group_member_added",
                title="Added to a group",
                description=f"You were added to {updated_group['name']}.",
                related_entity_id=str(updated_group["_id"]),
                related_entity_type="group",
                group_id=str(updated_group["_id"]),
            )
    members = [
        GroupMember(
            user=_public_profile(user_map[user_id]),
            role="member",
            joined_at=joined_at_by_id[user_id],
        )
        for user_id in added_ids
        if user_id in user_map and user_id in joined_at_by_id
    ]
    if updated_group is not None:
        updated_group = await _sync_group_if_enabled(request, database, updated_group)
    return AddedMembersResponse(
        members=members,
        nexconn_sync_status=(
            updated_group.get("nexconn_sync_status", "disabled")
            if updated_group is not None
            else "disabled"
        ),
    )


@router.delete(
    "/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member or leave a group",
)
async def remove_member(
    request: Request,
    group_id: str,
    user_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> None:
    if not valid_object_id(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    group, actor_role = await _require_group(database, group_id, current_user.id)
    target_id = ObjectId(user_id)
    if target_id == group["creator_id"]:
        raise HTTPException(
            status_code=409,
            detail="The group creator cannot be removed",
        )
    is_self = user_id.lower() == current_user.id.lower()
    if not is_self and actor_role != "admin":
        raise HTTPException(status_code=403, detail="Group admin role required")
    removed = await remove_group_member(
        database,
        group_id=group_id,
        target_user_id=user_id,
        actor_id=current_user.id,
        actor_is_admin=actor_role == "admin",
    )
    if not removed:
        raise HTTPException(
            status_code=409,
            detail="Member not found or the last admin cannot leave the group",
        )
    updated_group = await get_group(database, group_id)
    if updated_group is not None:
        await _sync_group_if_enabled(request, database, updated_group)


@router.post(
    "/{group_id}/sync",
    response_model=GroupDetails,
    summary="Manually trigger Nexconn sync for an existing group",
)
async def sync_group(
    request: Request,
    group_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupDetails:
    group, _ = await _require_group(database, group_id, current_user.id, admin=True)
    client: NexconnClient | None = request.app.state.nexconn_client
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nexconn integration is disabled",
        )
    try:
        group = await sync_nexconn_group(database, client, group)
    except NexconnAPIError:
        logger.warning(
            "Manual Nexconn group sync failed",
            extra={"group_id": group_id},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nexconn group sync failed",
        ) from None
    return await _group_details(database, group)


@router.get(
    "/{group_id}/chat-channel",
    response_model=GroupChatChannelResponse,
    summary="Get the current member's Nexconn chat channel",
)
async def get_group_chat_channel(
    request: Request,
    group_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupChatChannelResponse:
    group, _ = await _require_group(database, group_id, current_user.id)
    client: NexconnClient | None = request.app.state.nexconn_client
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nexconn integration is disabled",
        )
    if (
        group.get("nexconn_sync_status") != "synced"
        or not group.get("nexconn_channel_id")
    ):
        try:
            group = await sync_nexconn_group(database, client, group)
        except NexconnAPIError:
            logger.warning(
                "Could not synchronize Nexconn group channel",
                extra={"group_id": group_id},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Group chat channel is not available",
            ) from None
    channel_id = group.get("nexconn_channel_id")
    if not channel_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Group chat channel is not available",
        )
    return GroupChatChannelResponse(
        group_id=group_id,
        channel_id=channel_id,
        sync_status="synced",
    )


@router.post(
    "/{group_id}/admins/{user_id}",
    response_model=GroupMember,
    summary="Promote a group member to admin",
)
async def promote_admin(
    group_id: str,
    user_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupMember:
    group, _ = await _require_group(database, group_id, current_user.id, admin=True)
    if not valid_object_id(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    target = ObjectId(user_id)
    if target not in {member["user_id"] for member in group.get("members", [])}:
        raise HTTPException(status_code=404, detail="Group member not found")
    changed = await change_member_role(
        database,
        group_id=group_id,
        admin_id=current_user.id,
        target_user_id=user_id,
        role="admin",
    )
    if not changed:
        raise HTTPException(status_code=409, detail="Member is already an admin")
    user = await get_users_by_ids(database, [target])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return GroupMember(
        user=_public_profile(user[0]),
        role="admin",
        joined_at=next(
            member["joined_at"]
            for member in group["members"]
            if member["user_id"] == target
        ),
    )


@router.delete(
    "/{group_id}/admins/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Demote a group admin",
)
async def demote_admin(
    group_id: str,
    user_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> None:
    group, _ = await _require_group(database, group_id, current_user.id, admin=True)
    if not valid_object_id(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    target = ObjectId(user_id)
    if target == group["creator_id"]:
        raise HTTPException(status_code=409, detail="The group creator cannot be demoted")
    if target == ObjectId(current_user.id):
        raise HTTPException(status_code=400, detail="Admins cannot demote themselves")
    if target not in {member["user_id"] for member in group.get("members", [])}:
        raise HTTPException(status_code=404, detail="Group member not found")
    changed = await change_member_role(
        database,
        group_id=group_id,
        admin_id=current_user.id,
        target_user_id=user_id,
        role="member",
    )
    if not changed:
        raise HTTPException(
            status_code=409,
            detail="Target is not an admin or the last admin cannot be demoted",
        )
