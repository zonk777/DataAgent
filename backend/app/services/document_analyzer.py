from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings
from .knowledge_documents import chunk_text
from .planner import build_plan_steps, plan_titles
from .intent_classifier import IntentResult


MAX_DIRECT_CHARS = 12000
CHUNK_CHARS = 5500
MAX_CHUNKS = 10


def wants_database_context(question: str) -> bool:
    """Only combine uploaded files with business DB when the user says so."""
    signals = (
        "结合数据源",
        "结合数据库",
        "结合业务数据",
        "结合当前数据",
        "结合数据表",
        "查询数据库",
        "查询数据表",
        "用当前数据源",
        "用业务数据库",
        "和数据库一起",
        "和数据源一起",
    )
    text = question or ""
    return any(signal in text for signal in signals)


def _safe_json_loads(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


def _llm_error_message(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 401:
            return "模型接口认证失败：API Key 无效、过期或与当前平台不匹配。"
        if status == 402:
            return "模型接口余额不足或套餐不可用：请检查 API 账户余额、额度或计费状态。"
        if status == 429:
            return "模型接口请求过于频繁：请稍后重试或降低并发。"
        if 500 <= status < 600:
            return "模型服务暂时异常：对方接口返回服务器错误。"
        return f"模型接口调用失败：HTTP {status}。"
    if isinstance(exc, httpx.TimeoutException):
        return "模型接口响应超时：文件较长或网络较慢，请稍后重试。"
    if isinstance(exc, httpx.HTTPError):
        return f"模型接口网络错误：{exc}"
    return f"模型返回内容无法解析：{exc}"


async def _llm_json(messages: list[dict[str, str]], timeout: int = 60) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": settings.llm_model, "temperature": 0.2, "messages": messages},
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
    parsed = _safe_json_loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("模型返回的文档分析结果不是 JSON 对象")
    return parsed


async def _summarize_chunk(
    *,
    title: str,
    question: str,
    index: int,
    total: int,
    chunk: str,
) -> str:
    settings = get_settings()
    if not settings.llm_configured:
        return chunk[:1200]

    prompt = {
        "document_title": title,
        "user_question": question,
        "chunk_index": index,
        "chunk_total": total,
        "chunk_text": chunk,
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是企业文档分析助手。请阅读文档片段，提取与用户问题相关的事实。"
                "输出中文要点，不要编造；保留重要数字、时间、主体、结论、风险和建议。"
                "如果片段是表格/CSV/Excel 摘要，请关注字段、样例、规模、异常和可分析维度。"
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": settings.llm_model, "temperature": 0.2, "messages": messages},
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()


def _fallback_document_payload(
    *,
    session_id: str,
    title: str,
    question: str,
    text: str,
    reason: str = "",
) -> dict[str, Any]:
    excerpt = text[:1800]
    if reason:
        message = f"已解析《{title}》，但暂时无法完成深度模型分析：{reason}"
    else:
        message = f"已解析《{title}》，但当前未配置可用的大模型，因此仅返回文档前部摘要。"
    insight = f"{message}\n\n{excerpt}"
    plan_steps = build_plan_steps(
        intent=IntentResult("knowledge_qa", 0.8, "rules", "上传文件分析"),
        answer_type="knowledge_qa",
        execution_mode="local-document-parser",
        dataset_name=title,
        chart_type="none",
    )
    return {
        "session_id": session_id,
        "message": message,
        "intent": "文档分析",
        "intent_label": "knowledge_qa",
        "intent_confidence": 0.8,
        "intent_method": "rules",
        "intent_reason": "上传文件触发文档分析",
        "sql_source": None,
        "plan": plan_titles(plan_steps),
        "plan_steps": plan_steps,
        "sql": "",
        "columns": [],
        "rows": [],
        "chart": {
            "type": "none",
            "title": f"{title} - 文档分析",
            "x_field": "",
            "y_field": "",
            "series_name": "",
            "series_field": None,
            "series_fields": [],
        },
        "insights": [insight],
        "knowledge_refs": [{"id": 0, "title": title, "content": excerpt, "category": "uploaded_file", "score": 1.0}],
        "execution_mode": "local-document-parser",
        "answer_type": "knowledge_qa",
        "context_applied": False,
        "effective_question": question,
    }


async def analyze_uploaded_document(
    *,
    session_id: str,
    filename: str,
    text: str,
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze an uploaded file without defaulting to database queries."""
    title = Path(filename or "上传文件").stem
    effective_question = question or "请分析这份文件，提炼关键信息、主要结论、风险点和建议。"
    cleaned_text = text.strip()
    if not cleaned_text:
        raise ValueError("文件中没有可解析的文字内容；如果是扫描版 PDF，请先进行 OCR 后再上传。")

    settings = get_settings()
    if not settings.llm_configured:
        return _fallback_document_payload(session_id=session_id, title=title, question=effective_question, text=cleaned_text)

    chunks = chunk_text(cleaned_text, max_chars=CHUNK_CHARS)
    if len(chunks) > MAX_CHUNKS:
        chunks = chunks[:MAX_CHUNKS]
        truncated_notice = f"\n\n注意：文档较长，本次先分析前 {MAX_CHUNKS} 个片段。"
    else:
        truncated_notice = ""

    if len(cleaned_text) <= MAX_DIRECT_CHARS:
        notes = cleaned_text
        source_mode = "全文直读"
    else:
        source_mode = f"分段提炼（{len(chunks)} 个片段）"
        summaries = []
        try:
            for index, item in enumerate(chunks, 1):
                summaries.append(
                    await _summarize_chunk(
                        title=title,
                        question=effective_question,
                        index=index,
                        total=len(chunks),
                        chunk=item,
                    )
                )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            return _fallback_document_payload(
                session_id=session_id,
                title=title,
                question=effective_question,
                text=cleaned_text,
                reason=_llm_error_message(exc),
            )
        notes = "\n\n".join(f"片段 {idx}：\n{summary}" for idx, summary in enumerate(summaries, 1))

    recent_history = []
    for item in (history or [])[-4:]:
        role = item.get("role")
        if role in ("user", "assistant") and item.get("content"):
            recent_history.append({"role": role, "content": str(item["content"])[:1000]})

    final_messages = [
        {
            "role": "system",
            "content": (
                "你是企业文件分析专家。用户上传了一个文件，你必须基于文件内容回答，"
                "不要默认去分析业务数据库。除非用户明确要求结合数据库，否则不要生成 SQL、不要讨论当前数据源。"
                "输出必须是 JSON 对象，字段：summary 字符串、insights 字符串数组、document_type 字符串、"
                "recommended_actions 字符串数组。"
                "如果用户要求报告，请给出多维度报告；如果用户要求提取信息，请按要求提取。"
                "所有结论必须来自文件内容，不确定处要说明“文件中未明确给出”。"
            ),
        },
        *recent_history,
        {
            "role": "user",
            "content": json.dumps(
                {
                    "file_name": filename,
                    "document_title": title,
                    "analysis_mode": source_mode,
                    "user_question": effective_question,
                    "document_notes": notes[:28000],
                    "truncated_notice": truncated_notice,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        result = await _llm_json(final_messages, timeout=80)
    except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _fallback_document_payload(
            session_id=session_id,
            title=title,
            question=effective_question,
            text=cleaned_text,
            reason=_llm_error_message(exc),
        )
    summary = str(result.get("summary") or "").strip()
    insights = [str(item).strip() for item in result.get("insights", []) if str(item).strip()]
    actions = [str(item).strip() for item in result.get("recommended_actions", []) if str(item).strip()]
    if actions:
        insights.extend([f"建议：{item}" for item in actions[:3]])
    if truncated_notice:
        insights.append(truncated_notice.strip())
    if not summary and insights:
        summary = insights[0]
    if not insights and summary:
        insights = [summary]
    if not summary:
        summary = "文件已解析，但模型没有生成有效结论。请换一种更具体的问题重新分析。"
        insights = [summary]

    intent_label = "report_generation" if any(key in effective_question for key in ("报告", "总结", "分析")) else "knowledge_qa"
    intent = IntentResult(intent_label, 0.9, "file_router", "上传文件触发文件专用分析")
    plan_steps = build_plan_steps(
        intent=intent,
        answer_type="knowledge_qa",
        execution_mode="document-llm",
        dataset_name=title,
        chart_type="none",
    )
    plan = ["解析上传文件", f"读取文件内容（{source_mode}）", "围绕用户问题生成文件分析结论"]
    return {
        "session_id": session_id,
        "message": summary,
        "intent": "文档分析" if intent_label == "knowledge_qa" else "报告生成",
        "intent_label": intent_label,
        "intent_confidence": 0.9,
        "intent_method": "file_router",
        "intent_reason": "上传文件触发文件专用分析",
        "sql_source": None,
        "plan": plan,
        "plan_steps": plan_steps,
        "sql": "",
        "columns": [],
        "rows": [],
        "chart": {
            "type": "none",
            "title": f"{title} - 文件分析",
            "x_field": "",
            "y_field": "",
            "series_name": "",
            "series_field": None,
            "series_fields": [],
        },
        "insights": insights,
        "knowledge_refs": [
            {
                "id": 0,
                "title": title,
                "content": cleaned_text[:1600],
                "category": str(result.get("document_type") or "uploaded_file"),
                "score": 1.0,
                "retrieval_mode": "uploaded-file",
            }
        ],
        "execution_mode": "document-llm",
        "answer_type": "knowledge_qa",
        "context_applied": False,
        "effective_question": effective_question,
    }
