from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_JWT_SECRET = "development-only-change-me"


class Settings(BaseSettings):
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "sqlite:///./doc_agent.db"
    jwt_secret: SecretStr = SecretStr(DEVELOPMENT_JWT_SECRET)
    # 模型接入：fake=本地演示 | self=自用 AI（OpenAI 兼容）
    model_provider: Literal["fake", "self"] = "fake"
    # 自用 AI 接口（如 DeepSeek，OpenAI 兼容协议）
    self_ai_endpoint: str = ""
    self_ai_api_key: SecretStr = SecretStr("")
    self_ai_model: str = ""
    provider_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    # 语义检索向量：默认开启。离线/无模型缓存的内网环境可设 false 退回纯关键词
    # （检索仍可用，只是不再有向量召回；当前响应无 degraded 字段，前端不作降级提示）。
    embedding_enabled: bool = True
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    storage_dir: Path = Path("./storage")
    # 服务监听地址：dev 默认本机；内网部署改 BACKEND_HOST=0.0.0.0 供其他机器访问
    backend_host: str = "127.0.0.1"
    backend_port: int = Field(default=8000, ge=1, le=65535)
    frontend_host: str = "127.0.0.1"
    frontend_port: int = Field(default=5173, ge=1, le=65535)
    max_upload_bytes: int = 10 * 1024 * 1024
    job_heartbeat_seconds: int = Field(default=30, ge=1, le=3600)
    job_stale_after_seconds: int = Field(default=120, ge=2, le=86_400)
    job_max_attempts: int = Field(default=3, ge=1, le=100)
    job_poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    cors_allowed_origins: list[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def require_deployment_jwt_secret(self) -> Self:
        uses_default_secret = self.jwt_secret.get_secret_value() == DEVELOPMENT_JWT_SECRET
        if self.environment not in {"development", "test"} and uses_default_secret:
            raise ValueError("JWT_SECRET must be configured outside development and test")
        if self.job_stale_after_seconds <= self.job_heartbeat_seconds:
            raise ValueError("JOB_STALE_AFTER_SECONDS must exceed JOB_HEARTBEAT_SECONDS")
        return self
