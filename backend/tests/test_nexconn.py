import hashlib
import json
import re
import time
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
from app.services.nexconn import NexconnAPIError, NexconnClient


class FakeCursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents

    def sort(self, key: str, direction: int) -> "FakeCursor":
        self.documents.sort(key=lambda document: document.get(key))
        if direction < 0:
            self.documents.reverse()
        return self

    def skip(self, offset: int) -> "FakeCursor":
        self.documents = self.documents[offset:]
        return self

    def limit(self, maximum: int) -> "FakeCursor":
        self.documents = self.documents[:maximum]
        return self

    async def to_list(self, length: int) -> list[dict]:
        return self.documents[:length]


class FakeCollection:
    def __init__(self, documents: list[dict] | None = None) -> None:
        self.documents = documents or []
        self.indexes: list[tuple[object, dict]] = []

    async def create_index(self, key: object, **options: object) -> str:
        self.indexes.append((key, options))
        return str(key)

    @classmethod
    def _matches(cls, document: dict, query: dict) -> bool:
        for key, expected in query.items():
            if key == "$or":
                if not any(cls._matches(document, item) for item in expected):
                    return False
                continue
            if key == "$and":
                if not all(cls._matches(document, item) for item in expected):
                    return False
                continue
            if key == "members.user_id":
                if not any(
                    cls._value_matches(member.get("user_id"), expected)
                    for member in document.get("members", [])
                ):
                    return False
                continue
            if key == "members" and isinstance(expected, dict):
                elem_match = expected.get("$elemMatch")
                if elem_match is not None and not any(
                    cls._matches(member, elem_match)
                    for member in document.get("members", [])
                ):
                    return False
                continue
            if not cls._value_matches(document.get(key), expected):
                return False
        return True

    @classmethod
    def _value_matches(cls, actual: object, expected: object) -> bool:
        if isinstance(expected, dict):
            if "$ne" in expected:
                return actual != expected["$ne"]
            if "$in" in expected:
                return actual in expected["$in"]
        return actual == expected

    async def find_one(
        self, query: dict, projection: dict | None = None
    ) -> dict | None:
        return next(
            (document.copy() for document in self.documents if self._matches(document, query)),
            None,
        )

    def find(self, query: dict, projection: dict | None = None) -> FakeCursor:
        return FakeCursor(
            [
                document.copy()
                for document in self.documents
                if self._matches(document, query)
            ]
        )

    async def insert_one(self, document: dict) -> SimpleNamespace:
        stored = document.copy()
        stored["_id"] = ObjectId()
        self.documents.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def update_one(
        self,
        query: dict,
        update: dict,
        array_filters: list[dict] | None = None,
    ) -> SimpleNamespace:
        for document in self.documents:
            if not self._matches(document, query):
                continue
            document.update(update.get("$set", {}))
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

    async def find_one_and_update(
        self, query: dict, update: dict, return_document: object
    ) -> dict | None:
        for document in self.documents:
            if self._matches(document, query):
                document.update(update.get("$set", {}))
                return document.copy()
        return None


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


class FakeNexconnClient:
    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.calls: list[tuple[str, dict]] = []

    def _record(self, name: str, payload: dict) -> None:
        self.calls.append((name, payload))
        if self.fail_on == name:
            raise NexconnAPIError("mock Nexconn failure")

    async def issue_access_token(
        self, *, user_id: str, name: str, avatar_url: str | None
    ) -> str:
        self._record(
            "issue_access_token",
            {"user_id": user_id, "name": name, "avatar_url": avatar_url},
        )
        return "mock-nexconn-token"

    async def update_user(
        self, *, user_id: str, name: str, avatar_url: str | None
    ) -> None:
        self._record(
            "update_user",
            {"user_id": user_id, "name": name, "avatar_url": avatar_url},
        )

    async def create_group_channel(
        self,
        *,
        channel_id: str,
        name: str,
        owner: str,
        user_ids: list[str],
        description: str | None,
        picture_url: str | None,
    ) -> None:
        self._record(
            "create_group_channel",
            {
                "channel_id": channel_id,
                "name": name,
                "owner": owner,
                "user_ids": user_ids,
                "description": description,
                "picture_url": picture_url,
            },
        )

    async def join_group_channel(
        self, *, channel_id: str, user_ids: list[str]
    ) -> None:
        self._record(
            "join_group_channel",
            {"channel_id": channel_id, "user_ids": user_ids},
        )

    async def remove_group_members(
        self, *, channel_id: str, user_ids: list[str]
    ) -> None:
        self._record(
            "remove_group_members",
            {"channel_id": channel_id, "user_ids": user_ids},
        )

    async def update_group_channel_profile(
        self,
        *,
        channel_id: str,
        description: str | None,
        picture_url: str | None,
    ) -> None:
        self._record(
            "update_group_channel_profile",
            {
                "channel_id": channel_id,
                "description": description,
                "picture_url": picture_url,
            },
        )

    async def aclose(self) -> None:
        return None


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


