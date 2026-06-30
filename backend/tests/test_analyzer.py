from app.db import connect, initialize_database
from app.services.analyzer import _build_query, _dataset
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
