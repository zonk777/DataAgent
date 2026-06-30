from __future__ import annotations

import math
import random
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Iterator

from .config import get_settings


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL,
    table_name TEXT NOT NULL UNIQUE,
    row_count INTEGER NOT NULL DEFAULT 0,
    column_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dataset_columns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    sample_value TEXT,
    null_rate REAL NOT NULL DEFAULT 0,
    UNIQUE(dataset_id, name)
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'business_rule',
    dataset_id INTEGER REFERENCES datasets(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    dataset_id INTEGER REFERENCES datasets(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'success',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    is_initial_admin INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_dataset_permissions (
    user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    PRIMARY KEY(user_id, dataset_id)
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token TEXT PRIMARY KEY,
    admin_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_file, timeout=settings.sql_timeout_seconds)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate_schema(conn)
        _seed_initial_admin(conn)
        exists = conn.execute("SELECT id FROM datasets LIMIT 1").fetchone()
        if not exists:
            _seed_demo_dataset(conn)


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})").fetchall())


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply lightweight SQLite migrations for existing local development databases."""
    if not _has_column(conn, "admin_users", "role"):
        conn.execute("ALTER TABLE admin_users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
    if not _has_column(conn, "audit_logs", "user_id"):
        conn.execute("ALTER TABLE audit_logs ADD COLUMN user_id INTEGER")
    if not _has_column(conn, "audit_logs", "username"):
        conn.execute("ALTER TABLE audit_logs ADD COLUMN username TEXT")
    if not _has_column(conn, "sessions", "user_id"):
        conn.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_dataset_permissions (
            user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
            dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
            PRIMARY KEY(user_id, dataset_id)
        )"""
    )
    conn.execute("UPDATE admin_users SET role = 'initial_admin' WHERE is_initial_admin = 1")
    conn.execute("UPDATE admin_users SET role = 'admin' WHERE role IS NULL OR role = ''")


def _seed_initial_admin(conn: sqlite3.Connection) -> None:
    exists = conn.execute("SELECT id FROM admin_users WHERE username = ?", ("liuze",)).fetchone()
    if exists:
        return
    from .services.auth import hash_password

    conn.execute(
        "INSERT INTO admin_users(username, password_hash, role, is_initial_admin) VALUES (?, ?, 'initial_admin', 1)",
        ("liuze", hash_password("18437431")),
    )


def _seed_demo_dataset(conn: sqlite3.Connection) -> None:
    table_name = "data_demo_sales"
    conn.execute(
        f"""CREATE TABLE {table_name} (
            order_date TEXT NOT NULL,
            region TEXT NOT NULL,
            product_category TEXT NOT NULL,
            channel TEXT NOT NULL,
            sales_amount REAL NOT NULL,
            order_count INTEGER NOT NULL,
            profit REAL NOT NULL,
            complaint_count INTEGER NOT NULL,
            visits INTEGER NOT NULL,
            conversions INTEGER NOT NULL
        )"""
    )

    rng = random.Random(20250622)
    regions = ["华东", "华南", "华北", "西南"]
    categories = ["智能设备", "办公用品", "家居生活", "企业服务"]
    channels = ["线上商城", "直营网点", "渠道合作"]
    start = date.today() - timedelta(days=119)
    rows = []
    for day_index in range(120):
        current = start + timedelta(days=day_index)
        trend = 1 + day_index / 900
        weekly = 1 + 0.09 * math.sin(day_index / 7 * math.pi * 2)
        for region_index, region in enumerate(regions):
            category = categories[(day_index + region_index) % len(categories)]
            channel = channels[(day_index + region_index * 2) % len(channels)]
            region_factor = [1.22, 1.08, 0.94, 0.82][region_index]
            decline = 0.72 if region == "华东" and 73 <= day_index <= 86 else 1.0
            orders = max(18, int((42 + rng.randint(-8, 11)) * region_factor * weekly * decline))
            unit_price = 168 + categories.index(category) * 38 + rng.randint(-12, 20)
            sales = round(orders * unit_price * trend, 2)
            profit = round(sales * (0.17 + rng.random() * 0.08), 2)
            complaints = max(0, int(orders * (0.012 + rng.random() * 0.026)))
            visits = orders * rng.randint(14, 22)
            conversions = orders + rng.randint(0, 5)
            rows.append((current.isoformat(), region, category, channel, sales, orders, profit, complaints, visits, conversions))

    conn.executemany(
        f"INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    cursor = conn.execute(
        """INSERT INTO datasets(name, description, source_type, table_name, row_count, column_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("企业经营演示数据", "近 120 天区域、品类、渠道经营指标", "demo", table_name, len(rows), 10),
    )
    dataset_id = cursor.lastrowid
    columns = [
        ("order_date", "DATE", "订单日期", rows[0][0]),
        ("region", "TEXT", "销售区域", rows[0][1]),
        ("product_category", "TEXT", "产品类别", rows[0][2]),
        ("channel", "TEXT", "销售渠道", rows[0][3]),
        ("sales_amount", "DECIMAL", "销售额，单位为元", str(rows[0][4])),
        ("order_count", "INTEGER", "成交订单数", str(rows[0][5])),
        ("profit", "DECIMAL", "毛利润，单位为元", str(rows[0][6])),
        ("complaint_count", "INTEGER", "客户投诉数量", str(rows[0][7])),
        ("visits", "INTEGER", "访问人数", str(rows[0][8])),
        ("conversions", "INTEGER", "完成转化人数", str(rows[0][9])),
    ]
    conn.executemany(
        """INSERT INTO dataset_columns(dataset_id, name, data_type, description, sample_value)
           VALUES (?, ?, ?, ?, ?)""",
        [(dataset_id, *column) for column in columns],
    )
    knowledge = [
        ("销售额口径", "销售额为已完成交易的含税成交金额之和，退款订单不计入。", "metric", dataset_id),
        ("投诉率口径", "投诉率 = 投诉数量 / 成交订单数，分析时至少聚合到日级。", "metric", dataset_id),
        ("转化率口径", "转化率 = 完成转化人数 / 访问人数。", "metric", dataset_id),
        ("区域说明", "企业当前按华东、华南、华北、西南四个大区进行经营管理。", "data_dictionary", dataset_id),
        ("异常判断规则", "指标较前一可比周期偏离 15% 以上时，应提示业务人员进一步核查。", "business_rule", dataset_id),
    ]
    conn.executemany(
        "INSERT INTO knowledge_chunks(title, content, category, dataset_id) VALUES (?, ?, ?, ?)",
        knowledge,
    )
