import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.core.config import Settings
from app.repositories.agents import list_enabled_group_agents
from app.repositories.groups import get_group
from app.repositories.messages import (
    get_group_message_history,
    get_message,
)
from app.repositories.orchestrations import (
    claim_orchestration_run,
    create_orchestration_run,
    get_orchestration_run,
    update_orchestration_run,
)
from app.schemas.agents import AgentConfiguration
from app.services.orchestration.graph import build_orchestration_graph
from app.services.orchestration.nodes.agent_executor import execute_agents
from app.services.orchestration.nodes.coordinator import coordinate
from app.services.orchestration.nodes.synthesizer import synthesize
from app.services.orchestration.provider import GeminiModelProvider, ModelProvider
from app.services.orchestration.state import OrchestrationState
from app.services.messaging.ai_message_delivery import AIMessageDeliveryService
from app.services.document_retrieval import DocumentRetrievalService
from app.services.agent_templates import AGENT_TEMPLATES
from app.services.nexconn import NexconnClient

logger = logging.getLogger(__name__)
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
GROUP_CONTEXT_KEYS = {"language", "timezone", "response_style"}
def resolve_agent_mentions(
    content: str, agents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return agents explicitly @mentioned in the message, preserving order."""
    name_map = {
        agent["name"].strip().lower(): agent
        for agent in agents
        if isinstance(agent.get("name"), str) and agent["name"].strip()
    }
    if not name_map:
        return []
    names = sorted(name_map, key=len, reverse=True)
    mention_pattern = re.compile(
        r"@(?P<name>" + "|".join(re.escape(name) for name in names) + r")(?=$|[^\w])",
        re.IGNORECASE,
    )
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for match in mention_pattern.finditer(content):
        key = match.group("name").strip().lower()
        if key in name_map and key not in seen:
            seen.add(key)
            result.append(name_map[key])
    return result


def _mention_plan(agents: list[dict[str, Any]]) -> dict[str, Any]:
    from app.schemas.orchestration import CoordinatorPlan, AgentTask
    plan = CoordinatorPlan(
        requires_ai=True,
        reasoning="Agents were directly mentioned via @ in the message.",
        selected_agent_ids=[a["agent_id"] for a in agents],
        tasks=[
            AgentTask(
                agent_id=a["agent_id"],
                instruction="Respond to the user's request using your configured role.",
            )
            for a in agents
        ],
        execution_mode="parallel",
    )
    return plan.model_dump()


def _mention_tasks(agents: list[dict[str, Any]]) -> list[Any]:
    from app.schemas.orchestration import AgentTask
    return [
        AgentTask(
            agent_id=a["agent_id"],
            instruction="Respond to the user's request using your configured role.",
        )
        for a in agents
    ]


class OrchestrationMessageProcessor:
    def __init__(
        self,
        database: Database[dict[str, Any]],
        settings: Settings,
        provider: ModelProvider | None = None,
        semaphore: asyncio.Semaphore | None = None,
        nexconn_client: NexconnClient | None = None,
    ) -> None:
        self._database = database
        self._settings = settings
        self._provider = provider or GeminiModelProvider(settings)
        self._semaphore = semaphore or asyncio.Semaphore(
            settings.max_parallel_agents
        )
        self._nexconn_client = nexconn_client
        self._graph = build_orchestration_graph(
            coordinator=self._coordinate,
            executor=self._execute_agents,
            synthesizer=self._synthesize,
        )

    async def process(self, message: dict[str, Any]) -> str | None:
        run = await self.orchestrate_message(str(message["_id"]))
        if run is not None and run.get("status") == "failed":
            return "failed"
        if run is not None and run.get("status") in {"queued", "processing"}:
            return "processing"
        if (
            run is not None
            and run.get("status") == "completed"
            and not run.get("selected_agent_ids")
        ):
            return "not_required"
        return None

    async def orchestrate_message(self, message_id: str) -> dict[str, Any] | None:
        if not ObjectId.is_valid(message_id):
            return None
        message = await get_message(self._database, message_id)
        if (
            message is None
            or message.get("is_deleted")
            or message.get("sender_type") != "user"
        ):
            return None
        run, created = await create_orchestration_run(
            self._database,
            message_id=message["_id"],
            group_id=message["group_id"],
        )
        if not created:
            if run["status"] == "queued":
                return await self.run_reserved(
                    str(run["orchestration_id"]),
                    message_id,
                )
            return run
        return await self.run_reserved(str(run["orchestration_id"]), message_id)

    async def run_reserved(
        self,
        orchestration_id: str,
        message_id: str,
    ) -> dict[str, Any] | None:
        run = await get_orchestration_run(
            self._database,
            orchestration_id=orchestration_id,
        )
        if run is None or run["status"] != "queued":
            return run

        started = time.monotonic()
        started_at = datetime.now(timezone.utc)
        claimed_run = await claim_orchestration_run(
            self._database,
            orchestration_id=orchestration_id,
            started_at=started_at,
        )
        if claimed_run is None:
            return await get_orchestration_run(
                self._database,
                orchestration_id=orchestration_id,
            )
        run = claimed_run
        try:
            await self._database["messages"].update_one(
                {"_id": run["message_id"], "is_deleted": False},
                {
                    "$set": {
                        "ai_processing_status": "processing",
                        "updated_at": started_at,
                    }
                },
            )
            await self._database["message_processing_events"].update_one(
                {"message_id": run["message_id"], "status": "pending"},
                {"$set": {"status": "processing", "updated_at": started_at}},
            )
            message = await get_message(self._database, message_id)
            if (
                message is None
                or message.get("is_deleted")
                or message.get("sender_type") != "user"
                or message["group_id"] != run["group_id"]
            ):
                raise ValueError("The source message is no longer eligible")

            group = await get_group(self._database, str(run["group_id"]))
            if group is None:
                raise ValueError("The source group no longer exists")
            agents = await list_enabled_group_agents(
                self._database,
                run["group_id"],
            )
            agent_context = [self._agent_context(agent) for agent in agents]
            mentioned = resolve_agent_mentions(message["content"], agent_context)
            history, _ = await get_group_message_history(
                self._database,
                group_id=run["group_id"],
                limit=self._settings.orchestration_history_limit,
                before=None,
            )
            try:
                document_context = await DocumentRetrievalService(
                    self._settings,
                    self._database,
                ).retrieve(
                    group_id=str(run["group_id"]),
                    query=message["content"],
                )
            except Exception as retrieval_error:
                logger.warning(
                    "Group document retrieval failed",
                    extra={
                        "group_id": str(run["group_id"]),
                        "error_type": type(retrieval_error).__name__,
                    },
                )
                document_context = []
                retrieval_errors = ["Group document retrieval was unavailable."]
            else:
                retrieval_errors = []
            state: OrchestrationState = {
                "message_id": message_id,
                "group_id": str(run["group_id"]),
                "user_id": str(message["sender_id"]) if message.get("sender_id") else "",
                "original_message": message["content"],
                "conversation_history": [
                    {
                        "sender": item.get("sender_name", "Unknown")[:120],
                        "type": item.get("sender_type", "system"),
                        "content": item.get("content", "")[:4000],
                    }
                    for item in history
                ],
                "available_agents": agent_context,
                "selected_agents": mentioned,
                "coordinator_plan": _mention_plan(mentioned) if mentioned else {},
                "agent_tasks": _mention_tasks(mentioned) if mentioned else [],
                "agent_responses": [],
                "errors": retrieval_errors,
                "final_response": None,
                "processing_status": "processing",
                "metadata": {
                    "group_name": group.get("name", ""),
                    "group_settings": {
                        key: value
                        for key, value in group.get("settings", {}).items()
                        if key in GROUP_CONTEXT_KEYS and isinstance(value, str)
                    },
                },
                "document_context": document_context,
            }
            result = await asyncio.wait_for(
                self._graph.ainvoke(state),
                timeout=self._settings.orchestration_timeout_seconds,
            )
            final_response = result.get("final_response")
            selected_ids = result["coordinator_plan"].get(
                "selected_agent_ids", []
            )
            completed_at = datetime.now(timezone.utc)
            changes = {
                "status": "completed",
                "coordinator_plan": result.get("coordinator_plan"),
                "selected_agent_ids": selected_ids,
                "agent_results": result.get("agent_responses", []),
                "final_response": final_response,
                "errors": result.get("errors", []),
                "completed_at": completed_at,
                "execution_time": time.monotonic() - started,
                "delivery_status": (
                    "pending"
                    if isinstance(final_response, str) and final_response.strip()
                    else "failed"
                ),
                "citations": result.get("document_context", []),
            }
            await update_orchestration_run(
                self._database,
                orchestration_id=orchestration_id,
                changes=changes,
            )
            await self._database["message_processing_events"].update_one(
                {"message_id": message["_id"]},
                {
                    "$set": {
                        "status": "completed",
                        "updated_at": completed_at,
                    }
                },
            )
            await self._database["messages"].update_one(
                {"_id": message["_id"], "is_deleted": False},
                {
                    "$set": {
                        "ai_processing_status": (
                            "completed" if selected_ids else "not_required"
                        ),
                        "updated_at": completed_at,
                    }
                },
            )
            if isinstance(final_response, str) and final_response.strip():
                try:
                    await AIMessageDeliveryService(
                        self._database,
                        self._settings,
                        self._nexconn_client,
                    ).deliver_orchestration(orchestration_id)
                except Exception as delivery_error:
                    logger.exception(
                        "AI message delivery failed independently of orchestration",
                        extra={
                            "orchestration_id": orchestration_id,
                            "error_type": type(delivery_error).__name__,
                        },
                    )
            return await get_orchestration_run(
                self._database,
                orchestration_id=orchestration_id,
            )
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            error = f"Orchestration failed ({type(exc).__name__})."
            logger.exception(
                "Message orchestration failed",
                extra={
                    "message_id": message_id,
                    "orchestration_id": orchestration_id,
                },
            )
            await update_orchestration_run(
                self._database,
                orchestration_id=orchestration_id,
                changes={
                    "status": "failed",
                    "errors": [error],
                    "completed_at": finished_at,
                    "execution_time": time.monotonic() - started,
                },
            )
            await self._database["message_processing_events"].update_one(
                {"message_id": run["message_id"]},
                {"$set": {"status": "failed", "updated_at": finished_at}},
            )
            if ObjectId.is_valid(message_id):
                await self._database["messages"].update_one(
                    {"_id": ObjectId(message_id), "is_deleted": False},
                    {
                        "$set": {
                            "ai_processing_status": "failed",
                            "updated_at": finished_at,
                        }
                    },
                )
            return await get_orchestration_run(
                self._database,
                orchestration_id=orchestration_id,
            )

    def _agent_context(self, agent: dict[str, Any]) -> dict[str, Any]:
        model_name = agent.get("model", "")
        is_builtin_template = any(
            template["template_id"] == agent.get("template_id")
            for template in AGENT_TEMPLATES
        )
        if is_builtin_template and model_name in {
            "gemini-2.0-flash",
            "gemini-2.5-flash",
            "gemini-3.8-flash",
        }:
            model_name = self._settings.default_llm_model
        if not isinstance(model_name, str) or not MODEL_NAME_PATTERN.fullmatch(
            model_name
        ):
            model_name = self._settings.default_llm_model
        try:
            configuration = AgentConfiguration.model_validate(
                agent.get("configuration", {})
            ).model_dump(exclude_none=True)
        except Exception:
            configuration = {}
            logger.warning(
                "Invalid stored agent configuration ignored",
                extra={"agent_id": str(agent["_id"])},
            )
        temperature = agent.get(
            "temperature",
            self._settings.default_llm_temperature,
        )
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not 0 <= temperature <= 1
        ):
            temperature = self._settings.default_llm_temperature
        return {
            "agent_id": str(agent["_id"]),
            "name": agent["name"],
            "description": agent.get("description", ""),
            "system_prompt": agent["system_prompt"],
            "model": model_name,
            "temperature": float(temperature),
            "capabilities": agent.get("capabilities", []),
            "configuration": configuration,
        }

    async def _coordinate(self, state: OrchestrationState) -> dict[str, Any]:
        return await coordinate(
            state,
            provider=self._provider,
            settings=self._settings,
        )

    async def _execute_agents(self, state: OrchestrationState) -> dict[str, Any]:
        return await execute_agents(
            state,
            provider=self._provider,
            settings=self._settings,
            semaphore=self._semaphore,
        )

    async def _synthesize(self, state: OrchestrationState) -> dict[str, Any]:
        return await synthesize(
            state,
            provider=self._provider,
            settings=self._settings,
        )
