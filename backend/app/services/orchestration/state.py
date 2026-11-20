from typing import Any, TypedDict

from app.schemas.orchestration import AgentTask


class OrchestrationState(TypedDict):
    message_id: str
    group_id: str
    user_id: str
    original_message: str
    conversation_history: list[dict[str, str]]
    available_agents: list[dict[str, Any]]
    selected_agents: list[dict[str, Any]]
    coordinator_plan: dict[str, Any]
    agent_tasks: list[AgentTask]
    agent_responses: list[dict[str, Any]]
    errors: list[str]
    final_response: str | None
    processing_status: str
    metadata: dict[str, Any]
    document_context: list[dict[str, Any]]
