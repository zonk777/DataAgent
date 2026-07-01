"""MCP Client — discovers tools and executes them via JSON-RPC.

Used by the ReAct agent to dynamically discover available tools
instead of relying on hardcoded TOOL_SCHEMAS.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx


class McpClient:
    """Connects to an MCP server endpoint and provides tool discovery + execution."""

    def __init__(self, server_url: str = "http://127.0.0.1:8000/api/v1/mcp"):
        self.server_url = server_url
        self._tool_schemas: list[dict] | None = None
        self._session_id: str = str(uuid.uuid4())
        self._initialized = False

    async def initialize(self) -> dict:
        """Handshake with the MCP server."""
        resp = await self._rpc("initialize", {"clientInfo": {"name": "DataAgent-ReAct"}, "protocolVersion": "2024-11-05"})
        self._initialized = True
        return resp

    async def list_tools(self) -> list[dict]:
        """Discover available tools. Returns OpenAI-compatible function schemas."""
        resp = await self._rpc("tools/list")
        raw_tools = resp.get("tools", [])
        # Convert MCP format → OpenAI Function Calling format
        schemas = []
        for t in raw_tools:
            schemas.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                },
            })
        self._tool_schemas = schemas
        return schemas

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool and return its result as a string."""
        resp = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        content = resp.get("content", [])
        if content:
            return content[0].get("text", "") if isinstance(content[0], dict) else str(content[0])
        return json.dumps(resp, ensure_ascii=False)

    async def get_tool_schemas(self) -> list[dict]:
        """Get cached tool schemas, initializing if needed."""
        if not self._initialized:
            await self.initialize()
        if self._tool_schemas is None:
            await self.list_tools()
        return self._tool_schemas or []

    async def _rpc(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC request to the MCP server."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4())[:8],
            "method": method,
            "params": params or {},
        }
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                self.server_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        if "error" in data:
            raise RuntimeError(f"MCP error {data['error'].get('code')}: {data['error'].get('message')}")
        return data.get("result", {})