def make_connection(first: ObjectId, second: ObjectId) -> dict:
    pair_key = ":".join(sorted((str(first), str(second))))
    return {"pair_key": pair_key, "status": "accepted"}


@pytest.fixture
def nexconn_app(monkeypatch: pytest.MonkeyPatch):
    settings = Settings(
        jwt_secret_key="test-signing-secret-that-is-at-least-32-bytes",
        nexconn_app_key="test-app-key",
        nexconn_app_secret="test-app-secret",
        nexconn_api_base_url="https://api.example.test",
        nexconn_enabled=True,
    )
    nexconn_client = FakeNexconnClient()
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(
        main, "create_nexconn_client", lambda _settings: nexconn_client
    )
    users = [make_user("alice"), make_user("bob"), make_user("carol")]
    connections = [
        make_connection(users[0]["_id"], users[1]["_id"]),
        make_connection(users[0]["_id"], users[2]["_id"]),
    ]
    database = FakeDatabase(users, connections)
    app = main.create_app()
    app.dependency_overrides[get_database] = lambda: database
    tokens = {
        user["username"]: create_access_token(str(user["_id"]), settings)[0]
        for user in users
    }
    return app, database, tokens, nexconn_client, settings


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


def test_nexconn_disabled_settings_do_not_require_credentials() -> None:
    settings = Settings(_env_file=None, nexconn_enabled=False)
    assert settings.nexconn_app_key == ""
    assert settings.nexconn_api_base_url == ""


def test_nexconn_enabled_settings_require_credentials() -> None:
    with pytest.raises(ValueError, match="required settings are missing"):
        Settings(_env_file=None, nexconn_enabled=True)


def test_nexconn_enabled_settings_require_secure_api_url() -> None:
    with pytest.raises(ValueError, match="must use HTTPS"):
        Settings(
            nexconn_enabled=True,
            nexconn_app_key="key",
            nexconn_app_secret="secret",
            nexconn_api_base_url="http://api.example.test",
        )


@pytest.mark.asyncio
async def test_client_signs_official_request_and_parses_token() -> None:
    settings = Settings(
        nexconn_enabled=True,
        nexconn_app_key="test-key",
        nexconn_app_secret="test-secret",
        nexconn_api_base_url="https://api.example.test",
    )
    requested_user_id = str(ObjectId())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v4/auth/access-token/issue"
        assert request.headers["App-Key"] == "test-key"
        nonce = request.headers["Nonce"]
        timestamp = request.headers["Timestamp"]
        expected = hashlib.sha1(
            f"test-secret{nonce}{timestamp}".encode("utf-8")
        ).hexdigest()
        assert request.headers["Signature"] == expected
        assert re.fullmatch(r"[0-9a-f]{18}", nonce)
        assert abs(int(timestamp) - int(time.time() * 1000)) < 5000
        assert request.headers["X-Request-ID"]
        request_body = json.loads(request.read())
        assert request_body == {
            "userId": requested_user_id,
            "name": "Alice",
        }
        return httpx.Response(
            200,
            json={
                "code": 0,
                "result": {
                    "userId": requested_user_id,
                    "accessToken": "remote-token",
                },
            },
        )

    http_client = httpx.AsyncClient(
        base_url=settings.nexconn_api_base_url,
        transport=httpx.MockTransport(handler),
    )
    client = NexconnClient(settings, http_client=http_client)
    try:
        token = await client.issue_access_token(
            user_id=requested_user_id,
            name="Alice",
            avatar_url=None,
        )
    finally:
        await http_client.aclose()

    assert token == "remote-token"


@pytest.mark.asyncio
async def test_client_sends_documented_group_text_message() -> None:
    settings = Settings(
        nexconn_enabled=True,
        nexconn_app_key="test-key",
        nexconn_app_secret="test-secret",
        nexconn_api_base_url="https://api.example.test",
    )
    channel_id = str(ObjectId())

    sender_id = "ai" + str(ObjectId())
    http_client = httpx.AsyncClient(
        base_url=settings.nexconn_api_base_url,
        transport=httpx.MockTransport(
            lambda request: _send_message_response(request, channel_id, sender_id)
        ),
    )
    client = NexconnClient(settings, http_client=http_client)
    try:
        receipt = await client.send_group_message(
            sender_user_id=sender_id,
            channel_id=channel_id,
            content="Answer",
        )
    finally:
        await http_client.aclose()
    assert receipt.channel_id == channel_id
    assert receipt.message_id == "remote-message-id"


