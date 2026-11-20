import hashlib
import json
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
from app.services.nexconn import NexconnAPIError, NexconnMessageReceipt


class FakeCursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents
        self.maximum = len(documents)

    def sort(self, keys: object, direction: int | None = None) -> "FakeCursor":
        fields = [(keys, direction)] if isinstance(keys, str) else keys
        for key, order in reversed(fields):
            self.documents.sort(
                key=lambda document: document.get(key),
                reverse=order < 0,
            )
        return self

    def limit(self, maximum: int) -> "FakeCursor":
        self.maximum = maximum
        return self

    async def to_list(self, length: int) -> list[dict]:
        return self.documents[: min(length, self.maximum)]


class FakeCollection:
    def __init__(
        self,
        documents: list[dict] | None = None,
        unique_fields: tuple[str, ...] = (),
    ) -> None:
        self.documents = documents if documents is not None else []
        self.indexes: list[tuple[object, dict]] = []
        self.unique_fields = unique_fields

    async def create_index(self, keys: object, **options: object) -> str:
        self.indexes.append((keys, options))
        return str(keys)

    async def index_information(self) -> dict[str, dict]:
        information: dict[str, dict] = {}
        for keys, options in self.indexes:
            if isinstance(keys, str):
                name = f"{keys}_1"
            else:
                name = "_".join(f"{key}_{direction}" for key, direction in keys)
            information[name] = dict(options)
        return information

    async def drop_index(self, name: str) -> None:
        self.indexes = [
            (keys, options)
            for keys, options in self.indexes
            if (
                f"{keys}_1"
                if isinstance(keys, str)
                else "_".join(f"{key}_{direction}" for key, direction in keys)
            )
            != name
        ]

    @classmethod
    def _value(cls, document: dict, key: str) -> object:
        current: object = document
        for part in key.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    @classmethod
    def _matches(cls, document: dict, query: dict) -> bool:
        for key, expected in query.items():
            if key == "$or":
                if not any(cls._matches(document, clause) for clause in expected):
                    return False
                continue
            if key == "$and":
                if not all(cls._matches(document, clause) for clause in expected):
                    return False
                continue
            if key.startswith("members.") and "." not in key[len("members.") :]:
                member_key = key.split(".", 1)[1]
                if not any(
                    cls._matches(member, {member_key: expected})
                    for member in document.get("members", [])
                ):
                    return False
                continue
            if key == "members" and isinstance(expected, dict):
                condition = expected.get("$elemMatch")
                if condition is not None and not any(
                    cls._matches(member, condition)
                    for member in document.get("members", [])
                ):
                    return False
                continue

            actual = cls._value(document, key)
            if isinstance(expected, dict):
                if "$lt" in expected and not (
                    actual is not None and actual < expected["$lt"]
                ):
                    return False
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$type" in expected and expected["$type"] == "string":
                    if not isinstance(actual, str):
                        return False
                if "$exists" in expected and (key in document) != expected["$exists"]:
                    return False
                if not any(
                    operator in expected
                    for operator in ("$lt", "$ne", "$in", "$type", "$exists")
                ):
                    return False
            elif actual != expected:
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
        external_id = document.get("nexconn_message_id")
        if external_id and await self.find_one({"nexconn_message_id": external_id}):
            raise DuplicateKeyError("duplicate Nexconn message")
        for field in self.unique_fields:
            value = document.get(field)
            if value is not None and await self.find_one({field: value}):
                raise DuplicateKeyError(f"duplicate {field}")
        inserted = document.copy()
        inserted["_id"] = ObjectId()
        self.documents.append(inserted)
        return SimpleNamespace(inserted_id=inserted["_id"])

    async def update_one(
        self,
        query: dict,
        update: dict,
        upsert: bool = False,
    ) -> SimpleNamespace:
        for document in self.documents:
            if not self._matches(document, query):
                continue
            document.update(update.get("$set", {}))
            for key, value in update.get("$max", {}).items():
                if document.get(key) is None or value > document[key]:
                    document[key] = value
            return SimpleNamespace(modified_count=1)
        if upsert:
            document = query.copy()
            document.update(update.get("$setOnInsert", {}))
            self.documents.append(document)
            return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    async def update_many(self, query: dict, update: object) -> SimpleNamespace:
        modified = 0
        for document in self.documents:
            if not self._matches(document, query):
                continue
            if isinstance(update, list):
                for stage in update:
                    for key, value in stage.get("$set", {}).items():
                        document[key] = (
                            document.get(value[1:])
                            if isinstance(value, str) and value.startswith("$")
                            else value
                        )
            else:
                document.update(update.get("$set", {}))
            modified += 1
        return SimpleNamespace(modified_count=modified)

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

    async def count_documents(self, query: dict) -> int:
        return sum(self._matches(document, query) for document in self.documents)


