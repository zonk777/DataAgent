from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .intent_classifier import IntentResult


@dataclass
class PlanStep:
    id: int
    title: str
    tool: str
    depends_on: list[int] = field(default_factory=list)
    status: str = "completed"
    detail: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _step(step_id: int, title: str, tool: str, depends_on: list[int] | None = None, detail: str = "") -> PlanStep:
    return PlanStep(id=step_id, title=title, tool=tool, depends_on=depends_on or [], detail=detail)


def _trim_steps(steps: list[PlanStep]) -> list[PlanStep]:
    return steps[:5]


def build_plan_steps(
    *,
    intent: IntentResult,
    answer_type: str,
    execution_mode: str,
    scope: str = "",
    dataset_name: str = "",
    chart_type: str = "",
) -> list[dict[str, Any]]:
    """Build a bounded tool-routed execution plan.

    The system still runs deterministic Python tools, but each step is explicit about
    which internal tool/function handles it and which prior step it depends on.
    """
    llm_note = "LLM 增强" if execution_mode == "llm-assisted" else "本地规则/模板"

    if intent.label == "report_generation":
        steps = [
            _step(1, f"识别意图：{intent.display_name}（置信度 {intent.confidence:.2f}）", "intent_classifier"),
            _step(2, "读取当前会话分析结果", "session_report_loader", [1]),
            _step(3, "选择报告导出器并组织报告结构", "report_builder_router", [2], llm_note),
            _step(4, "生成 Word/PDF/Markdown 文件", "report_exporter", [3]),
        ]
        return [step.to_payload() for step in _trim_steps(steps)]

    if answer_type == "knowledge_qa":
        steps = [
            _step(1, f"识别意图：{intent.display_name}（置信度 {intent.confidence:.2f}）", "intent_classifier"),
            _step(2, "混合检索知识片段", "knowledge_retriever", [1], "向量语义检索 + 关键词兜底"),
            _step(3, "按数据集权限过滤知识依据", "permission_filter", [2]),
            _step(4, "生成知识库回答", "knowledge_answer_generator", [3], llm_note),
        ]
        return [step.to_payload() for step in _trim_steps(steps)]

    if intent.label == "anomaly_attribution":
        steps = [
            _step(1, f"识别意图：{intent.display_name}（置信度 {intent.confidence:.2f}）", "intent_classifier"),
            _step(2, f"确定数据集与分析范围：{dataset_name or scope}", "dataset_profile_router", [1]),
            _step(3, "生成并校验只读 SQL", "sql_generator.validate_readonly_sql", [2]),
            _step(4, "执行聚合查询并进行异常维度下钻", "sql_executor.anomaly_drilldown", [3]),
            _step(5, f"生成{chart_type or '图表'}与归因结论", "chart_renderer.insight_generator", [4], llm_note),
        ]
        return [step.to_payload() for step in steps]

    steps = [
        _step(1, f"识别意图：{intent.display_name}（置信度 {intent.confidence:.2f}）", "intent_classifier"),
        _step(2, f"确定数据集与查询范围：{dataset_name or scope}", "dataset_profile_router", [1]),
        _step(3, "生成并校验只读 SQL", "sql_generator.validate_readonly_sql", [2]),
        _step(4, "执行查询并整理结果集", "sql_executor", [3]),
        _step(5, f"生成{chart_type or '图表'}与业务结论", "chart_renderer.insight_generator", [4], llm_note),
    ]
    return [step.to_payload() for step in steps]


def plan_titles(plan_steps: list[dict[str, Any]]) -> list[str]:
    return [str(step.get("title", "")) for step in plan_steps if step.get("title")]
