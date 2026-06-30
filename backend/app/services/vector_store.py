from __future__ import annotations

import hashlib
import atexit
import threading
from typing import Any

import httpx
from qdrant_client import QdrantClient, models

from ..config import Settings, get_settings
from ..db import connect


class VectorStoreError(RuntimeError):
    pass


def _embedding_url(settings: Settings) -> str:
    base = settings.embedding_base_url.rstrip("/")
    return base if base.endswith("/embeddings") else f"{base}/embeddings"


def _collection_name(model_name: str) -> str:
    model_hash = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:12]
    return f"knowledge_{model_hash}"


def _content_hash(item: dict[str, Any]) -> str:
    content = "\n".join(
        str(item.get(key) or "") for key in ("title", "content", "category", "dataset_id")
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


_CLIENTS: dict[str, QdrantClient] = {}
_CLIENTS_LOCK = threading.Lock()


def _client(path: str) -> QdrantClient:
    with _CLIENTS_LOCK:
        if path not in _CLIENTS:
            _CLIENTS[path] = QdrantClient(path=path)
        return _CLIENTS[path]


def _close_clients() -> None:
    with _CLIENTS_LOCK:
        for client in _CLIENTS.values():
            client.close()
        _CLIENTS.clear()


atexit.register(_close_clients)


def get_vector_client(settings: Settings | None = None) -> QdrantClient:
    settings = settings or get_settings()
    settings.qdrant_directory.mkdir(parents=True, exist_ok=True)
    return _client(str(settings.qdrant_directory.resolve()))


async def embed_texts(texts: list[str], settings: Settings | None = None) -> list[list[float]]:
    settings = settings or get_settings()
    if not settings.embedding_configured:
        raise VectorStoreError("Embedding 服务尚未配置")
    if not texts:
        return []

    vectors: list[list[float]] = []
    headers = {"Authorization": f"Bearer {settings.embedding_api_key}"}
    async with httpx.AsyncClient(timeout=60) as client:
        for start in range(0, len(texts), 24):
            batch = texts[start : start + 24]
            try:
                response = await client.post(
                    _embedding_url(settings),
                    headers=headers,
                    json={
                        "model": settings.embedding_model,
                        "input": batch,
                        "encoding_format": "float",
                    },
                )
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda item: item.get("index", 0))
                batch_vectors = [item["embedding"] for item in data]
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                raise VectorStoreError(f"Embedding 请求失败：{type(exc).__name__}") from exc
            if len(batch_vectors) != len(batch) or not all(isinstance(vector, list) and vector for vector in batch_vectors):
                raise VectorStoreError("Embedding 服务返回的向量数量或格式无效")
            vectors.extend(batch_vectors)
    return vectors


def _load_knowledge() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, content, category, dataset_id, created_at FROM knowledge_chunks ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


async def sync_knowledge(force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    if settings.vector_store.lower() != "qdrant":
        return {"enabled": False, "reason": "vector_store_disabled", "indexed_count": 0}
    if not settings.embedding_configured:
        return {"enabled": False, "reason": "embedding_not_configured", "indexed_count": 0}

    items = _load_knowledge()
    collection_name = _collection_name(settings.embedding_model)
    client = get_vector_client(settings)
    exists = client.collection_exists(collection_name)

    existing: dict[int, dict[str, Any]] = {}
    if exists and not force and items:
        records = client.retrieve(
            collection_name=collection_name,
            ids=[int(item["id"]) for item in items],
            with_payload=True,
            with_vectors=False,
        )
        existing = {int(record.id): dict(record.payload or {}) for record in records}

    changed = [
        item for item in items
        if force or int(item["id"]) not in existing or existing[int(item["id"])].get("content_hash") != _content_hash(item)
    ]
    if not changed:
        count = client.count(collection_name=collection_name, exact=True).count if exists else 0
        return {
            "enabled": True,
            "collection": collection_name,
            "indexed_count": count,
            "updated_count": 0,
        }

    texts = [f"{item['title']}\n{item['content']}" for item in changed]
    vectors = await embed_texts(texts, settings)
    dimension = len(vectors[0])

    if force and exists:
        client.delete_collection(collection_name)
        exists = False
    if not exists:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
        )

    points = [
        models.PointStruct(
            id=int(item["id"]),
            vector=vector,
            payload={
                "title": item["title"],
                "content": item["content"],
                "category": item["category"],
                "dataset_id": item["dataset_id"],
                "created_at": item["created_at"],
                "content_hash": _content_hash(item),
                "embedding_model": settings.embedding_model,
            },
        )
        for item, vector in zip(changed, vectors)
    ]
    client.upsert(collection_name=collection_name, points=points, wait=True)
    count = client.count(collection_name=collection_name, exact=True).count
    return {
        "enabled": True,
        "collection": collection_name,
        "dimension": dimension,
        "indexed_count": count,
        "updated_count": len(points),
    }


