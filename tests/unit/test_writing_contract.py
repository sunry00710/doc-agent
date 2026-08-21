from uuid import uuid4

import pytest
from app.quality.contracts import ContractRevisionInput, Requirement
from pydantic import ValidationError


def contract_input() -> ContractRevisionInput:
    return ContractRevisionInput(
        domain="finance",
        document_type="report",
        subject_organization="Org",
        reporting_period="2026",
        purpose="说明情况",
        audience="领导",
        requirements=[Requirement(id="r1", text="必须披露金额")],
        standard_ids=[uuid4()],
        precedent_ids=[uuid4()],
    )


def test_contract_requires_structured_requirements_and_rejects_extra_fields():
    assert contract_input().requirements[0].id == "r1"
    with pytest.raises(ValidationError):
        ContractRevisionInput.model_validate({**contract_input().model_dump(), "unexpected": True})
