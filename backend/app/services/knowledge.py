"""RAG knowledge retrieval with Round 2 enhancements.

R-003: LLM query rewriting — resolves pronouns, converts colloquial to formal,
       and extracts keywords before embedding.
R-004: Multi-path parallel recall — semantic (Qdrant/FAISS) + keyword (SQLite TF)
       + title exact match, all executed concurrently then merged.
R-005: Coarse-to-fine ranking — LLM pairwise comparison re-ranks top candidates
       after initial retrieval.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter

from ..config import get_settings
from ..db import connect
from .vector_store import VectorStoreError, vector_search


# ---------------------------------------------------------------------------
# R-003: Query rewriting
# ---------------------------------------------------------------------------
async def rewrite_query(question: str, history: list[dict] | None = None) -> str:
    """Use LLM to rewrite the query for better retrieval:

    - Resolve pronouns ("它的" → actual entity from history)
    - Convert colloquial to formal ("卖得最差的" → "销售额最低的")
    - Extract key search terms
    """
    settings = get_settings()
    if not settings.llm_configured:
        return question

    history_hint = ""
    if history:
        last_user = None
        for m in reversed(history):
            if m.get("role") == "user" and m.get("content"):
                last_user = str(m["content"])[:200]
                break
        if last_user:
            history_hint = f"\n上一轮问题: {last_user}"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0,
                    "max_tokens": 80,
                    "messages": [{
                        "role": "user",
                        "content": (
                            "将用户的查询改写为适合语义检索的关键词短语（不超过30字）。"
                            "消解指代（'它的'→具体实体），口语转书面（'卖得最差'→'销售额最低'）。"
                            f"只输出改写后的短语。{history_hint}\n\n查询: {question}"
                        ),
                    }],
                },
            )
            resp.raise_for_status()
            rewritten = resp.json()["choices"][0]["message"]["content"].strip()
            return rewritten if rewritten and len(rewritten) >= 2 else question
    except Exception:
        return question


# ---------------------------------------------------------------------------
# R-004: Multi-path parallel recall
# ---------------------------------------------------------------------------
def _tokens(text: str) -> list[str]:
    latin = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    chinese = [text[i : i + 2] for i in range(len(text) - 1) if "一" <= text[i] <= "鿿"]
    return latin + chinese


def keyword_search(question: str, dataset_id: int | None, limit: int = 5) -> list[dict]:
    """SQLite keyword TF matching."""
    with connect() as conn:
        if dataset_id:
            rows = conn.execute(
                "SELECT id, title, content, category, dataset_id FROM knowledge_chunks WHERE dataset_id = ? OR dataset_id IS NULL",
                (dataset_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT id, title, content, category, dataset_id FROM knowledge_chunks").fetchall()

    query = Counter(_tokens(question))
    scored = []
    for row in rows:
        text_tokens = Counter(_tokens(f"{row['title']} {row['content']}"))
        score = sum(min(count, text_tokens[token]) for token, count in query.items())
        item = dict(row)
        item["score"] = float(score)
        item["retrieval_mode"] = "keyword"
        scored.append((score, item))
    scored.sort(key=lambda item: (item[0], item[1]["id"]), reverse=True)
    return [item[1] for item in scored[:limit]]


def title_search(question: str, dataset_id: int | None, limit: int = 3) -> list[dict]:
    """Exact/semi-exact title match (high precision, low recall)."""
    with connect() as conn:
        if dataset_id:
            rows = conn.execute(
                "SELECT id, title, content, category, dataset_id FROM knowledge_chunks WHERE (dataset_id = ? OR dataset_id IS NULL) AND title LIKE ?",
                (dataset_id, f"%{question[:20]}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, content, category, dataset_id FROM knowledge_chunks WHERE title LIKE ?",
                (f"%{question[:20]}%",),
            ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["score"] = 0.95
        item["retrieval_mode"] = "title_match"
        results.append(item)
    return results[:limit]


async def search_knowledge(question: str, dataset_id: int | None, limit: int = 4) -> list[dict]:
    """Multi-path parallel recall + merge + dedup."""
    settings = get_settings()

    # R-003: rewrite query before retrieval
    rewritten = await rewrite_query(question)

    # R-004: parallel three-path recall
    tasks = []
    tasks.append(keyword_search_async(question, dataset_id, limit * 2))
    tasks.append(title_search_async(question, dataset_id, 3))

    if settings.vector_store.lower() in {"qdrant", "faiss", "milvus"} and settings.embedding_configured:
        tasks.append(vector_search_async(rewritten, question, dataset_id, limit * 2))

    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge and deduplicate
    merged: dict[int, dict] = {}
    for results in results_list:
        if isinstance(results, list):
            for r in results:
                rid = r["id"]
                if rid not in merged or r.get("score", 0) > merged[rid].get("score", 0):
                    merged[rid] = r

    candidates = sorted(merged.values(), key=lambda x: x.get("score", 0), reverse=True)
    top_k = candidates[:limit * 2]

    # R-005: LLM pairwise reranking
    if settings.llm_configured and len(top_k) > limit:
        top_k = await llm_rerank(question, top_k, limit)

    # Fallback to keyword-only if everything failed
    if not top_k:
        kw = [r for r in results_list if isinstance(r, list)]
        for r_list in kw:
            if r_list:
                return r_list[:limit]

    return top_k[:limit]


# ---------------------------------------------------------------------------
# R-005: LLM pairwise reranking
# ---------------------------------------------------------------------------
async def llm_rerank(question: str, candidates: list[dict], top_n: int = 4) -> list[dict]:
    """Use LLM to pick the most relevant candidates from a shortlist.

    Instead of expensive pairwise comparison, uses a single prompt to rank all.
    """
    settings = get_settings()
    if len(candidates) <= top_n:
        return candidates

    # Build a numbered list for the LLM to select from
    items_text = []
    for i, c in enumerate(candidates[:10], 1):
        items_text.append(f"[{i}] {c['title']} | {c.get('category','')} | {c['content'][:150]}")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0,
                    "max_tokens": 30,
                    "messages": [{
                        "role": "user",
                        "content": (
                            f"从以下知识片段中选择与问题最相关的{top_n}条（只输出编号，用逗号分隔，如 '1,3,5,7'）：\n"
                            f"问题: {question}\n\n" + "\n".join(items_text)
                        ),
                    }],
                },
            )
            resp.raise_for_status()
            selection = resp.json()["choices"][0]["message"]["content"].strip()
            # Parse "1,3,5,7" or "1 3 5 7"
            indices = [int(x) - 1 for x in re.findall(r"\d+", selection) if 1 <= int(x) <= len(candidates)]
            if indices:
                ranked = [candidates[i] for i in indices if i < len(candidates)]
                # Add rerank metadata
                for r in ranked:
                    r["reranked"] = True
                return ranked[:top_n]
    except Exception:
        pass
    return candidates[:top_n]


# ---------------------------------------------------------------------------
# Async wrappers for parallel execution
# ---------------------------------------------------------------------------
async def keyword_search_async(question: str, dataset_id: int | None, limit: int) -> list[dict]:
    return keyword_search(question, dataset_id, limit)


async def title_search_async(question: str, dataset_id: int | None, limit: int) -> list[dict]:
    return title_search(question, dataset_id, limit)


async def vector_search_async(rewritten: str, original: str, dataset_id: int | None, limit: int) -> list[dict]:
    """Vector search with fallback through original question."""
    settings = get_settings()
    try:
        result = await asyncio.wait_for(
            vector_search(rewritten, dataset_id, limit),
            timeout=settings.semantic_search_timeout_seconds,
        )
        if result:
            return result
    except (VectorStoreError, asyncio.TimeoutError):
        pass
    # Fallback: try original question
    if rewritten != original:
        try:
            result = await asyncio.wait_for(
                vector_search(original, dataset_id, limit),
                timeout=settings.semantic_search_timeout_seconds,
            )
            if result:
                return result
        except (VectorStoreError, asyncio.TimeoutError):
            pass
    return []
