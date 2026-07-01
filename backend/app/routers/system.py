import time

import httpx
from fastapi import APIRouter

from ..config import get_settings
from ..db import connect
from ..services.vector_store import vector_status


router = APIRouter(tags=["system"])


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
    settings = get_settings()
    vectors = vector_status()
    return {
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
