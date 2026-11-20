from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.documents import DocumentCitation

OrchestrationStatus = Literal["queued", "processing", "completed", "failed"]
DeliveryStatus = Literal["pending", "sending", "delivered", "failed"]


class AgentTask(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    instruction: str = Field(min_length=1, max_length=4000)
    depends_on: list[str] = Field(default_factory=list, max_length=32)

    model_config = ConfigDict(extra="forbid")


class CoordinatorPlan(BaseModel):
    requires_ai: bool
    reasoning: str = Field(default="", max_length=4000)
    selected_agent_ids: list[str] = Field(default_factory=list, max_length=32)
    tasks: list[AgentTask] = Field(default_factory=list, max_length=32)
    execution_mode: Literal["parallel", "sequential"] = "parallel"

    model_config = ConfigDict(extra="forbid")


class AgentExecutionResult(BaseModel):
    agent_id: str
    agent_name: str
    task: str
    response: str | None = None
    status: Literal["completed", "failed"]
    execution_time: float
    error: str | None = None


class OrchestrationAccepted(BaseModel):
    orchestration_id: str
    message_id: str
    status: OrchestrationStatus


class OrchestrationRunResponse(BaseModel):
    orchestration_id: str
    message_id: str
    group_id: str
    status: OrchestrationStatus
    coordinator_plan: dict[str, Any] | None = None
    selected_agent_ids: list[str] = Field(default_factory=list)
    agent_results: list[AgentExecutionResult] = Field(default_factory=list)
    final_response: str | None = None
    errors: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None
    execution_time: float | None = None
    delivery_status: DeliveryStatus | None = None
    citations: list[DocumentCitation] = Field(default_factory=list)


class AIMessageDeliveryAccepted(BaseModel):
    orchestration_id: str
    delivery_status: DeliveryStatus
    message_id: str | None = None


class AIMessageDeliveryStatus(BaseModel):
    orchestration_id: str
    delivery_status: DeliveryStatus
    message_id: str | None = None
    sender_name: str | None = None
    created_at: datetime | None = None
    delivered_at: datetime | None = None
    retry_count: int = 0
    error_message: str | None = None
