from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI
from pymongo.errors import DuplicateKeyError

import app.main as main
from app.core.config import Settings
from app.database.mongodb import get_database


class FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.indexes: list[tuple[str, dict]] = []

    async def create_index(self, key: str, **options: object) -> str:
        self.indexes.append((key, options))
        return key

    async def find_one(
        self, query: dict, projection: dict | None = None
    ) -> dict | None:
        for document in self.documents:
            if "$or" in query:
                if any(
                    document.get(key) == value
                    for clause in query["$or"]
                    for key, value in clause.items()
                ):
                    return document.copy()
            elif all(document.get(key) == value for key, value in query.items()):
                return document.copy()
        return None

    async def insert_one(self, document: dict) -> SimpleNamespace:
        if await self.find_one({"email": document["email"]}) or await self.find_one(
            {"username": document["username"]}
        ):
            raise DuplicateKeyError("duplicate key")
        stored = document.copy()
        stored["_id"] = ObjectId()
        self.documents.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def update_one(
        self, query: dict, update: dict, upsert: bool = False
    ) -> None:
        existing = await self.find_one(query)
        if existing is None and upsert:
            self.documents.append({"_id": query["_id"], **update["$setOnInsert"]})


class FakeDatabase:
    def __init__(self) -> None:
        self.collections = {
            "users": FakeCollection(),
            "revoked_tokens": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections[name]


@pytest.fixture
def auth_app(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, FakeDatabase]:
    settings = Settings(
        _env_file=None,
        jwt_secret_key="test-signing-secret-that-is-at-least-32-bytes",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = main.create_app()
    database = FakeDatabase()
    app.dependency_overrides[get_database] = lambda: database
    return app, database


@asynccontextmanager
async def make_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


@pytest.mark.asyncio
async def test_register_creates_profile_without_password_hash(auth_app) -> None:
    app, database = auth_app
    async with make_client(app) as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "Team_Member",
                "full_name": "Team Member",
                "email": "Person@Example.com",
                "password": "a-strong-password",
            },
        )

    assert response.status_code == 201
    assert response.json()["username"] == "team_member"
    assert response.json()["email"] == "person@example.com"
    assert "password" not in response.json()
    assert "password_hash" not in response.json()
    stored = database["users"].documents[0]
    assert stored["password_hash"] != "a-strong-password"
    assert stored["password_hash"].startswith("$2")
    assert [index[0] for index in database["users"].indexes] == [
        "email",
        "username",
        "full_name",
    ]


@pytest.mark.asyncio
async def test_registration_rejects_duplicate_email_and_username(auth_app) -> None:
    app, _ = auth_app
    async with make_client(app) as client:
        first = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "member_one",
                "full_name": "First Member",
                "email": "first@example.com",
                "password": "a-strong-password",
            },
        )
        duplicate_email = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "member_two",
                "full_name": "Second Member",
                "email": "first@example.com",
                "password": "a-strong-password",
            },
        )
        duplicate_username = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "MEMBER_ONE",
                "full_name": "Second Member",
                "email": "second@example.com",
                "password": "a-strong-password",
            },
        )

    assert first.status_code == 201
    assert duplicate_email.status_code == 409
    assert duplicate_username.status_code == 409


@pytest.mark.asyncio
async def test_registration_validates_email(auth_app) -> None:
    app, _ = auth_app
    async with make_client(app) as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "member_one",
                "full_name": "Member",
                "email": "not-an-email",
                "password": "a-strong-password",
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_and_protected_profile_and_logout(auth_app) -> None:
    app, _ = auth_app
    async with make_client(app) as client:
        registration = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "member_one",
                "full_name": "First Member",
                "email": "first@example.com",
                "password": "a-strong-password",
            },
        )
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "FIRST@example.com", "password": "a-strong-password"},
        )
        access_token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        profile = await client.get("/api/v1/auth/me", headers=headers)
        logout = await client.post("/api/v1/auth/logout", headers=headers)
        after_logout = await client.get("/api/v1/auth/me", headers=headers)

    assert registration.status_code == 201
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    assert login.json()["expires_in"] == 3600
    assert login.json()["user"]["id"] == registration.json()["id"]
    assert profile.status_code == 200
    assert profile.json()["email"] == "first@example.com"
    assert logout.status_code == 200
    assert after_logout.status_code == 401


@pytest.mark.asyncio
async def test_login_rejects_invalid_credentials(auth_app) -> None:
    app, _ = auth_app
    async with make_client(app) as client:
        await client.post(
            "/api/v1/auth/register",
            json={
                "username": "member_one",
                "full_name": "First Member",
                "email": "first@example.com",
                "password": "a-strong-password",
            },
        )
        invalid_password = await client.post(
            "/api/v1/auth/login",
            json={"email": "first@example.com", "password": "incorrect-password"},
        )
        missing_user = await client.post(
            "/api/v1/auth/login",
            json={"email": "unknown@example.com", "password": "incorrect-password"},
        )

    assert invalid_password.status_code == 401
    assert missing_user.status_code == 401
    assert invalid_password.json() == missing_user.json()


@pytest.mark.asyncio
async def test_profile_requires_authentication(auth_app) -> None:
    app, _ = auth_app
    async with make_client(app) as client:
        response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
