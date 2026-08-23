from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.identity.models import User
from app.identity.router import get_current_user
from app.reviews.schemas import (
    CommentCreate,
    CommentRead,
    ResponseConfirm,
    ResponseCreate,
    ResponseRead,
    ReviewAssign,
    ReviewCreate,
    ReviewDetailRead,
    ReviewRead,
    ReviewTransition,
)
from app.reviews.service import (
    add_comment,
    assign_reviewer,
    confirm_comment_response,
    create_review,
    list_reviews,
    respond_to_comment,
    review_detail,
    transition,
)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/documents/{document_id}", response_model=list[ReviewRead])
def list_for_document(
    document_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> list[ReviewRead]:
    return list_reviews(session, document_id, user)


@router.get("/{review_id}", response_model=ReviewDetailRead)
def detail(
    review_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewDetailRead:
    review, comments, responses = review_detail(session, review_id, user)
    return ReviewDetailRead(
        **ReviewRead.model_validate(review).model_dump(),
        comments=[CommentRead.model_validate(item) for item in comments],
        responses=[ResponseRead.model_validate(item) for item in responses],
    )


@router.post("/documents/{document_id}", response_model=ReviewRead, status_code=201)
def create(
    document_id: UUID,
    data: ReviewCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewRead:
    result = create_review(session, document_id, data.version_id, user)
    session.commit()
    return result


@router.post("/{review_id}/assign", response_model=ReviewRead)
def assign(
    review_id: UUID,
    data: ReviewAssign,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewRead:
    result = assign_reviewer(
        session, review_id, data.reviewer_id, data.expected_revision, user
    )
    session.commit()
    return result


@router.post("/{review_id}/transition", response_model=ReviewRead)
def change_state(
    review_id: UUID,
    data: ReviewTransition,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewRead:
    result = transition(session, review_id, data.state, data.expected_revision, user)
    session.commit()
    return result


@router.post("/{review_id}/comments", response_model=CommentRead, status_code=201)
def comment(
    review_id: UUID,
    data: CommentCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> CommentRead:
    result = add_comment(
        session, review_id, data.source_range, data.text, data.expected_revision, user
    )
    session.commit()
    return result


@router.post(
    "/comments/{comment_id}/responses", response_model=ResponseRead, status_code=201
)
def respond(
    comment_id: UUID,
    data: ResponseCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ResponseRead:
    result = respond_to_comment(
        session,
        comment_id,
        data.response_version_id,
        data.assessment,
        data.expected_revision,
        user,
    )
    session.commit()
    return result


@router.post("/responses/{response_id}/confirm", response_model=ResponseRead)
def confirm_response(
    response_id: UUID,
    data: ResponseConfirm,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> ResponseRead:
    result = confirm_comment_response(
        session, response_id, data.expected_revision, user
    )
    session.commit()
    return result
