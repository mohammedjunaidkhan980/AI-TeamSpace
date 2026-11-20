import asyncio
import re
from collections.abc import Sequence
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.core.config import Settings

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)
GEMINI_MODEL_VERSION_PATTERN = re.compile(
    r"^(?:models/)?gemini-(\d+)\.(\d+)"
)


class ModelProvider(Protocol):
    async def structured_output(
        self,
        *,
        model_name: str,
        temperature: float,
        schema: type[StructuredModel],
        messages: Sequence[dict[str, str]],
    ) -> StructuredModel: ...

    async def text_output(
        self,
        *,
        model_name: str,
        temperature: float,
        messages: Sequence[dict[str, str]],
        configuration: dict[str, Any] | None = None,
    ) -> str: ...


class GeminiModelProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _model(
        self,
        model_name: str,
        temperature: float,
        configuration: dict[str, Any] | None = None,
    ) -> Any:
        api_key = self._settings.google_api_key or self._settings.gemini_api_key
        if not api_key:
            raise RuntimeError("Google Gemini API credentials are not configured")
        from langchain_google_genai import ChatGoogleGenerativeAI

        model_options: dict[str, Any] = {}
        version_match = GEMINI_MODEL_VERSION_PATTERN.match(model_name)
        uses_new_sampling_config = bool(
            version_match
            and (
                int(version_match.group(1)) > 3
                or (
                    int(version_match.group(1)) == 3
                    and int(version_match.group(2)) >= 6
                )
            )
        )
        if configuration:
            if configuration.get("max_tokens") is not None:
                model_options["max_output_tokens"] = configuration["max_tokens"]
            if (
                not uses_new_sampling_config
                and configuration.get("top_p") is not None
            ):
                model_options["top_p"] = configuration["top_p"]
            if configuration.get("response_format") == "json":
                model_options["response_mime_type"] = "application/json"
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=None if uses_new_sampling_config else temperature,
            google_api_key=api_key,
            timeout=self._settings.orchestration_timeout_seconds,
            max_retries=0,
            **model_options,
        )

    @staticmethod
    def _langchain_messages(messages: Sequence[dict[str, str]]) -> list[Any]:
        from langchain_core.messages import HumanMessage, SystemMessage

        message_types = {"system": SystemMessage, "human": HumanMessage}
        return [
            message_types[item["role"]](content=item["content"])
            for item in messages
        ]

    async def _invoke(self, runnable: Any, messages: Sequence[dict[str, str]]) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return await asyncio.wait_for(
                    runnable.ainvoke(self._langchain_messages(messages)),
                    timeout=self._settings.orchestration_timeout_seconds,
                )
            except Exception as exc:
                last_error = exc
                retryable = isinstance(exc, TimeoutError) or type(exc).__name__ in {
                    "ResourceExhausted",
                    "RateLimitError",
                    "ServiceUnavailable",
                    "InternalServerError",
                }
                if not retryable or attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (2**attempt))
        if last_error is None:
            raise RuntimeError("LLM invocation did not produce a result")
        raise last_error

    async def structured_output(
        self,
        *,
        model_name: str,
        temperature: float,
        schema: type[StructuredModel],
        messages: Sequence[dict[str, str]],
    ) -> StructuredModel:
        import json
        # First try native structured output (function calling)
        try:
            model = self._model(model_name, temperature).with_structured_output(schema)
            result = await self._invoke(model, messages)
            if isinstance(result, schema):
                return result
            return schema.model_validate(result)
        except Exception:
            pass
        # Fallback: ask for JSON text and parse it
        json_messages = list(messages) + [
            {
                "role": "human",
                "content": (
                    f"Respond with a single valid JSON object matching this schema and nothing else.\n"
                    f"Schema fields: {list(schema.model_fields.keys())}"
                ),
            }
        ]
        model_plain = self._model(
            model_name,
            temperature,
            {"response_format": "json"},
        )
        result = await self._invoke(model_plain, json_messages)
        content = result.content
        if isinstance(content, list):
            content = "\n".join(
                item["text"]
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            )
        # Strip markdown code fences if present
        content = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content.strip())
        return schema.model_validate(json.loads(content))

    async def text_output(
        self,
        *,
        model_name: str,
        temperature: float,
        messages: Sequence[dict[str, str]],
        configuration: dict[str, Any] | None = None,
    ) -> str:
        result = await self._invoke(
            self._model(model_name, temperature, configuration),
            messages,
        )
        content = result.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "\n".join(
                item["text"]
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ).strip()
        raise TypeError("Gemini returned an unsupported text response format")
