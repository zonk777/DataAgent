"""MCP (Model Context Protocol) Server — JSON-RPC over HTTP.

Exposes internal DataAgent tools as discoverable MCP resources.
Clients call POST /mcp with JSON-RPC payloads:
  - initialize: handshake
  - tools/list: return tool schemas
  - tools/call: execute a tool
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from .tool_registry import TOOL_SCHEMAS, ToolExecutor

_server_instance: "McpServer | None" = None


class McpServer:
    """Stateless MCP protocol handler."""

    def __init__(self, executor: ToolExecutor | None = None):
        self.executor = executor or ToolExecutor(dataset_id=None)

    async def handle_request(self, body: dict) -> dict:
        """Process a JSON-RPC request. Returns JSON-RPC response."""
        req_id = body.get("id")
        method = body.get("method", "")

        try:
            if method == "initialize":
                return self._ok(req_id, {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "DataAgent MCP", "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                })

            if method == "tools/list":
                tools = [{"name": t["function"]["name"], "description": t["function"]["description"], "inputSchema": t["function"]["parameters"]} for t in TOOL_SCHEMAS]
                return self._ok(req_id, {"tools": tools})

            if method == "tools/call":
                params = body.get("params", {})
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                result = await self.executor.execute(tool_name, arguments)
                return self._ok(req_id, {"content": [{"type": "text", "text": str(result)}]})

            return self._error(req_id, -32601, f"未知方法: {method}")

        except Exception as exc:
            return self._error(req_id, -32603, f"{exc}\n{traceback.format_exc()[-500:]}")

    def _ok(self, req_id: Any, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _error(self, req_id: Any, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def get_mcp_server() -> McpServer:
    global _server_instance
    if _server_instance is None:
        _server_instance = McpServer()
    return _server_instance
