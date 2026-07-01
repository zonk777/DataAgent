from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..config import get_settings
from .security import UnsafeQueryError, validate_readonly_sql


def needs_complex_sql(question: str) -> bool:
    """判断问题是否需要 LLM 生成 SQL（模板引擎无法覆盖）。

    覆盖场景：
    - 时间序列分析：同比/环比/移动平均/累计/窗口函数
    - 排名/筛选：TOP N、最高/最低、超过/大于/小于、HAVING
    - 多表/子查询：JOIN、子查询、UNION、EXISTS
    - 统计函数：中位数、标准差、方差、百分位
    - 高级分组：分组排名、每个分组内排序、GROUP_CONCAT
    """
    complex_terms = (
        # 时间序列 & 窗口
        "同比", "环比", "移动平均", "累计", "同比增长", "环比增长",
        "窗口", "rank", "row_number", "lag", "lead",
        "滚动", "滞后", "领先", "累加",
        # 排名 & 极值
        "最高", "最低", "top", "排名", "排行", "第几",
        "最多", "最少", "最大", "最小",
        # 条件筛选
        "超过", "大于", "小于", "高于", "低于", "不低于",
        "having",
        # 多表 & 子查询
        "join", "子查询", "union", "exists",
        # 占比 & 比率
        "占比", "占比变化", "比例", "比率",
        "前后", "对比上",
        # 高级聚合 & 统计
        "中位数", "标准差", "方差", "百分位", "众数",
        "每个.*第", "分组.*前",
    )
    text = question.lower()
    if any(term in text for term in complex_terms):
        return True
    # 额外模式检测：数字 + 排名相关词（如"前5名"、"TOP 10"）
    if re.search(r"(前|top|最[高低大])\s*\d+", text):
        return True
    if re.search(r"每个\S{0,6}(最高|最低|最大|最小|前|top)", text):
        return True
    return False


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
    business_knowledge: list[dict] | None = None,
    intent_reason: str = "",
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
    if intent_reason:
        payload["intent_context"] = intent_reason
    if business_knowledge:
        payload["business_knowledge"] = [
            {
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "category": item.get("category", ""),
            }
            for item in business_knowledge[:5]
        ]

    knowledge_hint = ""
    if business_knowledge:
        knowledge_hint = (
            "请优先使用 business_knowledge 中的指标口径/计算公式生成 SQL。"
            f"例如投诉率 = 投诉数/订单数、转化率 = 转化数/访问数等。"
        )

    intent_hint = ""
    if intent_reason:
        intent_hint = f"当前分析意图: {intent_reason}。请根据此意图选择合理的聚合方式。"

    return [
        {
            "role": "system",
            "content": (
                "你是安全 SQL 生成与修复器。只输出一条只读 SELECT/WITH SQL，不要解释，不要 Markdown。"
                "只能访问给定 table_name；禁止 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE 等写入或管理语句；"
                f"结果必须 LIMIT {limit} 以内。{knowledge_hint}{intent_hint}"
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
    business_knowledge: list[dict] | None = None,
    intent_reason: str = "",
) -> str:
    settings = get_settings()
    messages = _sql_messages(
        question, dataset, limit,
        failed_sql=failed_sql,
        error=error,
        business_knowledge=business_knowledge,
        intent_reason=intent_reason,
    )
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
    business_knowledge: list[dict] | None = None,
    intent_reason: str = "",
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
                business_knowledge=business_knowledge,
                intent_reason=intent_reason,
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


async def generate_llm_sql(
    question: str,
    dataset: dict[str, Any],
    limit: int,
    business_knowledge: list[dict] | None = None,
    intent_reason: str = "",
) -> str | None:
    result = await generate_llm_sql_with_repair(
        question, dataset, limit,
        business_knowledge=business_knowledge,
        intent_reason=intent_reason,
    )
    return result["sql"]


async def repair_llm_sql(
    question: str,
    dataset: dict[str, Any],
    limit: int,
    failed_sql: str,
    error: str,
    business_knowledge: list[dict] | None = None,
    intent_reason: str = "",
) -> str | None:
    result = await generate_llm_sql_with_repair(
        question,
        dataset,
        limit,
        max_attempts=1,
        failed_sql=failed_sql,
        error=error,
        business_knowledge=business_knowledge,
        intent_reason=intent_reason,
    )
    return result["sql"]


def query_plan_source(question: str, llm_sql: str | None) -> str:
    if llm_sql:
        return "llm_sql"
    return "template_sql_complex_fallback" if needs_complex_sql(question) else "template_sql"
