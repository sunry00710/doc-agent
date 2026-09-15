from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.documents.models import Document, DocumentVersion
from app.documents.storage import FileStorage
from app.identity.models import User
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import KnowledgeSpace, KnowledgeSpaceKind
from app.knowledge.schemas import SearchQuery
from app.knowledge.search import search
from app.projects.models import MembershipRole, Project, ProjectMember

CONTENT = """# 差旅费管理办法

伙食补助费每人每天 100 元，市内交通费每人每天 80 元，包干使用。

差旅结束后 15 个工作日内办理报销，逾期未报销的，财务部门将予以提示并记录。
"""


def _prepare(session: Session, storage: FileStorage, owner: User, content: str, title: str) -> None:
    project = Project(name=f"{title} project")
    session.add(project)
    session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=owner.id, membership_role=MembershipRole.owner))
    stored = storage.store(f"{title}.md", content.encode())
    document = Document(project_id=project.id, owner_id=owner.id, title=title, domain="finance", document_type="policy")
    session.add(document)
    session.flush()
    version = DocumentVersion(
        document_id=document.id,
        number=1,
        content_sha256=stored.content_sha256,
        storage_key=stored.storage_key,
        created_by=owner.id,
    )
    space = KnowledgeSpace(kind=KnowledgeSpaceKind.personal, owner_id=owner.id)
    session.add_all((version, space))
    session.flush()
    ingest_version(session, storage, UUID(version.id), UUID(space.id))


def _factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'recall.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5("
                "chunk_id UNINDEXED, generation_id UNINDEXED, text)"
            )
        )
    return sessionmaker(bind=engine, expire_on_commit=False)


def _owner(session: Session, name: str) -> User:
    user = User(username=name, password_hash=hash_password("correct"))
    session.add(user)
    session.flush()
    return user


def test_keyword_search_falls_back_to_or_when_and_has_no_hits(tmp_path: Path):
    factory = _factory(tmp_path)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = _owner(session, "owner")
        _prepare(session, storage, owner, CONTENT, "差旅费管理办法")
        session.commit()

        # AND 检索式能命中的短查询：行为与修复前一致
        assert search(session, storage, SearchQuery(query="差旅补助", mode="keyword"), owner)

        # 修复前：AND 要求 差/旅/补/助/标/准 同时出现在同一块 -> 0 命中
        hits = search(session, storage, SearchQuery(query="差旅补助标准", mode="keyword"), owner)
        assert hits, "长自然语言查询应通过 OR 兜底召回，而不是返回空"
        assert hits[0].title == "差旅费管理办法"
        # 引文仍来自原文，未被检索改写污染
        assert hits[0].quote in CONTENT


def test_or_fallback_still_respects_space_authorization(tmp_path: Path):
    factory = _factory(tmp_path)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = _owner(session, "owner")
        stranger = _owner(session, "stranger")
        _prepare(session, storage, owner, CONTENT, "差旅费管理办法")
        # 他人的个人知识库内容同样包含这些字，但不应被 OR 兜底带出来
        _prepare(session, storage, stranger, CONTENT.replace("财务部门", "外部机构"), "外部差旅办法")
        session.commit()

        hits = search(session, storage, SearchQuery(query="差旅补助标准", mode="keyword"), owner)
        assert hits
        assert {hit.title for hit in hits} == {"差旅费管理办法"}


def test_unmatched_query_returns_empty_without_error(tmp_path: Path):
    factory = _factory(tmp_path)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = _owner(session, "owner")
        _prepare(session, storage, owner, CONTENT, "差旅费管理办法")
        session.commit()

        assert search(session, storage, SearchQuery(query="量子计算", mode="keyword"), owner) == []


def test_latin_multi_term_query_keeps_and_semantics(tmp_path: Path):
    factory = _factory(tmp_path)
    storage = FileStorage(Settings(environment="test", storage_dir=tmp_path / "storage"))
    with factory() as session:
        owner = _owner(session, "owner")
        _prepare(session, storage, owner, "shared-indexed", "shared-indexed")
        session.commit()

        assert search(session, storage, SearchQuery(query="shared-indexed", mode="keyword"), owner)
        # 第三个词不存在，AND 语义下必须为空：拉丁词不参与 OR 降级
        assert search(session, storage, SearchQuery(query="shared-indexed-deleted", mode="keyword"), owner) == []
