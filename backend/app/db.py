from __future__ import annotations

import math
import random
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor
from sqlalchemy import create_engine

from .config import get_settings


class _MysqlWrapper:
    """Thin wrapper to make pymysql behave like sqlite3.Connection for minimal code changes."""

    def __init__(self, conn: pymysql.Connection):
        self._conn = conn

    def execute(self, sql: str, params=None):
        cursor = self._conn.cursor()
        cursor.execute(sql, params)
        return cursor

    def executemany(self, sql: str, seq_of_params):
        cursor = self._conn.cursor()
        cursor.executemany(sql, seq_of_params)
        return cursor

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS datasets (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        source_type VARCHAR(32) NOT NULL,
        table_name VARCHAR(128) NOT NULL UNIQUE,
        row_count INT NOT NULL DEFAULT 0,
        column_count INT NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL DEFAULT 'ready',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS dataset_columns (
        id INT AUTO_INCREMENT PRIMARY KEY,
        dataset_id INT NOT NULL,
        name VARCHAR(128) NOT NULL,
        data_type VARCHAR(32) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        sample_value TEXT,
        null_rate DOUBLE NOT NULL DEFAULT 0,
        UNIQUE(dataset_id, name),
        FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        content TEXT NOT NULL,
        category VARCHAR(64) NOT NULL DEFAULT 'business_rule',
        dataset_id INT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id VARCHAR(64) PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        dataset_id INT,
        user_id INT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE SET NULL
    )""",
    """CREATE TABLE IF NOT EXISTS messages (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        role VARCHAR(16) NOT NULL,
        content TEXT NOT NULL,
        payload TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS audit_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT,
        username VARCHAR(128),
        action VARCHAR(64) NOT NULL,
        resource_type VARCHAR(64) NOT NULL,
        resource_id VARCHAR(128),
        detail TEXT NOT NULL DEFAULT '',
        status VARCHAR(32) NOT NULL DEFAULT 'success',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS admin_users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(128) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(32) NOT NULL DEFAULT 'admin',
        is_initial_admin TINYINT NOT NULL DEFAULT 0,
        created_by INT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (created_by) REFERENCES admin_users(id) ON DELETE SET NULL
    )""",
    """CREATE TABLE IF NOT EXISTS user_dataset_permissions (
        user_id INT NOT NULL,
        dataset_id INT NOT NULL,
        PRIMARY KEY(user_id, dataset_id),
        FOREIGN KEY (user_id) REFERENCES admin_users(id) ON DELETE CASCADE,
        FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS admin_sessions (
        token VARCHAR(255) PRIMARY KEY,
        admin_id INT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME NOT NULL,
        FOREIGN KEY (admin_id) REFERENCES admin_users(id) ON DELETE CASCADE
    )""",
]


@contextmanager
def connect() -> Iterator[_MysqlWrapper]:
    settings = get_settings()
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=settings.sql_timeout_seconds,
    )
    wrapped = _MysqlWrapper(conn)
    try:
        yield wrapped
        wrapped.commit()
    except Exception:
        wrapped.rollback()
        raise
    finally:
        wrapped.close()


def _engine():
    """SQLAlchemy engine for pandas to_sql / read_sql operations."""
    settings = get_settings()
    url = (
        f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_password}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
        "?charset=utf8mb4"
    )
    return create_engine(url)


def initialize_database() -> None:
    with connect() as conn:
        for stmt in SCHEMA:
            conn.execute(stmt)
        _migrate_schema(conn)
        _seed_initial_admin(conn)
        exists = conn.execute("SELECT id FROM datasets LIMIT 1").fetchone()
        if not exists:
            _seed_demo_dataset(conn)


def _has_column(conn: _MysqlWrapper, table: str, column: str) -> bool:
    return conn.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,)).fetchone() is not None


def _migrate_schema(conn: _MysqlWrapper) -> None:
    """Apply lightweight MySQL migrations for existing databases."""
    if not _has_column(conn, "admin_users", "role"):
        conn.execute("ALTER TABLE admin_users ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'admin'")
    if not _has_column(conn, "audit_logs", "user_id"):
        conn.execute("ALTER TABLE audit_logs ADD COLUMN user_id INT")
    if not _has_column(conn, "audit_logs", "username"):
        conn.execute("ALTER TABLE audit_logs ADD COLUMN username VARCHAR(128)")
    if not _has_column(conn, "sessions", "user_id"):
        conn.execute("ALTER TABLE sessions ADD COLUMN user_id INT")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_dataset_permissions (
            user_id INT NOT NULL,
            dataset_id INT NOT NULL,
            PRIMARY KEY(user_id, dataset_id),
            FOREIGN KEY (user_id) REFERENCES admin_users(id) ON DELETE CASCADE,
            FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
        )"""
    )
    conn.execute("UPDATE admin_users SET role = 'initial_admin' WHERE is_initial_admin = 1")
    conn.execute("UPDATE admin_users SET role = 'admin' WHERE role IS NULL OR role = ''")


def _seed_initial_admin(conn: _MysqlWrapper) -> None:
    exists = conn.execute("SELECT id FROM admin_users WHERE username = %s", ("liuze",)).fetchone()
    if exists:
        return
    from .services.auth import hash_password

    conn.execute(
        "INSERT INTO admin_users(username, password_hash, role, is_initial_admin) VALUES (%s, %s, 'initial_admin', 1)",
        ("liuze", hash_password("18437431")),
    )


def _seed_demo_dataset(conn: _MysqlWrapper) -> None:
    table_name = "data_demo_sales"
    conn.execute(
        f"""CREATE TABLE {table_name} (
            order_date VARCHAR(16) NOT NULL,
            region VARCHAR(16) NOT NULL,
            product_category VARCHAR(32) NOT NULL,
            channel VARCHAR(32) NOT NULL,
            sales_amount DOUBLE NOT NULL,
            order_count INT NOT NULL,
            profit DOUBLE NOT NULL,
            complaint_count INT NOT NULL,
            visits INT NOT NULL,
            conversions INT NOT NULL
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
        f"INSERT INTO {table_name} VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        rows,
    )
    cursor = conn.execute(
        """INSERT INTO datasets(name, description, source_type, table_name, row_count, column_count)
           VALUES (%s, %s, %s, %s, %s, %s)""",
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
           VALUES (%s, %s, %s, %s, %s)""",
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
        "INSERT INTO knowledge_chunks(title, content, category, dataset_id) VALUES (%s, %s, %s, %s)",
        knowledge,
    )
