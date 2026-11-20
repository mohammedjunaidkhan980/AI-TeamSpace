from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pymongo import AsyncMongoClient

from app.database.mongodb import check_mongodb_connection
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
    summary="Check application and MongoDB health",
)
async def health_check(request: Request) -> JSONResponse:
    client: AsyncMongoClient = request.app.state.mongo_client
    connected = await check_mongodb_connection(client)
    response = HealthResponse(
        status="ok" if connected else "degraded",
        mongodb="connected" if connected else "disconnected",
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if connected else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(),
    )
