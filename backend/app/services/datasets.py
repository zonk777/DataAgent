from __future__ import annotations

import io
import re
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import UploadFile

from ..config import get_settings
from ..db import connect, using_mysql
from .security import safe_identifier


NUMERIC_TYPE_TOKENS = ("int", "float", "double", "decimal", "real", "numeric", "number")


def _quote_identifier(name: str) -> str:
    if using_mysql():
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def _sql_type(dtype: Any) -> str:
    text = str(dtype).lower()
    if "int" in text:
        return "BIGINT" if using_mysql() else "INTEGER"
    if any(token in text for token in ("float", "double", "decimal")):
        return "DOUBLE" if using_mysql() else "REAL"
    if "bool" in text:
        return "TINYINT" if using_mysql() else "INTEGER"
    if "datetime" in text or "date" in text:
        return "DATETIME" if using_mysql() else "TEXT"
    return "TEXT"


def _clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value.item() if hasattr(value, "item") else value


def _read_file_frame(filename: str | None, content: bytes) -> pd.DataFrame:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise ValueError("仅支持 CSV、XLS、XLSX 文件")
    if suffix == ".csv":
        try:
            return pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(io.BytesIO(content), encoding="gb18030")
    return pd.read_excel(io.BytesIO(content))


def _normalize_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    if frame.empty or not len(frame.columns):
        raise ValueError("文件中没有可用数据")
    if len(frame.columns) > 200:
        raise ValueError("单个数据集最多支持 200 个字段")
    original_columns = [str(column) for column in frame.columns]
    sanitized: list[str] = []
    used: set[str] = set()
    for index, column in enumerate(original_columns):
        candidate = safe_identifier(column, f"column_{index + 1}")
        base = candidate
        counter = 2
        while candidate in used:
            candidate = f"{base}_{counter}"
            counter += 1
        used.add(candidate)
        sanitized.append(candidate)
    frame = frame.copy()
    frame.columns = sanitized
    return frame, original_columns


def _store_frame(
    frame: pd.DataFrame,
    original_columns: list[str],
    *,
    source_type: str,
    name: str,
    description: str,
) -> dict:
    table_name = f"data_{uuid.uuid4().hex[:12]}"
    with connect() as conn:
        column_defs = ", ".join(f"{_quote_identifier(column)} {_sql_type(frame[column].dtype)}" for column in frame.columns)
        engine = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if using_mysql() else ""
        conn.execute(f"CREATE TABLE {_quote_identifier(table_name)} ({column_defs}){engine}")
        if len(frame):
            columns_sql = ", ".join(_quote_identifier(column) for column in frame.columns)
            placeholders = ", ".join("?" for _ in frame.columns)
            values = [tuple(_clean_value(value) for value in row) for row in frame.itertuples(index=False, name=None)]
            conn.executemany(f"INSERT INTO {_quote_identifier(table_name)} ({columns_sql}) VALUES ({placeholders})", values)
        cursor = conn.execute(
            """INSERT INTO datasets(name, description, source_type, table_name, row_count, column_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, description, source_type, table_name, len(frame), len(frame.columns)),
        )
        dataset_id = int(cursor.lastrowid)
        for original, column in zip(original_columns, frame.columns):
            series = frame[column]
            sample = next((str(value) for value in series.head(20) if pd.notna(value)), None)
            null_rate = round(float(series.isna().mean()), 4)
            conn.execute(
                """INSERT INTO dataset_columns(dataset_id, name, data_type, description, sample_value, null_rate)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (dataset_id, str(column), str(series.dtype), original, sample, null_rate),
            )
    return get_dataset(dataset_id)


async def import_dataset(file: UploadFile, name: str | None = None, description: str = "") -> dict:
    settings = get_settings()
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError(f"文件不能超过 {settings.max_upload_mb}MB")
    frame = _read_file_frame(file.filename, content)
    frame, original_columns = _normalize_frame(frame)
    display_name = name or Path(file.filename or "数据集").stem
    suffix = Path(file.filename or "").suffix.lower().lstrip(".")
    return _store_frame(frame, original_columns, source_type=suffix or "file", name=display_name, description=description)


def import_mysql_dataset(payload: Any) -> dict:
    try:
        import pymysql
    except ImportError as exc:
        raise ValueError("未安装 pymysql，无法导入 MySQL 数据源；请先执行 pip install pymysql") from exc

    if not re.fullmatch(r"[A-Za-z0-9_]+", payload.table):
        raise ValueError("MySQL 表名仅支持字母、数字和下划线")
    try:
        mysql_conn = pymysql.connect(
            host=payload.host,
            port=payload.port,
            user=payload.username,
            password=payload.password,
            database=payload.database,
            charset="utf8mb4",
            connect_timeout=5,
            read_timeout=20,
        )
        with mysql_conn:
            query = f"SELECT * FROM `{payload.table}` LIMIT {int(payload.limit)}"
            frame = pd.read_sql_query(query, mysql_conn)
    except Exception as exc:
        raise ValueError(f"MySQL 连接或读取失败：{exc}") from exc

    frame, original_columns = _normalize_frame(frame)
    display_name = payload.name or f"{payload.database}.{payload.table}"
    return _store_frame(
        frame,
        original_columns,
        source_type="mysql",
        name=display_name,
        description=payload.description,
    )


