from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_JWT_SECRET = "development-only-change-me"


class Settings(BaseSettings):
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "sqlite:///./doc_agent.db"
    jwt_secret: SecretStr = SecretStr(DEVELOPMENT_JWT_SECRET)
    model_provider: str = "anthropic"
    storage_dir: Path = Path("./storage")
    max_upload_bytes: int = 10 * 1024 * 1024
    job_heartbeat_seconds: int = Field(default=30, ge=1, le=3600)
    job_stale_after_seconds: int = Field(default=120, ge=2, le=86_400)
    job_max_attempts: int = Field(default=3, ge=1, le=100)
    job_poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def require_deployment_jwt_secret(self) -> Self:
        uses_default_secret = self.jwt_secret.get_secret_value() == DEVELOPMENT_JWT_SECRET
        if self.environment not in {"development", "test"} and uses_default_secret:
            raise ValueError("JWT_SECRET must be configured outside development and test")
        if self.job_stale_after_seconds <= self.job_heartbeat_seconds:
            raise ValueError("JOB_STALE_AFTER_SECONDS must exceed JOB_HEARTBEAT_SECONDS")
        return self
