"""FastAPI 集成测试 — 使用持久化动态 Key"""

import pytest
from httpx import AsyncClient


# ═══════════════════════════════════════════════════════════════
# 健康检查 (无认证)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_health_live(client: AsyncClient):
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_health_ready(client: AsyncClient):
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ═══════════════════════════════════════════════════════════════
# 认证
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_no_auth_returns_401(client: AsyncClient):
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_invalid_key_returns_401(client: AsyncClient):
    resp = await client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer sk-invalid"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_admin_key_works(client: AsyncClient, admin_headers):
    resp = await client.get("/api/v1/me", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_valid_user_key_works(client: AsyncClient, user_headers):
    resp = await client.get("/api/v1/me", headers=user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "user"


# ═══════════════════════════════════════════════════════════════
# 会话
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_session(client: AsyncClient, user_headers):
    resp = await client.post(
        "/api/v1/sessions",
        json={"title": "测试会话"},
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "session_id" in data
    assert data["title"] == "测试会话"
    assert data["message_count"] == 0


@pytest.mark.asyncio
async def test_list_sessions(client: AsyncClient, user_headers):
    # 先创建一个
    await client.post("/api/v1/sessions", json={}, headers=user_headers)
    resp = await client.get("/api/v1/sessions", headers=user_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_regular_user_can_rename_own_session(
    client: AsyncClient, user_headers,
):
    resp = await client.post(
        "/api/v1/sessions",
        json={"title": "旧标题"},
        headers=user_headers,
    )
    session_id = resp.json()["session_id"]

    resp = await client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "新标题"},
        headers=user_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["title"] == "新标题"


@pytest.mark.asyncio
async def test_cannot_rename_another_users_session(
    client: AsyncClient, user_headers, admin_headers,
):
    resp = await client.post(
        "/api/v1/sessions",
        json={"title": "用户会话"},
        headers=user_headers,
    )
    session_id = resp.json()["session_id"]

    resp = await client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "越权修改"},
        headers=admin_headers,
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_session(client: AsyncClient, user_headers):
    resp = await client.post("/api/v1/sessions", json={}, headers=user_headers)
    session_id = resp.json()["session_id"]

    resp = await client.delete(
        f"/api/v1/sessions/{session_id}",
        headers=user_headers,
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_cannot_access_other_user_session(
    client: AsyncClient, user_headers, admin_headers,
):
    """验证用户隔离: user 创建会话, admin 不能访问"""
    # user 创建会话
    resp = await client.post(
        "/api/v1/sessions", json={}, headers=user_headers,
    )
    session_id = resp.json()["session_id"]

    # 另一个用户 (admin) 尝试访问 → 应返回 404 (不暴露存在性)
    resp = await client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=admin_headers,
    )
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# 问答 (fallback 模式 — 无外部 LLM)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_chat_sync(client: AsyncClient, user_headers):
    """同步问答 — 在无 API Key 时使用 fallback 模式"""
    resp = await client.post(
        "/api/v1/chat",
        json={"query": "你好"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "session_id" in data


@pytest.mark.asyncio
async def test_chat_with_existing_session(
    client: AsyncClient, user_headers,
):
    """在已有会话中问答"""
    # 创建会话
    resp = await client.post(
        "/api/v1/sessions", json={"title": "Chat"},
        headers=user_headers,
    )
    session_id = resp.json()["session_id"]

    # 在该会话中问答
    resp = await client.post(
        "/api/v1/chat",
        json={"query": "你好", "session_id": session_id},
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id


@pytest.mark.asyncio
async def test_chat_stream(client: AsyncClient, user_headers):
    """SSE 流式问答 — 验证事件类型"""
    resp = await client.post(
        "/api/v1/chat/stream",
        json={"query": "你好"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    # 解析 SSE 事件
    import json
    events = []
    current_event = None
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: ") and current_event:
            data = json.loads(line[6:])
            events.append((current_event, data))
            current_event = None

    # 验证事件顺序: start → token* → done
    assert len(events) >= 2
    assert events[0][0] == "start"
    assert events[-1][0] == "done"


@pytest.mark.asyncio
async def test_chat_query_too_long(client: AsyncClient, user_headers):
    """验证 query 长度限制"""
    resp = await client.post(
        "/api/v1/chat",
        json={"query": "x" * 5000},
        headers=user_headers,
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════
# 用户管理 (admin only)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_admin_can_create_user(client: AsyncClient, admin_headers):
    resp = await client.post(
        "/api/v1/users",
        json={"name": "Test User", "role": "user"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test User"
    assert data["role"] == "user"


@pytest.mark.asyncio
async def test_key_created_for_admin_member_has_admin_permissions(
    client: AsyncClient,
    admin_headers,
):
    """管理员成员的新 Key 应能继续访问管理员接口。"""
    create_user_resp = await client.post(
        "/api/v1/users",
        json={"name": "Second Admin", "role": "admin"},
        headers=admin_headers,
    )
    assert create_user_resp.status_code == 201

    create_key_resp = await client.post(
        "/api/v1/api-keys",
        json={"user_id": create_user_resp.json()["user_id"]},
        headers=admin_headers,
    )
    assert create_key_resp.status_code == 201

    new_admin_headers = {
        "Authorization": f"Bearer {create_key_resp.json()['key']}"
    }
    list_users_resp = await client.get(
        "/api/v1/users",
        headers=new_admin_headers,
    )
    assert list_users_resp.status_code == 200


@pytest.mark.asyncio
async def test_user_cannot_create_user(client: AsyncClient, user_headers):
    """普通用户不能创建用户"""
    resp = await client.post(
        "/api/v1/users",
        json={"name": "Hacker", "role": "admin"},
        headers=user_headers,
    )
    assert resp.status_code == 403
