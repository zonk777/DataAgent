from app.services.chart_recommender import recommend_chart


def test_recommends_area_or_line_for_time_series() -> None:
    rows = [{"日期": f"2026-06-{day:02d}", "销售额": 100 + day} for day in range(1, 8)]

    result = recommend_chart("分析销售额趋势", "trend_analysis", rows, "日期", "销售额")

    assert result["type"] in {"area", "line"}
    assert result["distribution"]["is_time_series"] is True


def test_recommends_pie_for_small_share_question() -> None:
    rows = [{"区域": "华东", "销售额": 60}, {"区域": "华南", "销售额": 40}]

    result = recommend_chart("查看各地区销售额占比", "data_query", rows, "区域", "销售额")

    assert result["type"] == "pie"
    assert result["source"] == "data_distribution"


def test_recommends_dual_axis_when_numeric_scales_differ() -> None:
    rows = [
        {"日期": "2026-06-01", "销售额": 100000, "转化率": 0.12},
        {"日期": "2026-06-02", "销售额": 120000, "转化率": 0.15},
    ]

    result = recommend_chart("对比销售额和转化率趋势", "trend_analysis", rows, "日期", "销售额")

    assert result["display_mode"] == "dual_axis"
    assert result["secondary_y_field"] == "转化率"


def test_recommends_facet_when_series_are_too_many() -> None:
    rows = [
        {"日期": "2026-06-01", "区域": f"区域{i}", "销售额": i * 10}
        for i in range(8)
    ]

    result = recommend_chart("分析各区域销售额趋势", "trend_analysis", rows, "日期", "销售额", ["区域"])

    assert result["display_mode"] == "facet"
    assert result["facet_fields"] == ["区域"]
