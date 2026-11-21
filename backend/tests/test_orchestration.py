import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI
from pydantic import ValidationError

import app.main as main
from app.core.config import Settings
from app.core.security import create_access_token
from app.database.indexes import ensure_orchestration_indexes
from app.database.mongodb import get_database
from app.schemas.orchestration import AgentTask, CoordinatorPlan
from app.services.messaging.ai_message_delivery import AIMessageDeliveryService
from app.services.nexconn import NexconnAPIError, NexconnMessageReceipt
from app.services.agent_templates import get_agent_template, get_agent_templates
from app.services.orchestration.provider import GeminiModelProvider
from app.services.orchestration.service import OrchestrationMessageProcessor
from tests.test_messages import FakeDatabase, make_user


class MockProvider:
    def __init__(
        self,
        plan: CoordinatorPlan | None = None,
        *,
        coordinator_error: bool = False,
        agent_error: bool = False,
    ) -> None:
        self.plan = plan
        self.coordinator_error = coordinator_error
        self.agent_error = agent_error
        self.active_calls = 0
        self.max_active_calls = 0
        self.text_calls: list[list[dict[str, str]]] = []

    async def structured_output(
        self,
        *,
        model_name: str,
        temperature: float,
        schema: type[CoordinatorPlan],
        messages: list[dict[str, str]],
    ) -> CoordinatorPlan:
        if self.coordinator_error or self.plan is None:
            raise ValueError("Invalid mocked coordinator result")
        return self.plan

    async def text_output(
        self,
        *,
        model_name: str,
        temperature: float,
        messages: list[dict[str, str]],
        configuration: dict[str, Any] | None = None,
    ) -> str:
        if messages[0]["content"].startswith("You synthesize"):
            return "Synthesized answer."
        self.text_calls.append(messages)
        if self.agent_error:
            raise RuntimeError("Mock model unavailable")
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        await asyncio.sleep(0.02)
        self.active_calls -= 1
        return "Agent response."


class MockNexconnClient:
    def __init__(self, *, failures: list[NexconnAPIError] | None = None) -> None:
        self.failures = list(failures or [])
        self.token_requests: list[dict[str, Any]] = []
        self.sent_messages: list[dict[str, str]] = []

    async def issue_access_token(
        self, *, user_id: str, name: str, avatar_url: str | None
    ) -> str:
        self.token_requests.append(
            {"user_id": user_id, "name": name, "avatar_url": avatar_url}
        )
        return "mock-token"

    async def send_group_message(
        self, *, sender_user_id: str, channel_id: str, content: str
    ) -> NexconnMessageReceipt:
        if self.failures:
            raise self.failures.pop(0)
        self.sent_messages.append(
            {
                "sender_user_id": sender_user_id,
                "channel_id": channel_id,
                "content": content,
            }
        )
        return NexconnMessageReceipt(channel_id, f"remote-{len(self.sent_messages)}")


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret_key="test-signing-secret-that-is-at-least-32-bytes",
        default_llm_model="gemini-test",
        orchestration_timeout_seconds=10,
        max_parallel_agents=4,
    )


def test_builtin_templates_use_configured_gemini_model() -> None:
    model_name = "gemini-configured-test"
    templates = get_agent_templates(model_name)

    assert templates
    assert all(template["model"] == model_name for template in templates)
    assert get_agent_template("research", model_name)["model"] == model_name
    assert get_agent_template("missing", model_name) is None


def test_legacy_builtin_agent_model_uses_configured_model() -> None:
    settings = _settings().model_copy(
        update={"default_llm_model": "gemini-configured-test"}
    )
    processor = OrchestrationMessageProcessor(None, settings, MockProvider())

    context = processor._agent_context(
        {
            "_id": ObjectId(),
            "template_id": "research",
            "name": "Research Agent",
            "system_prompt": "Research carefully.",
            "model": "gemini-2.5-flash",
        }
    )

    assert context["model"] == "gemini-configured-test"


def test_gemini_36_and_later_omit_deprecated_sampling_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_model(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "langchain_google_genai.ChatGoogleGenerativeAI",
        fake_model,
    )
    settings = _settings().model_copy(
        update={"gemini_api_key": "test-key"}
    )
    provider = GeminiModelProvider(settings)

    provider._model(
        "gemini-3.8-flash",
        0.2,
        {"top_p": 0.8, "max_tokens": 256},
    )

    assert captured["temperature"] is None
    assert "top_p" not in captured
    assert captured["max_output_tokens"] == 256


