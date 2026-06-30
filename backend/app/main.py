from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import initialize_database
from .routers import agent, audit, auth, datasets, knowledge, system
from .services.auth import SESSION_COOKIE, admin_from_session
from .services.vector_store import VectorStoreError, sync_knowledge


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    try:
        await sync_knowledge()
    except VectorStoreError:
        # 向量服务不可用时不阻止 API 启动，检索自动降级为关键词模式。
        pass
    yield


settings = get_settings()
app = FastAPI(
    title="DataAgent API",
    version="0.1.0",
    description="企业数据智能体服务系统 API",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


PUBLIC_PATHS = {
    "/",
    "/api/v1/health",
    "/api/v1/auth/login",
}


@app.middleware("http")
async def require_login(request, call_next):
    path = request.url.path
    if (
        request.method == "OPTIONS"
        or path in PUBLIC_PATHS
        or path.startswith("/docs")
        or path.startswith("/redoc")
        or path == "/openapi.json"
    ):
        return await call_next(request)
    if path.startswith("/api/v1"):
        admin = admin_from_session(request.cookies.get(SESSION_COOKIE))
        if not admin:
            return JSONResponse({"detail": "请先登录"}, status_code=401)
        request.state.admin = admin
    return await call_next(request)

app.include_router(system.router, prefix="/api/v1")
app.include_router(datasets.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")


@app.get("/")
def root() -> dict:
    return {"name": settings.app_name, "docs": "/docs", "health": "/api/v1/health"}
