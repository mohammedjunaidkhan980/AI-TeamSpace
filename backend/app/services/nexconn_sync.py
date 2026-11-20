from datetime import datetime, timezone
from typing import Any

from pymongo.database import Database

from app.repositories.users import get_users_by_ids
from app.services.nexconn import NexconnAPIError, NexconnClient

GROUPS_COLLECTION = "groups"
USERS_COLLECTION = "users"
GROUP_JOIN_BATCH_SIZE = 30


def _user_profile(user: dict[str, Any]) -> tuple[str, str | None]:
    return user["full_name"], user.get("profile_picture_url")


async def sync_nexconn_user(
    database: Database[dict[str, Any]],
    client: NexconnClient,
    user: dict[str, Any],
    *,
    issue_token: bool = False,
) -> str | None:
    user_id = str(user["_id"])
    name, avatar_url = _user_profile(user)
    profile = {"name": name, "avatar_url": avatar_url}
    is_synced = (
        user.get("nexconn_sync_status") == "synced"
        and user.get("nexconn_synced_at") is not None
    )
    try:
        if is_synced:
            if user.get("nexconn_synced_profile") != profile:
                await client.update_user(
                    user_id=user_id,
                    name=name,
                    avatar_url=avatar_url,
                )
            token = (
                await client.issue_access_token(
                    user_id=user_id,
                    name=name,
                    avatar_url=avatar_url,
                )
                if issue_token
                else None
            )
        else:
            token = await client.issue_access_token(
                user_id=user_id,
                name=name,
                avatar_url=avatar_url,
            )
    except NexconnAPIError:
        await database[USERS_COLLECTION].update_one(
            {"_id": user["_id"]},
            {"$set": {"nexconn_sync_status": "failed"}},
        )
        raise

    await database[USERS_COLLECTION].update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "nexconn_sync_status": "synced",
                "nexconn_synced_at": datetime.now(timezone.utc),
                "nexconn_synced_profile": profile,
            }
        },
    )
    return token


async def sync_nexconn_group(
    database: Database[dict[str, Any]],
    client: NexconnClient,
    group: dict[str, Any],
) -> dict[str, Any]:
    group_id = str(group["_id"])
    members = group.get("members", [])
    member_ids = [str(member["user_id"]) for member in members]
    users = await get_users_by_ids(
        database, [member["user_id"] for member in members]
    )
    user_by_id = {str(user["_id"]): user for user in users}
    if len(user_by_id) != len(set(member_ids)):
        await database[GROUPS_COLLECTION].update_one(
            {"_id": group["_id"]},
            {"$set": {"nexconn_sync_status": "failed"}},
        )
        raise NexconnAPIError("A group member is missing from the user collection")

    await database[GROUPS_COLLECTION].update_one(
        {"_id": group["_id"]},
        {"$set": {"nexconn_sync_status": "pending"}},
    )
    try:
        for member_id in member_ids:
            await sync_nexconn_user(
                database,
                client,
                user_by_id[member_id],
            )

        channel_id = group.get("nexconn_channel_id")
        channel_created = channel_id is not None
        group_profile = {
            "description": group.get("description"),
            "picture_url": group.get("group_picture_url"),
        }
        profile_is_synced = group.get("nexconn_synced_profile") == group_profile
        synced_member_ids = set(group.get("nexconn_member_ids", []))
        if channel_id is None:
            # Nexconn channel_id must be a numeric string; derive one from the ObjectId
            channel_id = str(int(group_id, 16) % (10 ** 18)).zfill(18)
            owner_id = str(group["creator_id"])
            invitees = [user_id for user_id in member_ids if user_id != owner_id]
            initial_invitees = invitees[:GROUP_JOIN_BATCH_SIZE]
            await client.create_group_channel(
                channel_id=channel_id,
                name=group["name"],
                owner=owner_id,
                user_ids=initial_invitees,
                description=group.get("description"),
                picture_url=group.get("group_picture_url"),
            )
            synced_member_ids = {owner_id, *initial_invitees}
            await database[GROUPS_COLLECTION].update_one(
                {"_id": group["_id"]},
                {
                    "$set": {
                        "nexconn_channel_id": channel_id,
                        "nexconn_member_ids": sorted(synced_member_ids),
                        "nexconn_synced_profile": group_profile,
                    }
                },
            )

        current_member_ids = set(member_ids)
        to_join = sorted(current_member_ids - synced_member_ids)
        to_remove = sorted(synced_member_ids - current_member_ids)
        for start in range(0, len(to_join), GROUP_JOIN_BATCH_SIZE):
            batch = to_join[start : start + GROUP_JOIN_BATCH_SIZE]
            await client.join_group_channel(
                channel_id=channel_id,
                user_ids=batch,
            )
            synced_member_ids.update(batch)
            await database[GROUPS_COLLECTION].update_one(
                {"_id": group["_id"]},
                {"$set": {"nexconn_member_ids": sorted(synced_member_ids)}},
            )
        for start in range(0, len(to_remove), GROUP_JOIN_BATCH_SIZE):
            batch = to_remove[start : start + GROUP_JOIN_BATCH_SIZE]
            await client.remove_group_members(
                channel_id=channel_id,
                user_ids=batch,
            )
            synced_member_ids.difference_update(batch)
            await database[GROUPS_COLLECTION].update_one(
                {"_id": group["_id"]},
                {"$set": {"nexconn_member_ids": sorted(synced_member_ids)}},
            )

        if channel_created and not profile_is_synced:
            await client.update_group_channel_profile(
                channel_id=channel_id,
                description=group.get("description"),
                picture_url=group.get("group_picture_url"),
            )
            await database[GROUPS_COLLECTION].update_one(
                {"_id": group["_id"]},
                {"$set": {"nexconn_synced_profile": group_profile}},
            )
    except NexconnAPIError:
        await database[GROUPS_COLLECTION].update_one(
            {"_id": group["_id"]},
            {"$set": {"nexconn_sync_status": "failed"}},
        )
        raise

    await database[GROUPS_COLLECTION].update_one(
        {"_id": group["_id"]},
        {
            "$set": {
                "nexconn_channel_id": channel_id,
                "nexconn_sync_status": "synced",
                "nexconn_synced_at": datetime.now(timezone.utc),
            }
        },
    )
    updated = group.copy()
    updated.update(
        {
            "nexconn_channel_id": channel_id,
            "nexconn_member_ids": sorted(synced_member_ids),
            "nexconn_sync_status": "synced",
            "nexconn_synced_at": datetime.now(timezone.utc),
            "nexconn_synced_profile": group_profile,
        }
    )
    return updated
