from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.documents.router import get_storage
from app.documents.storage import FileStorage
from app.identity.models import User
from app.identity.router import get_current_user
from app.knowledge.promotion_schemas import (
    PromotionCreate,
    PromotionRead,
    PromotionReview,
)
from app.knowledge.promotion_service import (
    activate_promotion,
    request_promotion,
    review_promotion,
    revoke_promotion,
)
from app.quality.gates import evaluate_quality_gate

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post("/promotions", response_model=PromotionRead, status_code=201)
def create_promotion(
    data: PromotionCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> PromotionRead:
    result = request_promotion(
        session,
        data.version_id,
        data.target_space_id,
        user,
        evaluate_quality_gate(data.findings),
        public_authority=data.public_authority,
        authority_level=data.authority_level,
    )
    session.commit()
    return result


@router.post("/promotions/{request_id}/review", response_model=PromotionRead)
def review(
    request_id: UUID,
    data: PromotionReview,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> PromotionRead:
    result = review_promotion(session, request_id, user, data.approved)
    session.commit()
    return result


@router.post("/promotions/{request_id}/activate", response_model=PromotionRead)
def activate(
    request_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_storage)],
) -> PromotionRead:
    result = activate_promotion(session, request_id, storage, user)
    session.commit()
    return result


@router.post("/promotions/{request_id}/revoke", response_model=PromotionRead)
def revoke(
    request_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> PromotionRead:
    result = revoke_promotion(session, request_id, user)
    session.commit()
    return result
