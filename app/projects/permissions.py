from enum import Enum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.identity.models import User
from app.projects.models import MembershipRole, Project, ProjectMember


class ProjectAction(str, Enum):
    view = "view"
    edit = "edit"
    comment = "comment"
    submit = "submit"
    review = "review"
    manage_members = "manage_members"


ROLE_ACTIONS: dict[MembershipRole, frozenset[ProjectAction]] = {
    MembershipRole.contributor: frozenset(
        {ProjectAction.view, ProjectAction.edit, ProjectAction.comment, ProjectAction.submit}
    ),
    MembershipRole.reviewer: frozenset(
        {
            ProjectAction.view,
            ProjectAction.edit,
            ProjectAction.comment,
            ProjectAction.submit,
            ProjectAction.review,
        }
    ),
    MembershipRole.owner: frozenset(ProjectAction),
}


def require_project_permission(
    project_id: UUID, action: ProjectAction, user: User, session: Session
) -> Project:
    project = session.get(Project, str(project_id))
    if project is None:
        raise AppError("not_found", "Project not found", 404)
    membership = session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == str(project_id), ProjectMember.user_id == user.id
        )
    )
    if membership is None or action not in ROLE_ACTIONS[membership.membership_role]:
        raise AppError("permission_denied", "Project access denied", 403)
    return project
