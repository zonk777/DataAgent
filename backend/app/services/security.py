import re


BLOCKED_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|REPLACE|CREATE)\b",
    re.IGNORECASE,
)


class UnsafeQueryError(ValueError):
    pass


def validate_readonly_sql(sql: str, allowed_table: str) -> str:
    normalized = sql.strip().rstrip(";")
    if not normalized.upper().startswith(("SELECT ", "WITH ")):
        raise UnsafeQueryError("只允许执行只读 SELECT 查询")
    if BLOCKED_SQL.search(normalized):
        raise UnsafeQueryError("查询包含被禁止的写入或管理语句")
    if ";" in normalized:
        raise UnsafeQueryError("不允许执行多条 SQL")

    table_refs = re.findall(r"\b(?:FROM|JOIN)\s+([\w]+)", normalized, flags=re.IGNORECASE)
    if not table_refs or any(table != allowed_table for table in table_refs):
        raise UnsafeQueryError("查询访问了未授权的数据表")
    return normalized


def safe_identifier(value: str, prefix: str = "data") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", value).strip("_").lower()
    if not cleaned:
        cleaned = prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned[:48]

