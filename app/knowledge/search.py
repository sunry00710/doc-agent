from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.documents.storage import FileStorage
from app.identity.models import User
from app.knowledge.citations import assemble_citation
from app.knowledge.embeddings import EmbeddingProvider, normalized_query
from app.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeSpace,
    KnowledgeSpaceKind,
    KnowledgeState,
)
from app.knowledge.ranking import RankedId, reciprocal_rank_fusion
from app.knowledge.schemas import SearchHit, SearchQuery
from app.projects.models import ProjectMember

RankedChunk = RankedId
_DENSE_CANDIDATE_LIMIT = 5_000


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
        authorized_generation_ids: frozenset[str],
        limit: int,
    ) -> list[RankedChunk]: ...


class SQLiteFtsBackend(SearchBackend):
    """SQLite FTS adapter; authorization IDs are applied inside the ranked query."""
    def __init__(self, session: Session):
        self.session = session

    def search(
        self,
        query: str,
        authorized_generation_ids: frozenset[str],
        limit: int,
    ) -> list[RankedChunk]:
        if self.session.bind is None or self.session.bind.dialect.name != "sqlite":
            raise AppError("index_failure", "Knowledge index is temporarily unavailable", 500)
        fts_query = _fts_query(query)
        if not fts_query:
            raise AppError("validation_error", "Invalid knowledge search query", 422)
        if not authorized_generation_ids:
            return []
        statement = text(
            "SELECT f.chunk_id, f.generation_id, bm25(knowledge_chunks_fts) AS score "
            "FROM knowledge_chunks_fts AS f "
            "WHERE knowledge_chunks_fts MATCH :query "
            "AND f.generation_id IN (SELECT value FROM json_each(:generation_ids)) "
            "ORDER BY score, f.chunk_id LIMIT :limit"
        )
        try:
            rows = self.session.execute(
                statement,
                {"query": fts_query, "generation_ids": json.dumps(sorted(authorized_generation_ids)), "limit": limit},
            ).all()
        except OperationalError as exc:
            raise AppError("index_failure", "Knowledge index is temporarily unavailable", 500) from exc
        return [RankedChunk(chunk_id=row.chunk_id, generation_id=row.generation_id, score=float(row.score)) for row in rows]


class DenseBackend:
    def __init__(self, session: Session, provider: EmbeddingProvider):
        self.session = session
        self.provider = provider

    def search(
        self,
        query: str,
        authorized_generation_ids: frozenset[str],
        limit: int,
    ) -> list[RankedChunk]:
        if not authorized_generation_ids:
            return []
        try:
            rows = self.session.execute(
                select(KnowledgeEmbedding)
                .where(KnowledgeEmbedding.generation_id.in_(authorized_generation_ids))
                .order_by(KnowledgeEmbedding.generation_id, KnowledgeEmbedding.chunk_id)
                .limit(_DENSE_CANDIDATE_LIMIT)
            ).scalars().all()
        except OperationalError as exc:
            raise AppError("index_failure", "Knowledge index is temporarily unavailable", 500) from exc
        if not rows:
            return []
        dimensions = {row.dimension for row in rows}
        if len(dimensions) != 1:
            raise AppError("index_failure", "Knowledge index is temporarily unavailable", 500)
        dimension = dimensions.pop()
        try:
            vectors = np.vstack([np.frombuffer(row.vector, dtype=np.float32) for row in rows])
            if vectors.shape != (len(rows), dimension) or not np.isfinite(vectors).all():
                raise ValueError("stored embedding is invalid")
            query_vector = normalized_query(self.provider, query, dimension)
        except (RuntimeError, ValueError) as exc:
            raise AppError("index_failure", "Knowledge index is temporarily unavailable", 500) from exc
        scores = vectors @ query_vector
        ranked_indices = sorted(range(len(rows)), key=lambda index: (-float(scores[index]), rows[index].chunk_id, rows[index].generation_id))[:limit]
        return [RankedChunk(chunk_id=rows[index].chunk_id, generation_id=rows[index].generation_id, score=float(scores[index])) for index in ranked_indices]


def _authorized_documents(session: Session, actor: User) -> list[KnowledgeDocument]:
    member_project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == actor.id)
    allowed_space_ids = select(KnowledgeSpace.id).where(
        (KnowledgeSpace.kind == KnowledgeSpaceKind.personal) & (KnowledgeSpace.owner_id == actor.id)
        | (KnowledgeSpace.kind == KnowledgeSpaceKind.project) & (KnowledgeSpace.project_id.in_(member_project_ids))
        | KnowledgeSpace.kind.in_((KnowledgeSpaceKind.shared, KnowledgeSpaceKind.standard))
    )
    return list(session.scalars(select(KnowledgeDocument).where(KnowledgeDocument.space_id.in_(allowed_space_ids), KnowledgeDocument.state == KnowledgeState.indexed, KnowledgeDocument.active_generation_id.is_not(None))))


def search(
    session: Session,
    storage: FileStorage,
    query: SearchQuery,
    actor: User,
    backend: SearchBackend | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    allowed_space_ids: frozenset[str] | None = None,
) -> list[SearchHit]:
    documents = _authorized_documents(session, actor)
    if allowed_space_ids is not None:
        # 会话级空间子集（chat 的 knowledge_space_ids）：在用户授权范围内进一步收窄
        documents = [document for document in documents if document.space_id in allowed_space_ids]
    active_generation_ids = {document.active_generation_id for document in documents if document.active_generation_id}
    chunks = list(session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.generation_id.in_(active_generation_ids)))) if active_generation_ids else []
    chunk_by_key = {(chunk.id, chunk.generation_id): chunk for chunk in chunks}
    keyword_backend = backend or SQLiteFtsBackend(session)
    if query.mode == "keyword":
        ranked = keyword_backend.search(query.query, frozenset(active_generation_ids), query.limit)
    else:
        if embedding_provider is None:
            raise AppError("index_failure", "Knowledge index is temporarily unavailable", 500)
        dense_backend = DenseBackend(session, embedding_provider)
        if query.mode == "dense":
            ranked = dense_backend.search(query.query, frozenset(active_generation_ids), query.limit)
        else:
            keyword = keyword_backend.search(query.query, frozenset(active_generation_ids), query.limit)
            dense = dense_backend.search(query.query, frozenset(active_generation_ids), query.limit)
            ranked = reciprocal_rank_fusion([keyword, dense])[:query.limit]
    hits: list[SearchHit] = []
    for item in ranked:
        chunk = chunk_by_key.get((item.chunk_id, item.generation_id))
        if chunk is None:
            continue
        citation = assemble_citation(session, storage, chunk.id, chunk.generation_id)
        hits.append(SearchHit(**citation.model_dump()))
    return hits
