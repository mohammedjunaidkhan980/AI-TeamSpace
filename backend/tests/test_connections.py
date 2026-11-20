import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI
from pymongo.errors import DuplicateKeyError

import app.main as main
from app.core.config import Settings
from app.core.security import create_access_token
from app.database.mongodb import get_database


class FakeCursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents
        self.offset = 0
        self.maximum = len(documents)

    def sort(self, key: str, direction: int) -> "FakeCursor":
        self.documents.sort(key=lambda document: document.get(key))
        if direction < 0:
            self.documents.reverse()
        return self

    def skip(self, offset: int) -> "FakeCursor":
        self.offset = offset
        return self

    def limit(self, maximum: int) -> "FakeCursor":
        self.maximum = maximum
        return self

    async def to_list(self, length: int) -> list[dict]:
        return self.documents[self.offset : self.offset + min(length, self.maximum)]


class FakeCollection:
    def __init__(self, documents: list[dict] | None = None) -> None:
        self.documents = documents if documents is not None else []
        self.indexes: list[tuple[object, dict]] = []

    async def create_index(self, key: object, **options: object) -> str:
        self.indexes.append((key, options))
        return str(key)

    @staticmethod
    def _matches(document: dict, query: dict) -> bool:
        for key, expected in query.items():
            if key == "$or":
                if not any(FakeCollection._matches(document, item) for item in expected):
                    return False
            elif isinstance(expected, dict) and "$in" in expected:
                if document.get(key) not in expected["$in"]:
                    return False
            elif isinstance(expected, dict) and "$ne" in expected:
                if document.get(key) == expected["$ne"]:
                    return False
            elif isinstance(expected, dict) and "$regex" in expected:
                if not re.search(
                    expected["$regex"],
                    document.get(key, ""),
                    re.IGNORECASE,
                ):
                    return False
            elif document.get(key) != expected:
                return False
        return True

    async def find_one(
        self, query: dict, projection: dict | None = None
    ) -> dict | None:
        for document in self.documents:
            if self._matches(document, query):
                return document.copy()
        return None

    def find(self, query: dict, projection: dict | None = None) -> FakeCursor:
        return FakeCursor(
            [
                document.copy()
                for document in self.documents
                if self._matches(document, query)
            ]
        )

    async def insert_one(self, document: dict) -> SimpleNamespace:
        if any(
            stored.get("pair_key") == document["pair_key"]
            for stored in self.documents
        ):
            raise DuplicateKeyError("duplicate pair")
        inserted = document.copy()
        inserted["_id"] = ObjectId()
        self.documents.append(inserted)
        return SimpleNamespace(inserted_id=inserted["_id"])

    async def find_one_and_update(
        self, query: dict, update: dict, return_document: object
    ) -> dict | None:
        for document in self.documents:
            if self._matches(document, query):
                document.update(update["$set"])
                return document.copy()
        return None

    async def delete_one(self, query: dict) -> SimpleNamespace:
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                del self.documents[index]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class FakeDatabase:
    def __init__(self, users: list[dict]) -> None:
        self.collections = {
            "users": FakeCollection(users),
            "connections": FakeCollection(),
            "revoked_tokens": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections[name]


def make_user(username: str, email: str) -> dict:
    return {
        "_id": ObjectId(),
        "username": username,
        "full_name": username.title(),
        "email": email,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "profile_picture_url": None,
        "bio": None,
        "status_message": None,
        "password_hash": "hidden",
    }


@pytest.fixture
def connection_app(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[FastAPI, FakeDatabase, dict[str, str]]:
    settings = Settings(
        _env_file=None,
        jwt_secret_key="test-signing-secret-that-is-at-least-32-bytes",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    users = [
        make_user("alice", "alice@example.com"),
        make_user("bob", "bob@example.com"),
        make_user("carol", "carol@example.com"),
    ]
    database = FakeDatabase(users)
    app = main.create_app()
    app.dependency_overrides[get_database] = lambda: database
    tokens = {}
    for user in users:
        token, _, _ = create_access_token(str(user["_id"]), settings)
        tokens[user["username"]] = token
    return app, database, tokens


@asynccontextmanager
async def make_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_send_friend_request_and_duplicate(connection_app) -> None:
    app, database, tokens = connection_app
    recipient_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        sent = await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": recipient_id},
            headers=auth(tokens["alice"]),
        )
        duplicate = await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": recipient_id},
            headers=auth(tokens["alice"]),
        )

    assert sent.status_code == 201
    assert sent.json()["status"] == "pending"
    assert duplicate.status_code == 409
    assert len(database["connections"].documents) == 1
    assert ("pair_key", {"unique": True}) in database["connections"].indexes


@pytest.mark.asyncio
async def test_prevent_self_and_nonexistent_user_requests(connection_app) -> None:
    app, database, tokens = connection_app
    alice_id = str(database["users"].documents[0]["_id"])
    async with make_client(app) as client:
        self_request = await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": alice_id},
            headers=auth(tokens["alice"]),
        )
        missing_user = await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": str(ObjectId())},
            headers=auth(tokens["alice"]),
        )

    assert self_request.status_code == 400
    assert missing_user.status_code == 404


