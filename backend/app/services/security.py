import re


BLOCKED_COMMENT = re.compile(r"(--|#|/\*|\*/)")
BLOCKED_SQL = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|REPLACE|CREATE|"
    r"PRAGMA|ATTACH|DETACH|VACUUM|ANALYZE|REINDEX|"
    r"GRANT|REVOKE|MERGE|CALL|EXEC|EXECUTE|LOAD|COPY|LOCK|UNLOCK"
    r")\b",
    re.IGNORECASE,
)
STRING_LITERAL = re.compile(r"'(?:''|[^'])*'")
IDENTIFIER = r"(?:`[^`]+`|\"[^\"]+\"|\[[^\]]+\]|[A-Za-z_][\w$]*)"
TABLE_REF = re.compile(
    rf"\b(?:FROM|JOIN)\s+({IDENTIFIER}(?:\s*\.\s*{IDENTIFIER})?)",
    re.IGNORECASE,
)
CTE_REF = re.compile(rf"(?:\bWITH|,)\s+({IDENTIFIER})\s+AS\s*\(", re.IGNORECASE)


class UnsafeQueryError(ValueError):
    pass


def _strip_string_literals(sql: str) -> str:
    return STRING_LITERAL.sub("''", sql)


def _normalize_identifier(value: str) -> str:
    cleaned = value.strip()
    if (
        (cleaned.startswith("`") and cleaned.endswith("`"))
        or (cleaned.startswith('"') and cleaned.endswith('"'))
        or (cleaned.startswith("[") and cleaned.endswith("]"))
    ):
        cleaned = cleaned[1:-1]
    return cleaned.lower()


def _normalize_table_ref(value: str) -> str:
    parts = [part.strip() for part in re.split(r"\s*\.\s*", value.strip())]
    return ".".join(_normalize_identifier(part) for part in parts if part)


def validate_readonly_sql(sql: str, allowed_table: str) -> str:
    normalized = sql.strip()
    if normalized.endswith(";"):
        normalized = normalized[:-1].strip()
    scan_sql = _strip_string_literals(normalized)
    if not normalized:
        raise UnsafeQueryError("SQL 不能为空")
    if ";" in scan_sql:
        raise UnsafeQueryError("不允许执行多条 SQL")
    if BLOCKED_COMMENT.search(scan_sql):
        raise UnsafeQueryError("不允许在查询中使用 SQL 注释")
    if not scan_sql.upper().startswith(("SELECT ", "WITH ")):
        raise UnsafeQueryError("只允许执行只读 SELECT 查询")
    if BLOCKED_SQL.search(scan_sql):
        raise UnsafeQueryError("查询包含被禁止的写入或管理语句")

    allowed = allowed_table.lower()
    cte_refs = {_normalize_identifier(item) for item in CTE_REF.findall(scan_sql)}
    table_refs = [_normalize_table_ref(item) for item in TABLE_REF.findall(scan_sql)]
    real_table_refs = [table for table in table_refs if table not in cte_refs]
    if not real_table_refs or any(table != allowed for table in real_table_refs):
        raise UnsafeQueryError("查询访问了未授权的数据表")
    return normalized


def safe_identifier(value: str, prefix: str = "data") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", value).strip("_").lower()
    if not cleaned:
        cleaned = prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned[:48]