def test_older_gemini_models_keep_supported_sampling_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_model(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "langchain_google_genai.ChatGoogleGenerativeAI",
        fake_model,
    )
    provider = GeminiModelProvider(
        _settings().model_copy(update={"gemini_api_key": "test-key"})
    )

    provider._model("gemini-2.5-flash", 0.2, {"top_p": 0.8})

    assert captured["temperature"] == 0.2
    assert captured["top_p"] == 0.8


def _group(users: list[dict]) -> dict:
    return {
        "_id": ObjectId(),
        "name": "Orchestration team",
        "creator_id": users[0]["_id"],
        "members": [
            {"user_id": users[0]["_id"], "role": "admin"},
            {"user_id": users[1]["_id"], "role": "member"},
        ],
        "settings": {"language": "en"},
        "ai_agents": [],
    }


def _agent(group_id: ObjectId, name: str) -> dict:
    return {
        "_id": ObjectId(),
        "group_id": group_id,
        "template_id": "research",
        "name": name,
        "description": "Research and summarize.",
        "system_prompt": "You research carefully.",
        "model": "gemini-test",
        "temperature": 0.2,
        "capabilities": ["research"],
        "configuration": {"max_tokens": 512},
        "enabled": True,
        "created_at": datetime.now(timezone.utc),
    }


def _message(group: dict, user: dict, content: str = "Explain this topic") -> dict:
    return {
        "_id": ObjectId(),
        "group_id": group["_id"],
        "nexconn_channel_id": None,
        "nexconn_message_id": None,
        "sender_id": user["_id"],
        "sender_type": "user",
        "sender_name": user["full_name"],
        "content": content,
        "message_type": "text",
        "attachments": [],
        "reply_to_message_id": None,
        "metadata": {},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "is_deleted": False,
        "ai_processing_status": "pending",
    }


def _plan(agents: list[dict], mode: str = "parallel") -> CoordinatorPlan:
    return CoordinatorPlan(
        requires_ai=True,
        reasoning="Two specialists can address different aspects.",
        selected_agent_ids=[str(agent["_id"]) for agent in agents],
        tasks=[
            AgentTask(
                agent_id=str(agent["_id"]),
                instruction=f"Analyze the request as {agent['name']}.",
                depends_on=(
                    [str(agents[0]["_id"])]
                    if mode == "sequential" and index == 1
                    else []
                ),
            )
            for index, agent in enumerate(agents)
        ],
        execution_mode=mode,
    )


def _database_with_message(agent_count: int = 2):
    users = [make_user("alice"), make_user("bob"), make_user("outsider")]
    group = _group(users)
    group["nexconn_channel_id"] = "nexconn-team"
    database = FakeDatabase(users, group)
    agents = [_agent(group["_id"], f"Agent {index}") for index in range(agent_count)]
    database["agents"].documents.extend(agents)
    plain_message = _message(group, users[1], "Please summarize this")
    message = _message(group, users[1], "@Research Agent summarize this")
    database["messages"].documents.extend([plain_message, message])
    return database, users, group, agents, message


@pytest.mark.asyncio
async def test_orchestration_index_migration_preserves_legacy_message_keys() -> None:
    database, _, _, _, _ = _database_with_message(agent_count=0)
    legacy_orchestration_id = "legacy-run"
    database["messages"].documents[0]["orchestration_id"] = legacy_orchestration_id
    database["messages"].indexes.append(
        ("orchestration_id", {"unique": True})
    )

    await ensure_orchestration_indexes(database)

    migrated = database["messages"].documents[0]
    assert migrated["delivery_key"] == legacy_orchestration_id
    indexes = await database["messages"].index_information()
    assert indexes["orchestration_id_1"].get("unique") is not True
    assert indexes["delivery_key_1"]["unique"] is True