def _send_message_response(
    request: httpx.Request,
    channel_id: str,
    sender_id: str,
) -> httpx.Response:
    assert request.method == "POST"
    assert request.url.path == "/v4/group-channel/message/send"
    body = json.loads(request.read())
    assert body == {
        "fromUserId": sender_id,
        "toChannelIds": [channel_id],
        "messageType": "RC:TxtMsg",
        "content": json.dumps({"content": "Answer", "extra": ""}),
        "shouldPersist": 1,
        "isEchoToSender": 0,
    }
    return httpx.Response(
        200,
        json={
            "code": 0,
            "result": {
                "messageIds": [
                    {"channelId": channel_id, "messageId": "remote-message-id"}
                ]
            },
        },
    )


@pytest.mark.asyncio
async def test_client_rejects_nonzero_api_response() -> None:
    settings = Settings(
        nexconn_enabled=True,
        nexconn_app_key="key",
        nexconn_app_secret="secret",
        nexconn_api_base_url="https://api.example.test",
    )
    http_client = httpx.AsyncClient(
        base_url=settings.nexconn_api_base_url,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"code": 9})
        ),
    )
    client = NexconnClient(settings, http_client=http_client)
    try:
        with pytest.raises(NexconnAPIError):
            await client._post("/v4/user/update", {"user_id": "user"})
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_client_uses_official_group_endpoints_and_payloads() -> None:
    settings = Settings(
        nexconn_enabled=True,
        nexconn_app_key="key",
        nexconn_app_secret="secret",
        nexconn_api_base_url="https://api.example.test",
    )
    requests: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"code": 0})

    http_client = httpx.AsyncClient(
        base_url=settings.nexconn_api_base_url,
        transport=httpx.MockTransport(handler),
    )
    client = NexconnClient(settings, http_client=http_client)
    try:
        await client.create_group_channel(
            channel_id="group-1",
            name="Team",
            owner="user-1",
            user_ids=["user-2"],
            description="Project",
            picture_url="https://example.test/team.png",
        )
        await client.join_group_channel(
            channel_id="group-1",
            user_ids=["user-3"],
        )
        await client.remove_group_members(
            channel_id="group-1",
            user_ids=["user-3"],
        )
        await client.update_group_channel_profile(
            channel_id="group-1",
            description=None,
            picture_url=None,
        )
    finally:
        await http_client.aclose()

    assert requests == [
        (
            "/v4/group-channel/create",
            {
                "channel_id": "group-1",
                "name": "Team",
                "owner": "user-1",
                "user_ids": ["user-2"],
                "group_profile": {
                    "introduction": "Project",
                    "portraitUrl": "https://example.test/team.png",
                },
            },
        ),
        (
            "/v4/group-channel/join",
            {"channel_id": "group-1", "user_ids": ["user-3"]},
        ),
        (
            "/v4/group-channel/quit",
            {"channel_id": "group-1", "user_ids": ["user-3"]},
        ),
        (
            "/v4/group-channel/profile/update",
            {
                "channel_id": "group-1",
                "group_profile": {
                    "introduction": None,
                    "portraitUrl": None,
                },
            },
        ),
    ]


@pytest.mark.asyncio
async def test_token_generation_and_sync_use_current_user_only(nexconn_app) -> None:
    app, database, tokens, nexconn_client, settings = nexconn_app
    async with make_client(app) as client:
        response = await client.post(
            "/api/v1/nexconn/token",
            headers=auth(tokens["alice"]),
        )

    assert response.status_code == 200
    result = response.json()
    user_id = str(database["users"].documents[0]["_id"])
    assert result == {
        "nexconn_token": "mock-nexconn-token",
        "nexconn_user_id": user_id,
        "app_key": settings.nexconn_app_key,
    }
    assert "test-app-secret" not in response.text
    assert database["users"].documents[0]["nexconn_sync_status"] == "synced"
    assert any(call[0] == "issue_access_token" for call in nexconn_client.calls)


@pytest.mark.asyncio
async def test_user_sync_updates_only_when_profile_changes(nexconn_app) -> None:
    app, database, tokens, nexconn_client, _ = nexconn_app
    async with make_client(app) as client:
        first = await client.post(
            "/api/v1/nexconn/token",
            headers=auth(tokens["alice"]),
        )
        second = await client.post(
            "/api/v1/nexconn/token",
            headers=auth(tokens["alice"]),
        )
        database["users"].documents[0]["full_name"] = "Alice Updated"
        third = await client.post(
            "/api/v1/nexconn/token",
            headers=auth(tokens["alice"]),
        )

    assert first.status_code == second.status_code == third.status_code == 200
    assert sum(call[0] == "issue_access_token" for call in nexconn_client.calls) == 3
    updates = [call for call in nexconn_client.calls if call[0] == "update_user"]
    assert len(updates) == 1
    assert updates[0][1]["name"] == "Alice Updated"


