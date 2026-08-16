from types import SimpleNamespace
import asyncio

import pytest
from mcp.types import Tool

from src.tools.mcp.adapter import McpAdapter, McpConnection, _extract_text
from src.tools.mcp.config import McpConfig, McpServerConfig
from src.tools.mcp.transport import (
    StdioTransport,
    StreamableHttpTransport,
    build_transport,
)


# ── Task 3: 传输层 ──

def test_build_transport_dispatch():
    assert isinstance(
        build_transport(McpServerConfig(name="x", transport="stdio", command="python")),
        StdioTransport,
    )
    assert isinstance(
        build_transport(McpServerConfig(name="x", transport="streamable-http", url="http://x")),
        StreamableHttpTransport,
    )


def test_http_transport_requires_url():
    with pytest.raises(ValueError):
        build_transport(McpServerConfig(name="x", transport="streamable-http"))


# ── Task 4: 连接管理 + 熔断 ──

class _FakeSession:
    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("boom")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")])


def test_extract_text():
    result = SimpleNamespace(content=[
        SimpleNamespace(type="text", text="hello"),
        SimpleNamespace(type="image", text=None),
        SimpleNamespace(type="text", text="world"),
    ])
    assert _extract_text(result) == "hello\nworld"


@pytest.mark.asyncio
async def test_call_succeeds():
    conn = McpConnection(McpServerConfig(name="k", transport="stdio", command="python"))
    conn._session = _FakeSession()
    conn.available = True
    assert await conn.call("search", {"q": "x"}) == "ok"


@pytest.mark.asyncio
async def test_call_circuit_breaker_opens_after_3_failures():
    conn = McpConnection(McpServerConfig(name="k", transport="stdio", command="python"))
    conn._session = _FakeSession(fail_times=99)
    conn.available = True
    for _ in range(3):
        await conn.call("search", {"q": "x"})
    assert conn.available is False
    # 熔断后调用直接返回错误文本，不再抛异常
    assert "不可用" in await conn.call("search", {"q": "x"})


@pytest.mark.asyncio
async def test_call_returns_error_text_when_unavailable():
    conn = McpConnection(McpServerConfig(name="k", transport="stdio", command="python"))
    conn.available = False
    assert "不可用" in await conn.call("search", {})


# ── Task 5: 发现编排 ──

class _FakeMcpConnection:
    def __init__(self, cfg):
        self.cfg = cfg
        self.available = True

    async def connect(self):
        pass

    async def list_tools(self):
        return [
            Tool(name="search", description="s",
                 input_schema={"type": "object", "properties": {}}),
            Tool(name="delete", description="d",
                 input_schema={"type": "object", "properties": {}}),
        ]

    async def call(self, name, args):
        return "x"

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_discover_namespaces_and_whitelist(monkeypatch):
    monkeypatch.setattr("src.tools.mcp.adapter.McpConnection", _FakeMcpConnection)
    cfg = McpConfig(enabled=True, servers=[
        McpServerConfig(name="knowledge", transport="stdio",
                        command="python", allowed_tools=["search"]),
    ])
    tools, metas = await McpAdapter(cfg).discover()
    assert [t.name for t in tools] == ["knowledge_search"]   # 白名单过滤掉 delete
    assert metas["knowledge_search"]["category"] == "mcp"
    assert metas["knowledge_search"]["tags"] == ["mcp", "knowledge"]


@pytest.mark.asyncio
async def test_discover_disabled_returns_empty():
    tools, metas = await McpAdapter(McpConfig(enabled=False)).discover()
    assert tools == [] and metas == {}


@pytest.mark.asyncio
async def test_discover_times_out_and_closes_partial_connection(monkeypatch):
    class SlowConnection(_FakeMcpConnection):
        closed = False

        async def connect(self):
            await asyncio.sleep(1)

        async def close(self):
            self.__class__.closed = True

    monkeypatch.setattr("src.tools.mcp.adapter.McpConnection", SlowConnection)
    cfg = McpConfig(enabled=True, servers=[
        McpServerConfig(
            name="slow",
            transport="stdio",
            command="python",
            timeout_seconds=0.01,
        ),
    ])

    adapter = McpAdapter(cfg)
    tools, metas = await adapter.discover()

    assert tools == [] and metas == {}
    assert adapter.server_statuses["slow"]["status"] == "error"
    assert SlowConnection.closed is True
