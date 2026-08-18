from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./doc_agent.db"
    jwt_secret: SecretStr = SecretStr("development-only-change-me")
    model_provider: str = "anthropic"
    storage_dir: Path = Path("./storage")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
