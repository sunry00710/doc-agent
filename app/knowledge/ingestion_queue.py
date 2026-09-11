"""上传版本后的项目空间索引入队。

`POST /api/documents/{id}/versions` 与后台 worker 的 `knowledge.ingest` 处理器之间的桥：
上传事务里落一条 Job（幂等键 = 版本 ID），worker 消费时真正建索引。
worker 未运行时索引延迟可见（Job 面板显示「排队中」），Job 本身持久化，天然补偿。
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.models import User
from app.jobs.models import Job
from app.jobs.service import enqueue
from app.knowledge.models import KnowledgeSpace, KnowledgeSpaceKind
from app.knowledge.schemas import IngestionJobPayload

JOB_TYPE_INGEST = "knowledge.ingest"


def project_space(session: Session, project_id: str) -> KnowledgeSpace:
    """项目空间按项目惰性创建：一个项目一个空间，成员读写。"""
    space = session.scalar(
        select(KnowledgeSpace).where(
            KnowledgeSpace.kind == KnowledgeSpaceKind.project,
            KnowledgeSpace.project_id == project_id,
        )
    )
    if space is not None:
        return space
    space = KnowledgeSpace(kind=KnowledgeSpaceKind.project, project_id=project_id)
    session.add(space)
    session.flush()
    return space


def enqueue_ingestion(session: Session, version_id: str, project_id: str, actor: User) -> Job:
    """版本不可变，version_id 天然是幂等键；重复上传同一版本不会重复建索引。"""
    space = project_space(session, project_id)
    return enqueue(
        session,
        JOB_TYPE_INGEST,
        IngestionJobPayload(version_id=UUID(version_id), space_id=UUID(space.id)),
        owner_id=actor.id,
        idempotency_key=f"knowledge.ingest:{version_id}",
    )
