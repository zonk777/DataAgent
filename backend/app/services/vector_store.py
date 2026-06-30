from __future__ import annotations

import atexit
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import QdrantClient, models

from ..config import Settings, get_settings
from ..db import connect


class VectorStoreError(RuntimeError):
    pass


SUPPORTED_VECTOR_STORES = {"qdrant", "faiss", "milvus"}


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


def _store_name(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return settings.vector_store.strip().lower()


def _vector_store_enabled(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return _store_name(settings) in SUPPORTED_VECTOR_STORES and settings.embedding_configured


def _payload(item: dict[str, Any], settings: Settings) -> dict[str, Any]:
    created_at = item["created_at"]
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    return {
        "title": item["title"],
        "content": item["content"],
        "category": item["category"],
        "dataset_id": item["dataset_id"],
        "created_at": created_at,
        "content_hash": _content_hash(item),
        "embedding_model": settings.embedding_model,
    }


_QDRANT_CLIENTS: dict[str, QdrantClient] = {}
_QDRANT_CLIENTS_LOCK = threading.Lock()


def _qdrant_client(path: str) -> QdrantClient:
    with _QDRANT_CLIENTS_LOCK:
        if path not in _QDRANT_CLIENTS:
            _QDRANT_CLIENTS[path] = QdrantClient(path=path)
        return _QDRANT_CLIENTS[path]


def _close_clients() -> None:
    with _QDRANT_CLIENTS_LOCK:
        for client in _QDRANT_CLIENTS.values():
            client.close()
        _QDRANT_CLIENTS.clear()


atexit.register(_close_clients)


def get_vector_client(settings: Settings | None = None) -> QdrantClient:
    """Backward-compatible helper for the Qdrant Local client."""
    settings = settings or get_settings()
    settings.qdrant_directory.mkdir(parents=True, exist_ok=True)
    return _qdrant_client(str(settings.qdrant_directory.resolve()))


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


async def _sync_qdrant(settings: Settings, items: list[dict[str, Any]], force: bool) -> dict[str, Any]:
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
            "store": "qdrant-local",
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
            payload=_payload(item, settings),
        )
        for item, vector in zip(changed, vectors)
    ]
    client.upsert(collection_name=collection_name, points=points, wait=True)
    count = client.count(collection_name=collection_name, exact=True).count
    return {
        "enabled": True,
        "store": "qdrant-local",
        "collection": collection_name,
        "dimension": dimension,
        "indexed_count": count,
        "updated_count": len(points),
    }


def _faiss_import():
    try:
        import faiss  # type: ignore
        import numpy as np
    except ImportError as exc:
        raise VectorStoreError("未安装 FAISS；如需启用 VECTOR_STORE=faiss，请先安装 faiss-cpu") from exc
    return faiss, np


def _faiss_paths(settings: Settings, collection_name: str) -> tuple[Path, Path]:
    directory = settings.faiss_directory / collection_name
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "index.faiss", directory / "metadata.json"


