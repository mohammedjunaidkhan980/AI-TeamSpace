import io
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
import zipfile

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI, HTTPException, UploadFile
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from starlette.datastructures import Headers

import app.main as main
from app.api.v1.endpoints.documents import _validate_upload
from app.core.config import Settings
from app.core.security import create_access_token
from app.database.mongodb import get_database
from app.repositories.documents import list_group_documents
from app.repositories.notifications import (
    create_notification,
    mark_notification_read,
)
from app.services.document_processing import DocumentProcessingService
from app.services.document_retrieval import DocumentRetrievalService
from app.services.document_storage import LocalDocumentStorage
from app.services.mongo_storage import (
    DocumentStorageCapacityError,
    DocumentStorageError,
    MongoGridFSDocumentStorage,
    MongoVectorStore,
)
from tests.test_messages import FakeCollection, FakeDatabase, auth, make_client, make_user


def _upload(filename: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers=Headers({"content-type": content_type}),
    )


def _docx_archive(extra_content: bytes = b"") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", b"<document/>")
        if extra_content:
            archive.writestr("word/media/data.bin", extra_content)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_upload_validation_accepts_supported_file_signatures() -> None:
    settings = Settings(_env_file=None, document_max_upload_bytes=1000)
    test_files = [
        ("notes.txt", b"Team notes", "text/plain", ".txt"),
        ("brief.pdf", b"%PDF-1.7 test", "application/pdf", ".pdf"),
        ("brief.docx", _docx_archive(), "application/octet-stream", ".docx"),
    ]

    for filename, content, mime_type, expected_extension in test_files:
        extension, validated_content = await _validate_upload(
            _upload(filename, content, mime_type), settings
        )
        assert extension == expected_extension
        assert validated_content == content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "mime_type", "max_bytes", "status_code"),
    [
        ("../private.txt", b"valid", "text/plain", 100, 422),
        ("notes.exe", b"valid", "application/octet-stream", 100, 415),
        ("empty.txt", b"", "text/plain", 100, 422),
        ("oversized.txt", b"four", "text/plain", 3, 413),
        ("invalid.txt", b"\xff", "text/plain", 100, 422),
        ("invalid.pdf", b"not a pdf", "application/pdf", 100, 422),
        ("invalid.docx", b"not a docx", "application/octet-stream", 100, 422),
    ],
)
async def test_upload_validation_rejects_invalid_files(
    filename: str,
    content: bytes,
    mime_type: str,
    max_bytes: int,
    status_code: int,
) -> None:
    settings = Settings(_env_file=None, document_max_upload_bytes=max_bytes)
    with pytest.raises(HTTPException) as error:
        await _validate_upload(_upload(filename, content, mime_type), settings)
    assert error.value.status_code == status_code


@pytest.mark.asyncio
async def test_upload_validation_rejects_expanding_docx_archive() -> None:
    settings = Settings(
        _env_file=None,
        document_max_upload_bytes=100_000,
        document_max_text_characters=1000,
    )
    compressed_document = _docx_archive(b"x" * 17_000)
    assert len(compressed_document) < 1000

    with pytest.raises(HTTPException) as error:
        await _validate_upload(
            _upload("large.docx", compressed_document, "application/octet-stream"),
            settings,
        )

    assert error.value.status_code == 413


@pytest.mark.asyncio
async def test_document_storage_rejects_path_traversal(tmp_path) -> None:
    storage = LocalDocumentStorage(
        Settings(_env_file=None, document_storage_path=str(tmp_path))
    )
    await storage.put("safe.txt", b"private document")
    assert await storage.read("safe.txt") == b"private document"
    await storage.delete("safe.txt")
    assert not storage.path_for("safe.txt").exists()
    with pytest.raises(ValueError):
        storage.path_for("../outside.txt")


class _FakeGridFSUpload:
    def __init__(self, database, filename: str, metadata: dict) -> None:
        self._database = database
        self._filename = filename
        self._metadata = metadata
        self._data = bytearray()

    async def write(self, data: bytes) -> None:
        self._data.extend(data)

    async def close(self) -> None:
        file_id = ObjectId()
        self._database.gridfs_files[self._filename] = {
            "_id": file_id,
            "filename": self._filename,
            "metadata": self._metadata,
            "data": bytes(self._data),
        }

    async def abort(self) -> None:
        self._database.gridfs_files.pop(self._filename, None)


