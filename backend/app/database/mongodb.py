import logging
from typing import Any

from fastapi import Request
from pymongo import AsyncMongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.core.config import Settings

logger = logging.getLogger(__name__)


def create_mongo_client(settings: Settings) -> AsyncMongoClient[dict[str, Any]]:
    return AsyncMongoClient(settings.mongodb_url)


def get_database(request: Request) -> Database[dict[str, Any]]:
    settings: Settings = request.app.state.settings
    client: AsyncMongoClient[dict[str, Any]] = request.app.state.mongo_client
    return client.get_database(settings.mongodb_database)


async def check_mongodb_connection(
    client: AsyncMongoClient[dict[str, Any]],
) -> bool:
    try:
        await client.admin.command("ping")
    except PyMongoError:
        logger.warning("MongoDB health check failed", exc_info=True)
        return False
    return True
