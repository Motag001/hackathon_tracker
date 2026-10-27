"""Runtime configuration, read from environment variables.

Secrets are held as ``SecretStr`` so they never appear in reprs, logs or
tracebacks. Owner-adjustable values (threshold, budgets, profile) live in the
``settings`` table instead, so they can be changed from the dashboard.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_service_role_key: SecretStr | None = Field(
        default=None, alias="SUPABASE_SERVICE_ROLE_KEY"
    )

    # Model routing (section 10). Cheap for scanning/classification/rules,
    # mid for planning/building/review, top only for approved hard steps.
    model_cheap: str = Field(default="claude-haiku-5-5", alias="HACKAGENT_MODEL_CHEAP")
    model_mid: str = Field(default="claude-sonnet-5-5", alias="HACKAGENT_MODEL_MID")
    model_top: str = Field(default="claude-opus-5-5", alias="HACKAGENT_MODEL_TOP")

    # When true, no LLM calls are made and nothing is written to the database.
    dry_run: bool = Field(default=False, alias="HACKAGENT_DRY_RUN")
    workspace_dir: Path = Field(default=Path("workspace"), alias="HACKAGENT_WORKSPACE_DIR")
    http_timeout_s: float = Field(default=20.0, alias="HACKAGENT_HTTP_TIMEOUT")
    user_agent: str = Field(
        default="hackagent/0.1 (personal hackathon tracker; single user)",
        alias="HACKAGENT_USER_AGENT",
    )

    @field_validator("supabase_url")
    @classmethod
    def _https_only(cls, v: str | None) -> str | None:
        local = ("http://127.0.0.1", "http://localhost")
        if v and not v.startswith("https://") and not v.startswith(local):
            raise ValueError("SUPABASE_URL must use https:// (plain http only for localhost)")
        return v.rstrip("/") if v else v


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