@pytest.mark.asyncio
async def test_parallel_orchestration_persists_results_and_ai_message() -> None:
    database, _, group, agents, message = _database_with_message()
    provider = MockProvider(_plan(agents))
    processor = OrchestrationMessageProcessor(database, _settings(), provider)

    run = await processor.orchestrate_message(str(message["_id"]))

    assert run is not None
    assert run["status"] == "completed"
    assert run["selected_agent_ids"] == [str(agent["_id"]) for agent in agents]
    assert run["final_response"] == "Synthesized answer."
    assert len(run["agent_results"]) == 2
    assert provider.max_active_calls == 2
    ai_messages = [
        item
        for item in database["messages"].documents
        if item.get("sender_type") == "agent"
    ]
    assert len(ai_messages) == 1
    assert ai_messages[0]["group_id"] == group["_id"]
    assert ai_messages[0]["reply_to_message_id"] == message["_id"]
    assert ai_messages[0]["orchestration_id"] == run["orchestration_id"]
    assert message["ai_processing_status"] == "completed"


@pytest.mark.asyncio
async def test_orchestration_preserves_retrieved_citations(monkeypatch) -> None:
    database, _, _, _, message = _database_with_message(agent_count=1)
    citations = [
        {
            "document_id": str(ObjectId()),
            "filename": "research.txt",
            "chunk_index": 0,
            "page_number": 1,
            "excerpt": "Verified source excerpt.",
        }
    ]

    class RetrievalService:
        def __init__(self, _settings: Settings, _database: object) -> None:
            pass

        async def retrieve(self, *, group_id: str, query: str) -> list[dict]:
            return citations

    monkeypatch.setattr(
        "app.services.orchestration.service.DocumentRetrievalService",
        RetrievalService,
    )
    run = await OrchestrationMessageProcessor(
        database, _settings(), MockProvider(_plan(database["agents"].documents))
    ).orchestrate_message(str(message["_id"]))

    assert run is not None
    assert run["status"] == "completed"
    assert run["citations"] == citations


@pytest.mark.asyncio
async def test_ai_delivery_persists_distinct_sender_and_is_idempotent() -> None:
    database, _, group, _, message = _database_with_message(agent_count=0)
    group["nexconn_channel_id"] = "nexconn-group"
    orchestration_id = "run-delivery-success"
    database["orchestration_runs"].documents.append(
        {
            "orchestration_id": orchestration_id,
            "message_id": message["_id"],
            "group_id": group["_id"],
            "status": "completed",
            "final_response": "Synthesized answer.",
            "agent_results": [],
        }
    )
    client = MockNexconnClient()
    settings = _settings().model_copy(update={"nexconn_enabled": True})
    delivery = AIMessageDeliveryService(database, settings, client)

    await delivery.deliver_orchestration(orchestration_id)
    await delivery.deliver_orchestration(orchestration_id)

    ai_messages = [
        item
        for item in database["messages"].documents
        if item.get("orchestration_id") == orchestration_id
    ]
    assert len(ai_messages) == 1
    assert ai_messages[0]["sender_type"] == "agent"
    assert ai_messages[0]["sender_id"] == f"ai{group['_id']}coordinator"
    assert ai_messages[0]["delivery_status"] == "delivered"
    assert ai_messages[0]["nexconn_message_id"] == "remote-1"
    assert client.sent_messages == [
        {
            "sender_user_id": f"ai{group['_id']}coordinator",
            "channel_id": "nexconn-group",
            "content": "Synthesized answer.",
        }
    ]
    assert database["orchestration_runs"].documents[0]["delivery_status"] == "delivered"