class FakeDatabase:
    def __init__(self, users: list[dict], group: dict) -> None:
        self.collections = {
            "users": FakeCollection(users),
            "groups": FakeCollection([group]),
            "messages": FakeCollection(unique_fields=("delivery_key",)),
            "message_processing_events": FakeCollection(),
            "agents": FakeCollection(),
            "orchestration_runs": FakeCollection(
                unique_fields=("message_id", "orchestration_id")
            ),
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


@pytest.fixture
def message_app(monkeypatch: pytest.MonkeyPatch):
    settings = Settings(
        _env_file=None,
        jwt_secret_key="test-signing-secret-that-is-at-least-32-bytes",
        nexconn_app_key="webhook-app-key",
        nexconn_app_secret="webhook-app-secret",
        nexconn_api_base_url="https://api.example.test",
        nexconn_enabled=True,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    users = [make_user("alice"), make_user("bob"), make_user("carol")]
    group = {
        "_id": ObjectId(),
        "name": "Team",
        "creator_id": users[0]["_id"],
        "members": [
            {"user_id": users[0]["_id"], "role": "admin"},
            {"user_id": users[1]["_id"], "role": "member"},
        ],
        "nexconn_channel_id": "nexconn-team",
        "ai_agents": [],
    }
    database = FakeDatabase(users, group)
    app = main.create_app()
    app.dependency_overrides[get_database] = lambda: database
    tokens = {
        user["username"]: create_access_token(str(user["_id"]), settings)[0]
        for user in users
    }
    return app, database, tokens, settings


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


def webhook_headers(settings: Settings) -> dict[str, str]:
    nonce = "nexconnnonce123456"
    timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    signature = hashlib.sha1(
        f"{settings.nexconn_app_secret}{nonce}{timestamp}".encode()
    ).hexdigest()
    return {
        "AppKey": settings.nexconn_app_key,
        "Nonce": nonce,
        "Timestamp": timestamp,
        "Signature": signature,
    }


def webhook_payload(sender_id: str, message_id: str, text: str, event_id: str) -> dict:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {
        "type": "message:send",
        "id": event_id,
        "time": now_ms,
        "data": [
            {
                "userId": sender_id,
                "channelId": "nexconn-team",
                "messageType": "RC:TxtMsg",
                "content": json.dumps({"content": text, "extra": ""}),
                "channelType": 3,
                "time": now_ms,
                "messageId": message_id,
                "os": "Websocket",
                "profanityType": 0,
            }
        ],
    }


class MockMessageSender:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = list(failures or [])
        self.sent: list[dict[str, str]] = []

    async def send_group_message(
        self, *, sender_user_id: str, channel_id: str, content: str
    ) -> NexconnMessageReceipt:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(
            {
                "sender_user_id": sender_user_id,
                "channel_id": channel_id,
                "content": content,
            }
        )
        return NexconnMessageReceipt(channel_id, f"remote-{len(self.sent)}")


@pytest.mark.asyncio
async def test_webhook_persists_message_and_deduplicates(message_app) -> None:
    app, database, tokens, settings = message_app
    sender_id = str(database["users"].documents[1]["_id"])
    payload = webhook_payload(sender_id, "nex-msg-1", "Hello team", "event-1")
    async with make_client(app) as client:
        response = await client.post(
            "/api/v1/webhooks/nexconn/messages",
            json=payload,
            headers=webhook_headers(settings),
        )
        repeated = await client.post(
            "/api/v1/webhooks/nexconn/messages",
            json=payload,
            headers=webhook_headers(settings),
        )

    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "duplicates": 0}
    assert repeated.status_code == 200
    assert repeated.json() == {"accepted": 0, "duplicates": 1}
    assert len(database["messages"].documents) == 1
    message = database["messages"].documents[0]
    assert message["content"] == "Hello team"
    assert message["sender_type"] == "user"
    assert message["sender_id"] == ObjectId(sender_id)
    assert message["nexconn_message_id"] == "nex-msg-1"
    assert "webhook-app-secret" not in repr(message)
    assert database["groups"].documents[0]["last_message_at"] == message["created_at"]


@pytest.mark.asyncio
async def test_human_send_persists_and_is_idempotent(message_app) -> None:
    app, database, tokens, _settings = message_app
    group_id = str(database["groups"].documents[0]["_id"])
    sender_id = str(database["users"].documents[0]["_id"])
    message_sender = MockMessageSender()

    async with make_client(app) as client:
        app.state.nexconn_client = message_sender
        response = await client.post(
            f"/api/v1/groups/{group_id}/messages",
            headers={**auth(tokens["alice"]), "Idempotency-Key": "message-request-0001"},
            json={"content": "Hello group"},
        )
        repeated = await client.post(
            f"/api/v1/groups/{group_id}/messages",
            headers={**auth(tokens["alice"]), "Idempotency-Key": "message-request-0001"},
            json={"content": "Hello group"},
        )

    assert response.status_code == 201
    assert response.json()["delivery_status"] == "delivered"
    assert response.json()["sender"]["id"] == sender_id
    assert repeated.json()["message_id"] == response.json()["message_id"]
    assert len(message_sender.sent) == 1
    assert len(database["messages"].documents) == 1


@pytest.mark.asyncio
async def test_human_send_failure_can_be_retried_without_duplicate_local_message(
    message_app,
) -> None:
    app, database, tokens, _settings = message_app
    group_id = str(database["groups"].documents[0]["_id"])
    message_sender = MockMessageSender(
        [NexconnAPIError("temporary Nexconn failure", retryable=True)]
    )

    async with make_client(app) as client:
        app.state.nexconn_client = message_sender
        response = await client.post(
            f"/api/v1/groups/{group_id}/messages",
            headers={**auth(tokens["alice"]), "Idempotency-Key": "message-request-0002"},
            json={"content": "Retry this message"},
        )
        message_id = response.json()["message_id"]
        retried = await client.post(
            f"/api/v1/messages/{message_id}/retry",
            headers=auth(tokens["alice"]),
        )

    assert response.status_code == 201
    assert response.json()["delivery_status"] == "failed"
    assert retried.status_code == 200
    assert retried.json()["delivery_status"] == "delivered"
    assert retried.json()["message_id"] == message_id
    assert len(message_sender.sent) == 1
    assert len(database["messages"].documents) == 1


@pytest.mark.asyncio
async def test_human_send_rejects_nonmembers_and_unsupported_attachments(
    message_app,
) -> None:
    app, database, tokens, _settings = message_app
    group_id = str(database["groups"].documents[0]["_id"])
    message_sender = MockMessageSender()

    async with make_client(app) as client:
        app.state.nexconn_client = message_sender
        unauthorized = await client.post(
            f"/api/v1/groups/{group_id}/messages",
            headers={**auth(tokens["carol"]), "Idempotency-Key": "message-request-0003"},
            json={"content": "Not a member"},
        )
        attachment = await client.post(
            f"/api/v1/groups/{group_id}/messages",
            headers={**auth(tokens["alice"]), "Idempotency-Key": "message-request-0004"},
            json={
                "content": "Unsupported attachment",
                "attachments": [{"type": "file", "url": "https://example.test/a.txt"}],
            },
        )

    assert unauthorized.status_code == 403
    assert attachment.status_code == 422
    assert message_sender.sent == []
    assert database["messages"].documents == []


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature_and_nonmember_sender(message_app) -> None:
    app, database, _, settings = message_app
    carol_id = str(database["users"].documents[2]["_id"])
    headers = webhook_headers(settings)
    headers["Signature"] = "0" * 40
    async with make_client(app) as client:
        invalid_signature = await client.post(
            "/api/v1/webhooks/nexconn/messages",
            json=webhook_payload(carol_id, "msg-invalid-sig", "hello", "evt-a"),
            headers=headers,
        )
        nonmember = await client.post(
            "/api/v1/webhooks/nexconn/messages",
            json=webhook_payload(carol_id, "msg-nonmember", "hello", "evt-b"),
            headers=webhook_headers(settings),
        )

    assert invalid_signature.status_code == 401
    assert nonmember.status_code == 403
    assert database["messages"].documents == []


@pytest.mark.asyncio
async def test_reused_nexconn_message_id_cannot_cross_sender_or_group(message_app) -> None:
    app, database, _, settings = message_app
    bob_id = str(database["users"].documents[1]["_id"])
    carol_id = str(database["users"].documents[2]["_id"])
    database["groups"].documents[0]["members"].append(
        {"user_id": ObjectId(carol_id), "role": "member"}
    )
    async with make_client(app) as client:
        first = await client.post(
            "/api/v1/webhooks/nexconn/messages",
            json=webhook_payload(bob_id, "global-msg-id", "Original", "evt-1"),
            headers=webhook_headers(settings),
        )
        conflict = await client.post(
            "/api/v1/webhooks/nexconn/messages",
            json=webhook_payload(carol_id, "global-msg-id", "Altered", "evt-2"),
            headers=webhook_headers(settings),
        )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert len(database["messages"].documents) == 1
    assert database["messages"].documents[0]["content"] == "Original"


@pytest.mark.asyncio
async def test_history_membership_pagination_and_stats(message_app) -> None:
    app, database, tokens, settings = message_app
    sender_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        for index in range(3):
            created = await client.post(
                "/api/v1/webhooks/nexconn/messages",
                json=webhook_payload(
                    sender_id,
                    f"msg-{index}",
                    f"Message {index}",
                    f"event-{index}",
                ),
                headers=webhook_headers(settings),
            )
            assert created.status_code == 200
        latest = await client.get(
            f"/api/v1/groups/{database['groups'].documents[0]['_id']}/messages",
            params={"limit": 2},
            headers=auth(tokens["alice"]),
        )
        older = await client.get(
            f"/api/v1/groups/{database['groups'].documents[0]['_id']}/messages",
            params={"limit": 2, "before": latest.json()["next_cursor"]},
            headers=auth(tokens["alice"]),
        )
        ai_payload = webhook_payload(
            str(database["users"].documents[0]["_id"]),
            "ai-message",
            "AI response",
            "event-ai-stats",
        )
        ai_payload["data"][0]["aiGenerated"] = True
        ai_response = await client.post(
            "/api/v1/webhooks/nexconn/messages",
            json=ai_payload,
            headers=webhook_headers(settings),
        )
        stats = await client.get(
            f"/api/v1/groups/{database['groups'].documents[0]['_id']}/messages/stats",
            headers=auth(tokens["alice"]),
        )
        denied = await client.get(
            f"/api/v1/groups/{database['groups'].documents[0]['_id']}/messages",
            headers=auth(tokens["carol"]),
        )
        message_nonmember = await client.get(
            f"/api/v1/messages/{database['messages'].documents[0]['_id']}",
            headers=auth(tokens["carol"]),
        )
        unauthorized = await client.get(
            f"/api/v1/groups/{database['groups'].documents[0]['_id']}/messages"
        )

    assert latest.status_code == 200
    assert [item["content"] for item in latest.json()["items"]] == [
        "Message 1",
        "Message 2",
    ]
    assert latest.json()["next_cursor"]
    assert [item["content"] for item in older.json()["items"]] == ["Message 0"]
    assert older.json()["next_cursor"] is None
    assert ai_response.status_code == 200
    assert stats.json()["total_message_count"] == 4
    assert stats.json()["human_message_count"] == 3
    assert stats.json()["ai_message_count"] == 1
    assert denied.status_code == 403
    assert message_nonmember.status_code == 403
    assert unauthorized.status_code == 401


@pytest.mark.asyncio
async def test_message_retrieval_and_soft_delete_permissions(message_app) -> None:
    app, database, tokens, settings = message_app
    alice_id = str(database["users"].documents[0]["_id"])
    bob_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        await client.post(
            "/api/v1/webhooks/nexconn/messages",
            json=webhook_payload(bob_id, "message-for-delete", "Remove me", "evt-del"),
            headers=webhook_headers(settings),
        )
        message_id = str(database["messages"].documents[0]["_id"])
        retrieved = await client.get(
            f"/api/v1/messages/{message_id}",
            headers=auth(tokens["alice"]),
        )
        invalid_id = await client.get(
            "/api/v1/messages/not-an-object-id",
            headers=auth(tokens["alice"]),
        )
        denied = await client.delete(
            f"/api/v1/messages/{message_id}",
            headers=auth(tokens["carol"]),
        )
        deleted = await client.delete(
            f"/api/v1/messages/{message_id}",
            headers=auth(tokens["alice"]),
        )
        deleted_result = await client.get(
            f"/api/v1/messages/{message_id}",
            headers=auth(tokens["bob"]),
        )
        history = await client.get(
            f"/api/v1/groups/{database['groups'].documents[0]['_id']}/messages",
            headers=auth(tokens["alice"]),
        )

    assert retrieved.status_code == 200
    assert retrieved.json()["sender"]["id"] == bob_id
    assert invalid_id.status_code == 404
    assert denied.status_code == 403
    assert deleted.status_code == 204
    assert deleted_result.json()["is_deleted"] is True
    assert deleted_result.json()["content"] == "This message was deleted"
    assert history.json()["items"] == []
    assert database["messages"].documents[0]["content"] == "This message was deleted"


@pytest.mark.asyncio
async def test_sender_can_delete_and_invalid_auth_is_rejected(message_app) -> None:
    app, database, tokens, settings = message_app
    bob_id = str(database["users"].documents[1]["_id"])
    async with make_client(app) as client:
        await client.post(
            "/api/v1/webhooks/nexconn/messages",
            json=webhook_payload(bob_id, "sender-delete", "My message", "evt-own"),
            headers=webhook_headers(settings),
        )
        message_id = str(database["messages"].documents[0]["_id"])
        sender_delete = await client.delete(
            f"/api/v1/messages/{message_id}",
            headers=auth(tokens["bob"]),
        )
        nonexistent = await client.get(
            f"/api/v1/messages/{ObjectId()}",
            headers=auth(tokens["bob"]),
        )
        no_auth = await client.delete(f"/api/v1/messages/{message_id}")

    assert sender_delete.status_code == 204
    assert nonexistent.status_code == 404
    assert no_auth.status_code == 401


@pytest.mark.asyncio
async def test_ai_messages_run_orchestration_and_preserve_processing_event(message_app) -> None:
    app, database, _, settings = message_app
    database["groups"].documents[0]["ai_agents"] = [{"agent_id": "agent"}]
    alice_id = str(database["users"].documents[0]["_id"])
    async with make_client(app) as client:
        response = await client.post(
            "/api/v1/webhooks/nexconn/messages",
            json=webhook_payload(alice_id, "ai-trigger", "Ask AI", "evt-ai"),
            headers=webhook_headers(settings),
        )
        assert database["messages"].documents[0]["ai_processing_status"] == "not_required"
        assert database["message_processing_events"].documents[0]["status"] == "completed"
        deleted = await client.delete(
            f"/api/v1/messages/{database['messages'].documents[0]['_id']}",
            headers=auth(
                create_access_token(
                    alice_id,
                    settings,
                )[0]
            ),
        )

    assert response.status_code == 200
    message = database["messages"].documents[0]
    assert len(database["message_processing_events"].documents) == 1
    assert message["ai_processing_status"] == "not_required"
    assert database["message_processing_events"].documents[0]["status"] == "completed"
    assert database["orchestration_runs"].documents[0]["status"] == "completed"
    assert deleted.status_code == 204
