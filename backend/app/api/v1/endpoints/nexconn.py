from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo.database import Database

from app.core.security import get_current_user
from app.database.mongodb import get_database
from app.repositories.users import get_user_by_id
from app.schemas.auth import AuthenticatedUser
from app.schemas.nexconn import NexconnStatusResponse, NexconnTokenResponse
from app.services.nexconn import NexconnAPIError, NexconnClient
from app.services.nexconn_sync import sync_nexconn_user

router = APIRouter()


def get_nexconn_client(request: Request) -> NexconnClient:
    client = request.app.state.nexconn_client
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nexconn integration is disabled",
        )
    return client


@router.post(
    "/token",
    response_model=NexconnTokenResponse,
    summary="Generate a Nexconn token for the current user",
)
async def generate_nexconn_token(
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database, Depends(get_database)],
    client: Annotated[NexconnClient, Depends(get_nexconn_client)],
) -> NexconnTokenResponse:
    user = await get_user_by_id(database, current_user.id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authenticated user not found")
    try:
        token = await sync_nexconn_user(
            database,
            client,
            user,
            issue_token=True,
        )
    except NexconnAPIError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nexconn token generation failed",
        ) from None
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nexconn token generation failed",
        )
    return NexconnTokenResponse(
        nexconn_token=token,
        nexconn_user_id=current_user.id,
        app_key=request.app.state.settings.nexconn_app_key,
    )


@router.get(
    "/status",
    response_model=NexconnStatusResponse,
    summary="Get Nexconn integration status",
)
async def nexconn_status(
    request: Request,
    _current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> NexconnStatusResponse:
    enabled = request.app.state.settings.nexconn_enabled
    return NexconnStatusResponse(
        enabled=enabled,
        status="enabled" if enabled else "disabled",
    )
