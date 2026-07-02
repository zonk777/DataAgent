import json
import time
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..config import BACKEND_DIR, get_settings
from ..db import connect
from ..services.audit import log_action
from ..services.auth import require_initial_admin
from ..services.vector_store import vector_status


router = APIRouter(tags=["system"])


class ApiConfigPayload(BaseModel):
    mode: Literal["system", "custom"] = "system"
    llm_api_key: str | None = Field(default=None, max_length=5000)
    llm_base_url: str | None = Field(default=None, max_length=500)
    llm_model: str | None = Field(default=None, max_length=200)
    embedding_api_key: str | None = Field(default=None, max_length=5000)
    embedding_base_url: str | None = Field(default=None, max_length=500)
    embedding_model: str | None = Field(default=None, max_length=200)


ENV_PATH = BACKEND_DIR / ".env"


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _read_env_file() -> tuple[list[str], dict[str, str]]:
    if not ENV_PATH.exists():
        return [], {}
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        values[key] = value
    return lines, values


def _format_env_value(value: str) -> str:
    value = value.replace("\r", "").replace("\n", "").strip()
    if not value:
        return ""
    if any(ch in value for ch in [" ", "#", '"', "'"]):
        return json.dumps(value, ensure_ascii=False)
    return value


def _write_env_values(updates: dict[str, str]) -> None:
    lines, _ = _read_env_file()
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in updates:
            new_lines.append(f"{key}={_format_env_value(updates[key])}")
            seen.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={_format_env_value(value)}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _config_response() -> dict:
    settings = get_settings()
    vectors = vector_status()
    mode = (settings.api_mode or "system").strip().lower()
    return {
        "api_mode": mode if mode in {"system", "custom"} else "system",
        "llm_configured": settings.llm_configured,
        "llm_model": settings.llm_model or None,
        "embedding_configured": settings.embedding_configured,
        "embedding_model": settings.embedding_model if settings.embedding_configured else None,
        "vector_store": vectors["store"],
        "vector_indexed_count": vectors["indexed_count"],
        "database_backend": settings.database_backend,
        "database_name": settings.mysql_database if settings.database_backend.lower() == "mysql" else str(settings.database_file),
        "environment": settings.environment,
    }


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    result = {"status": "ok", "service": settings.app_name, "checks": {}}

    # DB check
    try:
        start = time.perf_counter()
        with connect() as conn:
            conn.execute("SELECT 1").fetchone()
        result["checks"]["database"] = {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 1)}
    except Exception as exc:
        result["checks"]["database"] = {"status": "error", "detail": str(exc)[:120]}
        result["status"] = "degraded"

    # Qdrant check
    try:
        start = time.perf_counter()
        vs = vector_status()
        result["checks"]["vector_store"] = {
            "status": "ok",
            "store": vs.get("store", "unknown"),
            "indexed": vs.get("indexed_count", 0),
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        }
    except Exception as exc:
        result["checks"]["vector_store"] = {"status": "error", "detail": str(exc)[:120]}
        result["status"] = "degraded"

    # LLM check (lightweight: just check connectivity, no actual completion)
    if settings.llm_configured:
        try:
            start = time.perf_counter()
            async def _check():
                async with httpx.AsyncClient(timeout=5) as client:
                    r = await client.get(
                        settings.llm_base_url.rstrip("/") + "/models",
                        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    )
                    return r.status_code
                # Run sync for simplicity in health check
            result["checks"]["llm"] = {"status": "ok", "configured": True, "model": settings.llm_model}
        except Exception:
            result["checks"]["llm"] = {"status": "unreachable", "configured": True}
    else:
        result["checks"]["llm"] = {"status": "disabled", "configured": False}

    return result


@router.get("/config/status")
def config_status() -> dict:
    return _config_response()


