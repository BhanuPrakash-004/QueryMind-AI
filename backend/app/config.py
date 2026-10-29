"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = ""
    database_admin_url: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    frontend_url: str = "http://localhost:5173"
    currency_code: str = ""

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key.strip())

    @property
    def groq_ready(self) -> bool:
        return self.groq_configured and bool(self.groq_model.strip())

    @property
    def groq_endpoint(self) -> str:
        return self.groq_base_url.strip() or "https://api.groq.com/openai/v1"

    @property
    def currency_configured(self) -> bool:
        return bool(self.currency_code.strip())

    def require_database_url(self) -> str:
        if not self.database_url.strip():
            raise RuntimeError(
                "DATABASE_URL is not configured. Add the restricted runtime "
                "PostgreSQL connection string to .env."
            )
        return self.database_url.strip()

    def require_database_admin_url(self) -> str:
        if not self.database_admin_url.strip():
            raise RuntimeError(
                "DATABASE_ADMIN_URL is not configured. Add the administrative "
                "PostgreSQL connection string to .env for schema setup and "
                "CSV ingestion."
            )
        return self.database_admin_url.strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
