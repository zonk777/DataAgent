from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db import SCHEMA_MYSQL  # noqa: E402


SYSTEM_TABLES = [
    "datasets",
    "dataset_columns",
    "admin_users",
    "knowledge_chunks",
    "sessions",
    "messages",
    "audit_logs",
    "user_dataset_permissions",
    "admin_sessions",
]


def mysql_conn(database: str | None = None):
    settings = get_settings()
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


def q(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def sqlite_type_to_mysql(sqlite_type: str) -> str:
    text = (sqlite_type or "").lower()
    if "int" in text:
        return "BIGINT"
    if any(token in text for token in ("real", "float", "double", "decimal", "numeric")):
        return "DOUBLE"
    if "date" in text or "time" in text:
        return "VARCHAR(64)"
    return "LONGTEXT"


def rows_from_sqlite(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
    return [dict(row) for row in rows]


def insert_rows(mysql, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    sql = f"INSERT INTO {q(table)} ({', '.join(q(column) for column in columns)}) VALUES ({', '.join(['%s'] * len(columns))})"
    values = [tuple(row.get(column) for column in columns) for row in rows]
    with mysql.cursor() as cursor:
        cursor.executemany(sql, values)


def recreate_database() -> None:
    settings = get_settings()
    conn = mysql_conn(None)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS {q(settings.mysql_database)}")
            cursor.execute(
                f"CREATE DATABASE {q(settings.mysql_database)} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    finally:
        conn.close()


def create_schema(mysql) -> None:
    with mysql.cursor() as cursor:
        for statement in SCHEMA_MYSQL:
            cursor.execute(statement)


def create_data_table(mysql, sqlite: sqlite3.Connection, table: str) -> None:
    columns = sqlite.execute(f'PRAGMA table_info("{table}")').fetchall()
    column_defs = ", ".join(f"{q(row['name'])} {sqlite_type_to_mysql(row['type'])}" for row in columns)
    with mysql.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {q(table)}")
        cursor.execute(
            f"CREATE TABLE {q(table)} ({column_defs}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        )


def migrate(reset: bool) -> None:
    settings = get_settings()
    sqlite_path = settings.database_file
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite 文件不存在：{sqlite_path}")
    if reset:
        recreate_database()
    sqlite = sqlite3.connect(sqlite_path)
    sqlite.row_factory = sqlite3.Row
    mysql = mysql_conn(settings.mysql_database)
    try:
        create_schema(mysql)
        dataset_rows = rows_from_sqlite(sqlite, "datasets")
        data_tables = [row["table_name"] for row in dataset_rows]
        with mysql.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        for table in data_tables:
            create_data_table(mysql, sqlite, table)
            insert_rows(mysql, table, rows_from_sqlite(sqlite, table))
        for table in SYSTEM_TABLES:
            rows = rows_from_sqlite(sqlite, table)
            if rows:
                insert_rows(mysql, table, rows)
        with mysql.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        mysql.commit()
        print(f"迁移完成：{len(dataset_rows)} 个数据源，{len(data_tables)} 张业务数据表。")
    except Exception:
        mysql.rollback()
        raise
    finally:
        sqlite.close()
        mysql.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate DataAgent SQLite storage to MySQL.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate target MySQL database first.")
    args = parser.parse_args()
    migrate(reset=args.reset)


if __name__ == "__main__":
    main()
