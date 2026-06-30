from __future__ import annotations

import asyncio
import re
from collections import Counter

from ..config import get_settings
from ..db import connect
from .vector_store import VectorStoreError, vector_search


def _tokens(text: str) -> list[str]:
    latin = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    chinese = [text[i : i + 2] for i in range(len(text) - 1) if "\u4e00" <= text[i] <= "\u9fff"]
    return latin + chinese


def keyword_search(question: str, dataset_id: int | None, limit: int = 4) -> list[dict]:
    with connect() as conn:
        if dataset_id:
            rows = conn.execute(
                "SELECT id, title, content, category, dataset_id FROM knowledge_chunks WHERE dataset_id = %s OR dataset_id IS NULL",
                (dataset_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT id, title, content, category, dataset_id FROM knowledge_chunks").fetchall()

    query = Counter(_tokens(question))
    scored = []
    for row in rows:
        text_tokens = Counter(_tokens(f"{row['title']} {row['content']}"))
        score = sum(min(count, text_tokens[token]) for token, count in query.items())
        if score or len(rows) <= limit:
            item = dict(row)
            item["score"] = float(score)
            item["retrieval_mode"] = "keyword"
            scored.append((score, item))
    scored.sort(key=lambda item: (item[0], item[1]["id"]), reverse=True)
    return [item[1] for item in scored[:limit]]


async def search_knowledge(question: str, dataset_id: int | None, limit: int = 4) -> list[dict]:
    settings = get_settings()
    if settings.vector_store.lower() in {"qdrant", "faiss", "milvus"} and settings.embedding_configured:
        try:
            results = await asyncio.wait_for(
                vector_search(question, dataset_id, limit),
                timeout=settings.semantic_search_timeout_seconds,
            )
            if results:
                return results
        except (VectorStoreError, TimeoutError):
            pass
    return keyword_search(question, dataset_id, limit)
