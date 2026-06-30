from pathlib import Path

from app.services.sql_generator import needs_complex_sql, query_plan_source
from scripts import evaluate_sql_generation


def test_sql_generation_reaches_target_accuracy() -> None:
    sample_path = Path(__file__).resolve().parents[1] / "evaluation" / "sql_samples.jsonl"
    samples = evaluate_sql_generation.load_samples(sample_path)
    result = evaluate_sql_generation.evaluate(samples)

    assert result["accuracy"] >= 0.85


def test_complex_sql_routing_metadata() -> None:
    assert needs_complex_sql("分析销售额同比增长") is True
    assert query_plan_source("分析销售额同比增长", None) == "template_sql_complex_fallback"
    assert query_plan_source("分析销售额同比增长", "SELECT 1 FROM data_demo_sales") == "llm_sql"
