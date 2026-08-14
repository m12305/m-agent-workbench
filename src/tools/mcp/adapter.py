"""MCP 连接管理、工具发现与熔断。"""
import asyncio
import logging
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.types import Tool
from langchain_core.tools import BaseTool

from .config import McpConfig, McpServerConfig
from .transport import build_transport
from .convert import to_langchain_tool

logger = logging.getLogger(__name__)


def _extract_text(result) -> str:
    parts = []
    for block in getattr(result, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "\n".join(parts)


class McpConnection:
    """单个 MCP Server 的连接与调用封装，含熔断。"""

    def __init__(self, cfg: McpServerConfig):
        self.cfg = cfg
        self._transport = build_transport(cfg)
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
        self.available = False
        self._failures = 0

    async def connect(self):
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(self._transport.open())
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        # v2: initialize() 用于自动向下协商；纯无状态服务器可改用 discover()/adopt()
        await self._session.initialize()
        self.available = True

    async def list_tools(self) -> list[Tool]:
        result = await self._session.list_tools()
        return list(result.tools)

    async def call(self, tool_name: str, arguments: dict) -> str:
        if not self.available:
            return f"[MCP] 服务器 {self.cfg.name} 当前不可用"
        try:
            async with asyncio.timeout(self.cfg.timeout_seconds):
                result = await self._session.call_tool(tool_name, arguments)
            self._failures = 0
            return _extract_text(result)
        except Exception as e:
            self._failures += 1
            if self._failures >= 3:
                self.available = False
            return f"[MCP] 工具调用失败: {e}"

    async def close(self):
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None
            self.available = False


def _allowed(allowed: list[str], name: str) -> bool:
    return "*" in allowed or name in allowed


class McpAdapter:
    """编排多个 MCP Server：连接、发现工具、转换为内部工具描述。"""

    def __init__(self, config: McpConfig):
        self.config = config
        self._connections: list[McpConnection] = []

    async def discover(self) -> tuple[list[BaseTool], dict[str, dict]]:
        if not self.config.enabled:
            return [], {}
        tools: list[BaseTool] = []
        metas: dict[str, dict] = {}
        for server_cfg in self.config.servers:
            conn = McpConnection(server_cfg)
            try:
                await conn.connect()
            except Exception as e:
                logger.warning("MCP '%s' 连接失败，已跳过: %s", server_cfg.name, e)
                continue
            self._connections.append(conn)
            try:
                for t in await conn.list_tools():
                    if not _allowed(server_cfg.allowed_tools, t.name):
                        continue
                    tool = to_langchain_tool(conn, t)
                    tools.append(tool)
                    metas[tool.name] = {"category": "mcp",
                                        "tags": ["mcp", server_cfg.name],
                                        "version": "1.0.0",
                                        "subagents": server_cfg.subagents}
            except Exception as e:
                logger.warning("MCP '%s' 工具发现失败: %s", server_cfg.name, e)
        return tools, metas

    async def close(self):
        for conn in self._connections:
            await conn.close()
        self._connections = []
