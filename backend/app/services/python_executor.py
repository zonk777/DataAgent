"""Python/Pandas code generation and sandbox execution.

Generates analysis code via LLM, then executes it in an isolated subprocess
with restricted imports, timeout protection, and safe output capture.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from ..config import get_settings
from ..db import connect

# ---------------------------------------------------------------------------
# Import whitelist – only pandas / numpy are permitted
# ---------------------------------------------------------------------------
_ALLOWED_IMPORTS = {"pandas", "numpy", "math", "json", "datetime", "collections", "itertools", "functools", "statistics", "re", "decimal", "fractions", "random", "operator", "typing"}
_BLOCKED_MODULES = {"os", "sys", "subprocess", "shutil", "socket", "http", "urllib", "requests", "httpx", "openpyxl", "psycopg2", "pymysql", "pickle", "marshal", "ctypes", "importlib", "compileall", "code", "codeop", "pty", "fcntl", "tty", "pdb", "traceback", "inspect"}


def _quote_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def _load_table_frame(table_name: str) -> pd.DataFrame:
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM {_quote_identifier(table_name)}").fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def _validate_imports(code: str) -> None:
    """Raise ValueError if code imports anything outside the whitelist."""
    imports = re.findall(r"^\s*(?:import|from)\s+(\w+)", code, re.MULTILINE)
    for module in imports:
        if module in _BLOCKED_MODULES:
            raise ValueError(f"禁止导入模块：{module}；Python 沙箱仅允许 pandas、numpy 及部分标准库")
        if module not in _ALLOWED_IMPORTS:
            raise ValueError(f"不允许导入模块：{module}；当前仅支持 pandas、numpy 等数据分析库")


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------
async def _generate_python_code(
    question: str,
    table_name: str,
    columns: list[dict[str, Any]],
    row_count: int,
    knowledge: list[dict[str, Any]] | None = None,
) -> str:
    """Use LLM to generate a Pandas analysis script."""
    settings = get_settings()
    if not settings.llm_configured:
        raise RuntimeError("LLM 未配置，无法生成 Python 分析代码")

    schema_lines = [f"表名: {table_name} ({row_count} 行)", "列信息:"]
    for col in columns:
        desc = col.get("description", "")
        schema_lines.append(f"  - {col['name']} ({col['data_type']})" + (f" — {desc}" if desc else ""))

    knowledge_block = ""
    if knowledge:
        knowledge_block = "\n业务指标口径：\n" + "\n".join(
            f"  - {item['title']}：{item['content']}" for item in knowledge[:3]
        )

    prompt = f"""根据用户问题和数据表信息，编写一段可独立运行的 Python/Pandas 分析脚本。

{schema_lines}

{knowledge_block}

用户问题：
{question}

要求：
1. 数据已通过 pd.read_sql 读取到 DataFrame `df` 中（不需要你写 read_sql）
2. 输出为 JSON 对象，包含 `summary`（字符串）、`data`（列表字典，最多 50 行）、`chart_suggestion`（可选）
   chart_suggestion.type 可选：bar、line、pie、scatter、area、radar
3. 使用 print(json.dumps(result, ensure_ascii=False, default=str)) 输出结果
4. 不要使用 print 输出其他内容
5. 只使用 pandas、numpy 及 Python 标准库
6. 处理可能的空值和异常情况

示例输出结构：
{{
    "summary": "经过分析，华东地区销售额同比下降 15.2%，主要受智能设备品类下滑影响。",
    "data": [{{"维度": "华东", "本期": 12345, "上期": 14567, "变化率": "-15.2%"}}],
    "chart_suggestion": {{"type": "bar", "x": "维度", "y": "变化率"}}
}}

请直接输出 Python 代码，不要用 markdown 代码块包裹。"""

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0.1,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个 Python 数据分析专家。只输出可直接运行的代码，不输出任何解释文字。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            code = response.json()["choices"][0]["message"]["content"].strip()
            # Strip accidental markdown fences
            if code.startswith("```"):
                code = re.sub(r"^```(?:python)?\s*\n?", "", code)
                code = re.sub(r"\n?```\s*$", "", code)
            return code
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Python 代码生成失败：{exc}") from exc


async def _repair_python_code(
    question: str,
    table_name: str,
    columns: list[dict[str, Any]],
    row_count: int,
    knowledge: list[dict[str, Any]] | None,
    failed_code: str,
    error: str,
    traceback: str | None,
) -> str:
    """Ask the LLM to repair a failed Pandas script using the structured error."""
    settings = get_settings()
    if not settings.llm_configured:
        raise RuntimeError("LLM 未配置，无法自动修复 Python 代码")

    prompt = {
        "task": "修复上一版 Python/Pandas 分析代码。只输出可运行 Python 代码，不要 Markdown，不要解释。",
        "question": question,
        "schema": {
            "table_name": table_name,
            "row_count": row_count,
            "columns": columns,
            "knowledge": (knowledge or [])[:3],
        },
        "failed_code": failed_code,
        "error": error,
        "traceback": traceback or "",
        "requirements": [
            "数据已经在 DataFrame df 中，不要访问数据库、文件系统或网络。",
            "只能使用 pandas、numpy 和允许的标准库。",
            "最终必须 print(json.dumps(result, ensure_ascii=False, default=str))。",
            "result 必须包含 summary 字符串、data 列表，可选 chart_suggestion。",
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": "你是 Python 数据分析代码修复器。只输出代码。"},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                },
            )
            response.raise_for_status()
            code = response.json()["choices"][0]["message"]["content"].strip()
            if code.startswith("```"):
                code = re.sub(r"^```(?:python)?\s*\n?", "", code)
                code = re.sub(r"\n?```\s*$", "", code)
            return code
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Python 代码自动修复失败：{exc}") from exc


# ---------------------------------------------------------------------------
# Sandbox execution
# ---------------------------------------------------------------------------
async def _run_sandbox(
    code: str,
    table_name: str,
    data_json_path: str,
    timeout: int = 30,
) -> dict[str, Any]:
    """Execute a Pandas script in an isolated subprocess.

    Data is passed as a JSON file to avoid granting the sandbox database access.
    """
    try:
        _validate_imports(code)
    except ValueError as exc:
        return {
            "success": False,
            "error": "代码安全校验失败",
            "traceback": str(exc),
            "result": None,
        }

    wrapper = f"""
