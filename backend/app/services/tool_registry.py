"""Tool registry for Function Calling and ReAct agent.

Defines JSON Schema for each tool and provides a unified execution interface.
All tools are read-only — no data mutation.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from ..config import get_settings
from ..db import connect
from .knowledge import search_knowledge
from .security import validate_readonly_sql
from .chart_recommender import recommend_chart
from .llm import answer_from_knowledge


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI Function Calling format)
# ---------------------------------------------------------------------------
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_data",
            "description": "执行一条只读 SQL SELECT/WITH 查询，返回聚合或明细数据。用于统计销售额、订单数、投诉率等指标，支持 GROUP BY 分组和 WHERE 过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "只读 SELECT 或 WITH 查询语句。必须包含 LIMIT。"},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "从企业业务知识库中检索指标口径、业务规则、数据字典等信息。用于回答'什么是'、'如何计算'、口径定义类问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要检索的业务问题或关键词"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": "对比两个时间段的数据，计算变化率和贡献度。用于回答'为什么下降'、'变化原因'类归因问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_sql": {"type": "string", "description": "当前周期的 SQL 查询"},
                    "description": {"type": "string", "description": "用户问题的简要描述，用于生成上期对比 SQL"},
                },
                "required": ["current_sql", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python_analyze",
            "description": "对数据进行 Python/Pandas 深度分析，包括同比环比、异常检测、相关性分析、趋势预测等。适合数据量较大或需要复杂计算的场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "用户的分析问题"},
                    "table_name": {"type": "string", "description": "数据表名"},
                },
                "required": ["question", "table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_visualization",
            "description": "根据数据特征推荐最优图表类型和配置。在所有数据查询完成后调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "description": "分析意图类型"},
                    "x_field": {"type": "string", "description": "X 轴字段名"},
                    "y_field": {"type": "string", "description": "Y 轴字段名"},
                },
                "required": ["intent", "x_field", "y_field"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_quality",
            "description": "检查数据集的质量状况：缺失值、重复值、异常值、综合评分。在上传数据后或分析前调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "integer", "description": "数据集 ID"},
                },
                "required": ["dataset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_analysis",
            "description": "所有分析步骤完成后调用此工具输出最终结论。必须包含 insights（关键发现列表）和 chart（图表配置）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "分析结论摘要（1-3 句）"},
                    "insights": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关键发现列表（3-5 条）",
                    },
                    "chart_type": {"type": "string", "description": "推荐图表类型：bar/line/pie/scatter/area/radar"},
                    "intent_label": {"type": "string", "description": "分析意图标签"},
                },
                "required": ["summary", "insights", "chart_type"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution dispatcher
# ---------------------------------------------------------------------------
class ToolExecutor:
    """Stateless dispatcher that routes tool calls to the correct function."""

    def __init__(self, dataset_id: int | None, table_name: str = "", columns: list[dict] | None = None):
        self.dataset_id = dataset_id
        self.table_name = table_name
        self.columns = columns or []
        self.query_results: list[dict] = []
        self.knowledge_results: list[dict] = []
        self.intent_label = "data_query"

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Route and execute a tool call. Returns serialized result string."""
        if name == "query_data":
            return await self._query_data(arguments)
        if name == "search_knowledge_base":
            return await self._search_knowledge_base(arguments)
        if name == "compare_periods":
            return await self._compare_periods(arguments)
        if name == "python_analyze":
            return await self._python_analyze(arguments)
        if name == "recommend_visualization":
            return self._recommend_visualization(arguments)
        if name == "check_data_quality":
            return self._check_data_quality(arguments)
        if name == "finish_analysis":
            return self._finish_analysis(arguments)
        return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)

    async def _query_data(self, args: dict) -> str:
        sql = args["sql"].strip().rstrip(";")
        table = self.table_name or self._default_table()
        safe_sql = validate_readonly_sql(sql, table)
        with connect() as conn:
            rows = conn.execute(safe_sql).fetchall()
            result = [dict(row) for row in rows]
        self.query_results = result
        row_count = len(result)
        preview = result[:5] if result else []
        return json.dumps({"row_count": row_count, "preview": preview, "sql": safe_sql}, ensure_ascii=False, default=str)

    async def _search_knowledge_base(self, args: dict) -> str:
        question = args["question"]
        results = await search_knowledge(question, self.dataset_id, limit=5)
        self.knowledge_results = results
        return json.dumps(
            [{"title": r["title"], "content": r["content"][:300], "category": r.get("category", ""), "score": r.get("score", 0)} for r in results],
            ensure_ascii=False,
        )

    async def _compare_periods(self, args: dict) -> str:
        from .analyzer import _build_query, _column_profile, _draft_insights

        current_sql = args["current_sql"].strip().rstrip(";")
        description = args.get("description", "")

        # Get current period data
        with connect() as conn:
            current_rows = [dict(row) for row in conn.execute(current_sql).fetchall()]

        # Build comparison for previous period by modifying the description
        prev_desc = description.replace("近", "上期", 1) if "近" in description else f"上期 {description}"
        dataset = {"table_name": self.table_name, "columns": self.columns}
        prev_plan = _build_query(prev_desc, dataset, 100)

        with connect() as conn:
            prev_rows = [dict(row) for row in conn.execute(prev_plan.sql, prev_plan.params).fetchall()]

        # Calculate delta
        if not current_rows or not prev_rows:
            return json.dumps({"error": "无法获取对比数据", "current_rows": len(current_rows), "prev_rows": len(prev_rows)}, ensure_ascii=False)

        y_field = prev_plan.y_field
        curr_total = sum(float(r.get(y_field, 0) or 0) for r in current_rows)
        prev_total = sum(float(r.get(y_field, 0) or 0) for r in prev_rows)
        if prev_total == 0:
            return json.dumps({"delta_pct": 0, "current_total": curr_total, "prev_total": prev_total, "note": "上期数据为零，无法计算变化率"}, ensure_ascii=False)

        delta_pct = round((curr_total - prev_total) / prev_total * 100, 1)

        # Drill down by dimensions
        profile = _column_profile(self.columns)
        dims = []
        if profile.get("region"):
            dims.append((profile["region"], "区域"))
        if profile.get("product"):
            dims.append((profile["product"], "产品"))
        if profile.get("channel"):
            dims.append((profile["channel"], "渠道"))

        contributions = []
        for dim_col, dim_label in dims:
            curr_by: dict[str, float] = defaultdict(float)
            prev_by: dict[str, float] = defaultdict(float)
            for r in current_rows:
                curr_by[str(r.get(dim_col, "未知"))[:16]] += float(r.get(y_field, 0) or 0)
            for r in prev_rows:
                prev_by[str(r.get(dim_col, "未知"))[:16]] += float(r.get(y_field, 0) or 0)
            for val in set(curr_by) | set(prev_by):
                c, p = curr_by.get(val, 0), prev_by.get(val, 0)
                if p == 0:
                    continue
                contributions.append({
                    "dimension": dim_label, "value": val,
                    "delta_pct": round((c - p) / p * 100, 1),
                    "contribution_pct": round((c - p) / prev_total * 100, 1),
                })

        contributions.sort(key=lambda x: abs(x["contribution_pct"]), reverse=True)

        return json.dumps({
            "delta_pct": delta_pct,
            "current_total": round(curr_total, 2),
            "prev_total": round(prev_total, 2),
            "direction": "增长" if delta_pct > 0 else "下降",
            "top_contributors": contributions[:4],
            "current_preview": current_rows[:5],
            "prev_preview": prev_rows[:5],
        }, ensure_ascii=False, default=str)

    async def _python_analyze(self, args: dict) -> str:
        from .python_executor import execute_python_analysis

        question = args["question"]
        table_name = args.get("table_name", self.table_name)
        result = await execute_python_analysis(question, table_name, self.columns, len(self.query_results) or 100, self.knowledge_results)
        return json.dumps({
            "success": result.get("success"),
            "summary": (result.get("result") or {}).get("summary", "") if result.get("success") else result.get("error", ""),
            "data": (result.get("result") or {}).get("data", [])[:20],
        }, ensure_ascii=False, default=str)

    def _recommend_visualization(self, args: dict) -> str:
        chart = recommend_chart(
            args.get("description", ""),
            args.get("intent", self.intent_label),
            self.query_results,
            args.get("x_field", ""),
            args.get("y_field", ""),
            [],
        )
        return json.dumps({"type": chart["type"], "reason": chart.get("recommendation", {}).get("reason", ""), "alternatives": chart.get("alternatives", [])[:3]}, ensure_ascii=False)

    def _check_data_quality(self, args: dict) -> str:
        from .datasets import dataset_quality

        ds_id = args["dataset_id"]
        try:
            quality = dataset_quality(ds_id)
            return json.dumps({"quality_score": quality.get("quality_score"), "quality_level": quality.get("quality_level"), "summary": quality.get("summary_insights", [])[:3]}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    def _finish_analysis(self, args: dict) -> str:
        return json.dumps({"status": "complete", "summary": args.get("summary", ""), "insights": args.get("insights", []), "chart_type": args.get("chart_type", "bar")}, ensure_ascii=False)

    def _default_table(self) -> str:
        if self.table_name:
            return self.table_name
        with connect() as conn:
            row = conn.execute("SELECT table_name FROM datasets ORDER BY id LIMIT 1").fetchone()
        return row["table_name"] if row else "unknown"