@pytest.mark.asyncio
async def test_token_generation_requires_authentication(nexconn_app) -> None:
    app, _, _, _, _ = nexconn_app
    async with make_client(app) as client:
        response = await client.post("/api/v1/nexconn/token")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_api_failure_is_explicit_and_saved(nexconn_app) -> None:
    app, database, tokens, nexconn_client, _ = nexconn_app
    nexconn_client.fail_on = "issue_access_token"
    async with make_client(app) as client:
        response = await client.post(
            "/api/v1/nexconn/token",
            headers=auth(tokens["alice"]),
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Nexconn token generation failed"
    assert database["users"].documents[0]["nexconn_sync_status"] == "failed"


@pytest.mark.asyncio
async def test_group_channel_create_and_membership_sync(nexconn_app) -> None:
    app, database, tokens, nexconn_client, _ = nexconn_app
    alice_id = str(database["users"].documents[0]["_id"])
    bob_id = str(database["users"].documents[1]["_id"])
    carol_id = str(database["users"].documents[2]["_id"])
    async with make_client(app) as client:
        created = await client.post(
            "/api/v1/groups",
            json={"name": "Team", "member_ids": [bob_id]},
            headers=auth(tokens["alice"]),
        )
        assert created.status_code == 201
        group_id = created.json()["group_id"]
        assert created.json()["nexconn_channel_id"] == group_id
        assert created.json()["nexconn_sync_status"] == "synced"
        create_call = next(
            call for call in nexconn_client.calls if call[0] == "create_group_channel"
        )
        assert create_call[1]["owner"] == alice_id
        assert create_call[1]["channel_id"] == group_id
        assert create_call[1]["user_ids"] == [bob_id]

        updated = await client.put(
            f"/api/v1/groups/{group_id}",
            json={"description": "Updated description"},
            headers=auth(tokens["alice"]),
        )
        assert updated.status_code == 200
        profile_call = next(
            call
            for call in nexconn_client.calls
            if call[0] == "update_group_channel_profile"
        )
        assert profile_call[1]["description"] == "Updated description"

        added = await client.post(
            f"/api/v1/groups/{group_id}/members",
            json={"user_ids": [carol_id]},
            headers=auth(tokens["alice"]),
        )
        assert added.status_code == 201
        assert added.json()["nexconn_sync_status"] == "synced"
        join_call = next(
            call for call in nexconn_client.calls if call[0] == "join_group_channel"
        )
        assert join_call[1] == {"channel_id": group_id, "user_ids": [carol_id]}

        removed = await client.delete(
            f"/api/v1/groups/{group_id}/members/{carol_id}",
            headers=auth(tokens["alice"]),
        )
        assert removed.status_code == 204
        remove_call = next(
            call for call in nexconn_client.calls if call[0] == "remove_group_members"
        )
        assert remove_call[1] == {"channel_id": group_id, "user_ids": [carol_id]}

        channel = await client.get(
            f"/api/v1/groups/{group_id}/chat-channel",
            headers=auth(tokens["bob"]),
        )
        forbidden = await client.get(
            f"/api/v1/groups/{group_id}/chat-channel",
            headers=auth(tokens["carol"]),
        )

    assert channel.status_code == 200
    assert channel.json() == {
        "group_id": group_id,
        "channel_id": group_id,
        "sync_status": "synced",
    }
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_group_sync_failure_is_reported_in_group_response(nexconn_app) -> None:
    app, database, tokens, nexconn_client, _ = nexconn_app
    nexconn_client.fail_on = "create_group_channel"
    bob_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        response = await client.post(
            "/api/v1/groups",
            json={"name": "Team", "member_ids": [bob_id]},
            headers=auth(tokens["alice"]),
        )

    assert response.status_code == 201
    assert response.json()["nexconn_sync_status"] == "failed"


@pytest.mark.asyncio
async def test_disabled_integration_reports_status_and_rejects_token(nexconn_app, monkeypatch) -> None:
    settings = Settings(
        jwt_secret_key="test-signing-secret-that-is-at-least-32-bytes",
        nexconn_enabled=False,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = main.create_app()
    database = FakeDatabase([make_user("alice")], [])
    app.dependency_overrides[get_database] = lambda: database
    token = create_access_token(
        str(database["users"].documents[0]["_id"]), settings
    )[0]
    async with make_client(app) as client:
        status_response = await client.get(
            "/api/v1/nexconn/status",
            headers=auth(token),
        )
        token_response = await client.post(
            "/api/v1/nexconn/token",
            headers=auth(token),
        )

    assert status_response.status_code == 200
    assert status_response.json() == {"enabled": False, "status": "disabled"}
    assert token_response.status_code == 503