class _FakeGridFSDownload:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._position = 0
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        end = len(self._data) if size < 0 else self._position + size
        result = self._data[self._position:end]
        self._position += len(result)
        return result

    async def close(self) -> None:
        self.closed = True


class _FakeGridFSBucket:
    def __init__(self, database, *, bucket_name: str) -> None:
        self._database = database
        self._bucket_name = bucket_name

    def open_upload_stream(self, filename: str, *, metadata: dict):
        return _FakeGridFSUpload(self._database, filename, metadata)

    async def open_download_stream_by_name(self, filename: str):
        file = self._database.gridfs_files.get(filename)
        if file is None:
            from gridfs.errors import NoFile

            raise NoFile("file not found")
        return _FakeGridFSDownload(file["data"])

    async def delete(self, file_id: ObjectId) -> None:
        for filename, file in list(self._database.gridfs_files.items()):
            if file["_id"] == file_id:
                del self._database.gridfs_files[filename]
                return


class _FakeGridFSFilesCollection:
    def __init__(self, database) -> None:
        self._database = database
        self.indexes: list[tuple[object, dict]] = []

    async def create_index(self, keys: object, **options: object) -> str:
        self.indexes.append((keys, options))
        return str(keys)

    async def find_one(self, query: dict, projection: dict | None = None):
        key = query["metadata.storage_key"]
        file = self._database.gridfs_files.get(key)
        return {"_id": file["_id"]} if file is not None else None


class _FakeVectorCursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents
        self.maximum = len(documents)

    def limit(self, maximum: int):
        self.maximum = maximum
        return self

    async def to_list(self, length: int) -> list[dict]:
        return self.documents[: min(length, self.maximum)]


class _FakeVectorCollection:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.indexes: list[tuple[object, dict]] = []
        self.last_query: dict | None = None

    async def create_index(self, keys: object, **options: object) -> str:
        self.indexes.append((keys, options))
        return str(keys)

    async def bulk_write(self, operations, *, ordered: bool):
        for operation in operations:
            replacement = operation._doc
            query = operation._filter
            existing = next(
                (
                    index
                    for index, document in enumerate(self.documents)
                    if all(document.get(key) == value for key, value in query.items())
                ),
                None,
            )
            if existing is None:
                self.documents.append(replacement.copy())
            else:
                self.documents[existing] = replacement.copy()
        return SimpleNamespace()

    async def delete_many(self, query: dict):
        before = len(self.documents)
        self.documents = [
            document
            for document in self.documents
            if not (
                document.get("group_id") == query.get("group_id")
                and document.get("document_id") == query.get("document_id")
                and (
                    "chunk_index" not in query
                    or document.get("chunk_index", -1)
                    >= query["chunk_index"]["$gte"]
                )
            )
        ]
        return SimpleNamespace(deleted_count=before - len(self.documents))

    def find(self, query: dict, projection: dict | None = None):
        self.last_query = query
        return _FakeVectorCursor(
            [
                document.copy()
                for document in self.documents
                if all(document.get(key) == value for key, value in query.items())
            ]
        )


class _MongoTestDatabase:
    def __init__(self) -> None:
        self.gridfs_files: dict[str, dict] = {}
        self.collections = {
            "document_chunks": _FakeVectorCollection(),
            "document_files.files": _FakeGridFSFilesCollection(self),
        }

    def __getitem__(self, name: str):
        return self.collections[name]


@pytest.mark.asyncio
async def test_mongo_gridfs_round_trip_delete_and_streaming(monkeypatch) -> None:
    import app.services.mongo_storage as mongo_storage

    monkeypatch.setattr(mongo_storage, "AsyncGridFSBucket", _FakeGridFSBucket)
    database = _MongoTestDatabase()
    storage = MongoGridFSDocumentStorage(database)
    content = b"stream this document in chunks"

    await storage.put("file.txt", content)
    assert await storage.read("file.txt") == content
    download = await storage.open_stream("file.txt")
    streamed = b"".join(
        [chunk async for chunk in storage.iter_chunks(download, chunk_size=5)]
    )
    assert streamed == content
    assert download.closed

    await storage.delete("file.txt")
    assert database.gridfs_files == {}


