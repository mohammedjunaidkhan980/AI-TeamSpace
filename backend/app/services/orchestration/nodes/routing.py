from typing import Literal

from app.services.orchestration.state import OrchestrationState


def route_after_coordinator(
    state: OrchestrationState,
) -> Literal["execute_agents", "finish_without_ai"]:
    if state["processing_status"] == "processing" and state["selected_agents"]:
        return "execute_agents"
    return "finish_without_ai"
