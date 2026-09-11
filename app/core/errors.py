from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PromotionFinding(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    category: str
    summary: str
    evidence: str
    requirement_id: str | None
    contract_id: str | None = None
    contract_revision: int | None = None
    status: str
    severity: str
    mandatory: bool
    blocking: bool
    human_review_required: bool


class ErrorDetails(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    findings: list[PromotionFinding] | None = None


class PublicError(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    code: str
    message: str
    request_id: UUID
    retryable: bool
    details: ErrorDetails | None = None


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    error: PublicError


@dataclass
class AppError(Exception):
    code: str
    message: str
    status_code: int
    retryable: bool = False
    details: dict[str, object] | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)
