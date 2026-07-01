"""Conversation memory and context management.

M-001: Progressive summarization — keeps recent messages verbatim,
       compresses middle-range into LLM summaries, drops oldest.
M-002: Cross-session user profile — remembers user preferences and
       past analysis topics across sessions.
M-003: LLM-based follow-up merging — replaces fragile regex with
       semantic context integration.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import get_settings
from ..db import connect

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# M-001: Progressive context compression
# ---------------------------------------------------------------------------
RECENT_KEEP = 3       # Keep last 3 messages verbatim
MIDDLE_KEEP = 7       # Summarize messages 4-10
DROP_BEYOND = 10      # Drop everything beyond 10th message


async def compress_history(history: list[dict]) -> str:
    """
    Progressive compression:
    - Last 3 messages: keep verbatim
    - Messages 4-10: LLM one-paragraph summary
    - Beyond 10: discard

    Returns a compact context string suitable for injection into system prompt.
    """
    if len(history) <= RECENT_KEEP:
        return ""

    settings = get_settings()
    parts: list[str] = []

    # Middle section → summarize
    middle = history[-(RECENT_KEEP + MIDDLE_KEEP):-RECENT_KEEP] if len(history) > RECENT_KEEP else []
    # Get messages that are beyond the window
    old = history[:max(0, len(history) - RECENT_KEEP - MIDDLE_KEEP)]

    summary_targets = (old + middle)[-MIDDLE_KEEP:]
    if summary_targets and settings.llm_configured:
        conversation_text = "\n".join(
            f"{m['role']}: {str(m.get('content', ''))[:500]}"
            for m in summary_targets
            if m.get("role") in ("user", "assistant") and m.get("content")
        )
        if conversation_text:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                        json={
                            "model": settings.llm_model,
                            "temperature": 0,
                            "max_tokens": 200,
                            "messages": [{
                                "role": "user",
                                "content": f"用一段中文总结以下对话的关键信息和结论（不超过100字）：\n{conversation_text}",
                            }],
                        },
                    )
                    resp.raise_for_status()
                    summary = resp.json()["choices"][0]["message"]["content"].strip()
                    if summary:
                        parts.append(f"[对话摘要] {summary}")
            except Exception:
                logger.debug("History summarization skipped", exc_info=True)

    # Recent messages → verbatim
    recent = history[-RECENT_KEEP:]
    for m in recent:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            parts.append(f"{'用户' if m['role'] == 'user' else '助手'}: {str(m['content'])[:300]}")

    # Also extract key entities from the entire history
    entities = _extract_entities(history)
    if entities:
        parts.insert(0, f"[上下文实体] {entities}")

    return "\n".join(parts)


def _extract_entities(history: list[dict]) -> str:
    """Extract key entities (regions, metrics, dimensions) from history."""
    regions = set()
    metrics = set()
    for m in history:
        content = str(m.get("content", ""))
        for region in ("华东", "华南", "华北", "西南"):
            if region in content:
                regions.add(region)
        for metric in ("销售额", "利润", "订单数", "投诉率", "转化率"):
            if metric in content:
                metrics.add(metric)
    parts = []
    if regions:
        parts.append(f"地区: {', '.join(sorted(regions))}")
    if metrics:
        parts.append(f"指标: {', '.join(sorted(metrics))}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# M-002: Cross-session user profile
# ---------------------------------------------------------------------------
async def load_user_profile(user_id: int) -> dict[str, Any]:
    """Load user profile from DB. Returns empty dict if none exists."""
    with connect() as conn:
        row = conn.execute(
            "SELECT user_profile FROM admin_users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not row or not row.get("user_profile"):
        return {}
    try:
        return json.loads(row["user_profile"]) if isinstance(row["user_profile"], str) else row["user_profile"]
    except json.JSONDecodeError:
        return {}


async def save_user_profile(user_id: int, profile: dict) -> None:
    """Save updated user profile to DB."""
    with connect() as conn:
        conn.execute(
            "UPDATE admin_users SET user_profile = ? WHERE id = ?",
            (json.dumps(profile, ensure_ascii=False), user_id),
        )


async def update_user_profile_from_analysis(
    user_id: int,
    question: str,
    insights: list[str],
    dataset_name: str = "",
) -> None:
    """Incrementally update user profile based on an analysis session."""
    profile = await load_user_profile(user_id) or {}
    profile.setdefault("preferred_metrics", [])
    profile.setdefault("preferred_dimensions", [])
    profile.setdefault("recent_topics", [])
    profile["last_analysis_at"] = str(profile.get("analysis_count", 0) + 1)
    profile["analysis_count"] = profile.get("analysis_count", 0) + 1

    # Track metric preferences
    for metric in ("销售额", "利润", "订单", "投诉", "转化"):
        if metric in question:
            if metric not in profile["preferred_metrics"]:
                profile["preferred_metrics"].append(metric)

    # Track dimension preferences
    for dim in ("华东", "华南", "华北", "西南", "区域", "产品", "渠道"):
        if dim in question:
            if dim not in profile["preferred_dimensions"]:
                profile["preferred_dimensions"].append(dim)

    # Track recent topics (keep last 5)
    topic = question[:80]
    if topic not in profile["recent_topics"]:
        profile["recent_topics"].insert(0, topic)
        profile["recent_topics"] = profile["recent_topics"][:5]

    await save_user_profile(user_id, profile)


def format_profile_context(profile: dict) -> str:
    """Convert user profile into a compact context string for LLM prompts."""
    if not profile:
        return ""
    parts = []
    if profile.get("preferred_metrics"):
        parts.append(f"常用指标: {', '.join(profile['preferred_metrics'][-5:])}")
    if profile.get("preferred_dimensions"):
        parts.append(f"常用维度: {', '.join(profile['preferred_dimensions'][-5:])}")
    if profile.get("recent_topics"):
        parts.append(f"最近问题: {'; '.join(profile['recent_topics'][-3:])}")
    if not parts:
        return ""
    return "[用户偏好] " + " | ".join(parts)


# ---------------------------------------------------------------------------
# M-003: LLM-based follow-up merging
# ---------------------------------------------------------------------------
async def llm_merge_followup(question: str, history: list[dict]) -> tuple[str, bool]:
    """
    Use LLM to semantically merge a follow-up question with previous context.
    Returns (merged_question, is_followup).
    Falls back to simple concatenation if LLM unavailable.
    """
    if not history:
        return question, False

    # Quick check: very short questions are likely follow-ups
    is_short = len(question.strip()) <= 15

    # Get the last meaningful exchange
    last_user = None
    last_assistant = None
    for m in reversed(history):
        if m.get("role") == "user" and not last_user:
            last_user = str(m.get("content", ""))[:500]
        if m.get("role") == "assistant" and not last_assistant:
            last_assistant = str(m.get("content", ""))[:500]
        if last_user and last_assistant:
            break

    if not last_user:
        return question, False

    settings = get_settings()
    if not settings.llm_configured:
        return _simple_merge(question, last_user), True if is_short else (question, False)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0,
                    "max_tokens": 150,
                    "messages": [{
                        "role": "user",
                        "content": (
                            "你的任务：将用户的追问合并到上一轮问题中，形成一个完整的、自包含的分析问题。\n"
                            f"上一轮问题: {last_user}\n"
                            f"上一轮回答要点: {last_assistant[:200] if last_assistant else '无'}\n"
                            f"用户的追问: {question}\n\n"
                            "输出规则：\n"
                            "1. 如果追问是独立的新问题，输出原追问原文\n"
                            "2. 如果追问是对上一轮的延续（如缩小范围、切换图表、追问原因），输出合并后的完整问题\n"
                            "3. 只输出最终问题，不要任何解释"
                        ),
                    }],
                },
            )
            resp.raise_for_status()
            merged = resp.json()["choices"][0]["message"]["content"].strip()
            is_followup = merged != question or is_short
            return merged[:300], is_followup
    except Exception:
        logger.debug("LLM follow-up merge failed, using simple merge", exc_info=True)
        return _simple_merge(question, last_user), True


def _simple_merge(question: str, last_question: str) -> str:
    """Simple concatenation fallback when LLM unavailable."""
    current = question.strip()
    if current in ("继续", "这个呢", "为什么", "解释一下"):
        return f"{last_question}，请进一步说明"
    if len(current) <= 12:
        return f"{last_question}；{current}"
    return f"{last_question}；{current}"
