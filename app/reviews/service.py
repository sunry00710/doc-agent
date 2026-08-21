from __future__ import annotations

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.models import Document, DocumentVersion
from app.identity.models import User
from app.projects.permissions import ProjectAction, require_project_permission
from app.reviews.models import CommentResponse, DocumentReview, ReviewComment
from app.reviews.workflow import validate_transition

_REVIEWER_TRANSITIONS = frozenset(
    {
        "in_review",
        "changes_requested",
        "approved",
        "promotion_pending",
        "indexed",
        "archived",
    }
)


def _review(
    session: Session, review_id: UUID, actor: User, action: ProjectAction
) -> DocumentReview:
    review = session.get(DocumentReview, str(review_id))
    if review is None:
        raise AppError("not_found", "Review not found", 404)
    document = session.get(Document, review.document_id)
    if document is None:
        raise AppError("not_found", "Document not found", 404)
    require_project_permission(UUID(document.project_id), action, actor, session)
    return review


def _check_revision(review: DocumentReview, expected_revision: int) -> None:
    if review.workflow_revision != expected_revision:
        raise AppError(
            "version_conflict",
            "Review workflow revision has changed",
            409,
            retryable=True,
        )


def _require_assigned_reviewer(review: DocumentReview, actor: User) -> None:
    if review.reviewer_id != actor.id:
        raise AppError(
            "permission_denied", "Review is assigned to another reviewer", 403
        )


def create_review(
    session: Session, document_id: UUID, version_id: UUID, actor: User
) -> DocumentReview:
    document = session.get(Document, str(document_id))
    if document is None:
        raise AppError("not_found", "Document not found", 404)
    require_project_permission(
        UUID(document.project_id), ProjectAction.submit, actor, session
    )
    version = session.get(DocumentVersion, str(version_id))
    if version is None or version.document_id != document.id:
        raise AppError("validation_error", "Version does not belong to document", 422)
    review = DocumentReview(
        document_id=document.id, version_id=version.id, created_by=actor.id
    )
    session.add(review)
    session.flush()
    return review


def transition(
    session: Session, review_id: UUID, state: str, expected_revision: int, actor: User
) -> DocumentReview:
    action = (
        ProjectAction.review if state in _REVIEWER_TRANSITIONS else ProjectAction.submit
    )
    review = _review(session, review_id, actor, action)
    _check_revision(review, expected_revision)
    validate_transition(review.state, state)
    if state in _REVIEWER_TRANSITIONS:
        _require_assigned_reviewer(review, actor)
    result = session.execute(
        update(DocumentReview)
        .where(
            DocumentReview.id == review.id,
            DocumentReview.workflow_revision == expected_revision,
        )
        .values(state=state, workflow_revision=expected_revision + 1)
    )
    if result.rowcount != 1:
        raise AppError(
            "version_conflict",
            "Review workflow revision has changed",
            409,
            retryable=True,
        )
    session.refresh(review)
    return review


def assign_reviewer(
    session: Session,
    review_id: UUID,
    reviewer_id: UUID,
    expected_revision: int,
    actor: User,
) -> DocumentReview:
    review = _review(session, review_id, actor, ProjectAction.review)
    _check_revision(review, expected_revision)
    reviewer = session.get(User, str(reviewer_id))
    if reviewer is None or not reviewer.is_active:
        raise AppError("not_found", "Reviewer not found", 404)
    result = session.execute(
        update(DocumentReview)
        .where(
            DocumentReview.id == review.id,
            DocumentReview.workflow_revision == expected_revision,
        )
        .values(reviewer_id=reviewer.id, workflow_revision=expected_revision + 1)
    )
    if result.rowcount != 1:
        raise AppError(
            "version_conflict",
            "Review workflow revision has changed",
            409,
            retryable=True,
        )
    session.refresh(review)
    return review


def add_comment(
    session: Session,
    review_id: UUID,
    source_range: dict[str, int],
    text: str,
    expected_revision: int,
    actor: User,
) -> ReviewComment:
    review = _review(session, review_id, actor, ProjectAction.review)
    _check_revision(review, expected_revision)
    _require_assigned_reviewer(review, actor)
    if review.state not in {"in_review", "resubmitted"}:
        raise AppError("validation_error", "Comments require an active review", 422)
    start = source_range.get("start")
    end = source_range.get("end")
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end <= start
    ):
        raise AppError("validation_error", "Invalid comment source range", 422)
    comment = ReviewComment(
        review_id=review.id,
        version_id=review.version_id,
        source_range={"start": start, "end": end},
        text=text.strip(),
        created_by=actor.id,
    )
    session.add(comment)
    review.workflow_revision += 1
    session.flush()
    return comment


def respond_to_comment(
    session: Session,
    comment_id: UUID,
    response_version_id: UUID,
    assessment: str,
    expected_revision: int,
    actor: User,
) -> CommentResponse:
    comment = session.get(ReviewComment, str(comment_id))
    if comment is None:
        raise AppError("not_found", "Review comment not found", 404)
    review = _review(session, UUID(comment.review_id), actor, ProjectAction.submit)
    _check_revision(review, expected_revision)
    response_version = session.get(DocumentVersion, str(response_version_id))
    if (
        response_version is None
        or response_version.document_id != review.document_id
        or response_version.number
        <= session.get(DocumentVersion, comment.version_id).number
    ):
        raise AppError(
            "validation_error", "Response must target a later document version", 422
        )
    if assessment not in {"addressed", "not_addressed", "ambiguous"}:
        raise AppError("validation_error", "Invalid comment assessment", 422)
    response = CommentResponse(
        comment_id=comment.id,
        response_version_id=response_version.id,
        assessment=assessment,
        reviewer_confirmed=False,
        created_by=actor.id,
    )
    session.add(response)
    review.workflow_revision += 1
    session.flush()
    return response


def confirm_comment_response(
    session: Session,
    response_id: UUID,
    expected_revision: int,
    actor: User,
) -> CommentResponse:
    response = session.get(CommentResponse, str(response_id))
    if response is None:
        raise AppError("not_found", "Comment response not found", 404)
    comment = session.get(ReviewComment, response.comment_id)
    if comment is None:
        raise AppError("not_found", "Review comment not found", 404)
    review = _review(session, UUID(comment.review_id), actor, ProjectAction.review)
    _check_revision(review, expected_revision)
    _require_assigned_reviewer(review, actor)
    response.reviewer_confirmed = True
    if response.assessment == "addressed":
        comment.status = "resolved"
    review.workflow_revision += 1
    session.flush()
    return response
