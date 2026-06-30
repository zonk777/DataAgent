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
        "占比",
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
        text = re.sub(r"^```(?:sql)?\s*\n?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\n?```\s*$", "", text).strip()
    return text


def _sql_messages(
    question: str,
    dataset: dict[str, Any],
    limit: int,
    *,
    failed_sql: str | None = None,
    error: str | None = None,
) -> list[dict[str, str]]:
    payload: dict[str, Any] = {
        "question": question,
        "schema": _schema_payload(dataset),
        "limit": limit,
    }
    if failed_sql or error:
        payload["repair_task"] = {
            "failed_sql": failed_sql or "",
            "error": error or "",
            "instruction": "请根据错误信息修正 SQL。仍然只能输出一条只读 SELECT/WITH 查询。",
        }

    return [
        {
            "role": "system",
            "content": (
                "你是安全 SQL 生成与修复器。只输出一条只读 SELECT/WITH SQL，不要解释，不要 Markdown。"
                "只能访问给定 table_name；禁止 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE 等写入或管理语句；"
                f"结果必须 LIMIT {limit} 以内。"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


async def _request_llm_sql(
    question: str,
    dataset: dict[str, Any],
    limit: int,
    *,
    failed_sql: str | None = None,
    error: str | None = None,
) -> str:
    settings = get_settings()
    messages = _sql_messages(question, dataset, limit, failed_sql=failed_sql, error=error)
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


async def generate_llm_sql_with_repair(
    question: str,
    dataset: dict[str, Any],
    limit: int,
    *,
    max_attempts: int = 3,
    failed_sql: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.llm_configured:
        return {
            "sql": None,
            "attempts": 0,
            "repair_attempts": 0,
            "repaired": False,
            "repair_success_rate": None,
            "errors": [],
        }

    errors: list[dict[str, Any]] = []
    current_failed_sql = failed_sql
    current_error = error
    seeded_repair = bool(failed_sql or error)
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            sql = await _request_llm_sql(
                question,
                dataset,
                limit,
                failed_sql=current_failed_sql,
                error=current_error,
            )
            repair_attempts = max(0, attempt - 1 + (1 if seeded_repair else 0))
            return {
                "sql": sql,
                "attempts": attempt,
                "repair_attempts": repair_attempts,
                "repaired": repair_attempts > 0,
                "repair_success_rate": 1.0 if repair_attempts else None,
                "errors": errors,
            }
        except (httpx.HTTPError, KeyError, TypeError, ValueError, UnsafeQueryError) as exc:
            current_error = str(exc)
            errors.append(
                {
                    "attempt": attempt,
                    "error": current_error,
                    "failed_sql": current_failed_sql,
                }
            )

    repair_attempts = max(0, len(errors) - 1 + (1 if seeded_repair else 0))
    return {
        "sql": None,
        "attempts": len(errors),
        "repair_attempts": repair_attempts,
        "repaired": False,
        "repair_success_rate": 0.0 if repair_attempts else None,
        "errors": errors,
    }


async def generate_llm_sql(question: str, dataset: dict[str, Any], limit: int) -> str | None:
    result = await generate_llm_sql_with_repair(question, dataset, limit)
    return result["sql"]


async def repair_llm_sql(
    question: str,
    dataset: dict[str, Any],
    limit: int,
    failed_sql: str,
    error: str,
) -> str | None:
    result = await generate_llm_sql_with_repair(
        question,
        dataset,
        limit,
        max_attempts=1,
        failed_sql=failed_sql,
        error=error,
    )
    return result["sql"]


def query_plan_source(question: str, llm_sql: str | None) -> str:
    if llm_sql:
        return "llm_sql"
    return "template_sql_complex_fallback" if needs_complex_sql(question) else "template_sql"
