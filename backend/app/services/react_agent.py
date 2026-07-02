"""ReAct (Reasoning-Action-Observation) agent loop.

Replaces the linear pipeline with an iterative think-act-observe cycle:
  1. LLM receives question + tool schemas
  2. LLM decides: call a tool or finish
  3. Execute tool → observe result → back to step 2
  4. Max 5 turns, then force-finish

All tool calls respect the read-only constraint of the underlying tools.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import get_settings
from .mcp_client import McpClient
from .tool_registry import TOOL_SCHEMAS, ToolExecutor

logger = logging.getLogger(__name__)

MAX_REACT_TURNS = 5

SYSTEM_PROMPT = """你是企业数据智能体（DataAgent）。你拥有以下工具，通过调用它们来完成用户的分析请求。

核心规则：
1. 所有数据查询必须通过工具完成，不要凭空编造数字。
2. 每次只调用一个工具，等待结果后再决定下一步。
3. 分析路径：query_data（查数据） → 如果需要归因则 compare_periods → 如果需要深度计算则 python_analyze → 最后 recommend_visualization → finish_analysis。
4. 如果是知识类问题（什么是/如何计算/口径/定义），用 search_knowledge_base 直接回答。
5. 最多分析 3 步，不要过度循环。
6. 分析完成后必须调用 finish_analysis 输出最终结论。
7. 如果工具返回错误，尝试换一种方式查询；最多重试一次。
8. 你正在处理的数据在数据表 {table_name} 中，只查询这个表。"""
TABLE_NAME_HINT = " 数据表: {table_name}，列: {columns}"


def _extract_tool_calls(response: dict) -> list[dict]:
    """Extract tool calls from LLM response."""
    message = response.get("choices", [{}])[0].get("message", {})
    return message.get("tool_calls") or []


def _extract_text(response: dict) -> str:
    """Extract text content from LLM response."""
    message = response.get("choices", [{}])[0].get("message", {})
    return (message.get("content") or "").strip()


async def _call_llm(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Low-level LLM call with optional tools."""
    settings = get_settings()
    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "temperature": 0.1,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def run_react_loop(
    question: str,
    dataset_id: int | None,
    table_name: str = "",
    columns: list[dict] | None = None,
    history: list[dict] | None = None,
    *,
    use_mcp: bool = False,
) -> dict[str, Any]:
    """Execute a ReAct reasoning loop for a single user question.

    Args:
        use_mcp: If True, discover tools dynamically via MCP client (list_tools + call_tool).
                 If False, use hardcoded TOOL_SCHEMAS + ToolExecutor.

    Returns a dict compatible with the existing AnalysisResponse format.
    """
    settings = get_settings()
    if not settings.llm_configured:
        return _fallback_result(question, "LLM 未配置，无法运行 ReAct 分析")

    executor = ToolExecutor(dataset_id=dataset_id, table_name=table_name, columns=columns or [])

    # ── MCP path: dynamic tool discovery ──
    mcp_client: McpClient | None = None
    tool_schemas: list[dict] = TOOL_SCHEMAS
    if use_mcp:
        try:
            mcp_client = McpClient()
            tool_schemas = await mcp_client.get_tool_schemas()
            logger.info("MCP: discovered %d tools", len(tool_schemas))
        except Exception as exc:
            logger.warning("MCP client init failed, falling back to hardcoded tools: %s", exc)

    # Build message list from history, injecting table schema context
    cols_summary = ", ".join(c.get("name", "") for c in (columns or [])[:8]) if columns else "未知"
    table_hint = TABLE_NAME_HINT.format(table_name=table_name or "data", columns=cols_summary)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + table_hint}]
    for item in (history or [])[-4:]:
        role = item.get("role")
        if role in ("user", "assistant") and item.get("content"):
            messages.append({"role": role, "content": str(item["content"])[:800]})
    messages.append({"role": "user", "content": question})

    analysis_plan: list[dict] = []
    sql_executed = ""
    chart_result: dict = {"type": "bar", "title": ""}
    insights: list[str] = []
    final_summary = ""
    last_llm_error: Exception | None = None

    for turn in range(MAX_REACT_TURNS):
        try:
            response = await _call_llm(messages, tool_schemas)
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            logger.warning("ReAct turn %d LLM call failed: %s", turn + 1, exc)
            last_llm_error = exc
            if not analysis_plan and not executor.query_results and not executor.knowledge_results:
                raise RuntimeError(f"ReAct 模型调用失败，尚未执行任何分析工具：{exc}") from exc
            break

        tool_calls = _extract_tool_calls(response)
        text = _extract_text(response)

        if not tool_calls:
            # LLM thinks it's done — but we should force finish_analysis
            if turn >= MAX_REACT_TURNS - 1 or "完成" in text or "结论" in text:
                final_summary = text
                break
            # Otherwise, prompt LLM to continue
            messages.append({"role": "assistant", "content": text or "继续分析"})
            messages.append({"role": "user", "content": "请使用工具继续分析，或调用 finish_analysis 总结结论。"})
            continue

        # Execute each tool call
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}

            analysis_plan.append({
                "step": len(analysis_plan) + 1,
                "tool": fn_name,
                "args_summary": str(fn_args)[:100],
                "turn": turn + 1,
            })

            # Execute via MCP or direct executor
            if mcp_client:
                result_str = await mcp_client.call_tool(fn_name, fn_args)
            else:
                result_str = await executor.execute(fn_name, fn_args)

            if fn_name == "query_data" and not sql_executed:
                try:
                    sql_executed = json.loads(result_str).get("sql", "")
                except json.JSONDecodeError:
                    pass

            if fn_name == "recommend_visualization":
                try:
                    chart_result.update(json.loads(result_str))
                except json.JSONDecodeError:
                    pass

            if fn_name == "finish_analysis":
                try:
                    finish_data = json.loads(result_str)
                    final_summary = finish_data.get("summary", "")
                    insights = finish_data.get("insights", [])
                    chart_result["type"] = finish_data.get("chart_type", "bar")
                except json.JSONDecodeError:
                    pass
                break

            # Record tool result as observation
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [tc],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_str[:2000],
            })

        # If finish_analysis was called, exit loop
        if any(tc["function"]["name"] == "finish_analysis" for tc in tool_calls):
            break

        # Safety: if we've done query_data + recommend, auto-finish
        tools_used = {tc["function"]["name"] for tc in tool_calls}
        if "finish_analysis" not in tools_used and turn >= MAX_REACT_TURNS - 1:
            messages.append({"role": "user", "content": "你已经完成了工具调用。请现在调用 finish_analysis 输出最终结论（中文，简洁）。"})

    # If LLM never called finish_analysis, force-generate a conclusion
    if not final_summary and executor.query_results:
        final_summary = _force_conclusion(executor, messages)
    if not analysis_plan and not executor.query_results and not executor.knowledge_results:
        if last_llm_error:
            raise RuntimeError(f"ReAct 分析没有执行任何工具，模型调用失败：{last_llm_error}") from last_llm_error
        raise RuntimeError("ReAct 分析没有执行任何工具，无法确认已经完成数据查询或文档分析")
    if not executor.query_results and not executor.knowledge_results and not sql_executed:
        raise RuntimeError("ReAct 分析没有获取到任何数据结果或知识依据，因此不能标记为分析完成")
    if not final_summary and not insights and sql_executed and not executor.query_results:
        final_summary = "已执行数据查询，但当前条件下没有匹配到数据。请检查筛选条件、时间范围、字段名称，或换一个数据源后再试。"
        insights = [final_summary]
        chart_result["type"] = "none"
    if not final_summary and not insights and executor.knowledge_results:
        final_summary = "已检索到相关文档或业务知识，但模型没有生成最终总结。请换一种问法，或检查模型 API 是否支持工具调用。"
        insights = [final_summary]
        chart_result["type"] = "none"

    plan_lines = _format_analysis_plan(analysis_plan)
    plan_steps = _analysis_plan_steps(analysis_plan)

    return {
        "message": final_summary or "分析完成。",
        "intent": executor.intent_label,
        "plan": plan_lines,
        "plan_steps": plan_steps,
        "sql": sql_executed,
        "columns": list(executor.query_results[0].keys()) if executor.query_results else [],
        "rows": executor.query_results[:50],
        "chart": {
            "type": chart_result.get("type", "bar"),
            "title": chart_result.get("title", "分析结果"),
            "x_field": chart_result.get("x_field", ""),
            "y_field": chart_result.get("y_field", ""),
            "series_name": "",
            "series_field": None,
            "series_fields": [],
        },
        "insights": insights or [final_summary] if final_summary else ["分析完成，请查看数据和图表。"],
        "knowledge_refs": executor.knowledge_results,
        "execution_mode": "react-agent" if settings.llm_configured else "local-demo",
        "answer_type": "data_analysis",
        "context_applied": False,
        "effective_question": question,
        "react_turns": len(analysis_plan),
    }


