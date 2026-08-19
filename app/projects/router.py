from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.identity.models import User
from app.identity.router import get_current_user
from app.projects.schemas import (
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectRead,
)
from app.projects.service import (
    add_project_member,
    create_project,
    list_project_members,
    list_projects,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create(
    data: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    project = create_project(session, data.name, current_user)
    session.commit()
    return project


@router.get("", response_model=list[ProjectRead])
def list_for_user(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    return list_projects(session, current_user)


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberRead,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    project_id: UUID,
    data: ProjectMemberCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    member = add_project_member(
        session, project_id, data.user_id, data.membership_role, current_user
    )
    session.commit()
    return member


@router.get("/{project_id}/members", response_model=list[ProjectMemberRead])
def list_members(
    project_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    return list_project_members(session, project_id, current_user)
