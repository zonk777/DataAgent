from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ..db import connect
from ..models import KnowledgeCreate, KnowledgeUpdate
from ..services.audit import log_action
from ..services.auth import current_admin
from ..services.knowledge_documents import import_knowledge_document
from ..services.permissions import accessible_dataset_ids, ensure_dataset_access, require_data_manager
from ..services.vector_store import VectorStoreError, delete_knowledge_vectors, sync_knowledge, vector_status


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def list_knowledge(dataset_id: int | None = None, actor: dict | None = None) -> list[dict]:
    if dataset_id and actor:
        ensure_dataset_access(actor, dataset_id)
    allowed = accessible_dataset_ids(actor) if actor else None
    params: list[int] = []
    if dataset_id:
        where = "WHERE dataset_id = %s OR dataset_id IS NULL"
        params.append(dataset_id)
    elif allowed is None:
        where = ""
    elif allowed:
        placeholders = ",".join("%s" for _ in allowed)
        where = f"WHERE dataset_id IS NULL OR dataset_id IN ({placeholders})"
        params.extend(allowed)
    else:
        where = "WHERE dataset_id IS NULL"
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM knowledge_chunks {where} ORDER BY id DESC", params).fetchall()
    return [dict(row) for row in rows]


@router.get("")
def list_knowledge_endpoint(request: Request, dataset_id: int | None = None) -> list[dict]:
    return list_knowledge(dataset_id=dataset_id, actor=current_admin(request))


@router.post("", status_code=201)
async def create_knowledge(payload: KnowledgeCreate, request: Request) -> dict:
    actor = require_data_manager(request)
    if payload.dataset_id:
        ensure_dataset_access(actor, payload.dataset_id)
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO knowledge_chunks(title, content, category, dataset_id) VALUES (%s, %s, %s, %s)",
            (payload.title, payload.content, payload.category, payload.dataset_id),
        )
        row = conn.execute("SELECT * FROM knowledge_chunks WHERE id = %s", (cursor.lastrowid,)).fetchone()
    result = dict(row)
    try:
        index_status = await sync_knowledge()
        result["vector_indexed"] = bool(index_status.get("enabled"))
    except VectorStoreError:
        result["vector_indexed"] = False
    log_action("create_knowledge", "knowledge", result["id"], payload.title, actor=actor)
    return result


@router.post("/upload", status_code=201)
async def upload_knowledge_document(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str = Form(default="business_rule"),
    dataset_id: int | None = Form(default=None),
) -> list[dict]:
    actor = require_data_manager(request)
    if dataset_id:
        ensure_dataset_access(actor, dataset_id)
    content = await file.read()
    try:
        chunks = import_knowledge_document(
            filename=file.filename,
            content=content,
            title=title,
            category=category,
            dataset_id=dataset_id,
        )
        await sync_knowledge()
    except (ValueError, VectorStoreError) as exc:
        log_action("upload_knowledge", "knowledge", file.filename, str(exc), status="failed", actor=actor)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action("upload_knowledge", "knowledge", None, f"{file.filename}，切分 {len(chunks)} 个片段", actor=actor)
    return chunks


@router.post("/reindex")
async def reindex_knowledge(request: Request) -> dict:
    actor = require_data_manager(request)
    try:
        result = await sync_knowledge(force=True)
        log_action("reindex_knowledge", "knowledge", None, f"索引状态：{result}", actor=actor)
        return result
    except VectorStoreError as exc:
        return {"enabled": False, "error": str(exc)}


@router.get("/vector/status")
def knowledge_vector_status() -> dict:
    return vector_status()


@router.put("/{knowledge_id}")
async def update_knowledge(knowledge_id: int, payload: KnowledgeUpdate, request: Request) -> dict:
    actor = require_data_manager(request)
    if payload.dataset_id:
        ensure_dataset_access(actor, payload.dataset_id)
    with connect() as conn:
        row = conn.execute("SELECT id FROM knowledge_chunks WHERE id = %s", (knowledge_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="知识片段不存在")
        conn.execute(
            "UPDATE knowledge_chunks SET title = %s, content = %s, category = %s, dataset_id = %s WHERE id = %s",
            (payload.title, payload.content, payload.category, payload.dataset_id, knowledge_id),
        )
        updated = conn.execute("SELECT * FROM knowledge_chunks WHERE id = %s", (knowledge_id,)).fetchone()
    try:
        await sync_knowledge(force=True)
    except VectorStoreError:
        pass
    log_action("update_knowledge", "knowledge", knowledge_id, payload.title, actor=actor)
    return dict(updated)


def delete_knowledge(knowledge_id: int, request: Request | None = None) -> None:
    actor = require_data_manager(request) if request else None
    with connect() as conn:
        row = conn.execute("SELECT id, title, dataset_id FROM knowledge_chunks WHERE id = %s", (knowledge_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="知识片段不存在")
        if actor and row["dataset_id"]:
            ensure_dataset_access(actor, int(row["dataset_id"]))
        conn.execute("DELETE FROM knowledge_chunks WHERE id = %s", (knowledge_id,))
        try:
            delete_knowledge_vectors([knowledge_id])
        except VectorStoreError:
            pass
    log_action("delete_knowledge", "knowledge", knowledge_id, row["title"], actor=actor)


@router.delete("/{knowledge_id}", status_code=204)
def delete_knowledge_endpoint(knowledge_id: int, request: Request) -> None:
    delete_knowledge(knowledge_id, request)