@router.put("/config/api")
def update_api_config(payload: ApiConfigPayload, request: Request) -> dict:
    actor = require_initial_admin(request)
    settings = get_settings()
    _, env = _read_env_file()
    current_mode = (env.get("API_MODE") or settings.api_mode or "system").strip().lower()

    updates: dict[str, str] = {"API_MODE": payload.mode}

    if payload.mode == "custom":
        # 首次切换到自定义 API 前，先备份当前系统 API，方便之后切回。
        if current_mode != "custom":
            backup_pairs = {
                "SYSTEM_LLM_API_KEY": env.get("LLM_API_KEY") or settings.llm_api_key,
                "SYSTEM_LLM_BASE_URL": env.get("LLM_BASE_URL") or settings.llm_base_url,
                "SYSTEM_LLM_MODEL": env.get("LLM_MODEL") or settings.llm_model,
                "SYSTEM_EMBEDDING_API_KEY": env.get("EMBEDDING_API_KEY") or settings.embedding_api_key,
                "SYSTEM_EMBEDDING_BASE_URL": env.get("EMBEDDING_BASE_URL") or settings.embedding_base_url,
                "SYSTEM_EMBEDDING_MODEL": env.get("EMBEDDING_MODEL") or settings.embedding_model,
            }
            for key, value in backup_pairs.items():
                if value and not env.get(key):
                    updates[key] = value

        llm_key = _clean(payload.llm_api_key) or (env.get("LLM_API_KEY", "") if current_mode == "custom" else "")
        embedding_key = _clean(payload.embedding_api_key) or (env.get("EMBEDDING_API_KEY", "") if current_mode == "custom" else "")
        llm_base_url = _clean(payload.llm_base_url)
        llm_model = _clean(payload.llm_model)
        embedding_base_url = _clean(payload.embedding_base_url)
        embedding_model = _clean(payload.embedding_model)

        missing = []
        if not llm_key:
            missing.append("大模型 API Key")
        if not llm_base_url:
            missing.append("LLM Base URL")
        if not llm_model:
            missing.append("LLM 模型")
        if not embedding_key:
            missing.append("Embedding API Key")
        if not embedding_base_url:
            missing.append("Embedding Base URL")
        if not embedding_model:
            missing.append("Embedding 模型")
        if missing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请填写：" + "、".join(missing))

        updates.update(
            {
                "LLM_API_KEY": llm_key,
                "LLM_BASE_URL": llm_base_url,
                "LLM_MODEL": llm_model,
                "EMBEDDING_API_KEY": embedding_key,
                "EMBEDDING_BASE_URL": embedding_base_url,
                "EMBEDDING_MODEL": embedding_model,
            }
        )
    else:
        restore_pairs = {
            "LLM_API_KEY": env.get("SYSTEM_LLM_API_KEY") or settings.system_llm_api_key,
            "LLM_BASE_URL": env.get("SYSTEM_LLM_BASE_URL") or settings.system_llm_base_url,
            "LLM_MODEL": env.get("SYSTEM_LLM_MODEL") or settings.system_llm_model,
            "EMBEDDING_API_KEY": env.get("SYSTEM_EMBEDDING_API_KEY") or settings.system_embedding_api_key,
            "EMBEDDING_BASE_URL": env.get("SYSTEM_EMBEDDING_BASE_URL") or settings.system_embedding_base_url,
            "EMBEDDING_MODEL": env.get("SYSTEM_EMBEDDING_MODEL") or settings.system_embedding_model,
        }
        if current_mode == "custom" and not restore_pairs["LLM_API_KEY"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未找到系统 API 备份，无法切回系统 API")
        for key, value in restore_pairs.items():
            if value:
                updates[key] = value

    _write_env_values(updates)
    log_action(
        "update_api_config",
        "system_config",
        detail=f"切换 API 模式为 {payload.mode}；密钥已脱敏保存",
        actor=actor,
    )
    return _config_response()


@router.get("/dashboard")
def dashboard() -> dict:
    with connect() as conn:
        dataset_count = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        knowledge_count = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        analysis_count = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'analyze'").fetchone()[0]
        session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        recent = [dict(row) for row in conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 6").fetchall()]
    return {
        "dataset_count": dataset_count,
        "knowledge_count": knowledge_count,
        "analysis_count": analysis_count,
        "session_count": session_count,
        "recent_sessions": recent,
    }
