from __future__ import annotations

import json
import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

from ..config import get_settings
from ..db import connect
from .knowledge import search_knowledge
from .llm import answer_from_knowledge, polish_insights
from .security import validate_readonly_sql

logger = logging.getLogger(__name__)


REGIONS = ["华东", "华南", "华北", "西南"]


@dataclass
class QueryPlan:
    sql: str
    params: list[Any]
    x_field: str
    y_field: str
    series_field: str | None
    series_fields: list[str]
    time_description: str | None


def _dataset(dataset_id: int | None) -> dict:
    with connect() as conn:
        if dataset_id:
            row = conn.execute("SELECT * FROM datasets WHERE id = %s", (dataset_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM datasets ORDER BY id LIMIT 1").fetchone()
        columns = [] if not row else [
            dict(item)
            for item in conn.execute(
                "SELECT name, data_type, description FROM dataset_columns WHERE dataset_id = %s ORDER BY id",
                (row["id"],),
            ).fetchall()
        ]
    if not row:
        raise ValueError("没有可用数据集，请先上传数据")
    result = dict(row)
    result["columns"] = columns
    return result


def _find_column(columns: list[dict], keywords: tuple[str, ...], numeric: bool | None = None) -> str | None:
    numeric_types = ("int", "float", "double", "decimal", "real", "number")
    for column in columns:
        haystack = f"{column['name']} {column.get('description', '')}".lower()
        is_numeric = any(token in column["data_type"].lower() for token in numeric_types)
        if numeric is not None and is_numeric != numeric:
            continue
        if any(keyword.lower() in haystack for keyword in keywords):
            return column["name"]
    return None


def _column_profile(columns: list[dict]) -> dict[str, str | None]:
    numeric_types = ("int", "float", "double", "decimal", "real", "number")
    first_numeric = next(
        (item["name"] for item in columns if any(token in item["data_type"].lower() for token in numeric_types)),
        None,
    )
    first_dimension = next(
        (item["name"] for item in columns if not any(token in item["data_type"].lower() for token in numeric_types)),
        columns[0]["name"] if columns else None,
    )
    return {
        "date": _find_column(columns, ("date", "time", "日期", "时间")),
        "region": _find_column(columns, ("region", "area", "地区", "区域")),
        "product": _find_column(columns, ("product", "category", "产品", "品类", "类别")),
        "channel": _find_column(columns, ("channel", "渠道")),
        "sales": _find_column(columns, ("sales_amount", "revenue", "amount", "销售额", "营收", "成交金额"), True) or first_numeric,
        "orders": _find_column(columns, ("order_count", "orders", "订单数", "销量"), True),
        "profit": _find_column(columns, ("profit", "利润"), True),
        "complaints": _find_column(columns, ("complaint", "投诉"), True),
        "visits": _find_column(columns, ("visit", "traffic", "访问", "流量"), True),
        "conversions": _find_column(columns, ("conversion", "转化"), True),
        "first_numeric": first_numeric,
        "first_dimension": first_dimension,
    }


def _metric(question: str, profile: dict[str, str | None]) -> tuple[str, str, str]:
    if "投诉" in question and profile["complaints"] and profile["orders"]:
        return (
            f"ROUND(100.0 * SUM({profile['complaints']}) / NULLIF(SUM({profile['orders']}), 0), 2)",
            "投诉率",
            "%",
        )
    if "转化" in question and profile["conversions"] and profile["visits"]:
        return (
            f"ROUND(100.0 * SUM({profile['conversions']}) / NULLIF(SUM({profile['visits']}), 0), 2)",
            "转化率",
            "%",
        )
    if "利润" in question and profile["profit"]:
        return (f"ROUND(SUM({profile['profit']}), 2)", "毛利润", "元")
    if ("订单" in question or "销量" in question) and profile["orders"]:
        return (f"SUM({profile['orders']})", "订单数", "单")
    selected = profile["sales"] or profile["first_numeric"]
    if not selected:
        raise ValueError("当前数据集没有可聚合的数值字段")
    label = "销售额" if profile["sales"] == selected else str(selected)
    return (f"ROUND(SUM({selected}), 2)", label, "元" if label == "销售额" else "")


def _time_filter(question: str, date_column: str | None, table_name: str) -> tuple[list[str], list[Any], str | None]:
    if not date_column:
        return [], [], None
    match = re.search(r"(?:近|最近)\s*(\d+)\s*(天|日|周|个月|月)", question)
    max_date = f"(SELECT MAX(DATE({date_column})) FROM {table_name})"
    if match:
        amount = max(1, int(match.group(1)))
        unit = match.group(2)
        if unit in ("天", "日"):
            return [f"DATE({date_column}) >= DATE_SUB({max_date}, INTERVAL %s DAY)"], [amount - 1], f"近{amount}天"
        if unit == "周":
            return [f"DATE({date_column}) >= DATE_SUB({max_date}, INTERVAL %s DAY)"], [amount * 7 - 1], f"近{amount}周"
        return [f"DATE({date_column}) >= DATE_SUB(DATE_FORMAT({max_date}, '%Y-%m-01'), INTERVAL %s MONTH)"], [amount - 1], f"近{amount}个月"
    if "本月" in question:
        return [f"DATE({date_column}) >= DATE_FORMAT({max_date}, '%Y-%m-01')"], [], "本月"
    if "今年" in question or "本年" in question:
        return [f"YEAR({date_column}) = YEAR({max_date})"], [], "本年"
    return [], [], None


def _breakdowns(question: str, profile: dict[str, str | None]) -> list[tuple[str, str]]:
    targets = [
        (("地区", "区域", "大区"), profile["region"], "区域"),
        (("产品", "展品", "品类", "类别"), profile["product"], "产品类别"),
        (("渠道",), profile["channel"], "渠道"),
    ]
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for keywords, column, label in targets:
        if column and any(keyword in question for keyword in keywords):
            if column not in seen:
                result.append((column, label))
                seen.add(column)
    return result


def _build_query(question: str, dataset: dict, limit: int) -> QueryPlan:
    profile = _column_profile(dataset["columns"])
    metric_sql, metric_label, _ = _metric(question, profile)
    table_name = dataset["table_name"]
    filters, params, time_description = _time_filter(question, profile["date"], table_name)
    for region in REGIONS:
        if region in question and profile["region"]:
            filters.append(f"{profile['region']} = %s")
            params.append(region)

    breakdowns = _breakdowns(question, profile)
    is_monthly = any(word in question for word in ("按月", "每月", "月份", "月度"))
    is_time_series = bool(
        profile["date"]
        and (time_description or is_monthly or any(word in question for word in ("趋势", "走势", "按天", "每日", "每天")))
    )
    if is_time_series:
        if is_monthly:
            x_sql, x_field = f"DATE_FORMAT({profile['date']}, '%Y-%m')", "月份"
        else:
            x_sql, x_field = f"DATE({profile['date']})", "日期"
        series_dimensions = breakdowns
    else:
        if breakdowns:
            x_sql, x_field = breakdowns[0]
            series_dimensions = breakdowns[1:]
        else:
            x_sql = profile["region"] or profile["first_dimension"]
            x_field = "区域" if profile["region"] == x_sql else str(x_sql)
            series_dimensions = []
    if not x_sql:
        raise ValueError("当前数据集没有可用于分组的维度字段")

    select_parts = [f'{x_sql} AS "{x_field}"']
    group_parts = [x_sql]
    order_parts = [x_sql]
    for series_sql, series_field in series_dimensions:
        select_parts.append(f'{series_sql} AS "{series_field}"')
        group_parts.append(series_sql)
        order_parts.append(series_sql)
    select_parts.append(f'{metric_sql} AS "{metric_label}"')
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    sql = (
        f"SELECT {', '.join(select_parts)} FROM {table_name}{where} "
        f"GROUP BY {', '.join(group_parts)} ORDER BY {', '.join(order_parts)} LIMIT {limit}"
    )
    series_fields = [label for _, label in series_dimensions]
    return QueryPlan(
        sql,
        params,
        x_field,
        metric_label,
        series_fields[0] if series_fields else None,
        series_fields,
        time_description,
    )


async def _build_query_llm(question: str, dataset: dict, limit: int) -> QueryPlan | None:
    """LLM-based text-to-SQL for complex queries beyond template coverage."""
    settings = get_settings()
    if not settings.llm_configured:
        return None

    columns_desc = []
    for col in dataset["columns"]:
        desc = col.get("description", "")
        col_line = f"  - {col['name']} ({col['data_type']})"
        if desc:
            col_line += f" — {desc}"
        if col.get("sample_value"):
            col_line += f" [样例: {col['sample_value']}]"
        columns_desc.append(col_line)

    schema_text = (
        f"表名: {dataset['table_name']} ({dataset['row_count']} 行)\n"
        + "列：\n" + "\n".join(columns_desc)
    )

    prompt = (
        "你是一个 MySQL 查询专家。根据用户问题和数据表信息生成一条只读 SELECT 查询。\n\n"
        f"{schema_text}\n\n"
        "要求：\n"
        "1. 只生成 SELECT 或 WITH ... SELECT 语句\n"
        "2. 使用参数化思维但直接输出最终 SQL（不要使用 %s 占位符）\n"
        "3. 时间字段用 DATE() 函数包裹，月份聚合用 DATE_FORMAT(col, '%Y-%m')\n"
        "4. 聚合使用 SUM/AVG/COUNT/MAX/MIN，比率用 ROUND(100.0 * SUM(A) / NULLIF(SUM(B),0), 2)\n"
        f"5. LIMIT 不超过 {limit}\n"
        "6. 只输出纯 SQL，不要 markdown 代码块、不要解释\n"
        f"\n用户问题：{question}\nSQL:"
    )
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            resp = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            sql = resp.json()["choices"][0]["message"]["content"].strip()
            # Strip markdown fences
            for prefix in ("```sql", "```"):
                if sql.startswith(prefix):
                    sql = sql[len(prefix):].strip()
            if sql.endswith("```"):
                sql = sql[:-3].strip()
            sql = sql.rstrip(";")
            if not sql.upper().startswith(("SELECT", "WITH")):
                return None
            safe = validate_readonly_sql(sql, dataset["table_name"])
    except (httpx.HTTPError, KeyError, ValueError):
        logger.warning("LLM SQL generation failed", exc_info=True)
        return None

    profile = _column_profile(dataset["columns"])
    x_field = next((col["name"] for col in dataset["columns"] if col["name"] in safe.lower()), None)
    if not x_field:
        x_field = profile.get("first_dimension") or (dataset["columns"][0]["name"] if dataset["columns"] else "结果")
    y_field = profile.get("sales") or profile.get("first_numeric") or "值"
    return QueryPlan(safe, [], x_field, y_field, None, [], None)


def _needs_complex_sql(question: str) -> bool:
    """Detect if question likely needs JOIN/subquery/window beyond template capability."""
    markers = (
        "关联", "JOIN", "join", "子查询", "窗口", "排名", "rank",
        "逐年", "同比", "环比", "滚动", "累计", "累计占比",
        "top", "TOP", "前", "第几", "中位数", "百分位",
        "差", "对比", "比较", "增长", "下降", "变化率",
    )
    return any(marker in question for marker in markers) or len(question) > 60


def _series_label(row: dict[str, Any], series_fields: list[str]) -> str:
    return " / ".join(str(row.get(field) or "未分类") for field in series_fields)


def _draft_insights(rows: list[dict[str, Any]], x_field: str, y_field: str, series_fields: list[str]) -> list[str]:
    if not rows:
        return ["当前筛选条件下没有匹配数据，请调整时间或维度后重试。"]
    if series_fields:
        totals: dict[str, float] = defaultdict(float)
        for row in rows:
            totals[_series_label(row, series_fields)] += float(row[y_field] or 0)
        ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        peak = max(rows, key=lambda row: float(row[y_field] or 0))
        peak_series = _series_label(peak, series_fields)
        return [
            f"{ranked[0][0]}累计{y_field}最高，为 {ranked[0][1]:,.2f}。",
            f"{ranked[-1][0]}累计{y_field}最低，为 {ranked[-1][1]:,.2f}。",
            f"单点峰值出现在 {peak[x_field]}，{peak_series}的{y_field}为 {float(peak[y_field] or 0):,.2f}。",
        ]
    numeric = [(row[x_field], float(row[y_field] or 0)) for row in rows]
    highest = max(numeric, key=lambda item: item[1])
    lowest = min(numeric, key=lambda item: item[1])
    insights = [f"{highest[0]}的{y_field}最高，为 {highest[1]:,.2f}。"]
    if len(numeric) > 1:
        insights.append(f"{lowest[0]}的{y_field}最低，为 {lowest[1]:,.2f}。")
    insights.append(f"当前结果合计为 {sum(value for _, value in numeric):,.2f}。")
    return insights


def _load_history(session_id: str | None) -> list[dict[str, Any]]:
    if not session_id:
        return []
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, role, content, payload, created_at FROM messages WHERE session_id = %s ORDER BY id",
            (session_id,),
        ).fetchall()
    history = []
    for row in rows:
        item = dict(row)
        if item.get("payload"):
            try:
                item["payload"] = json.loads(item["payload"])
            except json.JSONDecodeError:
                item["payload"] = None
        history.append(item)
    return history


def _last_effective_question(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        payload = item.get("payload")
        if item.get("role") == "assistant" and isinstance(payload, dict) and payload.get("effective_question"):
            return str(payload["effective_question"])
    for item in reversed(history):
        if item.get("role") == "user":
            return str(item.get("content") or "")
    return None


def _previous_answer_type(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        payload = item.get("payload")
        if item.get("role") == "assistant" and isinstance(payload, dict):
            return payload.get("answer_type") or ("knowledge_qa" if payload.get("intent") == "知识库问答" else "data_analysis")
    return None


def _looks_like_followup(question: str, history: list[dict[str, Any]]) -> bool:
    if not history:
        return False
    markers = ("只看", "改成", "改为", "换成", "再看", "继续", "其中", "那么", "这个", "该指标", "按", "解释", "为什么", "呢")
    return any(marker in question for marker in markers) or len(question.strip()) <= 12


def _is_knowledge_question(question: str, history: list[dict[str, Any]]) -> bool:
    """Legacy keyword fallback – retained for backward compatibility when LLM unavailable."""
    knowledge_signals = ("什么是", "如何计算", "怎么计算", "怎样计算", "口径", "定义", "含义", "业务规则", "制度", "知识库", "字段说明")
    data_signals = ("统计", "分析", "趋势", "最高", "最低", "排行", "同比", "环比", "图表", "多少")
    if any(signal in question for signal in knowledge_signals) and not any(signal in question for signal in data_signals):
        return True
    return _previous_answer_type(history) == "knowledge_qa" and _looks_like_followup(question, history)


async def _classify_intent(question: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    """LLM few-shot intent classification → 5 types. Falls back to keyword method.

    Returns {"intent": str, "is_knowledge_qa": bool, "confidence": float, "method": str}
    """
    settings = get_settings()
    if not settings.llm_configured:
        return _classify_intent_keyword(question, history)

    prompt = (
        "你是一个数据分析意图分类器。将用户问题归类为以下 5 种意图之一：\n\n"
        "1. data_query —— 简单数据查询，如\"各地区销售额\"、\"最近一周订单数\"\n"
        "2. trend_analysis —— 趋势/对比分析，如\"近30天销售额趋势\"、\"各月利润变化\"\n"
        "3. anomaly_attribution —— 异常归因，如\"为什么华东地区销售额下降\"、\"投诉率上升原因\"\n"
        "4. knowledge_qa —— 知识问答，如\"销售额怎么计算的\"、\"投诉率的定义\"\n"
        "5. report_generation —— 报告生成，如\"生成本月分析报告\"、\"导出Q2总结\"\n\n"
        "示例：\n"
        "- \"统计各地区销售额\" → data_query\n"
        "- \"近30天销售额趋势\" → trend_analysis\n"
        "- \"分析华东地区销售额为什么下降\" → anomaly_attribution\n"
        "- \"投诉率如何计算\" → knowledge_qa\n"
        "- \"帮我生成这个月的分析报告\" → report_generation\n\n"
        "请分析以下问题，只输出 JSON：{\"intent\":\"...\",\"confidence\":0.XX}"
        f"\n\n用户问题：{question}"
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0.0,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            parsed = json.loads(raw)
            intent = parsed.get("intent", "data_query")
            confidence = float(parsed.get("confidence", 0.7))
    except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError):
        logger.warning("LLM intent classification failed, falling back to keyword method", exc_info=True)
        return _classify_intent_keyword(question, history)

    knowledge_types = {"knowledge_qa"}
    return {
        "intent": intent,
        "is_knowledge_qa": intent in knowledge_types,
        "confidence": confidence,
        "method": "llm-fewshot",
    }


def _classify_intent_keyword(question: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    """Keyword-based intent classification (fallback when LLM unavailable)."""
    is_knowledge = _is_knowledge_question(question, history)
    if is_knowledge:
        return {"intent": "knowledge_qa", "is_knowledge_qa": True, "confidence": 0.5, "method": "keyword"}

    if any(word in question for word in ("原因", "异常", "为什么", "为何")):
        intent = "anomaly_attribution"
    elif any(word in question for word in ("趋势", "走势", "按月", "按天", "按日", "变化")):
        intent = "trend_analysis"
    elif any(word in question for word in ("报告", "导出", "生成")):
        intent = "report_generation"
    else:
        intent = "data_query"
    return {"intent": intent, "is_knowledge_qa": False, "confidence": 0.5, "method": "keyword"}


def _merge_followup(question: str, history: list[dict[str, Any]]) -> tuple[str, bool]:
    base = _last_effective_question(history)
    if not base or not _looks_like_followup(question, history):
        return question, False

    current = question.strip()
    merged_base = base
    if re.search(r"(?:近|最近)\s*\d+\s*(?:天|日|周|个月|月)|本月|今年|本年", current):
        merged_base = re.sub(r"(?:近|最近)\s*\d+\s*(?:天|日|周|个月|月)|本月|今年|本年", "", merged_base)
    if any(term in current for term in ("销售额", "利润", "订单", "销量", "投诉率", "投诉", "转化率", "转化")):
        merged_base = re.sub(r"销售额|毛利润|利润|订单数|订单|销量|投诉率|投诉|转化率|转化", "", merged_base)
    dimension_replace = any(term in current for term in (
        "只按", "仅按", "不看地区", "不看区域", "去掉地区", "去掉区域", "不要地区", "不要区域",
    ))
    if dimension_replace:
        merged_base = re.sub(r"(?:各|按)?(?:地区|区域|大区|产品类别|产品|展品|品类|类别|渠道)(?:拆分|分组|展示|对比)?", "", merged_base)
    if any(region in current for region in REGIONS):
        for region in REGIONS:
            merged_base = merged_base.replace(region, "")
    merged_base = re.sub(r"\s+", " ", merged_base).strip(" ，。；")
    return f"{merged_base}；{current}" if merged_base else current, True


def _store_user(session_id: str, question: str, dataset_id: int | None) -> None:
    with connect() as conn:
        session = conn.execute("SELECT id FROM sessions WHERE id = %s", (session_id,)).fetchone()
        if not session:
            conn.execute(
                "INSERT INTO sessions(id, title, dataset_id) VALUES (%s, %s, %s)",
                (session_id, question[:40], dataset_id),
            )
        elif dataset_id is not None:
            conn.execute("UPDATE sessions SET dataset_id = %s WHERE id = %s", (dataset_id, session_id))
        conn.execute("INSERT INTO messages(session_id, role, content) VALUES (%s, 'user', %s)", (session_id, question))
        conn.execute("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = %s", (session_id,))


def _store_assistant(session_id: str, payload: dict, audit_action: str, dataset_id: int | None) -> None:
    content = "\n".join(payload.get("insights") or [payload.get("message", "")])
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages(session_id, role, content, payload) VALUES (%s, 'assistant', %s, %s)",
            (session_id, content, json.dumps(payload, ensure_ascii=False)),
        )
        conn.execute(
            "INSERT INTO audit_logs(action, resource_type, resource_id, detail) VALUES (%s, 'session', %s, %s)",
            (audit_action, session_id, payload.get("effective_question", "")),
        )
        conn.execute("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = %s", (session_id,))


async def _answer_knowledge(
    question: str,
    effective_question: str,
    session_id: str,
    dataset_id: int | None,
    history: list[dict[str, Any]],
    context_applied: bool,
) -> dict:
    settings = get_settings()
    knowledge = await search_knowledge(effective_question, dataset_id, limit=5)
    answer = await answer_from_knowledge(question, knowledge, history)
    payload = {
        "session_id": session_id,
        "message": "已根据企业知识库回答。",
        "intent": "知识库问答",
        "plan": ["识别知识问答意图", "从 Qdrant 检索相关知识", "按数据集权限过滤", "基于知识片段生成回答"],
        "sql": "",
        "columns": [],
        "rows": [],
        "chart": {
            "type": "none",
            "title": "企业知识库回答",
            "x_field": None,
            "y_field": None,
            "series_name": None,
            "series_field": None,
            "series_fields": [],
        },
        "insights": [answer],
        "knowledge_refs": knowledge,
        "execution_mode": "llm-assisted" if settings.llm_configured else "knowledge-extract",
        "answer_type": "knowledge_qa",
        "context_applied": context_applied,
        "effective_question": effective_question,
    }
    _store_assistant(session_id, payload, "knowledge_qa", dataset_id)
    return payload


async def _anomaly_attribution(
    question: str,
    dataset: dict,
    base_plan: QueryPlan,
    base_rows: list[dict[str, Any]],
) -> list[str]:
    """Multi-dimensional drill-down: compare periods and attribute changes."""

    if not base_rows or not base_plan.time_description:
        return _draft_insights(base_rows, base_plan.x_field, base_plan.y_field, base_plan.series_fields)

    # 1. Build a comparison query for the previous period
    prev_plan = _build_query(
        question.replace(base_plan.time_description or "", f"上期{base_plan.time_description}" if base_plan.time_description else ""),
        dataset,
        len(base_rows) * 2,
    )

    try:
        with connect() as conn:
            prev_result = conn.execute(prev_plan.sql, prev_plan.params).fetchall()
            prev_rows = [dict(row) for row in prev_result]
    except Exception:
        return _draft_insights(base_rows, base_plan.x_field, base_plan.y_field, base_plan.series_fields)

    if not prev_rows:
        return _draft_insights(base_rows, base_plan.x_field, base_plan.y_field, base_plan.series_fields)

    # 2. Calculate totals
    y_field = base_plan.y_field
    current_total = sum(float(row.get(y_field, 0) or 0) for row in base_rows)
    prev_total = sum(float(row.get(y_field, 0) or 0) for row in prev_rows)
    if prev_total == 0:
        return _draft_insights(base_rows, base_plan.x_field, base_plan.y_field, base_plan.series_fields)

    delta_pct = round((current_total - prev_total) / prev_total * 100, 1)

    # 3. Drill down by available dimensions
    dimensions: list[tuple[str, str]] = []
    profile = _column_profile(dataset["columns"])
    for dim_key, label in [("region", "区域"), ("product", "产品类别"), ("channel", "渠道")]:
        col = profile.get(dim_key)
        if col and any(row.get(col) for row in base_rows):
            dimensions.append((col, label))

    if not dimensions:
        return _draft_insights(base_rows, base_plan.x_field, base_plan.y_field, base_plan.series_fields)

    # 4. Calculate contributions per dimension value
    contributions: list[dict] = []
    for dim_col, dim_label in dimensions:
        current_by_dim: dict[str, float] = defaultdict(float)
        prev_by_dim: dict[str, float] = defaultdict(float)
        for row in base_rows:
            current_by_dim[str(row.get(dim_col, "未知"))] += float(row.get(y_field, 0) or 0)
        for row in prev_rows:
            prev_by_dim[str(row.get(dim_col, "未知"))] += float(row.get(y_field, 0) or 0)

        all_values = set(current_by_dim.keys()) | set(prev_by_dim.keys())
        for val in all_values:
            curr_val = current_by_dim.get(val, 0)
            prev_val = prev_by_dim.get(val, 0)
            if prev_val == 0:
                continue
            dim_delta = round((curr_val - prev_val) / prev_val * 100, 1)
            contribution = round((curr_val - prev_val) / prev_total * 100, 1)
            contributions.append({
                "dimension": dim_label,
                "value": val,
                "current": round(curr_val, 2),
                "previous": round(prev_val, 2),
                "delta_pct": dim_delta,
                "contribution_pct": contribution,
            })

    contributions.sort(key=lambda x: abs(x["contribution_pct"]), reverse=True)

    # 5. Format insights
    insights: list[str] = []
    direction = "增长" if delta_pct > 0 else "下降"
    insights.append(f"本期{y_field}较上期{direction}{abs(delta_pct)}%。")

    if contributions:
        top = contributions[:4]
        for item in top:
            dir_word = "增长" if item["delta_pct"] > 0 else "下降"
            insights.append(
                f"• {item['dimension']}「{item['value']}」{dir_word}{abs(item['delta_pct'])}%，"
                f"贡献了总变化的{abs(item['contribution_pct'])}%（从{item['previous']:,.2f}→{item['current']:,.2f}）。"
            )

    # 6. Add recommendation
    if contributions:
        largest = contributions[0]
        insights.append(f"建议重点关注{largest['dimension']}「{largest['value']}」的异常变化，进一步排查业务原因。")

    return insights


async def analyze(question: str, session_id: str | None, dataset_id: int | None) -> dict:
    settings = get_settings()
    session_id = session_id or uuid.uuid4().hex
    history = _load_history(session_id)
    effective_question, context_applied = _merge_followup(question, history)
    _store_user(session_id, question, dataset_id)

    # ---- FR#8: LLM intent classification (with keyword fallback) ----
    intent_result = await _classify_intent(question, history)

    if intent_result["is_knowledge_qa"]:
        return await _answer_knowledge(
            question, effective_question, session_id, dataset_id, history, context_applied
        )

    dataset = _dataset(dataset_id)
    dataset_id = dataset["id"]

    # ---- FR#10: Dual-path SQL generation (template → LLM fallback) ----
    query_plan = _build_query(effective_question, dataset, settings.query_row_limit)
    if query_plan is None or _needs_complex_sql(effective_question):
        llm_plan = await _build_query_llm(effective_question, dataset, settings.query_row_limit)
        if llm_plan is not None:
            query_plan = llm_plan
    safe_sql = validate_readonly_sql(query_plan.sql, dataset["table_name"])
    with connect() as conn:
        result = conn.execute(safe_sql, query_plan.params).fetchall()
        rows = [dict(row) for row in result]

    knowledge = await search_knowledge(effective_question, dataset_id)
    draft = _draft_insights(rows, query_plan.x_field, query_plan.y_field, query_plan.series_fields)

    # ---- FR#18: Anomaly attribution path ----
    if intent_result["intent"] == "anomaly_attribution":
        insights = await _anomaly_attribution(effective_question, dataset, query_plan, rows)
    else:
        insights = await polish_insights(effective_question, rows, draft, knowledge)

    is_time = query_plan.x_field in ("日期", "月份")
    # Use LLM intent-aware chart selection
    if intent_result["intent"] == "trend_analysis":
        chart_type = "line"
    elif intent_result["intent"] == "anomaly_attribution":
        chart_type = "bar"
    elif "柱状图" in effective_question:
        chart_type = "bar"
    elif "折线图" in effective_question:
        chart_type = "line"
    elif "饼图" in effective_question:
        chart_type = "pie"
    else:
        chart_type = "line" if is_time else ("pie" if "占比" in effective_question and len(rows) <= 8 else "bar")
    intent_user = "趋势分析" if intent_result["intent"] == "trend_analysis" else (
        "异常归因" if intent_result["intent"] == "anomaly_attribution" else (
        "报告生成" if intent_result["intent"] == "report_generation" else "指标查询"
    ))
    scope_parts = [item for item in (query_plan.time_description, *query_plan.series_fields) if item]
    scope = "、".join(scope_parts) or query_plan.x_field
    plan_steps = [
        f"识别分析意图：{intent_user}（{intent_result['method']}，置信度 {intent_result['confidence']:.0%}）",
        f"确定查询范围与分组：{scope}",
        f"检索数据集与指标口径：{dataset['name']}",
        "生成并校验只读 SQL" + ("（LLM 增强）" if intent_result.get("method") == "llm-fewshot" else ""),
        f"执行查询并生成{chart_type}图与业务结论",
    ]
    if intent_result["intent"] == "anomaly_attribution":
        plan_steps.insert(3, "异常归因：对比上期数据并逐维度下钻分析")
    payload = {
        "session_id": session_id,
        "message": "分析完成。" + (" 已继承上轮对话条件。" if context_applied else ""),
        "intent": intent_user,
        "plan": plan_steps,
        "sql": safe_sql,
        "columns": list(rows[0].keys()) if rows else [query_plan.x_field, query_plan.y_field],
        "rows": rows,
        "chart": {
            "type": chart_type,
            "title": f"{dataset['name']} - {(query_plan.time_description + ' ') if query_plan.time_description else ''}{query_plan.y_field}",
            "x_field": query_plan.x_field,
            "y_field": query_plan.y_field,
            "series_name": query_plan.y_field,
            "series_field": query_plan.series_field,
            "series_fields": query_plan.series_fields,
        },
        "insights": insights,
        "knowledge_refs": knowledge,
        "execution_mode": "llm-assisted" if settings.llm_configured else "local-demo",
        "answer_type": "data_analysis",
        "context_applied": context_applied,
        "effective_question": effective_question,
    }
    _store_assistant(session_id, payload, "analyze", dataset_id)
    return payload
