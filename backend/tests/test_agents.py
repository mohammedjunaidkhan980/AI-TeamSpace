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

    def sort(self, key: str, direction: int) -> "FakeCursor":
        self.documents.sort(key=lambda item: item.get(key), reverse=direction < 0)
        return self

    async def to_list(self, length: int) -> list[dict]:
        return self.documents[:length]


class FakeCollection:
    def __init__(self, documents: list[dict] | None = None) -> None:
        self.documents = documents if documents is not None else []
        self.indexes: list[tuple[object, dict]] = []

    async def create_index(self, keys: object, **options: object) -> str:
        self.indexes.append((keys, options))
        return str(keys)

    @classmethod
    def _value(cls, document: dict, key: str) -> object:
        value: object = document
        for part in key.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value

    @classmethod
    def _matches(cls, document: dict, query: dict) -> bool:
        for key, expected in query.items():
            if key.startswith("members."):
                field = key.split(".", 1)[1]
                if not any(
                    cls._matches(member, {field: expected})
                    for member in document.get("members", [])
                ):
                    return False
                continue
            actual = cls._value(document, key)
            if isinstance(expected, dict):
                if "$exists" in expected and (key in document) != expected["$exists"]:
                    return False
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
                if "$elemMatch" in expected and not any(
                    cls._matches(item, expected["$elemMatch"])
                    for item in (actual if isinstance(actual, list) else [])
                ):
                    return False
            elif actual != expected:
                return False
        return True

    async def find_one(self, query: dict, projection: dict | None = None) -> dict | None:
        for document in self.documents:
            if self._matches(document, query):
                return document.copy()
        return None

    def find(self, query: dict) -> FakeCursor:
        return FakeCursor(
            [item.copy() for item in self.documents if self._matches(item, query)]
        )

    async def insert_one(self, document: dict) -> SimpleNamespace:
        if "group_id" in document and any(
            item.get("group_id") == document["group_id"]
            and item.get("template_id") == document["template_id"]
            and "deleted_at" not in item
            for item in self.documents
        ):
            raise DuplicateKeyError("duplicate active template")
        inserted = document.copy()
        inserted["_id"] = ObjectId()
        self.documents.append(inserted)
        return SimpleNamespace(inserted_id=inserted["_id"])

    async def find_one_and_update(
        self, query: dict, update: dict, return_document: object
    ) -> dict | None:
        for document in self.documents:
            if self._matches(document, query):
                document.update(update.get("$set", {}))
                return document.copy()
        return None

    async def update_one(self, query: dict, update: dict) -> SimpleNamespace:
        for document in self.documents:
            if not self._matches(document, query):
                continue
            for key, value in update.get("$set", {}).items():
                document[key] = value
            for key, value in update.get("$addToSet", {}).items():
                target = document.setdefault(key, [])
                if value not in target:
                    target.append(value)
            for key, condition in update.get("$pull", {}).items():
                document[key] = [
                    item
                    for item in document.get(key, [])
                    if not self._matches(item, condition)
                ]
            return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)


