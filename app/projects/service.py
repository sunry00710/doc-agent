from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.identity.models import User
from app.projects.models import MembershipRole, Project, ProjectMember
from app.projects.permissions import ProjectAction, require_project_permission


def create_project(session: Session, name: str, owner: User) -> Project:
    project = Project(name=name.strip())
    session.add(project)
    session.flush()
    session.add(
        ProjectMember(
            project_id=project.id,
            user_id=owner.id,
            membership_role=MembershipRole.owner,
        )
    )
    session.flush()
    return project


def list_projects(session: Session, user: User) -> list[Project]:
    return list(
        session.scalars(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
            .order_by(Project.created_at, Project.id)
        )
    )


def add_project_member(
    session: Session,
    project_id: UUID,
    user_id: UUID,
    membership_role: MembershipRole,
    actor: User,
) -> ProjectMember:
    require_project_permission(project_id, ProjectAction.manage_members, actor, session)
    if session.get(User, str(user_id)) is None:
        raise AppError("not_found", "User not found", 404)
    existing = session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == str(project_id),
            ProjectMember.user_id == str(user_id),
        )
    )
    if existing is not None:
        raise AppError("membership_exists", "Project membership already exists", 409)
    member = ProjectMember(
        project_id=str(project_id),
        user_id=str(user_id),
        membership_role=membership_role,
    )
    session.add(member)
    session.flush()
    return member


def list_project_members(
    session: Session, project_id: UUID, actor: User
) -> list[ProjectMember]:
    require_project_permission(project_id, ProjectAction.view, actor, session)
    return list(
        session.scalars(
            select(ProjectMember)
            .where(ProjectMember.project_id == str(project_id))
            .order_by(ProjectMember.created_at, ProjectMember.id)
        )
    )
