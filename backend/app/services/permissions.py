from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status

from ..db import connect
from .auth import current_admin


DATA_MANAGER_ROLES = {"initial_admin", "admin", "data_analyst"}


def normalize_role(role: str | None) -> str:
    role = (role or "admin").strip()
    return role if role in {"initial_admin", "admin", "data_analyst", "business_user"} else "business_user"


def get_dataset_permissions(user_id: int) -> list[int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT dataset_id FROM user_dataset_permissions WHERE user_id = %s ORDER BY dataset_id",
            (user_id,),
        ).fetchall()
    return [int(row["dataset_id"]) for row in rows]


def set_dataset_permissions(user_id: int, dataset_ids: list[int] | None) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM user_dataset_permissions WHERE user_id = %s", (user_id,))
        for dataset_id in dataset_ids or []:
            conn.execute(
                "INSERT IGNORE INTO user_dataset_permissions(user_id, dataset_id) VALUES (%s, %s)",
                (user_id, int(dataset_id)),
            )


def has_all_dataset_access(actor: dict[str, Any]) -> bool:
    if actor.get("is_initial_admin"):
        return True
    permissions = actor.get("dataset_permissions")
    return actor.get("role") in {"admin", "data_analyst"} and not permissions


def accessible_dataset_ids(actor: dict[str, Any]) -> list[int] | None:
    if has_all_dataset_access(actor):
        return None
    return [int(item) for item in actor.get("dataset_permissions") or []]


def ensure_dataset_access(actor: dict[str, Any], dataset_id: int | None) -> None:
    if dataset_id is None or has_all_dataset_access(actor):
        return
    if int(dataset_id) not in set(accessible_dataset_ids(actor) or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该数据源")


def first_accessible_dataset_id(actor: dict[str, Any]) -> int | None:
    allowed = accessible_dataset_ids(actor)
    with connect() as conn:
        if allowed is None:
            row = conn.execute("SELECT id FROM datasets ORDER BY id LIMIT 1").fetchone()
        elif allowed:
            placeholders = ",".join("%s" for _ in allowed)
            row = conn.execute(
                f"SELECT id FROM datasets WHERE id IN ({placeholders}) ORDER BY id LIMIT 1",
                allowed,
            ).fetchone()
        else:
            row = None
    return int(row["id"]) if row else None


def require_data_manager(request: Request) -> dict[str, Any]:
    actor = current_admin(request)
    if actor.get("role") not in DATA_MANAGER_ROLES and not actor.get("is_initial_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无数据源/知识库管理权限")
    return actor
