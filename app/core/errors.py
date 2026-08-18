from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PublicError(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    code: str
    message: str
    request_id: UUID
    retryable: bool


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    error: PublicError


@dataclass
class AppError(Exception):
    code: str
    message: str
    status_code: int
    retryable: bool = False

    def __post_init__(self) -> None:
        super().__init__(self.message)
