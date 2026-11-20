import io
from datetime import datetime, timezone
from types import SimpleNamespace
import zipfile

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI, HTTPException, UploadFile
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
