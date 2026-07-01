"""Dimension Executor — iterative plan execution with dynamic adjustment.

Phase 2.2 + 2.4: For each section in the analysis plan:
  1. Execute SQL → fetch data
  2. Evaluate interestingness → skip/downgrade/deep-dive
  3. Render chart PNG
  4. LLM writes narrative
  5. Yield SSE progress events
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from ..config import get_settings
from ..db import connect
from .security import validate_readonly_sql

logger = logging.getLogger(__name__)

_MAX_SECTIONS = 8


async def execute_section(
    section: dict,
    table_name: str,
    dataset_columns: list[dict],
) -> dict[str, Any]:
    """Execute a single analysis section: SQL → data → chart recommendation.

    Returns {section, rows, chart_type, interesting, surprise, should_drill}
    """
    result: dict[str, Any] = {
        "section": section,
        "rows": [],
        "chart_type": section.get("chart", "bar"),
        "interesting": True,
        "surprise": False,
        "should_drill": False,
        "error": None,
    }

    sql = section.get("sql")
    if not sql:
        return result

    # Execute SQL (with readonly validation)
    try:
        safe_sql = validate_readonly_sql(sql, table_name)
        with connect() as conn:
            rows_result = conn.execute(safe_sql).fetchall()
            rows = [dict(r) for r in rows_result]
        result["rows"] = rows
    except Exception as exc:
        result["rows"] = []
        result["interesting"] = False
        result["error"] = str(exc)[:200]
        return result

    # Evaluate data quality / interestingness
    result["interesting"], result["surprise"] = _evaluate_interestingness(rows)
    if len(rows) == 0:
        result["interesting"] = False

    return result


async def execute_section_with_narrative(
    section: dict,
    rows: list[dict],
    chart_type: str,
    question: str,
    dataset_name: str,
) -> str:
    """LLM writes analysis narrative for a section's data."""
    if not rows:
        return f"「{section.get('title','')}」：当前维度暂无可用数据。"

    settings = get_settings()
    if not settings.llm_configured:
        return _simple_narrative(section, rows)

    preview = rows[:10]
    focus = section.get("narrative_focus", section.get("title", ""))

    prompt = f"""你是{section.get('title','数据分析师')}，撰写一段简明的分析叙事。

## 分析方向
{focus}

## 数据（{len(rows)}行，展示前{len(preview)}行）
{json.dumps(preview, ensure_ascii=False, default=str)[:1500]}

## 要求
- 2-4句话，简洁专业
- 指出关键数字、趋势方向、异常点
- 不要重复数据表的内容，给出洞察

输出纯文本叙事："""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={"model": settings.llm_model, "temperature": 0.3, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return _simple_narrative(section, rows)


def _simple_narrative(section: dict, rows: list[dict]) -> str:
    if not rows:
        return f"「{section.get('title','')}」：暂无数据。"
    cols = list(rows[0].keys()) if rows else []
    return f"「{section.get('title','')}」：共 {len(rows)} 条记录，涉及 {', '.join(cols[:4])} 等维度。"


def _evaluate_interestingness(rows: list[dict]) -> tuple[bool, bool]:
    """Quick heuristic: is the data interesting/surprising enough for the report?"""
    if not rows or len(rows) < 2:
        return False, False

    # Check for high variance (surprising)
    numeric_cols = []
    for row in rows[:5]:
        for k, v in row.items():
            if isinstance(v, (int, float)) and k not in numeric_cols:
                numeric_cols.append(k)

    surprise = False
    for col in numeric_cols:
        values = [float(r.get(col, 0) or 0) for r in rows if r.get(col) is not None]
        if len(values) >= 4:
            avg = sum(values) / len(values)
            if avg > 0:
                max_dev = max(abs(v - avg) / avg for v in values)
                if max_dev > 0.5:  # 50%+ deviation from average
                    surprise = True
                    break

    return True, surprise


async def execute_plan_stream(
    plan: dict,
    table_name: str,
    dataset_columns: list[dict],
    question: str,
    dataset_name: str = "",
) -> AsyncIterator[dict]:
    """Execute an entire analysis plan, yielding SSE events for each section.

    Events: {type: "section_start"|"section_narrative"|"section_done"|...}
    """
    sections = plan.get("sections", [])[:_MAX_SECTIONS]
    total = len(sections)

    yield {"type": "plan_start", "total": total, "title": plan.get("report_title", "")}

    completed = 0
    for idx, section in enumerate(sections):
        yield {
            "type": "section_start",
            "index": idx + 1,
            "total": total,
            "title": section.get("title", ""),
            "description": section.get("description", ""),
            "chart_type": section.get("chart", "bar"),
        }

        # Execute SQL
        result = await execute_section(section, table_name, dataset_columns)

        if result["error"]:
            yield {"type": "section_error", "index": idx + 1, "error": result["error"]}
            completed += 1
            continue

        if not result["interesting"] and len(sections) > 3:
            yield {"type": "section_skip", "index": idx + 1, "reason": "数据平淡，已在摘要中提及"}
            completed += 1
            continue

        # Generate narrative
        narrative = await execute_section_with_narrative(
            section, result["rows"], result["chart_type"], question, dataset_name,
        )

        yield {
            "type": "section_done",
            "index": idx + 1,
            "title": section.get("title", ""),
            "narrative": narrative,
            "rows": result["rows"][:20],
            "chart_type": result["chart_type"],
            "row_count": len(result["rows"]),
            "surprise": result["surprise"],
        }

        completed += 1

        # Dynamic adjustment: if surprising, add a sub-section drill-down
        if result["surprise"] and completed < _MAX_SECTIONS:
            drill_section = {
                "title": f"{section.get('title','')} — 异常下钻",
                "description": f"对{section.get('title','')}中发现的异常进行深入分析",
                "approach": "sql_query",
                "sql": _build_drill_sql(section, result["rows"]),
                "chart": "bar",
                "narrative_focus": f"解释{section.get('title','')}异常波动的原因",
                "priority": 8,
            }
            yield {
                "type": "section_start",
                "index": completed + 1,
                "total": total,
                "title": drill_section["title"],
                "description": drill_section["description"],
                "chart_type": "bar",
                "drill": True,
            }
            drill_result = await execute_section(drill_section, table_name, dataset_columns)
            if drill_result["interesting"]:
                drill_narrative = await execute_section_with_narrative(
                    drill_section, drill_result["rows"], "bar", question, dataset_name,
                )
                yield {
                    "type": "section_done",
                    "index": completed + 1,
                    "title": drill_section["title"],
                    "narrative": drill_narrative,
                    "rows": drill_result["rows"][:20],
                    "chart_type": "bar",
                    "row_count": len(drill_result["rows"]),
                    "drill": True,
                }
            completed += 1

    yield {"type": "plan_done", "completed": completed, "total": total}


def _build_drill_sql(section: dict, rows: list[dict]) -> str | None:
    """Build a simple drill-down SQL for anomaly investigation."""
    if not rows or len(rows) < 2:
        return None
    # Simply return the same SQL — in a real implementation this would add more dimensions
    return section.get("sql")
