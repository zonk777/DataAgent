"""Data Profiler — generates a human-readable data summary for LLM consumption."""

from __future__ import annotations

from ..db import connect


def profile_dataset(dataset_id: int) -> str:
    """Generate a compact data profile: schema, quality, samples, dimensions.

    Reuses existing dataset_quality() for quality stats.
    """
    from .datasets import dataset_quality

    with connect() as conn:
        ds = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if not ds:
            return "数据集不存在"
        ds = dict(ds)
        cols = conn.execute("SELECT * FROM dataset_columns WHERE dataset_id = ? ORDER BY id", (dataset_id,)).fetchall()
        columns = [dict(c) for c in cols]

    parts = [f"数据集: {ds['name']}（{ds['source_type']}, {ds['row_count']}行, {len(columns)}列）"]

    # Column profile
    parts.append("\n字段清单:")
    for c in columns:
        sample = f' [{c.get("sample_value","")[:30]}]' if c.get("sample_value") else ""
        desc = f' — {c["description"]}' if c.get("description") else ""
        parts.append(f"  • {c['name']} ({c['data_type']}){desc}{sample}")

    # Quality summary
    try:
        quality = dataset_quality(dataset_id)
        parts.append(f"\n数据质量: {quality.get('quality_score',0)}/100 ({quality.get('quality_level','')})")
    except Exception:
        pass

    # Detect available dimensions
    dims = _detect_dimensions(columns)
    parts.append(f"\n可用分析维度: {', '.join(dims) if dims else '（无明确维度）'}")

    return "\n".join(parts)


def _detect_dimensions(columns: list[dict]) -> list[str]:
    dims = []
    for c in columns:
        name = c["name"].lower()
        dtype = c.get("data_type", "").lower()
        if any(t in name for t in ("date", "time", "日期", "时间")):
            dims.append(f"时间({c['name']})")
        elif any(t in dtype for t in ("int", "float", "decimal", "number", "real")):
            dims.append(f"数值({c['name']})")
        else:
            dims.append(f"分类({c['name']})")
    return dims
