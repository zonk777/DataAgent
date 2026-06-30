from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, status

from ..db import connect


SESSION_COOKIE = "dataagent_session"
SESSION_DAYS = 7
PBKDF2_ITERATIONS = 200_000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${iterations}${salt}${digest}".format(
        iterations=PBKDF2_ITERATIONS,
        salt=base64.b64encode(salt).decode("ascii"),
        digest=base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _public_admin(row: Any) -> dict:
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "is_initial_admin": bool(row["is_initial_admin"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }


def authenticate(username: str, password: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, is_initial_admin, created_by, created_at FROM admin_users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return _public_admin(row)


def create_session(admin_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    expires_at = _utc_now() + timedelta(days=SESSION_DAYS)
    with connect() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (_iso(_utc_now()),))
        conn.execute(
            "INSERT INTO admin_sessions(token, admin_id, expires_at) VALUES (?, ?, ?)",
            (token, admin_id, _iso(expires_at)),
        )
    return token, _iso(expires_at)


def destroy_session(token: str | None) -> None:
    if not token:
        return
    with connect() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))


def admin_from_session(token: str | None) -> dict | None:
    if not token:
        return None
    with connect() as conn:
        row = conn.execute(
            """SELECT u.id, u.username, u.is_initial_admin, u.created_by, u.created_at
               FROM admin_sessions s
               JOIN admin_users u ON u.id = s.admin_id
               WHERE s.token = ? AND s.expires_at > ?""",
            (token, _iso(_utc_now())),
        ).fetchone()
    return _public_admin(row) if row else None


def current_admin(request: Request) -> dict:
    admin = getattr(request.state, "admin", None) or admin_from_session(request.cookies.get(SESSION_COOKIE))
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return admin


def require_initial_admin(request: Request) -> dict:
    admin = current_admin(request)
    if not admin.get("is_initial_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有初始管理员可以新增管理员")
    return admin


def list_admins() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, username, is_initial_admin, created_by, created_at FROM admin_users ORDER BY id"
        ).fetchall()
    return [_public_admin(row) for row in rows]


def create_admin(username: str, password: str, creator_id: int) -> dict:
    if not username.strip():
        raise HTTPException(status_code=400, detail="账号不能为空")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少需要 6 位")
    try:
        with connect() as conn:
            cursor = conn.execute(
                "INSERT INTO admin_users(username, password_hash, is_initial_admin, created_by) VALUES (?, ?, 0, ?)",
                (username.strip(), hash_password(password), creator_id),
            )
            row = conn.execute(
                "SELECT id, username, is_initial_admin, created_by, created_at FROM admin_users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="该管理员账号已存在") from exc
        raise
    return _public_admin(row)