def _format_analysis_plan(plan: list[dict]) -> list[str]:
    """Convert structured ReAct tool steps to the legacy response shape."""
    lines: list[str] = []
    for index, item in enumerate(plan, 1):
        tool = str(item.get("tool") or "tool")
        turn = item.get("turn")
        args = str(item.get("args_summary") or "").strip()
        prefix = f"第 {item.get('step') or index} 步：调用 {tool}"
        if turn:
            prefix += f"（第 {turn} 轮）"
        if args:
            prefix += f"：{args}"
        lines.append(prefix)
    return lines


def _analysis_plan_steps(plan: list[dict]) -> list[dict]:
    """Expose ReAct steps through the newer structured plan_steps field."""
    steps: list[dict] = []
    for index, item in enumerate(plan, 1):
        tool = str(item.get("tool") or "tool")
        args = str(item.get("args_summary") or "").strip()
        try:
            step_id = int(item.get("step") or index)
        except (TypeError, ValueError):
            step_id = index
        steps.append({
            "id": step_id,
            "title": f"调用 {tool}",
            "tool": tool,
            "depends_on": [step_id - 1] if step_id > 1 else [],
            "status": "completed",
            "detail": args,
        })
    return steps


def _force_conclusion(executor: ToolExecutor, messages: list[dict]) -> str:
    """Force-generate a conclusion from accumulated data when LLM didn't finish."""
    if not executor.query_results:
        return "未获取到数据结果。"
    row_count = len(executor.query_results)
    preview = executor.query_results[:5]
    prompt = f"基于以下 {row_count} 行数据的前 5 行，用 1-2 句中文总结关键发现：\n{json.dumps(preview, ensure_ascii=False, default=str)[:800]}"
    messages.append({"role": "user", "content": prompt})
    try:
        resp = httpx.Client(timeout=20).post(
            f"{get_settings().llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {get_settings().llm_api_key}"},
            json={"model": get_settings().llm_model, "temperature": 0.2, "messages": [{"role": "user", "content": prompt}]},
        )
        return resp.json()["choices"][0]["message"]["content"].strip() or "分析完成。"
    except Exception:
        return f"分析完成，共获得 {row_count} 条数据。"


def _fallback_result(question: str, reason: str) -> dict:
    return {
        "message": reason,
        "intent": "指标查询",
        "plan": [],
        "sql": "",
        "columns": [],
        "rows": [],
        "chart": {"type": "none", "title": "分析不可用", "x_field": "", "y_field": "", "series_field": None, "series_fields": []},
        "insights": [reason],
        "knowledge_refs": [],
        "execution_mode": "offline",
        "answer_type": "data_analysis",
        "context_applied": False,
        "effective_question": question,
        "react_turns": 0,
    }
