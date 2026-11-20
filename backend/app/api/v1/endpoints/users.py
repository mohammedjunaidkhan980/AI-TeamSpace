import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.core.security import get_current_user
from app.database.indexes import ensure_user_indexes
from app.database.mongodb import get_database
from app.repositories.users import (
    get_user_by_id,
    search_users,
    update_user_profile,
)
from app.schemas.auth import AuthenticatedUser
from app.schemas.users import (
    PublicUserProfile,
    UserProfileResponse,
    UserProfileUpdate,
    UserSearchResponse,
)

router = APIRouter()


def _profile_document(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(user["_id"]),
        "username": user["username"],
        "full_name": user["full_name"],
        "email": user["email"],
        "profile_picture_url": user.get("profile_picture_url"),
        "bio": user.get("bio"),
        "status_message": user.get("status_message"),
        "created_at": user["created_at"],
    }


def _public_profile_document(user: dict[str, Any]) -> dict[str, Any]:
    profile = _profile_document(user)
    profile.pop("email")
    return profile


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get the authenticated user's complete profile",
)
async def get_my_profile(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> UserProfileResponse:
    user = await get_user_by_id(database, current_user.id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return UserProfileResponse.model_validate(_profile_document(user))


@router.put(
    "/me",
    response_model=UserProfileResponse,
    summary="Update the authenticated user's profile",
)
async def update_my_profile(
    payload: UserProfileUpdate,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> UserProfileResponse:
    await ensure_user_indexes(database)
    changes = payload.model_dump(exclude_unset=True)
    if "profile_picture_url" in changes and changes["profile_picture_url"] is not None:
        changes["profile_picture_url"] = str(changes["profile_picture_url"])

    try:
        user = await update_user_profile(database, current_user.id, changes)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already taken",
        ) from None

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return UserProfileResponse.model_validate(_profile_document(user))


@router.get(
    "/search",
    response_model=UserSearchResponse,
    summary="Search for users",
)
async def search_for_users(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserSearchResponse:
    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=422,
            detail="Search query must not be empty",
        )

    await ensure_user_indexes(database)
    users = await search_users(
        database,
        query=re.escape(query),
        exclude_user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return UserSearchResponse(
        items=[
            PublicUserProfile.model_validate(_public_profile_document(user))
            for user in users
        ],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{user_id}",
    response_model=PublicUserProfile,
    summary="Get a user's public profile",
)
async def get_user_profile(
    user_id: str,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> PublicUserProfile:
    user = await get_user_by_id(database, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return PublicUserProfile.model_validate(_public_profile_document(user))
