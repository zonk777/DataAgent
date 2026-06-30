from fastapi import APIRouter

from ..config import get_settings
from ..db import connect
from ..services.vector_store import vector_status


router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": get_settings().app_name}


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