@pytest.mark.asyncio
async def test_mongo_vector_store_ranks_and_filters_by_group() -> None:
    database = _MongoTestDatabase()
    store = MongoVectorStore(database)
    group_id = str(ObjectId())
    foreign_group_id = str(ObjectId())
    document_id = str(ObjectId())
    chunks = [
        {"chunk_index": 0, "text": "best match", "page_number": 2},
        {"chunk_index": 1, "text": "second match", "page_number": 3},
    ]

    await store.upsert(
        group_id=group_id,
        document_id=document_id,
        chunks=chunks,
        embeddings=[[1.0, 0.0, 0.0], [0.7, 0.7, 0.0]],
        filename="notes.txt",
    )
    await store.upsert(
        group_id=foreign_group_id,
        document_id=str(ObjectId()),
        chunks=[{"chunk_index": 0, "text": "foreign", "page_number": None}],
        embeddings=[[1.0, 0.0, 0.0]],
        filename="foreign.txt",
    )

    matches = await store.query(
        group_id=group_id,
        query_embedding=[1.0, 0.0, 0.0],
        limit=2,
    )

    assert database["document_chunks"].last_query == {"group_id": group_id}
    assert [item["text"] for item in matches] == ["best match", "second match"]
    assert all(item["group_id"] == group_id for item in matches)
    assert len(database["document_chunks"].documents[0]["embedding"]) == 3
    assert database["document_chunks"].documents[0]["metadata"][
        "embedding_dimensions"
    ] == 3


@pytest.mark.asyncio
async def test_mongo_retrieval_uses_gemini_dimension_and_group_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _MongoTestDatabase()
    group_id = str(ObjectId())
    await MongoVectorStore(database).upsert(
        group_id=group_id,
        document_id=str(ObjectId()),
        chunks=[{"chunk_index": 0, "text": "group excerpt", "page_number": 1}],
        embeddings=[[0.0, 1.0, 0.0, 0.0]],
        filename="group.txt",
    )

    class Embeddings:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def aembed_query(self, _query: str) -> list[float]:
            return [0.0, 1.0, 0.0, 0.0]

    monkeypatch.setitem(
        __import__("sys").modules,
        "langchain_google_genai",
        SimpleNamespace(GoogleGenerativeAIEmbeddings=Embeddings),
    )
    settings = Settings(
        _env_file=None,
        use_mongo_storage=True,
        gemini_api_key="test-key",
    )
    results = await DocumentRetrievalService(
        settings,
        cast(Database[dict[str, Any]], database),
    ).retrieve(
        group_id=group_id,
        query="group question",
    )

    assert database["document_chunks"].last_query == {"group_id": group_id}
    assert results == [
        {
            "document_id": database["document_chunks"].documents[0]["document_id"],
            "filename": "group.txt",
            "chunk_index": 0,
            "page_number": 1,
            "excerpt": "group excerpt",
        }
    ]


@pytest.mark.asyncio
async def test_document_processing_stores_returned_embedding_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.mongo_storage as mongo_storage

    monkeypatch.setattr(mongo_storage, "AsyncGridFSBucket", _FakeGridFSBucket)
    database = _MongoTestDatabase()

    class Embeddings:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def aembed_documents(self, _texts: list[str]) -> list[list[float]]:
            return [[0.1, 0.2, 0.3, 0.4]]

    monkeypatch.setitem(
        __import__("sys").modules,
        "langchain_google_genai",
        SimpleNamespace(GoogleGenerativeAIEmbeddings=Embeddings),
    )
    settings = Settings(
        _env_file=None,
        use_mongo_storage=True,
        gemini_api_key="test-key",
    )
    document = {
        "_id": ObjectId(),
        "group_id": ObjectId(),
        "filename": "group.txt",
    }

    await DocumentProcessingService(database, settings)._store_vectors(
        document,
        [{"chunk_index": 0, "text": "test chunk", "page_number": None}],
    )

    stored = database["document_chunks"].documents[0]
    assert len(stored["embedding"]) == 4
    assert stored["metadata"]["embedding_dimensions"] == 4


def test_cosine_similarity_handles_rank_zero_and_mismatched_dimensions() -> None:
    cosine = MongoVectorStore.cosine_similarity
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 0]) is None
    assert cosine([1], [1, 0]) is None


