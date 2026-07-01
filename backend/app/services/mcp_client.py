"""MCP Client — discovers tools from multiple MCP servers via JSON-RPC.

Phase 4: Multi-server support with deduplication and fallback.
All internal tools use ToolExecutor directly (no HTTP overhead),
external tools discovered via MCP protocol from configured servers.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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


class MultiMcpClient:
    """Phase 4: Aggregates tools from multiple MCP servers with dedup and fallback."""

    def __init__(self, server_urls: list[str] | None = None):
        self.clients: list[McpClient] = [McpClient(url) for url in (server_urls or [])]

    def add_server(self, url: str) -> None:
        if not any(c.server_url == url for c in self.clients):
            self.clients.append(McpClient(url))

    async def get_tool_schemas(self) -> list[dict]:
        """Discover tools from all servers, deduplicate by name."""
        all_tools: list[dict] = []
        seen: set[str] = set()
        for client in self.clients:
            try:
                tools = await client.get_tool_schemas()
                for t in tools:
                    name = t.get("function", {}).get("name", "")
                    if name and name not in seen:
                        seen.add(name)
                        all_tools.append(t)
            except Exception as exc:
                logger.warning("MCP server %s unavailable: %s", client.server_url, exc)
        return all_tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Execute a tool on the first available server that has it."""
        for client in self.clients:
            try:
                schemas = await client.get_tool_schemas()
                if any(t.get("function", {}).get("name") == name for t in schemas):
                    return await client.call_tool(name, arguments)
            except Exception:
                continue
        raise RuntimeError(f"No MCP server available for tool: {name}")


def get_mcp_servers() -> list[str]:
    """Parse MCP_SERVERS from config (comma-separated URLs)."""
    from ..config import get_settings
    raw = get_settings().mcp_servers.strip()
    if not raw:
        return []
    return [url.strip() for url in raw.split(",") if url.strip()]
