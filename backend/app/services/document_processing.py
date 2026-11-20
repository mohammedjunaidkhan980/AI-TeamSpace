import asyncio
import io
import logging
import re
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.core.config import Settings
from app.repositories.documents import get_document, set_document_status
from app.services.chroma import get_chroma_client, get_chroma_collection
from app.services.document_storage import DocumentStorage, create_document_storage
from app.services.mongo_storage import MongoVectorStore
from app.services.notifications import notify_user_best_effort

logger = logging.getLogger(__name__)


class DocumentProcessingError(Exception):
    pass


class DocumentProcessingService:
    def __init__(
        self,
        database: Database[dict[str, Any]],
        settings: Settings,
        storage: DocumentStorage | None = None,
    ) -> None:
        self._database = database
        self._settings = settings
        self._storage = storage or create_document_storage(database, settings)

    async def process(self, document_id: str) -> None:
        if not ObjectId.is_valid(document_id):
            return
        identifier = ObjectId(document_id)
        document = await get_document(self._database, document_id)
        if document is None:
            return
        await set_document_status(
            self._database, document_id=identifier, status="processing"
        )
        try:
            data = await self._storage.read(document["storage_key"])
            pages = await asyncio.to_thread(
                self._extract_pages,
                document["filename"],
                data,
                self._settings.document_max_text_characters,
            )
            chunks = self._chunk_pages(
                pages,
                self._settings.document_chunk_size,
                self._settings.document_chunk_overlap,
            )
            if not chunks:
                raise DocumentProcessingError("No readable text was found in the document")
            await self._store_vectors(document, chunks)
        except Exception as exc:
            logger.exception(
                "Document processing failed",
                extra={"document_id": document_id, "error_type": type(exc).__name__},
            )
            await set_document_status(
                self._database,
                document_id=identifier,
                status="failed",
                processing_error=f"Document processing failed ({type(exc).__name__}).",
            )
            await notify_user_best_effort(
                self._database,
                recipient_id=document["uploader_id"],
                event_key=f"document:{document_id}:processing:failed",
                notification_type="document_processing_failed",
                title="Document processing failed",
                description=f"{document['filename']} could not be processed.",
                related_entity_id=document_id,
                related_entity_type="document",
                group_id=str(document["group_id"]),
            )
            return
        await set_document_status(
            self._database, document_id=identifier, status="completed"
        )
        await notify_user_best_effort(
            self._database,
            recipient_id=document["uploader_id"],
            event_key=f"document:{document_id}:processing:completed",
            notification_type="document_processing_completed",
            title="Document ready",
            description=f"{document['filename']} is ready for AI-assisted search.",
            related_entity_id=document_id,
            related_entity_type="document",
            group_id=str(document["group_id"]),
        )

    async def _store_vectors(
        self,
        document: dict[str, Any],
        chunks: list[dict[str, Any]],
    ) -> None:
        if not self._settings.use_mongo_storage and not self._settings.chroma_enabled:
            raise DocumentProcessingError("Vector search is not enabled")
        api_key = self._settings.gemini_api_key or self._settings.google_api_key
        if not api_key:
            raise DocumentProcessingError("Embedding provider credentials are not configured")
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
        except ImportError as exc:
            raise DocumentProcessingError("Document processing dependencies are unavailable") from exc

        embeddings = GoogleGenerativeAIEmbeddings(
            model=self._settings.gemini_embedding_model,
            google_api_key=api_key,
        )
        vectors = await embeddings.aembed_documents([item["text"] for item in chunks])
        if not vectors or not vectors[0]:
            raise DocumentProcessingError("Embedding provider returned empty vectors")
        if self._settings.use_mongo_storage:
            await MongoVectorStore(
                self._database,
                max_candidates=self._settings.mongo_vector_max_candidates,
            ).upsert(
                group_id=str(document["group_id"]),
                document_id=str(document["_id"]),
                chunks=chunks,
                embeddings=vectors,
                filename=document["filename"],
            )
            logger.info(
                "Document embeddings stored in MongoDB",
                extra={
                    "document_id": str(document["_id"]),
                    "chunk_count": len(vectors),
                    "embedding_dimensions": len(vectors[0]),
                },
            )
            return
        collection = await asyncio.to_thread(
            get_chroma_collection, self._settings
        )
        ids = [f"{document['_id']}:{item['chunk_index']}" for item in chunks]
        metadatas = [
            {
                "group_id": str(document["group_id"]),
                "document_id": str(document["_id"]),
                "filename": document["filename"],
                "chunk_index": item["chunk_index"],
                "page_number": item["page_number"] or 0,
            }
            for item in chunks
        ]
        await asyncio.to_thread(
            collection.upsert,
            ids=ids,
            documents=[item["text"] for item in chunks],
            embeddings=vectors,
            metadatas=metadatas,
        )

    async def delete_vectors(self, *, group_id: str, document_id: str) -> None:
        if self._settings.use_mongo_storage:
            await MongoVectorStore(
                self._database,
                max_candidates=self._settings.mongo_vector_max_candidates,
            ).delete(group_id=group_id, document_id=document_id)
            return
        if not self._settings.chroma_enabled:
            return
        client = await asyncio.to_thread(get_chroma_client, self._settings)
        collections = await asyncio.to_thread(client.list_collections)
        if not any(
            getattr(collection, "name", collection)
            == self._settings.chroma_collection_name
            for collection in collections
        ):
            return
        collection = await asyncio.to_thread(
            client.get_collection, self._settings.chroma_collection_name
        )
        await asyncio.to_thread(
            collection.delete,
            where={
                "$and": [
                    {"group_id": group_id},
                    {"document_id": document_id},
                ]
            },
        )

    @staticmethod
    def _extract_pages(filename: str, data: bytes, max_characters: int) -> list[tuple[int | None, str]]:
        extension = Path(filename).suffix.lower()
        if extension == ".txt":
            text = data.decode("utf-8-sig")
            if "\x00" in text:
                raise DocumentProcessingError("Text file contains binary data")
            return [(None, text[:max_characters])]
        if extension == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages: list[tuple[int | None, str]] = []
            total = 0
            for index, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                total += len(text)
                if total > max_characters:
                    raise DocumentProcessingError("Extracted text exceeds the configured limit")
                pages.append((index + 1, text))
            return pages
        if extension == ".docx":
            from docx import Document

            parsed = Document(io.BytesIO(data))
            text = "\n".join(paragraph.text for paragraph in parsed.paragraphs)
            text = text[:max_characters]
            return [(None, text)]
        raise DocumentProcessingError("Unsupported document format")

    @staticmethod
    def _chunk_pages(
        pages: list[tuple[int | None, str]],
        chunk_size: int,
        overlap: int,
    ) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for page_number, text in pages:
            normalized = re.sub(r"\s+", " ", text).strip()
            start = 0
            while start < len(normalized):
                end = min(start + chunk_size, len(normalized))
                content = normalized[start:end].strip()
                if content:
                    chunks.append(
                        {
                            "chunk_index": len(chunks),
                            "page_number": page_number,
                            "text": content,
                        }
                    )
                if end >= len(normalized):
                    break
                start = end - overlap
        return chunks
