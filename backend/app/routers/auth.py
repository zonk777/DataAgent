from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from ..models import AdminCreate, LoginRequest
from ..services.auth import (
    SESSION_COOKIE,
    authenticate,
    create_admin,
    create_session,
    current_admin,
    destroy_session,
    list_admins,
    require_initial_admin,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, response: Response) -> dict:
    admin = authenticate(payload.username, payload.password)
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    token, _ = create_session(admin["id"])
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    return {"admin": admin}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    destroy_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
def me(request: Request) -> dict:
    return {"admin": current_admin(request)}


@router.get("/admins")
def admins(request: Request) -> list[dict]:
    current_admin(request)
    return list_admins()


@router.post("/admins", status_code=201)
def add_admin(payload: AdminCreate, request: Request) -> dict:
    admin = require_initial_admin(request)
    return create_admin(payload.username, payload.password, admin["id"])
