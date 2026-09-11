from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QualityGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[dict] = Field(default_factory=list, max_length=1_000)


class PromotionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    target_space_id: UUID


class PromotionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool


class PromotionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_id: UUID
    target_space_id: UUID
    requested_by: UUID
    reviewed_by: UUID | None
    status: str
    quality_status: str
    findings: list[dict]
    policy_version: str
    authority_level: int
    public_authority: bool
    # 展示辅助字段：由路由联表填充，便于前端显示《文档标题》vN 而非裸 UUID
    document_title: str | None = None
    version_number: int | None = None
    can_govern: bool = False
