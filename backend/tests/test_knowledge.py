import asyncio

import pytest
from fastapi import HTTPException

from app.db import connect, initialize_database
from app.routers.knowledge import delete_knowledge, list_knowledge
from app.services.knowledge import search_knowledge


def test_delete_knowledge_removes_record(monkeypatch) -> None:
    monkeypatch.setenv("MYSQL_DATABASE", "dataagent_test")
    monkeypatch.setenv("VECTOR_STORE", "disabled")
    initialize_database()

    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO knowledge_chunks(title, content, category) VALUES (%s, %s, %s)",
            ("测试删除片段", "这条知识片段用于验证删除功能。", "business_rule"),
        )
        knowledge_id = int(cursor.lastrowid)

    delete_knowledge(knowledge_id)

    assert all(item["id"] != knowledge_id for item in list_knowledge())


def test_delete_knowledge_returns_404_for_missing_id(monkeypatch) -> None:
    monkeypatch.setenv("MYSQL_DATABASE", "dataagent_test")
    monkeypatch.setenv("VECTOR_STORE", "disabled")
    initialize_database()

    with pytest.raises(HTTPException) as exc_info:
        delete_knowledge(999999)

    assert exc_info.value.status_code == 404


def test_semantic_search_timeout_falls_back_to_keyword(monkeypatch) -> None:
    monkeypatch.setenv("VECTOR_STORE", "qdrant")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv("SEMANTIC_SEARCH_TIMEOUT_SECONDS", "0.1")
    initialize_database()
    with connect() as conn:
        conn.execute(
            "INSERT INTO knowledge_chunks(title, content, category) VALUES (?, ?, ?)",
            ("销售额口径", "销售额等于订单成交金额，不含退款金额。", "metric"),
        )

    async def slow_vector_search(*args, **kwargs):
        await asyncio.sleep(1)
        return [{"id": 1, "retrieval_mode": "hybrid-vector"}]

    monkeypatch.setattr("app.services.knowledge.vector_search", slow_vector_search)
    results = asyncio.run(search_knowledge("销售额怎么计算", None))

    assert results
    assert results[0]["retrieval_mode"] == "keyword"