import json, warnings
warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np

TABLE_NAME = {json.dumps(table_name)}
DATA_PATH = {json.dumps(data_json_path)}

with open(DATA_PATH, "r", encoding="utf-8") as _f:
    df = pd.read_json(_f, orient="records")

# ---- 用户代码 ----
{code}
""".strip()

    tmp_dir = tempfile.mkdtemp(prefix="dataagent_py_")
    script_path = Path(tmp_dir) / f"analysis_{uuid.uuid4().hex[:8]}.py"
    script_path.write_text(wrapper, encoding="utf-8")

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmp_dir,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            return {
                "success": False,
                "error": "代码执行失败",
                "traceback": stderr[-1500:] if stderr else f"退出码 {proc.returncode}",
                "result": None,
            }

        # Parse JSON output from the last line
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            try:
                parsed = json.loads(line)
                return {"success": True, "error": None, "result": parsed}
            except json.JSONDecodeError:
                continue

        return {"success": True, "error": None, "result": {"raw_output": stdout, "data": []}}
    except asyncio.TimeoutError:
        return {"success": False, "error": f"代码执行超时（{timeout} 秒）", "traceback": "", "result": None}
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _result_structure_error(result: dict[str, Any]) -> str | None:
    if not result.get("success"):
        return None
    payload = result.get("result")
    if not isinstance(payload, dict):
        return "Python 输出必须是 JSON 对象"
    if not isinstance(payload.get("summary"), str) or not payload.get("summary", "").strip():
        return "Python 输出缺少 summary 字符串"
    if "data" not in payload:
        payload["data"] = []
    if not isinstance(payload.get("data"), list):
        return "Python 输出 data 必须是列表"
    return None


def _repair_stats(attempts: list[dict[str, Any]], success: bool) -> dict[str, Any]:
    repair_attempts = max(0, len(attempts) - 1)
    return {
        "attempts": len(attempts),
        "repair_attempts": repair_attempts,
        "repaired": success and repair_attempts > 0,
        "success": success,
        "repair_success_rate": (1.0 if success else 0.0) if repair_attempts else None,
        "history": attempts,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def execute_python_analysis(
    question: str,
    table_name: str,
    columns: list[dict[str, Any]],
    row_count: int,
    knowledge: list[dict[str, Any]] | None = None,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    """Generate and execute a Python/Pandas analysis.

    Returns:
        {
            "success": bool,
            "error": str | None,
            "traceback": str | None,
            "result": dict | None,   # parsed JSON output from the script
            "code": str,             # the generated code (for audit)
        }
    """
    settings = get_settings()

    if not settings.llm_configured:
        return {
            "success": False,
            "error": "LLM 未配置，无法进行 Python 数据分析",
            "traceback": None,
            "result": None,
            "code": "",
            "repair_stats": _repair_stats([], False),
        }

    try:
        code = await _generate_python_code(question, table_name, columns, row_count, knowledge)
    except RuntimeError as exc:
        return {
            "success": False,
            "error": str(exc),
            "traceback": None,
            "result": None,
            "code": "",
            "repair_stats": _repair_stats([], False),
        }

    # Load data through the application's DB adapter, then pass JSON to the sandbox.
    df = _load_table_frame(table_name)
    tmp_data_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8", prefix="dataagent_data_"
    )
    df.to_json(tmp_data_file, orient="records", force_ascii=False)
    tmp_data_file.close()

    attempts: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "success": False,
        "error": "Python 分析未执行",
        "traceback": None,
        "result": None,
    }
    try:
        for attempt_no in range(1, 4):
            result = await _run_sandbox(code, table_name, tmp_data_file.name, timeout)
            structure_error = _result_structure_error(result)
            if structure_error:
                result = {
                    "success": False,
                    "error": structure_error,
                    "traceback": json.dumps(result.get("result"), ensure_ascii=False, default=str)[:1500],
                    "result": None,
                }
            attempts.append(
                {
                    "attempt": attempt_no,
                    "success": bool(result.get("success")),
                    "error": result.get("error"),
                    "traceback": result.get("traceback"),
                }
            )
            if result.get("success"):
                break
            if attempt_no >= 3:
                break
            try:
                code = await _repair_python_code(
                    question,
                    table_name,
                    columns,
                    row_count,
                    knowledge,
                    code,
                    str(result.get("error") or ""),
                    result.get("traceback"),
                )
            except RuntimeError as exc:
                result = {
                    "success": False,
                    "error": str(exc),
                    "traceback": result.get("traceback"),
                    "result": None,
                }
                attempts.append(
                    {
                        "attempt": attempt_no + 1,
                        "success": False,
                        "error": str(exc),
                        "traceback": result.get("traceback"),
                    }
                )
                break
    finally:
        try:
            Path(tmp_data_file.name).unlink(missing_ok=True)
        except Exception:
            pass

    result["code"] = code
    result["repair_stats"] = _repair_stats(attempts, bool(result.get("success")))
    return result
