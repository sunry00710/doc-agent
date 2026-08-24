from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import create_database_engine
from app.documents.models import Document, DocumentVersion
from app.documents.service import create_document, create_version
from app.documents.storage import FileStorage
from app.identity.models import Role, User
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import KnowledgeSpace, KnowledgeSpaceKind
from app.projects.models import Project
from app.projects.service import create_project
from app.quality.contracts import ContractRevisionInput, create_contract
from app.quality.models import WritingContract

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "DemoPass-2026!"
PROJECT_NAME = "演示项目：年度审计报告"
DOCUMENT_TITLE = "2026 年上半年审计整改报告"
CONTENT = """# 2026 年上半年审计整改报告

## 审计范围

本报告覆盖 2026 年 1 月至 6 月的采购、报销和合同管理流程。

## 主要发现

抽样发现 3 笔采购事项缺少完整的比价记录，相关部门应在 2026 年 9 月前完成补正。

## 整改建议

建立采购比价材料清单，并由项目负责人在付款前完成复核。
"""

# 演示契约要求：前 5 条在正文中逐字出现（模拟评估会判定“已满足”），
# 最后 1 条正文缺失，用于演示“未满足 → 主管关注点 → 作者待办”闭环
CONTRACT_REQUIREMENTS = [
    {"id": "scope-section", "text": "审计范围", "mandatory": True},
    {"id": "findings-section", "text": "主要发现", "mandatory": True},
    {"id": "rectification-section", "text": "整改建议", "mandatory": True},
    {"id": "evidence-mention", "text": "采购比价", "mandatory": True},
    {"id": "deadline", "text": "2026 年 9 月前完成补正", "mandatory": False},
    {"id": "owner-list", "text": "整改责任清单", "mandatory": True},
]


def seed_demo(session: Session, storage: FileStorage) -> tuple[User, DocumentVersion]:
    user = session.scalar(select(User).where(User.username == DEMO_USERNAME))
    if user is None:
        user = User(
            username=DEMO_USERNAME,
            password_hash=hash_password(DEMO_PASSWORD),
            role=Role.admin,
        )
        session.add(user)
        session.flush()
    project = session.scalar(
        select(Project).where(Project.name == PROJECT_NAME)
    )
    if project is None:
        project = create_project(session, PROJECT_NAME, user)
    document = session.scalar(
        select(Document).where(
            Document.project_id == project.id, Document.title == DOCUMENT_TITLE
        )
    )
    if document is None:
        document = create_document(
            session, UUID(project.id), DOCUMENT_TITLE, "审计", "报告", user
        )
    version = session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.number == 1
        )
    )
    if version is None:
        version = create_version(
            session,
            storage,
            UUID(document.id),
            CONTENT.encode(),
            user,
            "annual-audit-demo.md",
        )
    contract = session.scalar(
        select(WritingContract).where(WritingContract.document_id == document.id)
    )
    if contract is None:
        create_contract(
            session,
            UUID(document.id),
            ContractRevisionInput(
                domain="审计",
                document_type="报告",
                subject_organization="演示单位",
                reporting_period="2026 年上半年",
                purpose="向管理层汇报审计发现与整改进展",
                audience="管理层与整改责任部门",
                requirements=CONTRACT_REQUIREMENTS,
                standard_ids=[],
                precedent_ids=[],
                reviewer_id=None,
            ),
            user,
        )
    space = session.scalar(
        select(KnowledgeSpace).where(KnowledgeSpace.kind == KnowledgeSpaceKind.shared)
    )
    if space is None:
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add(space)
        session.flush()
    ingest_version(session, storage, UUID(version.id), UUID(space.id))
    return user, version


def main() -> int:
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user, version = seed_demo(session, FileStorage(settings))
            session.commit()
        print(f"演示数据已就绪：用户 {user.username}，文档版本 {version.id}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
