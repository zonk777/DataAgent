from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..config import get_settings
from .security import UnsafeQueryError, validate_readonly_sql


def needs_complex_sql(question: str) -> bool:
    complex_terms = (
        "同比",
        "环比",
        "移动平均",
        "累计",
        "占总",
        "占比变化",
        "前后",
        "对比上",
        "同比增长",
        "环比增长",
        "窗口",
        "rank",
    )
    return any(term in question.lower() for term in complex_terms)


def _schema_payload(dataset: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_name": dataset["table_name"],
        "columns": [
            {
                "name": column["name"],
                "data_type": column.get("data_type", ""),
                "description": column.get("description", ""),
            }
            for column in dataset.get("columns", [])
        ],
    }


def _strip_sql_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:sql)?|```$", "", text, flags=re.IGNORECASE | re.MULTILINE).strip()
    return text


async def generate_llm_sql(question: str, dataset: dict[str, Any], limit: int) -> str | None:
    settings = get_settings()
    if not settings.llm_configured:
        return None
    schema = _schema_payload(dataset)
    messages = [
        {
            "role": "system",
            "content": (
                "你是安全 SQL 生成器。只输出一条只读 SELECT SQL，不要解释，不要 Markdown。"
                "只能访问给定 table_name；禁止 INSERT/UPDATE/DELETE/DROP/ALTER；"
                f"结果必须 LIMIT {limit} 以内。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"question": question, "schema": schema, "limit": limit}, ensure_ascii=False),
        },
    ]
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={"model": settings.llm_model, "temperature": 0, "messages": messages},
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            sql = _strip_sql_fences(content)
            if not re.search(r"\bLIMIT\s+\d+\b", sql, flags=re.IGNORECASE):
                sql = f"{sql.rstrip(';')} LIMIT {limit}"
            return validate_readonly_sql(sql, dataset["table_name"])
    except (httpx.HTTPError, KeyError, TypeError, ValueError, UnsafeQueryError):
        return None


def query_plan_source(question: str, llm_sql: str | None) -> str:
    if llm_sql:
        return "llm_sql"
    return "template_sql_complex_fallback" if needs_complex_sql(question) else "template_sql"
