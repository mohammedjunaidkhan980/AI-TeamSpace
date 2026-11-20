from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.services.orchestration.nodes.routing import route_after_coordinator
from app.services.orchestration.state import OrchestrationState

OrchestrationNode = Callable[[OrchestrationState], Any]


def build_orchestration_graph(
    *,
    coordinator: OrchestrationNode,
    executor: OrchestrationNode,
    synthesizer: OrchestrationNode,
) -> Any:
    workflow = StateGraph(OrchestrationState)
    workflow.add_node("coordinator", coordinator)
    workflow.add_node("execute_agents", executor)
    workflow.add_node("synthesize", synthesizer)
    workflow.add_node("finish_without_ai", lambda _state: {"final_response": None})
    workflow.add_edge(START, "coordinator")
    workflow.add_conditional_edges(
        "coordinator",
        route_after_coordinator,
        {
            "execute_agents": "execute_agents",
            "finish_without_ai": "finish_without_ai",
        },
    )
    workflow.add_edge("execute_agents", "synthesize")
    workflow.add_edge("synthesize", END)
    workflow.add_edge("finish_without_ai", END)
    return workflow.compile()