class FakeDatabase:
    def __init__(self, users: list[dict], group: dict) -> None:
        self.collections = {
            "users": FakeCollection(users),
            "groups": FakeCollection([group]),
            "agents": FakeCollection(),
            "revoked_tokens": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections[name]


def _user(name: str) -> dict:
    return {
        "_id": ObjectId(),
        "username": name,
        "full_name": name.title(),
        "email": f"{name}@example.com",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "password_hash": "not-returned",
    }


@pytest.fixture
def agent_app(monkeypatch: pytest.MonkeyPatch):
    settings = Settings(
        _env_file=None,
        jwt_secret_key="test-signing-secret-that-is-at-least-32-bytes",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    users = [_user("admin"), _user("member"), _user("outsider")]
    group = {
        "_id": ObjectId(),
        "creator_id": users[0]["_id"],
        "members": [
            {"user_id": users[0]["_id"], "role": "admin"},
            {"user_id": users[1]["_id"], "role": "member"},
        ],
        "ai_agents": [],
    }
    database = FakeDatabase(users, group)
    app = main.create_app()
    app.dependency_overrides[get_database] = lambda: database
    tokens = {
        user["username"]: create_access_token(str(user["_id"]), settings)[0]
        for user in users
    }
    return app, database, tokens


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_templates_are_authenticated_and_include_all_templates(agent_app) -> None:
    app, _, tokens = agent_app
    async with _client(app) as client:
        response = await client.get(
            "/api/v1/agents/templates", headers=_auth(tokens["member"])
        )
        unauthorized = await client.get("/api/v1/agents/templates")

    assert response.status_code == 200
    assert {item["template_id"] for item in response.json()} == {
        "research",
        "coding",
        "data_analyst",
        "writing",
        "project_manager",
        "coordinator",
    }
    assert all(item["model"] == "gemini-3.8-flash" for item in response.json())
    assert unauthorized.status_code == 401


@pytest.mark.asyncio
async def test_group_agent_create_list_update_status_and_soft_delete(agent_app) -> None:
    app, database, tokens = agent_app
    group_id = str(database["groups"].documents[0]["_id"])
    async with _client(app) as client:
        created = await client.post(
            f"/api/v1/groups/{group_id}/agents",
            json={
                "template_id": "research",
                "name": "Market Research",
                "custom_system_prompt": "Research the supplied market carefully.",
                "temperature": 0.4,
                "configuration": {"max_tokens": 1024, "top_p": 0.9},
            },
            headers=_auth(tokens["admin"]),
        )
        listed = await client.get(
            f"/api/v1/groups/{group_id}/agents",
            headers=_auth(tokens["member"]),
        )
        details = await client.get(
            f"/api/v1/groups/{group_id}/agents/{created.json()['agent_id']}",
            headers=_auth(tokens["member"]),
        )
        agent_id = created.json()["agent_id"]
        updated = await client.put(
            f"/api/v1/groups/{group_id}/agents/{agent_id}",
            json={"model": "gemini-2.0-pro"},
            headers=_auth(tokens["admin"]),
        )
        disabled = await client.patch(
            f"/api/v1/groups/{group_id}/agents/{agent_id}/status",
            json={"enabled": False},
            headers=_auth(tokens["admin"]),
        )
        removed = await client.delete(
            f"/api/v1/groups/{group_id}/agents/{agent_id}",
            headers=_auth(tokens["admin"]),
        )
        recreated = await client.post(
            f"/api/v1/groups/{group_id}/agents",
            json={"template_id": "research"},
            headers=_auth(tokens["admin"]),
        )
        after_delete = await client.get(
            f"/api/v1/groups/{group_id}/agents/{agent_id}",
            headers=_auth(tokens["admin"]),
        )

    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Market Research"
    assert body["system_prompt"] == "Research the supplied market carefully."
    assert body["configuration"] == {"max_tokens": 1024, "top_p": 0.9}
    assert "password_hash" not in body and "api_key" not in body
    assert listed.status_code == 200 and len(listed.json()["items"]) == 1
    assert details.status_code == 200
    assert updated.status_code == 200 and updated.json()["model"] == "gemini-2.0-pro"
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    assert removed.status_code == 204
    assert recreated.status_code == 201
    assert after_delete.status_code == 404
    assert database["groups"].documents[0]["ai_agents"] == [
        {"agent_id": recreated.json()["agent_id"], "enabled": True}
    ]
    assert "deleted_at" in database["agents"].documents[0]


@pytest.mark.asyncio
async def test_group_agent_permissions_and_identifier_validation(agent_app) -> None:
    app, database, tokens = agent_app
    group_id = str(database["groups"].documents[0]["_id"])
    async with _client(app) as client:
        non_admin_create = await client.post(
            f"/api/v1/groups/{group_id}/agents",
            json={"template_id": "coding"},
            headers=_auth(tokens["member"]),
        )
        outsider_list = await client.get(
            f"/api/v1/groups/{group_id}/agents",
            headers=_auth(tokens["outsider"]),
        )
        invalid_group = await client.get(
            "/api/v1/groups/not-an-object-id/agents",
            headers=_auth(tokens["admin"]),
        )
        invalid_agent = await client.get(
            f"/api/v1/groups/{group_id}/agents/not-an-object-id",
            headers=_auth(tokens["admin"]),
        )
        invalid_temperature = await client.post(
            f"/api/v1/groups/{group_id}/agents",
            json={"template_id": "coding", "temperature": 1.1},
            headers=_auth(tokens["admin"]),
        )
        unsupported_config = await client.post(
            f"/api/v1/groups/{group_id}/agents",
            json={"template_id": "coding", "configuration": {"api_key": "secret"}},
            headers=_auth(tokens["admin"]),
        )

    assert non_admin_create.status_code == 403
    assert outsider_list.status_code == 403
    assert invalid_group.status_code == 404
    assert invalid_agent.status_code == 404
    assert invalid_temperature.status_code == 422
    assert unsupported_config.status_code == 422


@pytest.mark.asyncio
async def test_one_active_agent_per_template_per_group(agent_app) -> None:
    app, database, tokens = agent_app
    group_id = str(database["groups"].documents[0]["_id"])
    async with _client(app) as client:
        first = await client.post(
            f"/api/v1/groups/{group_id}/agents",
            json={"template_id": "coding"},
            headers=_auth(tokens["admin"]),
        )
        second = await client.post(
            f"/api/v1/groups/{group_id}/agents",
            json={"template_id": "coding"},
            headers=_auth(tokens["admin"]),
        )

    assert first.status_code == 201
    assert second.status_code == 409
    assert len(database["agents"].documents) == 1


@pytest.mark.asyncio
async def test_templates_are_independent_across_groups_and_types(agent_app) -> None:
    app, database, tokens = agent_app
    first_group = database["groups"].documents[0]
    second_group = {
        "_id": ObjectId(),
        "creator_id": first_group["creator_id"],
        "members": first_group["members"].copy(),
        "ai_agents": [],
    }
    database["groups"].documents.append(second_group)
    async with _client(app) as client:
        first_coding = await client.post(
            f"/api/v1/groups/{first_group['_id']}/agents",
            json={"template_id": "coding"},
            headers=_auth(tokens["admin"]),
        )
        first_writing = await client.post(
            f"/api/v1/groups/{first_group['_id']}/agents",
            json={"template_id": "writing"},
            headers=_auth(tokens["admin"]),
        )
        second_coding = await client.post(
            f"/api/v1/groups/{second_group['_id']}/agents",
            json={"template_id": "coding"},
            headers=_auth(tokens["admin"]),
        )

    assert first_coding.status_code == 201
    assert first_writing.status_code == 201
    assert second_coding.status_code == 201
    assert len(database["agents"].documents) == 3
