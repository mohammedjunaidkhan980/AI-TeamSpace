import json
import logging
from typing import Any

from app.core.config import Settings
from app.services.orchestration.prompts import SYNTHESIZER_SYSTEM_PROMPT
from app.services.orchestration.provider import ModelProvider
from app.services.orchestration.state import OrchestrationState

logger = logging.getLogger(__name__)


async def synthesize(
    state: OrchestrationState,
    *,
    provider: ModelProvider,
    settings: Settings,
) -> dict[str, Any]:
    successful = [
        result for result in state["agent_responses"] if result["status"] == "completed"
    ]
    if not successful:
        return {
            "final_response": (
                "I couldn't complete this request because the assigned AI agents "
                "were unavailable. Please try again later."
            ),
            "processing_status": "completed",
        }
    if len(successful) == 1:
        return {
            "final_response": successful[0]["response"],
            "processing_status": "completed",
        }

    context = {
        "original_user_request": state["original_message"],
        "coordinator_plan": state["coordinator_plan"],
        "relevant_group_document_excerpts": state["document_context"],
        "successful_agent_responses": [
            {
                "agent_name": result["agent_name"],
                "task": result["task"],
                "response": result["response"],
            }
            for result in successful
        ],
    }
    try:
        final_response = await provider.text_output(
            model_name=settings.default_llm_model,
            temperature=settings.default_llm_temperature,
            messages=[
                {"role": "system", "content": SYNTHESIZER_SYSTEM_PROMPT},
                {
                    "role": "human",
                    "content": json.dumps(context, ensure_ascii=False),
                },
            ],
        )
        if not final_response:
            raise ValueError("Empty synthesis response")
    except Exception as exc:
        logger.warning(
            "Response synthesis failed; using successful agent responses",
            extra={"message_id": state["message_id"], "error_type": type(exc).__name__},
        )
        final_response = "\n\n".join(
            f"**{result['agent_name']}**\n{result['response']}"
            for result in successful
        )
        return {
            "final_response": final_response,
            "processing_status": "completed",
            "errors": [
                *state["errors"],
                f"Synthesis failed ({type(exc).__name__}); agent responses were returned directly.",
            ],
        }
    return {"final_response": final_response, "processing_status": "completed"}
