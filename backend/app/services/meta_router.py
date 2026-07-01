"""Meta-Router — intent understanding, persona matching, and clarification."""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import get_settings
from .persona_registry import get_persona_registry, match_persona


async def route_intent(question: str, data_profile: str, history: list[dict] | None = None) -> dict[str, Any]:
    """
    Phase 0: Understand user intent, match persona, check info sufficiency.

    Returns:
        {
            task_type, matched_persona, confidence, info_sufficient,
            clarification (if not sufficient), reasoning
        }
    """
    registry = get_persona_registry()
    settings = get_settings()

    # Fast path: keyword-based matching
    keyword_match = match_persona("analysis", question)
    persona_summary = registry.registry_summary

    if not settings.llm_configured:
        return _fast_result(question, keyword_match)

    prompt = f"""你是企业数据智能体的任务路由器。理解用户需求，匹配分析角色，判断信息是否足够。

## 可用分析角色
{persona_summary}

## 当前数据概况
{data_profile}

## 历史对话
{_format_history(history)}

## 判断规则
1. 用户想做分析/审计/诊断/探索/其他？
2. 匹配最合适的分析角色
3. 信息是否足够？
   - 需求明确 → info_sufficient = true
   - 笼统（如"看看这份数据"）→ 生成2-3个分析方向让用户选
   - 关键信息缺失 → 生成针对性澄清问题

## 输出（严格JSON）
{{"task_type":"analysis|audit|diagnosis|exploration|other","matched_persona":"data_analyst","confidence":0.9,"info_sufficient":true,"clarification":null,"reasoning":"..."}}

## 用户问题
{question}

JSON:"""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={"model": settings.llm_model, "temperature": 0, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]},
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            parsed = json.loads(raw)
            return {
                "task_type": parsed.get("task_type", "analysis"),
                "matched_persona": parsed.get("matched_persona", keyword_match.name if keyword_match else "data_analyst"),
                "confidence": float(parsed.get("confidence", 0.7)),
                "info_sufficient": bool(parsed.get("info_sufficient", True)),
                "clarification": parsed.get("clarification"),
                "reasoning": parsed.get("reasoning", ""),
            }
    except Exception:
        return _fast_result(question, keyword_match)


def _fast_result(question: str, persona) -> dict:
    is_vague = len(question.strip()) <= 10 or any(w in question for w in ("看看", "分析一下", "帮我", "看一下"))
    return {
        "task_type": "analysis",
        "matched_persona": persona.name if persona else "data_analyst",
        "confidence": 0.6,
        "info_sufficient": not is_vague,
        "clarification": {
            "message": "我看了您的数据。您想了解哪个方面？",
            "options": ["销售趋势和业绩表现", "关键指标对比分析", "异常检测和风险识别", "全面分析生成报告"],
        } if is_vague else None,
        "reasoning": "关键词匹配" if persona else "默认数据分析师",
    }


def _format_history(history: list[dict] | None) -> str:
    if not history:
        return "（无历史对话）"
    recent = history[-3:]
    return "\n".join(f"{m.get('role','')}: {str(m.get('content',''))[:150]}" for m in recent)
