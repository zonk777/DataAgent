from app.services.intent_classifier import IntentResult
from app.services.planner import build_plan_steps, plan_titles


def test_data_analysis_plan_has_tool_routes_and_dependencies() -> None:
    steps = build_plan_steps(
        intent=IntentResult("trend_analysis", 0.93, "rules"),
        answer_type="data_analysis",
        execution_mode="local-demo",
        scope="近10天、区域",
        dataset_name="企业经营演示数据",
        chart_type="line",
    )

    assert len(steps) <= 5
    assert all(step["tool"] for step in steps)
    assert steps[0]["depends_on"] == []
    assert steps[-1]["depends_on"]
    assert plan_titles(steps) == [step["title"] for step in steps]


def test_anomaly_plan_includes_drilldown_step() -> None:
    steps = build_plan_steps(
        intent=IntentResult("anomaly_attribution", 0.92, "rules"),
        answer_type="data_analysis",
        execution_mode="llm-assisted",
        scope="区域",
        dataset_name="企业经营演示数据",
        chart_type="bar",
    )

    assert len(steps) == 5
    assert any("下钻" in step["title"] or "drilldown" in step["tool"] for step in steps)


def test_knowledge_plan_has_four_steps() -> None:
    steps = build_plan_steps(
        intent=IntentResult("knowledge_qa", 0.94, "rules"),
        answer_type="knowledge_qa",
        execution_mode="llm-assisted",
    )

    assert len(steps) == 4
    assert steps[1]["tool"] == "knowledge_retriever"
