import secrets
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


def _default_local_origins() -> list[str]:
    return [
        "http://localhost",
        "http://localhost:5173",
        "http://127.0.0.1",
        "http://127.0.0.1:5173",
        "https://localhost",
        "https://localhost:5173",
        "https://127.0.0.1",
        "https://127.0.0.1:5173",
    ]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Resolve the repository-level .env file from this module location.
        env_file=str(Path(__file__).resolve().parents[3] / ".env"),
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        origins = [
            str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS
        ] + [self.FRONTEND_HOST] + _default_local_origins()
        return list(dict.fromkeys(origins))

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""
    SILICONFLOW_API_KEY: str | None = None
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    SILICONFLOW_CHAT_MODEL: str = "Qwen/Qwen2.5-72B-Instruct-128K"
    SILICONFLOW_EMBEDDING_MODEL: str = "Qwen/Qwen3-Embedding-8B"
    SILICONFLOW_RERANKER_MODEL: str = "Qwen/Qwen3-Reranker-8B"
    SILICONFLOW_TTS_MODEL: str = "fnlp/MOSS-TTSD-v0.5"
    SILICONFLOW_TTS_VOICE: str = "fnlp/MOSS-TTSD-v0.5:anna"
    MILVUS_URI: str | None = None
    MILVUS_TOKEN: str | None = None
    MILVUS_DB_NAME: str = "gwy_pilot"
    MILVUS_COLLECTION_POLICY: str = "gwy_policy_chunks"
    MILVUS_COLLECTION_POLICY_RAG: str = "gwy_policy_rag_chunks"
    EMBEDDING_DIM: int = 1024
    REDIS_URL: str | None = None
    RAG_CACHE_TTL_SECONDS: int = 3600
    MEMORY_SIDE_QUERY_ENABLED: bool = True
    MEMORY_SIDE_QUERY_MODEL: str | None = None
    MEMORY_SIDE_QUERY_MAX_CARDS: int = 200
    MEMORY_SIDE_QUERY_MAX_SELECTED: int = 5
    MEMORY_SIDE_QUERY_MAX_ITEM_CHARS: int = 4096
    MEMORY_SIDE_QUERY_MAX_CONTEXT_CHARS: int = 60_000
    MEMORY_SIDE_QUERY_MAX_CATALOG_CHARS: int = 60_000
    MEMORY_SIDE_QUERY_TIMEOUT_SECONDS: float = 3.0
    # Short-term chat memory window measured in turns; override via env when needed.
    RAG_MEMORY_TURNS: int = 12
    # Working-memory summary should stay concise and focused on the latest dialogue state.
    WORKING_MEMORY_SUMMARY_MAX_CHARS: int = 200
    WORKING_MEMORY_OPEN_TOPICS_LIMIT: int = 5
    MILVUS_COLLECTION_POLICY_DOCUMENTS: str = "gwy_policy_documents"
    MILVUS_COLLECTION_EXAM_GUIDES: str = "gwy_exam_guides"
    MILVUS_COLLECTION_MAJOR_CATALOGS: str = "gwy_major_catalogs"
    WEB_SEARCH_ENABLED: bool = True
    SEARXNG_BASE_URL: str = "http://localhost:8080"
    SEARXNG_TIMEOUT_SECONDS: float = 8.0
    SEARXNG_TOP_K: int = 5
    SEARXNG_LANGUAGE: str = "zh-CN"
    WEB_MCP_URL: AnyUrl | None = None
    DB_MCP_URL: AnyUrl | None = None
    FETCH_MCP_URL: AnyUrl | None = None
    PLAYWRIGHT_MCP_URL: AnyUrl | None = None
    WEB_FETCH_TIMEOUT_SECONDS: float = 10.0
    WEB_FETCH_MIN_TEXT_LENGTH: int = 400
    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str | None = None
    LLM_MODEL: str | None = None
    CHAT_API_KEY: str | None = None
    CHAT_BASE_URL: str | None = "https://a6api.com/v1"
    CHAT_MODEL: str | None = "gpt-5.4-mini"
    TOOL_CHAT_API_KEY: str | None = None
    TOOL_CHAT_BASE_URL: str | None = None
    TOOL_CHAT_MODEL: str | None = "gpt-5.4-mini"
    FALLBACK_MODEL_ID: str | None = None
    FEISHU_WEBHOOK_URL: AnyUrl | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        if not self.SILICONFLOW_API_KEY and self.LLM_API_KEY:
            self.SILICONFLOW_API_KEY = self.LLM_API_KEY
        if not self.LLM_BASE_URL and self.SILICONFLOW_BASE_URL:
            self.LLM_BASE_URL = self.SILICONFLOW_BASE_URL
        if not self.LLM_MODEL and self.SILICONFLOW_CHAT_MODEL:
            self.LLM_MODEL = self.SILICONFLOW_CHAT_MODEL
        if not self.CHAT_API_KEY and self.LLM_API_KEY:
            self.CHAT_API_KEY = self.LLM_API_KEY
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
