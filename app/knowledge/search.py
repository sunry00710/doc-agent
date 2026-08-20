from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.storage import FileStorage
from app.identity.models import User
from app.knowledge.citations import assemble_citation
from app.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSpace,
    KnowledgeSpaceKind,
    KnowledgeState,
)
from app.knowledge.schemas import SearchHit, SearchQuery
from app.projects.models import ProjectMember


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: str
    generation_id: str
    score: float


def _fts_query(query: str) -> str:
    tokens: list[str] = []
    for part in re.findall(r"[\w]+", query, flags=re.UNICODE):
        tokens.extend(character for character in part if "一" <= character <= "鿿") if any("一" <= character <= "鿿" for character in part) else tokens.append(part)
    return " AND ".join(f'"{token}"' for token in tokens)


class SearchBackend(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        authorized_chunk_keys: frozenset[tuple[str, str]],
        limit: int,
    ) -> list[RankedChunk]: ...


class SQLiteFtsBackend(SearchBackend):
    """SQLite FTS adapter; authorization IDs are applied inside the ranked query."""
    def __init__(self, session: Session):
        self.session = session

    def search(
        self,
        query: str,
        authorized_chunk_keys: frozenset[tuple[str, str]],
        limit: int,
    ) -> list[RankedChunk]:
        fts_query = _fts_query(query)
        if not fts_query:
            raise AppError("validation_error", "Invalid knowledge search query", 422)
        if not authorized_chunk_keys:
            return []
        parameters = {"query": fts_query, "limit": limit}
        predicates: list[str] = []
        for number, (chunk_id, generation_id) in enumerate(sorted(authorized_chunk_keys)):
            chunk_name = f"chunk_id_{number}"
            generation_name = f"generation_id_{number}"
            predicates.append(f"(f.chunk_id = :{chunk_name} AND f.generation_id = :{generation_name})")
            parameters[chunk_name] = chunk_id
            parameters[generation_name] = generation_id
        statement = text(
            "SELECT f.chunk_id, f.generation_id, bm25(knowledge_chunks_fts) AS score "
            "FROM knowledge_chunks_fts AS f "
            "WHERE knowledge_chunks_fts MATCH :query AND ("
            + " OR ".join(predicates)
            + ") ORDER BY score, f.chunk_id LIMIT :limit"
        )
        try:
            rows = self.session.execute(statement, parameters).all()
        except OperationalError as exc:
            raise AppError("validation_error", "Invalid knowledge search query", 422) from exc
        return [RankedChunk(chunk_id=row.chunk_id, generation_id=row.generation_id, score=float(row.score)) for row in rows]


def _authorized_documents(session: Session, actor: User) -> list[KnowledgeDocument]:
    member_project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == actor.id)
    allowed_space_ids = select(KnowledgeSpace.id).where(
        (KnowledgeSpace.kind == KnowledgeSpaceKind.personal) & (KnowledgeSpace.owner_id == actor.id)
        | (KnowledgeSpace.kind == KnowledgeSpaceKind.project) & (KnowledgeSpace.project_id.in_(member_project_ids))
        | KnowledgeSpace.kind.in_((KnowledgeSpaceKind.shared, KnowledgeSpaceKind.standard))
    )
    return list(session.scalars(select(KnowledgeDocument).where(KnowledgeDocument.space_id.in_(allowed_space_ids), KnowledgeDocument.state == KnowledgeState.indexed, KnowledgeDocument.active_generation_id.is_not(None))))


def search(session: Session, storage: FileStorage, query: SearchQuery, actor: User, backend: SearchBackend | None = None) -> list[SearchHit]:
    documents = _authorized_documents(session, actor)
    active_generation_ids = {document.active_generation_id for document in documents if document.active_generation_id}
    chunks = list(session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.generation_id.in_(active_generation_ids)))) if active_generation_ids else []
    chunk_by_key = {(chunk.id, chunk.generation_id): chunk for chunk in chunks}
    ranked = (backend or SQLiteFtsBackend(session)).search(
        query.query,
        frozenset(chunk_by_key),
        query.limit,
    )
    hits: list[SearchHit] = []
    for item in ranked:
        chunk = chunk_by_key.get((item.chunk_id, item.generation_id))
        if chunk is None:
            continue
        citation = assemble_citation(session, storage, chunk.id, chunk.generation_id)
        hits.append(SearchHit(**citation.model_dump()))
    return hits
