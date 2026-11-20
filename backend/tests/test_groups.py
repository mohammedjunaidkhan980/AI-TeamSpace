import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI

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

    @classmethod
    def _matches(cls, document: dict, query: dict) -> bool:
        for key, expected in query.items():
            if key == "$and":
                if not all(cls._matches(document, item) for item in expected):
                    return False
                continue
            if key == "$or":
                if not any(cls._matches(document, item) for item in expected):
                    return False
                continue

            if key.startswith("members."):
                field = key.split(".", 1)[1]
                if not any(
                    cls._value_matches(member.get(field), expected)
                    for member in document.get("members", [])
                ):
                    return False
            elif key == "members" and isinstance(expected, dict) and "$elemMatch" in expected:
                if not any(
                    cls._matches(member, expected["$elemMatch"])
                    for member in document.get("members", [])
                ):
                    return False
            elif not cls._value_matches(document.get(key), expected):
                return False
        return True

    @classmethod
    def _value_matches(cls, actual: object, expected: object) -> bool:
        if isinstance(expected, dict):
            if "$ne" in expected:
                return actual != expected["$ne"]
            if "$in" in expected:
                return actual in expected["$in"]
            if "$elemMatch" in expected:
                return isinstance(actual, list) and any(
                    cls._matches(item, expected["$elemMatch"]) for item in actual
                )
            if "$regex" in expected:
                return bool(
                    re.search(str(expected["$regex"]), str(actual or ""), re.I)
                )
        return actual == expected

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
        inserted = document.copy()
        inserted["_id"] = ObjectId()
        self.documents.append(inserted)
        return SimpleNamespace(inserted_id=inserted["_id"])

    async def find_one_and_update(
        self,
        query: dict,
        update: dict,
        return_document: object,
    ) -> dict | None:
        for document in self.documents:
            if self._matches(document, query):
                document.update(update.get("$set", {}))
                return document.copy()
        return None

    async def update_one(
        self,
        query: dict,
        update: dict,
        array_filters: list[dict] | None = None,
    ) -> SimpleNamespace:
        for document in self.documents:
            if not self._matches(document, query):
                continue
            for key, value in update.get("$set", {}).items():
                if key.startswith("members.$["):
                    filter_spec = array_filters[0]
                    target_id = filter_spec["target.user_id"]
                    for member in document.get("members", []):
                        if member["user_id"] == target_id:
                            member[key.rsplit(".", 1)[1]] = value
                else:
                    document[key] = value
            for key, value in update.get("$push", {}).items():
                document.setdefault(key, []).append(value)
            for key, condition in update.get("$pull", {}).items():
                document[key] = [
                    item
                    for item in document.get(key, [])
                    if not self._matches(item, condition)
                ]
            return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)


