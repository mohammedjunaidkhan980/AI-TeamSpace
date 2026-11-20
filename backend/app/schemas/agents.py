from datetime import datetime
import re
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

MODEL_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
AGENT_NAME_PATTERN = r"^[^\x00-\x1f\x7f]{1,80}$"
CAPABILITY_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class AgentConfiguration(BaseModel):
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    top_p: float | None = Field(default=None, ge=0, le=1)
    response_format: str | None = Field(default=None, pattern=r"^(text|json)$")

    model_config = ConfigDict(extra="forbid")


class AgentTemplate(BaseModel):
    template_id: str
    name: str
    role: str
    description: str
    capabilities: list[str]
    system_prompt: str
    model: str
    temperature: float


class CreateGroupAgent(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    custom_system_prompt: str | None = Field(
        default=None, min_length=1, max_length=12000
    )
    model: str | None = Field(default=None, pattern=MODEL_NAME_PATTERN)
    temperature: float | None = Field(default=None, ge=0, le=1)
    capabilities: list[str] | None = Field(default=None, min_length=1, max_length=20)
    configuration: AgentConfiguration | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Agent name must contain printable characters")
        return value

    @field_validator("model")
    @classmethod
    def reject_null_model(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Model cannot be null")
        return value

    @field_validator("temperature", mode="before")
    @classmethod
    def reject_boolean_temperature(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("Temperature must be a number between 0 and 1")
        return value

    @field_validator("custom_system_prompt")
    @classmethod
    def validate_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("System prompt cannot be blank")
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(
        cls, values: list[str] | None
    ) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip().lower() for value in values]
        if any(not value or not re.fullmatch(CAPABILITY_PATTERN, value) for value in normalized):
            raise ValueError("Capabilities must be lowercase identifier strings")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Capabilities must not contain duplicates")
        return normalized


class UpdateGroupAgent(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=12000)
    model: str | None = Field(default=None, pattern=MODEL_NAME_PATTERN)
    temperature: float | None = Field(default=None, ge=0, le=1)
    capabilities: list[str] | None = Field(default=None, min_length=1, max_length=20)
    configuration: AgentConfiguration | None = None
    enabled: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Agent name cannot be null")
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Agent name must contain printable characters")
        return value

    @field_validator("*", mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Agent fields cannot be null")
        return value

    @field_validator("temperature", mode="before")
    @classmethod
    def reject_boolean_temperature(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("Temperature must be a number between 0 and 1")
        return value

    @field_validator("description", "system_prompt")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Text fields cannot be null")
        value = value.strip()
        if not value:
            raise ValueError("Text fields cannot be blank")
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(
        cls, values: list[str] | None
    ) -> list[str] | None:
        if values is None:
            raise ValueError("Capabilities cannot be null")
        normalized = [value.strip().lower() for value in values]
        if any(
            not value or not re.fullmatch(CAPABILITY_PATTERN, value)
            for value in normalized
        ):
            raise ValueError("Capabilities must be lowercase identifier strings")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Capabilities must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def require_changes(self) -> "UpdateGroupAgent":
        if not self.model_fields_set:
            raise ValueError("At least one agent field must be provided")
        return self


class AgentStatusUpdate(BaseModel):
    enabled: bool

    model_config = ConfigDict(extra="forbid")


class GroupAgentResponse(BaseModel):
    agent_id: str
    group_id: str
    template_id: str
    name: str
    description: str
    system_prompt: str
    model: str
    temperature: float
    capabilities: list[str]
    configuration: dict[str, Any]
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class GroupAgentListResponse(BaseModel):
    items: list[GroupAgentResponse]
