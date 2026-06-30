from __future__ import annotations

import io
import uuid
from pathlib import Path

import pandas as pd
from fastapi import UploadFile

from ..config import get_settings
from ..db import connect
from .security import safe_identifier


async def import_dataset(file: UploadFile, name: str | None = None, description: str = "") -> dict:
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise ValueError("仅支持 CSV 或 XLSX 文件")
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError(f"文件不能超过 {settings.max_upload_mb}MB")

    if suffix == ".csv":
        try:
            frame = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
        except UnicodeDecodeError:
            frame = pd.read_csv(io.BytesIO(content), encoding="gb18030")
    else:
        frame = pd.read_excel(io.BytesIO(content))
    if frame.empty or not len(frame.columns):
        raise ValueError("文件中没有可用数据")
    if len(frame.columns) > 200:
        raise ValueError("单个数据集最多支持 200 个字段")

    original_columns = [str(column) for column in frame.columns]
    sanitized = []
    used = set()
    for index, column in enumerate(original_columns):
        candidate = safe_identifier(column, f"column_{index + 1}")
        while candidate in used:
            candidate = f"{candidate}_{index + 1}"
        used.add(candidate)
        sanitized.append(candidate)
    frame.columns = sanitized
    table_name = f"data_{uuid.uuid4().hex[:12]}"
    display_name = name or Path(file.filename or "数据集").stem

    with connect() as conn:
        frame.to_sql(table_name, conn, index=False, if_exists="fail")
        cursor = conn.execute(
            """INSERT INTO datasets(name, description, source_type, table_name, row_count, column_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (display_name, description, suffix.lstrip("."), table_name, len(frame), len(frame.columns)),
        )
        dataset_id = cursor.lastrowid
        for original, column in zip(original_columns, sanitized):
            series = frame[column]
            sample = next((str(value) for value in series.head(20) if pd.notna(value)), None)
            null_rate = round(float(series.isna().mean()), 4)
            conn.execute(
                """INSERT INTO dataset_columns(dataset_id, name, data_type, description, sample_value, null_rate)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (dataset_id, column, str(series.dtype), original, sample, null_rate),
            )
        conn.execute(
            "INSERT INTO audit_logs(action, resource_type, resource_id, detail) VALUES ('upload', 'dataset', ?, ?)",
            (str(dataset_id), file.filename or display_name),
        )
    return get_dataset(dataset_id)


def list_datasets() -> list[dict]:
    with connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM datasets ORDER BY id DESC").fetchall()]


def get_dataset(dataset_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if not row:
            raise ValueError("数据集不存在")
        result = dict(row)
        result["columns"] = [
            dict(item)
            for item in conn.execute(
                "SELECT name, data_type, description, sample_value, null_rate FROM dataset_columns WHERE dataset_id = ? ORDER BY id",
                (dataset_id,),
            ).fetchall()
        ]
        preview = conn.execute(f"SELECT * FROM {result['table_name']} LIMIT 20").fetchall()
        result["preview"] = [dict(item) for item in preview]
        return result

