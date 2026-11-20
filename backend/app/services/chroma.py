from pathlib import Path
from typing import Any

from app.core.config import Settings


def get_chroma_client(settings: Settings) -> Any:
    if not settings.chroma_enabled:
        raise RuntimeError("ChromaDB is not enabled")
    path = Path(settings.chroma_persist_directory).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    import chromadb

    return chromadb.PersistentClient(path=str(path))


def get_chroma_collection(settings: Settings) -> Any:
    client = get_chroma_client(settings)
    return client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def initialize_chroma(settings: Settings) -> str:
    client = get_chroma_client(settings)
    collection = client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    client.heartbeat()
    return collection.name
