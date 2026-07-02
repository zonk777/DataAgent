from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

import httpx
from fastapi import HTTPException


MAX_DETAIL_CHARS = 900


def _clean(text: Any, *, limit: int = MAX_DETAIL_CHARS) -> str:
    value = str(text or "").strip()
    value = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", value)
    value = re.sub(r"sk-[A-Za-z0-9._\-]+", "sk-***", value)
    value = re.sub(r"api[_-]?key[=:]\s*[^,\s;]+", "api_key=***", value, flags=re.I)
    value = re.sub(r"\s+", " ", value)
    if len(value) > limit:
        value = value[:limit].rstrip() + "..."
    return value


def _response_text(response: httpx.Response | None) -> str:
    if response is None:
        return ""
    try:
        data = response.json()
        if isinstance(data, dict):
            detail = data.get("error") or data.get("detail") or data.get("message")
            if isinstance(detail, dict):
                return json.dumps(detail, ensure_ascii=False)
            return _clean(detail or data)
        return _clean(data)
    except Exception:
        return _clean(response.text)


def _prefix(operation: str, message: str) -> str:
    message = _clean(message)
    if message.startswith(f"{operation}失败"):
        return message
    return f"{operation}失败：{message}"


def format_analysis_error(
    exc: Exception,
    *,
    operation: str = "智能分析",
    filename: str | None = None,
    dataset_id: int | None = None,
) -> str:
    """Convert common backend/LLM/database/file failures into user-facing Chinese details.

    The message is intentionally actionable and safe: it avoids leaking API keys while preserving
    status codes, provider responses, dataset/file context, and suggested fixes.
    """

    if isinstance(exc, HTTPException):
        return _clean(exc.detail or f"HTTP {exc.status_code}")

    original = _clean(str(exc) or type(exc).__name__)
    lower = original.lower()
    context: list[str] = []
    if filename:
        context.append(f"文件：{filename}")
    if dataset_id:
        context.append(f"数据源 ID：{dataset_id}")
    context_text = f"\n上下文：{'；'.join(context)}" if context else ""

    # LLM / embedding HTTP provider errors.
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else 0
        provider_text = _response_text(exc.response)
        if status in {401, 403}:
            return (
                f"{operation}失败：模型服务认证失败（HTTP {status}）。\n"
                "可能原因：API Key 填错、Key 已过期、账号无该模型权限，或自定义 API 与系统 API 切换后未保存成功。\n"
                f"服务返回：{provider_text or original}{context_text}\n"
                "建议：到“系统配置 → API 设置”重新保存 Key；如果使用自己的 API，请确认 Base URL、模型名和余额/权限。"
            )
        if status == 404:
            return (
                f"{operation}失败：模型接口或模型名称不存在（HTTP 404）。\n"
                f"服务返回：{provider_text or original}{context_text}\n"
                "建议：检查 LLM_BASE_URL 是否带错路径，模型名是否拼写正确，DeepSeek 常见 Base URL 为 https://api.deepseek.com。"
            )
        if status == 429:
            return (
                f"{operation}失败：模型服务限流或额度不足（HTTP 429）。\n"
                f"服务返回：{provider_text or original}{context_text}\n"
                "建议：稍后重试，或检查账号余额、并发限制和调用频率。"
            )
        if status >= 500:
            return (
                f"{operation}失败：模型服务端异常（HTTP {status}）。\n"
                f"服务返回：{provider_text or original}{context_text}\n"
                "建议：稍后重试；若连续失败，请切换模型或检查服务商状态。"
            )
        return (
            f"{operation}失败：模型服务请求被拒绝（HTTP {status}）。\n"
            f"服务返回：{provider_text or original}{context_text}\n"
            "建议：检查 API 配置、模型名、请求内容长度和服务商接口格式。"
        )

    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return (
            f"{operation}失败：模型或数据服务响应超时。{context_text}\n"
            "可能原因：网络代理不稳定、模型服务响应慢、上传文件过大，或数据库查询耗时过长。\n"
            "建议：稍后重试；缩小问题范围或文件大小；检查代理、防火墙、Qdrant/MySQL/后端是否正常运行。"
        )

    if isinstance(exc, httpx.RequestError):
        return (
            f"{operation}失败：无法连接到模型服务。\n"
            f"网络错误：{original}{context_text}\n"
            "建议：检查 Base URL、代理设置、防火墙、网络连接；如果是本机服务，请确认后端能访问该地址。"
        )

    # File/document parsing failures.
    if any(key in lower for key in ("文档解析失败", "仅支持", "pdf", "docx", "markdown", "txt", "pypdf", "python-docx", "文件内容为空")):
        return (
            _prefix(operation, original)
            + context_text
            + "\n可能原因：文件为空、格式不受支持、PDF 是扫描图片没有可提取文字，或缺少解析依赖。"
            + "\n建议：换成可复制文字的 PDF/Word/Markdown/TXT；扫描件请先 OCR；确认后端依赖已安装。"
        )

    # Dataset / permission / schema / SQL failures.
    if "无权访问" in original or "403" in lower:
        return (
            f"{operation}失败：当前账号没有该数据源的使用权限。{context_text}\n"
            "建议：请初始管理员在“账户管理”里给当前账号分配该数据源权限，或切换到有权限的数据源。"
        )

    if any(key in lower for key in ("no such table", "unknown table", "table", "数据集不存在")):
        return (
            _prefix(operation, original)
            + context_text
            + "\n可能原因：选择的数据源已删除、数据表未成功创建，或数据库连接指向了错误库。"
            + "\n建议：重新选择数据源；到“数据源”页面查看是否能预览；必要时重新上传或重新导入。"
        )

    if any(key in lower for key in ("no such column", "unknown column", "字段不存在", "field", "column")):
        return (
            _prefix(operation, original)
            + context_text
            + "\n可能原因：问题中提到的字段/指标在当前数据源不存在，或业务知识库里的字段口径与数据表字段不一致。"
            + "\n建议：查看数据源字段说明；换成当前表存在的字段名；补充业务知识库中的指标口径。"
        )

    if any(key in lower for key in ("sql", "readonly", "select", "syntax", "unsafequery")):
        return (
            _prefix(operation, original)
            + context_text
            + "\n可能原因：自动生成 SQL 失败、字段匹配错误，或安全校验拦截了非只读查询。"
            + "\n建议：把问题描述得更具体，例如说明指标、时间范围、分组维度；也可以先在数据源页确认字段。"
        )

    if isinstance(exc, sqlite3.Error) or any(key in lower for key in ("mysql", "sqlite", "database", "pymysql", "connection refused", "access denied")):
        return (
            _prefix(operation, original)
            + context_text
            + "\n可能原因：数据库服务未启动、账号密码错误、网络不可达、SQL 执行失败，或 MySQL 连接被防火墙拦截。"
            + "\n建议：确认 MySQL/Qdrant/后端服务已启动；检查 backend/.env 数据库配置；让同事访问时确认主机 IP 和端口开放。"
        )

    # Python sandbox failures.
    if any(key in lower for key in ("python", "pandas", "代码执行", "沙箱", "subprocess", "timeout")):
        return (
            _prefix(operation, original)
            + context_text
            + "\n可能原因：深度分析代码生成失败、执行超时、结果格式不符合要求，或代码安全校验未通过。"
            + "\n建议：缩小分析范围；避免一次要求过多复杂计算；如果反复失败，可先用普通查询再逐步追问。"
        )

    # Configuration failures.
    if any(key in lower for key in ("llm 未配置", "embedding 服务尚未配置", "api key", "base_url", "model")):
        return (
            _prefix(operation, original)
            + context_text
            + "\n可能原因：模型 API、Embedding API、Base URL 或模型名未配置/配置错误。"
            + "\n建议：到“系统配置 → API 设置”选择系统 API，或填写自己的 API Key、Base URL 和模型名后保存。"
        )

    if not original or original in {"None", "unknown", "未知错误"}:
        original = f"{type(exc).__name__}"

    return (
        _prefix(operation, original)
        + context_text
        + "\n建议：刷新页面后重试；如果仍失败，请检查后端控制台日志、模型 API 配置、数据库服务和当前数据源权限。"
    )
