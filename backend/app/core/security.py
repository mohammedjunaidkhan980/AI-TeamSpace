import asyncio
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import uuid4

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from pymongo.database import Database

from app.core.config import Settings
from app.database.indexes import ensure_revoked_token_indexes
from app.database.mongodb import get_database
from app.repositories.users import get_user_by_id
from app.schemas.auth import AuthenticatedUser

bearer_scheme = HTTPBearer(auto_error=False)
SUPPORTED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}


def _validate_jwt_settings(settings: Settings) -> None:
    if (
        settings.jwt_algorithm not in SUPPORTED_JWT_ALGORITHMS
        or len(settings.jwt_secret_key.encode("utf-8")) < 32
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT authentication is not configured",
        )


async def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    hashed = await asyncio.to_thread(bcrypt.hashpw, password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


async def verify_password(password: str, password_hash: str) -> bool:
    try:
        return await asyncio.to_thread(
            bcrypt.checkpw,
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str, settings: Settings
) -> tuple[str, str, datetime]:
    _validate_jwt_settings(settings)
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    token_id = str(uuid4())
    token = jwt.encode(
        {
            "sub": subject,
            "jti": token_id,
            "iat": issued_at,
            "exp": expires_at,
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, token_id, expires_at


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> AuthenticatedUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    settings: Settings = request.app.state.settings
    _validate_jwt_settings(settings)
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "jti", "exp"]},
        )
        user_id = payload["sub"]
        token_id = payload["jti"]
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        if not isinstance(user_id, str) or not isinstance(token_id, str):
            raise InvalidTokenError("Invalid token claim types")
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None

    if not request.app.state.revoked_token_indexes_ready:
        async with request.app.state.revoked_token_indexes_lock:
            if not request.app.state.revoked_token_indexes_ready:
                await ensure_revoked_token_indexes(database)
                request.app.state.revoked_token_indexes_ready = True
    revoked = await database["revoked_tokens"].find_one({"_id": token_id})
    if revoked is not None:
        raise unauthorized

    user = await get_user_by_id(database, user_id)
    if user is None:
        raise unauthorized

    return AuthenticatedUser(
        id=str(user["_id"]),
        username=user["username"],
        full_name=user["full_name"],
        email=user["email"],
        created_at=user["created_at"],
        token_id=token_id,
        token_expires_at=expires_at,
    )