@pytest.mark.asyncio
async def test_document_vector_and_gridfs_deletion_are_group_scoped(
    monkeypatch,
) -> None:
    import app.services.mongo_storage as mongo_storage

    monkeypatch.setattr(mongo_storage, "AsyncGridFSBucket", _FakeGridFSBucket)
    database = _MongoTestDatabase()
    storage = MongoGridFSDocumentStorage(database)
    vector_store = MongoVectorStore(database)
    group_id = str(ObjectId())
    document_id = str(ObjectId())
    await storage.put("file.txt", b"stored")
    await vector_store.upsert(
        group_id=group_id,
        document_id=document_id,
        chunks=[{"chunk_index": 0, "text": "stored chunk", "page_number": None}],
        embeddings=[[0.1, 0.2, 0.3]],
        filename="file.txt",
    )
    await vector_store.upsert(
        group_id=str(ObjectId()),
        document_id=document_id,
        chunks=[{"chunk_index": 0, "text": "other group", "page_number": None}],
        embeddings=[[0.1, 0.2, 0.3]],
        filename="file.txt",
    )

    await vector_store.delete(group_id=group_id, document_id=document_id)
    await storage.delete("file.txt")

    assert len(database["document_chunks"].documents) == 1
    assert database["document_chunks"].documents[0]["text"] == "other group"
    assert database.gridfs_files == {}


@pytest.mark.asyncio
async def test_mongo_upload_limit_uses_the_mongo_specific_cap() -> None:
    settings = Settings(
        _env_file=None,
        use_mongo_storage=True,
        document_max_upload_bytes=100,
        mongo_document_max_upload_bytes=3,
    )
    with pytest.raises(HTTPException) as error:
        await _validate_upload(_upload("notes.txt", b"four", "text/plain"), settings)
    assert error.value.status_code == 413


@pytest.mark.asyncio
async def test_mongo_gridfs_capacity_errors_are_reported_without_raw_details(
    monkeypatch,
) -> None:
    import app.services.mongo_storage as mongo_storage
    from pymongo.errors import OperationFailure

    class FullBucket(_FakeGridFSBucket):
        def open_upload_stream(self, filename: str, *, metadata: dict):
            raise OperationFailure("Free tier storage limit reached")

    monkeypatch.setattr(mongo_storage, "AsyncGridFSBucket", FullBucket)
    with pytest.raises(DocumentStorageCapacityError):
        await MongoGridFSDocumentStorage(_MongoTestDatabase()).put(
            "file.txt",
            b"document",
        )

    class BrokenBucket(_FakeGridFSBucket):
        def open_upload_stream(self, filename: str, *, metadata: dict):
            raise OperationFailure("temporary database failure")

    monkeypatch.setattr(mongo_storage, "AsyncGridFSBucket", BrokenBucket)
    with pytest.raises(DocumentStorageError):
        await MongoGridFSDocumentStorage(_MongoTestDatabase()).put(
            "file.txt",
            b"document",
        )

def test_document_chunking_preserves_configured_overlap() -> None:
    chunks = DocumentProcessingService._chunk_pages(
        [(1, "abcdefghijklmnopqrst")],
        chunk_size=10,
        overlap=2,
    )

    assert [chunk["text"] for chunk in chunks] == [
        "abcdefghij",
        "ijklmnopqr",
        "qrst",
    ]
    assert [chunk["chunk_index"] for chunk in chunks] == [0, 1, 2]
    assert all(chunk["page_number"] == 1 for chunk in chunks)


class _DocumentCursor:
    def __init__(self) -> None:
        self.documents: list[dict] = []

    def sort(self, *_args: object) -> "_DocumentCursor":
        return self

    def limit(self, _limit: int) -> "_DocumentCursor":
        return self

    async def to_list(self, length: int) -> list[dict]:
        return self.documents[:length]


class _DocumentCollection:
    def __init__(self) -> None:
        self.query: dict | None = None

    async def create_index(self, *_args: object, **_kwargs: object) -> str:
        return "index"

    def find(self, query: dict, **_kwargs: object) -> _DocumentCursor:
        self.query = query
        return _DocumentCursor()


@pytest.mark.asyncio
async def test_group_document_search_escapes_regex_input() -> None:
    collection = _DocumentCollection()

    await list_group_documents(
        {"documents": collection},
        group_id=ObjectId(),
        limit=30,
        before=None,
        search="report.*(2026)",
    )

    assert collection.query is not None
    assert collection.query["filename"] == {
        "$regex": r"report\.\*\(2026\)",
        "$options": "i",
    }


