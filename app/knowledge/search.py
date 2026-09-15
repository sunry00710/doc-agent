from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from itertools import pairwise

import numpy as np
from sqlalchemy import func, select, text
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


def _is_cjk(character: str) -> bool:
    return "\u4e00" <= character <= "\u9fff"


def _query_terms(query: str) -> list[str]:
    """把查询拆成与索引侧一致的检索单元。

    索引侧由 `ingestion._fts_text` 把每个汉字单独成词（标题路径同样入索引），
    因此查询侧也必须逐字拆开；拉丁词与数字保持整词。
    """
    terms: list[str] = []
    for part in re.findall(r"[\w]+", query, flags=re.UNICODE):
        if any(_is_cjk(character) for character in part):
            terms.extend(character for character in part if _is_cjk(character))
        else:
            terms.append(part)
    return terms


def _fts_query(query: str) -> str:
    """精度优先：所有检索单元必须命中同一块。"""
    return " AND ".join(f'"{term}"' for term in _query_terms(query))


def _fts_query_any(query: str) -> str:
    """召回优先：任一「相邻两字短语」命中即可，由 bm25 排序。

    索引里的单字 token 保留了原文顺序，因此 FTS5 短语查询（`"差 旅"`）等价于
    一次 bigram 匹配。用它兜底而不是用单字 OR，可以避免「量子计算」这类查询
    仅凭一个「计」字就匹配到「计算机」，把无关内容灌进上下文。
    """
    phrases: list[str] = []
    for part in re.findall(r"[\w]+", query, flags=re.UNICODE):
        characters = [character for character in part if _is_cjk(character)]
        phrases.extend(f'"{first} {second}"' for first, second in pairwise(characters))
    return " OR ".join(dict.fromkeys(phrases))


class SearchBackend(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        authorized_generation_ids: frozenset[str],
        limit: int,
    ) -> list[RankedChunk]: ...


class SQLiteFtsBackend(SearchBackend):
    """SQLite FTS adapter; authorization IDs are applied inside the ranked query.

    有意的降级检索：先按单字 AND 取精确结果，零命中时再用相邻二字短语兜底召回。
    中文按单字建索引（见 `ingestion._fts_text`），AND 检索式的约束强度与「输入了多少个字」
    成正比而非与「表达了多少个概念」成正比——实测「差旅补助」能命中而「差旅补助标准」
    返回空，长自然语言查询因此在关键词模式下搜不到内容。

    两个边界：拉丁词是整词 token，AND（"两个词都要出现"）本就是预期语义，不参与降级；
    汉字数量不足两个时也没有可用的 bigram，同样不降级。两种情况都会得到空的兜底检索式。
    """

    def __init__(self, session: Session):
        self.session = session

    def _run(self, fts_query: str, authorized_generation_ids: frozenset[str], limit: int) -> list[RankedChunk]:
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
        ranked = self._run(fts_query, authorized_generation_ids, limit)
        if ranked:
            return ranked
        fallback = _fts_query_any(query)
        if not fallback:
            return ranked
        return self._run(fallback, authorized_generation_ids, limit)


class DenseBackend:
    """SQLite 下的暴力向量检索：把授权范围内的向量全部载入内存做点积，没有 ANN 索引。

    候选上限 `_DENSE_CANDIDATE_LIMIT` 用于兜住内存，但**不能**用 `ORDER BY ... LIMIT`
    来实现：那不是「取最相似的 N 个」，而是按 chunk_id 字典序任意丢弃——一旦超过阈值，
    结果就会静默出错（漏掉更相似的块，界面上却看不出任何异常）。因此这里先计数，
    超限直接报错，与既有「语义检索硬失败」的取舍保持一致：宁可失败，也不返回一个
    看起来正常但实际不完整的子集。
    """

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
            candidates = self.session.scalar(
                select(func.count())
                .select_from(KnowledgeEmbedding)
                .where(KnowledgeEmbedding.generation_id.in_(authorized_generation_ids))
            )
            if not candidates:
                return []
            if candidates > _DENSE_CANDIDATE_LIMIT:
                raise AppError(
                    "index_failure",
                    "Knowledge index exceeds the brute-force vector search limit "
                    f"({candidates} > {_DENSE_CANDIDATE_LIMIT} vectors); move to an "
                    "ANN-indexed vector store before enabling dense or hybrid retrieval",
                    500,
                )
            rows = (
                self.session.execute(
                    select(KnowledgeEmbedding).where(
                        KnowledgeEmbedding.generation_id.in_(authorized_generation_ids)
                    )
                )
                .scalars()
                .all()
            )
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
    elif query.mode == "dense":
        # 明确要求向量检索但未配置 embedding：这是配置错误，直接报错
        if embedding_provider is None:
            raise AppError("index_failure", "Knowledge index is temporarily unavailable", 500)
        ranked = DenseBackend(session, embedding_provider).search(query.query, frozenset(active_generation_ids), query.limit)
    else:
        # hybrid：embedding 未启用时降级为纯关键词（配置关闭语义检索是合法选择，不应报错）
        keyword = keyword_backend.search(query.query, frozenset(active_generation_ids), query.limit)
        if embedding_provider is None:
            ranked = keyword
        else:
            dense = DenseBackend(session, embedding_provider).search(query.query, frozenset(active_generation_ids), query.limit)
            ranked = reciprocal_rank_fusion([keyword, dense])[:query.limit]
    hits: list[SearchHit] = []
    for item in ranked:
        chunk = chunk_by_key.get((item.chunk_id, item.generation_id))
        if chunk is None:
            continue
        citation = assemble_citation(session, storage, chunk.id, chunk.generation_id)
        hits.append(SearchHit(**citation.model_dump()))
    return hits
