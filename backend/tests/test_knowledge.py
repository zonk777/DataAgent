import pytest
from fastapi import HTTPException

from app.db import connect, initialize_database
from app.routers.knowledge import delete_knowledge, list_knowledge


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