@pytest.mark.asyncio
async def test_document_retrieval_filters_group_at_vector_query(monkeypatch) -> None:
    requested_group = str(ObjectId())
    query_calls: list[dict] = []

    class Embeddings:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def aembed_query(self, _query: str) -> list[float]:
            return [0.1, 0.2]

    class Collection:
        def query(self, **kwargs: object) -> dict:
            query_calls.append(kwargs)
            return {
                "documents": [["authorized excerpt", "foreign excerpt"]],
                "metadatas": [[
                    {
                        "group_id": requested_group,
                        "document_id": "doc-a",
                        "filename": "A.txt",
                        "chunk_index": 0,
                    },
                    {
                        "group_id": str(ObjectId()),
                        "document_id": "doc-b",
                        "filename": "B.txt",
                        "chunk_index": 0,
                    },
                ]],
            }

    class Client:
        def list_collections(self) -> list[SimpleNamespace]:
            return [SimpleNamespace(name="documents")]

        def get_collection(self, _name: str) -> Collection:
            return Collection()

        def get_or_create_collection(
            self, *, name: str, metadata: dict
        ) -> Collection:
            assert name == "documents"
            assert metadata == {"hnsw:space": "cosine"}
            return Collection()

    client = Client()
    monkeypatch.setitem(
        __import__("sys").modules,
        "chromadb",
        SimpleNamespace(PersistentClient=lambda **_kwargs: client),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "langchain_google_genai",
        SimpleNamespace(GoogleGenerativeAIEmbeddings=Embeddings),
    )
    settings = Settings(
        _env_file=None,
        chroma_enabled=True,
        gemini_api_key="test-key",
        chroma_collection_name="documents",
    )

    results = await DocumentRetrievalService(settings).retrieve(
        group_id=requested_group,
        query="project detail",
    )

    assert query_calls[0]["where"] == {"group_id": requested_group}
    assert [item["document_id"] for item in results] == ["doc-a"]


class _NotificationCollection:
    def __init__(self) -> None:
        self.documents: list[dict] = []

    async def create_index(self, *_args: object, **_kwargs: object) -> str:
        return "index"

    async def insert_one(self, document: dict) -> SimpleNamespace:
        if any(item["event_key"] == document["event_key"] for item in self.documents):
            raise DuplicateKeyError("duplicate event key")
        stored = {**document, "_id": ObjectId()}
        self.documents.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def find_one(
        self, query: dict, projection: dict | None = None
    ) -> dict | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return document.copy()
        return None

    async def update_one(self, query: dict, update: dict) -> SimpleNamespace:
        document = await self.find_one(query)
        if document is None:
            return SimpleNamespace(matched_count=0)
        stored = next(item for item in self.documents if item["_id"] == document["_id"])
        stored.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=1)


@pytest.mark.asyncio
async def test_notification_creation_is_idempotent_and_read_is_owner_scoped() -> None:
    collection = _NotificationCollection()
    database = {"notifications": collection}
    owner_id = ObjectId()
    other_user_id = ObjectId()
    fields = {
        "recipient_id": owner_id,
        "event_key": "message:abc:user",
        "notification_type": "new_group_message",
        "title": "New message",
        "description": "A message arrived.",
        "related_entity_id": "abc",
        "related_entity_type": "message",
        "group_id": str(ObjectId()),
        "metadata": {},
    }

    first = await create_notification(database, **fields)
    duplicate = await create_notification(database, **fields)

    assert first["_id"] == duplicate["_id"]
    assert len(collection.documents) == 1
    assert await mark_notification_read(
        database, recipient_id=owner_id, notification_id=str(first["_id"])
    )
    assert await mark_notification_read(
        database, recipient_id=owner_id, notification_id=str(first["_id"])
    )
    assert not await mark_notification_read(
        database, recipient_id=other_user_id, notification_id=str(first["_id"])
    )
    assert isinstance(collection.documents[0]["read_at"], datetime)
    assert collection.documents[0]["read_at"].tzinfo == timezone.utc


class _RouteCollection(FakeCollection):
    async def delete_one(self, query: dict) -> SimpleNamespace:
        for document in self.documents:
            if self._matches(document, query):
                self.documents.remove(document)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def update_one(
        self, query: dict, update: dict, upsert: bool = False
    ) -> SimpleNamespace:
        result = await super().update_one(query, update, upsert)
        return SimpleNamespace(
            matched_count=result.modified_count,
            modified_count=result.modified_count,
        )


