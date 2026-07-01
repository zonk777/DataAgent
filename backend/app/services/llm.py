from __future__ import annotations

import json

import httpx

from ..config import get_settings


async def answer_from_knowledge(
    question: str,
    knowledge: list[dict],
    history: list[dict] | None = None,
) -> str:
    """Answer only from retrieved business knowledge, with recent conversation context."""
    if not knowledge:
        return "知识库中暂时没有找到足够相关的内容。你可以先补充指标口径、业务规则或数据字典。"

    settings = get_settings()
    if not settings.llm_configured:
        return "\n".join(f"{item['title']}：{item['content']}" for item in knowledge[:3])

    recent_history = []
    for item in (history or [])[-6:]:
        role = item.get("role")
        if role in ("user", "assistant") and item.get("content"):
            recent_history.append({"role": role, "content": str(item["content"])[:1200]})
    context = [
        {
            "title": item.get("title", ""),
            "content": item.get("content", ""),
            "category": item.get("category", ""),
        }
        for item in knowledge[:5]
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是企业业务知识助手。只能依据提供的知识片段回答；不得编造制度、指标或数字。"
                "若知识不足，明确说明缺少什么。回答应简洁，并在末尾用“依据：”列出引用的知识标题。"
            ),
        },
        *recent_history,
        {
            "role": "user",
            "content": json.dumps({"question": question, "knowledge": context}, ensure_ascii=False),
        },
    ]
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={"model": settings.llm_model, "temperature": 0.1, "messages": messages},
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"].strip()
            if answer:
                return answer
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        pass
    return "\n".join(f"{item['title']}：{item['content']}" for item in knowledge[:3])


async def polish_insights(
    question: str,
    rows: list[dict],
    draft: list[str],
    knowledge: list[dict],
    intent_reason: str = "",
    plan_source: str = "",
) -> list[str]:
    """Use an OpenAI-compatible endpoint when configured; otherwise keep deterministic output.

    当 intent_reason 非空时，注入意图分类的推理上下文，避免 LLM 冷启动。
    当 plan_source 非空时，注入 SQL 生成来源（模板/LLM/修复），帮助理解数据口径。
    """
    settings = get_settings()
    if not settings.llm_configured:
        return draft

    system_extra = ""
    if intent_reason:
        system_extra += f" 本次分析意图: {intent_reason}。"
    if plan_source:
        system_extra += f" SQL 由 {plan_source} 生成，请据此判断数据口径可信度。"

    payload = {
        "model": settings.llm_model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是企业数据分析师。只依据给定聚合数据总结，输出 JSON 字符串数组，最多4条，不虚构原因。"
                    + system_extra
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "aggregate_rows": rows[:30],
                        "draft": draft,
                        "business_knowledge": knowledge,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
                return parsed[:4]
    except (httpx.HTTPError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return draft
