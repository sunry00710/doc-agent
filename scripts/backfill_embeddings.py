"""回填历史知识块的语义向量。

背景：早期版本的 ingest 调用未传 embedding_provider（已知缺陷），导致历史索引
只有 FTS 关键词、没有向量，hybrid 搜索静默退化为纯关键词。此脚本为所有「活跃
generation 且缺向量」的知识块补齐向量。

用法（先确保模型可用，见 prefetch_embeddings.py）：
    HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 \
        uv run python scripts/backfill_embeddings.py
    uv run python scripts/backfill_embeddings.py --dry-run   # 只统计不写入
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.knowledge.embeddings import FastEmbedProvider, normalized_documents
from app.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill knowledge chunk embeddings.")
    parser.add_argument("--dry-run", action="store_true", help="只统计缺失数量，不写入")
    args = parser.parse_args(argv)

    settings = Settings()
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    provider = FastEmbedProvider(model_name=settings.embedding_model)

    with factory() as session:
        active_generation_ids = [
            document.active_generation_id
            for document in session.scalars(
                select(KnowledgeDocument).where(KnowledgeDocument.active_generation_id.is_not(None))
            )
            if document.active_generation_id
        ]
        if not active_generation_ids:
            print("没有活跃的知识索引，无需回填。")
            return 0

        existing = set(
            session.execute(
                select(KnowledgeEmbedding.chunk_id).where(
                    KnowledgeEmbedding.generation_id.in_(active_generation_ids)
                )
            ).scalars()
        )
        missing = [
            chunk
            for chunk in session.scalars(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.generation_id.in_(active_generation_ids)
                )
            )
            if chunk.id not in existing
        ]
        print(f"活跃知识块: {len(existing) + len(missing)}，缺向量: {len(missing)}")
        if args.dry_run or not missing:
            return 0

        batch_size = 64
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            vectors = normalized_documents(provider, [chunk.text for chunk in batch])
            for index, chunk in enumerate(batch):
                session.add(
                    KnowledgeEmbedding(
                        chunk_id=chunk.id,
                        generation_id=chunk.generation_id,
                        dimension=int(vectors.shape[1]),
                        vector=vectors[index].tobytes(),
                    )
                )
            session.flush()
            print(f"已回填 {min(start + batch_size, len(missing))}/{len(missing)}")
        session.commit()
        print("回填完成。建议再跑一次 --dry-run 确认缺向量为 0。")
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
