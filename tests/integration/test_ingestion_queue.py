"""上传版本 → 后台任务入队 → worker 消费建索引 的端到端链路。

修复前：`enqueue` 无任何生产端调用者，JobStatus 面板恒空；
上传版本同步建索引。本测试锁定异步链路与幂等语义。
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.documents.service import create_document, create_version
from app.documents.storage import FileStorage
from app.identity.models import User
from app.jobs.models import Job, JobStatus
from app.jobs.runner import JobRegistry, Worker
from app.knowledge.ingestion import KnowledgeIngestionHandler
from app.knowledge.ingestion_queue import enqueue_ingestion, project_space
from app.knowledge.models import KnowledgeDocument, KnowledgeSpace, KnowledgeSpaceKind
from app.projects import models as project_models  # noqa: F401
from app.projects.models import MembershipRole, Project, ProjectMember


def make_env(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ingestion-queue.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(chunk_id UNINDEXED, generation_id UNINDEXED, text)"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(environment="test", database_url=f"sqlite:///{tmp_path / 'ingestion-queue.db'}", storage_dir=tmp_path / "storage")
    return engine, factory, FileStorage(settings)


def seed_document(session, storage: FileStorage):
    owner = User(username="queue-owner", password_hash=hash_password("correct"))
    session.add(owner)
    session.flush()
    project = Project(name="队列测试项目")
    session.add(project)
    session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=owner.id, membership_role=MembershipRole.owner))
    session.flush()
    document = create_document(session, UUID(project.id), "测试文档", "audit", "report", owner)
    version = create_version(session, storage, UUID(document.id), "# 标题\n\n正文内容。".encode(), owner)
    return owner, project, document, version


def test_upload_enqueues_idempotent_ingestion_job(tmp_path: Path):
    engine, factory, storage = make_env(tmp_path)
    with factory() as session:
        owner, _project, document, version = seed_document(session, storage)

        first = enqueue_ingestion(session, version.id, document.project_id, owner)
        second = enqueue_ingestion(session, version.id, document.project_id, owner)
        session.commit()

        # 同一版本重复入队 → 幂等返回同一条任务
        assert first.id == second.id
        jobs = list(session.scalars(select(Job)))
        assert len(jobs) == 1
        assert jobs[0].job_type == "knowledge.ingest"
        assert jobs[0].status == JobStatus.queued

        # 项目空间惰性创建：一个项目一个空间
        space = project_space(session, document.project_id)
        assert space.kind == KnowledgeSpaceKind.project
        assert space.project_id == document.project_id
        assert session.scalars(select(KnowledgeSpace)).all() == [space]
    engine.dispose()


def test_worker_consumes_queued_job_and_indexes_version(tmp_path: Path):
    engine, factory, storage = make_env(tmp_path)
    with factory() as session:
        owner, _project, document, version = seed_document(session, storage)
        job = enqueue_ingestion(session, version.id, document.project_id, owner)
        session.commit()
        job_id = job.id

    registry = JobRegistry()
    registry.register("knowledge.ingest", KnowledgeIngestionHandler(factory, storage))
    worker = Worker(factory, registry, worker_id="test-worker")
    assert worker.run_once() is True

    with factory() as session:
        finished = session.get(Job, job_id)
        assert finished is not None
        assert finished.status is JobStatus.succeeded
        assert finished.result["version_id"] == version.id
        assert finished.result["generation_id"]
        indexed = session.scalars(select(KnowledgeDocument)).all()
        assert len(indexed) == 1
        assert indexed[0].version_id == version.id
        assert indexed[0].active_generation_id == finished.result["generation_id"]
    # 队列清空后再次运行返回 False
    assert worker.run_once() is False
    engine.dispose()


def test_job_fails_permanently_when_version_is_missing(tmp_path: Path):
    """Job 指向不存在的版本 → handler 抛 AppError(not_found) → 永久失败而不是无限重试。"""
    engine, factory, storage = make_env(tmp_path)
    with factory() as session:
        owner, _, document, _ = seed_document(session, storage)
        job = enqueue_ingestion(session, "00000000-0000-0000-0000-000000000999", document.project_id, owner)
        session.commit()
        job_id = job.id

    registry = JobRegistry()
    registry.register("knowledge.ingest", KnowledgeIngestionHandler(factory, storage))
    Worker(factory, registry, worker_id="test-worker").run_once()

    with factory() as session:
        failed = session.get(Job, job_id)
        assert failed is not None
        assert failed.status is JobStatus.failed
        # 失败 3 次后不再重试（max_attempts 默认 3），此处首轮即为永久失败
        assert failed.error is not None
    engine.dispose()
