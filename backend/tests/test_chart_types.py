from app.models import ChartSpec


def test_chart_spec_supports_required_six_chart_types() -> None:
    for chart_type in ("bar", "line", "pie", "scatter", "area", "radar"):
        spec = ChartSpec(type=chart_type, title="测试图表")
        assert spec.type == chart_type
