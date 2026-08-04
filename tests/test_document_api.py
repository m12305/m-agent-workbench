"""文档 API 集成测试"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
#from conftest import client, user_headers, admin_headers


# conftest.py 会在测试模块导入前加载
os.environ["ADMIN_API_KEYS"] = "sk-test-admin"
os.environ["USER_API_KEYS"] = "sk-test-user"


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from src.server.main import app

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as async_client:
            yield async_client


@pytest.fixture
def user_headers() -> dict[str, str]:
    return {"Authorization": "Bearer sk-test-user"}


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer sk-test-admin"}

@pytest.mark.asyncio
async def test_upload_txt(
    client: AsyncClient,
    user_headers: dict[str, str],
):
    resp = await client.post(
        "/api/v1/documents",
        files={
            "file": (
                "test.txt",
                b"Hello World\n\nTest content.",
                "text/plain",
            )
        },
        data={"scope": "private"},
        headers=user_headers,
    )

    assert resp.status_code == 201

    data = resp.json()
    assert data["status"] == "queued"
    assert "task_id" in data
    assert "document_id" in data


@pytest.mark.asyncio
async def test_upload_invalid_extension(
    client: AsyncClient,
    user_headers: dict[str, str],
):
    resp = await client.post(
        "/api/v1/documents",
        files={
            "file": (
                "test.exe",
                b"malware",
                "application/octet-stream",
            )
        },
        headers=user_headers,
    )

    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_list_documents(
    client: AsyncClient,
    user_headers: dict[str, str],
):
    create_resp = await client.post(
        "/api/v1/documents",
        files={
            "file": (
                "doc.txt",
                b"content",
                "text/plain",
            )
        },
        headers=user_headers,
    )

    assert create_resp.status_code == 201

    resp = await client.get(
        "/api/v1/documents",
        headers=user_headers,
    )

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_document(
    client: AsyncClient,
    user_headers: dict[str, str],
):
    create_resp = await client.post(
        "/api/v1/documents",
        files={
            "file": (
                "doc.txt",
                b"content",
                "text/plain",
            )
        },
        headers=user_headers,
    )

    assert create_resp.status_code == 201
    doc_id = create_resp.json()["document_id"]

    resp = await client.get(
        f"/api/v1/documents/{doc_id}",
        headers=user_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["document_id"] == doc_id


@pytest.mark.asyncio
async def test_delete_document(
    client: AsyncClient,
    user_headers: dict[str, str],
):
    create_resp = await client.post(
        "/api/v1/documents",
        files={
            "file": (
                "doc.txt",
                b"content",
                "text/plain",
            )
        },
        headers=user_headers,
    )

    assert create_resp.status_code == 201
    doc_id = create_resp.json()["document_id"]

    resp = await client.delete(
        f"/api/v1/documents/{doc_id}",
        headers=user_headers,
    )

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_user_isolation(
    client: AsyncClient,
    user_headers: dict[str, str],
    admin_headers: dict[str, str],
):
    """user A 的文档 user B 看不到"""
    create_resp = await client.post(
        "/api/v1/documents",
        files={
            "file": (
                "secret.txt",
                b"secret",
                "text/plain",
            )
        },
        headers=user_headers,
    )

    assert create_resp.status_code == 201
    doc_id = create_resp.json()["document_id"]

    resp = await client.get(
        f"/api/v1/documents/{doc_id}",
        headers=admin_headers,
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_task_query(
    client: AsyncClient,
    user_headers: dict[str, str],
):
    create_resp = await client.post(
        "/api/v1/documents",
        files={
            "file": (
                "doc.txt",
                b"content",
                "text/plain",
            )
        },
        headers=user_headers,
    )

    assert create_resp.status_code == 201
    task_id = create_resp.json()["task_id"]

    await asyncio.sleep(0.5)

    resp = await client.get(
        f"/api/v1/tasks/{task_id}",
        headers=user_headers,
    )

    assert resp.status_code == 200

    data = resp.json()
    assert data["status"] in {
        "queued",
        "parsing",
        "chunking",
        "done",
        "failed",
    }


@pytest.mark.asyncio
async def test_task_not_found(
    client: AsyncClient,
    user_headers: dict[str, str],
):
    resp = await client.get(
        "/api/v1/tasks/nonexistent",
        headers=user_headers,
    )

    assert resp.status_code == 404