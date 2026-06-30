from __future__ import annotations

import re
from statistics import mean, pstdev
from typing import Any


CHART_TYPES = ("bar", "line", "pie", "scatter", "area", "radar")


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _numeric_values(rows: list[dict[str, Any]], field: str | None) -> list[float]:
    if not field:
        return []
    return [value for row in rows if (value := _to_float(row.get(field))) is not None]


def _numeric_columns(rows: list[dict[str, Any]], exclude: set[str]) -> list[str]:
    if not rows:
        return []
    columns = [column for column in rows[0].keys() if column not in exclude]
    result = []
    for column in columns:
        values = _numeric_values(rows, column)
        if values and len(values) >= max(1, len(rows) // 2):
            result.append(column)
    return result


def _series_key(row: dict[str, Any], series_fields: list[str]) -> str:
    if not series_fields:
        return ""
    return " / ".join(str(row.get(field) or "未分类") for field in series_fields)


def _looks_time(labels: list[str], x_field: str | None) -> bool:
    if x_field and any(token in x_field.lower() for token in ("date", "time", "日期", "时间", "月份", "月")):
        return True
    sampled = labels[:8]
    if not sampled:
        return False
    matched = sum(1 for label in sampled if re.search(r"\d{4}[-/年]\d{1,2}", label))
    return matched >= max(1, len(sampled) // 2)


def _keyword_override(question: str) -> tuple[str | None, str | None]:
    lower = question.lower()
    mapping = [
        (("雷达图", "radar"), "radar", "用户明确要求雷达图"),
        (("面积图", "area"), "area", "用户明确要求面积图"),
        (("散点图", "scatter"), "scatter", "用户明确要求散点图"),
        (("柱状图", "柱形图", "bar"), "bar", "用户明确要求柱状图"),
        (("折线图", "line"), "line", "用户明确要求折线图"),
        (("饼图", "pie"), "pie", "用户明确要求饼图"),
    ]
    for keywords, chart_type, reason in mapping:
        if any(keyword in lower or keyword in question for keyword in keywords):
            return chart_type, reason
    return None, None


def _scale(values: list[float]) -> float:
    if not values:
        return 0.0
    return max(abs(value) for value in values)


def _alternatives(primary: str, display_mode: str, label_count: int, series_count: int) -> list[str]:
    preferred = {
        "line": ["area", "bar", "scatter"],
        "area": ["line", "bar", "scatter"],
        "bar": ["radar", "pie", "line"],
        "pie": ["bar", "radar"],
        "scatter": ["line", "bar"],
        "radar": ["bar", "pie"],
    }.get(primary, ["bar", "line"])
    if label_count > 12:
        preferred = [item for item in preferred if item not in {"pie", "radar"}]
    if series_count > 6:
        preferred = [item for item in preferred if item != "pie"]
    if display_mode == "dual_axis":
        preferred.insert(0, "line")
    return [item for item in dict.fromkeys(preferred) if item != primary and item in CHART_TYPES][:4]


def recommend_chart(
    question: str,
    intent_label: str | None,
    rows: list[dict[str, Any]],
    x_field: str | None,
    y_field: str | None,
    series_fields: list[str] | None = None,
) -> dict[str, Any]:
    series_fields = series_fields or []
    if not rows or not x_field or not y_field:
        return {
            "type": "none",
            "source": "empty_result",
            "reason": "当前结果为空或缺少可视化字段",
            "confidence": 0.0,
            "alternatives": [],
            "display_mode": "single",
            "secondary_y_field": None,
            "facet_fields": [],
            "distribution": {},
        }

    labels = [str(row.get(x_field) or "") for row in rows]
    label_count = len(set(labels))
    series_count = len({ _series_key(row, series_fields) for row in rows }) if series_fields else 1
    values = _numeric_values(rows, y_field)
    value_mean = mean(values) if values else 0.0
    value_cv = (pstdev(values) / abs(value_mean)) if values and value_mean else 0.0
    is_time = _looks_time(labels, x_field)
    share_terms = any(term in question for term in ("占比", "构成", "比例", "份额"))
    compare_terms = any(term in question for term in ("对比", "比较", "排名", "排行", "最高", "最低"))

    exclude = {x_field, y_field, *series_fields}
    numeric_columns = _numeric_columns(rows, exclude)
    display_mode = "single"
    secondary_y_field = None
    facet_fields: list[str] = []

    y_scale = _scale(values)
    for column in numeric_columns:
        other_values = _numeric_values(rows, column)
        other_scale = _scale(other_values)
        if y_scale and other_scale and max(y_scale, other_scale) / max(min(y_scale, other_scale), 1e-9) >= 8:
            secondary_y_field = column
            display_mode = "dual_axis"
            break

    if series_count > 6 or len(series_fields) > 1:
        display_mode = "facet"
        facet_fields = series_fields[:2]

    override_type, override_reason = _keyword_override(question)
    if override_type:
        chart_type = override_type
        source = "keyword_override"
        reason = override_reason or "用户关键词覆盖自动推荐"
        confidence = 0.95
    elif share_terms and label_count <= 8 and series_count <= 1:
        chart_type = "pie"
        source = "data_distribution"
        reason = "问题关注占比且分类数量较少，适合用饼图表达构成"
        confidence = 0.88
    elif is_time and display_mode == "dual_axis":
        chart_type = "line"
        source = "data_distribution"
        reason = "时间序列中存在两个量纲差异较大的指标，建议折线图并采用双轴提示"
        confidence = 0.86
    elif is_time and len(values) >= 5:
        chart_type = "area" if value_cv < 1.2 and series_count <= 3 and all(value >= 0 for value in values) else "line"
        source = "intent_distribution"
        reason = "结果按时间排列，适合展示趋势；波动较平稳时使用面积图突出累计规模"
        confidence = 0.84
    elif intent_label == "anomaly_attribution":
        chart_type = "bar"
        source = "intent_distribution"
        reason = "异常归因更关注维度贡献差异，柱状图更便于比较"
        confidence = 0.82
    elif label_count <= 8 and series_count >= 3 and compare_terms:
        chart_type = "radar"
        source = "data_distribution"
        reason = "分类较少且包含多组对比，雷达图适合展示多维轮廓差异"
        confidence = 0.78
    elif label_count > 20 and values:
        chart_type = "scatter"
        source = "data_distribution"
        reason = "分类点较多，散点图可以减少拥挤并观察离散分布"
        confidence = 0.74
    else:
        chart_type = "bar"
        source = "fallback"
        reason = "默认使用柱状图展示分类指标对比，阅读成本最低"
        confidence = 0.7

    return {
        "type": chart_type,
        "source": source,
        "reason": reason,
        "confidence": confidence,
        "alternatives": _alternatives(chart_type, display_mode, label_count, series_count),
        "display_mode": display_mode,
        "secondary_y_field": secondary_y_field,
        "facet_fields": facet_fields,
        "distribution": {
            "row_count": len(rows),
            "category_count": label_count,
            "series_count": series_count,
            "is_time_series": is_time,
            "value_cv": round(value_cv, 4),
            "numeric_columns": numeric_columns[:6],
        },
    }
