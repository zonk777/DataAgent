import html
import json
import sqlite3
import uuid
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from ..db import connect
from ..models import AnalysisResponse, ChatRequest, SessionCreate
from ..services.analyzer import analyze
from ..services.reports import build_docx_report, build_pdf_report, load_report_data


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
def list_sessions(limit: int = Query(default=30, ge=1, le=100)) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT s.id, s.title, s.dataset_id, s.created_at, s.updated_at,
                      COUNT(m.id) AS message_count,
                      (SELECT content FROM messages lm WHERE lm.session_id = s.id ORDER BY lm.id DESC LIMIT 1) AS last_message
               FROM sessions s
               LEFT JOIN messages m ON m.session_id = s.id
               GROUP BY s.id
               ORDER BY s.updated_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/sessions", status_code=201)
def create_session(payload: SessionCreate) -> dict:
    session_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions(id, title, dataset_id) VALUES (?, ?, ?)",
            (session_id, payload.title, payload.dataset_id),
        )
    return {"id": session_id, "title": payload.title, "dataset_id": payload.dataset_id}


@router.get("/sessions/{session_id}")
def session_detail(session_id: str) -> dict:
    with connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        rows = conn.execute(
            "SELECT id, role, content, payload, created_at FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    result = dict(session)
    result["messages"] = [_message_dict(row) for row in rows]
    return result


@router.get("/sessions/{session_id}/messages")
def session_messages(session_id: str) -> list[dict]:
    return session_detail(session_id)["messages"]


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


@router.post("/agent/chat", response_model=AnalysisResponse)
async def chat(payload: ChatRequest) -> dict:
    try:
        return await analyze(payload.question, payload.session_id, payload.dataset_id)
    except (ValueError, sqlite3.Error) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/reports/{session_id}.html", response_class=HTMLResponse)
def report(session_id: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT payload FROM messages WHERE session_id = ? AND role = 'assistant' AND payload IS NOT NULL ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="该会话还没有可导出的结果")
    payload = json.loads(row["payload"])
    insights = "".join(f"<li>{html.escape(str(item))}</li>" for item in payload.get("insights", []))
    references = "".join(
        f"<li><strong>{html.escape(str(item.get('title', '')))}</strong>：{html.escape(str(item.get('content', '')))}</li>"
        for item in payload.get("knowledge_refs", [])
    )
    table = ""
    if payload.get("rows"):
        table_head = "".join(f"<th>{html.escape(str(column))}</th>" for column in payload["columns"])
        table_rows = "".join(
            "<tr>" + "".join(
                f"<td>{html.escape(str(item.get(column, '')))}</td>" for column in payload["columns"]
            ) + "</tr>"
            for item in payload["rows"]
        )
        table = f"<h2>数据结果</h2><table><thead><tr>{table_head}</tr></thead><tbody>{table_rows}</tbody></table>"
    sql = f"<h2>执行 SQL</h2><pre>{html.escape(payload['sql'])}</pre>" if payload.get("sql") else ""
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>数据智能报告</title>
    <style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;max-width:980px;margin:48px auto;color:#16324f;line-height:1.7}}
    h1{{color:#087ea4}} .meta{{color:#667085}} table{{width:100%;border-collapse:collapse;margin:24px 0}}
    th,td{{padding:10px 12px;border:1px solid #dbe5ee;text-align:left}} th{{background:#edf8fc}} pre{{background:#f4f7fa;padding:16px}}</style></head>
    <body><h1>企业数据智能报告</h1><p class='meta'>会话编号：{html.escape(session_id)} · 类型：{html.escape(payload.get('intent', ''))}</p>
    <h2>回答与发现</h2><ul>{insights}</ul>{table}{sql}<h2>知识依据</h2><ul>{references}</ul></body></html>"""


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


@router.get("/reports/{session_id}.docx")
def report_docx(session_id: str) -> Response:
    data = _report_or_404(session_id)
    return _attachment(
        build_docx_report(data),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        f"数据智能体分析报告_{session_id}.docx",
    )


@router.get("/reports/{session_id}.pdf")
def report_pdf(session_id: str) -> Response:
    data = _report_or_404(session_id)
    return _attachment(
        build_pdf_report(data),
        "application/pdf",
        f"数据智能体分析报告_{session_id}.pdf",
    )
