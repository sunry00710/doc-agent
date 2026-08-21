from uuid import UUID

import pytest

from app.core.errors import AppError
from app.documents.service import create_document, create_version
from app.documents.storage import FileStorage
from app.identity.models import Role
from app.projects.models import MembershipRole, ProjectMember
from app.reviews.service import (
    add_comment,
    assign_reviewer,
    confirm_comment_response,
    create_review,
    respond_to_comment,
    transition,
)
from tests.integration.test_documents import project_for, user_factory

pytest_plugins = ("tests.integration.test_documents",)


def test_review_comment_response_and_concurrent_revision_conflict(db_session, tmp_path):
    author = user_factory(db_session, "review-author")
    reviewer = user_factory(db_session, "reviewer", Role.reviewer)
    other_reviewer = user_factory(db_session, "other-reviewer", Role.reviewer)
    project = project_for(db_session, author)
    for user in (reviewer, other_reviewer):
        db_session.add(
            ProjectMember(
                project_id=project.id,
                user_id=user.id,
                membership_role=MembershipRole.reviewer,
            )
        )
    document = create_document(
        db_session, UUID(project.id), "Report", "finance", "report", author
    )
    storage = FileStorage(
        type(
            "Settings",
            (),
            {"storage_dir": tmp_path / "storage", "max_upload_bytes": 100},
        )()
    )
    submitted = create_version(db_session, storage, UUID(document.id), b"first", author)
    later = create_version(db_session, storage, UUID(document.id), b"second", author)
    review = create_review(db_session, UUID(document.id), UUID(submitted.id), author)
    db_session.commit()

    review = transition(db_session, UUID(review.id), "submitted", 0, author)
    review = assign_reviewer(
        db_session, UUID(review.id), UUID(reviewer.id), 1, reviewer
    )
    with pytest.raises(AppError, match="assigned to another reviewer"):
        transition(db_session, UUID(review.id), "in_review", 2, other_reviewer)
    review = transition(db_session, UUID(review.id), "in_review", 2, reviewer)
    comment = add_comment(
        db_session, UUID(review.id), {"start": 0, "end": 5}, "Clarify this", 3, reviewer
    )
    db_session.commit()

    ambiguous = respond_to_comment(
        db_session, UUID(comment.id), UUID(later.id), "ambiguous", 4, author
    )
    db_session.commit()
    assert ambiguous.reviewer_confirmed is False
    assert comment.status == "open"

    addressed = respond_to_comment(
        db_session, UUID(comment.id), UUID(later.id), "addressed", 5, author
    )
    db_session.commit()
    assert addressed.reviewer_confirmed is False
    assert comment.status == "open"

    confirmed = confirm_comment_response(db_session, UUID(addressed.id), 6, reviewer)
    db_session.commit()
    assert confirmed.reviewer_confirmed is True
    assert comment.status == "resolved"

    response = transition(db_session, UUID(review.id), "changes_requested", 7, reviewer)
    assert response.state == "changes_requested"
    assert (
        transition(db_session, UUID(review.id), "resubmitted", 8, author).state
        == "resubmitted"
    )

    with pytest.raises(AppError, match="revision has changed") as error:
        transition(db_session, UUID(review.id), "in_review", 8, reviewer)

    assert error.value.code == "version_conflict"
