from fastapi import APIRouter, Request, Response, status

from ..config import get_settings
from ..models import AdminCreate, AdminUpdate, LoginRequest
from ..services.audit import log_action
from ..services.auth import (
    SESSION_COOKIE,
    authenticate,
    create_admin,
    create_session,
    current_admin,
    delete_admin,
    destroy_session,
    list_admins,
    require_initial_admin,
    update_admin,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, response: Response) -> dict:
    admin = authenticate(payload.username, payload.password)
    if not admin:
        log_action("login", "auth", payload.username, "登录失败", status="failed")
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    token, _ = create_session(admin["id"])
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=get_settings().environment == "production",
        max_age=7 * 24 * 3600,
        path="/",
    )
    log_action("login", "auth", admin["id"], "登录成功", actor=admin)
    return {"admin": admin}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    actor = current_admin(request)
    destroy_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    log_action("logout", "auth", actor["id"], "退出登录", actor=actor)


@router.get("/me")
def me(request: Request) -> dict:
    return {"admin": current_admin(request)}


@router.get("/admins")
def admins(request: Request) -> list[dict]:
    current_admin(request)
    return list_admins()


@router.post("/admins", status_code=201)
def add_admin(payload: AdminCreate, request: Request) -> dict:
    actor = require_initial_admin(request)
    created = create_admin(payload.username, payload.password, actor["id"], payload.role, payload.dataset_ids)
    log_action(
        "create_user",
        "user",
        created["id"],
        f"创建账号 {created['username']}，角色 {created['role']}",
        actor=actor,
    )
    return created


@router.patch("/admins/{user_id}")
def edit_admin(user_id: int, payload: AdminUpdate, request: Request) -> dict:
    actor = require_initial_admin(request)
    updated = update_admin(user_id, payload.role, payload.dataset_ids)
    log_action(
        "update_user",
        "user",
        user_id,
        f"更新账号 {updated['username']}，角色 {updated['role']}",
        actor=actor,
    )
    return updated


@router.delete("/admins/{user_id}", status_code=204)
def remove_admin(user_id: int, request: Request) -> None:
    actor = require_initial_admin(request)
    delete_admin(user_id, actor["id"])
    log_action("delete_user", "user", user_id, "删除账号", actor=actor)
