from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database.indexes import ensure_revoked_token_indexes
from app.database.mongodb import get_database
from app.repositories.users import (
    create_user,
    find_user_conflict,
    get_user_by_email,
)
from app.schemas.auth import (
    AuthenticatedUser,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RegisterRequest,
    UserProfile,
)

router = APIRouter()


@router.post(
    "/register",
    response_model=UserProfile,
    status_code=status.HTTP_201_CREATED,
    summary="Register a user",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> UserProfile:
    if await find_user_conflict(
        database, username=payload.username, email=str(payload.email)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username is already registered",
        )

    password_hash = await hash_password(payload.password)
    try:
        user = await create_user(
            database,
            username=payload.username,
            full_name=payload.full_name,
            email=str(payload.email),
            password_hash=password_hash,
        )
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username is already registered",
        ) from None

    request.app.state.logger.info("User registered", extra={"user_id": user["id"]})
    return UserProfile.model_validate(user)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Log in and receive an access token",
)
async def login(
    payload: LoginRequest,
    request: Request,
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> LoginResponse:
    user = await get_user_by_email(database, str(payload.email))
    password_hash = user.get("password_hash", "") if user else ""
    if user is None or not await verify_password(payload.password, password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings: Settings = request.app.state.settings
    token, _, _ = create_access_token(str(user["_id"]), settings)
    request.app.state.logger.info(
        "User logged in", extra={"user_id": str(user["_id"])}
    )
    return LoginResponse(
        access_token=token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=UserProfile(
            id=str(user["_id"]),
            username=user["username"],
            full_name=user["full_name"],
            email=user["email"],
            created_at=user["created_at"],
        ),
    )


@router.get(
    "/me",
    response_model=UserProfile,
    summary="Get the authenticated user's profile",
)
async def current_user(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> UserProfile:
    return UserProfile.model_validate(user.model_dump())


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Revoke the current access token",
)
async def logout(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> LogoutResponse:
    if not request.app.state.revoked_token_indexes_ready:
        async with request.app.state.revoked_token_indexes_lock:
            if not request.app.state.revoked_token_indexes_ready:
                await ensure_revoked_token_indexes(database)
                request.app.state.revoked_token_indexes_ready = True
    await database["revoked_tokens"].update_one(
        {"_id": user.token_id},
        {"$setOnInsert": {"expires_at": user.token_expires_at}},
        upsert=True,
    )
    return LogoutResponse(message="Successfully logged out")