@pytest.mark.asyncio
async def test_ai_delivery_retries_transient_error_and_persists_permanent_failure() -> None:
    database, _, group, _, message = _database_with_message(agent_count=0)
    group["nexconn_channel_id"] = "nexconn-group"
    orchestration_id = "run-delivery-retry"
    run = {
        "orchestration_id": orchestration_id,
        "message_id": message["_id"],
        "group_id": group["_id"],
        "status": "completed",
        "final_response": "Answer to deliver.",
        "agent_results": [],
    }
    database["orchestration_runs"].documents.append(run)
    transient = MockNexconnClient(
        failures=[NexconnAPIError("temporary", retryable=True)]
    )
    settings = _settings().model_copy(
        update={
            "nexconn_enabled": True,
            "nexconn_delivery_max_retries": 1,
            "nexconn_delivery_retry_base_seconds": 0.05,
        }
    )

    await AIMessageDeliveryService(database, settings, transient).deliver_orchestration(
        orchestration_id
    )
    message_record = next(
        item
        for item in database["messages"].documents
        if item.get("orchestration_id") == orchestration_id
    )
    assert message_record["delivery_status"] == "delivered"
    assert message_record["delivery_retry_count"] == 1
    assert len(transient.token_requests) == 2
    assert run["status"] == "completed"
    assert run["delivery_status"] == "delivered"

    failed_id = "run-delivery-permanent"
    database["orchestration_runs"].documents.append(
        {
            **run,
            "_id": ObjectId(),
            "orchestration_id": failed_id,
            "final_response": "A separate answer.",
        }
    )
    permanent = MockNexconnClient(
        failures=[NexconnAPIError("rejected", retryable=False)]
    )
    await AIMessageDeliveryService(database, settings, permanent).deliver_orchestration(
        failed_id
    )
    failed_message = next(
        item
        for item in database["messages"].documents
        if item.get("orchestration_id") == failed_id
    )
    assert failed_message["delivery_status"] == "failed"
    assert failed_message["delivery_retry_count"] == 0
    assert failed_message["delivery_error"] != "rejected"
    failed_run = next(
        item
        for item in database["orchestration_runs"].documents
        if item["orchestration_id"] == failed_id
    )
    assert failed_run["status"] == "completed"
    assert failed_run["delivery_status"] == "failed"


@pytest.mark.asyncio
async def test_sequential_tasks_receive_prior_results() -> None:
    database, _, _, agents, message = _database_with_message()
    provider = MockProvider(_plan(agents, mode="sequential"))
    processor = OrchestrationMessageProcessor(database, _settings(), provider)

    run = await processor.orchestrate_message(str(message["_id"]))

    assert run is not None and run["status"] == "completed"
    assert provider.max_active_calls == 1
    second_input = json.loads(provider.text_calls[1][1]["content"])
    assert second_input["prior_agent_results"][0]["response"] == "Agent response."


@pytest.mark.asyncio
async def test_invalid_coordinator_and_agent_failures_use_safe_fallback() -> None:
    database, _, _, _, message = _database_with_message()
    provider = MockProvider(coordinator_error=True, agent_error=True)
    processor = OrchestrationMessageProcessor(database, _settings(), provider)

    run = await processor.orchestrate_message(str(message["_id"]))

    assert run is not None and run["status"] == "completed"
    assert run["coordinator_plan"]["selected_agent_ids"]
    assert all(result["status"] == "failed" for result in run["agent_results"])
    assert "couldn't complete" in run["final_response"]
    assert run["errors"][0] == "Coordinator planning used a safe fallback."


@pytest.mark.asyncio
async def test_workflow_timeout_is_persisted_as_failure() -> None:
    database, _, _, agents, message = _database_with_message(agent_count=1)

    class SlowProvider(MockProvider):
        async def text_output(self, **kwargs: Any) -> str:
            await asyncio.sleep(0.2)
            return "Too late"

    provider = SlowProvider(_plan(agents, mode="sequential"))
    settings = _settings().model_copy(update={"orchestration_timeout_seconds": 0.02})
    run = await OrchestrationMessageProcessor(
        database, settings, provider
    ).orchestrate_message(str(message["_id"]))

    assert run is not None
    assert run["status"] == "failed"
    assert run["errors"] == ["Orchestration failed (TimeoutError)."]
    assert message["ai_processing_status"] == "failed"


def test_llm_settings_are_validated_without_requiring_credentials() -> None:
    settings = _settings()
    assert settings.google_api_key == ""
    assert settings.gemini_api_key == ""
    assert settings.default_llm_model == "gemini-test"
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            default_llm_temperature=2,
        )


@pytest.mark.asyncio
async def test_no_agents_and_foreign_agent_ids_are_not_invoked() -> None:
    database, _, group, _, message = _database_with_message(agent_count=0)
    provider = MockProvider()
    no_agents = await OrchestrationMessageProcessor(
        database, _settings(), provider
    ).orchestrate_message(str(message["_id"]))
    assert no_agents is not None and no_agents["status"] == "completed"
    assert no_agents["final_response"] is None

    other_group = ObjectId()
    foreign_agent = _agent(other_group, "Foreign")
    database["agents"].documents.append(foreign_agent)
    second_message = _message(group, database["users"].documents[1], "Different")
    database["messages"].documents.append(second_message)
    provider.plan = CoordinatorPlan(
        requires_ai=True,
        selected_agent_ids=[str(foreign_agent["_id"])],
        tasks=[
            AgentTask(
                agent_id=str(foreign_agent["_id"]),
                instruction="Try selecting a foreign agent.",
            )
        ],
    )

    run = await OrchestrationMessageProcessor(
        database, _settings(), provider
    ).orchestrate_message(str(second_message["_id"]))
    assert run is not None and run["status"] == "completed"
    assert run["selected_agent_ids"] == []
    assert provider.text_calls == []