def _read_faiss_metadata(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VectorStoreError("FAISS 元数据文件损坏，请重建索引") from exc
    return list(data.get("items") or [])


def _write_faiss_index(settings: Settings, collection_name: str, entries: list[dict[str, Any]], dimension: int) -> None:
    index_path, metadata_path = _faiss_paths(settings, collection_name)
    if dimension <= 0:
        if index_path.exists():
            index_path.unlink()
        metadata_path.write_text(
            json.dumps({"dimension": 0, "items": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        return
    faiss, np = _faiss_import()
    index = faiss.IndexFlatIP(dimension)
    if entries:
        matrix = np.asarray([entry["vector"] for entry in entries], dtype="float32")
        faiss.normalize_L2(matrix)
        index.add(matrix)
    faiss.write_index(index, str(index_path))
    metadata_path.write_text(
        json.dumps({"dimension": dimension, "items": entries}, ensure_ascii=False),
        encoding="utf-8",
    )


async def _sync_faiss(settings: Settings, items: list[dict[str, Any]], force: bool) -> dict[str, Any]:
    collection_name = _collection_name(settings.embedding_model)
    _, metadata_path = _faiss_paths(settings, collection_name)
    existing_entries = [] if force else _read_faiss_metadata(metadata_path)
    existing = {int(entry["id"]): entry for entry in existing_entries}
    item_ids = {int(item["id"]) for item in items}
    existing = {item_id: entry for item_id, entry in existing.items() if item_id in item_ids}
    changed = [
        item for item in items
        if force
        or int(item["id"]) not in existing
        or existing[int(item["id"])]["payload"].get("content_hash") != _content_hash(item)
    ]

    dimension = int(existing_entries[0]["dimension"]) if existing_entries and existing_entries[0].get("dimension") else 0
    if changed:
        texts = [f"{item['title']}\n{item['content']}" for item in changed]
        vectors = await embed_texts(texts, settings)
        dimension = len(vectors[0])
        for item, vector in zip(changed, vectors):
            existing[int(item["id"])] = {
                "id": int(item["id"]),
                "dimension": dimension,
                "vector": vector,
                "payload": _payload(item, settings),
            }

    entries = [existing[item_id] for item_id in sorted(existing)]
    if entries:
        dimension = int(entries[0].get("dimension") or len(entries[0]["vector"]))
        _write_faiss_index(settings, collection_name, entries, dimension)
    else:
        _write_faiss_index(settings, collection_name, [], 0)

    return {
        "enabled": True,
        "store": "faiss-local",
        "collection": collection_name,
        "dimension": dimension,
        "indexed_count": len(entries),
        "updated_count": len(changed),
    }


def _milvus_client(settings: Settings):
    if not settings.milvus_uri:
        raise VectorStoreError("MILVUS_URI 未配置")
    try:
        from pymilvus import MilvusClient  # type: ignore
    except ImportError as exc:
        raise VectorStoreError("未安装 pymilvus；如需启用 VECTOR_STORE=milvus，请先执行 pip install pymilvus") from exc
    kwargs: dict[str, Any] = {"uri": settings.milvus_uri}
    if settings.milvus_token:
        kwargs["token"] = settings.milvus_token
    if settings.milvus_database:
        kwargs["db_name"] = settings.milvus_database
    return MilvusClient(**kwargs)


async def _sync_milvus(settings: Settings, items: list[dict[str, Any]], force: bool) -> dict[str, Any]:
    collection_name = _collection_name(settings.embedding_model)
    client = _milvus_client(settings)
    exists = client.has_collection(collection_name)
    if force and exists:
        client.drop_collection(collection_name)
        exists = False
    if not items:
        if not exists:
            return {
                "enabled": True,
                "store": "milvus",
                "collection": collection_name,
                "indexed_count": 0,
                "updated_count": 0,
            }
        return {
            "enabled": True,
            "store": "milvus",
            "collection": collection_name,
            "indexed_count": _milvus_count(client, collection_name),
            "updated_count": 0,
        }

    texts = [f"{item['title']}\n{item['content']}" for item in items]
    vectors = await embed_texts(texts, settings)
    dimension = len(vectors[0])
    if not exists:
        client.create_collection(collection_name=collection_name, dimension=dimension, metric_type="COSINE", auto_id=False)

    data = [
        {"id": int(item["id"]), "vector": vector, **_payload(item, settings)}
        for item, vector in zip(items, vectors)
    ]
    client.upsert(collection_name=collection_name, data=data)
    return {
        "enabled": True,
        "store": "milvus",
        "collection": collection_name,
        "dimension": dimension,
        "indexed_count": _milvus_count(client, collection_name),
        "updated_count": len(data),
    }


def _milvus_count(client: Any, collection_name: str) -> int:
    try:
        stats = client.get_collection_stats(collection_name)
        return int(stats.get("row_count", 0))
    except Exception:
        return 0


async def sync_knowledge(force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    store = _store_name(settings)
    if store not in SUPPORTED_VECTOR_STORES:
        return {"enabled": False, "reason": "vector_store_disabled", "indexed_count": 0}
    if not settings.embedding_configured:
        return {"enabled": False, "reason": "embedding_not_configured", "indexed_count": 0}

    items = _load_knowledge()
    if store == "qdrant":
        return await _sync_qdrant(settings, items, force)
    if store == "faiss":
        return await _sync_faiss(settings, items, force)
    if store == "milvus":
        return await _sync_milvus(settings, items, force)
    return {"enabled": False, "reason": "vector_store_disabled", "indexed_count": 0}


def _lexical_bonus(question: str, document: str) -> float:
    normalized_question = (
        question.replace("抱怨", "投诉")
        .replace("成交单", "订单")
        .replace("成交金额", "销售额")
        .replace("购买转化", "转化率")
    )
    metric_terms = ("投诉", "订单", "销售额", "利润", "转化", "访问", "区域", "渠道", "异常")
    matched_terms = sum(1 for term in metric_terms if term in normalized_question and term in document)
    return min(0.3, matched_terms * 0.12)


def _result_from_payload(point_id: int, payload: dict[str, Any], vector_score: float, question: str) -> dict[str, Any]:
    document = f"{payload.get('title', '')} {payload.get('content', '')}"
    return {
        "id": int(point_id),
        "title": payload.get("title", ""),
        "content": payload.get("content", ""),
        "category": payload.get("category", "business_rule"),
        "dataset_id": payload.get("dataset_id"),
        "score": round(vector_score + _lexical_bonus(question, document), 6),
        "vector_score": round(vector_score, 6),
        "retrieval_mode": "hybrid-vector",
    }


def _search_qdrant(settings: Settings, question: str, vector: list[float], dataset_id: int | None, limit: int, collection_name: str) -> list[dict[str, Any]]:
    response = get_vector_client(settings).query_points(
        collection_name=collection_name,
        query=vector,
        limit=max(limit * 4, 12),
        with_payload=True,
        with_vectors=False,
    )
    results: list[dict[str, Any]] = []
    for point in response.points:
        payload = dict(point.payload or {})
        point_dataset_id = payload.get("dataset_id")
        if dataset_id is not None and point_dataset_id not in (None, dataset_id):
            continue
        results.append(_result_from_payload(int(point.id), payload, float(point.score), question))
    return results


def _search_faiss(settings: Settings, question: str, vector: list[float], dataset_id: int | None, limit: int, collection_name: str) -> list[dict[str, Any]]:
    faiss, np = _faiss_import()
    index_path, metadata_path = _faiss_paths(settings, collection_name)
    entries = _read_faiss_metadata(metadata_path)
    if not index_path.exists() or not entries:
        return []
    index = faiss.read_index(str(index_path))
    query = np.asarray([vector], dtype="float32")
    faiss.normalize_L2(query)
    top_k = min(max(limit * 4, 12), len(entries))
    scores, positions = index.search(query, top_k)
    results: list[dict[str, Any]] = []
    for score, position in zip(scores[0], positions[0]):
        if position < 0:
            continue
        entry = entries[int(position)]
        payload = dict(entry.get("payload") or {})
        point_dataset_id = payload.get("dataset_id")
        if dataset_id is not None and point_dataset_id not in (None, dataset_id):
            continue
        results.append(_result_from_payload(int(entry["id"]), payload, float(score), question))
    return results


def _search_milvus(settings: Settings, question: str, vector: list[float], dataset_id: int | None, limit: int, collection_name: str) -> list[dict[str, Any]]:
    client = _milvus_client(settings)
    rows = client.search(
        collection_name=collection_name,
        data=[vector],
        limit=max(limit * 4, 12),
        output_fields=["title", "content", "category", "dataset_id", "created_at", "content_hash", "embedding_model"],
    )
    hits = rows[0] if rows else []
    results: list[dict[str, Any]] = []
    for hit in hits:
        entity = dict(hit.get("entity") or {})
        point_id = int(hit.get("id") or entity.get("id"))
        point_dataset_id = entity.get("dataset_id")
        if dataset_id is not None and point_dataset_id not in (None, dataset_id):
            continue
        vector_score = float(hit.get("distance", hit.get("score", 0)))
        results.append(_result_from_payload(point_id, entity, vector_score, question))
    return results


def _search_faiss(settings: Settings, question: str, vector: list[float], dataset_id: int | None, limit: int) -> list[dict[str, Any]]:
    """FAISS local search — lightweight alternative to Qdrant."""
    try:
        import numpy as np
        import faiss
    except ImportError:
        raise VectorStoreError("未安装 faiss-cpu，无法使用 FAISS 检索；请先执行 pip install faiss-cpu numpy") from None

    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, content, category FROM knowledge_chunks" + (" WHERE dataset_id = ? OR dataset_id IS NULL" if dataset_id else "") + " ORDER BY id",
            (dataset_id,) if dataset_id else (),
        ).fetchall()

    if not rows:
        return []

    chunks = [dict(row) for row in rows]
    embeddings_path = settings.qdrant_directory / "faiss_embeddings.json"
    chunk_ids: list[int] = []
    stored_vectors: list[list[float]] | None = None

    if embeddings_path.exists():
        try:
            cached = json.loads(embeddings_path.read_text(encoding="utf-8"))
            stored_vectors = cached.get("vectors", [])
            chunk_ids = cached.get("ids", [])
        except (json.JSONDecodeError, KeyError):
            stored_vectors = None

    current_ids = [c["id"] for c in chunks]
    if stored_vectors is None or chunk_ids != current_ids:
        vecs = _embed_with_fallback([c["content"][:2000] for c in chunks], settings)
        stored_vectors = vecs if vecs else None
        if stored_vectors:
            embeddings_path.parent.mkdir(parents=True, exist_ok=True)
            embeddings_path.write_text(json.dumps({"ids": current_ids, "vectors": stored_vectors}), encoding="utf-8")

    if not stored_vectors:
        return _keyword_fallback_search(question, chunks, limit)

    dim = len(stored_vectors[0])
    index = faiss.IndexFlatIP(dim)
    emb_array = np.array(stored_vectors, dtype=np.float32)
    faiss.normalize_L2(emb_array)
    index.add(emb_array)

    query_vec = np.array([vector], dtype=np.float32)
    faiss.normalize_L2(query_vec)
    scores, indices = index.search(query_vec, min(limit * 2, len(chunks)))

    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    for idx_list, score_list in zip(indices, scores):
        for idx, score in zip(idx_list, score_list):
            if idx < 0 or idx >= len(chunks) or idx in seen:
                continue
            seen.add(idx)
            chunk = chunks[idx]
            results.append({
                "id": chunk["id"],
                "title": chunk["title"],
                "content": chunk["content"],
                "category": chunk.get("category", ""),
                "score": round(float(score), 4),
                "retrieval_mode": "faiss-semantic",
            })
    return results[:limit]


async def vector_search(question: str, dataset_id: int | None, limit: int = 4) -> list[dict[str, Any]]:
    settings = get_settings()
    status = await sync_knowledge()
    if not status.get("enabled") or not status.get("collection"):
        raise VectorStoreError(str(status.get("reason") or "向量索引未启用"))

    vector = (await embed_texts([question], settings))[0]
    store = _store_name(settings)
    collection_name = str(status["collection"])
    if store == "qdrant":
        results = _search_qdrant(settings, question, vector, dataset_id, limit, collection_name)
    elif store == "faiss":
        results = _search_faiss(settings, question, vector, dataset_id, limit)
    elif store == "milvus":
        raise VectorStoreError("Milvus 适配器规划中，当前请使用 qdrant 或 faiss")
    elif store == "faiss":
        results = _search_faiss(settings, question, vector, dataset_id, limit, collection_name)
    elif store == "milvus":
        results = _search_milvus(settings, question, vector, dataset_id, limit, collection_name)
    else:
        raise VectorStoreError("向量索引未启用")
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def vector_status() -> dict[str, Any]:
    settings = get_settings()
    store = _store_name(settings)
    base = {
        "enabled": _vector_store_enabled(settings),
        "store": store,
        "model": settings.embedding_model if settings.embedding_configured else None,
        "indexed_count": 0,
    }
    if not base["enabled"]:
        if store not in SUPPORTED_VECTOR_STORES:
            base["reason"] = "vector_store_disabled"
        elif not settings.embedding_configured:
            base["reason"] = "embedding_not_configured"
        return base

    collection_name = _collection_name(settings.embedding_model)
    base["collection"] = collection_name
    if store == "qdrant":
        client = get_vector_client(settings)
        base["store"] = "qdrant-local"
        if client.collection_exists(collection_name):
            base["indexed_count"] = client.count(collection_name=collection_name, exact=True).count
    elif store == "faiss":
        base["store"] = "faiss-local"
        _, metadata_path = _faiss_paths(settings, collection_name)
        try:
            base["indexed_count"] = len(_read_faiss_metadata(metadata_path))
        except VectorStoreError as exc:
            base["error"] = str(exc)
    elif store == "milvus":
        base["store"] = "milvus"
        try:
            client = _milvus_client(settings)
            if client.has_collection(collection_name):
                base["indexed_count"] = _milvus_count(client, collection_name)
        except VectorStoreError as exc:
            base["enabled"] = False
            base["error"] = str(exc)
    return base


def _delete_faiss_vectors(settings: Settings, ids: list[int], collection_name: str) -> dict[str, Any]:
    _, metadata_path = _faiss_paths(settings, collection_name)
    entries = [entry for entry in _read_faiss_metadata(metadata_path) if int(entry["id"]) not in set(ids)]
    dimension = int(entries[0].get("dimension") or len(entries[0]["vector"])) if entries else 0
    _write_faiss_index(settings, collection_name, entries, dimension)
    return {
        "enabled": True,
        "collection": collection_name,
        "deleted_count": len(ids),
        "indexed_count": len(entries),
    }


def delete_knowledge_vectors(ids: list[int]) -> dict[str, Any]:
    settings = get_settings()
    store = _store_name(settings)
    if store not in SUPPORTED_VECTOR_STORES:
        return {"enabled": False, "reason": "vector_store_disabled", "deleted_count": 0}
    if not ids:
        return {"enabled": True, "deleted_count": 0}

    collection_name = _collection_name(settings.embedding_model)
    if store == "qdrant":
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
    if store == "faiss":
        return _delete_faiss_vectors(settings, [int(item) for item in ids], collection_name)
    if store == "milvus":
        client = _milvus_client(settings)
        if client.has_collection(collection_name):
            client.delete(collection_name=collection_name, ids=[int(item) for item in ids])
        return {
            "enabled": True,
            "collection": collection_name,
            "deleted_count": len(ids),
            "indexed_count": _milvus_count(client, collection_name) if client.has_collection(collection_name) else 0,
        }
    return {"enabled": False, "reason": "vector_store_disabled", "deleted_count": 0}
