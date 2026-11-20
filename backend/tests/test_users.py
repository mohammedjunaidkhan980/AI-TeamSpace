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
        self.documents.sort(key=lambda document: document.get(key, ""))
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
        self.documents = documents or []
        self.indexes: list[tuple[str, dict]] = []

    async def create_index(self, key: str, **options: object) -> str:
        self.indexes.append((key, options))
        return key

    @staticmethod
    def _matches(document: dict, query: dict) -> bool:
        for key, expected in query.items():
            if key == "$or":
                if not any(FakeCollection._matches(document, item) for item in expected):
                    return False
            elif isinstance(expected, dict) and "$ne" in expected:
                if document.get(key) == expected["$ne"]:
                    return False
            elif isinstance(expected, dict) and "$regex" in expected:
                value = document.get(key, "")
                if not re.search(expected["$regex"], value, re.IGNORECASE):
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

    async def find_one_and_update(
        self, query: dict, update: dict, return_document: bool
    ) -> dict | None:
        for document in self.documents:
            if not self._matches(document, query):
                continue
            for key, value in update["$set"].items():
                if key == "username" and any(
                    other is not document and other["username"] == value
                    for other in self.documents
                ):
                    raise DuplicateKeyError("duplicate username")
            document.update(update["$set"])
            return document.copy()
        return None


class FakeDatabase:
    def __init__(self, users: list[dict]) -> None:
        self.collections = {
            "users": FakeCollection(users),
            "revoked_tokens": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections[name]


def make_user(
    *,
    username: str,
    full_name: str,
    email: str,
    user_id: ObjectId | None = None,
    **extra: object,
) -> dict:
    return {
        "_id": user_id or ObjectId(),
        "username": username,
        "full_name": full_name,
        "email": email,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "password_hash": "never-return-this",
        "auth": {"secret": "never-return-this-either"},
        **extra,
    }


@pytest.fixture
def users_app(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, FakeDatabase, str]:
    settings = Settings(
        _env_file=None,
        jwt_secret_key="test-signing-secret-that-is-at-least-32-bytes",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    current_user = make_user(
        username="self_user",
        full_name="Current User",
        email="current@example.com",
        bio="Existing bio",
    )
    database = FakeDatabase(
        [
            current_user,
            make_user(
                username="alice",
                full_name="Alice Smith",
                email="alice@example.com",
                profile_picture_url="https://example.com/alice.png",
                bio="A user",
                status_message="Available",
            ),
            make_user(
                username="bob",
                full_name="Robert Jones",
                email="bob@example.com",
            ),
        ]
    )
    app = main.create_app()
    app.dependency_overrides[get_database] = lambda: database
    token, _, _ = create_access_token(str(current_user["_id"]), settings)
    return app, database, token


@asynccontextmanager
async def make_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


@pytest.mark.asyncio
async def test_get_current_profile(users_app) -> None:
    app, _, token = users_app
    async with make_client(app) as client:
        response = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["username"] == "self_user"
    assert response.json()["email"] == "current@example.com"
    assert response.json()["bio"] == "Existing bio"
    assert "password_hash" not in response.json()


@pytest.mark.asyncio
async def test_update_current_profile(users_app) -> None:
    app, database, token = users_app
    async with make_client(app) as client:
        response = await client.put(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "username": "New_Name",
                "full_name": "Updated Name",
                "profile_picture_url": "https://example.com/profile.png",
                "bio": "Updated bio",
                "status_message": "At work",
            },
        )

    assert response.status_code == 200
    assert response.json()["username"] == "new_name"
    assert response.json()["full_name"] == "Updated Name"
    assert response.json()["email"] == "current@example.com"
    assert response.json()["profile_picture_url"] == "https://example.com/profile.png"
    assert "password" not in response.json()
    assert database["users"].documents[0]["bio"] == "Updated bio"
    assert ("full_name", {}) in database["users"].indexes


@pytest.mark.asyncio
async def test_update_rejects_duplicate_username(users_app) -> None:
    app, _, token = users_app
    async with make_client(app) as client:
        response = await client.put(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"username": "alice"},
        )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_update_rejects_email_changes(users_app) -> None:
    app, _, token = users_app
    async with make_client(app) as client:
        response = await client.put(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "new@example.com"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_username"),
    [
        ("ali", "alice"),
        ("smith", "alice"),
        ("@EXAMPLE", "alice"),
        ("robert", "bob"),
    ],
)
async def test_search_users_by_username_name_or_email(
    users_app, query: str, expected_username: str
) -> None:
    app, _, token = users_app
    async with make_client(app) as client:
        response = await client.get(
            "/api/v1/users/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    results = response.json()["items"]
    assert expected_username in [item["username"] for item in results]
    assert all(item["username"] != "self_user" for item in results)
    assert all("email" not in item and "password_hash" not in item for item in results)


@pytest.mark.asyncio
async def test_search_requires_nonblank_query_and_caps_results(users_app) -> None:
    app, _, token = users_app
    async with make_client(app) as client:
        blank = await client.get(
            "/api/v1/users/search",
            params={"q": "   "},
            headers={"Authorization": f"Bearer {token}"},
        )
        too_many = await client.get(
            "/api/v1/users/search",
            params={"q": "a", "limit": 21},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert blank.status_code == 422
    assert too_many.status_code == 422


@pytest.mark.asyncio
async def test_search_excludes_current_user_even_when_matched(users_app) -> None:
    app, _, token = users_app
    async with make_client(app) as client:
        response = await client.get(
            "/api/v1/users/search",
            params={"q": "current@example.com"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_public_profile_excludes_email_and_sensitive_fields(users_app) -> None:
    app, database, token = users_app
    user_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        response = await client.get(
            f"/api/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["username"] == "alice"
    assert "email" not in response.json()
    assert "password_hash" not in response.json()
    assert "auth" not in response.json()


@pytest.mark.asyncio
async def test_users_routes_require_authentication(users_app) -> None:
    app, _, _ = users_app
    async with make_client(app) as client:
        current_profile = await client.get("/api/v1/users/me")
        update_profile = await client.put(
            "/api/v1/users/me",
            json={"full_name": "Unauthorized"},
        )
        search = await client.get("/api/v1/users/search", params={"q": "alice"})
        profile = await client.get(f"/api/v1/users/{ObjectId()}")

    assert current_profile.status_code == 401
    assert update_profile.status_code == 401
    assert search.status_code == 401
    assert profile.status_code == 401


@pytest.mark.asyncio
async def test_user_not_found_and_invalid_id(users_app) -> None:
    app, _, token = users_app
    headers = {"Authorization": f"Bearer {token}"}
    async with make_client(app) as client:
        invalid = await client.get("/api/v1/users/not-an-object-id", headers=headers)
        missing = await client.get(
            f"/api/v1/users/{ObjectId()}",
            headers=headers,
        )

    assert invalid.status_code == 404
    assert missing.status_code == 404
