import asyncio

from app.db import connect, initialize_database
from app.services.analyzer import _build_query, _dataset, analyze
from app.services.intent_classifier import IntentResult
from app.services.security import validate_readonly_sql


def _run(question: str):
    initialize_database()
    dataset = _dataset(1)
    plan = _build_query(question, dataset, 500)
    sql = validate_readonly_sql(plan.sql, dataset["table_name"])
    with connect() as conn:
        rows = [dict(row) for row in conn.execute(sql, plan.params).fetchall()]
    return plan, rows


def test_recent_ten_days_by_region_returns_four_series() -> None:
    plan, rows = _run("分析近10天各地区销售额趋势")
    assert plan.x_field == "日期"
    assert plan.series_field == "区域"
    assert plan.series_fields == ["区域"]
    assert plan.time_description == "近10天"
    assert len({row["日期"] for row in rows}) == 10
    assert len({row["区域"] for row in rows}) == 4
    assert len(rows) == 40


def test_question_change_changes_metric_and_dimension() -> None:
    plan, rows = _run("查询投诉率最高的产品类别")
    assert plan.x_field == "产品类别"
    assert plan.y_field == "投诉率"
    assert plan.series_field is None
    assert plan.series_fields == []
    assert len(rows) == 4


def test_time_series_can_keep_region_and_add_product_breakdown() -> None:
    plan, rows = _run("分析近10天各地区销售额趋势；按产品类别拆分")
    assert plan.x_field == "日期"
    assert plan.series_field == "区域"
    assert plan.series_fields == ["区域", "产品类别"]
    assert len({row["日期"] for row in rows}) == 10
    assert len({row["区域"] for row in rows}) == 4
    assert len({row["产品类别"] for row in rows}) == 4
    assert len({(row["区域"], row["产品类别"]) for row in rows}) == 16
    assert len(rows) == 40


def test_product_typo_breakdown_is_supported() -> None:
    plan, rows = _run("分析近10天各地区销售额趋势；按展品拆分")
    assert plan.series_fields == ["区域", "产品类别"]
    assert rows


def test_python_analysis_is_used_for_complex_trend_question(monkeypatch) -> None:
    initialize_database()
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    async def fake_classify_intent(question, history):
        return IntentResult("trend_analysis", 0.99, "test", "python route")

    async def fake_generate_llm_sql(question, dataset, limit, business_knowledge=None, intent_reason=""):
        return None

    async def fake_polish_insights(question, rows, draft, knowledge, intent_reason="", plan_source=""):
        return draft

    async def fake_search_knowledge(question, dataset_id=None, limit=5):
        return []

    async def fake_execute_python_analysis(question, table_name, columns, row_count, knowledge, *, timeout=30):
        return {
            "success": True,
            "error": None,
            "traceback": None,
            "code": "print('ok')",
            "result": {
                "summary": "Python 已完成同比趋势分析。",
                "data": [{"维度": "华东", "同比": "-12.3%"}],
                "chart_suggestion": {"type": "bar", "x": "维度", "y": "同比"},
            },
        }

    monkeypatch.setattr("app.services.analyzer.classify_intent", fake_classify_intent)
    monkeypatch.setattr("app.services.analyzer.generate_llm_sql", fake_generate_llm_sql)
    monkeypatch.setattr("app.services.analyzer.polish_insights", fake_polish_insights)
    monkeypatch.setattr("app.services.analyzer.search_knowledge", fake_search_knowledge)
    monkeypatch.setattr("app.services.analyzer.execute_python_analysis", fake_execute_python_analysis)

    payload = asyncio.run(analyze("分析销售额同比趋势", None, None))

    assert payload["analysis_engine"] == "python_pandas"
    assert payload["execution_mode"] == "llm-python-pandas"
    assert payload["insights"] == ["Python 已完成同比趋势分析。"]
    assert payload["rows"] == [{"维度": "华东", "同比": "-12.3%"}]
    assert payload["chart"]["x_field"] == "维度"
    assert payload["chart"]["y_field"] == "同比"
    assert payload["python_code"] == "print('ok')"


def test_sql_auto_repair_recovers_from_bad_llm_sql(monkeypatch) -> None:
    initialize_database()
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    async def fake_classify_intent(question, history):
        return IntentResult("data_query", 0.99, "test", "sql repair route")

    async def fake_generate_llm_sql(question, dataset, limit, business_knowledge=None, intent_reason=""):
        return "SELECT missing_column FROM data_demo_sales LIMIT 10"

    async def fake_repair_llm_sql(question, dataset, limit, failed_sql, error, business_knowledge=None, intent_reason=""):
        assert "missing_column" in failed_sql
        return 'SELECT region AS "区域", ROUND(SUM(sales_amount), 2) AS "销售额" FROM data_demo_sales GROUP BY region LIMIT 500'

    async def fake_polish_insights(question, rows, draft, knowledge, intent_reason="", plan_source=""):
        return draft

    async def fake_search_knowledge(question, dataset_id=None, limit=5):
        return []

    monkeypatch.setattr("app.services.analyzer.classify_intent", fake_classify_intent)
    monkeypatch.setattr("app.services.analyzer.generate_llm_sql", fake_generate_llm_sql)
    monkeypatch.setattr("app.services.analyzer.repair_llm_sql", fake_repair_llm_sql)
    monkeypatch.setattr("app.services.analyzer.polish_insights", fake_polish_insights)
    monkeypatch.setattr("app.services.analyzer.search_knowledge", fake_search_knowledge)

    payload = asyncio.run(analyze("统计各地区销售额", None, None))

    assert payload["sql_source"] == "llm_sql_repair"
    assert payload["sql_repair"]["repaired"] is True
    assert payload["sql_repair"]["repair_attempts"] == 1
    assert payload["sql_repair"]["repair_success_rate"] == 1.0
    assert len(payload["sql_repair"]["history"]) == 2
    assert payload["rows"]
