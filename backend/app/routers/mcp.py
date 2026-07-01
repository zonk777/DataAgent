"""MCP JSON-RPC endpoint — POST /api/v1/mcp"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..services.mcp_server import get_mcp_server

router = APIRouter(tags=["mcp"])


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    body = await request.json()
    server = get_mcp_server()
    result = await server.handle_request(body)
    return JSONResponse(content=result)
