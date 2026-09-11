from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.quality.contracts import ContractAssessment, assess_contract


class SupervisorConcern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    requirement_id: str | None = None
    assigned_to: str = "author"
    evidence: str = ""
    mandatory: bool = True
    blocking: bool = True


class SupervisorSimulation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessments: list[ContractAssessment]
    concerns: list[SupervisorConcern]
    author_tasks: list[str]


def simulate_supervisor_review(revision, source: str) -> SupervisorSimulation:
    assessments = assess_contract(revision, source)
    concerns = [
        SupervisorConcern(
            id=f"contract:{item.requirement_id}",
            category="contract_requirement",
            summary=f"未满足写作要求：{item.requirement_id}",
            requirement_id=item.requirement_id,
            evidence=item.evidence,
            mandatory=item.mandatory,
            blocking=item.blocking,
        )
        for item in assessments
        if item.status != "satisfied"
    ]
    return SupervisorSimulation(
        assessments=assessments,
        concerns=concerns,
        author_tasks=[item.id for item in concerns],
    )