@pytest.mark.asyncio
async def test_opposite_request_automatically_accepts(connection_app) -> None:
    app, database, tokens = connection_app
    alice_id = str(database["users"].documents[0]["_id"])
    bob_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": bob_id},
            headers=auth(tokens["alice"]),
        )
        reverse = await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": alice_id},
            headers=auth(tokens["bob"]),
        )

    assert reverse.status_code == 200
    assert reverse.json()["status"] == "accepted"
    assert len(database["connections"].documents) == 1


@pytest.mark.asyncio
async def test_incoming_and_outgoing_request_lists(connection_app) -> None:
    app, database, tokens = connection_app
    bob_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": bob_id},
            headers=auth(tokens["alice"]),
        )
        outgoing = await client.get(
            "/api/v1/connections/requests/outgoing",
            headers=auth(tokens["alice"]),
        )
        incoming = await client.get(
            "/api/v1/connections/requests/incoming",
            headers=auth(tokens["bob"]),
        )

    assert outgoing.status_code == incoming.status_code == 200
    assert outgoing.json()["items"][0]["recipient"]["username"] == "bob"
    assert incoming.json()["items"][0]["sender"]["username"] == "alice"
    assert "email" not in incoming.json()["items"][0]["sender"]


@pytest.mark.asyncio
async def test_accept_and_reject_requests_and_enforce_recipient(connection_app) -> None:
    app, database, tokens = connection_app
    bob_id = str(database["users"].documents[1]["_id"])
    carol_id = str(database["users"].documents[2]["_id"])
    async with make_client(app) as client:
        accept_request = await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": bob_id},
            headers=auth(tokens["alice"]),
        )
        request_id = accept_request.json()["id"]
        unauthorized = await client.post(
            f"/api/v1/connections/requests/{request_id}/accept",
            headers=auth(tokens["alice"]),
        )
        accepted = await client.post(
            f"/api/v1/connections/requests/{request_id}/accept",
            headers=auth(tokens["bob"]),
        )
        reject_request = await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": carol_id},
            headers=auth(tokens["alice"]),
        )
        rejected = await client.post(
            f"/api/v1/connections/requests/{reject_request.json()['id']}/reject",
            headers=auth(tokens["carol"]),
        )

    assert unauthorized.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_cancel_request_only_sender(connection_app) -> None:
    app, database, tokens = connection_app
    bob_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        request = await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": bob_id},
            headers=auth(tokens["alice"]),
        )
        request_id = request.json()["id"]
        forbidden = await client.delete(
            f"/api/v1/connections/requests/{request_id}",
            headers=auth(tokens["bob"]),
        )
        cancelled = await client.delete(
            f"/api/v1/connections/requests/{request_id}",
            headers=auth(tokens["alice"]),
        )

    assert forbidden.status_code == 403
    assert cancelled.status_code == 204
    assert database["connections"].documents == []


@pytest.mark.asyncio
async def test_list_and_remove_accepted_connection(connection_app) -> None:
    app, database, tokens = connection_app
    bob_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        sent = await client.post(
            "/api/v1/connections/requests",
            json={"recipient_id": bob_id},
            headers=auth(tokens["alice"]),
        )
        await client.post(
            f"/api/v1/connections/requests/{sent.json()['id']}/accept",
            headers=auth(tokens["bob"]),
        )
        listed = await client.get(
            "/api/v1/connections",
            headers=auth(tokens["alice"]),
        )
        removed = await client.delete(
            f"/api/v1/connections/{bob_id}",
            headers=auth(tokens["alice"]),
        )
        empty = await client.get(
            "/api/v1/connections",
            headers=auth(tokens["bob"]),
        )

    assert listed.status_code == 200
    assert listed.json()["items"][0]["username"] == "bob"
    assert "email" not in listed.json()["items"][0]
    assert removed.status_code == 204
    assert empty.json()["items"] == []


@pytest.mark.asyncio
async def test_missing_requests_connections_and_authentication(connection_app) -> None:
    app, _, tokens = connection_app
    async with make_client(app) as client:
        missing_accept = await client.post(
            f"/api/v1/connections/requests/{ObjectId()}/accept",
            headers=auth(tokens["alice"]),
        )
        invalid_request = await client.post(
            "/api/v1/connections/requests/not-an-id/reject",
            headers=auth(tokens["bob"]),
        )
        missing_connection = await client.delete(
            f"/api/v1/connections/{ObjectId()}",
            headers=auth(tokens["alice"]),
        )
        no_auth = await client.get("/api/v1/connections")

    assert missing_accept.status_code == 404
    assert invalid_request.status_code == 404
    assert missing_connection.status_code == 404
    assert no_auth.status_code == 401
