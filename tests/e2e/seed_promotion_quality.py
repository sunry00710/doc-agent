from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings
from app.core.security import hash_password
from app.documents.service import create_document, create_version
from app.documents.storage import FileStorage
from app.identity.models import Role, User
from app.knowledge.models import KnowledgeSpace, KnowledgeSpaceKind
from app.projects.models import MembershipRole, Project, ProjectMember
from app.quality.contracts import (
    ContractRevisionInput,
    Requirement,
    confirm_revision,
    create_contract,
)

PASSWORD = "e2e-disposable-password"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--storage", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def add_document(
    session: Session,
    storage: FileStorage,
    project: Project,
    author: User,
    reviewer: User,
    *,
    title: str,
    source: str,
    requirement: Requirement,
    confirmed: bool,
) -> None:
    document = create_document(
        session,
        UUID(project.id),
        title,
        "audit",
        "report",
        author,
    )
    create_version(
        session,
        storage,
        UUID(document.id),
        source.encode(),
        author,
        f"{title}.md",
    )
    contract = create_contract(
        session,
        UUID(document.id),
        ContractRevisionInput(
            domain="audit",
            document_type="report",
            subject_organization="E2E Org",
            reporting_period="2026",
            purpose="E2E policy validation",
            audience="Reviewer",
            requirements=[requirement],
        ),
        author,
    )
    if confirmed:
        confirm_revision(session, contract.id, reviewer)


def main() -> int:
    args = parse_args()
    database_url = f"sqlite:///{args.database.as_posix()}"
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    settings = Settings(
        environment="test",
        database_url=database_url,
        storage_dir=args.storage,
    )
    storage = FileStorage(settings)
    engine = create_engine(database_url)
    with Session(engine, expire_on_commit=False) as session:
        author = User(
            username="e2e-author",
            password_hash=hash_password(PASSWORD),
            role=Role.user,
        )
        reviewer = User(
            username="e2e-reviewer",
            password_hash=hash_password(PASSWORD),
            role=Role.reviewer,
        )
        admin = User(
            username="e2e-admin",
            password_hash=hash_password(PASSWORD),
            role=Role.admin,
        )
        project = Project(name="E2E promotion policy")
        session.add_all((author, reviewer, admin, project))
        session.flush()
        session.add_all(
            (
                ProjectMember(
                    project_id=project.id,
                    user_id=author.id,
                    membership_role=MembershipRole.contributor,
                ),
                ProjectMember(
                    project_id=project.id,
                    user_id=reviewer.id,
                    membership_role=MembershipRole.reviewer,
                ),
                ProjectMember(
                    project_id=project.id,
                    user_id=admin.id,
                    membership_role=MembershipRole.owner,
                ),
                KnowledgeSpace(kind=KnowledgeSpaceKind.shared),
            )
        )
        session.flush()
        add_document(
            session,
            storage,
            project,
            author,
            reviewer,
            title="E2E mandatory blocked",
            source="# Mandatory policy\n\nNo required disclosure is present.",
            requirement=Requirement(
                id="mandatory",
                text="E2E-MANDATORY-MISSING",
                mandatory=True,
            ),
            confirmed=True,
        )
        add_document(
            session,
            storage,
            project,
            author,
            reviewer,
            title="E2E optional human review",
            source=(
                "# Optional policy\n\n"
                "E2E-OPTIONAL-PROMOTION-NEEDLE-20260901"
            ),
            requirement=Requirement(
                id="optional",
                text="E2E-OPTIONAL-MISSING",
                mandatory=False,
            ),
            confirmed=True,
        )
        add_document(
            session,
            storage,
            project,
            author,
            reviewer,
            title="E2E unconfirmed contract",
            source="# Unconfirmed policy\n\nE2E-UNCONFIRMED-SATISFIED",
            requirement=Requirement(
                id="unconfirmed",
                text="E2E-UNCONFIRMED-SATISFIED",
                mandatory=True,
            ),
            confirmed=False,
        )
        session.commit()
    engine.dispose()
    args.manifest.write_text(
        json.dumps(
            {
                "password": PASSWORD,
                "project": "E2E promotion policy",
                "author": "e2e-author",
                "reviewer": "e2e-reviewer",
                "admin": "e2e-admin",
                "mandatoryTitle": "E2E mandatory blocked",
                "optionalTitle": "E2E optional human review",
                "unconfirmedTitle": "E2E unconfirmed contract",
                "optionalNeedle": (
                    "E2E-OPTIONAL-PROMOTION-NEEDLE-20260901"
                ),
            }
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