@pytest.mark.asyncio
async def test_manual_processing_endpoint_checks_membership_and_returns_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = [make_user("alice"), make_user("bob"), make_user("outsider")]
    group = _group(users)
    group["nexconn_channel_id"] = "nexconn-team"
    database = FakeDatabase(users, group)
    agent = _agent(group["_id"], "Research Agent")
    database["agents"].documents.append(agent)
    plain_message = _message(group, users[1], "Please summarize this")
    message = _message(group, users[1], "@Research Agent summarize this")
    database["messages"].documents.extend([plain_message, message])
    settings = _settings()
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    provider = MockProvider(_plan([agent]))
    import app.api.v1.endpoints.messages as message_endpoints

    monkeypatch.setattr(
        message_endpoints,
        "OrchestrationMessageProcessor",
        lambda db, configured, **kwargs: OrchestrationMessageProcessor(
            db, configured, provider
        ),
    )
    app = main.create_app()
    app.dependency_overrides[get_database] = lambda: database
    tokens = {
        user["username"]: create_access_token(str(user["_id"]), settings)[0]
        for user in users
    }

    async with _client(app) as client:
        plain_rejected = await client.post(
            f"/api/v1/groups/{group['_id']}/messages/{plain_message['_id']}/ai-process",
            headers=_auth(tokens["bob"]),
        )
        queued = await client.post(
            f"/api/v1/groups/{group['_id']}/messages/{message['_id']}/ai-process",
            headers=_auth(tokens["bob"]),
        )
        outsider = await client.get(
            f"/api/v1/groups/{group['_id']}/orchestrations/"
            f"{queued.json()['orchestration_id']}",
            headers=_auth(tokens["outsider"]),
        )
        status_response = await client.get(
            f"/api/v1/groups/{group['_id']}/orchestrations/"
            f"{queued.json()['orchestration_id']}",
            headers=_auth(tokens["bob"]),
        )
        delivery_response = await client.post(
            f"/api/v1/groups/{group['_id']}/orchestrations/"
            f"{queued.json()['orchestration_id']}/deliver",
            headers=_auth(tokens["bob"]),
        )
        delivery_status = await client.get(
            f"/api/v1/groups/{group['_id']}/orchestrations/"
            f"{queued.json()['orchestration_id']}/delivery-status",
            headers=_auth(tokens["bob"]),
        )
        outsider_delivery_status = await client.get(
            f"/api/v1/groups/{group['_id']}/orchestrations/"
            f"{queued.json()['orchestration_id']}/delivery-status",
            headers=_auth(tokens["outsider"]),
        )
        duplicate = await client.post(
            f"/api/v1/groups/{group['_id']}/messages/{message['_id']}/ai-process",
            headers=_auth(tokens["bob"]),
        )
        mismatch_message = _message(
            {**group, "_id": ObjectId()},
            users[1],
            "Belongs elsewhere",
        )
        database["messages"].documents.append(mismatch_message)
        mismatch = await client.post(
            f"/api/v1/groups/{group['_id']}/messages/"
            f"{mismatch_message['_id']}/ai-process",
            headers=_auth(tokens["bob"]),
        )

    assert plain_rejected.status_code == 422
    assert queued.status_code == 202
    assert outsider.status_code == 403
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert status_response.json()["final_response"] == "Agent response."
    assert delivery_response.status_code == 202
    assert delivery_response.json()["delivery_status"] == "pending"
    assert delivery_status.status_code == 200
    assert delivery_status.json()["delivery_status"] == "failed"
    assert delivery_status.json()["message_id"]
    assert delivery_status.json()["error_message"]
    assert outsider_delivery_status.status_code == 403
    assert duplicate.status_code == 409
    assert mismatch.status_code == 404


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
