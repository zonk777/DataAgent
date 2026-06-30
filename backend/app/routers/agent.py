import json
import uuid

import pymysql
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from ..db import connect
from ..models import AnalysisResponse, ChatRequest, SessionCreate
from ..services.analyzer import analyze
from ..services.audit import log_action
from ..services.auth import current_admin
from ..services.permissions import ensure_dataset_access, first_accessible_dataset_id
from ..services.reports import (
    build_docx_report,
    build_html_report,
    build_markdown_report,
    build_pdf_report,
    load_report_data,
)


router = APIRouter(tags=["agent"])


def _message_dict(row) -> dict:
    item = dict(row)
    if item.get("payload"):
        try:
            item["payload"] = json.loads(item["payload"])
        except json.JSONDecodeError:
            item["payload"] = None
    return item


@router.get("/sessions")
def list_sessions(request: Request, limit: int = Query(default=30, ge=1, le=100)) -> list[dict]:
    current_admin(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT s.id, s.title, s.dataset_id, s.created_at, s.updated_at,
                      COUNT(m.id) AS message_count,
                      (SELECT content FROM messages lm WHERE lm.session_id = s.id ORDER BY lm.id DESC LIMIT 1) AS last_message
               FROM sessions s
               LEFT JOIN messages m ON m.session_id = s.id
               GROUP BY s.id
               ORDER BY s.updated_at DESC
               LIMIT %s""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/sessions", status_code=201)
def create_session(payload: SessionCreate, request: Request) -> dict:
    actor = current_admin(request)
    if payload.dataset_id:
        ensure_dataset_access(actor, payload.dataset_id)
    session_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions(id, title, dataset_id, user_id) VALUES (%s, %s, %s, %s)",
            (session_id, payload.title, payload.dataset_id, actor["id"]),
        )
    return {"id": session_id, "title": payload.title, "dataset_id": payload.dataset_id}


@router.get("/sessions/{session_id}")
def session_detail(session_id: str, request: Request) -> dict:
    current_admin(request)
    with connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id = %s", (session_id,)).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        rows = conn.execute(
            "SELECT id, role, content, payload, created_at FROM messages WHERE session_id = %s ORDER BY id",
            (session_id,),
        ).fetchall()
    result = dict(session)
    result["messages"] = [_message_dict(row) for row in rows]
    return result


@router.get("/sessions/{session_id}/messages")
def session_messages(session_id: str, request: Request) -> list[dict]:
    return session_detail(session_id, request)["messages"]


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, request: Request) -> None:
    actor = current_admin(request)
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
    log_action("delete_session", "session", session_id, "删除历史对话", actor=actor)


@router.post("/agent/chat", response_model=AnalysisResponse)
async def chat(payload: ChatRequest, request: Request) -> dict:
    actor = current_admin(request)
    dataset_id = payload.dataset_id or first_accessible_dataset_id(actor)
    if dataset_id:
        ensure_dataset_access(actor, dataset_id)
    try:
        result = await analyze(payload.question, payload.session_id, dataset_id)
        log_action("analysis_request", "session", result.get("session_id"), payload.question, actor=actor)
        return result
    except (ValueError, pymysql.Error) as exc:
        log_action("analysis_request", "session", payload.session_id, str(exc), status="failed", actor=actor)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _report_or_404(session_id: str):
    try:
        return load_report_data(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _attachment(content: bytes, media_type: str, filename: str) -> Response:
    encoded = quote(filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@router.get("/reports/{session_id}.html", response_class=HTMLResponse)
def report_html(session_id: str, request: Request) -> str:
    actor = current_admin(request)
    data = _report_or_404(session_id)
    log_action("export_report", "session", session_id, "HTML", actor=actor)
    return build_html_report(data)


@router.get("/reports/{session_id}.docx")
def report_docx(session_id: str, request: Request) -> Response:
    actor = current_admin(request)
    data = _report_or_404(session_id)
    log_action("export_report", "session", session_id, "Word", actor=actor)
    return _attachment(
        build_docx_report(data),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        f"数据智能体分析报告_{session_id}.docx",
    )


@router.get("/reports/{session_id}.pdf")
def report_pdf(session_id: str, request: Request) -> Response:
    actor = current_admin(request)
    data = _report_or_404(session_id)
    log_action("export_report", "session", session_id, "PDF", actor=actor)
    return _attachment(
        build_pdf_report(data),
        "application/pdf",
        f"数据智能体分析报告_{session_id}.pdf",
    )


@router.get("/reports/{session_id}.md")
def report_markdown(session_id: str, request: Request) -> Response:
    actor = current_admin(request)
    data = _report_or_404(session_id)
    log_action("export_report", "session", session_id, "Markdown", actor=actor)
    return _attachment(
        build_markdown_report(data),
        "text/markdown; charset=utf-8",
        f"数据智能体分析报告_{session_id}.md",
    )