@pytest.fixture
def api_context(monkeypatch: pytest.MonkeyPatch, tmp_path) -> tuple[FastAPI, FakeDatabase, dict[str, str], dict]:
    settings = Settings(
        _env_file=None,
        jwt_secret_key="test-signing-secret-that-is-at-least-32-bytes",
        document_storage_path=str(tmp_path),
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    users = [make_user("alice"), make_user("bob")]
    group = {
        "_id": ObjectId(),
        "name": "Research",
        "creator_id": users[0]["_id"],
        "members": [{"user_id": users[0]["_id"], "role": "admin"}],
    }
    database = FakeDatabase(users, group)
    database.collections["documents"] = _RouteCollection()
    database.collections["notifications"] = _RouteCollection(
        unique_fields=("event_key",)
    )
    app = main.create_app()
    app.dependency_overrides[get_database] = lambda: database
    tokens = {
        user["username"]: create_access_token(str(user["_id"]), settings)[0]
        for user in users
    }

    async def skip_document_processing(
        _service: DocumentProcessingService, _document_id: str
    ) -> None:
        return None

    monkeypatch.setattr(DocumentProcessingService, "process", skip_document_processing)
    return app, database, tokens, group


@pytest.mark.asyncio
async def test_document_api_upload_download_and_group_isolation(
    api_context,
) -> None:
    app, database, tokens, group = api_context
    async with make_client(app) as client:
        uploaded = await client.post(
            f"/api/v1/groups/{group['_id']}/documents",
            headers=auth(tokens["alice"]),
            files={"file": ("team.txt", b"Private team context", "text/plain")},
        )
        assert uploaded.status_code == 202
        document = uploaded.json()
        assert document["status"] == "pending"
        assert document["group_id"] == str(group["_id"])

        stored = database["documents"].documents[0]
        storage = LocalDocumentStorage(app.state.settings)
        assert storage.path_for(stored["storage_key"]).is_file()

        own_list = await client.get(
            "/api/v1/documents", headers=auth(tokens["alice"])
        )
        foreign_list = await client.get(
            "/api/v1/documents", headers=auth(tokens["bob"])
        )
        assert [item["document_id"] for item in own_list.json()["items"]] == [
            document["document_id"]
        ]
        assert foreign_list.json()["items"] == []

        downloaded = await client.get(
            f"/api/v1/documents/{document['document_id']}/download",
            headers=auth(tokens["alice"]),
        )
        assert downloaded.status_code == 200
        assert downloaded.content == b"Private team context"

        for path, method in (
            (f"/api/v1/groups/{group['_id']}/documents", "get"),
            (f"/api/v1/documents/{document['document_id']}/download", "get"),
            (f"/api/v1/documents/{document['document_id']}", "delete"),
        ):
            response = await getattr(client, method)(
                path, headers=auth(tokens["bob"])
            )
            assert response.status_code == 403

        removed = await client.delete(
            f"/api/v1/documents/{document['document_id']}",
            headers=auth(tokens["alice"]),
        )
        assert removed.status_code == 204
        assert not storage.path_for(stored["storage_key"]).exists()


@pytest.mark.asyncio
async def test_notification_api_lists_reads_and_deletes_only_recipient_items(
    api_context,
) -> None:
    app, database, tokens, _group = api_context
    owner_id = database["users"].documents[0]["_id"]
    notification = await create_notification(
        database,
        recipient_id=owner_id,
        event_key="group:1:message:1",
        notification_type="new_group_message",
        title="New group message",
        description="A message was sent.",
        related_entity_id="message-1",
        related_entity_type="message",
    )

    async with make_client(app) as client:
        listed = await client.get(
            "/api/v1/notifications", headers=auth(tokens["alice"])
        )
        assert listed.status_code == 200
        assert listed.json()["unread_count"] == 1
        assert listed.json()["items"][0]["notification_id"] == str(
            notification["_id"]
        )

        read = await client.put(
            f"/api/v1/notifications/{notification['_id']}/read",
            headers=auth(tokens["alice"]),
        )
        reread = await client.put(
            f"/api/v1/notifications/{notification['_id']}/read",
            headers=auth(tokens["alice"]),
        )
        assert read.status_code == reread.status_code == 204

        foreign = await client.delete(
            f"/api/v1/notifications/{notification['_id']}",
            headers=auth(tokens["bob"]),
        )
        assert foreign.status_code == 404

        read_list = await client.get(
            "/api/v1/notifications", headers=auth(tokens["alice"])
        )
        assert read_list.json()["unread_count"] == 0
        assert read_list.json()["items"][0]["is_read"] is True

        removed = await client.delete(
            f"/api/v1/notifications/{notification['_id']}",
            headers=auth(tokens["alice"]),
        )
        assert removed.status_code == 204


@pytest.mark.asyncio
async def test_mongo_document_api_streams_downloads_and_preserves_retry_flow(
    api_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.mongo_storage as mongo_storage

    app, database, tokens, group = api_context
    settings = main.get_settings()
    settings.use_mongo_storage = True
    settings.chroma_enabled = True
    database.collections["documents"] = _RouteCollection()
    database.collections["document_chunks"] = _FakeVectorCollection()
    database.gridfs_files = {}
    database.collections["document_files.files"] = _FakeGridFSFilesCollection(
        database
    )
    monkeypatch.setattr(mongo_storage, "AsyncGridFSBucket", _FakeGridFSBucket)
    monkeypatch.setattr(
        main,
        "initialize_chroma",
        lambda *_args: pytest.fail("Chroma must not initialize in Mongo storage mode"),
    )

    class MongoClient:
        def get_database(self, _name: str):
            return database

        async def close(self) -> None:
            return None

    monkeypatch.setattr(main, "create_mongo_client", lambda _settings: MongoClient())

    async with make_client(app) as client:
        uploaded = await client.post(
            f"/api/v1/groups/{group['_id']}/documents",
            headers=auth(tokens["alice"]),
            files={"file": ("team.txt", b"Mongo-backed document", "text/plain")},
        )
        assert uploaded.status_code == 202
        document = uploaded.json()

        await MongoVectorStore(database).upsert(
            group_id=str(group["_id"]),
            document_id=document["document_id"],
            chunks=[
                {
                    "chunk_index": 0,
                    "text": "Mongo-backed chunk",
                    "page_number": None,
                }
            ],
            embeddings=[[0.2, 0.4, 0.6]],
            filename=document["filename"],
        )

        database["documents"].documents[0]["status"] = "failed"
        retried = await client.post(
            f"/api/v1/documents/{document['document_id']}/retry",
            headers=auth(tokens["alice"]),
        )
        assert retried.status_code == 200
        assert retried.json()["status"] == "pending"

        downloaded = await client.get(
            f"/api/v1/documents/{document['document_id']}/download",
            headers=auth(tokens["alice"]),
        )
        assert downloaded.status_code == 200
        assert downloaded.content == b"Mongo-backed document"
        assert "filename*=UTF-8''team.txt" in downloaded.headers[
            "content-disposition"
        ]

        removed = await client.delete(
            f"/api/v1/documents/{document['document_id']}",
            headers=auth(tokens["alice"]),
        )
        assert removed.status_code == 204

        from pymongo.errors import OperationFailure

        class FullBucket(_FakeGridFSBucket):
            def open_upload_stream(self, filename: str, *, metadata: dict):
                raise OperationFailure("Free tier storage limit reached")

        monkeypatch.setattr(mongo_storage, "AsyncGridFSBucket", FullBucket)
        full = await client.post(
            f"/api/v1/groups/{group['_id']}/documents",
            headers=auth(tokens["alice"]),
            files={"file": ("full.txt", b"capacity", "text/plain")},
        )
        assert full.status_code == 507
        assert full.json()["detail"] == "Document storage capacity is exhausted"

        class UnavailableBucket(_FakeGridFSBucket):
            def open_upload_stream(self, filename: str, *, metadata: dict):
                raise OperationFailure("temporary database failure")

        monkeypatch.setattr(mongo_storage, "AsyncGridFSBucket", UnavailableBucket)
        unavailable = await client.post(
            f"/api/v1/groups/{group['_id']}/documents",
            headers=auth(tokens["alice"]),
            files={"file": ("retry.txt", b"retry", "text/plain")},
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"] == (
            "Document storage is temporarily unavailable"
        )

    assert database["document_chunks"].documents == []
    assert database.gridfs_files == {}