def list_datasets(allowed_ids: list[int] | None = None) -> list[dict]:
    with connect() as conn:
        if allowed_ids is None:
            rows = conn.execute("SELECT * FROM datasets ORDER BY id DESC").fetchall()
        elif allowed_ids:
            placeholders = ",".join("?" for _ in allowed_ids)
            rows = conn.execute(
                f"SELECT * FROM datasets WHERE id IN ({placeholders}) ORDER BY id DESC",
                allowed_ids,
            ).fetchall()
        else:
            rows = []
    return [dict(row) for row in rows]


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
        preview = conn.execute(f"SELECT * FROM {_quote_identifier(result['table_name'])} LIMIT 100").fetchall()
        result["preview"] = [dict(item) for item in preview]
        return result


def update_dataset(dataset_id: int, name: str, description: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT id FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if not row:
            raise ValueError("数据集不存在")
        conn.execute(
            "UPDATE datasets SET name = ?, description = ? WHERE id = ?",
            (name.strip(), description, dataset_id),
        )
    return get_dataset(dataset_id)


def update_column_description(dataset_id: int, column_name: str, description: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM dataset_columns WHERE dataset_id = ? AND name = ?",
            (dataset_id, column_name),
        ).fetchone()
        if not row:
            raise ValueError("字段不存在")
        conn.execute(
            "UPDATE dataset_columns SET description = ? WHERE dataset_id = ? AND name = ?",
            (description, dataset_id, column_name),
        )
    return get_dataset(dataset_id)


def delete_dataset(dataset_id: int) -> None:
    with connect() as conn:
        row = conn.execute("SELECT table_name FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if not row:
            raise ValueError("数据集不存在")
        table_name = row["table_name"]
        conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(table_name)}")
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))


def dataset_quality(dataset_id: int) -> dict[str, Any]:
    dataset = get_dataset(dataset_id)
    columns = dataset.get("columns", [])
    table_name = dataset["table_name"]
    with connect() as conn:
        row_count = int(conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}").fetchone()[0])
        missing = []
        for column in columns:
            name = column["name"]
            quoted_name = _quote_identifier(name)
            missing_count = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {_quote_identifier(table_name)} WHERE {quoted_name} IS NULL OR TRIM(CAST({quoted_name} AS CHAR)) = ''"
                ).fetchone()[0]
            )
            missing.append(
                {
                    "column": name,
                    "missing_count": missing_count,
                    "missing_rate": round(missing_count / row_count, 4) if row_count else 0,
                }
            )
        if columns:
            group_columns = ", ".join(_quote_identifier(column["name"]) for column in columns)
            duplicate_row = conn.execute(
                f"SELECT COALESCE(SUM(cnt - 1), 0) FROM (SELECT COUNT(*) AS cnt FROM {_quote_identifier(table_name)} GROUP BY {group_columns} HAVING cnt > 1) t"
            ).fetchone()
            duplicate_rows = int(duplicate_row[0] or 0)
        else:
            duplicate_rows = 0
        rows = conn.execute(f"SELECT * FROM {_quote_identifier(table_name)}").fetchall()
        frame = pd.DataFrame([dict(row) for row in rows])

    outliers = []
    for column in columns:
        if not any(token in column["data_type"].lower() for token in NUMERIC_TYPE_TOKENS):
            continue
        series = pd.to_numeric(frame[column["name"]], errors="coerce").dropna()
        if series.empty:
            continue
        q1 = float(series.quantile(0.25))
        q3 = float(series.quantile(0.75))
        iqr = q3 - q1
        if iqr <= 0:
            count = 0
        else:
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            count = int(((series < lower) | (series > upper)).sum())
        outliers.append({"column": column["name"], "outlier_count": count})

    return {
        "dataset_id": dataset_id,
        "row_count": row_count,
        "column_count": len(columns),
        "duplicate_rows": duplicate_rows,
        "missing": missing,
        "outliers": outliers,
        "summary": [
            f"共 {row_count} 行、{len(columns)} 个字段",
            f"重复行 {duplicate_rows} 行",
            f"存在缺失值字段 {sum(1 for item in missing if item['missing_count'])} 个",
            f"疑似异常值字段 {sum(1 for item in outliers if item['outlier_count'])} 个",
        ],
    }
