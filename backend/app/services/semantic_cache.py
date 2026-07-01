"""Semantic query cache — accelerates repeated/similar queries.

Embeds user questions and caches responses. New questions within a similarity
threshold reuse cached results, avoiding redundant LLM + SQL + RAG round-trips.
"""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np

from ..db import connect
from .vector_store import embed_texts

# Cosine similarity threshold above which a cached result is reused
SIMILARITY_THRESHOLD = 0.95
# Maximum age of cache entries (seconds) — 30 minutes
MAX_AGE_SECONDS = 30 * 60
# Maximum number of cached entries
MAX_ENTRIES = 200


_async_cache: dict[str, Any] = {}


async def lookup(question: str) -> dict | None:
    """Check if a semantically similar question has been cached.

    Returns the cached AnalysisResult dict, or None on miss.
    """
    try:
        vectors = await embed_texts([question])
    except Exception:
        return None
    query_vec = np.array(vectors[0], dtype=np.float32)

    best_score = 0.0
    best_entry = None
    now = time.time()

    with connect() as conn:
        rows = conn.execute(
            "SELECT question, vector, response, created_at FROM semantic_cache ORDER BY created_at DESC LIMIT ?",
            (MAX_ENTRIES,),
        ).fetchall()

    for row in rows:
        if now - _parse_time(row["created_at"]) > MAX_AGE_SECONDS:
            continue
        try:
            cached_vec = np.array(json.loads(row["vector"]), dtype=np.float32)
            similarity = float(np.dot(query_vec, cached_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(cached_vec)))
            if similarity > best_score:
                best_score = similarity
                best_entry = row
        except (json.JSONDecodeError, ValueError, KeyError):
            continue

    if best_score >= SIMILARITY_THRESHOLD and best_entry:
        try:
            return json.loads(best_entry["response"])
        except json.JSONDecodeError:
            return None
    return None


async def store(question: str, response: dict) -> None:
    """Cache a question-response pair with its embedding vector."""
    try:
        vectors = await embed_texts([question])
        vector_json = json.dumps(vectors[0])
        response_json = json.dumps(response, ensure_ascii=False)
    except Exception:
        return

    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS semantic_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, vector TEXT NOT NULL, response TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        )
        conn.execute(
            "INSERT INTO semantic_cache(question, vector, response) VALUES (?, ?, ?)",
            (question[:500], vector_json, response_json),
        )
        # Evict oldest entries if over limit
        conn.execute(
            "DELETE FROM semantic_cache WHERE id NOT IN (SELECT id FROM semantic_cache ORDER BY created_at DESC LIMIT ?)",
            (MAX_ENTRIES,),
        )


def _parse_time(val: str) -> float:
    try:
        import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        return datetime.datetime.strptime(val[:19], fmt).timestamp()
    except Exception:
        return 0.0
