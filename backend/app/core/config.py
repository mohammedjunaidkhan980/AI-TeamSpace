from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_database: str = "ai_teamspace"
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=60, gt=0)
    gemini_api_key: str = ""
    google_api_key: str = ""
    default_llm_model: str = Field(
        default="gemini-3.8-flash",
        validation_alias=AliasChoices("GEMINI_MODEL", "DEFAULT_LLM_MODEL"),
    )
    default_llm_temperature: float = Field(default=0.2, ge=0, le=1)
    orchestration_timeout_seconds: int = Field(default=120, ge=1, le=900)
    max_parallel_agents: int = Field(default=4, ge=1, le=32)
    orchestration_history_limit: int = Field(default=20, ge=1, le=100)
    ai_response_delivery_mode: str = "coordinator_only"
    nexconn_delivery_max_retries: int = Field(default=3, ge=0, le=10)
    nexconn_delivery_retry_base_seconds: float = Field(default=0.5, ge=0.05, le=30)
    nexconn_app_key: str = ""
    nexconn_app_secret: str = ""
    nexconn_api_base_url: str = ""
    nexconn_enabled: bool = False
    frontend_url: str = "http://localhost:5173"
    document_storage_path: str = "./data/documents"
    document_max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    document_max_text_characters: int = Field(default=2_000_000, ge=1000, le=10_000_000)
    document_chunk_size: int = Field(default=1200, ge=200, le=8000)
    document_chunk_overlap: int = Field(default=150, ge=0, le=1000)
    chroma_enabled: bool = False
    chroma_persist_directory: str = "./data/chroma"
    chroma_collection_name: str = "ai_teamspace_documents"
    gemini_embedding_model: str = "gemini-embedding-001"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def validate_nexconn_settings(self) -> "Settings":
        if self.document_chunk_overlap >= self.document_chunk_size:
            raise ValueError("DOCUMENT_CHUNK_OVERLAP must be smaller than DOCUMENT_CHUNK_SIZE")
        if not self.default_llm_model.strip():
            raise ValueError("GEMINI_MODEL cannot be blank")
        if self.ai_response_delivery_mode not in {
            "coordinator_only",
            "agents_and_coordinator",
        }:
            raise ValueError(
                "AI_RESPONSE_DELIVERY_MODE must be coordinator_only "
                "or agents_and_coordinator"
            )
        if not self.nexconn_enabled:
            return self

        missing = [
            name
            for name, value in (
                ("NEXCONN_APP_KEY", self.nexconn_app_key),
                ("NEXCONN_APP_SECRET", self.nexconn_app_secret),
                ("NEXCONN_API_BASE_URL", self.nexconn_api_base_url),
            )
            if not value.strip()
        ]
        if missing:
            raise ValueError(
                "Nexconn is enabled but required settings are missing: "
                + ", ".join(missing)
            )

        parsed_url = urlsplit(self.nexconn_api_base_url)
        if (
            parsed_url.scheme not in {"https", "http"}
            or not parsed_url.netloc
            or parsed_url.query
            or parsed_url.fragment
            or parsed_url.path not in {"", "/"}
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise ValueError(
                "NEXCONN_API_BASE_URL must be an absolute HTTP(S) origin"
            )
        if parsed_url.scheme != "https" and parsed_url.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("NEXCONN_API_BASE_URL must use HTTPS")

        self.nexconn_api_base_url = self.nexconn_api_base_url.rstrip("/")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