async def vector_search(question: str, dataset_id: int | None, limit: int = 4) -> list[dict[str, Any]]:
    settings = get_settings()
    status = await sync_knowledge()
    if not status.get("enabled") or not status.get("collection"):
        raise VectorStoreError(str(status.get("reason") or "向量索引未启用"))

    vector = (await embed_texts([question], settings))[0]
    response = get_vector_client(settings).query_points(
        collection_name=status["collection"],
        query=vector,
        limit=max(limit * 4, 12),
        with_payload=True,
        with_vectors=False,
    )
    normalized_question = (
        question.replace("抱怨", "投诉")
        .replace("成交单", "订单")
        .replace("成交金额", "销售额")
        .replace("购买转化", "转化率")
    )
    metric_terms = ("投诉", "订单", "销售额", "利润", "转化", "访问", "区域", "渠道", "异常")
    results: list[dict[str, Any]] = []
    for point in response.points:
        payload = dict(point.payload or {})
        point_dataset_id = payload.get("dataset_id")
        if dataset_id is not None and point_dataset_id not in (None, dataset_id):
            continue
        document = f"{payload.get('title', '')} {payload.get('content', '')}"
        matched_terms = sum(1 for term in metric_terms if term in normalized_question and term in document)
        lexical_bonus = min(0.3, matched_terms * 0.12)
        vector_score = float(point.score)
        results.append(
            {
                "id": int(point.id),
                "title": payload.get("title", ""),
                "content": payload.get("content", ""),
                "category": payload.get("category", "business_rule"),
                "dataset_id": point_dataset_id,
                "score": round(vector_score + lexical_bonus, 6),
                "vector_score": round(vector_score, 6),
                "retrieval_mode": "hybrid-vector",
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def vector_status() -> dict[str, Any]:
    settings = get_settings()
    base = {
        "enabled": settings.vector_store.lower() == "qdrant" and settings.embedding_configured,
        "store": "qdrant-local",
        "model": settings.embedding_model if settings.embedding_configured else None,
        "indexed_count": 0,
    }
    if not base["enabled"]:
        return base
    collection_name = _collection_name(settings.embedding_model)
    client = get_vector_client(settings)
    if client.collection_exists(collection_name):
        base["collection"] = collection_name
        base["indexed_count"] = client.count(collection_name=collection_name, exact=True).count
    return base


def delete_knowledge_vectors(ids: list[int]) -> dict[str, Any]:
    settings = get_settings()
    if settings.vector_store.lower() != "qdrant":
        return {"enabled": False, "reason": "vector_store_disabled", "deleted_count": 0}
    if not ids:
        return {"enabled": True, "deleted_count": 0}

    collection_name = _collection_name(settings.embedding_model)
    client = get_vector_client(settings)
    if not client.collection_exists(collection_name):
        return {"enabled": True, "collection": collection_name, "deleted_count": 0}

    try:
        client.delete(
            collection_name=collection_name,
            points_selector=models.PointIdsList(points=[int(item) for item in ids]),
            wait=True,
        )
    except Exception as exc:  # pragma: no cover - depends on local Qdrant file state
        raise VectorStoreError(f"向量索引删除失败：{type(exc).__name__}") from exc

    indexed_count = client.count(collection_name=collection_name, exact=True).count
    return {
        "enabled": True,
        "collection": collection_name,
        "deleted_count": len(ids),
        "indexed_count": indexed_count,
    }
