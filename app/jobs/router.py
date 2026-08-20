from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.identity.models import User
from app.identity.router import get_current_user
from app.jobs.schemas import JobListResponse, JobRead
from app.jobs.service import cancel_job, get_owned_job, list_owned_jobs, retry_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse)
def list_jobs(current_user: Annotated[User, Depends(get_current_user)], session: Annotated[Session, Depends(get_db)]):
    return JobListResponse(items=list_owned_jobs(session, current_user.id))


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: UUID, current_user: Annotated[User, Depends(get_current_user)], session: Annotated[Session, Depends(get_db)]):
    job = get_owned_job(session, job_id, current_user.id)
    if job is None:
        raise AppError("not_found", "Job not found", 404)
    return job


@router.post("/{job_id}/retry", response_model=JobRead)
def retry(job_id: UUID, current_user: Annotated[User, Depends(get_current_user)], session: Annotated[Session, Depends(get_db)]):
    job = get_owned_job(session, job_id, current_user.id)
    if job is None:
        raise AppError("not_found", "Job not found", 404)
    if not retry_job(session, job_id, current_user.id):
        raise AppError("conflict", "Job cannot be retried", status.HTTP_409_CONFLICT)
    session.commit()
    return get_owned_job(session, job_id, current_user.id)


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel(job_id: UUID, current_user: Annotated[User, Depends(get_current_user)], session: Annotated[Session, Depends(get_db)]):
    job = get_owned_job(session, job_id, current_user.id)
    if job is None:
        raise AppError("not_found", "Job not found", 404)
    if not cancel_job(session, job_id, current_user.id):
        raise AppError("conflict", "Job cannot be cancelled", status.HTTP_409_CONFLICT)
    session.commit()
    return get_owned_job(session, job_id, current_user.id)
