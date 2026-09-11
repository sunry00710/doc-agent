from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> FloatArray: ...

    @abstractmethod
    def embed_query(self, text: str) -> FloatArray: ...


class FastEmbedProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed_documents(self, texts: list[str]) -> FloatArray:
        return np.asarray(list(self.model.passage_embed(texts)), dtype=np.float32)

    def embed_query(self, text: str) -> FloatArray:
        embeddings = list(self.model.query_embed(text))
        return np.asarray(embeddings[0], dtype=np.float32)


def normalized_documents(provider: EmbeddingProvider, texts: list[str]) -> FloatArray:
    vectors = np.asarray(provider.embed_documents(texts), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(texts) or vectors.shape[1] == 0:
        raise ValueError("document embedding shape is invalid")
    if not np.isfinite(vectors).all():
        raise ValueError("document embeddings must be finite")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("document embeddings must be nonzero")
    return np.asarray(vectors / norms, dtype=np.float32)


def embedding_provider_from_settings(settings: object) -> FastEmbedProvider | None:
    """按配置构造 embedding provider；embedding_enabled=false（离线/关键词模式）时返回 None。"""
    if not getattr(settings, "embedding_enabled", False):
        return None
    return FastEmbedProvider(model_name=settings.embedding_model)


def normalized_query(provider: EmbeddingProvider, text: str, dimension: int) -> FloatArray:
    vector = np.asarray(provider.embed_query(text), dtype=np.float32)
    if vector.ndim != 1 or vector.shape[0] != dimension or not np.isfinite(vector).all():
        raise ValueError("query embedding shape is invalid")
    norm = np.linalg.norm(vector)
    if norm == 0:
        raise ValueError("query embedding must be nonzero")
    return np.asarray(vector / norm, dtype=np.float32)