class FakeDatabase:
    def __init__(self, users: list[dict], connections: list[dict]) -> None:
        self.collections = {
            "users": FakeCollection(users),
            "connections": FakeCollection(connections),
            "groups": FakeCollection(),
            "revoked_tokens": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections[name]


def make_user(username: str) -> dict:
    return {
        "_id": ObjectId(),
        "username": username,
        "full_name": username.title(),
        "email": f"{username}@example.com",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "profile_picture_url": None,
        "bio": None,
        "status_message": None,
        "password_hash": "hidden",
    }


def connection(first: ObjectId, second: ObjectId) -> dict:
    pair = ":".join(sorted((str(first), str(second))))
    return {"pair_key": pair, "status": "accepted"}


@pytest.fixture
def group_app(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, FakeDatabase, dict[str, str]]:
    settings = Settings(
        _env_file=None,
        jwt_secret_key="test-signing-secret-that-is-at-least-32-bytes",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    users = [make_user("alice"), make_user("bob"), make_user("carol"), make_user("dave")]
    links = [
        connection(users[0]["_id"], users[1]["_id"]),
        connection(users[0]["_id"], users[2]["_id"]),
        connection(users[1]["_id"], users[2]["_id"]),
    ]
    database = FakeDatabase(users, links)
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


async def create_test_group(client: httpx.AsyncClient, bob_id: str, token: str) -> dict:
    response = await client.post(
        "/api/v1/groups",
        json={"name": "Hackathon Team", "description": "Build together", "member_ids": [bob_id]},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_create_group_creator_is_admin_and_adds_connected_users(group_app) -> None:
    app, database, tokens = group_app
    alice_id = str(database["users"].documents[0]["_id"])
    bob_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        response = await client.post(
            "/api/v1/groups",
            json={
                "name": "Team Space",
                "description": "Project group",
                "member_ids": [bob_id],
            },
            headers=auth(tokens["alice"]),
        )

    assert response.status_code == 201
    result = response.json()
    assert result["creator_id"] == alice_id
    assert result["member_count"] == 2
    assert result["ai_agents"] == []
    assert [member["role"] for member in result["members"]] == ["admin", "member"]
    group = database["groups"].documents[0]
    assert group["settings"] == {}
    assert [key for key, _ in database["groups"].indexes] == [
        "creator_id",
        "members.user_id",
        "created_at",
        "nexconn_channel_id",
    ]
    assert database["groups"].indexes[-1][1] == {
        "unique": True,
        "partialFilterExpression": {
            "nexconn_channel_id": {"$type": "string"},
        },
    }


@pytest.mark.asyncio
async def test_create_group_rejects_unconnected_user(group_app) -> None:
    app, database, tokens = group_app
    dave_id = str(database["users"].documents[3]["_id"])
    async with make_client(app) as client:
        response = await client.post(
            "/api/v1/groups",
            json={"name": "No access", "member_ids": [dave_id]},
            headers=auth(tokens["alice"]),
        )

    assert response.status_code == 403
    assert database["groups"].documents == []


@pytest.mark.asyncio
async def test_list_groups_details_and_nonmember_access(group_app) -> None:
    app, database, tokens = group_app
    bob_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        created = await create_test_group(client, bob_id, tokens["alice"])
        group_id = created["group_id"]
        listed = await client.get("/api/v1/groups", headers=auth(tokens["bob"]))
        details = await client.get(
            f"/api/v1/groups/{group_id}",
            headers=auth(tokens["bob"]),
        )
        forbidden = await client.get(
            f"/api/v1/groups/{group_id}",
            headers=auth(tokens["dave"]),
        )

    assert listed.status_code == 200
    assert listed.json()["items"][0]["current_user_role"] == "member"
    assert listed.json()["items"][0]["member_count"] == 2
    assert details.status_code == 200
    assert details.json()["members"][0]["user"]["username"] == "alice"
    assert "email" not in details.json()["members"][0]["user"]
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_update_group_only_admin(group_app) -> None:
    app, database, tokens = group_app
    bob_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        group = await create_test_group(client, bob_id, tokens["alice"])
        group_id = group["group_id"]
        forbidden = await client.put(
            f"/api/v1/groups/{group_id}",
            json={"name": "Unauthorized"},
            headers=auth(tokens["bob"]),
        )
        updated = await client.put(
            f"/api/v1/groups/{group_id}",
            json={
                "name": "Updated Team",
                "description": "New description",
                "group_picture_url": "https://example.com/group.png",
            },
            headers=auth(tokens["alice"]),
        )

    assert forbidden.status_code == 403
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated Team"
    assert updated.json()["description"] == "New description"


@pytest.mark.asyncio
async def test_add_members_requires_connected_admin_and_prevents_duplicates(group_app) -> None:
    app, database, tokens = group_app
    bob_id = str(database["users"].documents[1]["_id"])
    carol_id = str(database["users"].documents[2]["_id"])
    dave_id = str(database["users"].documents[3]["_id"])
    async with make_client(app) as client:
        group = await create_test_group(client, bob_id, tokens["alice"])
        path = f"/api/v1/groups/{group['group_id']}/members"
        added = await client.post(
            path,
            json={"user_ids": [carol_id]},
            headers=auth(tokens["alice"]),
        )
        duplicate = await client.post(
            path,
            json={"user_ids": [carol_id]},
            headers=auth(tokens["alice"]),
        )
        unconnected = await client.post(
            path,
            json={"user_ids": [dave_id]},
            headers=auth(tokens["alice"]),
        )
        non_admin = await client.post(
            path,
            json={"user_ids": [carol_id]},
            headers=auth(tokens["bob"]),
        )

    assert added.status_code == 201
    assert added.json()["members"][0]["user"]["username"] == "carol"
    assert duplicate.json()["members"] == []
    assert unconnected.status_code == 403
    assert non_admin.status_code == 403
    assert len(database["groups"].documents[0]["members"]) == 3


@pytest.mark.asyncio
async def test_remove_member_leave_and_creator_protection(group_app) -> None:
    app, database, tokens = group_app
    bob_id = str(database["users"].documents[1]["_id"])
    alice_id = str(database["users"].documents[0]["_id"])
    async with make_client(app) as client:
        group = await create_test_group(client, bob_id, tokens["alice"])
        group_id = group["group_id"]
        creator_remove = await client.delete(
            f"/api/v1/groups/{group_id}/members/{alice_id}",
            headers=auth(tokens["alice"]),
        )
        leave = await client.delete(
            f"/api/v1/groups/{group_id}/members/{bob_id}",
            headers=auth(tokens["bob"]),
        )
        details = await client.get(
            f"/api/v1/groups/{group_id}",
            headers=auth(tokens["alice"]),
        )

    assert creator_remove.status_code == 409
    assert leave.status_code == 204
    assert details.json()["member_count"] == 1


@pytest.mark.asyncio
async def test_admin_can_remove_another_member(group_app) -> None:
    app, database, tokens = group_app
    bob_id = str(database["users"].documents[1]["_id"])
    carol_id = str(database["users"].documents[2]["_id"])
    async with make_client(app) as client:
        group = await create_test_group(client, bob_id, tokens["alice"])
        group_id = group["group_id"]
        added = await client.post(
            f"/api/v1/groups/{group_id}/members",
            json={"user_ids": [carol_id]},
            headers=auth(tokens["alice"]),
        )
        removed = await client.delete(
            f"/api/v1/groups/{group_id}/members/{carol_id}",
            headers=auth(tokens["alice"]),
        )
        details = await client.get(
            f"/api/v1/groups/{group_id}",
            headers=auth(tokens["alice"]),
        )

    assert added.status_code == 201
    assert removed.status_code == 204
    assert details.json()["member_count"] == 2
    assert "carol" not in [
        member["user"]["username"] for member in details.json()["members"]
    ]


@pytest.mark.asyncio
async def test_admin_promotion_demotion_and_creator_protection(group_app) -> None:
    app, database, tokens = group_app
    bob_id = str(database["users"].documents[1]["_id"])
    alice_id = str(database["users"].documents[0]["_id"])
    async with make_client(app) as client:
        group = await create_test_group(client, bob_id, tokens["alice"])
        group_id = group["group_id"]
        promoted = await client.post(
            f"/api/v1/groups/{group_id}/admins/{bob_id}",
            headers=auth(tokens["alice"]),
        )
        demoted = await client.delete(
            f"/api/v1/groups/{group_id}/admins/{bob_id}",
            headers=auth(tokens["alice"]),
        )
        creator_demote = await client.delete(
            f"/api/v1/groups/{group_id}/admins/{alice_id}",
            headers=auth(tokens["alice"]),
        )
        non_admin_promote = await client.post(
            f"/api/v1/groups/{group_id}/admins/{alice_id}",
            headers=auth(tokens["bob"]),
        )
        details = await client.get(
            f"/api/v1/groups/{group_id}",
            headers=auth(tokens["alice"]),
        )

    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"
    assert demoted.status_code == 204
    assert creator_demote.status_code == 409
    assert non_admin_promote.status_code == 403
    assert [member["role"] for member in details.json()["members"]] == [
        "admin",
        "member",
    ]


@pytest.mark.asyncio
async def test_group_routes_auth_and_invalid_ids(group_app) -> None:
    app, _, tokens = group_app
    async with make_client(app) as client:
        no_auth = await client.get("/api/v1/groups")
        missing = await client.get(
            "/api/v1/groups/not-an-object-id",
            headers=auth(tokens["alice"]),
        )
        invalid_member_id = await client.post(
            "/api/v1/groups",
            json={"name": "Invalid", "member_ids": ["bad-id"]},
            headers=auth(tokens["alice"]),
        )

    assert no_auth.status_code == 401
    assert missing.status_code == 404
    assert invalid_member_id.status_code == 422
