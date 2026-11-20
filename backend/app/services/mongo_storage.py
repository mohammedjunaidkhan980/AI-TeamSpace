import asyncio
import math
from collections.abc import AsyncIterator, Sequence
from typing import Any

from gridfs.asynchronous import AsyncGridFSBucket
from gridfs.asynchronous.grid_file import AsyncGridOut
from gridfs.errors import NoFile
from pymongo import ReplaceOne
from pymongo.database import Database
from pymongo.errors import PyMongoError


class DocumentStorageError(Exception):
    pass


class DocumentStorageCapacityError(DocumentStorageError):
    pass


class DocumentStorageNotFoundError(DocumentStorageError):
    pass


def _is_capacity_error(error: PyMongoError) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in ("storage limit", "disk quota", "exceeded storage", "quota exceeded")
    )


class MongoGridFSDocumentStorage:
    def __init__(
        self,
        database: Database[dict[str, Any]],
        *,
        bucket_name: str = "document_files",
    ) -> None:
        self._database = database
        self._bucket_name = bucket_name
        self._bucket = AsyncGridFSBucket(database, bucket_name=bucket_name)

    async def put(self, storage_key: str, data: bytes) -> None:
        upload = None
        try:
            upload = self._bucket.open_upload_stream(
                storage_key,
                metadata={"storage_key": storage_key},
            )
            await upload.write(data)
            await upload.close()
        except PyMongoError as exc:
            if upload is not None:
                try:
                    await upload.abort()
                except PyMongoError:
                    pass
            if _is_capacity_error(exc):
                raise DocumentStorageCapacityError(
                    "MongoDB storage capacity is exhausted"
                ) from exc
            raise DocumentStorageError("MongoDB document upload failed") from exc

    async def read(self, storage_key: str) -> bytes:
        download = await self.open_stream(storage_key)
        try:
            return await download.read()
        except PyMongoError as exc:
            raise DocumentStorageError("MongoDB document read failed") from exc
        finally:
            await download.close()

    async def open_stream(self, storage_key: str) -> AsyncGridOut:
        try:
            return await self._bucket.open_download_stream_by_name(storage_key)
        except NoFile as exc:
            raise DocumentStorageNotFoundError(
                "Document file is unavailable"
            ) from exc
        except PyMongoError as exc:
            raise DocumentStorageError("MongoDB document download failed") from exc

    async def iter_chunks(
        self,
        download: AsyncGridOut,
        *,
        chunk_size: int = 64 * 1024,
    ) -> AsyncIterator[bytes]:
        try:
            while chunk := await download.read(chunk_size):
                yield chunk
        except PyMongoError as exc:
            raise DocumentStorageError("MongoDB document stream failed") from exc
        finally:
            await download.close()

    async def delete(self, storage_key: str) -> None:
        try:
            file_record = await self._database[
                f"{self._bucket_name}.files"
            ].find_one(
                {"metadata.storage_key": storage_key},
                projection={"_id": 1},
            )
            if file_record is not None:
                await self._bucket.delete(file_record["_id"])
        except PyMongoError as exc:
            raise DocumentStorageError("MongoDB document delete failed") from exc


class MongoVectorStore:
    def __init__(
        self,
        database: Database[dict[str, Any]],
        *,
        max_candidates: int = 5000,
    ) -> None:
        self._collection = database["document_chunks"]
        self._max_candidates = max_candidates

    async def upsert(
        self,
        *,
        group_id: str,
        document_id: str,
        chunks: Sequence[dict[str, Any]],
        embeddings: Sequence[Sequence[float]],
        filename: str,
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Each document chunk must have one embedding")
        if not chunks:
            return

        dimensions = {len(vector) for vector in embeddings}
        if len(dimensions) != 1 or 0 in dimensions:
            raise ValueError("Document embeddings must have a consistent dimension")

        operations = []
        for chunk, vector in zip(chunks, embeddings, strict=True):
            embedding = [float(value) for value in vector]
            if not all(math.isfinite(value) for value in embedding):
                raise ValueError("Document embeddings must contain finite values")
            chunk_index = chunk["chunk_index"]
            page_number = chunk.get("page_number")
            document = {
                "group_id": group_id,
                "document_id": document_id,
                "chunk_index": chunk_index,
                "text": chunk["text"],
                "embedding": embedding,
                "metadata": {
                    "filename": filename,
                    "page_number": page_number,
                    "embedding_dimensions": len(embedding),
                },
            }
            operations.append(
                ReplaceOne(
                    {
                        "group_id": group_id,
                        "document_id": document_id,
                        "chunk_index": chunk_index,
                    },
                    document,
                    upsert=True,
                )
            )

        if operations:
            await self._collection.bulk_write(operations, ordered=False)
            await self._collection.delete_many(
                {
                    "group_id": group_id,
                    "document_id": document_id,
                    "chunk_index": {"$gte": len(chunks)},
                }
            )

    async def query(
        self,
        *,
        group_id: str,
        query_embedding: Sequence[float],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not query_embedding or not all(
            math.isfinite(float(value)) for value in query_embedding
        ):
            raise ValueError("Query embedding must contain finite values")
        query_vector = [float(value) for value in query_embedding]
        cursor = self._collection.find(
            {"group_id": group_id},
            projection={
                "_id": 0,
                "document_id": 1,
                "group_id": 1,
                "chunk_index": 1,
                "text": 1,
                "embedding": 1,
                "metadata": 1,
            },
        ).limit(self._max_candidates)
        candidates = await cursor.to_list(length=self._max_candidates)
        return await asyncio.to_thread(
            self._rank_candidates,
            candidates,
            query_vector,
            limit,
        )

    @classmethod
    def _rank_candidates(
        cls,
        candidates: Sequence[dict[str, Any]],
        query_vector: Sequence[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        ranked: list[tuple[float, dict[str, Any]]] = []
        for candidate in candidates:
            embedding = candidate.get("embedding")
            if not isinstance(embedding, list) or len(embedding) != len(query_vector):
                continue
            similarity = cls.cosine_similarity(query_vector, embedding)
            if similarity is not None:
                ranked.append((similarity, candidate))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            {**document, "similarity": score}
            for score, document in ranked[: max(1, min(limit, 10))]
        ]

    async def delete(self, *, group_id: str, document_id: str) -> None:
        await self._collection.delete_many(
            {"group_id": group_id, "document_id": document_id}
        )

    @staticmethod
    def cosine_similarity(
        left: Sequence[float],
        right: Sequence[float],
    ) -> float | None:
        if not left or len(left) != len(right):
            return None
        left_values = [float(value) for value in left]
        right_values = [float(value) for value in right]
        left_norm = math.sqrt(math.fsum(value * value for value in left_values))
        right_norm = math.sqrt(math.fsum(value * value for value in right_values))
        if left_norm == 0 or right_norm == 0:
            return None
        dot_product = math.fsum(
            left_value * right_value
            for left_value, right_value in zip(left_values, right_values, strict=True)
        )
        return dot_product / (left_norm * right_norm)
