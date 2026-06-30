import asyncio

from app.db import initialize_database
from app.services.python_executor import execute_python_analysis


def test_python_auto_repair_recovers_from_runtime_error(monkeypatch) -> None:
    initialize_database()
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    async def fake_generate_python_code(question, table_name, columns, row_count, knowledge):
        return 'result = {"summary": missing_name, "data": []}\nprint(json.dumps(result, ensure_ascii=False, default=str))'

    async def fake_repair_python_code(
        question,
        table_name,
        columns,
        row_count,
        knowledge,
        failed_code,
        error,
        traceback,
    ):
        assert "missing_name" in failed_code
        assert error
        return (
            'result = {"summary": "Python 自动修复成功", "data": [{"rows": int(len(df))}]}\n'
            "print(json.dumps(result, ensure_ascii=False, default=str))"
        )

    monkeypatch.setattr("app.services.python_executor._generate_python_code", fake_generate_python_code)
    monkeypatch.setattr("app.services.python_executor._repair_python_code", fake_repair_python_code)

    payload = asyncio.run(
        execute_python_analysis(
            "分析销售额同比趋势",
            "data_demo_sales",
            [],
            480,
            [],
        )
    )

    assert payload["success"] is True
    assert payload["result"]["summary"] == "Python 自动修复成功"
    assert payload["repair_stats"]["repaired"] is True
    assert payload["repair_stats"]["repair_attempts"] == 1
    assert payload["repair_stats"]["repair_success_rate"] == 1.0
    assert len(payload["repair_stats"]["history"]) == 2
