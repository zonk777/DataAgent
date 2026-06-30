import pytest

from app.services.security import UnsafeQueryError, validate_readonly_sql


def test_allows_readonly_query() -> None:
    sql = "SELECT region, SUM(sales_amount) FROM data_sales GROUP BY region"
    assert validate_readonly_sql(sql, "data_sales") == sql


def test_allows_quoted_table_and_cte_query() -> None:
    sql = "WITH totals AS (SELECT region FROM `data_sales`) SELECT region FROM totals"
    assert validate_readonly_sql(sql, "data_sales") == sql


def test_does_not_treat_string_literals_as_sql_keywords() -> None:
    sql = "SELECT 'DROP' AS label FROM data_sales"
    assert validate_readonly_sql(sql, "data_sales") == sql


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO data_sales(region) VALUES ('华东')",
        "UPDATE data_sales SET region = '华东'",
        "DELETE FROM data_sales",
        "DROP TABLE data_sales",
        "ALTER TABLE data_sales ADD COLUMN demo INT",
        "TRUNCATE TABLE data_sales",
        "REPLACE INTO data_sales(region) VALUES ('华东')",
        "CREATE TABLE data_copy AS SELECT * FROM data_sales",
        "PRAGMA table_info(data_sales)",
        "ATTACH DATABASE 'x.db' AS x",
        "DETACH DATABASE x",
        "SELECT * FROM other_table",
        "SELECT * FROM other_schema.data_sales",
        "SELECT * FROM data_sales; DROP TABLE data_sales",
        "SELECT * FROM data_sales -- hidden",
        "SELECT * FROM data_sales /* hidden */",
        "WITH totals AS (SELECT * FROM other_table) SELECT * FROM totals",
    ],
)
def test_blocks_unsafe_queries(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql(sql, "data_sales")
