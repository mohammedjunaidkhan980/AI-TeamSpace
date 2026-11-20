import asyncio
import os
from pathlib import Path
from typing import Any, Protocol

from pymongo.database import Database

from app.core.config import Settings


class DocumentStorage(Protocol):
    async def put(self, storage_key: str, data: bytes) -> None: ...

    async def read(self, storage_key: str) -> bytes: ...

    async def delete(self, storage_key: str) -> None: ...


class LocalDocumentStorage:
    def __init__(self, settings: Settings) -> None:
        self._root = Path(settings.document_storage_path).expanduser().resolve()

    def _resolve(self, storage_key: str) -> Path:
        path = (self._root / storage_key).resolve()
        if self._root not in path.parents:
            raise ValueError("Invalid document storage key")
        return path

    def path_for(self, storage_key: str) -> Path:
        return self._resolve(storage_key)

    async def put(self, storage_key: str, data: bytes) -> None:
        path = self._resolve(storage_key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def read(self, storage_key: str) -> bytes:
        return await asyncio.to_thread(self._resolve(storage_key).read_bytes)

    async def delete(self, storage_key: str) -> None:
        path = self._resolve(storage_key)

        def remove() -> None:
            try:
                os.remove(path)
            except FileNotFoundError:
                return

        await asyncio.to_thread(remove)


def create_document_storage(
    database: Database[dict[str, Any]],
    settings: Settings,
) -> DocumentStorage:
    if settings.use_mongo_storage:
        from app.services.mongo_storage import MongoGridFSDocumentStorage

        return MongoGridFSDocumentStorage(database)
    return LocalDocumentStorage(settings)
