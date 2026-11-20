import asyncio
import json
import time
from typing import Any

from app.core.config import Settings
from app.schemas.orchestration import AgentExecutionResult, AgentTask
from app.services.orchestration.prompts import AGENT_SYSTEM_GUARD
from app.services.orchestration.provider import ModelProvider
from app.services.orchestration.state import OrchestrationState

DOCUMENT_GROUNDING_INSTRUCTION = (
    "Use only the supplied group document excerpts as evidence for document-specific "
    "claims. If the user asks about group documents and no relevant excerpts are "
    "provided, clearly state that the available group documents do not contain "
    "sufficient information. Do not invent citations."
)


def _agent_prompt(
    state: OrchestrationState,
    agent: dict[str, Any],
    task: AgentTask,
    prior_results: list[dict[str, Any]],
) -> list[dict[str, str]]:
    input_content = {
        "original_user_request": state["original_message"],
        "task": task.instruction,
        "group_context": state["metadata"],
        "conversation_history": state["conversation_history"],
        "relevant_group_document_excerpts": state["document_context"],
        "prior_agent_results": [
            {
                "agent_name": result["agent_name"],
                "response": result["response"],
            }
            for result in prior_results
            if result["status"] == "completed"
            and result["agent_id"] in task.depends_on
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                f"{agent['system_prompt']}\n\n{AGENT_SYSTEM_GUARD}\n\n"
                f"{DOCUMENT_GROUNDING_INSTRUCTION}"
            ),
        },
        {
            "role": "human",
            "content": json.dumps(input_content, ensure_ascii=False),
        },
    ]


async def _execute_one(
    state: OrchestrationState,
    *,
    agent: dict[str, Any],
    task: AgentTask,
    provider: ModelProvider,
    settings: Settings,
    semaphore: asyncio.Semaphore,
    prior_results: list[dict[str, Any]],
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        async with semaphore:
            response = await provider.text_output(
                model_name=agent.get("model") or settings.default_llm_model,
                temperature=agent.get("temperature", settings.default_llm_temperature),
                messages=_agent_prompt(state, agent, task, prior_results),
                configuration=agent.get("configuration", {}),
            )
        if not response:
            raise ValueError("Empty agent response")
        result = AgentExecutionResult(
            agent_id=agent["agent_id"],
            agent_name=agent["name"],
            task=task.instruction,
            response=response,
            status="completed",
            execution_time=time.monotonic() - started,
        )
    except Exception as exc:
        result = AgentExecutionResult(
            agent_id=agent["agent_id"],
            agent_name=agent["name"],
            task=task.instruction,
            status="failed",
            execution_time=time.monotonic() - started,
            error=f"Agent execution failed ({type(exc).__name__}).",
        )
    return result.model_dump()


async def execute_agents(
    state: OrchestrationState,
    *,
    provider: ModelProvider,
    settings: Settings,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    by_id = {agent["agent_id"]: agent for agent in state["selected_agents"]}
    task_by_id = {task.agent_id: task for task in state["agent_tasks"]}

    if state["coordinator_plan"].get("execution_mode") == "sequential":
        results: list[dict[str, Any]] = []
        for agent_id in state["coordinator_plan"]["selected_agent_ids"]:
            agent = by_id.get(agent_id)
            task = task_by_id.get(agent_id)
            if agent is None or task is None:
                continue
            results.append(
                await _execute_one(
                    state,
                    agent=agent,
                    task=task,
                    provider=provider,
                    settings=settings,
                    semaphore=semaphore,
                    prior_results=results,
                )
            )
    else:
        selected = [
            (by_id[agent_id], task_by_id[agent_id])
            for agent_id in state["coordinator_plan"]["selected_agent_ids"]
            if agent_id in by_id and agent_id in task_by_id
        ]
        results = list(
            await asyncio.gather(
                *(
                    _execute_one(
                        state,
                        agent=agent,
                        task=task,
                        provider=provider,
                        settings=settings,
                        semaphore=semaphore,
                        prior_results=[],
                    )
                    for agent, task in selected
                )
            )
        )

    failures = [
        result["error"] for result in results if result["status"] == "failed"
    ]
    return {
        "agent_responses": results,
        "errors": [*state["errors"], *failures],
    }
