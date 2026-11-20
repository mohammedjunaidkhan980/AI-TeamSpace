import asyncio
from typing import Any

from app.core.config import Settings
from app.services.chroma import get_chroma_collection


class DocumentRetrievalService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def retrieve(
        self,
        *,
        group_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not self._settings.chroma_enabled:
            return []
        api_key = self._settings.gemini_api_key or self._settings.google_api_key
        if not api_key:
            raise RuntimeError("Embedding provider credentials are not configured")
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        embeddings = GoogleGenerativeAIEmbeddings(
            model=self._settings.gemini_embedding_model,
            google_api_key=api_key,
        )
        query_embedding = await embeddings.aembed_query(query[:8000])
        collection = await asyncio.to_thread(
            get_chroma_collection, self._settings
        )
        result = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_embedding],
            n_results=max(1, min(limit, 10)),
            where={"group_id": group_id},
            include=["documents", "metadatas", "distances"],
        )
        documents = result.get("documents") or [[]]
        metadatas = result.get("metadatas") or [[]]
        excerpts: list[dict[str, Any]] = []
        for text, metadata in zip(documents[0], metadatas[0], strict=False):
            if not isinstance(metadata, dict) or metadata.get("group_id") != group_id:
                continue
            document_id = metadata.get("document_id")
            filename = metadata.get("filename")
            chunk_index = metadata.get("chunk_index")
            if not isinstance(document_id, str) or not isinstance(filename, str):
                continue
            if not isinstance(chunk_index, int) or not isinstance(text, str) or not text:
                continue
            page_number = metadata.get("page_number")
            excerpts.append(
                {
                    "document_id": document_id,
                    "filename": filename[:255],
                    "chunk_index": chunk_index,
                    "page_number": page_number if isinstance(page_number, int) and page_number > 0 else None,
                    "excerpt": text[:1200],
                }
            )
        return excerpts
