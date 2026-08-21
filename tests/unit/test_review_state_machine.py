import pytest

from app.core.errors import AppError
from app.reviews.workflow import TRANSITIONS, validate_transition


def test_workflow_allows_product_transitions():
    for current, targets in TRANSITIONS.items():
        for target in targets:
            validate_transition(current, target)


def test_workflow_rejects_forbidden_transition():
    with pytest.raises(AppError) as error:
        validate_transition("draft", "approved")

    assert error.value.code == "validation_error"
