"""Analysis Planner — LLM-driven multi-dimensional analysis planning (Phase 1.6)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import get_settings
from .persona_registry import Persona, get_persona_registry


async def plan_analysis(
    question: str,
    data_profile: str,
    persona_name: str = "data_analyst",
) -> dict[str, Any]:
    """
    Phase 1: Generate a structured multi-dimensional analysis plan.

    Returns AnalysisPlan-compatible dict with 3-8 sections, each containing
    title, description, approach, sql template, chart type, and narrative focus.
    """
    settings = get_settings()
    registry = get_persona_registry()
    persona = registry.get(persona_name) or registry.default

    if not settings.llm_configured or not persona:
        return _default_plan(question, persona)

    frameworks_text = _format_frameworks(persona) if persona else ""

    prompt = f"""你是企业数据分析规划师。基于数据概况和分析框架，制定一个多维分析计划。

## 分析角色
{persona.summary if persona else "数据分析师"}

## 可用分析框架
{frameworks_text}

## 数据概况
{data_profile}

## 用户问题
{question}

## 要求
1. 基于分析框架，规划 3-6 个分析维度（section）
2. 每个维度包含：标题、描述、分析方式、SQL模板、推荐图表、叙事方向
3. 维度之间不要重复，覆盖数据的不同侧面
4. SQL 模板仅在 approach 为 sql_query 时需要

## 输出（严格JSON数组）
[
  {{
    "title": "维度标题",
    "description": "为什么分析这个维度",
    "approach": "sql_query|python_analysis|knowledge_qa",
    "sql": "SELECT ... 或 null",
    "chart": "bar|line|pie|radar|scatter|area|table|kpi_cards",
    "narrative_focus": "LLM撰写叙事的方向指引",
    "priority": 5
  }}
]

JSON:"""

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={"model": settings.llm_model, "temperature": 0.2, "max_tokens": 1500, "messages": [{"role": "user", "content": prompt}]},
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            sections = json.loads(raw)
            if not isinstance(sections, list) or len(sections) < 2:
                return _default_plan(question, persona)
            return {
                "report_title": question[:60] or "数据分析报告",
                "persona_name": persona_name,
                "sections": sections[:8],
                "plan_source": "llm",
            }
    except Exception:
        return _default_plan(question, persona)


def _default_plan(question: str, persona: Persona | None) -> dict:
    """Fallback plan when LLM is unavailable."""
    sections = []
    if persona:
        for fw in persona.frameworks[:5]:
            if fw.get("trigger_rule") == "always":
                sections.append({
                    "title": fw.get("display", fw.get("name", "")),
                    "description": fw.get("thinking", "")[:100],
                    "approach": "sql_query",
                    "sql": None,
                    "chart": "bar",
                    "narrative_focus": fw.get("thinking", "")[:80],
                    "priority": 5,
                })
    if not sections:
        sections = [
            {"title": "数据概览", "description": "基本统计信息", "approach": "sql_query", "sql": None, "chart": "kpi_cards", "narrative_focus": "整体规模和构成", "priority": 5},
            {"title": "趋势分析", "description": "时间维度的变化", "approach": "sql_query", "sql": None, "chart": "line", "narrative_focus": "变化趋势和拐点", "priority": 5},
            {"title": "对比分析", "description": "分类维度的差异", "approach": "sql_query", "sql": None, "chart": "bar", "narrative_focus": "类别差异和排名", "priority": 5},
        ]
    return {"report_title": question[:60] or "数据分析报告", "persona_name": persona.name if persona else "data_analyst", "sections": sections, "plan_source": "template"}


def _format_frameworks(persona: Persona) -> str:
    lines = []
    for fw in persona.frameworks:
        lines.append(f"  - {fw.get('display', fw['name'])}: {fw.get('thinking', '')[:120]}")
    return "\n".join(lines)
