from fastapi import APIRouter, HTTPException

from ..db import connect
from ..models import KnowledgeCreate
from ..services.vector_store import VectorStoreError, delete_knowledge_vectors, sync_knowledge, vector_status


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("")
def list_knowledge(dataset_id: int | None = None) -> list[dict]:
    with connect() as conn:
        if dataset_id:
            rows = conn.execute(
                "SELECT * FROM knowledge_chunks WHERE dataset_id = ? OR dataset_id IS NULL ORDER BY id DESC",
                (dataset_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM knowledge_chunks ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


@router.post("", status_code=201)
async def create_knowledge(payload: KnowledgeCreate) -> dict:
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO knowledge_chunks(title, content, category, dataset_id) VALUES (?, ?, ?, ?)",
            (payload.title, payload.content, payload.category, payload.dataset_id),
        )
        row = conn.execute("SELECT * FROM knowledge_chunks WHERE id = ?", (cursor.lastrowid,)).fetchone()
    result = dict(row)
    try:
        index_status = await sync_knowledge()
        result["vector_indexed"] = bool(index_status.get("enabled"))
    except VectorStoreError:
        result["vector_indexed"] = False
    return result


@router.delete("/{knowledge_id}", status_code=204)
def delete_knowledge(knowledge_id: int) -> None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM knowledge_chunks WHERE id = ?", (knowledge_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="知识片段不存在")
        conn.execute("DELETE FROM knowledge_chunks WHERE id = ?", (knowledge_id,))
        try:
            delete_knowledge_vectors([knowledge_id])
        except VectorStoreError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/reindex")
async def reindex_knowledge() -> dict:
    try:
        return await sync_knowledge(force=True)
    except VectorStoreError as exc:
        return {"enabled": False, "error": str(exc)}


@router.get("/vector/status")
def knowledge_vector_status() -> dict:
    return vector_status()
