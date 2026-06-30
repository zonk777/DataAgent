import pytest

from app.services.security import UnsafeQueryError, validate_readonly_sql


def test_allows_readonly_query() -> None:
    sql = "SELECT region, SUM(sales_amount) FROM data_sales GROUP BY region"
    assert validate_readonly_sql(sql, "data_sales") == sql


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM data_sales",
        "SELECT * FROM other_table",
        "SELECT * FROM data_sales; DROP TABLE data_sales",
    ],
)
def test_blocks_unsafe_queries(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql(sql, "data_sales")

