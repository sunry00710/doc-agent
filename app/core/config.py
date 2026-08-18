from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_JWT_SECRET = "development-only-change-me"


class Settings(BaseSettings):
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "sqlite:///./doc_agent.db"
    jwt_secret: SecretStr = SecretStr(DEVELOPMENT_JWT_SECRET)
    model_provider: str = "anthropic"
    storage_dir: Path = Path("./storage")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def require_deployment_jwt_secret(self) -> Self:
        uses_default_secret = self.jwt_secret.get_secret_value() == DEVELOPMENT_JWT_SECRET
        if self.environment not in {"development", "test"} and uses_default_secret:
            raise ValueError("JWT_SECRET must be configured outside development and test")
        return self
